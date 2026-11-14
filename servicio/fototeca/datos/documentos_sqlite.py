"""Adaptador del puerto `AlmacenDocumentos` (C7): archivos en disco y metadatos, fichas y duplicados en SQLite.

- Fotos subidas: `data/fotos/<documento_id>.<ext>` (ya sin EXIF sensible: el guardrail lo quita antes).
- Fotos del archivo (XM3600): se referencian en su ruta original (`metadatos.ruta_relativa`), sin copiarlas.
- Normas cargadas por la API: `data/normas/<documento_id>.<ext>`.
- `documento_id` de una subida = `up-<sha256[:16]>`: subir dos veces el mismo archivo devuelve el mismo documento.
- `estado_archivo` guarda `version_archivo` (cambia al ingerir, eliminar o validar; invalida la caché de
  búsquedas) y `version_corpus`.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fototeca.datos.sqlite_base import BaseSqlite
from fototeca.dominio.entidades import DocumentoResumen
from fototeca.dominio.errores import NoEncontrado
from fototeca.dominio.esquemas_ficha import FichaRegistrada

EXTENSIONES = {"JPEG": "jpg", "PNG": "png"}


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DocumentosSqlite(BaseSqlite):
    ESQUEMA = """
    CREATE TABLE IF NOT EXISTS documentos (
        documento_id TEXT PRIMARY KEY,
        tipo TEXT NOT NULL,              -- foto | norma
        nombre TEXT NOT NULL,
        fecha TEXT NOT NULL,
        sha256 TEXT,
        particion TEXT,
        metadatos TEXT
    );
    CREATE TABLE IF NOT EXISTS fichas (
        documento_id TEXT PRIMARY KEY REFERENCES documentos(documento_id) ON DELETE CASCADE,
        estado TEXT NOT NULL,
        contenido TEXT NOT NULL,
        actualizada TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS duplicados (
        documento_id TEXT NOT NULL REFERENCES documentos(documento_id) ON DELETE CASCADE,
        similar_a TEXT NOT NULL REFERENCES documentos(documento_id) ON DELETE CASCADE,
        similitud REAL NOT NULL,
        detectado TEXT NOT NULL,
        PRIMARY KEY (documento_id, similar_a)
    );
    CREATE TABLE IF NOT EXISTS estado_archivo (
        clave TEXT PRIMARY KEY,
        valor TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_documentos_tipo ON documentos(tipo);
    CREATE INDEX IF NOT EXISTS ix_documentos_sha ON documentos(sha256);
    CREATE INDEX IF NOT EXISTS ix_fichas_estado ON fichas(estado);
    """

    def __init__(self, ruta_sqlite: Path | str, dir_fotos: Path | str, dir_datos: Path | str | None = None):
        super().__init__(ruta_sqlite)
        self.dir_fotos = Path(dir_fotos)
        self.dir_fotos.mkdir(parents=True, exist_ok=True)
        self.dir_datos = Path(dir_datos) if dir_datos else self.dir_fotos.parent
        self.dir_normas = self.dir_datos / "normas"

    # ── estado ──
    def estado(self) -> dict:
        base = self.estado_basico(["documentos", "fichas"])
        base["directorio_fotos_escribible"] = self.dir_fotos.exists() and _escribible(self.dir_fotos)
        if not base["directorio_fotos_escribible"]:
            base["estado"] = "error"
        return base

    def leer_estado(self, clave: str, por_defecto: str | None = None) -> str | None:
        with self.conexion() as con:
            fila = con.execute("SELECT valor FROM estado_archivo WHERE clave=?", (clave,)).fetchone()
        return fila["valor"] if fila else por_defecto

    def escribir_estado(self, clave: str, valor: str) -> None:
        with self.conexion() as con:
            con.execute("INSERT INTO estado_archivo (clave, valor) VALUES (?, ?) "
                        "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor", (clave, str(valor)))

    def version_archivo(self) -> int:
        return int(self.leer_estado("version_archivo", "0"))

    def incrementar_version_archivo(self) -> int:
        with self.conexion() as con:
            con.execute("BEGIN IMMEDIATE")
            fila = con.execute("SELECT valor FROM estado_archivo WHERE clave='version_archivo'").fetchone()
            nueva = int(fila["valor"]) + 1 if fila else 1
            con.execute("INSERT INTO estado_archivo (clave, valor) VALUES ('version_archivo', ?) "
                        "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor", (str(nueva),))
            con.execute("COMMIT")
        return nueva

    # ── documentos ──
    def guardar_foto(self, contenido: bytes, metadatos: dict) -> str:
        sha = hashlib.sha256(contenido).hexdigest()
        documento_id = metadatos.get("documento_id") or f"up-{sha[:16]}"
        if self.obtener_documento(documento_id):
            return documento_id
        meta = {k: v for k, v in metadatos.items() if k != "documento_id"}
        if not meta.get("ruta_relativa"):
            ext = EXTENSIONES.get(str(meta.get("formato", "JPEG")).upper(), "jpg")
            ruta = self.dir_fotos / f"{documento_id}.{ext}"
            ruta.write_bytes(contenido)
            meta["ruta_relativa"] = str(ruta.relative_to(self.dir_datos))
        self._insertar(documento_id, "foto", meta.get("nombre") or documento_id, sha, meta.get("particion", "subida"), meta)
        return documento_id

    def guardar_documento(self, documento_id: str, tipo: str, nombre: str, contenido: bytes | None,
                          metadatos: dict, extension: str = "bin") -> str:
        meta = dict(metadatos)
        sha = hashlib.sha256(contenido).hexdigest() if contenido is not None else None
        if contenido is not None and not meta.get("ruta_relativa"):
            self.dir_normas.mkdir(parents=True, exist_ok=True)
            ruta = self.dir_normas / f"{documento_id}.{extension}"
            ruta.write_bytes(contenido)
            meta["ruta_relativa"] = str(ruta.relative_to(self.dir_datos))
        self._insertar(documento_id, tipo, nombre, sha, meta.get("particion"), meta)
        return documento_id

    def guardar_lote(self, documentos: list[dict]) -> None:
        """Alta masiva (indexado del archivo): [{documento_id, tipo, nombre, sha256, particion, metadatos}]."""
        with self.conexion() as con:
            con.execute("BEGIN")
            con.executemany(
                "INSERT INTO documentos (documento_id, tipo, nombre, fecha, sha256, particion, metadatos) "
                "VALUES (?,?,?,?,?,?,?) ON CONFLICT(documento_id) DO UPDATE SET nombre=excluded.nombre, "
                "sha256=excluded.sha256, particion=excluded.particion, metadatos=excluded.metadatos",
                [(d["documento_id"], d["tipo"], d["nombre"], ahora(), d.get("sha256"), d.get("particion"),
                  json.dumps(d.get("metadatos", {}), ensure_ascii=False)) for d in documentos])
            con.execute("COMMIT")

    def _insertar(self, documento_id, tipo, nombre, sha, particion, meta) -> None:
        with self.conexion() as con:
            con.execute("INSERT OR IGNORE INTO documentos (documento_id, tipo, nombre, fecha, sha256, particion, metadatos)"
                        " VALUES (?,?,?,?,?,?,?)",
                        (documento_id, tipo, nombre, ahora(), sha, particion, json.dumps(meta, ensure_ascii=False)))

    def obtener_documento(self, documento_id: str) -> dict | None:
        with self.conexion() as con:
            f = con.execute("SELECT * FROM documentos WHERE documento_id=?", (documento_id,)).fetchone()
        if not f:
            return None
        return {"documento_id": f["documento_id"], "tipo": f["tipo"], "nombre": f["nombre"], "fecha": f["fecha"],
                "sha256": f["sha256"], "particion": f["particion"], "metadatos": json.loads(f["metadatos"] or "{}")}

    def buscar_por_sha(self, sha256: str) -> str | None:
        with self.conexion() as con:
            f = con.execute("SELECT documento_id FROM documentos WHERE sha256=? LIMIT 1", (sha256,)).fetchone()
        return f["documento_id"] if f else None

    def ruta_foto(self, documento_id: str) -> Path:
        doc = self.obtener_documento(documento_id)
        if not doc or doc["tipo"] != "foto":
            raise NoEncontrado("La foto no existe.", documento_id=documento_id)
        return self.dir_datos / doc["metadatos"]["ruta_relativa"]

    def obtener_foto(self, documento_id: str) -> bytes:
        ruta = self.ruta_foto(documento_id)
        if not ruta.exists():
            raise NoEncontrado("El archivo de la foto no está en el almacén.", documento_id=documento_id)
        return ruta.read_bytes()

    def listar(self, tipo: str | None, pagina: int, por_pagina: int) -> list[DocumentoResumen]:
        # El titular y el texto alternativo salen de la ficha guardada (vacío → None): así la web no pide una ficha
        # por cada miniatura del listado.
        sql = ("SELECT d.documento_id, d.tipo, d.nombre, d.fecha, d.particion, f.estado,"
               " NULLIF(json_extract(f.contenido, '$.ficha.titular'), '') AS titular,"
               " NULLIF(json_extract(f.contenido, '$.ficha.texto_alternativo'), '') AS texto_alternativo"
               " FROM documentos d LEFT JOIN fichas f ON f.documento_id = d.documento_id")
        args: list = []
        if tipo:
            sql += " WHERE d.tipo=?"
            args.append(tipo)
        sql += " ORDER BY d.fecha DESC, d.documento_id LIMIT ? OFFSET ?"
        args += [int(por_pagina), int((pagina - 1) * por_pagina)]
        with self.conexion() as con:
            filas = con.execute(sql, args).fetchall()
        return [DocumentoResumen(f["documento_id"], f["tipo"], f["nombre"], f["fecha"], f["estado"], f["particion"],
                                 titular=f["titular"], texto_alternativo=f["texto_alternativo"])
                for f in filas]

    def contar(self, tipo: str | None = None) -> int:
        with self.conexion() as con:
            if tipo:
                return con.execute("SELECT COUNT(*) FROM documentos WHERE tipo=?", (tipo,)).fetchone()[0]
            return con.execute("SELECT COUNT(*) FROM documentos").fetchone()[0]

    def eliminar(self, documento_id: str) -> None:
        doc = self.obtener_documento(documento_id)
        if not doc:
            raise NoEncontrado("El documento no existe.", documento_id=documento_id)
        ruta = doc["metadatos"].get("ruta_relativa")
        if ruta:
            archivo = self.dir_datos / ruta
            # Solo se borran archivos propios del almacén (subidas y normas), nunca los datos crudos del corpus.
            if archivo.exists() and (self.dir_fotos in archivo.parents or self.dir_normas in archivo.parents):
                archivo.unlink()
        with self.conexion() as con:
            con.execute("DELETE FROM documentos WHERE documento_id=?", (documento_id,))

    # ── fichas ──
    def guardar_ficha(self, documento_id: str, ficha: FichaRegistrada) -> None:
        registro = ficha.model_copy(update={"actualizada": ahora()})
        with self.conexion() as con:
            con.execute("INSERT INTO fichas (documento_id, estado, contenido, actualizada) VALUES (?,?,?,?) "
                        "ON CONFLICT(documento_id) DO UPDATE SET estado=excluded.estado, contenido=excluded.contenido,"
                        " actualizada=excluded.actualizada",
                        (documento_id, registro.ficha.estado, registro.model_dump_json(), registro.actualizada))

    def guardar_fichas_lote(self, fichas: list[FichaRegistrada]) -> None:
        marca = ahora()
        with self.conexion() as con:
            con.execute("BEGIN")
            con.executemany(
                "INSERT INTO fichas (documento_id, estado, contenido, actualizada) VALUES (?,?,?,?) "
                "ON CONFLICT(documento_id) DO UPDATE SET estado=excluded.estado, contenido=excluded.contenido, "
                "actualizada=excluded.actualizada",
                [(f.documento_id, f.ficha.estado, f.model_copy(update={"actualizada": marca}).model_dump_json(), marca)
                 for f in fichas])
            con.execute("COMMIT")

    def obtener_ficha(self, documento_id: str) -> FichaRegistrada | None:
        with self.conexion() as con:
            f = con.execute("SELECT contenido FROM fichas WHERE documento_id=?", (documento_id,)).fetchone()
        return FichaRegistrada.model_validate_json(f["contenido"]) if f else None

    def contar_fichas(self) -> dict[str, int]:
        with self.conexion() as con:
            filas = con.execute("SELECT estado, COUNT(*) AS n FROM fichas f JOIN documentos d "
                                "ON d.documento_id=f.documento_id WHERE d.tipo='foto' GROUP BY estado").fetchall()
        return {f["estado"]: f["n"] for f in filas}

    def estadisticas_accesibilidad(self) -> dict:
        """Cuántas fotos tienen texto alternativo validado, cuántas requieren revisión y cuántas no tienen ficha."""
        with self.conexion() as con:
            fila = con.execute("""
                SELECT COUNT(*) AS fotos,
                       SUM(CASE WHEN f.estado = 'validada' AND COALESCE(json_extract(f.contenido, '$.ficha.texto_alternativo'), '') != ''
                                THEN 1 ELSE 0 END) AS alt_validado,
                       SUM(CASE WHEN f.estado = 'requiere_revision' THEN 1 ELSE 0 END) AS requiere_revision,
                       SUM(CASE WHEN f.estado = 'borrador' THEN 1 ELSE 0 END) AS borrador,
                       SUM(CASE WHEN f.documento_id IS NULL THEN 1 ELSE 0 END) AS sin_ficha
                FROM documentos d LEFT JOIN fichas f ON f.documento_id = d.documento_id
                WHERE d.tipo = 'foto'""").fetchone()
        return {k: int(fila[k] or 0) for k in ("fotos", "alt_validado", "requiere_revision", "borrador", "sin_ficha")}

    # ── duplicados ──
    def registrar_duplicado(self, documento_id: str, similar_a: str, similitud: float) -> None:
        with self.conexion() as con:
            con.execute("INSERT INTO duplicados (documento_id, similar_a, similitud, detectado) VALUES (?,?,?,?) "
                        "ON CONFLICT(documento_id, similar_a) DO UPDATE SET similitud=excluded.similitud",
                        (documento_id, similar_a, float(similitud), ahora()))

    def listar_duplicados(self) -> list[dict]:
        with self.conexion() as con:
            filas = con.execute("SELECT * FROM duplicados ORDER BY detectado DESC").fetchall()
        return [dict(f) for f in filas]


def _escribible(directorio: Path) -> bool:
    # Un archivo temporal con nombre único por sondeo: con un nombre fijo, dos /health simultáneos se borraban el
    # archivo de prueba entre sí y uno respondía 503 con el almacén en error.
    try:
        with tempfile.TemporaryFile(dir=directorio) as prueba:
            prueba.write(b"ok")
        return True
    except OSError:
        return False
