"""Resultado común de toda verificación de guardrail (C3; ADR-05)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

Resultado = Literal["aprobada", "sanitizado", "marcada", "bloqueada"]


@dataclass
class ResultadoGuardrail:
    verificacion: str
    resultado: Resultado
    valor: float | None = None
    umbral: float | None = None
    politica_aplicada: str | None = None
    detalle: dict = field(default_factory=dict)

    def a_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, {}, [])}
