"""`archivo_valido`: el contenido real (no la extensión) es JPEG o PNG, pesa 10 MB o menos y mide entre 64 y
12,000 px por lado. Política: bloquear (413, 415 o 422) con un mensaje seguro."""
from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from fototeca.dominio.errores import ArchivoDemasiadoGrande, BloqueadoPorGuardrail, FormatoNoSoportado
from fototeca.guardrails.politicas import MENSAJES_SEGUROS, politica
from fototeca.guardrails.resultado import ResultadoGuardrail

FORMATOS = {"JPEG", "PNG"}
Image.MAX_IMAGE_PIXELS = 12000 * 12000  # el límite de lado lo aplica esta verificación


@dataclass
class ImagenValidada:
    formato: str
    ancho: int
    alto: int
    tamano_bytes: int


def verificar_archivo(contenido: bytes, max_mb: float = 10, lado_min: int = 64,
                      lado_max: int = 12000) -> tuple[ImagenValidada, ResultadoGuardrail]:
    tamano = len(contenido)
    if tamano > max_mb * 1024 * 1024:
        raise ArchivoDemasiadoGrande(f"El archivo pesa {tamano / 2**20:.1f} MB; el máximo es {max_mb:g} MB.")
    try:
        with Image.open(io.BytesIO(contenido)) as im:
            formato, (ancho, alto) = im.format, im.size
            im.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as e:
        raise FormatoNoSoportado("El contenido no es una imagen JPEG o PNG válida.") from e
    if formato not in FORMATOS:
        raise FormatoNoSoportado(f"Formato {formato} no soportado: solo JPEG o PNG.")
    if min(ancho, alto) < lado_min or max(ancho, alto) > lado_max:
        r = ResultadoGuardrail("archivo_valido", "bloqueada", valor=float(max(ancho, alto)),
                               politica_aplicada=politica("archivo_valido"),
                               detalle={"ancho": ancho, "alto": alto, "limites_px": [lado_min, lado_max]})
        raise BloqueadoPorGuardrail(MENSAJES_SEGUROS["archivo_valido"], [r.a_dict()])
    return (ImagenValidada(formato, ancho, alto, tamano),
            ResultadoGuardrail("archivo_valido", "aprobada", detalle={"formato": formato, "ancho": ancho, "alto": alto}))
