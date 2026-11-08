"""Adaptador SQLite del puerto `AlmacenRetroalimentacion` de T2 (tabla `retroalimentacion`)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fototeca.datos.sqlite_base import BaseSqlite
from fototeca.retroalimentacion.puertos import RegistroRetroalimentacion


class RetroalimentacionSqlite(BaseSqlite):
    ESQUEMA = """
    CREATE TABLE IF NOT EXISTS retroalimentacion (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        traza_id TEXT NOT NULL,
        documento_id TEXT,
        util INTEGER,
        comentario TEXT,
        correcciones TEXT,
        validar_ficha INTEGER NOT NULL DEFAULT 0,
        ruta TEXT,
        modelos TEXT
    );
    CREATE INDEX IF NOT EXISTS ix_retro_traza ON retroalimentacion(traza_id);
    """

    def guardar(self, registro: RegistroRetroalimentacion) -> int:
        ts = registro.ts or datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.conexion() as con:
            cur = con.execute(
                "INSERT INTO retroalimentacion (ts, traza_id, documento_id, util, comentario, correcciones,"
                " validar_ficha, ruta, modelos) VALUES (?,?,?,?,?,?,?,?,?)",
                (ts, registro.traza_id, registro.documento_id,
                 None if registro.util is None else int(registro.util), registro.comentario,
                 json.dumps(registro.correcciones or {}, ensure_ascii=False), int(registro.validar_ficha),
                 registro.ruta, json.dumps(registro.modelos or {}, ensure_ascii=False)),
            )
            return int(cur.lastrowid)

    def listar(self, desde: str | None = None) -> list[RegistroRetroalimentacion]:
        sql, args = "SELECT * FROM retroalimentacion", []
        if desde:
            sql += " WHERE ts >= ?"
            args.append(desde)
        with self.conexion() as con:
            filas = con.execute(sql + " ORDER BY id", args).fetchall()
        return [RegistroRetroalimentacion(
            id=f["id"], ts=f["ts"], traza_id=f["traza_id"], documento_id=f["documento_id"],
            util=None if f["util"] is None else bool(f["util"]), comentario=f["comentario"],
            correcciones=json.loads(f["correcciones"] or "{}"), validar_ficha=bool(f["validar_ficha"]),
            ruta=f["ruta"], modelos=json.loads(f["modelos"] or "{}")) for f in filas]

    def estado(self) -> dict:
        return self.estado_basico(["retroalimentacion"])
