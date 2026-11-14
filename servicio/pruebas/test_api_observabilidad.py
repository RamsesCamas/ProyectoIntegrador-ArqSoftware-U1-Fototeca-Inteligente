"""T1 y T2 por la API, con adaptadores falsos (sin servidor de modelos ni base vectorial reales).

- `POST /retroalimentacion`: opinión útil / no útil ligada a la traza de una ficha o de una búsqueda; 404 si la
  traza no existe; 400 si la petición no se puede aplicar (y entonces no se escribe nada).
- Validar una ficha la promueve como ejemplo del RAG: queda `validada`, entra en `fotos_txt` y `fotos_txt_granite`
  con `validada=true`, sube `version_archivo` y, en la ficha posterior de una foto parecida, aparece como fuente
  `foto_similar` (criterio de aceptación de H6: el archivo aprende de las correcciones sin fine-tuning).
- `GET /metricas`: estructura completa (latencias por endpoint, etapa y capa; caché; guardrails; modelos; rutas;
  agente; retroalimentación y accesibilidad del archivo) y el filtro `desde`.
- `GET /duplicados`: agrupa los casi duplicados detectados al cargar las fotos.

Con el embebedor falso, el vector de una foto es la imagen reducida a 4×4 en gris: oscurecer la mitad izquierda de
la foto al 60 % da una foto «parecida» (coseno ≈ 0.91, bajo τ_dup = 0.97) y recomprimirla da un casi duplicado.
"""
from __future__ import annotations

import io
import json

from PIL import Image

from fototeca.dominio import colecciones as col
from fototeca.observabilidad.metricas import EVENTOS_CON_DETALLE, agregar, plantilla_ruta
from fototeca.observabilidad.puertos import EventoCapa
from fototeca.observabilidad.registro import ahora_iso
from pruebas.conftest import imagen_bytes

P1 = json.dumps({"tipo": "fotografia", "descripcion_visual": "Un puesto de frutas con mangos bajo un toldo azul.",
                 "elementos": ["puesto", "mangos", "toldo"], "texto_visible": [],
                 "personas": {"hay_personas": False, "cantidad": "0"}, "escena": "exterior"})
ORIGINAL = (150, 40, 120)


def p3(titular: str = "Puesto de frutas", fuentes: dict | None = None) -> str:
    return json.dumps({"titular": titular, "descripcion": "Un puesto de frutas con mangos.",
                       "texto_alternativo": "Puesto de frutas con mangos bajo un toldo azul.",
                       "descripcion_extendida": "", "palabras_clave": ["mercados"], "advertencias": [],
                       "fuentes": fuentes or {}})


def _mitad_oscura(contenido: bytes, factor: float = 0.6) -> bytes:
    """La misma escena con la mitad izquierda más oscura: parecida, pero no un casi duplicado."""
    im = Image.open(io.BytesIO(contenido)).convert("RGB")
    px = im.load()
    for x in range(im.width // 2):
        for y in range(im.height):
            r, g, b = px[x, y]
            px[x, y] = (int(r * factor), int(g * factor), int(b * factor))
    buf = io.BytesIO()
    im.save(buf, "JPEG")
    return buf.getvalue()


def _recomprimida(contenido: bytes) -> bytes:
    buf = io.BytesIO()
    Image.open(io.BytesIO(contenido)).save(buf, "JPEG", quality=40)
    return buf.getvalue()


def _tablero() -> bytes:
    """Escena sin relación con las demás (casillas claras y oscuras)."""
    im = Image.new("RGB", (320, 240), (20, 20, 20))
    for i in range(4):
        for j in range(4):
            if (i + j) % 2 == 0:
                im.paste((235, 235, 235), (i * 80, j * 60, (i + 1) * 80, (j + 1) * 60))
    buf = io.BytesIO()
    im.save(buf, "JPEG")
    return buf.getvalue()


def _subir(cliente_api, contenido: bytes, nombre: str = "foto.jpg") -> str:
    r = cliente_api.post("/documentos", data={"tipo": "foto"}, files=[("archivos", (nombre, contenido, "image/jpeg"))])
    assert r.status_code == 201, r.text
    return r.json()["documentos"][0]["documento_id"]


def _catalogar(cliente_api, contenedor, documento_id: str, titular: str = "Puesto de frutas",
               fuentes: dict | None = None) -> dict:
    contenedor.cliente_llm.respuestas += [P1, p3(titular, fuentes)]
    r = cliente_api.post("/fichas", json={"documento_id": documento_id})
    assert r.status_code == 200, r.text
    return r.json()


def _opinar(cliente_api, traza_id: str, **campos):
    return cliente_api.post("/retroalimentacion", json={"traza_id": traza_id, **campos})


def _ultimo_prompt(contenedor) -> str:
    return "\n".join(m.contenido for m in contenedor.cliente_llm.llamadas[-1]["mensajes"])


# ───────────────────────────── POST /retroalimentacion ─────────────────────────────
def test_opinion_util_y_no_util_queda_ligada_a_la_traza(cliente_api, contenedor):
    doc = _subir(cliente_api, imagen_bytes(color=ORIGINAL))
    ficha = _catalogar(cliente_api, contenedor, doc)
    traza, ruta = ficha["meta"]["traza_id"], ficha["meta"]["ruta"]
    version = contenedor.almacen_documentos.version_archivo()

    r = _opinar(cliente_api, traza, util=True, comentario="El texto alternativo omite el toldo")
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["registrado"] and cuerpo["traza_id"] == traza and cuerpo["documento_id"] == doc
    assert cuerpo["ficha_validada"] is False and cuerpo["version_archivo"] == version
    assert r.headers["x-traza-id"] != traza          # la opinión es otra petición, con su propia traza
    assert _opinar(cliente_api, traza, util=False).status_code == 200

    guardadas = contenedor.almacen_retroalimentacion.listar()
    assert [(g.traza_id, g.util, g.ruta, g.documento_id) for g in guardadas] == [(traza, True, ruta, doc),
                                                                                (traza, False, ruta, doc)]
    assert guardadas[0].modelos == ficha["meta"]["modelos"]
    # Sin `validar_ficha`, la ficha no cambia de estado ni se vuelve ejemplo del RAG
    assert cliente_api.get(f"/fichas/{doc}").json()["ficha"]["estado"] != "validada"
    assert f"{doc}#descripcion" not in contenedor.almacen_vectorial.colecciones.get(col.FOTOS_TXT, {}).get("puntos", {})

    resumen = cliente_api.get("/metricas").json()["retroalimentacion"]
    assert (resumen["total"], resumen["util"], resumen["no_util"], resumen["tasa_util"]) == (2, 1, 1, 0.5)
    assert resumen["con_comentario"] == 1 and resumen["fichas_validadas"] == 0
    assert resumen["por_ruta"][ruta] == {"util": 1, "no_util": 1}
    assert resumen["por_modelo"][ficha["meta"]["modelos"]["composicion"]] == {"util": 1, "no_util": 1}
    assert ficha["meta"]["modelos"]["embedding"] not in resumen["por_modelo"]    # el embebedor no redacta la ficha


def test_opinion_sobre_una_busqueda(cliente_api, contenedor):
    _subir(cliente_api, imagen_bytes(color=ORIGINAL))
    busqueda = cliente_api.post("/busquedas", json={"texto": "mercado con frutas"}).json()
    traza = busqueda["meta"]["traza_id"]
    r = _opinar(cliente_api, traza, util=False, comentario="No salió ningún mercado")
    assert r.status_code == 200, r.text
    assert r.json()["documento_id"] is None
    assert contenedor.almacen_retroalimentacion.listar()[0].ruta == busqueda["meta"]["ruta"]
    # Una búsqueda no tiene ficha que validar
    r = _opinar(cliente_api, traza, validar_ficha=True)
    assert r.status_code == 400 and r.json()["error"]["codigo"] == "peticion_invalida"


def test_traza_inexistente_404(cliente_api, contenedor):
    r = _opinar(cliente_api, "deadbeef", util=True)
    assert r.status_code == 404, r.text
    error = r.json()["error"]
    assert error["codigo"] == "no_encontrado" and error["traza_id"] == r.headers["x-traza-id"]
    assert contenedor.almacen_retroalimentacion.listar() == []


def test_peticiones_que_no_se_pueden_aplicar_400_sin_escribir_nada(cliente_api, contenedor):
    doc = _subir(cliente_api, imagen_bytes(color=ORIGINAL))
    traza = _catalogar(cliente_api, contenedor, doc)["meta"]["traza_id"]
    version = contenedor.almacen_documentos.version_archivo()
    casos = [
        {},                                                                      # opinión vacía
        {"correcciones": {"autor": "Juan"}, "validar_ficha": True},              # campo no editable
        {"correcciones": {"texto_alternativo": "x" * 251}, "validar_ficha": True},
        {"correcciones": {"texto_alternativo": "   "}, "validar_ficha": True},   # una ficha validada necesita alt
        {"correcciones": {"titular": "y" * 121}, "validar_ficha": True},
        {"correcciones": {"palabras_clave": "no es lista"}, "validar_ficha": True},
    ]
    for campos in casos:
        r = _opinar(cliente_api, traza, **campos)
        assert r.status_code == 400, (campos, r.text)
        assert r.json()["error"]["mensaje"]
    assert cliente_api.post("/retroalimentacion", json={"traza_id": "x", "util": True}).status_code == 400
    assert contenedor.almacen_retroalimentacion.listar() == []
    assert cliente_api.get(f"/fichas/{doc}").json()["ficha"]["estado"] != "validada"
    assert contenedor.almacen_documentos.version_archivo() == version


def test_validar_ficha_aplica_correcciones_y_la_promueve_al_rag(cliente_api, contenedor):
    doc = _subir(cliente_api, imagen_bytes(color=ORIGINAL))
    traza = _catalogar(cliente_api, contenedor, doc)["meta"]["traza_id"]
    version = contenedor.almacen_documentos.version_archivo()
    alt = "Puesto de mercado con mangos y piñas bajo un toldo azul."

    r = _opinar(cliente_api, traza, util=True, validar_ficha=True,
                correcciones={"texto_alternativo": alt, "palabras_clave": ["mercados", "frutas tropicales", "mercados"]})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["ficha_validada"] is True
    assert cuerpo["version_archivo"] == version + 1                       # invalida la caché de búsquedas
    assert cuerpo["entradas_cache_invalidadas"] >= 1                     # la ficha en caché de esta foto
    assert cuerpo["ficha"]["estado"] == "validada" and cuerpo["ficha"]["texto_alternativo"] == alt
    assert [p["termino"] for p in cuerpo["ficha"]["palabras_clave"]] == ["mercados", "frutas tropicales"]

    guardada = cliente_api.get(f"/fichas/{doc}").json()
    assert guardada["ficha"]["estado"] == "validada" and guardada["ficha"]["texto_alternativo"] == alt
    assert guardada["fuentes"]["texto_alternativo"][0]["tipo"] == "archivista"
    assert guardada["fuentes"]["palabras_clave"][0]["tipo"] == "archivista"
    assert guardada["origen"].endswith("archivista")

    puntos = contenedor.almacen_vectorial.colecciones
    for coleccion in (col.FOTOS_TXT, col.FOTOS_TXT_GRANITE):
        _, carga = puntos[coleccion]["puntos"][f"{doc}#descripcion"]
        assert carga["validada"] is True and carga["documento_id"] == doc and carga["campo"] == "descripcion"
    _, carga_img = puntos[col.FOTOS_IMG]["puntos"][doc]
    assert carga_img["validada"] is True and carga_img["particion"] == "subida"   # conserva su carga útil

    accesibilidad = cliente_api.get("/metricas").json()["accesibilidad"]
    assert accesibilidad["alt_validado"] == 1 and accesibilidad["fichas_validadas"] == 1
    assert accesibilidad["porcentaje_alt_validado"] == 1.0
    resumen = cliente_api.get("/metricas").json()["retroalimentacion"]
    assert resumen["fichas_validadas"] == 1
    assert resumen["campos_corregidos"] == {"palabras_clave": 1, "texto_alternativo": 1}


def test_ficha_validada_aparece_como_foto_similar_de_una_foto_parecida(cliente_api, contenedor):
    """Criterio de aceptación de H6."""
    original = imagen_bytes(color=ORIGINAL)
    a = _subir(cliente_api, original, "a.jpg")
    traza = _catalogar(cliente_api, contenedor, a)["meta"]["traza_id"]
    titular = "Mercado de frutas bajo un toldo azul"
    assert _opinar(cliente_api, traza, util=True, validar_ficha=True,
                   correcciones={"titular": titular}).json()["ficha_validada"]

    b = _subir(cliente_api, _mitad_oscura(original), "b.jpg")
    assert cliente_api.get("/duplicados").json() == []                    # parecida, no casi duplicada
    cita = {"titular": ["F1"], "descripcion": ["F1"], "texto_alternativo": ["F1"]}     # alias corto del prompt
    ficha_b = _catalogar(cliente_api, contenedor, b, fuentes=cita)

    assert ficha_b["meta"]["cache"] == "ninguna"
    # La ficha validada entró al contexto del modelo, con la corrección del archivista
    prompt = _ultimo_prompt(contenedor)
    assert f"F1: {titular}" in prompt
    # …y quedó como fuente `foto_similar` de los campos de la nueva ficha
    for campo in ("titular", "descripcion", "texto_alternativo"):
        similares = [f for f in ficha_b["fuentes"].get(campo, []) if f["tipo"] == "foto_similar"]
        assert [f["id"] for f in similares] == [a], (campo, ficha_b["fuentes"])
        assert 0.0 < similares[0]["puntaje"] < 0.97


def test_sin_validar_la_ficha_no_es_ejemplo_del_rag(cliente_api, contenedor):
    original = imagen_bytes(color=ORIGINAL)
    a = _subir(cliente_api, original, "a.jpg")
    _catalogar(cliente_api, contenedor, a)
    b = _subir(cliente_api, _mitad_oscura(original), "b.jpg")
    ficha_b = _catalogar(cliente_api, contenedor, b, fuentes={"descripcion": [f"foto:{a}"]})
    assert f"foto:{a}" not in _ultimo_prompt(contenedor)
    # La cita a una foto que no estaba en el contexto la quita el guardrail `fuentes`
    assert not [f for fs in ficha_b["fuentes"].values() for f in fs if f["tipo"] == "foto_similar"]


def test_validar_una_ficha_invalida_la_cache_de_busquedas(cliente_api, contenedor):
    doc = _subir(cliente_api, imagen_bytes(color=ORIGINAL))
    traza = _catalogar(cliente_api, contenedor, doc)["meta"]["traza_id"]
    consulta = {"texto": "mercado con frutas"}
    assert cliente_api.post("/busquedas", json=consulta).json()["meta"]["cache"] == "ninguna"
    assert cliente_api.post("/busquedas", json=consulta).json()["meta"]["cache"] == "exacta"
    assert _opinar(cliente_api, traza, validar_ficha=True).status_code == 200
    assert cliente_api.post("/busquedas", json=consulta).json()["meta"]["cache"] == "ninguna"


# ───────────────────────────── GET /metricas ─────────────────────────────
CLAVES_METRICAS = {"desde", "generado", "eventos_considerados", "latencia_por_endpoint", "latencia_por_capa",
                   "latencia_por_evento", "cache", "guardrails", "bloqueos", "modelos", "rutas", "iteraciones_agente",
                   "iteraciones_agente_busquedas", "retroalimentacion", "accesibilidad"}


def test_metricas_tiene_todo_lo_que_pide_t1(cliente_api, contenedor):
    doc = _subir(cliente_api, imagen_bytes(color=ORIGINAL))
    ficha = _catalogar(cliente_api, contenedor, doc)
    assert cliente_api.get(f"/fotos/{doc}/miniatura").status_code == 200
    cliente_api.post("/busquedas", json={"texto": "mercado con frutas"})
    _opinar(cliente_api, ficha["meta"]["traza_id"], util=True)

    r = cliente_api.get("/metricas")
    assert r.status_code == 200, r.text
    m = r.json()
    assert CLAVES_METRICAS <= set(m), CLAVES_METRICAS - set(m)
    assert m["desde"] is None and m["eventos_considerados"] > 0
    # Latencia p50/p95 por endpoint, agrupada por plantilla de ruta (no una entrada por documento)
    endpoints = m["latencia_por_endpoint"]
    assert {"POST /fichas", "POST /documentos", "GET /fotos/{id}/miniatura", "POST /busquedas"} <= set(endpoints)
    assert not [e for e in endpoints if doc in e]
    assert endpoints["POST /fichas"]["n"] == 1 and endpoints["POST /fichas"]["p95_ms"] >= endpoints["POST /fichas"]["p50_ms"]
    # Por etapa de cada flujo y por capa de la arquitectura
    assert {"total", "guardrails_entrada", "contexto"} <= set(m["latencia_por_capa"]["fichas"])
    assert m["latencia_por_capa"]["fichas"]["total"]["n"] == 1
    assert "total" in m["latencia_por_capa"]["busquedas"]
    assert "llamada_modelo" in m["latencia_por_evento"]["C6"] and "embedding_imagen" in m["latencia_por_evento"]["C7"]
    # Caché, guardrails, modelos, rutas e iteraciones del agente
    assert m["cache"]["fichas"] == {"consultas": 1, "aciertos_exactos": 0, "aciertos_semanticos": 0, "tasa_aciertos": 0.0}
    assert m["cache"]["busquedas"]["consultas"] == 1
    verificaciones = {(g["verificacion"], g["resultado"]) for g in m["guardrails"]}
    assert ("archivo_valido", "aprobada") in verificaciones and ("esquema", "aprobada") in verificaciones
    composicion = m["modelos"][ficha["meta"]["modelos"]["composicion"]]
    assert composicion["llamadas"] >= 1 and composicion["tokens_salida"] > 0 and composicion["respaldos"] == 0
    assert m["rutas"][f"fichas:{ficha['meta']['ruta']}"] == 1 and m["rutas"]["busquedas:simple"] == 1
    assert m["iteraciones_agente"] == {str(ficha["meta"]["iteraciones_agente"]): 1}
    assert m["iteraciones_agente_busquedas"] == {"0": 1}
    # Retroalimentación y accesibilidad del archivo
    assert m["retroalimentacion"]["util"] == 1
    a = m["accesibilidad"]
    assert a["fotos"] == 1 and a["alt_validado"] == 0 and a["porcentaje_alt_validado"] == 0.0
    assert a["requiere_revision"] + a["borrador"] == 1 and a["sin_ficha"] == 0


def test_metricas_filtra_por_fecha(cliente_api, contenedor):
    doc = _subir(cliente_api, imagen_bytes(color=ORIGINAL))
    _opinar(cliente_api, _catalogar(cliente_api, contenedor, doc)["meta"]["traza_id"], util=True)
    futuro = cliente_api.get("/metricas", params={"desde": "2999-01-01T00:00:00Z"}).json()
    assert futuro["desde"] == "2999-01-01T00:00:00+00:00"
    assert futuro["eventos_considerados"] == 0 and futuro["retroalimentacion"]["total"] == 0
    assert futuro["accesibilidad"]["fotos"] == 1                         # el estado del archivo no depende de `desde`
    pasado = cliente_api.get("/metricas", params={"desde": "2000-01-01"}).json()
    assert pasado["desde"] == "2000-01-01T00:00:00+00:00" and pasado["eventos_considerados"] > 0
    assert pasado["retroalimentacion"]["total"] == 1
    # Con zona horaria distinta de UTC se normaliza antes de comparar
    assert cliente_api.get("/metricas", params={"desde": "2999-01-01T00:00:00-06:00"}).json()["desde"] == \
        "2999-01-01T06:00:00+00:00"
    r = cliente_api.get("/metricas", params={"desde": "ayer"})
    assert r.status_code == 400 and r.json()["error"]["codigo"] == "peticion_invalida"


def test_metricas_sin_sondeos_de_salud_y_con_las_mismas_claves(cliente_api, contenedor):
    """GET /metricas conserva sus claves y deja fuera /health: los sondeos nuevos ya no se registran y los que
    quedaron guardados se omiten al leer. Fuera de eso, agrega lo mismo que la lectura completa de `consultar`."""
    doc = _subir(cliente_api, imagen_bytes(color=ORIGINAL))
    ficha = _catalogar(cliente_api, contenedor, doc)
    cliente_api.post("/busquedas", json={"texto": "mercado con frutas"})
    _opinar(cliente_api, ficha["meta"]["traza_id"], util=True)
    assert cliente_api.get("/health").status_code == 200
    sumidero = contenedor.sumidero_eventos
    for traza in ("5a1d0001", "5a1d0002"):     # sondeos guardados antes de que /health dejara de registrarse
        sumidero.registrar(EventoCapa(ts=ahora_iso(), traza_id=traza, capa="C2", evento="health", duracion_ms=351.0,
                                      resultado="ok"))
        sumidero.registrar(EventoCapa(ts=ahora_iso(), traza_id=traza, capa="C1", evento="peticion", duracion_ms=352.0,
                                      detalle={"metodo": "GET", "endpoint": "/health", "estado_http": 200}))

    m = cliente_api.get("/metricas").json()
    assert CLAVES_METRICAS <= set(m), CLAVES_METRICAS - set(m)
    endpoints = set(m["latencia_por_endpoint"])
    assert {"POST /documentos", "POST /fichas", "POST /busquedas", "POST /retroalimentacion"} <= endpoints
    assert "GET /health" not in endpoints
    assert "health" not in m["latencia_por_evento"].get("C2", {})
    assert m["modelos"] and m["guardrails"] and m["rutas"] and m["cache"]["fichas"]["consultas"] == 1

    def es_sondeo(e: EventoCapa) -> bool:
        return (e.capa, e.evento) == ("C2", "health") or (e.capa == "C1" and e.detalle.get("endpoint") == "/health")

    completa = [e for e in sumidero.consultar() if not es_sondeo(e)]
    assert len(completa) == len(sumidero.consultar()) - 4
    assert agregar(sumidero.consultar_para_metricas(con_detalle=EVENTOS_CON_DETALLE)) == agregar(completa)


def test_plantilla_de_ruta_agrupa_por_endpoint():
    assert plantilla_ruta("/fotos/xm-000411001ff7dd4f/miniatura") == "/fotos/{id}/miniatura"
    assert plantilla_ruta("/fichas/up-0123456789abcdef") == "/fichas/{id}"
    assert plantilla_ruta("/lotes/abcdefabcdef") == "/lotes/{id}"
    assert plantilla_ruta("/documentos/norma-iptc-2025") == "/documentos/{id}"
    for ruta in ("/health", "/documentos", "/metricas", "/duplicados", "/retroalimentacion", "/configuracion"):
        assert plantilla_ruta(ruta) == ruta


# ───────────────────────────── GET /duplicados ─────────────────────────────
def test_duplicados_agrupa_los_casi_duplicados(cliente_api, contenedor):
    original = imagen_bytes(color=ORIGINAL)
    a = _subir(cliente_api, original, "a.jpg")
    copia = _subir(cliente_api, _recomprimida(original), "a_recomprimida.jpg")
    otra = _subir(cliente_api, _tablero(), "tablero.jpg")
    assert len({a, copia, otra}) == 3

    r = cliente_api.get("/duplicados")
    assert r.status_code == 200, r.text
    grupos = r.json()
    assert len(grupos) == 1
    assert {d["id"] for d in grupos[0]["documentos"]} == {a, copia}     # la foto sin relación no aparece
    tau = float(contenedor.config.parametro("cache.fichas.tau_dup", 0.97))
    assert all(d["similitud"] >= tau for d in grupos[0]["documentos"])
    assert cliente_api.get("/duplicados").json()[0]["grupo_id"] == grupos[0]["grupo_id"]   # id estable

    # Con ficha, cada miembro trae su texto alternativo (la web lo usa como `alt` de la miniatura)
    _catalogar(cliente_api, contenedor, a)
    miembro = next(d for d in cliente_api.get("/duplicados").json()[0]["documentos"] if d["id"] == a)
    assert miembro["texto_alternativo"] and miembro["titular"]


def test_duplicados_une_grupos_transitivos(cliente_api):
    """Si A ≈ C y B ≈ C, las tres fotos quedan en un mismo grupo aunque A y B no pasen el umbral entre sí."""
    original = imagen_bytes(color=ORIGINAL)
    a = _subir(cliente_api, original, "a.jpg")
    b = _subir(cliente_api, _mitad_oscura(original, 0.6), "b.jpg")
    assert cliente_api.get("/duplicados").json() == []
    c = _subir(cliente_api, _mitad_oscura(original, 0.8), "c.jpg")
    grupos = cliente_api.get("/duplicados").json()
    assert len(grupos) == 1 and {d["id"] for d in grupos[0]["documentos"]} == {a, b, c}


def test_openapi_documenta_los_endpoints_de_t1_y_t2(cliente_api):
    esquema = cliente_api.get("/openapi.json").json()
    for ruta, metodo in (("/retroalimentacion", "post"), ("/metricas", "get"), ("/duplicados", "get")):
        operacion = esquema["paths"][ruta][metodo]
        assert operacion["summary"] and operacion["tags"]
    assert "404" in esquema["paths"]["/retroalimentacion"]["post"]["responses"]
    assert {t["name"] for t in esquema["tags"]} >= {"Duplicados", "Retroalimentación y métricas"}
