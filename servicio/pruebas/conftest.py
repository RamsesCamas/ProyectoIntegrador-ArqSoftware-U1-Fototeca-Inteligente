"""Fixtures comunes: la app real con adaptadores falsos para modelos y base vectorial, y SQLite temporal."""
from __future__ import annotations

import io
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fototeca.api.arranque import cargar_configuracion, crear_app, ensamblar
from fototeca.datos.cache_sqlite import CacheSqlite
from fototeca.datos.documentos_sqlite import DocumentosSqlite
from fototeca.datos.eventos_sqlite import EventosSqlite
from fototeca.datos.retroalimentacion_sqlite import RetroalimentacionSqlite
from fototeca.observabilidad.registro import configurar_sumidero
from pruebas.falsos import AlmacenVectorialFalso, ClienteLLMFalso, EmbebedorFalso


@pytest.fixture
def config(tmp_path):
    base = cargar_configuracion(modo_evaluacion=False)
    rutas = {"datos": str(tmp_path), "sqlite": str(tmp_path / "sqlite" / "prueba.db"),
             "fotos": str(tmp_path / "fotos"), "config": base.rutas["config"]}
    return replace(base, rutas=rutas)


@pytest.fixture
def contenedor(config):
    sqlite = config.rutas["sqlite"]
    c = ensamblar(
        config,
        cliente_llm=ClienteLLMFalso(list(config.modelos.values())),
        almacen_vectorial=AlmacenVectorialFalso(),
        almacen_documentos=DocumentosSqlite(sqlite, config.rutas["fotos"], config.rutas["datos"]),
        almacen_cache=CacheSqlite(sqlite),
        sumidero_eventos=EventosSqlite(sqlite),
        almacen_retroalimentacion=RetroalimentacionSqlite(sqlite),
        embebedor=EmbebedorFalso(),
        embebedor_secundario=EmbebedorFalso("granite-falso", acepta_imagenes=False),
    )
    yield c
    configurar_sumidero(None)


@pytest.fixture
def cliente_api(contenedor):
    with TestClient(crear_app(contenedor, precalentar=False)) as c:
        yield c


def imagen_bytes(color=(180, 90, 40), tam=(320, 240), formato="JPEG", patron=True, **kwargs) -> bytes:
    """Imagen sintética con un degradado (para que tenga estructura visual) en memoria."""
    img = Image.new("RGB", tam, color)
    if patron:
        px = img.load()
        for x in range(tam[0]):
            for y in range(0, tam[1], 4):
                px[x, y] = ((x * 3) % 256, (y * 2) % 256, color[2])
    buf = io.BytesIO()
    img.save(buf, formato, **kwargs)
    return buf.getvalue()
