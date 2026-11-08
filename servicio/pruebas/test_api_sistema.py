"""C1 · GET /health, GET /configuracion, cabecera X-Traza-Id, formato de errores y docs sin CDN."""
from __future__ import annotations


def test_health_en_verde(cliente_api):
    r = cliente_api.get("/health")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["estado"] in ("ok", "degradado")
    for componente in ("servicio", "ollama", "qdrant", "almacen", "cache"):
        assert cuerpo["componentes"][componente]["estado"] == "ok", componente
    assert len(r.headers["X-Traza-Id"]) == 8


def test_health_503_si_falla_un_componente_critico(cliente_api, contenedor):
    contenedor.cliente_llm.disponible = False
    r = cliente_api.get("/health")
    assert r.status_code == 503
    assert r.json()["componentes"]["ollama"]["estado"] == "error"


def test_configuracion_expone_modelos_y_version(cliente_api):
    r = cliente_api.get("/configuracion")
    assert r.status_code == 200
    cuerpo = r.json()
    assert set(cuerpo["modelos"]) == {"vision", "composicion", "embedding", "embedding_secundario"}
    assert len(cuerpo["version_configuracion"]) == 12
    assert "generacion" in cuerpo["parametros"]


def test_error_404_en_espanol_con_traza(cliente_api):
    r = cliente_api.get("/no-existe")
    assert r.status_code == 404
    error = r.json()["error"]
    assert error["codigo"] == "http_404"
    assert error["traza_id"] == r.headers["X-Traza-Id"]


def test_eventos_ligados_a_la_traza(cliente_api, contenedor):
    r = cliente_api.get("/health")
    eventos = contenedor.sumidero_eventos.consultar(traza_id=r.headers["X-Traza-Id"])
    capas = {(e.capa, e.evento) for e in eventos}
    assert ("C2", "health") in capas and ("C1", "peticion") in capas


def test_docs_sin_cdn(cliente_api):
    r = cliente_api.get("/docs")
    assert r.status_code == 200
    assert "/estaticos/swagger-ui-bundle.js" in r.text
    assert "cdn.jsdelivr" not in r.text and "unpkg" not in r.text
    assert cliente_api.get("/estaticos/swagger-ui-bundle.js").status_code == 200
    assert cliente_api.get("/openapi.json").json()["info"]["title"] == "Fototeca Viva · API"
