"""Puerto de T1: dónde se guardan los eventos de cada capa."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Protocol


@dataclass
class EventoCapa:
    ts: str
    traza_id: str | None
    capa: str
    evento: str
    duracion_ms: float | None = None
    modelo: str | None = None
    ruta: str | None = None
    cache: str | None = None
    guardrail: str | None = None
    resultado: str | None = None
    detalle: dict = field(default_factory=dict)

    def a_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, {}, [])}


class SumideroEventos(Protocol):
    def registrar(self, evento: EventoCapa) -> None: ...

    def consultar(self, desde: str | None = None, traza_id: str | None = None,
                  limite: int | None = None) -> list[EventoCapa]: ...
