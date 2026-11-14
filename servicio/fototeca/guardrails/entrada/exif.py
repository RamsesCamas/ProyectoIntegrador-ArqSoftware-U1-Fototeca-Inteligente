"""`exif_privacidad`: detecta GPS, número de serie y datos del autor y los quita ANTES de guardar.

- JPEG: se editan los segmentos sin recomprimir. Con piexif se borra el IFD de GPS y las etiquetas de autor y
  número de serie. Además se eliminan los segmentos XMP (APP1) e IPTC/Photoshop (APP13), que pueden repetir la
  ubicación o el autor.
- PNG: se vuelve a guardar sin metadatos (sin pérdida: PNG no recomprime con pérdida).
- HEIC/HEIF (fotos de iPhone): el paso intermedio la convierte a JPEG (`datos/imagenes.heif_a_jpeg`) sin ningún
  metadato. Se anota qué datos sensibles traía (el iPhone guarda el GPS si la ubicación está activa) y que se
  convirtió; la HEIC original nunca se guarda.
Política: sanitizar y continuar, dejando constancia en la traza.
"""
from __future__ import annotations

import io

import piexif
from PIL import Image

from fototeca.datos.imagenes import FORMATOS_HEIF, heif_a_jpeg
from fototeca.dominio.errores import FormatoNoSoportado
from fototeca.guardrails.politicas import politica
from fototeca.guardrails.resultado import ResultadoGuardrail

ETIQUETAS_0TH = {piexif.ImageIFD.Artist: "autor", piexif.ImageIFD.Copyright: "autor",
                 piexif.ImageIFD.XPAuthor: "autor", piexif.ImageIFD.CameraSerialNumber: "numero_serie"}
ETIQUETAS_EXIF = {piexif.ExifIFD.BodySerialNumber: "numero_serie", piexif.ExifIFD.LensSerialNumber: "numero_serie",
                  piexif.ExifIFD.CameraOwnerName: "autor", piexif.ExifIFD.ImageUniqueID: "identificador"}
_XMP = b"http://ns.adobe.com/xap/1.0/\x00"


def _quitar_segmentos(jpeg: bytes) -> tuple[bytes, list[str]]:
    """Quita APP1-XMP y APP13 de un JPEG recorriendo sus marcadores (sin decodificar la imagen)."""
    if jpeg[:2] != b"\xff\xd8":
        return jpeg, []
    salida, quitados, i = bytearray(jpeg[:2]), [], 2
    while i + 4 <= len(jpeg) and jpeg[i] == 0xFF:
        marcador = jpeg[i + 1]
        if marcador in (0xD9, 0xDA):  # fin de imagen o inicio de datos comprimidos: se copia el resto
            break
        largo = int.from_bytes(jpeg[i + 2:i + 4], "big")
        segmento = jpeg[i:i + 2 + largo]
        if marcador == 0xE1 and segmento[4:4 + len(_XMP)] == _XMP:
            quitados.append("xmp")
        elif marcador == 0xED:
            quitados.append("iptc_photoshop")
        else:
            salida += segmento
        i += 2 + largo
    salida += jpeg[i:]
    return bytes(salida), quitados


def detectar(contenido: bytes) -> dict[str, bool]:
    """Qué datos sensibles trae el EXIF (para pruebas y para la traza)."""
    hallado = {"gps": False, "numero_serie": False, "autor": False}
    try:
        exif = piexif.load(contenido)
    except Exception:  # noqa: BLE001 — sin EXIF legible
        return hallado
    hallado["gps"] = bool(exif.get("GPS"))
    for ifd, etiquetas in (("0th", ETIQUETAS_0TH), ("Exif", ETIQUETAS_EXIF)):
        for etiqueta, clase in etiquetas.items():
            if etiqueta in exif.get(ifd, {}) and clase in hallado:
                hallado[clase] = True
    return hallado


def _sensibles_heif(im: Image.Image) -> list[str]:
    """Qué datos sensibles trae una HEIC abierta con Pillow (las mismas etiquetas EXIF que en JPEG, más el XMP)."""
    exif = im.getexif()
    hallado = ["gps"] if exif.get_ifd(0x8825) or 0x8825 in exif else []   # IFD de GPS
    hallado += [clase for etiqueta, clase in ETIQUETAS_0TH.items() if etiqueta in exif]
    sub = exif.get_ifd(0x8769)   # IFD Exif
    hallado += [clase for etiqueta, clase in ETIQUETAS_EXIF.items() if etiqueta in sub]
    return hallado + (["xmp"] if im.info.get("xmp") else [])


def _heif_a_jpeg_sin_metadatos(contenido: bytes) -> tuple[bytes, list[str], dict]:
    """El paso intermedio para las fotos de iPhone: HEIC → JPEG sin metadatos, con lo que se quitó y sus medidas."""
    try:
        with Image.open(io.BytesIO(contenido)) as im:
            hallado = _sensibles_heif(im)
        jpeg, (ancho, alto) = heif_a_jpeg(contenido)
    except (OSError, ValueError, RuntimeError, SyntaxError) as e:
        raise FormatoNoSoportado("La foto HEIC está dañada o no se pudo leer.") from e
    return jpeg, hallado + ["metadatos_heif"], {"de": "HEIF", "a": "JPEG", "ancho": ancho, "alto": alto}


def sanitizar(contenido: bytes, formato: str) -> tuple[bytes, ResultadoGuardrail]:
    """Devuelve los bytes que se guardan (o con los que se busca) y el resultado. Si la foto era HEIC, los bytes son
    un JPEG y `detalle["convertida"]` dice de qué formato a cuál, con las medidas del JPEG."""
    quitado: list[str] = []
    convertida = None
    if formato in FORMATOS_HEIF:
        contenido, quitado, convertida = _heif_a_jpeg_sin_metadatos(contenido)
    elif formato == "JPEG":
        try:
            exif = piexif.load(contenido)
        except Exception:  # noqa: BLE001
            exif = None
        if exif:
            if exif.get("GPS"):
                exif["GPS"] = {}
                quitado.append("gps")
            for ifd, etiquetas in (("0th", ETIQUETAS_0TH), ("Exif", ETIQUETAS_EXIF)):
                for etiqueta, clase in etiquetas.items():
                    if exif.get(ifd, {}).pop(etiqueta, None) is not None:
                        quitado.append(clase)
            if exif.get("0th", {}).pop(piexif.ImageIFD.GPSTag, None) is not None and "gps" not in quitado:
                quitado.append("gps")
            if quitado:
                exif["thumbnail"] = None
                exif["1st"] = {}
                salida = io.BytesIO()
                try:
                    piexif.insert(piexif.dump(exif), contenido, salida)
                except Exception:  # noqa: BLE001 — EXIF que piexif no puede reescribir: se quita completo
                    salida = io.BytesIO()
                    piexif.remove(contenido, salida)
                    quitado.append("exif_completo")
                contenido = salida.getvalue()
        contenido, segmentos = _quitar_segmentos(contenido)
        quitado += segmentos
    else:  # PNG: sin metadatos (se conserva el perfil de color, que no es sensible)
        with Image.open(io.BytesIO(contenido)) as im:
            if im.info.keys() - {"dpi", "gamma", "transparency", "icc_profile"} or im.getexif():
                quitado.append("metadatos_png")
                salida = io.BytesIO()
                im.save(salida, "PNG", icc_profile=im.info.get("icc_profile"))
                contenido = salida.getvalue()
    unicos = sorted(set(quitado))
    detalle = {"eliminado": unicos} if unicos else {}
    if convertida:
        detalle["convertida"] = convertida
    resultado = ResultadoGuardrail("exif_privacidad", "sanitizado" if unicos else "aprobada",
                                   politica_aplicada=politica("exif_privacidad") if unicos else None, detalle=detalle)
    return contenido, resultado
