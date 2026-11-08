"""Configuración activa del servicio y su versión.

La versión de configuración es un hash de los parámetros, los modelos, las versiones de los prompts y la
versión del corpus normativo. Forma parte de las claves de la caché: cambiar cualquiera invalida las fichas.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


def _hash(*partes: object, largo: int = 12) -> str:
    texto = json.dumps(partes, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:largo]


@dataclass(frozen=True)
class Configuracion:
    parametros: dict
    modelos: dict[str, str]            # rol → tag de Ollama
    urls: dict[str, str]               # ollama, qdrant
    rutas: dict[str, str]              # datos, sqlite, fotos, config
    versiones_prompts: dict[str, str] = field(default_factory=dict)
    version_servicio: str = "0.1.0"
    modo_evaluacion: bool = False

    def version_estatica(self) -> str:
        return _hash(self.parametros, self.modelos, self.versiones_prompts)

    def version_configuracion(self, version_corpus: str) -> str:
        return _hash(self.version_estatica(), version_corpus)

    def parametro(self, ruta: str, por_defecto=None):
        """Lee un parámetro con notación de puntos, p. ej. `cache.fichas.tau_dup`."""
        nodo = self.parametros
        for parte in ruta.split("."):
            if not isinstance(nodo, dict) or parte not in nodo:
                return por_defecto
            nodo = nodo[parte]
        return nodo
