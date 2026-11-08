"""Identificador de traza por petición, propagado a todas las capas con `contextvars`."""
from __future__ import annotations

import uuid
from contextvars import ContextVar, Token

_traza: ContextVar[str | None] = ContextVar("traza_id", default=None)


def nueva_traza() -> str:
    """Crea un identificador de 8 caracteres hexadecimales (uuid4) y lo fija para el contexto actual."""
    traza_id = uuid.uuid4().hex[:8]
    _traza.set(traza_id)
    return traza_id


def fijar_traza(traza_id: str | None) -> Token:
    return _traza.set(traza_id)


def restaurar_traza(token: Token) -> None:
    _traza.reset(token)


def traza_actual() -> str | None:
    return _traza.get()
