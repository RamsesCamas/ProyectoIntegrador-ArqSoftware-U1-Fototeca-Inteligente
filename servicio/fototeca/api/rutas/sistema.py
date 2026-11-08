"""GET /health y GET /configuracion."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from fototeca.api.esquemas import RespuestaConfiguracion, RespuestaSalud, respuestas_error

router = APIRouter(tags=["Sistema"])


@router.get("/health", response_model=RespuestaSalud, summary="Estado de cada componente",
            responses={503: {"model": RespuestaSalud, "description": "Algún componente crítico no responde"}})
def salud(request: Request):
    """Comprueba el servicio, Ollama (modelos descargados y cargados), Qdrant (colecciones y puntos), el
    almacén de documentos y la caché. Devuelve 503 si un componente crítico no responde."""
    resultado = request.app.state.contenedor.salud.verificar()
    codigo = 503 if resultado["estado"] == "error" else 200
    return JSONResponse(RespuestaSalud(**resultado).model_dump(), status_code=codigo)


@router.get("/configuracion", response_model=RespuestaConfiguracion, summary="Modelos, parámetros y versiones activas",
            responses=respuestas_error(500))
def configuracion(request: Request) -> RespuestaConfiguracion:
    """Contenido de `config/parametros.yaml`, los modelos por rol, las versiones de los prompts y la versión de
    configuración (hash que forma parte de las claves de la caché)."""
    return RespuestaConfiguracion(**request.app.state.contenedor.salud.configuracion())
