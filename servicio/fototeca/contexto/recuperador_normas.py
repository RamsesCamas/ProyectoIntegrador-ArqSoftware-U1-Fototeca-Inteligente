"""RAG normativo (C5): reglas de IPTC, W3C WAI, WCAG y DCMI para guiar la ficha (k=4).

Consulta = «texto alternativo y descripción de imagen informativa» más las palabras clave de los vecinos
(ADR-06; informe, §8.1).
"""
from __future__ import annotations

from fototeca.datos.puertos import AlmacenVectorial, Embebedor
from fototeca.dominio import colecciones as col
from fototeca.dominio.entidades import ResultadoVectorial

CONSULTA_BASE = "texto alternativo y descripción de imagen informativa"


class RecuperadorNormas:
    def __init__(self, vectorial: AlmacenVectorial, embebedor: Embebedor, k: int = 4):
        self.vectorial = vectorial
        self.embebedor = embebedor
        self.k = k

    def recuperar(self, palabras_vecinos: list[str] | None = None, k: int | None = None) -> list[ResultadoVectorial]:
        extra = ", ".join(dict.fromkeys(p for p in (palabras_vecinos or []) if p))[:300]
        consulta = f"{CONSULTA_BASE}: {extra}" if extra else CONSULTA_BASE
        v = self.embebedor.embeber_textos([consulta], rol="consulta")[0]
        return self.vectorial.buscar(col.NORMAS, v, k or self.k)
