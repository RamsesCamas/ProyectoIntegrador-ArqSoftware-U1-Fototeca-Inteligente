"""Flujo de ingesta (C2): fotos y documentos normativos.

Foto: RECIBIR → GUARDRAILS_ENTRADA (archivo_valido, exif_privacidad[, fuera_de_dominio en H5]) → DUPLICADO
EXACTO (sha256) → GUARDAR → EMBEDDING DE IMAGEN → CASI DUPLICADOS (fotos_img ≥ τ_dup) → INDEXAR →
version_archivo++ (invalida la caché de búsquedas).

Norma (HTML, Markdown, PDF o TXT): RECIBIR → FRAGMENTAR (una regla por fragmento) → EMBEDDINGS → INDEXAR en
`normas` → nueva versión del corpus (invalida las fichas en caché).
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from fototeca.contexto.fragmentador import FORMATOS_NORMA, fragmentar_documento
from fototeca.datos.puertos import AlmacenCache, AlmacenDocumentos, AlmacenVectorial, Embebedor
from fototeca.dominio import colecciones as col
from fototeca.dominio.configuracion import Configuracion
from fototeca.dominio.errores import ArchivoDemasiadoGrande, FormatoNoSoportado, NoEncontrado
from fototeca.guardrails.entrada.archivo import verificar_archivo
from fototeca.guardrails.entrada.exif import sanitizar
from fototeca.observabilidad.registro import medir, registrar


@dataclass
class ResultadoIngesta:
    documento_id: str
    nombre: str
    tipo: str
    fragmentos: int
    ya_existia: bool = False
    duplicados: list[dict] = field(default_factory=list)
    guardrails: list[dict] = field(default_factory=list)
    version_archivo: int | None = None


class FlujoIngesta:
    def __init__(self, config: Configuracion, documentos: AlmacenDocumentos, vectorial: AlmacenVectorial,
                 embebedor: Embebedor, cache: AlmacenCache | None = None, verificador_dominio=None):
        self.config = config
        self.documentos = documentos
        self.vectorial = vectorial
        self.embebedor = embebedor
        self.cache = cache
        self.verificador_dominio = verificador_dominio   # guardrail fuera_de_dominio (H5)

    # ───────────────────────────── fotos ─────────────────────────────
    def ingerir_foto(self, contenido: bytes, nombre: str, metadatos: dict | None = None) -> ResultadoIngesta:
        p = self.config.parametro
        guardrails: list[dict] = []
        with medir("C3", "guardrails_entrada", tipo="foto") as d:
            imagen, r_archivo = verificar_archivo(contenido, p("guardrails.tamano_max_mb", 10),
                                                  p("guardrails.lado_min_px", 64), p("guardrails.lado_max_px", 12000))
            limpio, r_exif = sanitizar(contenido, imagen.formato)
            guardrails += [r_archivo.a_dict(), r_exif.a_dict()]
            d["resultado"] = r_exif.resultado
        sha = hashlib.sha256(limpio).hexdigest()
        existente = self.documentos.buscar_por_sha(sha)
        if existente:
            registrar("C2", "ingesta_duplicado_exacto", documento_id=existente)
            return ResultadoIngesta(existente, nombre, "foto", 1, ya_existia=True, guardrails=guardrails,
                                    duplicados=[{"documento_id": existente, "similitud": 1.0, "tipo": "exacto"}],
                                    version_archivo=self.documentos.version_archivo())
        with medir("C7", "embedding_imagen", modelo=self.embebedor.nombre_modelo):
            vector = self.embebedor.embeber_imagenes([limpio])[0]
        if self.verificador_dominio is not None:
            guardrails.append(self.verificador_dominio(vector).a_dict())   # bloquea con 422 si no es foto
        with medir("C7", "guardar_foto"):
            documento_id = self.documentos.guardar_foto(limpio, {
                **(metadatos or {}), "nombre": nombre, "formato": imagen.formato, "ancho": imagen.ancho,
                "alto": imagen.alto, "tamano_bytes": len(limpio), "particion": "subida",
                "exif_eliminado": r_exif.detalle.get("eliminado", [])})
        tau = float(p("cache.fichas.tau_dup", 0.97))
        self.vectorial.asegurar_coleccion(col.FOTOS_IMG, len(vector))
        with medir("C5", "detectar_duplicados") as d:
            vecinos = self.vectorial.buscar(col.FOTOS_IMG, vector, k=5, filtro={"documento_id": {"no": documento_id}})
            duplicados = [{"documento_id": v.carga.get("documento_id", v.id), "similitud": round(v.puntaje, 4),
                           "tipo": "semantico"} for v in vecinos if v.puntaje >= tau]
            for dup in duplicados:
                self.documentos.registrar_duplicado(documento_id, dup["documento_id"], dup["similitud"])
            d.update(encontrados=len(duplicados), umbral=tau)
        version = self.documentos.version_archivo() + 1
        with medir("C7", "indexar_foto"):
            self.vectorial.insertar(col.FOTOS_IMG, [documento_id], vector[None, :],
                                    [{"documento_id": documento_id, "particion": "subida", "validada": False,
                                      "locale": None, "version_archivo": version}])
        version = self.documentos.incrementar_version_archivo()
        registrar("C2", "ingesta_foto", documento_id=documento_id, duplicados=len(duplicados), version_archivo=version)
        return ResultadoIngesta(documento_id, nombre, "foto", 1, duplicados=duplicados, guardrails=guardrails,
                                version_archivo=version)

    def miniatura(self, documento_id: str, lado: int = 512) -> bytes:
        """JPEG de 512 px como máximo y sin EXIF (para la web)."""
        cache = Path(self.config.rutas["datos"]) / "miniaturas" / f"{documento_id}_{lado}.jpg"
        if cache.exists():
            return cache.read_bytes()
        contenido = self.documentos.obtener_foto(documento_id)
        with Image.open(io.BytesIO(contenido)) as im:
            im = im.convert("RGB")
            im.thumbnail((lado, lado))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)   # sin el parámetro exif: la miniatura sale sin metadatos
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(buf.getvalue())
        return buf.getvalue()

    # ───────────────────────────── normas ─────────────────────────────
    def ingerir_norma(self, contenido: bytes, nombre: str, metadatos: dict | None = None) -> ResultadoIngesta:
        meta = metadatos or {}
        maximo = float(self.config.parametro("guardrails.tamano_max_mb", 10))
        if len(contenido) > maximo * 1024 * 1024:
            raise ArchivoDemasiadoGrande(f"El documento supera {maximo:g} MB.")
        extension = Path(nombre).suffix.lower().lstrip(".")
        if extension not in FORMATOS_NORMA:
            raise FormatoNoSoportado("Las normas se aceptan en HTML, Markdown, PDF o TXT.")
        if extension == "pdf" and not contenido.startswith(b"%PDF"):
            raise FormatoNoSoportado("El contenido no es un PDF válido.")
        sha = hashlib.sha256(contenido).hexdigest()
        documento_id = f"norma-{sha[:12]}"
        if self.documentos.obtener_documento(documento_id):
            return ResultadoIngesta(documento_id, nombre, "norma", int(self.documentos.obtener_documento(
                documento_id)["metadatos"].get("fragmentos", 0)), ya_existia=True)
        version_corpus = hashlib.sha256(f"{self.version_corpus()}+{sha}".encode()).hexdigest()[:12]
        base = {"id": documento_id, "documento_id": documento_id, "fuente": meta.get("fuente", nombre),
                "url": meta.get("url", f"subida:{nombre}"), "licencia": meta.get("licencia", "indicada por quien la cargó"),
                "campo_iptc": meta.get("campo_iptc"), "version_corpus": version_corpus}
        with medir("C5", "fragmentar_norma", formato=extension) as d:
            fragmentos = fragmentar_documento(contenido, extension, base)
            d["fragmentos"] = len(fragmentos)
        if not fragmentos:
            raise FormatoNoSoportado("El documento no tiene texto que se pueda fragmentar.")
        with medir("C7", "embedding_texto", modelo=self.embebedor.nombre_modelo, n=len(fragmentos)):
            vectores = self.embebedor.embeber_textos([f["texto"] for f in fragmentos], rol="documento")
        self.vectorial.asegurar_coleccion(col.NORMAS, self.embebedor.dimension)
        self.vectorial.insertar(col.NORMAS, [f["id"] for f in fragmentos], vectores,
                                [{k: v for k, v in f.items() if k != "id"} for f in fragmentos])
        self.documentos.guardar_documento(documento_id, "norma", nombre, contenido,
                                          {**meta, "fragmentos": len(fragmentos), "formato": extension}, extension)
        self.documentos.escribir_estado("version_corpus", version_corpus)
        registrar("C2", "ingesta_norma", documento_id=documento_id, fragmentos=len(fragmentos), version_corpus=version_corpus)
        return ResultadoIngesta(documento_id, nombre, "norma", len(fragmentos))

    def version_corpus(self) -> str:
        return self.documentos.leer_estado("version_corpus", "sin_corpus") or "sin_corpus"

    # ───────────────────────────── eliminación ─────────────────────────────
    def eliminar(self, documento_id: str) -> dict:
        doc = self.documentos.obtener_documento(documento_id)
        if not doc:
            raise NoEncontrado("El documento no existe.", documento_id=documento_id)
        colecciones = (col.NORMAS,) if doc["tipo"] == "norma" else (col.FOTOS_IMG, col.FOTOS_TXT,
                                                                   col.FOTOS_TXT_GRANITE, col.FOTOS_DESC_QWEN)
        vectores = 0
        with medir("C7", "eliminar_vectores") as d:
            for c in colecciones:
                antes = self.vectorial.contar(c, {"documento_id": documento_id})
                if antes:
                    self.vectorial.eliminar_por_documento(c, documento_id)
                    vectores += antes
            d["vectores"] = vectores
        invalidadas = 0
        if self.cache is not None:
            with medir("C4", "invalidar", etiqueta=f"doc:{documento_id}") as d:
                invalidadas = self.cache.invalidar_por_etiqueta(f"doc:{documento_id}")
                d["entradas"] = invalidadas
        self.documentos.eliminar(documento_id)
        miniaturas = Path(self.config.rutas["datos"]) / "miniaturas"
        for m in miniaturas.glob(f"{documento_id}_*.jpg"):
            m.unlink(missing_ok=True)
        if doc["tipo"] == "norma":
            nueva = hashlib.sha256(f"{self.version_corpus()}-{documento_id}".encode()).hexdigest()[:12]
            self.documentos.escribir_estado("version_corpus", nueva)
        version = self.documentos.incrementar_version_archivo()
        registrar("C2", "eliminacion", documento_id=documento_id, vectores=vectores, cache=invalidadas)
        return {"documento_id": documento_id, "eliminado": True, "vectores_eliminados": vectores,
                "entradas_cache_invalidadas": invalidadas, "version_archivo": version}
