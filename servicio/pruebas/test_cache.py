"""C4 · Caché de fichas (exacta y semántica en dos niveles) y de búsquedas, con TTL e invalidación (H5; ADR-04)."""
from __future__ import annotations

import copy
import time
from dataclasses import replace

import numpy as np

from fototeca.cache.cache_busquedas import CacheBusquedas
from fototeca.cache.cache_fichas import CacheFichas
from fototeca.datos.cache_sqlite import CacheSqlite
from fototeca.datos.documentos_sqlite import DocumentosSqlite
from fototeca.dominio import colecciones as col
from fototeca.dominio.esquemas_ficha import Ficha, FichaRegistrada
from pruebas.falsos import AlmacenVectorialFalso


def _unitario(*componentes: float, n: int = 16) -> np.ndarray:
    v = np.zeros(n, np.float32)
    v[:len(componentes)] = componentes
    return v / np.linalg.norm(v)


def _cache(config, tau_dup: float = 0.97, ttl_s: int = 3600):
    parametros = copy.deepcopy(config.parametros)
    parametros["cache"]["fichas"].update(tau_dup=tau_dup, ttl_s=ttl_s)
    cfg = replace(config, parametros=parametros)
    almacen = CacheSqlite(cfg.rutas["sqlite"])
    vec = AlmacenVectorialFalso()
    docs = DocumentosSqlite(cfg.rutas["sqlite"], cfg.rutas["fotos"], cfg.rutas["datos"])
    return CacheFichas(cfg, almacen, vec, docs), almacen, vec, docs


RESPUESTA = {"documento_id": "up-1", "ficha": {"titular": "Mercado", "texto_alternativo": "Puesto de frutas."},
             "fuentes": {}, "meta": {"ruta": "completa"}}


def test_exacta_por_sha_y_version(config):
    cache, *_ = _cache(config)
    cache.guardar("sha-a", "v1", _unitario(1), RESPUESTA, ["up-1"], "corpus1")
    acierto = cache.exacta("sha-a", "v1")
    assert acierto and acierto.tipo == "exacta" and acierto.respuesta["documento_id"] == "up-1"
    assert cache.exacta("sha-a", "v2") is None          # otra versión de configuración = otra clave


def test_semantica_nivel_1_fichas_generadas(config):
    cache, *_ = _cache(config, tau_dup=0.97)
    cache.guardar("sha-a", "v1", _unitario(1, 0.01), RESPUESTA, ["up-1"], "corpus1")
    casi = cache.semantica(_unitario(1, 0.02), "v1", "up-2")          # recorte/recompresión: coseno ≈ 1
    assert casi and casi.tipo == "semantica" and casi.nivel == "generadas"
    assert casi.duplicado_de["documento_id"] == "up-1" and casi.duplicado_de["similitud"] >= 0.97
    assert cache.semantica(_unitario(1, 1), "v1", "up-2") is None      # coseno 0.71 < τ_dup
    assert cache.semantica(_unitario(1, 0.02), "v2", "up-2") is None   # otra configuración no responde


def test_semantica_nivel_2_ficha_validada_del_archivo(config):
    cache, _, vec, docs = _cache(config, tau_dup=0.97)
    docs.guardar_foto(b"\xff\xd8falso", {"documento_id": "xm-a", "particion": "archivo"})
    docs.guardar_ficha("xm-a", FichaRegistrada(documento_id="xm-a", ficha=Ficha(titular="Mercado", estado="validada",
                                                                                 texto_alternativo="Puesto de frutas."),
                                               origen="referencia_humana"))
    vec.insertar(col.FOTOS_IMG, ["xm-a"], [_unitario(0, 1)], [{"documento_id": "xm-a", "validada": True}])
    acierto = cache.semantica(_unitario(0.01, 1), "v1", "up-recorte")
    assert acierto and acierto.nivel == "validadas"
    assert acierto.duplicado_de["documento_id"] == "xm-a"               # «posible duplicado de…» (ADR-04)
    assert acierto.respuesta["ficha"]["titular"] == "Mercado"
    assert cache.semantica(_unitario(0, 1), "v1", "xm-a") is None       # una foto no es duplicado de sí misma


def test_ttl_vencido_no_responde(config):
    cache, almacen, *_ = _cache(config, ttl_s=1)
    cache.guardar("sha-a", "v1", _unitario(1), RESPUESTA, ["up-1"], "corpus1")
    assert cache.exacta("sha-a", "v1") is not None
    time.sleep(1.2)
    assert cache.exacta("sha-a", "v1") is None
    assert almacen.purgar_expirados() >= 1


def test_invalidacion_por_documento_fuente_y_por_corpus(config):
    cache, almacen, *_ = _cache(config)
    cache.guardar("sha-a", "v1", _unitario(1), RESPUESTA, ["up-1", "xm-vecino"], "corpus1")
    cache.guardar("sha-b", "v1", _unitario(0, 1), RESPUESTA, ["up-2"], "corpus1")
    assert almacen.invalidar_por_etiqueta("doc:xm-vecino") == 1        # se borró una foto citada como fuente
    assert cache.exacta("sha-a", "v1") is None and cache.exacta("sha-b", "v1") is not None
    assert almacen.invalidar_por_etiqueta("corpus:corpus1") == 1       # cambió el corpus normativo
    assert cache.exacta("sha-b", "v1") is None


def test_cache_de_busquedas_exacta_semantica_y_version_del_archivo(config):
    c = CacheBusquedas(config, CacheSqlite(config.rutas["sqlite"]))
    respuesta = {"resultados": [{"documento_id": "xm-a"}], "meta": {"ruta": "simple"}}
    c.guardar("Mercado con frutas", None, 1, "v1", _unitario(1, 0.01), respuesta)
    assert c.exacta("mercado   con frutas", None, 1, "v1") == respuesta       # texto normalizado
    assert c.exacta("mercado con frutas", None, 2, "v1") is None              # cambió el archivo
    valor, similitud = c.semantica(_unitario(1, 0.02), 1, "v1")
    assert valor == respuesta and similitud >= c.tau
    assert c.semantica(_unitario(1, 0.02), 2, "v1") is None
    assert c.semantica(_unitario(0, 1), 1, "v1") is None
