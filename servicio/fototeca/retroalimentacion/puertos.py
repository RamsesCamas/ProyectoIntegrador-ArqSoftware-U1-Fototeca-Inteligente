"""Puerto de T2: dónde se guarda la opinión del usuario."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class RegistroRetroalimentacion:
    traza_id: str
    util: bool | None
    documento_id: str | None = None
    comentario: str | None = None
    correcciones: dict = field(default_factory=dict)
    validar_ficha: bool = False
    ts: str | None = None
    ruta: str | None = None
    modelos: dict = field(default_factory=dict)
    id: int | None = None


class AlmacenRetroalimentacion(Protocol):
    def guardar(self, registro: RegistroRetroalimentacion) -> int: ...

    def listar(self, desde: str | None = None) -> list[RegistroRetroalimentacion]: ...
