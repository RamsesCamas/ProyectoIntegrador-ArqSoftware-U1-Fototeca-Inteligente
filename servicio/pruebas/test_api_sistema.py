"""C1 · GET /health, GET /configuracion, cabecera X-Traza-Id, formato de errores y docs sin CDN."""
from __future__ import annotations

from pruebas.conftest import imagen_bytes


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
    r = cliente_api.post("/documentos", data={"tipo": "foto"},
                         files=[("archivos", ("foto.jpg", imagen_bytes(), "image/jpeg"))])
    assert r.status_code == 201, r.text
    eventos = contenedor.sumidero_eventos.consultar(traza_id=r.headers["X-Traza-Id"])
    capas = {(e.capa, e.evento) for e in eventos}
    assert {("C1", "peticion"), ("C2", "ingesta_foto"), ("C7", "embedding_imagen")} <= capas


def test_health_no_se_registra_como_evento(cliente_api, contenedor):
    """Los sondeos de salud (healthcheck de Docker cada 15 s y la web) no son uso del sistema: ni la petición (C1)
    ni la verificación (C2) dejan eventos, tampoco con un 503. La respuesta conserva su traza."""
    antes = len(contenedor.sumidero_eventos.consultar())
    r = cliente_api.get("/health")
    assert r.status_code == 200 and len(r.headers["X-Traza-Id"]) == 8
    assert contenedor.sumidero_eventos.consultar(traza_id=r.headers["X-Traza-Id"]) == []
    contenedor.cliente_llm.disponible = False
    assert cliente_api.get("/health").status_code == 503
    assert len(contenedor.sumidero_eventos.consultar()) == antes


def test_docs_sin_cdn(cliente_api):
    r = cliente_api.get("/docs")
    assert r.status_code == 200
    assert "/estaticos/swagger-ui-bundle.js" in r.text
    assert "cdn.jsdelivr" not in r.text and "unpkg" not in r.text
    assert cliente_api.get("/estaticos/swagger-ui-bundle.js").status_code == 200
    assert cliente_api.get("/openapi.json").json()["info"]["title"] == "Fototeca Viva · API"


def test_precalentar_carga_con_las_opciones_de_cada_modelo(contenedor):
    """El proceso de Qwen debe cargarse sin el modelo de decodificación especulativa (draft_num_predict 0)."""
    contenedor.salud._precalentar()
    opciones = contenedor.cliente_llm.opciones_precalentar
    qwen = contenedor.config.modelos["vision"]
    assert opciones[qwen]["draft_num_predict"] == 0 and opciones[qwen]["num_ctx"] == 4096
