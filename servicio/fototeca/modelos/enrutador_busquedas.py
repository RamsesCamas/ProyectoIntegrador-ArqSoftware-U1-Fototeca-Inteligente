"""Enrutador de búsquedas (C6; docs/specs/05 §5; ADR-03).

- Búsqueda por imagen → ruta «imagen», sin modelo de lenguaje.
- Búsqueda por texto → «simple» o «compleja» con dos señales:
  1. similitud con los centroides de los prototipos de consultas simples y complejas (`prototipos`);
  2. reglas baratas: negación («sin», «excepto», «que no»…), más de 2 restricciones o más de 12 palabras.
- «compleja» → P4 (LFM3) descompone la consulta antes de buscar; «simple» → se embebe y se busca directo.
"""
from __future__ import annotations

import re

import numpy as np

from fototeca.datos.puertos import AlmacenVectorial, Embebedor
from fototeca.dominio import colecciones as col
from fototeca.dominio.configuracion import Configuracion
from fototeca.modelos.enrutador_fichas import DecisionRuta

NEGACION = re.compile(r"\b(sin|excepto|salvo|que no|ningun[oa]?s?|nada de|no (hay|haya|aparezca|se vea|sea))\b", re.I)
RESTRICCIONES = [
    re.compile(r"\b(de|por la) (noche|mañana|tarde|madrugada)\b|\b(al )?(atardecer|amanecer)\b|\bdurante\b", re.I),  # momento
    re.compile(r"\b(en|dentro de|junto a|cerca de|frente a|desde)\s+\w+", re.I),                                   # lugar
    re.compile(r"\b(\d+|uno|una|dos|tres|cuatro|cinco|varios|varias|muchos|muchas|pocos|pocas|grupo)\b", re.I),     # cantidad
    re.compile(r"\b(con|que tenga|donde se vea)\b", re.I),                                                         # atributo
]


class EnrutadorBusquedas:
    def __init__(self, config: Configuracion, vectorial: AlmacenVectorial, embebedor: Embebedor):
        self.config = config
        self.vectorial = vectorial
        self.embebedor = embebedor
        self._centroides: dict[str, np.ndarray] | None = None

    def centroides(self) -> dict[str, np.ndarray]:
        if self._centroides is None:
            self._centroides = {}
            for clase in ("simple", "compleja"):
                puntos = self.vectorial.vectores_por_filtro(col.PROTOTIPOS, {"tipo": "consulta", "clase": clase})
                if puntos:
                    c = np.mean(np.stack([v for _, v, _ in puntos]), axis=0)
                    self._centroides[clase] = c / max(np.linalg.norm(c), 1e-12)
        return self._centroides

    def decidir_texto(self, texto: str, vector_simetrico: np.ndarray) -> DecisionRuta:
        palabras = len(texto.split())
        restricciones = sum(1 for r in RESTRICCIONES if r.search(texto))
        negacion = bool(NEGACION.search(texto))
        c = self.centroides()
        sim_simple = float(np.dot(vector_simetrico, c["simple"])) if "simple" in c else None
        sim_compleja = float(np.dot(vector_simetrico, c["compleja"])) if "compleja" in c else None
        max_palabras = int(self.config.parametro("enrutador_busquedas.max_palabras_simple", 12))
        max_restr = int(self.config.parametro("enrutador_busquedas.max_restricciones_simple", 2))
        razones = []
        if negacion:
            razones.append("tiene negación")
        if restricciones > max_restr:
            razones.append(f"{restricciones} restricciones (> {max_restr})")
        if palabras > max_palabras:
            razones.append(f"{palabras} palabras (> {max_palabras})")
        if sim_simple is not None and sim_compleja is not None and sim_compleja > sim_simple:
            razones.append(f"más parecida a los prototipos complejos ({sim_compleja:.3f} > {sim_simple:.3f})")
        senales = {"palabras": palabras, "restricciones": restricciones, "negacion": negacion,
                   "sim_prototipos_simple": None if sim_simple is None else round(sim_simple, 4),
                   "sim_prototipos_compleja": None if sim_compleja is None else round(sim_compleja, 4)}
        return DecisionRuta("compleja" if razones else "simple", senales, razones or ["consulta corta y directa"])

    @staticmethod
    def decidir_imagen() -> DecisionRuta:
        return DecisionRuta("imagen", {}, ["búsqueda por imagen: sin modelo de lenguaje"])
