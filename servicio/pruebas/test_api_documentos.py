"""C1/C2 · POST/GET/DELETE /documentos y GET /fotos/{id}/miniatura (aceptación de H3)."""
from __future__ import annotations

import io

from PIL import Image

from fototeca.dominio import colecciones as col
from fototeca.guardrails.entrada.exif import detectar
from pruebas.conftest import imagen_bytes
from pruebas.test_guardrails_entrada import con_exif_sensible


def subir(cliente, contenido: bytes, nombre="foto.jpg", tipo="foto", mime="image/jpeg"):
    return cliente.post("/documentos", data={"tipo": tipo}, files=[("archivos", (nombre, contenido, mime))])


def test_foto_con_gps_se_guarda_y_miniatura_sin_gps(cliente_api, contenedor):
    r = subir(cliente_api, con_exif_sensible(imagen_bytes()))
    assert r.status_code == 201, r.text
    doc = r.json()["documentos"][0]
    assert any(g["verificacion"] == "exif_privacidad" and g["resultado"] == "sanitizado" for g in doc["guardrails"])
    guardado = contenedor.almacen_documentos.obtener_foto(doc["documento_id"])
    assert detectar(guardado)["gps"] is False
    mini = cliente_api.get(f"/fotos/{doc['documento_id']}/miniatura")
    assert mini.status_code == 200 and mini.headers["content-type"] == "image/jpeg"
    assert detectar(mini.content) == {"gps": False, "numero_serie": False, "autor": False}
    with Image.open(io.BytesIO(mini.content)) as im:
        assert max(im.size) <= 512
    assert contenedor.almacen_vectorial.contar(col.FOTOS_IMG, {"documento_id": doc["documento_id"]}) == 1


def test_subir_dos_veces_es_idempotente(cliente_api):
    contenido = imagen_bytes(color=(10, 120, 200))
    a = subir(cliente_api, contenido).json()["documentos"][0]
    b = subir(cliente_api, contenido).json()["documentos"][0]
    assert a["documento_id"] == b["documento_id"] and b["ya_existia"] is True
    assert b["duplicados"][0]["tipo"] == "exacto"


def test_casi_duplicado_se_detecta(cliente_api):
    original = imagen_bytes(color=(200, 40, 40), tam=(400, 300))
    a = subir(cliente_api, original).json()["documentos"][0]
    with Image.open(io.BytesIO(original)) as im:
        buf = io.BytesIO()
        im.resize((380, 285)).save(buf, "JPEG", quality=40)   # recompresión y reescalado
    b = subir(cliente_api, buf.getvalue(), "copia.jpg").json()["documentos"][0]
    assert b["documento_id"] != a["documento_id"]
    assert any(d["documento_id"] == a["documento_id"] for d in b["duplicados"])


def test_listar_y_eliminar_borra_vectores(cliente_api, contenedor):
    doc = subir(cliente_api, imagen_bytes(color=(30, 30, 30))).json()["documentos"][0]["documento_id"]
    listado = cliente_api.get("/documentos", params={"tipo": "foto"}).json()
    assert listado["total"] == 1 and listado["documentos"][0]["documento_id"] == doc
    r = cliente_api.delete(f"/documentos/{doc}")
    assert r.status_code == 200 and r.json()["vectores_eliminados"] == 1
    assert contenedor.almacen_vectorial.contar(col.FOTOS_IMG, {"documento_id": doc}) == 0
    assert cliente_api.delete(f"/documentos/{doc}").status_code == 404
    assert cliente_api.get(f"/fotos/{doc}/miniatura").status_code == 404


def test_rechazos_con_codigos_documentados(cliente_api):
    assert subir(cliente_api, b"no soy una imagen", "x.jpg").status_code == 415
    r = subir(cliente_api, imagen_bytes(tam=(20, 20)), "chica.jpg")
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "bloqueado_por_guardrail"
    assert "mensaje_seguro" in r.json()["error"]


def test_varios_archivos_con_uno_invalido(cliente_api):
    r = cliente_api.post("/documentos", data={"tipo": "foto"}, files=[
        ("archivos", ("buena.jpg", imagen_bytes(color=(1, 200, 1)), "image/jpeg")),
        ("archivos", ("mala.jpg", b"basura", "image/jpeg"))])
    assert r.status_code == 201
    cuerpo = r.json()
    assert cuerpo["creados"] == 1 and cuerpo["documentos"][1]["error"]["codigo"] == "formato_no_soportado"


def test_norma_markdown_se_fragmenta_e_indexa(cliente_api, contenedor):
    md = ("# Texto alternativo\n\nEl texto alternativo describe el propósito de la imagen en 250 caracteres o "
          "menos y no empieza con «imagen de».\n\n## Imágenes decorativas\n\nSi la imagen es decorativa, el "
          "texto alternativo va vacío para que los lectores de pantalla la ignoren.\n").encode()
    r = subir(cliente_api, md, "reglas.md", tipo="norma", mime="text/markdown")
    assert r.status_code == 201, r.text
    doc = r.json()["documentos"][0]
    assert doc["fragmentos"] == 2
    assert contenedor.almacen_vectorial.contar(col.NORMAS, {"documento_id": doc["documento_id"]}) == 2
    assert subir(cliente_api, b"MZ\x90\x00", "virus.exe", tipo="norma").status_code == 415


def test_metadatos_invalidos_400(cliente_api):
    r = cliente_api.post("/documentos", data={"tipo": "foto", "metadatos": "[1,2]"},
                         files=[("archivos", ("a.jpg", imagen_bytes(), "image/jpeg"))])
    assert r.status_code == 400 and r.json()["error"]["codigo"] == "peticion_invalida"
