"""C1 · POST /fichas, GET /fichas/{id}, POST /lotes, GET /lotes/{id} y POST /busquedas (H4) con adaptadores falsos.

Se verifica el contrato de la API (informe, Anexo B): los campos de la ficha, las fuentes y todo el bloque `meta`.
"""
from __future__ import annotations

import json
import time

from pruebas.conftest import imagen_bytes

P1 = json.dumps({"tipo": "fotografia", "descripcion_visual": "Un puesto de frutas con mangos bajo un toldo azul.",
                 "elementos": ["puesto", "mangos", "toldo"], "texto_visible": [],
                 "personas": {"hay_personas": False, "cantidad": "0"}, "escena": "exterior"})
P3 = json.dumps({"titular": "Puesto de frutas", "descripcion": "Un puesto de frutas con mangos.",
                 "texto_alternativo": "Puesto de frutas con mangos bajo un toldo azul.", "descripcion_extendida": "",
                 "palabras_clave": ["mercados"], "advertencias": [], "fuentes": {}})

META_FICHA = {"ruta", "modelos", "cache", "guardrails", "iteraciones_agente", "duplicado_de", "tiempo_ms",
              "tiempos_por_capa_ms", "traza_id", "version_configuracion", "aviso"}
META_BUSQUEDA = {"ruta", "modelo", "cache", "guardrails", "iteraciones_agente", "tiempo_ms", "tiempos_por_capa_ms",
                 "traza_id", "aviso"}


def _subir(cliente_api, color=(180, 90, 40)) -> str:
    r = cliente_api.post("/documentos", data={"tipo": "foto"},
                         files=[("archivos", ("f.jpg", imagen_bytes(color=color), "image/jpeg"))])
    assert r.status_code == 201, r.text
    return r.json()["documentos"][0]["documento_id"]


def test_ficha_por_documento_id_cumple_el_contrato(cliente_api, contenedor):
    doc = _subir(cliente_api)
    contenedor.cliente_llm.respuestas += [P1, P3]
    r = cliente_api.post("/fichas", json={"documento_id": doc})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["documento_id"] == doc
    assert {"titular", "descripcion", "texto_alternativo", "descripcion_extendida", "palabras_clave", "advertencias",
            "estado"} <= set(cuerpo["ficha"])
    assert len(cuerpo["ficha"]["texto_alternativo"]) <= 250
    assert isinstance(cuerpo["fuentes"], dict)
    assert META_FICHA <= set(cuerpo["meta"]), META_FICHA - set(cuerpo["meta"])
    assert {"entrada", "salida"} <= set(cuerpo["meta"]["guardrails"])
    assert cuerpo["meta"]["traza_id"] == r.headers["x-traza-id"]
    assert "IA" in cuerpo["meta"]["aviso"]
    # La ficha queda guardada y se puede consultar
    guardada = cliente_api.get(f"/fichas/{doc}")
    assert guardada.status_code == 200
    assert guardada.json()["ficha"]["titular"] == cuerpo["ficha"]["titular"]


def test_ficha_con_foto_multipart(cliente_api, contenedor):
    contenedor.cliente_llm.respuestas += [P1, P3]
    r = cliente_api.post("/fichas", files=[("foto", ("nueva.jpg", imagen_bytes(color=(30, 140, 60)), "image/jpeg"))])
    assert r.status_code == 200, r.text
    assert r.json()["documento_id"].startswith("up-")


def test_ficha_de_documento_inexistente_404(cliente_api):
    r = cliente_api.post("/fichas", json={"documento_id": "xm-no-existe"})
    assert r.status_code == 404
    assert r.json()["error"]["codigo"]


def test_opciones_de_evaluacion_se_ignoran_fuera_de_evaluacion(cliente_api, contenedor):
    doc = _subir(cliente_api, color=(60, 60, 200))
    contenedor.cliente_llm.respuestas += [P1, P3]
    r = cliente_api.post("/fichas", json={"documento_id": doc, "forzar_ruta": "rapida", "sin_rag": True})
    assert r.status_code == 200, r.text
    assert not any("forzada" in x for x in r.json()["meta"]["razones_enrutador"])


def test_segunda_ficha_igual_sale_de_la_cache_exacta(cliente_api, contenedor):
    doc = _subir(cliente_api, color=(120, 30, 160))
    contenedor.cliente_llm.respuestas += [P1, P3]
    assert cliente_api.post("/fichas", json={"documento_id": doc}).json()["meta"]["cache"] == "ninguna"
    llamadas = len(contenedor.cliente_llm.llamadas)
    r = cliente_api.post("/fichas", json={"documento_id": doc})
    assert r.json()["meta"]["cache"] == "exacta"
    assert len(contenedor.cliente_llm.llamadas) == llamadas      # sin llamar a los modelos


def test_lote_asincrono(cliente_api, contenedor):
    docs = [_subir(cliente_api, color=c) for c in ((10, 200, 10), (200, 200, 10))]
    contenedor.cliente_llm.respuestas += [P1, P3, P1, P3]
    r = cliente_api.post("/lotes", json={"documento_ids": docs})
    assert r.status_code == 202, r.text
    lote = r.json()["lote_id"]
    for _ in range(200):
        estado = cliente_api.get(f"/lotes/{lote}").json()
        if estado["estado"] == "terminado":
            break
        time.sleep(0.05)
    assert estado["estado"] == "terminado", estado
    assert (estado["total"], estado["completadas"], estado["fallidas"]) == (2, 2, 0)
    assert len(estado["fichas"]) == 2


def test_lote_con_documento_inexistente_404(cliente_api):
    assert cliente_api.post("/lotes", json={"documento_ids": ["xm-falta"]}).status_code == 404


def test_busqueda_simple_por_texto(cliente_api):
    _subir(cliente_api)
    r = cliente_api.post("/busquedas", json={"texto": "mercado con frutas"})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert isinstance(cuerpo["resultados"], list)
    assert META_BUSQUEDA <= set(cuerpo["meta"]), META_BUSQUEDA - set(cuerpo["meta"])
    assert cuerpo["meta"]["ruta"] == "simple"


def test_busqueda_por_foto(cliente_api):
    doc = _subir(cliente_api, color=(10, 120, 200))
    r = cliente_api.post("/busquedas", files=[("imagen", ("q.jpg", imagen_bytes(color=(10, 120, 200)), "image/jpeg"))])
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["meta"]["ruta"] == "imagen"
    assert cuerpo["resultados"] and cuerpo["resultados"][0]["documento_id"] == doc
    assert cuerpo["resultados"][0]["razones"]


def test_busqueda_invalida_400(cliente_api):
    assert cliente_api.post("/busquedas", json={"texto": "x"}).status_code == 400


def test_guardrails_de_la_ingesta_aparecen_en_la_ficha(cliente_api, contenedor):
    doc = _subir(cliente_api, color=(90, 150, 30))
    contenedor.cliente_llm.respuestas += [P1, P3]
    entrada = cliente_api.post("/fichas", json={"documento_id": doc}).json()["meta"]["guardrails"]["entrada"]
    de_ingesta = {g["verificacion"] for g in entrada if g.get("etapa") == "ingesta"}
    assert {"archivo_valido", "exif_privacidad"} <= de_ingesta


def test_casi_duplicado_sale_de_la_cache_semantica_como_propuesta_a_revisar(cliente_api, contenedor):
    original = imagen_bytes(color=(150, 40, 120))
    r = cliente_api.post("/documentos", data={"tipo": "foto"}, files=[("archivos", ("o.jpg", original, "image/jpeg"))])
    doc = r.json()["documentos"][0]["documento_id"]
    contenedor.cliente_llm.respuestas += [P1, P3]
    assert cliente_api.post("/fichas", json={"documento_id": doc}).json()["meta"]["cache"] == "ninguna"
    # La misma foto recomprimida: bytes distintos (otra sha), casi el mismo vector
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.open(BytesIO(original)).save(buf, "JPEG", quality=40)
    r = cliente_api.post("/fichas", files=[("foto", ("recomprimida.jpg", buf.getvalue(), "image/jpeg"))])
    cuerpo = r.json()
    assert r.status_code == 200, r.text
    assert cuerpo["meta"]["cache"] == "semantica"
    assert cuerpo["meta"]["duplicado_de"]["documento_id"] == doc
    assert cuerpo["ficha"]["estado"] == "requiere_revision"
    assert any("duplicado" in a for a in cuerpo["ficha"]["advertencias"])
    guardada = cliente_api.get(f"/fichas/{cuerpo['documento_id']}")
    assert guardada.status_code == 200 and guardada.json()["origen"] == "cache"


def test_busqueda_filtrada_por_particion(cliente_api, contenedor):
    from fototeca.dominio import colecciones as col
    subida = _subir(cliente_api, color=(200, 180, 20))
    # Una foto «del archivo» directamente en la base vectorial (como las que deja indexar_archivo)
    vector = contenedor.embebedor.embeber_imagenes([imagen_bytes(color=(200, 180, 25))])
    contenedor.almacen_vectorial.insertar(col.FOTOS_IMG, ["xm-archivo"], vector,
                                          [{"documento_id": "xm-archivo", "particion": "archivo", "validada": True}])
    def ids(filtros):
        r = cliente_api.post("/busquedas", json={"texto": "foto amarilla", "filtros": filtros})
        assert r.status_code == 200, r.text
        return {x["documento_id"] for x in r.json()["resultados"]}
    assert ids({"particion": "subida"}) == {subida}
    assert ids({"particion": "archivo"}) == {"xm-archivo"}
    assert cliente_api.post("/busquedas", json={"texto": "foto amarilla", "filtros": {"color": "rojo"}}).status_code == 400
