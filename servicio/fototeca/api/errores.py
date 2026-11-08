"""Traducción de errores a HTTP con el formato de docs/specs/03-api.md:

    {"error": {"codigo": "...", "mensaje": "...", "traza_id": "..."}}

Los errores de validación de FastAPI se devuelven como 400 (petición mal formada), porque 422 está reservado
para los bloqueos de los guardrails de entrada.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from fototeca.dominio import errores as e
from fototeca.observabilidad.registro import registrar
from fototeca.observabilidad.traza import traza_actual

ESTADO_HTTP = {
    e.PeticionInvalida: 400,
    e.NoEncontrado: 404,
    e.ArchivoDemasiadoGrande: 413,
    e.FormatoNoSoportado: 415,
    e.BloqueadoPorGuardrail: 422,
    e.ServicioNoDisponible: 503,
    e.TiempoAgotado: 504,
}

MENSAJES_HTTP = {400: "Petición mal formada.", 404: "Recurso no encontrado.", 405: "Método no permitido.",
                 413: "El archivo supera el tamaño máximo.", 415: "Formato no soportado."}


def cuerpo_error(codigo: str, mensaje: str, **extra) -> dict:
    return {"error": {"codigo": codigo, "mensaje": mensaje, "traza_id": traza_actual(), **extra}}


def instalar_manejadores(app: FastAPI) -> None:
    @app.exception_handler(e.ErrorDominio)
    async def _dominio(_: Request, exc: e.ErrorDominio):
        estado = next((v for k, v in ESTADO_HTTP.items() if isinstance(exc, k)), 500)
        extra = {}
        if isinstance(exc, e.BloqueadoPorGuardrail):
            extra = {"mensaje_seguro": exc.mensaje_seguro, "verificaciones": exc.verificaciones}
            for v in exc.verificaciones:
                registrar("C3", "bloqueo", guardrail=v.get("verificacion"), resultado="bloqueada",
                          verificacion=v.get("verificacion"), valor=v.get("valor"), umbral=v.get("umbral"))
        elif exc.detalle:
            extra = {"detalle": exc.detalle}
        registrar("C1", "error", resultado=exc.codigo, estado_http=estado)
        return JSONResponse(cuerpo_error(exc.codigo, exc.mensaje, **extra), status_code=estado)

    @app.exception_handler(RequestValidationError)
    async def _validacion(_: Request, exc: RequestValidationError):
        detalles = [{"campo": ".".join(str(p) for p in err.get("loc", [])), "problema": err.get("msg")}
                    for err in exc.errors()][:10]
        registrar("C1", "error", resultado="peticion_invalida", estado_http=400)
        return JSONResponse(cuerpo_error("peticion_invalida", "La petición no cumple el esquema.",
                                         detalle=detalles), status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        mensaje = exc.detail if isinstance(exc.detail, str) and exc.detail not in ("Not Found",) else \
            MENSAJES_HTTP.get(exc.status_code, "Error en la petición.")
        return JSONResponse(cuerpo_error(f"http_{exc.status_code}", mensaje), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _generico(_: Request, exc: Exception):
        registrar("C1", "error", resultado="error_interno", tipo=type(exc).__name__)
        return JSONResponse(cuerpo_error("error_interno", "Ocurrió un error interno. Consulta la traza."),
                            status_code=500)
