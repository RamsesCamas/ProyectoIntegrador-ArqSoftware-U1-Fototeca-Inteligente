"""C7 · Almacén de documentos en SQLite + archivos."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from fototeca.datos.documentos_sqlite import DocumentosSqlite
from fototeca.dominio.errores import NoEncontrado
from fototeca.dominio.esquemas_ficha import Ficha, FichaRegistrada, Fuente


def jpeg(color=(200, 30, 30), tam=(80, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", tam, color).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def almacen(tmp_path):
    return DocumentosSqlite(tmp_path / "sqlite" / "t.db", tmp_path / "fotos")


def test_guardar_foto_es_idempotente_por_contenido(almacen):
    a = almacen.guardar_foto(jpeg(), {"nombre": "a.jpg", "formato": "JPEG"})
    b = almacen.guardar_foto(jpeg(), {"nombre": "otra.jpg", "formato": "JPEG"})
    assert a == b and a.startswith("up-")
    assert almacen.contar("foto") == 1
    assert almacen.obtener_foto(a) == jpeg()


def test_foto_del_archivo_no_se_copia_ni_se_borra(almacen, tmp_path):
    crudo = tmp_path / "crudos" / "x.jpg"
    crudo.parent.mkdir(parents=True)
    crudo.write_bytes(jpeg())
    doc = almacen.guardar_foto(crudo.read_bytes(), {"documento_id": "xm-abc", "ruta_relativa": "crudos/x.jpg",
                                                    "particion": "archivo"})
    assert doc == "xm-abc"
    assert not list((tmp_path / "fotos").iterdir())
    almacen.eliminar(doc)
    assert crudo.exists(), "eliminar un documento nunca borra los datos crudos del corpus"
    with pytest.raises(NoEncontrado):
        almacen.obtener_foto(doc)


def test_fichas_listado_y_conteo(almacen):
    doc = almacen.guardar_foto(jpeg(), {"nombre": "a.jpg"})
    ficha = FichaRegistrada(documento_id=doc, ficha=Ficha(titular="Mercado", texto_alternativo="Puesto de frutas",
                                                          estado="validada"),
                            fuentes={"texto_alternativo": [Fuente(tipo="regla", id="iptc-2025.1#alt-text")]})
    almacen.guardar_ficha(doc, ficha)
    leida = almacen.obtener_ficha(doc)
    assert leida.ficha.titular == "Mercado" and leida.fuentes["texto_alternativo"][0].id == "iptc-2025.1#alt-text"
    assert almacen.contar_fichas() == {"validada": 1}
    resumen = almacen.listar("foto", 1, 10)
    assert resumen[0].estado_ficha == "validada"
    assert (resumen[0].titular, resumen[0].texto_alternativo) == ("Mercado", "Puesto de frutas")


def test_listado_sin_ficha_o_con_campos_vacios_da_none(almacen):
    sin_ficha = almacen.guardar_foto(jpeg((10, 20, 30)), {"nombre": "a.jpg"})
    sin_alt = almacen.guardar_foto(jpeg((90, 90, 90)), {"nombre": "b.jpg"})
    almacen.guardar_ficha(sin_alt, FichaRegistrada(documento_id=sin_alt, ficha=Ficha(titular="Calle")))
    listado = {d.documento_id: d for d in almacen.listar("foto", 1, 10)}
    assert (listado[sin_ficha].estado_ficha, listado[sin_ficha].titular, listado[sin_ficha].texto_alternativo) == \
        (None, None, None)
    assert (listado[sin_alt].estado_ficha, listado[sin_alt].titular, listado[sin_alt].texto_alternativo) == \
        ("borrador", "Calle", None)


def test_eliminar_borra_archivo_ficha_y_duplicados(almacen):
    a = almacen.guardar_foto(jpeg((1, 2, 3)), {"nombre": "a.jpg"})
    b = almacen.guardar_foto(jpeg((200, 200, 200)), {"nombre": "b.jpg"})
    almacen.registrar_duplicado(b, a, 0.98)
    ruta = almacen.ruta_foto(a)
    almacen.eliminar(a)
    assert not ruta.exists()
    assert almacen.listar_duplicados() == []
    with pytest.raises(NoEncontrado):
        almacen.eliminar("no-existe")


def test_version_archivo_incrementa(almacen):
    assert almacen.version_archivo() == 0
    assert almacen.incrementar_version_archivo() == 1
    assert almacen.incrementar_version_archivo() == 2
    assert almacen.version_archivo() == 2


def test_estado_no_falla_con_sondeos_simultaneos(almacen):
    # /health corre en el threadpool: dos sondeos a la vez no deben pisarse la prueba de escritura del directorio.
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as pool:
        estados = list(pool.map(lambda _: almacen.estado()["estado"], range(400)))
    assert estados.count("error") == 0
    assert not list((almacen.dir_fotos).iterdir())   # no deja archivos de prueba
