"""C7 · Tabla de eventos de T1 en SQLite: `consultar` completa y la lectura ligera de GET /metricas.

`consultar` no cambia: la evaluación (`evaluacion/guardrails.py`, `evaluacion/desempeno.py`) y la retroalimentación
leen con ella las trazas completas, incluidos los sondeos de salud que quedaron guardados. `consultar_para_metricas`
los omite y decodifica `detalle` solo de los tipos de evento que usa la agregación.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from fototeca.datos.eventos_sqlite import EventosSqlite
from fototeca.observabilidad.metricas import EVENTOS_CON_DETALLE
from fototeca.observabilidad.puertos import EventoCapa

SALUD = [   # sondeo de salud guardado antes de que /health dejara de registrarse
    EventoCapa("2026-11-13T10:00:00.000+00:00", "aaaa0001", "C2", "health", duracion_ms=351.2, resultado="ok"),
    EventoCapa("2026-11-13T10:00:00.010+00:00", "aaaa0001", "C1", "peticion", duracion_ms=352.0,
               detalle={"metodo": "GET", "endpoint": "/health", "estado_http": 200}),
]
FICHA = [
    EventoCapa("2026-11-13T10:01:00.000+00:00", "bbbb0002", "C7", "embedding_imagen", duracion_ms=210.5,
               modelo="embeddinggemma-2:440m", detalle={"n": 1}),
    EventoCapa("2026-11-13T10:01:00.300+00:00", "bbbb0002", "C6", "llamada_modelo", duracion_ms=8123.4,
               modelo="qwen3.5:0.8b", resultado="ok", detalle={"tarea": "P3", "tokens_prompt": 812, "tokens_salida": 95}),
    EventoCapa("2026-11-13T10:01:09.000+00:00", "bbbb0002", "C2", "ficha_completa", duracion_ms=9001.0, ruta="simple",
               cache="ninguna", detalle={"tiempos_por_capa_ms": {"contexto": 12.5}, "iteraciones_agente": 1}),
    EventoCapa("2026-11-13T10:01:09.010+00:00", "bbbb0002", "C1", "peticion", duracion_ms=9010.0,
               detalle={"metodo": "POST", "endpoint": "/fichas", "estado_http": 200}),
]


@pytest.fixture
def eventos(tmp_path):
    sumidero = EventosSqlite(tmp_path / "sqlite" / "eventos.db")
    for e in SALUD + FICHA:
        sumidero.registrar(e)
    return sumidero


def test_consultar_devuelve_las_trazas_completas_como_antes(eventos):
    """Mismos eventos, campos, `detalle` y orden; los sondeos de salud guardados siguen en su traza."""
    assert eventos.consultar(traza_id="bbbb0002") == FICHA
    assert eventos.consultar(traza_id="aaaa0001") == SALUD
    assert eventos.consultar() == SALUD + FICHA
    assert eventos.consultar(desde="2026-11-13T10:01:00.000+00:00") == FICHA
    assert eventos.consultar(limite=3) == (SALUD + FICHA)[:3]
    assert eventos.consultar(traza_id="no-existe") == []


def test_lectura_para_metricas_sin_sondeos_de_salud_y_con_detalle_solo_donde_se_usa(eventos):
    leidos = eventos.consultar_para_metricas(con_detalle=EVENTOS_CON_DETALLE)
    assert [(e.capa, e.evento) for e in leidos] == [(e.capa, e.evento) for e in FICHA]
    for leido, guardado in zip(leidos, FICHA):
        se_usa = (guardado.capa, guardado.evento) in EVENTOS_CON_DETALLE
        assert leido == (guardado if se_usa else replace(guardado, detalle={}))
    assert eventos.consultar_para_metricas(desde="2026-11-13T10:01:09.000+00:00", con_detalle=EVENTOS_CON_DETALLE) \
        == FICHA[2:]
    assert all(e.detalle == {} for e in eventos.consultar_para_metricas())       # sin `con_detalle`, nada se decodifica
