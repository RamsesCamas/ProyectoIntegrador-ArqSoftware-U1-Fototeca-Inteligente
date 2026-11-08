"""C3 · Una prueba por verificación de guardrails (docs/specs/06; aceptación de H5).

Cuando existe el conjunto correspondiente en `evaluacion/conjuntos/` (montado en `/app/evaluacion_datos`), se usan
sus casos reales; si no está (clon sin datos), esas pruebas se saltan. `archivo_valido` y `exif_privacidad` con
imágenes sintéticas están en `test_guardrails_entrada.py`; aquí `exif_privacidad` se repite con las fotos de
`gps_sintetico` cuando están materializadas en `data/`.
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from fototeca.contexto.tesauro import Tesauro
from fototeca.dominio import colecciones as col
from fototeca.dominio.errores import BloqueadoPorGuardrail
from fototeca.dominio.esquemas_ficha import Ficha
from fototeca.guardrails.entrada.exif import detectar, sanitizar
from fototeca.guardrails.entrada.imagen import VerificadorImagen
from fototeca.guardrails.entrada.texto import sanitizar_pii, verificar_inyeccion
from fototeca.guardrails.politicas import MENSAJES_SEGUROS
from fototeca.guardrails.salida.reglas import (aplicar_reglas_iptc, recortar_longitudes, verificar_esquema,
                                              verificar_fuentes)
from fototeca.guardrails.salida.semanticas import GuardrailsSemanticos
from pruebas.falsos import AlmacenVectorialFalso, EmbebedorFalso

EVAL = Path(os.environ.get("FOTOTECA_EVAL", "/app/evaluacion_datos"))
DATA = Path(os.environ.get("FOTOTECA_DATA", "/app/data"))


def conjunto(nombre: str) -> dict:
    ruta = EVAL / "conjuntos" / f"{nombre}.json"
    if not ruta.exists():
        pytest.skip(f"no está el conjunto {nombre} (se genera en H2)")
    return json.loads(ruta.read_text(encoding="utf-8"))


def unitario(i: int, n: int = 16) -> np.ndarray:
    v = np.zeros(n, np.float32)
    v[i] = 1.0
    return v


def config_con(config, **guardrails):
    parametros = copy.deepcopy(config.parametros)
    parametros.setdefault("guardrails", {}).update(guardrails)
    return replace(config, parametros=parametros)


# ───────────────────────────── entrada: texto de búsqueda ─────────────────────────────
def test_pii_texto_enmascara_los_casos_del_conjunto():
    for it in [x for x in conjunto("consultas_guardrail")["items"] if x["tipo"] == "pii"]:
        limpio, r = sanitizar_pii(it["texto"])
        assert r.resultado == "sanitizado", it
        assert limpio != it["texto"] and "[" in limpio
        assert r.politica_aplicada


def test_pii_texto_no_toca_consultas_normales():
    for it in [x for x in conjunto("consultas_guardrail")["items"] if x["tipo"] == "normal"]:
        limpio, r = sanitizar_pii(it["texto"])
        assert r.resultado == "aprobada" and limpio == it["texto"], it


def test_inyeccion_texto_bloquea_con_mensaje_seguro_sin_repetir_el_contenido():
    for it in [x for x in conjunto("consultas_guardrail")["items"] if x["tipo"] == "inyeccion"]:
        with pytest.raises(BloqueadoPorGuardrail) as e:
            verificar_inyeccion(it["texto"], None, None, umbral=1.0)   # solo la heurística de patrones
        assert e.value.mensaje_seguro == MENSAJES_SEGUROS["inyeccion_texto"]
        assert it["texto"] not in e.value.mensaje_seguro


def test_inyeccion_texto_aprueba_consultas_normales():
    for it in [x for x in conjunto("consultas_guardrail")["items"] if x["tipo"] == "normal"]:
        r = verificar_inyeccion(it["texto"], None, None, umbral=1.0)
        assert r.resultado == "aprobada", it


def test_inyeccion_texto_por_similitud_con_prototipos():
    prototipos = np.stack([unitario(0), unitario(1)])
    with pytest.raises(BloqueadoPorGuardrail):
        verificar_inyeccion("fotos de playas", unitario(0), prototipos, umbral=0.9)
    assert verificar_inyeccion("fotos de playas", unitario(5), prototipos, umbral=0.9).resultado == "aprobada"


# ───────────────────────────── entrada: imagen ─────────────────────────────
def _verificador(config, **umbrales) -> VerificadorImagen:
    vec = AlmacenVectorialFalso()
    filas = [("dominio", "fotografia", 0), ("dominio", "fuera_de_dominio", 1),
             ("texto_visible", "con_texto", 2), ("texto_visible", "sin_texto", 3)]
    for i, (tipo, clase, eje) in enumerate(filas):
        vec.insertar(col.PROTOTIPOS, [f"proto:{tipo}:{clase}:{i}"], [unitario(eje)], [{"tipo": tipo, "clase": clase}])
    return VerificadorImagen(config_con(config, **umbrales), vec, EmbebedorFalso())


def test_fuera_de_dominio_bloquea_con_mensaje_seguro_cuando_esta_calibrado(config):
    ver = _verificador(config, tau_fuera_dominio=0.0)
    with pytest.raises(BloqueadoPorGuardrail) as e:
        ver.fuera_de_dominio(unitario(1))          # más parecida a «documento/tabla/interfaz»
    assert e.value.mensaje_seguro == MENSAJES_SEGUROS["fuera_de_dominio"]
    assert ver.fuera_de_dominio(unitario(0)).resultado == "aprobada"


def test_fuera_de_dominio_sin_calibrar_no_bloquea_a_ciegas(config):
    r = _verificador(config, tau_fuera_dominio=None).fuera_de_dominio(unitario(1))
    assert r.resultado == "aprobada" and "sin calibrar" in r.detalle["nota"]


def test_texto_visible_marca_para_la_ruta_completa(config):
    ver = _verificador(config, tau_texto_visible=0.0)
    assert ver.texto_visible(unitario(2)).resultado == "marcada"
    assert ver.texto_visible(unitario(3)).resultado == "aprobada"


def test_inyeccion_en_imagen_marca_y_no_bloquea_con_los_textos_del_conjunto(config):
    ver = _verificador(config)
    for it in conjunto("inyeccion_imagen")["items"]:
        r = ver.inyeccion_en_texto_visible([it["texto"]])
        assert r.resultado == "marcada", it          # se aísla y se marca; la foto NO se bloquea
        assert r.politica_aplicada


def test_inyeccion_en_imagen_no_marca_letreros_benignos(config):
    ver = _verificador(config)
    falsos = [it["texto"] for it in conjunto("texto_benigno_imagen")["items"]
              if ver.inyeccion_en_texto_visible([it["texto"]]).resultado == "marcada"]
    assert not falsos


def test_exif_privacidad_con_las_fotos_de_gps_sintetico():
    items = conjunto("gps_sintetico")["items"]
    rutas = [DATA / it["archivo"] for it in items]
    if not all(r.exists() for r in rutas):
        pytest.skip("las fotos de gps_sintetico no están materializadas en data/")
    for ruta in rutas:
        original = ruta.read_bytes()
        assert detectar(original)["gps"] is True
        limpio, r = sanitizar(original)
        assert r.resultado == "sanitizado"
        assert detectar(limpio)["gps"] is False


# ───────────────────────────── salida de la ficha ─────────────────────────────
def test_esquema_valida_y_rechaza():
    ficha, r = verificar_esquema({"titular": "Mercado", "texto_alternativo": "Puesto de frutas."})
    assert ficha is not None and r.resultado == "aprobada"
    ficha, r = verificar_esquema({"titular": 5, "texto_alternativo": ["no"]})
    assert ficha is None and r.resultado != "aprobada"


def test_reglas_iptc_recorta_por_oracion_antes_del_esquema_y_normaliza_el_inicio():
    largo = "Puesto de frutas con mangos y piñas. " * 12
    datos, recortes = recortar_longitudes({"titular": "Mercado " * 20, "texto_alternativo": "Imagen de " + largo})
    assert set(recortes) == {"alt_recortado", "titular_recortado"}
    ficha, r = verificar_esquema(datos)
    assert ficha is not None and r.resultado == "aprobada"      # un texto largo no provoca un reintento
    ficha, r = aplicar_reglas_iptc(ficha, recortes)
    assert r.resultado == "sanitizado" and {"alt_recortado", "inicio_normalizado"} <= set(r.detalle["cambios"])
    assert len(ficha.texto_alternativo) <= 250 and ficha.texto_alternativo.endswith(".")
    assert not ficha.texto_alternativo.lower().startswith("imagen de")
    assert len(ficha.titular) <= 120


def test_reglas_iptc_marca_alt_vacio_para_reintentar():
    _, r = aplicar_reglas_iptc(Ficha(titular="T", texto_alternativo="   "))
    assert r.resultado == "marcada" and r.politica_aplicada == "reintentar"


def _semanticos(config, **umbrales) -> GuardrailsSemanticos:
    cfg = config_con(config, **umbrales)
    emb = EmbebedorFalso()
    return GuardrailsSemanticos(cfg, emb, EmbebedorFalso("granite", acepta_imagenes=False),
                                Tesauro(AlmacenVectorialFalso(), emb), gateway=None)


def test_apego_visual_marca_bajo_el_umbral(config):
    g = _semanticos(config, tau_apego_visual=0.99)
    v = EmbebedorFalso().embeber_textos(["otra cosa"], rol="consulta")[0]
    assert g.apego_visual(v, "Puesto de frutas").resultado == "marcada"
    v_mismo = EmbebedorFalso().embeber_textos(["Puesto de frutas"], rol="consulta")[0]
    assert g.apego_visual(v_mismo, "Puesto de frutas").resultado == "aprobada"


def test_consistencia_marca_textos_que_no_coinciden(config):
    g = _semanticos(config, tau_consistencia=0.99)
    assert g.consistencia("Puesto de frutas", "Una montaña nevada").resultado == "marcada"
    assert g.consistencia("Puesto de frutas", "Puesto de frutas").resultado == "aprobada"
    assert g.consistencia("Puesto de frutas", None) is None      # sin P1 (ruta rápida) no aplica


def test_atributos_sensibles_elimina_la_frase(config):
    g = _semanticos(config)
    ficha = Ficha(titular="Mercado", texto_alternativo="Puesto de frutas. Una mujer indígena de religión católica vende.",
                  descripcion="Puesto de frutas al aire libre.")
    limpia, r = g.atributos_sensibles(ficha)
    assert r.resultado == "sanitizado"
    assert "indígena" not in limpia.texto_alternativo and "Puesto de frutas." in limpia.texto_alternativo


def test_tesauro_normaliza_sobre_el_umbral_y_deja_libres(config):
    vec, emb = AlmacenVectorialFalso(), EmbebedorFalso()
    vec.insertar(col.TESAURO, ["tesauro:u:mercados"], emb.embeber_textos(["mercados"], rol="consulta"),
                 [{"uri": "u:mercados", "etiqueta_es": "Mercados"}])
    g = GuardrailsSemanticos(config_con(config, tau_tesauro=0.9), emb, EmbebedorFalso("granite", acepta_imagenes=False),
                             Tesauro(vec, emb), gateway=None)
    palabras, r = g.normalizar_palabras(["mercados", "piñatas"])
    origenes = {p.termino: p.origen for p in palabras}
    assert origenes.get("Mercados") == "tesauro" and origenes.get("piñatas") == "libre"
    assert r.resultado == "sanitizado"


def test_fuentes_quita_las_invalidas_y_marca_campos_sin_fuente():
    validos = {"foto:xm-a", "regla:iptc#alt"}
    limpias, r = verificar_fuentes({"titular": ["foto:xm-a", "foto:inventada"], "texto_alternativo": ["regla:no-existe"]},
                                   validos, campos=("titular", "texto_alternativo"))
    assert limpias == {"titular": ["foto:xm-a"]}
    assert r.resultado == "marcada" and "texto_alternativo" in r.detalle["campos_sin_fuente"]
    limpias, r = verificar_fuentes({"titular": ["foto:xm-a"], "texto_alternativo": ["regla:iptc#alt", "x"]}, validos,
                                   campos=("titular", "texto_alternativo"))
    assert r.resultado == "sanitizado" and r.detalle["invalidas_quitadas"] == 1


# ───────────────────────────── salida de la búsqueda ─────────────────────────────
def test_salida_de_busqueda_sin_campos_internos_y_con_aviso(cliente_api):
    from pruebas.conftest import imagen_bytes
    cliente_api.post("/documentos", data={"tipo": "foto"},
                     files=[("archivos", ("f.jpg", imagen_bytes(), "image/jpeg"))])
    r = cliente_api.post("/busquedas", json={"texto": "mercado con frutas"})
    cuerpo = json.dumps(r.json(), ensure_ascii=False).lower()
    for prohibido in ("ruta_relativa", "sha256", "gps", "exif", "/app/"):
        assert prohibido not in cuerpo, prohibido
    assert r.json()["meta"]["aviso"]
