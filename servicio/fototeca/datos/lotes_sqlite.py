"""Adaptador SQLite del puerto `AlmacenLotes` (C7): estado de los lotes de catalogación asíncrona (ADR-08)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fototeca.datos.sqlite_base import BaseSqlite


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class LotesSqlite(BaseSqlite):
    ESQUEMA = """
    CREATE TABLE IF NOT EXISTS lotes (
        lote_id TEXT PRIMARY KEY,
        estado TEXT NOT NULL,            -- en_cola | en_proceso | terminado
        creado TEXT NOT NULL,
        actualizado TEXT NOT NULL,
        opciones TEXT
    );
    CREATE TABLE IF NOT EXISTS lote_items (
        lote_id TEXT NOT NULL REFERENCES lotes(lote_id) ON DELETE CASCADE,
        posicion INTEGER NOT NULL,
        documento_id TEXT NOT NULL,
        estado TEXT NOT NULL,            -- pendiente | en_proceso | completada | fallida
        respuesta TEXT,
        error TEXT,
        traza_id TEXT,
        PRIMARY KEY (lote_id, posicion)
    );
    """

    def crear(self, documento_ids: list[str], opciones: dict | None = None) -> str:
        lote_id = uuid.uuid4().hex[:12]
        with self.conexion() as con:
            con.execute("BEGIN")
            con.execute("INSERT INTO lotes (lote_id, estado, creado, actualizado, opciones) VALUES (?,?,?,?,?)",
                        (lote_id, "en_cola", ahora(), ahora(), json.dumps(opciones or {})))
            con.executemany("INSERT INTO lote_items (lote_id, posicion, documento_id, estado) VALUES (?,?,?,?)",
                            [(lote_id, i, d, "pendiente") for i, d in enumerate(documento_ids)])
            con.execute("COMMIT")
        return lote_id

    def marcar_lote(self, lote_id: str, estado: str) -> None:
        with self.conexion() as con:
            con.execute("UPDATE lotes SET estado=?, actualizado=? WHERE lote_id=?", (estado, ahora(), lote_id))

    def marcar_item(self, lote_id: str, posicion: int, estado: str, respuesta: dict | None = None,
                    error: str | None = None, traza_id: str | None = None) -> None:
        with self.conexion() as con:
            con.execute("UPDATE lote_items SET estado=?, respuesta=?, error=?, traza_id=COALESCE(?, traza_id) "
                        "WHERE lote_id=? AND posicion=?",
                        (estado, None if respuesta is None else json.dumps(respuesta, ensure_ascii=False, default=str),
                         error, traza_id, lote_id, posicion))
            con.execute("UPDATE lotes SET actualizado=? WHERE lote_id=?", (ahora(), lote_id))

    def obtener(self, lote_id: str) -> dict | None:
        with self.conexion() as con:
            lote = con.execute("SELECT * FROM lotes WHERE lote_id=?", (lote_id,)).fetchone()
            if not lote:
                return None
            items = con.execute("SELECT * FROM lote_items WHERE lote_id=? ORDER BY posicion", (lote_id,)).fetchall()
        return {"lote_id": lote_id, "estado": lote["estado"], "creado": lote["creado"], "actualizado": lote["actualizado"],
                "opciones": json.loads(lote["opciones"] or "{}"),
                "items": [{"posicion": i["posicion"], "documento_id": i["documento_id"], "estado": i["estado"],
                           "respuesta": json.loads(i["respuesta"]) if i["respuesta"] else None, "error": i["error"],
                           "traza_id": i["traza_id"]} for i in items]}

    def pendientes(self) -> list[str]:
        """Lotes que quedaron sin terminar (p. ej. tras un reinicio) para reanudarlos."""
        with self.conexion() as con:
            return [f["lote_id"] for f in con.execute("SELECT lote_id FROM lotes WHERE estado != 'terminado'")]

    def estado(self) -> dict:
        return self.estado_basico(["lotes", "lote_items"])
