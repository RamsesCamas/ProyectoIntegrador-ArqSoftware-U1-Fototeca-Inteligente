"""Verdad de referencia LÉXICA para el mapeo etiqueta de Open Images (inglés) → concepto del Tesauro UNESCO.

La usan `indexar_archivo` (calibración de τ_tesauro con un proxy léxico, mientras el autor no revise los 50 pares)
y `evaluacion/r3_embeddings` (exactitud top-1/top-3 de la asignación de términos). El mapeo del sistema SIEMPRE es por
embeddings (ADR-05); esto solo decide cuál es el concepto «esperado» cuando la etiqueta coincide con una etiqueta en
inglés del concepto (prefLabel o altLabel @en), aceptando la diferencia singular/plural del inglés.
"""
from __future__ import annotations

import re


def _formas(texto: str) -> set[str]:
    t = re.sub(r"\s+", " ", texto.strip().lower())
    formas = {t}
    if t.endswith("ies") and len(t) > 4:
        formas.add(t[:-3] + "y")
    if t.endswith("es") and len(t) > 3:
        formas.add(t[:-2])
    if t.endswith("s") and len(t) > 2:
        formas.add(t[:-1])
    formas |= {t + "s", t + "es"}
    if t.endswith("y") and len(t) > 2:
        formas.add(t[:-1] + "ies")
    return formas


def indice_ingles(conceptos: list[dict]) -> dict[str, str]:
    """forma en inglés (minúsculas) → uri del concepto. Si una forma apunta a varios conceptos, se descarta
    (ambigua): el esperado debe ser único."""
    candidatos: dict[str, set[str]] = {}
    for c in conceptos:
        for etiqueta in c.get("etiquetas_en", []):
            for f in _formas(etiqueta):
                candidatos.setdefault(f, set()).add(c["uri"])
    return {f: next(iter(uris)) for f, uris in candidatos.items() if len(uris) == 1}


def esperado(etiqueta: str, indice: dict[str, str]) -> str | None:
    """URI esperada para una etiqueta de Open Images, o None si no hay coincidencia léxica única."""
    t = re.sub(r"\s+", " ", etiqueta.strip().lower())
    if t in indice:
        return indice[t]
    uris = {indice[f] for f in _formas(t) if f in indice}
    return next(iter(uris)) if len(uris) == 1 else None
