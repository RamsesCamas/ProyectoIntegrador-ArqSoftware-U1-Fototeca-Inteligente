"""Imágenes (C7): el paso intermedio HEIC → JPEG y la preparación para los modelos (orientación EXIF, RGB y lado
máximo, en JPEG).

Las fotos de iPhone llegan en HEIC (HEIF con HEVC): el navegador las sube tal cual. `pi-heif` (solo decodifica:
libheif con libde265, sin codificadores) registra el formato en Pillow al importar este módulo. `heif_a_jpeg`
convierte la foto a JPEG antes de guardarla o de buscar con ella; desde ahí, los guardrails, los modelos y las
miniaturas trabajan con un JPEG como con cualquier otra foto. La orientación ya viene aplicada: libheif rota la imagen
al decodificarla y pi-heif deja la orientación EXIF en 1, así que `exif_transpose` no la gira dos veces.
"""
from __future__ import annotations

import io

from PIL import Image, ImageOps
from pi_heif import register_heif_opener

register_heif_opener()   # Pillow abre HEIC/HEIF; nunca se escribe HEIC (pi-heif no trae codificador)

FORMATOS_HEIF = frozenset({"HEIF"})   # el nombre que Pillow da a HEIC/HEIF con pi-heif


def heif_a_jpeg(contenido: bytes, calidad: int = 92) -> tuple[bytes, tuple[int, int]]:
    """HEIC/HEIF → JPEG en RGB, orientado y SIN metadatos (ni EXIF ni XMP); solo conserva el perfil de color, que
    no es sensible. Devuelve el JPEG y sus medidas (ancho, alto)."""
    with Image.open(io.BytesIO(contenido)) as im:
        perfil = im.info.get("icc_profile")
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.info.clear()   # Pillow escribiría el XMP de `info` en el JPEG; sin `exif=` tampoco lleva EXIF
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=calidad, icc_profile=perfil)
        return buf.getvalue(), im.size


def preparar_imagen(contenido: bytes, lado_max: int, calidad: int = 90) -> bytes:
    with Image.open(io.BytesIO(contenido)) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((lado_max, lado_max))
        im.info.clear()
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=calidad)
        return buf.getvalue()
