"""C7 · Cliente de Ollama: las peticiones a un mismo modelo esperan su turno ANTES de que empiece su tiempo límite."""
from __future__ import annotations

import json
import threading
import time

import httpx

from fototeca.datos.ollama_cliente import OllamaCliente
from fototeca.dominio.entidades import Mensaje, OpcionesGeneracion

OPCIONES = OpcionesGeneracion(temperatura=0.2, top_p=0.9, presence_penalty=0.0, num_ctx=4096, num_predict=10,
                              think=False, extra={})


def cliente_con_servidor_lento(segundos: float):
    """Un servidor falso que tarda `segundos` en cada /api/chat y anota cuándo empezó y terminó cada petición."""
    intervalos: list[tuple[str, float, float]] = []
    candado = threading.Lock()

    def responder(peticion: httpx.Request) -> httpx.Response:
        modelo = json.loads(peticion.content)["model"]
        inicio = time.perf_counter()
        time.sleep(segundos)
        with candado:
            intervalos.append((modelo, inicio, time.perf_counter()))
        return httpx.Response(200, json={"model": modelo, "message": {"content": "{}"}, "prompt_eval_count": 1,
                                         "eval_count": 1, "total_duration": 1, "load_duration": 0,
                                         "done_reason": "stop"})

    c = OllamaCliente("http://ollama:11434", ["qwen", "lfm3"])
    c._http = httpx.Client(base_url=c.url, transport=httpx.MockTransport(responder))
    return c, intervalos


def generar_en_paralelo(c: OllamaCliente, modelos: list[str]) -> None:
    hilos = [threading.Thread(target=c.generar, args=(m, [Mensaje("user", "hola")]),
                              kwargs={"opciones": OPCIONES, "tiempo_limite_s": 5}) for m in modelos]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()


def test_un_mismo_modelo_atiende_una_peticion_a_la_vez():
    c, intervalos = cliente_con_servidor_lento(0.2)
    generar_en_paralelo(c, ["qwen", "qwen", "qwen"])
    tramos = sorted((i, f) for _, i, f in intervalos)
    assert len(tramos) == 3
    assert all(tramos[k][1] <= tramos[k + 1][0] + 1e-3 for k in range(2))   # no se enciman


def test_modelos_distintos_no_se_esperan_entre_si():
    c, intervalos = cliente_con_servidor_lento(0.3)
    t0 = time.perf_counter()
    generar_en_paralelo(c, ["qwen", "lfm3"])
    assert len(intervalos) == 2 and time.perf_counter() - t0 < 0.55   # en paralelo (≈0.3 s), no en serie (≈0.6 s)
