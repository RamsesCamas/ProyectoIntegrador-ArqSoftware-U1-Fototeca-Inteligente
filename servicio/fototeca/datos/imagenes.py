"""Preparación de imágenes para los modelos (C7): orientación EXIF, RGB y lado máximo, en JPEG."""
from __future__ import annotations

import io

from PIL import Image, ImageOps


def preparar_imagen(contenido: bytes, lado_max: int, calidad: int = 90) -> bytes:
    with Image.open(io.BytesIO(contenido)) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((lado_max, lado_max))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=calidad)
        return buf.getvalue()
