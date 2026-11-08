"""Adaptador del puerto `AlmacenCache` (C7) en SQLite (ADR-09).

- Entradas con espacio (`fichas` | `busquedas`), valor JSON, TTL y etiquetas para invalidar (`doc:<id>`,
  `corpus:<versión>`, `config:<versión>`).
- Caché semántica: los vectores viven en la misma tabla; la búsqueda es lineal en numpy sobre las entradas
  vigentes del espacio, suficiente para menos de 10,000 entradas (ADR-04). Sin Redis: ahorra memoria.
"""
from __future__ import annotations

import json
import time

import numpy as np

from fototeca.datos.sqlite_base import BaseSqlite
from fototeca.dominio.entidades import EntradaCache


class CacheSqlite(BaseSqlite):
    ESQUEMA = """
    CREATE TABLE IF NOT EXISTS cache (
        clave TEXT PRIMARY KEY,
        espacio TEXT NOT NULL,           -- fichas | busquedas
        valor TEXT NOT NULL,
        creada REAL NOT NULL,
        expira REAL NOT NULL,
        vector BLOB
    );
    CREATE TABLE IF NOT EXISTS cache_etiquetas (
        clave TEXT NOT NULL REFERENCES cache(clave) ON DELETE CASCADE,
        etiqueta TEXT NOT NULL,
        PRIMARY KEY (clave, etiqueta)
    );
    CREATE INDEX IF NOT EXISTS ix_cache_espacio ON cache(espacio);
    CREATE INDEX IF NOT EXISTS ix_cache_etiqueta ON cache_etiquetas(etiqueta);
    """

    def estado(self) -> dict:
        base = self.estado_basico(["cache"])
        if base.get("estado") == "ok":
            with self.conexion() as con:
                filas = con.execute("SELECT espacio, COUNT(*) n FROM cache WHERE expira > ? GROUP BY espacio",
                                    (time.time(),)).fetchall()
            base["vigentes_por_espacio"] = {f["espacio"]: f["n"] for f in filas}
        return base

    def _entrada(self, f, similitud: float | None = None) -> EntradaCache:
        with self.conexion() as con:
            etiquetas = [e["etiqueta"] for e in con.execute("SELECT etiqueta FROM cache_etiquetas WHERE clave=?",
                                                            (f["clave"],)).fetchall()]
        return EntradaCache(clave=f["clave"], espacio=f["espacio"], valor=json.loads(f["valor"]), creada=f["creada"],
                            expira=f["expira"], etiquetas=etiquetas, similitud=similitud)

    def obtener(self, clave: str) -> EntradaCache | None:
        with self.conexion() as con:
            f = con.execute("SELECT * FROM cache WHERE clave=? AND expira > ?", (clave, time.time())).fetchone()
        return self._entrada(f) if f else None

    def guardar(self, clave: str, valor: dict, ttl_s: int, etiquetas: list[str],
                vector: np.ndarray | None = None, espacio: str = "fichas") -> None:
        ahora = time.time()
        blob = None if vector is None else np.asarray(vector, dtype=np.float32).tobytes()
        with self.conexion() as con:
            con.execute("BEGIN")
            con.execute("INSERT INTO cache (clave, espacio, valor, creada, expira, vector) VALUES (?,?,?,?,?,?) "
                        "ON CONFLICT(clave) DO UPDATE SET espacio=excluded.espacio, valor=excluded.valor, "
                        "creada=excluded.creada, expira=excluded.expira, vector=excluded.vector",
                        (clave, espacio, json.dumps(valor, ensure_ascii=False, default=str), ahora, ahora + ttl_s, blob))
            con.execute("DELETE FROM cache_etiquetas WHERE clave=?", (clave,))
            con.executemany("INSERT OR IGNORE INTO cache_etiquetas (clave, etiqueta) VALUES (?,?)",
                            [(clave, e) for e in dict.fromkeys(etiquetas)])
            con.execute("COMMIT")

    def buscar_semantica(self, espacio: str, vector: np.ndarray, umbral: float,
                         etiqueta_requerida: str | None = None) -> EntradaCache | None:
        sql = "SELECT * FROM cache c WHERE espacio=? AND expira > ? AND vector IS NOT NULL"
        args: list = [espacio, time.time()]
        if etiqueta_requerida:
            sql += " AND EXISTS (SELECT 1 FROM cache_etiquetas e WHERE e.clave=c.clave AND e.etiqueta=?)"
            args.append(etiqueta_requerida)
        with self.conexion() as con:
            filas = con.execute(sql, args).fetchall()
        if not filas:
            return None
        matriz = np.stack([np.frombuffer(f["vector"], dtype=np.float32) for f in filas])
        sims = matriz @ np.asarray(vector, dtype=np.float32).ravel()
        mejor = int(np.argmax(sims))
        if float(sims[mejor]) < umbral:
            return None
        return self._entrada(filas[mejor], similitud=round(float(sims[mejor]), 4))

    def invalidar_por_etiqueta(self, etiqueta: str) -> int:
        with self.conexion() as con:
            con.execute("BEGIN")
            claves = [f["clave"] for f in con.execute("SELECT clave FROM cache_etiquetas WHERE etiqueta=?", (etiqueta,))]
            if claves:
                con.executemany("DELETE FROM cache WHERE clave=?", [(c,) for c in claves])
            con.execute("COMMIT")
        return len(claves)

    def purgar_expirados(self) -> int:
        with self.conexion() as con:
            return con.execute("DELETE FROM cache WHERE expira <= ?", (time.time(),)).rowcount

    def vaciar(self) -> int:
        with self.conexion() as con:
            return con.execute("DELETE FROM cache").rowcount
