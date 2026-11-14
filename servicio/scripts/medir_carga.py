"""Tiempos de carga de los datos que pide cada página de la web, medidos a través de nginx (como el navegador).

    docker compose run --rm servicio python -m scripts.medir_carga --etiqueta antes
    docker compose run --rm servicio python -m scripts.medir_carga --etiqueta despues

Mide p50 y p95 de las peticiones de datos de la web: el estado y las cifras de Inicio (`/health` y `/metricas`, en
paralelo como la página), la página de documentos de Archivo con lo que hace falta para el `alt` de cada miniatura
(si el listado no trae el texto alternativo, un GET /fichas/{id} por foto, en 6 conexiones como el navegador), la
ficha guardada y una búsqueda simple repetida (sale de la caché exacta). No genera fichas, no sube fotos y no borra
nada. Cada corrida se guarda con su etiqueta en `evaluacion/resultados/carga_web.json`, junto a las anteriores.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from scripts._descargas import EVAL, ahora_iso, json_guardar, registro

WEB = os.environ.get("FOTOTECA_DEMO_URL", "http://web").rstrip("/")
API = f"{WEB}/api"
CONEXIONES_NAVEGADOR = 6           # conexiones por origen en Chromium con HTTP/1.1
CONSULTA_SIMPLE = "mercado con frutas"
SALIDA = EVAL / "resultados" / "carga_web.json"


def _percentiles(valores: list[float]) -> dict:
    ordenados = sorted(valores)
    p95 = ordenados[min(len(ordenados) - 1, round(0.95 * (len(ordenados) - 1)))]
    return {"n": len(valores), "p50_ms": round(statistics.median(valores), 1), "p95_ms": round(p95, 1),
            "min_ms": round(ordenados[0], 1), "max_ms": round(ordenados[-1], 1)}


def _medir(nombre: str, funcion, repeticiones: int, calentamiento: int = 2) -> dict:
    for _ in range(calentamiento):
        funcion()
    tiempos = []
    for _ in range(repeticiones):
        t0 = time.perf_counter()
        funcion()
        tiempos.append((time.perf_counter() - t0) * 1000)
    resultado = _percentiles(tiempos)
    registro(f"{nombre}: p50 {resultado['p50_ms']} ms · p95 {resultado['p95_ms']} ms")
    return resultado


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--etiqueta", required=True, help="nombre de esta corrida, por ejemplo «antes» o «despues»")
    ap.add_argument("--repeticiones", type=int, default=20)
    args = ap.parse_args()

    http = httpx.Client(timeout=httpx.Timeout(10.0, read=120.0),
                        limits=httpx.Limits(max_connections=CONEXIONES_NAVEGADOR))
    pool = ThreadPoolExecutor(max_workers=CONEXIONES_NAVEGADOR)

    def obtener(ruta: str) -> httpx.Response:
        r = http.get(f"{API}{ruta}")
        r.raise_for_status()
        return r

    salud = obtener("/health").json()
    listado = obtener("/documentos?tipo=foto&pagina=1&por_pagina=24").json()
    fotos = [d for d in listado["documentos"] if d.get("estado_ficha")]
    trae_alt = all("texto_alternativo" in d for d in listado["documentos"])
    ficha = next((d["documento_id"] for d in fotos if d["documento_id"].startswith("xm-")), fotos[0]["documento_id"])

    def inicio():
        list(pool.map(obtener, ["/health", "/metricas"]))

    def archivo():
        cuerpo = obtener("/documentos?tipo=foto&pagina=1&por_pagina=24").json()
        if not trae_alt:   # la página pide la ficha de cada foto solo para el `alt` de su miniatura
            list(pool.map(obtener, [f"/fichas/{d['documento_id']}" for d in cuerpo["documentos"] if d.get("estado_ficha")]))

    def busqueda():
        r = http.post(f"{API}/busquedas", json={"texto": CONSULTA_SIMPLE})
        r.raise_for_status()

    mediciones = {
        "health": _medir("GET /health", lambda: obtener("/health"), args.repeticiones),
        "metricas": _medir("GET /metricas", lambda: obtener("/metricas"), args.repeticiones),
        "datos_inicio_en_paralelo": _medir("Inicio (/health y /metricas en paralelo)", inicio, args.repeticiones),
        "documentos_24": _medir("GET /documentos (24 fotos)", lambda: obtener("/documentos?tipo=foto&pagina=1&por_pagina=24"),
                                args.repeticiones),
        "datos_archivo_con_alt": _medir("Archivo (listado y alt de 24 miniaturas)", archivo, args.repeticiones),
        "ficha_guardada": _medir("GET /fichas/{id}", lambda: obtener(f"/fichas/{ficha}"), args.repeticiones),
        "busqueda_simple_repetida": _medir(f"POST /busquedas «{CONSULTA_SIMPLE}» (repetida)", busqueda, args.repeticiones),
    }
    corrida = {
        "fecha": ahora_iso(),
        "url": API,
        "version_configuracion": (salud.get("versiones") or {}).get("configuracion"),
        "hardware": {"plataforma": platform.platform(), "cpus": os.cpu_count()},
        "metodo": (f"{args.repeticiones} repeticiones por medición tras 2 de calentamiento, desde un contenedor en la red "
                   f"de compose a través de nginx; {CONEXIONES_NAVEGADOR} conexiones en paralelo como el navegador"),
        "listado_trae_texto_alternativo": trae_alt,
        "peticiones_de_datos_archivo": 1 + (0 if trae_alt else len(fotos)),
        "mediciones": mediciones,
    }
    previo = json.loads(SALIDA.read_text(encoding="utf-8")) if SALIDA.exists() else {}
    corridas = previo.get("corridas", {})
    corridas[args.etiqueta] = corrida
    json_guardar(SALIDA, {"modulo": "carga_web", "descripcion": __doc__.splitlines()[0], "corridas": corridas})
    registro(f"guardado en {SALIDA} con la etiqueta «{args.etiqueta}»")


if __name__ == "__main__":
    main()
