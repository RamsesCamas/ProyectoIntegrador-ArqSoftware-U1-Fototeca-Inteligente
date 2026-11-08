"""Normalización de términos al Tesauro de la UNESCO por similitud de embeddings (C5).

La usan el indexado (etiquetas de Open Images → tesauro), la construcción del contexto (términos candidatos) y
el guardrail de salida `tesauro`. Un término se normaliza al concepto más cercano si la similitud supera
`τ_tesauro`; si no, queda como término `libre` (guardrail de salida `tesauro`; ADR-05).
"""
from __future__ import annotations

from fototeca.datos.puertos import AlmacenVectorial, Embebedor
from fototeca.dominio import colecciones as col
from fototeca.dominio.entidades import ResultadoVectorial
from fototeca.dominio.esquemas_ficha import PalabraClave


class Tesauro:
    def __init__(self, vectorial: AlmacenVectorial, embebedor: Embebedor):
        self.vectorial = vectorial
        self.embebedor = embebedor

    def normalizar(self, terminos: list[str], umbral: float) -> list[tuple[str, PalabraClave]]:
        """Devuelve (término original, palabra clave normalizada) para cada término, en el mismo orden."""
        terminos = [t.strip() for t in terminos if t and t.strip()]
        if not terminos:
            return []
        vectores = self.embebedor.embeber_textos(terminos, rol="consulta")
        salida = []
        for termino, v in zip(terminos, vectores):
            mejores = self.vectorial.buscar(col.TESAURO, v, k=1)
            if mejores and mejores[0].puntaje >= umbral:
                m = mejores[0]
                salida.append((termino, PalabraClave(termino=m.carga.get("etiqueta_es", termino), uri=m.carga.get("uri"),
                                                     origen="tesauro", similitud=round(m.puntaje, 4))))
            else:
                similitud = round(mejores[0].puntaje, 4) if mejores else None
                salida.append((termino, PalabraClave(termino=termino, uri=None, origen="libre", similitud=similitud)))
        return salida

    def candidatos(self, texto: str, k: int = 10, umbral: float | None = None) -> list[ResultadoVectorial]:
        """Conceptos del tesauro más cercanos a un texto (para el contexto del prompt)."""
        v = self.embebedor.embeber_textos([texto], rol="consulta")[0]
        resultados = self.vectorial.buscar(col.TESAURO, v, k=k)
        return [r for r in resultados if umbral is None or r.puntaje >= umbral]
