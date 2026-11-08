"""Adaptador SQLite del puerto `SumideroEventos` de T1 (tabla `eventos`)."""
from __future__ import annotations

import json

from fototeca.datos.sqlite_base import BaseSqlite
from fototeca.observabilidad.puertos import EventoCapa


class EventosSqlite(BaseSqlite):
    ESQUEMA = """
    CREATE TABLE IF NOT EXISTS eventos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        traza_id TEXT,
        capa TEXT NOT NULL,
        evento TEXT NOT NULL,
        duracion_ms REAL,
        modelo TEXT,
        ruta TEXT,
        cache TEXT,
        guardrail TEXT,
        resultado TEXT,
        detalle TEXT
    );
    CREATE INDEX IF NOT EXISTS ix_eventos_traza ON eventos(traza_id);
    CREATE INDEX IF NOT EXISTS ix_eventos_ts ON eventos(ts);
    CREATE INDEX IF NOT EXISTS ix_eventos_capa_evento ON eventos(capa, evento);
    """

    def registrar(self, evento: EventoCapa) -> None:
        with self.conexion() as con:
            con.execute(
                "INSERT INTO eventos (ts, traza_id, capa, evento, duracion_ms, modelo, ruta, cache, guardrail,"
                " resultado, detalle) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (evento.ts, evento.traza_id, evento.capa, evento.evento, evento.duracion_ms, evento.modelo,
                 evento.ruta, evento.cache, evento.guardrail, evento.resultado,
                 json.dumps(evento.detalle or {}, ensure_ascii=False, default=str)),
            )

    def consultar(self, desde: str | None = None, traza_id: str | None = None,
                  limite: int | None = None) -> list[EventoCapa]:
        sql, args = "SELECT * FROM eventos WHERE 1=1", []
        if desde:
            sql += " AND ts >= ?"
            args.append(desde)
        if traza_id:
            sql += " AND traza_id = ?"
            args.append(traza_id)
        sql += " ORDER BY id"
        if limite:
            sql += " LIMIT ?"
            args.append(int(limite))
        with self.conexion() as con:
            filas = con.execute(sql, args).fetchall()
        return [EventoCapa(ts=f["ts"], traza_id=f["traza_id"], capa=f["capa"], evento=f["evento"],
                           duracion_ms=f["duracion_ms"], modelo=f["modelo"], ruta=f["ruta"], cache=f["cache"],
                           guardrail=f["guardrail"], resultado=f["resultado"],
                           detalle=json.loads(f["detalle"] or "{}")) for f in filas]

    def estado(self) -> dict:
        return self.estado_basico(["eventos"])
