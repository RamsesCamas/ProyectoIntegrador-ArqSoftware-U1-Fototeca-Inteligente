"""C2 · Máquina de estados de la ficha con adaptadores falsos (sin modelos reales)."""
from __future__ import annotations

import copy
import io
import json
from dataclasses import replace

import pytest
from PIL import Image

from fototeca.cache.cache_fichas import CacheFichas
from fototeca.datos.cache_sqlite import CacheSqlite
from fototeca.datos.documentos_sqlite import DocumentosSqlite
from fototeca.dominio import colecciones as col
from fototeca.dominio.errores import TiempoAgotado
from fototeca.dominio.esquemas_ficha import Ficha, FichaRegistrada, PalabraClave
from fototeca.guardrails.entrada.imagen import VerificadorImagen
from fototeca.modelos.gateway import Gateway
from fototeca.modelos.plantillas import cargar_plantillas
from fototeca.orquestacion.flujo_ficha import FlujoFicha, OpcionesFicha
from pruebas.falsos import AlmacenVectorialFalso, EmbebedorFalso
from pruebas.test_gateway import ClienteGuionado

P1 = {"tipo": "fotografia", "descripcion_visual": "Un puesto de frutas con mangos bajo un toldo azul.",
      "elementos": ["puesto", "mangos", "toldo"], "texto_visible": [],
      "personas": {"hay_personas": False, "cantidad": "0"}, "escena": "exterior"}


def imagen(color, tam=(240, 180), franjas=4) -> bytes:
    im = Image.new("RGB", tam, color)
    px = im.load()
    for x in range(tam[0]):
        for y in range(0, tam[1], franjas):
            px[x, y] = (x % 256, (x * 2) % 256, color[2])
    buf = io.BytesIO()
    im.save(buf, "JPEG")
    return buf.getvalue()


def p3(fuentes=None, alt="Puesto de frutas con mangos bajo un toldo azul.") -> str:
    return json.dumps({"titular": "Puesto de frutas", "descripcion": "Un puesto de frutas con mangos.",
                       "texto_alternativo": alt, "descripcion_extendida": "", "palabras_clave": ["mercados", "frutas"],
                       "advertencias": [], "fuentes": fuentes or {"texto_alternativo": ["regla:iptc#alt"],
                                                                 "titular": ["foto:xm-a"], "descripcion": ["foto:xm-a"]}})


@pytest.fixture
def entorno(config, tmp_path):
    parametros = copy.deepcopy(config.parametros)
    parametros.setdefault("enrutador_fichas", {})["tau_consenso"] = 0.0
    parametros["enrutador_fichas"]["tau_acuerdo"] = 0.0
    parametros["gateway"]["espera_reintento_s"] = 0
    cfg = replace(config, parametros=parametros, modo_evaluacion=True)
    docs = DocumentosSqlite(cfg.rutas["sqlite"], cfg.rutas["fotos"], cfg.rutas["datos"])
    vec, emb = AlmacenVectorialFalso(), EmbebedorFalso()
    # Archivo: 3 fotos con ficha validada
    for i, color in enumerate([(200, 60, 40), (190, 70, 50), (40, 60, 200)]):
        d = f"xm-{'abc'[i]}"
        contenido = imagen(color)
        docs.guardar_foto(contenido, {"documento_id": d, "particion": "archivo"})
        ficha = Ficha(titular=f"Foto {i}", descripcion="Mercado de frutas", texto_alternativo="Puesto de mercado",
                      palabras_clave=[PalabraClave(termino="Mercados", uri="u:mercados", origen="tesauro")], estado="validada")
        docs.guardar_ficha(d, FichaRegistrada(documento_id=d, ficha=ficha, origen="referencia_humana"))
        vec.insertar(col.FOTOS_IMG, [d], emb.embeber_imagenes([contenido]), [{"documento_id": d, "validada": True}])
        vec.insertar(col.FOTOS_TXT, [f"{d}#descripcion"], emb.embeber_textos(["Mercado de frutas"]),
                     [{"documento_id": d, "validada": True, "campo": "descripcion"}])
    vec.insertar(col.NORMAS, ["iptc#alt"], emb.embeber_textos(["Alt text ≤250"]), [{"texto": "Alt text ≤250", "seccion": "Alt Text"}])
    vec.insertar(col.TESAURO, ["tesauro:u:mercados"], emb.embeber_textos(["mercados"]), [{"uri": "u:mercados", "etiqueta_es": "Mercados"}])
    nueva = docs.guardar_foto(imagen((210, 50, 45), tam=(260, 190)), {"nombre": "nueva.jpg"})

    def flujo(guion: dict) -> tuple[FlujoFicha, ClienteGuionado]:
        cliente = ClienteGuionado(guion)
        gw = Gateway(cliente, cfg, cargar_plantillas())
        cache = CacheFichas(cfg, CacheSqlite(cfg.rutas["sqlite"]), vec, docs)
        return FlujoFicha(cfg, docs, vec, emb, EmbebedorFalso("granite", acepta_imagenes=False), gw, cache,
                          VerificadorImagen(cfg, vec, emb), lambda: "v1"), cliente

    return {"cfg": cfg, "docs": docs, "vec": vec, "nueva": nueva, "flujo": flujo}


def test_ruta_completa_con_fuentes_y_meta(entorno):
    cfg = entorno["cfg"]
    f, cliente = entorno["flujo"]({cfg.modelos["vision"]: [json.dumps(P1)], cfg.modelos["composicion"]: [p3()]})
    r = f.ejecutar(entorno["nueva"], OpcionesFicha(forzar_ruta="completa", sin_cache=True))
    assert r["meta"]["ruta"] == "completa" and r["ficha"]["texto_alternativo"].startswith("Puesto")
    assert {"vision", "composicion", "embedding"} <= set(r["meta"]["modelos"])
    assert r["fuentes"]["texto_alternativo"][0]["tipo"] == "regla"
    assert r["fuentes"]["titular"][0]["tipo"] == "foto_similar"
    assert any(p["origen"] == "tesauro" for p in r["ficha"]["palabras_clave"])
    for clave in ("ruta", "modelos", "cache", "guardrails", "iteraciones_agente", "duplicado_de", "tiempo_ms",
                  "tiempos_por_capa_ms", "traza_id", "version_configuracion", "aviso"):
        assert clave in r["meta"], clave
    assert entorno["docs"].obtener_ficha(entorno["nueva"]).ficha.titular == "Puesto de frutas"


def test_ruta_rapida_usa_p2_con_imagen(entorno):
    cfg = entorno["cfg"]
    p2 = json.dumps({"titular": "Frutas", "texto_alternativo": "Mangos en un puesto.", "palabras_clave": ["frutas"],
                     "fuentes": {"texto_alternativo": ["foto:xm-a"], "titular": ["foto:xm-a"]}})
    f, cliente = entorno["flujo"]({cfg.modelos["vision"]: [p2]})
    r = f.ejecutar(entorno["nueva"], OpcionesFicha(forzar_ruta="rapida", sin_cache=True))
    assert r["meta"]["ruta"] == "rapida" and cliente.llamadas[0]["imagenes"]


def test_ciclo_de_agente_con_recuperacion_pobre(entorno):
    cfg = entorno["cfg"]
    cfg.parametros.setdefault("agente", {})["tau_ret"] = 0.9999   # todo es «pobre»
    f, _ = entorno["flujo"]({cfg.modelos["vision"]: [json.dumps(P1)], cfg.modelos["composicion"]: [p3()]})
    r = f.ejecutar(entorno["nueva"], OpcionesFicha(forzar_ruta="completa", sin_cache=True))
    assert r["meta"]["iteraciones_agente"] == 2
    assert "REFORMULAR→EVALUAR_RECUPERACION" in r["meta"]["transiciones"]


def test_segunda_vez_sale_de_cache_exacta(entorno):
    cfg = entorno["cfg"]
    cfg.parametros["cache"]["fichas"]["tau_dup"] = 1.01   # solo la exacta: la foto nueva se parece a xm-a a propósito
    f, _ = entorno["flujo"]({cfg.modelos["vision"]: [json.dumps(P1)], cfg.modelos["composicion"]: [p3()]})
    f.ejecutar(entorno["nueva"], OpcionesFicha(forzar_ruta="completa"))
    r = f.ejecutar(entorno["nueva"], OpcionesFicha(forzar_ruta="completa"))
    assert r["meta"]["cache"] == "exacta" and r["meta"]["ruta"] == "cache"


def test_casi_duplicado_del_archivo_responde_por_cache_semantica(entorno):
    cfg = entorno["cfg"]
    docs, vec = entorno["docs"], entorno["vec"]
    copia = docs.guardar_foto(imagen((200, 60, 40), tam=(250, 190)), {"nombre": "copia.jpg"})  # casi igual a xm-a
    f, cliente = entorno["flujo"]({})
    cfg.parametros["cache"]["fichas"]["tau_dup"] = 0.99
    r = f.ejecutar(copia, OpcionesFicha())
    assert r["meta"]["cache"] == "semantica" and r["meta"]["duplicado_de"]["documento_id"] == "xm-a"
    assert not cliente.llamadas, "un acierto de caché no llama a los modelos"


def test_falla_de_modelos_da_ficha_degradada(entorno):
    cfg = entorno["cfg"]
    f, _ = entorno["flujo"]({cfg.modelos["vision"]: [json.dumps(P1), TiempoAgotado("t"), TiempoAgotado("t")],
                             cfg.modelos["composicion"]: [TiempoAgotado("t"), TiempoAgotado("t")]})
    r = f.ejecutar(entorno["nueva"], OpcionesFicha(forzar_ruta="completa", sin_cache=True))
    assert r["ficha"]["estado"] == "requiere_revision" and r["meta"]["revision"]
    assert any(p["termino"] == "Mercados" for p in r["ficha"]["palabras_clave"])


def test_reglas_iptc_normalizan_el_alt(entorno):
    cfg = entorno["cfg"]
    largo = "Imagen de un puesto de frutas. " + "Muchos mangos y piñas en cajas de madera. " * 10
    f, _ = entorno["flujo"]({cfg.modelos["vision"]: [json.dumps(P1)], cfg.modelos["composicion"]: [p3(alt=largo[:250])]})
    r = f.ejecutar(entorno["nueva"], OpcionesFicha(forzar_ruta="completa", sin_cache=True))
    alt = r["ficha"]["texto_alternativo"]
    assert not alt.lower().startswith("imagen de") and len(alt) <= 250
