"""RAG de ejemplos (C5): fotos parecidas ya catalogadas (fichas validadas) para guiar la ficha nueva.

- Ruta unificada (por defecto): el vector de la imagen busca en `fotos_img` (imagen→imagen) y en `fotos_txt`
  (imagen→texto); las dos listas se fusionan con RRF (k=60) y se toman 5 vecinos.
- Ruta pipeline (reformulación del agente, C2): se agregan listas de búsquedas por texto (la descripción de Qwen
  y, en la 2ª iteración, sus elementos) contra `fotos_txt`, fusionadas con lo anterior.
- Solo fichas `validada=true` y nunca la propia foto.
- La calidad de la recuperación (top-1 y margen top-1 − top-5) se mide SIEMPRE con el coseno imagen-imagen
  entre la foto y cada vecino, para comparar iteraciones en la misma escala (ADR-07).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from fototeca.contexto.fusion import rrf
from fototeca.datos.puertos import AlmacenDocumentos, AlmacenVectorial, Embebedor
from fototeca.dominio import colecciones as col
from fototeca.dominio.entidades import ResultadoVectorial
from fototeca.dominio.esquemas_ficha import FichaRegistrada


@dataclass
class Vecino:
    documento_id: str
    puntaje_rrf: float
    similitud_imagen: float          # coseno imagen-imagen con la foto que se cataloga
    ficha: FichaRegistrada | None = None
    listas: list[str] = field(default_factory=list)


@dataclass
class Recuperacion:
    vecinos: list[Vecino]
    top1: float
    top5: float
    listas: dict[str, list[ResultadoVectorial]]

    @property
    def margen(self) -> float:
        return self.top1 - self.top5

    def ids(self) -> list[str]:
        return [v.documento_id for v in self.vecinos]


class RecuperadorEjemplos:
    def __init__(self, vectorial: AlmacenVectorial, embebedor: Embebedor, documentos: AlmacenDocumentos,
                 k: int = 5, k_lista: int = 10, rrf_k: int = 60):
        self.vectorial = vectorial
        self.embebedor = embebedor
        self.documentos = documentos
        self.k, self.k_lista, self.rrf_k = k, k_lista, rrf_k

    def _filtro(self, propio: str | None) -> dict:
        f: dict = {"validada": True}
        if propio:
            f["documento_id"] = {"no": propio}
        return f

    def listas_unificadas(self, vector_imagen: np.ndarray, propio: str | None) -> dict[str, list[ResultadoVectorial]]:
        f = self._filtro(propio)
        return {"imagen_imagen": self.vectorial.buscar(col.FOTOS_IMG, vector_imagen, self.k_lista, f),
                "imagen_texto": self.vectorial.buscar(col.FOTOS_TXT, vector_imagen, self.k_lista, f)}

    def listas_texto(self, consultas: list[str], propio: str | None, prefijo: str) -> dict[str, list[ResultadoVectorial]]:
        consultas = [c for c in consultas if c and c.strip()]
        if not consultas:
            return {}
        vectores = self.embebedor.embeber_textos(consultas, rol="consulta")
        f = self._filtro(propio)
        return {f"{prefijo}_{i}": self.vectorial.buscar(col.FOTOS_TXT, v, self.k_lista, f) for i, v in enumerate(vectores)}

    def fusionar(self, vector_imagen: np.ndarray, listas: dict[str, list[ResultadoVectorial]]) -> Recuperacion:
        nombres = list(listas)
        fusion = rrf([listas[n] for n in nombres], k=self.rrf_k, limite=self.k)
        ids = [c for c, _, _ in fusion]
        # Coseno imagen-imagen de cada vecino (los de listas de texto no lo traen: se piden sus vectores)
        conocidos = {r.carga.get("documento_id", r.id): r.puntaje for r in listas.get("imagen_imagen", [])}
        faltan = [i for i in ids if i not in conocidos]
        if faltan:
            vectores = self.vectorial.obtener_vectores(col.FOTOS_IMG, faltan)
            for i, v in vectores.items():
                conocidos[i] = float(np.dot(v, vector_imagen))
        vecinos = []
        for c, puntaje, detalle in fusion:
            vecinos.append(Vecino(documento_id=c, puntaje_rrf=puntaje, similitud_imagen=round(conocidos.get(c, 0.0), 4),
                                  ficha=self.documentos.obtener_ficha(c),
                                  listas=[nombres[n] for n in detalle["cosenos"]]))
        sims = sorted((v.similitud_imagen for v in vecinos), reverse=True)
        top1 = sims[0] if sims else 0.0
        top5 = sims[min(4, len(sims) - 1)] if sims else 0.0
        return Recuperacion(vecinos=vecinos, top1=round(top1, 4), top5=round(top5, 4), listas=listas)
