"""C3 · Guardrails de entrada de fotos: archivo_valido y exif_privacidad."""
from __future__ import annotations

import io

import piexif
import pytest
from PIL import Image

from fototeca.dominio.errores import ArchivoDemasiadoGrande, BloqueadoPorGuardrail, FormatoNoSoportado
from fototeca.guardrails.entrada.archivo import verificar_archivo
from fototeca.guardrails.entrada.exif import detectar, sanitizar
from pruebas.conftest import imagen_bytes


def con_exif_sensible(jpeg: bytes) -> bytes:
    exif = {
        "0th": {piexif.ImageIFD.Make: b"Camara", piexif.ImageIFD.Artist: b"Fulano"},
        "Exif": {piexif.ExifIFD.BodySerialNumber: b"SN-123"},
        "GPS": {piexif.GPSIFD.GPSLatitudeRef: b"N", piexif.GPSIFD.GPSLatitude: ((16, 1), (45, 1), (0, 1)),
                piexif.GPSIFD.GPSLongitudeRef: b"W", piexif.GPSIFD.GPSLongitude: ((93, 1), (7, 1), (0, 1))},
        "1st": {}, "thumbnail": None,
    }
    salida = io.BytesIO()
    piexif.insert(piexif.dump(exif), jpeg, salida)
    return salida.getvalue()


def test_archivo_valido_acepta_jpeg_y_png():
    for formato in ("JPEG", "PNG"):
        img, r = verificar_archivo(imagen_bytes(formato=formato))
        assert img.formato == formato and r.resultado == "aprobada"


def test_archivo_grande_413():
    with pytest.raises(ArchivoDemasiadoGrande):
        verificar_archivo(b"\xff\xd8" + b"0" * (10 * 1024 * 1024 + 1))


def test_contenido_que_no_es_imagen_415():
    with pytest.raises(FormatoNoSoportado):
        verificar_archivo(b"%PDF-1.7 esto no es una foto")


def test_formato_no_soportado_415():
    buf = io.BytesIO()
    Image.new("RGB", (100, 100)).save(buf, "GIF")
    with pytest.raises(FormatoNoSoportado):
        verificar_archivo(buf.getvalue())


def test_imagen_diminuta_bloqueada_422():
    with pytest.raises(BloqueadoPorGuardrail) as e:
        verificar_archivo(imagen_bytes(tam=(32, 32)))
    assert e.value.verificaciones[0]["verificacion"] == "archivo_valido"


def test_exif_sensible_se_elimina_sin_tocar_el_resto():
    original = con_exif_sensible(imagen_bytes())
    assert detectar(original) == {"gps": True, "numero_serie": True, "autor": True}
    limpio, r = sanitizar(original, "JPEG")
    assert r.resultado == "sanitizado"
    assert set(r.detalle["eliminado"]) >= {"gps", "numero_serie", "autor"}
    assert detectar(limpio) == {"gps": False, "numero_serie": False, "autor": False}
    assert piexif.load(limpio)["0th"].get(piexif.ImageIFD.Make) == b"Camara"   # lo no sensible se conserva
    with Image.open(io.BytesIO(limpio)) as im:
        assert im.size == (320, 240)


def test_sin_exif_queda_aprobada():
    limpio, r = sanitizar(imagen_bytes(), "JPEG")
    assert r.resultado == "aprobada"
