"""Agregación de métricas a partir de los eventos (T1). Funciones puras: no conocen ninguna capa de negocio.

`GET /metricas` combina esto, en la orquestación, con la retroalimentación (T2) y con la accesibilidad del
archivo (C7). Lo que se agrega:

- latencia p50 y p95 por endpoint (las rutas se agrupan por plantilla: `/fotos/{id}/miniatura`);
- latencia p50 y p95 por etapa de cada flujo (los `tiempos_por_capa_ms` de las fichas y de las búsquedas);
- latencia p50 y p95 por capa (C1–C7, T1 y T2) y evento, con los eventos medidos de la bitácora;
- aciertos de caché exactos y semánticos; activaciones de guardrails por verificación y resultado;
- uso por modelo (llamadas, tokens, tiempo, respaldos); rutas elegidas; iteraciones del ciclo de agente.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

import numpy as np

from fototeca.observabilidad.puertos import EventoCapa

EVENTOS_CIERRE = {"ficha_completa": "fichas", "busqueda_completa": "busquedas"}
# Un segmento de ruta con dígitos o guiones (xm-…, up-…, norma-…) o hexadecimal largo (lotes) es un identificador.
_IDENTIFICADOR = re.compile(r"^(?=.*[\d-])[\w.-]+$|^[0-9a-f]{8,}$")


def _percentiles(valores: list[float]) -> dict:
    if not valores:
        return {"n": 0}
    a = np.asarray(valores, dtype=float)
    return {"n": len(valores), "p50_ms": round(float(np.percentile(a, 50)), 1),
            "p95_ms": round(float(np.percentile(a, 95)), 1), "media_ms": round(float(a.mean()), 1),
            "max_ms": round(float(a.max()), 1)}


def plantilla_ruta(ruta: str) -> str:
    """`/fotos/xm-0004…/miniatura` → `/fotos/{id}/miniatura`: agrupa la latencia por endpoint y no por documento."""
    partes = (ruta or "/").split("?")[0].split("/")
    return "/".join("{id}" if p and _IDENTIFICADOR.match(p) else p for p in partes) or "/"


def agregar(eventos: list[EventoCapa]) -> dict:
    por_endpoint: dict[str, list[float]] = defaultdict(list)
    por_etapa: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    por_evento: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    cache = Counter()
    guardrails = Counter()
    modelos: dict[str, dict] = defaultdict(lambda: {"llamadas": 0, "tokens_prompt": 0, "tokens_salida": 0,
                                                    "tiempo_ms": 0.0, "respaldos": 0, "tiempos_agotados": 0,
                                                    "json_invalido": 0})
    rutas = Counter()
    iteraciones = {"fichas": Counter(), "busquedas": Counter()}
    bloqueos = Counter()
    for e in eventos:
        d = e.detalle or {}
        if e.capa == "C1" and e.evento == "peticion":
            if e.duracion_ms is not None:
                por_endpoint[f"{d.get('metodo', '')} {plantilla_ruta(d.get('endpoint', ''))}"].append(e.duracion_ms)
            continue
        if e.capa == "C2" and e.evento in EVENTOS_CIERRE:
            flujo = EVENTOS_CIERRE[e.evento]
            for etapa, ms in (d.get("tiempos_por_capa_ms") or {}).items():
                por_etapa[flujo][etapa].append(float(ms))
            if e.duracion_ms is not None:
                por_etapa[flujo]["total"].append(e.duracion_ms)
            rutas[f"{flujo}:{e.ruta}"] += 1
            iteraciones[flujo][int(d.get("iteraciones_agente") or 0)] += 1
            for etapa in ("entrada", "salida"):
                for g in (d.get("guardrails") or {}).get(etapa, []):
                    guardrails[(g.get("verificacion"), g.get("resultado"))] += 1
            cache[(flujo, e.cache or "ninguna")] += 1
            continue
        if e.duracion_ms is not None:
            por_evento[e.capa][e.evento].append(e.duracion_ms)
        if e.capa == "C6" and e.evento == "llamada_modelo" and e.modelo:
            m = modelos[e.modelo]
            m["llamadas"] += 1
            m["tokens_prompt"] += int(d.get("tokens_prompt") or 0)
            m["tokens_salida"] += int(d.get("tokens_salida") or 0)
            m["tiempo_ms"] += float(e.duracion_ms or 0)
            m["respaldos"] += 1 if d.get("respaldo") else 0
            m["tiempos_agotados"] += 1 if d.get("tiempo_agotado") else 0
            m["json_invalido"] += 1 if e.resultado == "json_invalido" else 0
        elif e.capa == "C3" and e.evento == "bloqueo":
            bloqueos[d.get("verificacion") or e.guardrail or "desconocida"] += 1
            guardrails[(d.get("verificacion") or e.guardrail, "bloqueada")] += 1
    tasas = {}
    for flujo in ("fichas", "busquedas"):
        total = sum(n for (f, _), n in cache.items() if f == flujo)
        exactas, semanticas = cache[(flujo, "exacta")], cache[(flujo, "semantica")]
        tasas[flujo] = {"consultas": total, "aciertos_exactos": exactas, "aciertos_semanticos": semanticas,
                        "tasa_aciertos": round((exactas + semanticas) / total, 4) if total else None}
    for m in modelos.values():
        m["tiempo_ms"] = round(m["tiempo_ms"], 1)
    return {
        "latencia_por_endpoint": {k: _percentiles(v) for k, v in sorted(por_endpoint.items())},
        "latencia_por_capa": {flujo: {c: _percentiles(v) for c, v in sorted(etapas.items())}
                              for flujo, etapas in por_etapa.items()},
        "latencia_por_evento": {capa: {ev: _percentiles(v) for ev, v in sorted(evs.items())}
                                for capa, evs in sorted(por_evento.items())},
        "cache": tasas,
        "guardrails": [{"verificacion": v, "resultado": r, "n": n} for (v, r), n in sorted(guardrails.items(), key=str)],
        "bloqueos": dict(bloqueos),
        "modelos": dict(modelos),
        "rutas": dict(rutas),
        "iteraciones_agente": {str(k): n for k, n in sorted(iteraciones["fichas"].items())},
        "iteraciones_agente_busquedas": {str(k): n for k, n in sorted(iteraciones["busquedas"].items())},
        "eventos_considerados": len(eventos),
    }
