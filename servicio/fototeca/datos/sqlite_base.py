"""Base común de los adaptadores SQLite: una conexión por operación, modo WAL y espera ante bloqueos.

Todos los almacenes comparten un archivo (`data/sqlite/fototeca.db`, en un volumen con nombre y no en una carpeta
montada, donde SQLite puede fallar en Docker Desktop para Windows; ADR-09). Abrir una conexión por operación es
barato en SQLite y evita compartir conexiones entre el threadpool de FastAPI y el trabajador de lotes.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class BaseSqlite:
    ESQUEMA: str = ""

    def __init__(self, ruta: Path | str):
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        with self.conexion() as con:
            con.execute("PRAGMA journal_mode=WAL")
            if self.ESQUEMA:
                con.executescript(self.ESQUEMA)

    @contextmanager
    def conexion(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.ruta, timeout=30, isolation_level=None, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=30000")
        con.execute("PRAGMA foreign_keys=ON")
        try:
            yield con
        finally:
            con.close()

    def estado_basico(self, tablas: list[str]) -> dict:
        try:
            with self.conexion() as con:
                conteos = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tablas}
            return {"estado": "ok", "archivo": self.ruta.name, "filas": conteos}
        except Exception as e:  # noqa: BLE001
            return {"estado": "error", "error": str(e)[:200]}
