"""Middleware de traza: crea el `traza_id` de cada petición, lo propaga y lo devuelve en `X-Traza-Id`."""
from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from fototeca.observabilidad.registro import registrar
from fototeca.observabilidad.traza import nueva_traza

# Sin evento: la documentación y sus recursos, y los sondeos de salud (el healthcheck de Docker cada 15 s y la web).
# Los sondeos no son uso del sistema y eran la mayoría de los eventos que lee GET /metricas.
_SIN_REGISTRO = ("/docs", "/openapi.json", "/estaticos", "/health")


class MiddlewareTraza(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        traza_id = nueva_traza()
        request.state.traza_id = traza_id
        t0 = time.perf_counter()
        respuesta = await call_next(request)
        respuesta.headers["X-Traza-Id"] = traza_id
        ruta = request.url.path
        if not ruta.startswith(_SIN_REGISTRO):
            registrar("C1", "peticion", duracion_ms=(time.perf_counter() - t0) * 1000,
                      metodo=request.method, endpoint=ruta, estado_http=respuesta.status_code)
        return respuesta
