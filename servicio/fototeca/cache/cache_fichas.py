"""Caché de fichas (C4; ADR-04).

- **Exacta:** `sha256(bytes de la imagen) + versión de configuración`.
- **Semántica, en dos niveles con el mismo umbral τ_dup:**
  1. fichas generadas por el servicio (SQLite, TTL 7 días, solo de la misma versión de configuración);
  2. fichas **validadas** del archivo (`fotos_img` con `validada=true`): las respalda una persona, así que no
     expiran; se invalidan cuando se elimina el documento.
- Un acierto semántico es además una detección de duplicado: la respuesta lleva `duplicado_de`.
- Etiquetas de invalidación: `doc:<id>` (la foto y los vecinos usados como fuente), `corpus:<versión>`,
  `config:<versión>`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fototeca.cache.claves import clave_ficha
from fototeca.datos.puertos import AlmacenCache, AlmacenDocumentos, AlmacenVectorial
from fototeca.dominio import colecciones as col
from fototeca.dominio.configuracion import Configuracion


@dataclass
class AciertoFicha:
    tipo: str                 # exacta | semantica
    nivel: str                # generadas | validadas
    respuesta: dict           # cuerpo cacheado (ficha, fuentes, meta mínima)
    duplicado_de: dict | None = None


class CacheFichas:
    def __init__(self, config: Configuracion, almacen: AlmacenCache, vectorial: AlmacenVectorial,
                 documentos: AlmacenDocumentos):
        self.config = config
        self.almacen = almacen
        self.vectorial = vectorial
        self.documentos = documentos

    @property
    def tau_dup(self) -> float:
        return float(self.config.parametro("cache.fichas.tau_dup", 0.97))

    @property
    def ttl(self) -> int:
        return int(self.config.parametro("cache.fichas.ttl_s", 604800))

    def exacta(self, sha256: str, version: str) -> AciertoFicha | None:
        e = self.almacen.obtener(clave_ficha(sha256, version))
        return AciertoFicha("exacta", "generadas", e.valor) if e else None

    def semantica(self, vector: np.ndarray, version: str, documento_id: str | None) -> AciertoFicha | None:
        e = self.almacen.buscar_semantica("fichas", vector, self.tau_dup, etiqueta_requerida=f"config:{version}")
        if e and e.valor.get("documento_id") != documento_id:
            return AciertoFicha("semantica", "generadas", e.valor,
                                {"documento_id": e.valor.get("documento_id"), "similitud": e.similitud})
        filtro = {"validada": True}
        if documento_id:
            filtro["documento_id"] = {"no": documento_id}
        mejores = self.vectorial.buscar(col.FOTOS_IMG, vector, 1, filtro)
        if mejores and mejores[0].puntaje >= self.tau_dup:
            original = mejores[0].carga.get("documento_id", mejores[0].id)
            ficha = self.documentos.obtener_ficha(original)
            if ficha is not None:
                respuesta = {"documento_id": original, "ficha": ficha.ficha.model_dump(),
                             "fuentes": {k: [f.model_dump() for f in v] for k, v in ficha.fuentes.items()},
                             "meta": {"ruta": "cache", "origen_ficha": ficha.origen}}
                return AciertoFicha("semantica", "validadas", respuesta,
                                    {"documento_id": original, "similitud": round(mejores[0].puntaje, 4)})
        return None

    def guardar(self, sha256: str, version: str, vector: np.ndarray, respuesta: dict, documentos_fuente: list[str],
                version_corpus: str) -> None:
        etiquetas = [f"doc:{d}" for d in dict.fromkeys(documentos_fuente)] + [f"corpus:{version_corpus}", f"config:{version}"]
        self.almacen.guardar(clave_ficha(sha256, version), respuesta, self.ttl, etiquetas, vector=vector, espacio="fichas")
