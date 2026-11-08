"""Caché de búsquedas (C4): exacta por texto normalizado + filtros + `version_archivo`, y semántica por el vector
del texto (umbral τ_busq). TTL 24 h. Cualquier cambio del archivo (ingesta, eliminación o validación de una ficha)
incrementa `version_archivo` y deja sin efecto las búsquedas anteriores."""
from __future__ import annotations

import numpy as np

from fototeca.cache.claves import clave_busqueda
from fototeca.datos.puertos import AlmacenCache
from fototeca.dominio.configuracion import Configuracion


class CacheBusquedas:
    def __init__(self, config: Configuracion, almacen: AlmacenCache):
        self.config = config
        self.almacen = almacen

    @property
    def tau(self) -> float:
        return float(self.config.parametro("cache.busquedas.tau_busq", 0.95))

    @property
    def ttl(self) -> int:
        return int(self.config.parametro("cache.busquedas.ttl_s", 86400))

    def exacta(self, texto: str, filtros: dict | None, version_archivo: int, version: str) -> dict | None:
        e = self.almacen.obtener(clave_busqueda(texto, filtros, version_archivo, version))
        return e.valor if e else None

    def semantica(self, vector: np.ndarray, version_archivo: int, version: str) -> tuple[dict, float] | None:
        e = self.almacen.buscar_semantica("busquedas", vector, self.tau, etiqueta_requerida=f"archivo:{version_archivo}:{version}")
        return (e.valor, e.similitud) if e else None

    def guardar(self, texto: str, filtros: dict | None, version_archivo: int, version: str, vector: np.ndarray | None,
                respuesta: dict) -> None:
        self.almacen.guardar(clave_busqueda(texto, filtros, version_archivo, version), respuesta, self.ttl,
                             [f"archivo:{version_archivo}:{version}", f"config:{version}"], vector=vector,
                             espacio="busquedas")
