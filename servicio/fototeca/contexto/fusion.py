"""Fusión de listas de resultados por Reciprocal Rank Fusion (RRF, k=60 por defecto)."""
from __future__ import annotations

from collections import defaultdict

from fototeca.dominio.entidades import ResultadoVectorial


def rrf(listas: list[list[ResultadoVectorial]], k: int = 60, clave=lambda r: r.carga.get("documento_id", r.id),
        limite: int | None = None) -> list[tuple[str, float, dict]]:
    """Devuelve [(clave, puntaje_rrf, detalle)] ordenado. `detalle` guarda el mejor puntaje coseno por lista."""
    puntaje: dict[str, float] = defaultdict(float)
    detalle: dict[str, dict] = defaultdict(lambda: {"cosenos": {}, "carga": {}})
    for n, lista in enumerate(listas):
        for rango, r in enumerate(lista, start=1):
            c = clave(r)
            puntaje[c] += 1.0 / (k + rango)
            previo = detalle[c]["cosenos"].get(n)
            if previo is None or r.puntaje > previo:
                detalle[c]["cosenos"][n] = r.puntaje
            detalle[c]["carga"] = detalle[c]["carga"] or r.carga
    orden = sorted(puntaje.items(), key=lambda kv: -kv[1])
    if limite:
        orden = orden[:limite]
    return [(c, round(p, 6), dict(detalle[c])) for c, p in orden]
