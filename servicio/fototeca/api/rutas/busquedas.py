"""POST /busquedas: por texto (JSON) o por foto (multipart)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fototeca.api.esquemas import respuestas_error
from fototeca.dominio.errores import PeticionInvalida

router = APIRouter(tags=["Búsquedas"])


class FiltrosBusqueda(BaseModel):
    model_config = ConfigDict(extra="forbid")
    particion: Literal["archivo", "subida"] | None = Field(
        None, description="Limita la búsqueda al archivo catalogado o a las fotos subidas después")


class PeticionBusqueda(BaseModel):
    texto: str = Field(min_length=2, max_length=300, examples=["mercado con frutas"])
    k: int = Field(12, ge=1, le=48)
    filtros: FiltrosBusqueda | None = None
    sin_cache: bool = False                                       # solo evaluación
    forzar_ruta: Literal["simple", "compleja"] | None = None      # solo evaluación


class Resultado(BaseModel):
    documento_id: str
    puntaje: float
    miniatura_url: str
    titular: str | None = None
    texto_alternativo: str | None = None
    razones: list[str]


class RespuestaBusqueda(BaseModel):
    resultados: list[Resultado]
    mensaje: str | None = None
    consulta_interpretada: dict
    meta: dict


CUERPO = {"requestBody": {"required": True, "content": {
    "application/json": {"schema": PeticionBusqueda.model_json_schema()},
    "multipart/form-data": {"schema": {"type": "object", "required": ["imagen"],
                                       "properties": {"imagen": {"type": "string", "format": "binary"},
                                                      "k": {"type": "integer", "default": 12}}}}}}}


@router.post("/busquedas", response_model=RespuestaBusqueda, summary="Buscar por texto en español o por foto",
             openapi_extra=CUERPO, responses=respuestas_error(400, 413, 415, 422, 503, 504))
async def buscar(request: Request):
    """Texto: guardrails (datos personales e inyección), caché exacta y semántica, enrutador simple/compleja (la
    compleja se descompone con P4), recuperación texto→imagen y texto→texto con RRF, reformulación si no hay
    resultados y una razón por cada coincidencia. Foto: búsqueda imagen→imagen sin modelo de lenguaje."""
    c = request.app.state.contenedor
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        formulario = await request.form()
        imagen = formulario.get("imagen")
        if imagen is None or not hasattr(imagen, "read"):
            raise PeticionInvalida("Envía la imagen en el campo `imagen` del formulario.")
        k = int(formulario.get("k") or 12)
        respuesta = await run_in_threadpool(c.busquedas.buscar_imagen, await imagen.read(), max(1, min(k, 48)))
        return JSONResponse(respuesta)
    try:
        p = PeticionBusqueda.model_validate(await request.json())
    except (ValidationError, ValueError) as e:
        raise PeticionInvalida("El cuerpo debe ser JSON con `texto` (2 a 300 caracteres).") from e
    evaluacion = c.config.modo_evaluacion
    filtros = p.filtros.model_dump(exclude_none=True) or None if p.filtros else None
    respuesta = await run_in_threadpool(c.busquedas.buscar_texto, p.texto, p.k, filtros,
                                        p.sin_cache and evaluacion, p.forzar_ruta if evaluacion else None)
    return JSONResponse(respuesta)
