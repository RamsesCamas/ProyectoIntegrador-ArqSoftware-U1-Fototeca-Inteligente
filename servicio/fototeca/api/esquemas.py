"""Esquemas Pydantic de petición y respuesta de la API (C1)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ErrorDetalle(BaseModel):
    codigo: str = Field(examples=["no_encontrado"])
    mensaje: str = Field(examples=["El documento no existe."])
    traza_id: str | None = Field(None, examples=["c7f2a1b3"])
    mensaje_seguro: str | None = None
    verificaciones: list[dict] | None = None
    detalle: list | dict | None = None


class RespuestaError(BaseModel):
    error: ErrorDetalle


class RespuestaSalud(BaseModel):
    estado: Literal["ok", "degradado", "error"]
    componentes: dict[str, dict]
    precalentamiento: dict
    versiones: dict[str, str]


class RespuestaConfiguracion(BaseModel):
    version_configuracion: str
    version_servicio: str
    version_corpus: str
    modelos: dict[str, str]
    versiones_prompts: dict[str, str]
    parametros: dict
    modo_evaluacion: bool


def respuestas_error(*codigos: int) -> dict:
    """Documentación OpenAPI de los errores que puede devolver un endpoint."""
    descripciones = {400: "Petición mal formada", 404: "No encontrado", 413: "Archivo de más de 10 MB",
                     415: "Formato no soportado", 422: "Bloqueado por un guardrail de entrada",
                     503: "Modelo o base vectorial no disponible", 504: "Tiempo límite agotado"}
    return {c: {"model": RespuestaError, "description": descripciones.get(c, "Error")} for c in codigos}
