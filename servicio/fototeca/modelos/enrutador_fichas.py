"""Enrutador de fichas (C6; docs/specs/05 §4; ADR-03).

Señales (sobre los 5 vecinos que recuperó C5):
- consenso = media del coseno imagen-imagen de los vecinos;
- acuerdo = Jaccard medio entre los conjuntos de palabras clave de los pares de vecinos;
- texto_visible = el guardrail de entrada detectó texto en la imagen;
- margen = similitud del 1er vecino − la del 5º.

Regla explícita:
    si texto_visible o acuerdo < τ_acuerdo o consenso < τ_consenso → ruta «completa» (Qwen describe, LFM3 compone)
    si no → ruta «rapida» (Qwen ve la imagen y las fichas vecinas)
Si τ_consenso todavía no está calibrado, se elige la ruta completa (la conservadora).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from statistics import mean

from fototeca.dominio.configuracion import Configuracion


@dataclass
class DecisionRuta:
    ruta: str
    senales: dict = field(default_factory=dict)
    razones: list[str] = field(default_factory=list)


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a or b else 0.0


def senales(vecinos: list, texto_visible: bool) -> dict:
    sims = [v.similitud_imagen for v in vecinos]
    conjuntos = [{(p.uri or p.termino.lower()) for p in v.ficha.ficha.palabras_clave}
                 for v in vecinos if v.ficha is not None]
    pares = [jaccard(a, b) for a, b in combinations(conjuntos, 2)]
    ordenadas = sorted(sims, reverse=True)
    return {
        "consenso": round(mean(sims), 4) if sims else 0.0,
        "acuerdo": round(mean(pares), 4) if pares else 0.0,
        "texto_visible": bool(texto_visible),
        "margen": round(ordenadas[0] - ordenadas[min(4, len(ordenadas) - 1)], 4) if ordenadas else 0.0,
    }


class EnrutadorFichas:
    def __init__(self, config: Configuracion):
        self.config = config

    def decidir(self, vecinos: list, texto_visible: bool) -> DecisionRuta:
        s = senales(vecinos, texto_visible)
        tau_acuerdo = self.config.parametro("enrutador_fichas.tau_acuerdo", 0.25)
        tau_consenso = self.config.parametro("enrutador_fichas.tau_consenso")
        razones = []
        if s["texto_visible"]:
            razones.append("la imagen tiene texto visible")
        if s["acuerdo"] < tau_acuerdo:
            razones.append(f"acuerdo {s['acuerdo']} < τ_acuerdo {tau_acuerdo}")
        if tau_consenso is None:
            razones.append("τ_consenso sin calibrar (ruta conservadora)")
        elif s["consenso"] < tau_consenso:
            razones.append(f"consenso {s['consenso']} < τ_consenso {tau_consenso}")
        s.update(tau_acuerdo=tau_acuerdo, tau_consenso=tau_consenso)
        return DecisionRuta("completa" if razones else "rapida", s,
                            razones or [f"consenso {s['consenso']} ≥ {tau_consenso} y acuerdo {s['acuerdo']} ≥ {tau_acuerdo}"])
