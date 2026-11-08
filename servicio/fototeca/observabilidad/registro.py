"""Bitácora estructurada por capa: cada evento va a stdout en JSON y al sumidero configurado (SQLite).

Uso:
    registrar("C6", "llamada_modelo", duracion_ms=812.4, modelo="qwen3.5:0.8b", resultado="ok")
    with medir("C5", "recuperar_ejemplos") as d:
        ...
        d["k"] = 5            # campos extra que terminan en `detalle`
"""
from __future__ import annotations

import json
import logging
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from fototeca.observabilidad.puertos import EventoCapa, SumideroEventos
from fototeca.observabilidad.traza import traza_actual

_CAMPOS = {"modelo", "ruta", "cache", "guardrail", "resultado"}
_sumidero: SumideroEventos | None = None
_bitacora = logging.getLogger("fototeca.eventos")
if not _bitacora.handlers:
    _manejador = logging.StreamHandler(sys.stdout)
    _manejador.setFormatter(logging.Formatter("%(message)s"))
    _bitacora.addHandler(_manejador)
    _bitacora.setLevel(logging.INFO)
    _bitacora.propagate = False


def configurar_sumidero(sumidero: SumideroEventos | None) -> None:
    global _sumidero
    _sumidero = sumidero


def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def registrar(capa: str, evento: str, *, duracion_ms: float | None = None, **campos) -> EventoCapa:
    principales = {k: campos.pop(k) for k in list(campos) if k in _CAMPOS}
    ev = EventoCapa(ts=ahora_iso(), traza_id=traza_actual(), capa=capa, evento=evento,
                    duracion_ms=round(duracion_ms, 2) if duracion_ms is not None else None,
                    detalle=campos, **principales)
    _bitacora.info(json.dumps(ev.a_dict(), ensure_ascii=False, default=str))
    if _sumidero is not None:
        try:
            _sumidero.registrar(ev)
        except Exception as e:  # noqa: BLE001 — la observabilidad nunca tumba una petición
            _bitacora.warning(json.dumps({"capa": "T1", "evento": "sumidero_fallo", "error": str(e)}))
    return ev


@contextmanager
def medir(capa: str, evento: str, **campos) -> Iterator[dict]:
    """Mide la duración de un bloque y registra el evento al salir (también si hay excepción)."""
    extra: dict = {}
    t0 = time.perf_counter()
    try:
        yield extra
    except Exception as e:
        extra.setdefault("resultado", "error")
        extra.setdefault("error", type(e).__name__)
        raise
    finally:
        registrar(capa, evento, duracion_ms=(time.perf_counter() - t0) * 1000, **campos, **extra)
