"""Desempeño a partir de las trazas (tabla `eventos` de T1): latencia promedio, máxima, p50 y p95, totales y por capa,
por ruta y por endpoint; uso por modelo y tarea; comparación con `config/metas_calidad.yaml` (solo se lee); y un
diagrama de barras apiladas por capa para cada ruta.

Ventana: todas las trazas guardadas o, si se define FOTOTECA_EVAL_DESDE (fecha ISO 8601), solo las posteriores.

Cada ficha o búsqueda se clasifica por su evento de cierre (C2 `ficha_completa` o `busqueda_completa`): flujo, ruta,
caché y tiempo por capa. Las fichas de configuraciones experimentales se separan de las de producción con señales de
su propia traza: P3 compuesto por Qwen sin ser respaldo (experimento R3), sin RAG (transición
RECUPERAR_EJEMPLOS→ENRUTAR), P1 precalculado (ruta completa sin llamada a P1) y ciclo de agente apagado (max_iter = 0).
La latencia total es la de la petición HTTP (evento C1 de la misma traza); si no existe (lotes en segundo plano), la
del flujo. «Otros» = total − suma de las capas medidas (API, orquestación y registro).

    python -m evaluacion.desempeno
"""
from __future__ import annotations

import os
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import yaml

from evaluacion.comun import ClienteEval, guardar_grafica, guardar_resultado, percentiles, plt, registro

CAPAS = {"guardrails_entrada": "C3 guardrails de entrada", "cache": "C4 caché", "contexto": "C5 contexto (RAG)",
         "enrutador": "C6 enrutador", "modelo_vision": "C6/C7 modelo de visión (Qwen)",
         "modelo_composicion": "C6/C7 modelo de composición", "guardrails_salida": "C3 guardrails de salida",
         "otros": "C1/C2 y otros"}
COLORES = {"guardrails_entrada": "#2a78d6", "cache": "#eb6834", "contexto": "#1baf7a", "enrutador": "#eda100",
           "modelo_vision": "#e87ba4", "modelo_composicion": "#6250d6", "guardrails_salida": "#008300",
           "otros": "#9a9992"}
# Meta → (flujo, grupo, estadístico). Las fichas se comparan solo con las de producción.
MAPEO_METAS = {"busqueda_simple_p95": ("busquedas", "simple", "p95"),
               "busqueda_compleja_p95": ("busquedas", "compleja", "p95"),
               "ficha_rapida_p50": ("fichas", "rapida", "p50"),
               "ficha_completa_p50": ("fichas", "completa", "p50"),
               "ficha_cache_p50": ("fichas", "cache", "p50")}


def endpoint(ruta: str) -> str:
    """/documentos/up-123 → /documentos/{id} (para agrupar por endpoint)."""
    return re.sub(r"^/(documentos|fichas|lotes|fotos)/[^/]+", r"/\1/{id}", ruta or "")


def _variante_ficha(cierre, eventos, modelo_vision: str) -> str:
    if (cierre.cache or "ninguna") != "ninguna":
        return "produccion"
    transiciones = {((e.detalle or {}).get("de"), (e.detalle or {}).get("a")) for e in eventos
                    if e.capa == "C2" and e.evento == "transicion"}
    llamadas = [e for e in eventos if e.capa == "C6" and e.evento == "llamada_modelo"]
    if ("RECUPERAR_EJEMPLOS", "ENRUTAR") in transiciones:
        return "experimento: sin RAG"
    if any((e.detalle or {}).get("tarea") == "P3" and e.modelo == modelo_vision and not (e.detalle or {}).get("respaldo")
           for e in llamadas):
        return "experimento: P3 con Qwen (R3)"
    if cierre.ruta == "completa" and not any((e.detalle or {}).get("tarea") == "P1" for e in llamadas):
        return "experimento: P1 precalculado (R3)"
    if any(e.capa == "C2" and e.evento == "evaluar_recuperacion" and (e.detalle or {}).get("max_iter") == 0 for e in eventos):
        return "experimento: sin ciclo de agente"
    return "produccion"


def peticiones(eventos: list, modelo_vision: str) -> list[dict]:
    """Una fila por ficha o búsqueda cerrada, con su ruta, caché, variante y tiempo por capa (ms)."""
    por_traza: dict[str, list] = defaultdict(list)
    for e in eventos:
        if e.traza_id:
            por_traza[e.traza_id].append(e)
    filas = []
    for traza, evs in por_traza.items():
        cierres = [e for e in evs if e.capa == "C2" and e.evento in ("ficha_completa", "busqueda_completa")]
        c1 = [e for e in evs if e.capa == "C1" and e.evento == "peticion" and e.duracion_ms is not None]
        for cierre in cierres:
            d = cierre.detalle or {}
            flujo = "fichas" if cierre.evento == "ficha_completa" else "busquedas"
            capas = {k: float(v) for k, v in (d.get("tiempos_por_capa_ms") or {}).items() if v is not None}
            total = c1[-1].duracion_ms if len(cierres) == 1 and c1 else cierre.duracion_ms
            if total is None:
                continue
            cache = cierre.cache or "ninguna"
            variante = _variante_ficha(cierre, evs, modelo_vision) if flujo == "fichas" else "produccion"
            if cache != "ninguna":
                grupo = f"cache {cache}"
            else:
                grupo = cierre.ruta or "desconocida"
            fila = {"traza_id": traza, "ts": cierre.ts, "flujo": flujo, "ruta": cierre.ruta, "cache": cache,
                    "variante": variante, "grupo": grupo if variante == "produccion" else f"{grupo} · {variante}",
                    "total_ms": round(float(total), 1), "flujo_ms": cierre.duracion_ms,
                    "total_desde": "peticion_http" if len(cierres) == 1 and c1 else "flujo",
                    "iteraciones_agente": d.get("iteraciones_agente"), "modelos": d.get("modelos") or cierre.modelo}
            for capa in CAPAS:
                if capa != "otros":
                    fila[f"ms_{capa}"] = round(capas.get(capa, 0.0), 1)
            fila["ms_otros"] = round(max(0.0, float(total) - sum(capas.get(k, 0.0) for k in CAPAS if k != "otros")), 1)
            filas.append(fila)
    return filas


def _stats(valores: list[float]) -> dict:
    return percentiles(valores, "ms")


def por_grupo(filas: list[dict]) -> dict:
    salida: dict[str, dict] = {}
    for flujo in ("fichas", "busquedas"):
        grupos = defaultdict(list)
        for f in filas:
            if f["flujo"] == flujo:
                grupos[f["grupo"]].append(f)
        bloque = {}
        for g, fs in sorted(grupos.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            totales = [f["total_ms"] for f in fs]
            capas = {capa: _stats([f[f"ms_{capa}"] for f in fs]) for capa in CAPAS}
            media_total = float(np.mean(totales))
            bloque[g] = {"total": _stats(totales), "por_capa": capas,
                         "proporcion_media_por_capa": {capa: round(float(np.mean([f[f"ms_{capa}"] for f in fs])) / media_total, 4)
                                                       if media_total else None for capa in CAPAS},
                         "variante": fs[0]["variante"], "rutas": dict(Counter(f["ruta"] for f in fs)),
                         "iteraciones_agente": dict(Counter(str(f["iteraciones_agente"]) for f in fs
                                                            if f["iteraciones_agente"] is not None))}
        salida[flujo] = bloque
    return salida


def por_endpoint(eventos: list) -> dict:
    grupos: dict[str, list] = defaultdict(list)
    estados: dict[str, Counter] = defaultdict(Counter)
    for e in eventos:
        if e.capa == "C1" and e.evento == "peticion" and e.duracion_ms is not None:
            d = e.detalle or {}
            clave = f"{d.get('metodo', '')} {endpoint(d.get('endpoint', ''))}"
            grupos[clave].append(e.duracion_ms)
            estados[clave][f"{str(d.get('estado_http', '?'))[:1]}xx"] += 1
    return {k: {**_stats(v), "estados_http": dict(estados[k])} for k, v in sorted(grupos.items())}


def por_modelo(eventos: list) -> dict:
    grupos: dict[tuple, list] = defaultdict(list)
    for e in eventos:
        if e.capa == "C6" and e.evento == "llamada_modelo" and e.modelo:
            origen = "peticiones_api" if e.traza_id else "llamadas_directas_de_la_evaluacion"
            grupos[(origen, e.modelo, (e.detalle or {}).get("tarea", "?"))].append(e)
    salida: dict[str, dict] = defaultdict(dict)
    for (origen, modelo, tarea), evs in sorted(grupos.items()):
        d = [x.detalle or {} for x in evs]
        salida[origen][f"{modelo} · {tarea}"] = {
            **_stats([x.duracion_ms for x in evs if x.duracion_ms is not None]),
            "json_invalido": sum(1 for x in evs if x.resultado == "json_invalido"),
            "tiempo_agotado": sum(1 for x in d if x.get("tiempo_agotado")),
            "respaldo": sum(1 for x in d if x.get("respaldo")),
            "tokens_salida_media": round(float(np.mean([x.get("tokens_salida") or 0 for x in d])), 1)}
    return dict(salida)


def comparar_metas(filas: list[dict], ruta_metas: Path) -> dict:
    metas = (yaml.safe_load(ruta_metas.read_text(encoding="utf-8")) or {}).get("latencia_s", {})
    salida = {}
    for nombre, valor in metas.items():
        if nombre not in MAPEO_METAS:
            salida[nombre] = {"meta_s": valor, "estado": "pendiente: sin regla para medirla en las trazas"}
            continue
        flujo, grupo, estadistico = MAPEO_METAS[nombre]
        if grupo == "cache":
            fs = [f for f in filas if f["flujo"] == flujo and f["cache"] in ("exacta", "semantica")]
            descripcion = f"{flujo} servidas desde la caché (exacta o semántica)"
        else:
            fs = [f for f in filas if f["flujo"] == flujo and f["cache"] == "ninguna" and f["ruta"] == grupo
                  and f["variante"] == "produccion"]
            descripcion = f"{flujo}, ruta {grupo}, sin caché, configuración de producción"
        if not fs:
            salida[nombre] = {"meta_s": valor, "estado": f"pendiente: no hay trazas de {descripcion}"}
            continue
        q = 50 if estadistico == "p50" else 95
        medido = round(float(np.percentile([f["total_ms"] for f in fs], q)) / 1000, 3)
        salida[nombre] = {"meta_s": valor, "medido_s": medido, "estadistico": estadistico, "n": len(fs),
                          "cumple": medido <= float(valor), "grupo": descripcion}
    return salida


def grafica_capas(bloque: dict, flujo: str, en_segundos: bool) -> None:
    grupos = [g for g, d in bloque.items() if d["total"].get("n")]
    if not grupos:
        return
    escala = 1000.0 if en_segundos else 1.0
    pyplot = plt()
    fig, ax = pyplot.subplots(figsize=(max(6.5, 1.1 * len(grupos) + 3), 4.2))
    x = np.arange(len(grupos))
    base = np.zeros(len(grupos))
    for capa, etiqueta in CAPAS.items():
        valores = np.array([bloque[g]["por_capa"][capa].get("media_ms", 0.0) or 0.0 for g in grupos]) / escala
        if not valores.any():
            continue
        ax.bar(x, valores, bottom=base, width=0.6, color=COLORES[capa], edgecolor="white", linewidth=1, label=etiqueta)
        base += valores
    for i, g in enumerate(grupos):
        ax.text(i, base[i] * 1.01, f"n={bloque[g]['total']['n']}", ha="center", va="bottom", fontsize=7)
    ax.set_xticks(x, [g.replace(" · ", "\n") for g in grupos], fontsize=7)
    ax.set_ylabel("Tiempo medio (s)" if en_segundos else "Tiempo medio (ms)")
    titulo = "Fichas" if flujo == "fichas" else "Búsquedas"
    ax.set_title(f"{titulo}: tiempo medio por capa en cada ruta (trazas de T1)")
    ax.legend(fontsize=7, frameon=False, bbox_to_anchor=(1.01, 1), loc="upper left")
    guardar_grafica(f"desempeno_capas_{flujo}", fig)


def ejecutar(c: ClienteEval) -> dict:
    desde = os.environ.get("FOTOTECA_EVAL_DESDE") or None
    eventos = c.contenedor.sumidero_eventos.consultar(desde=desde)
    registro(f"desempeño · {len(eventos)} eventos" + (f" desde {desde}" if desde else " (todas las trazas)"))
    filas = peticiones(eventos, c.config.modelos.get("vision", ""))
    grupos = por_grupo(filas)
    metricas = {
        "ventana": {"desde": desde, "eventos": len(eventos), "primer_evento": eventos[0].ts if eventos else None,
                    "ultimo_evento": eventos[-1].ts if eventos else None,
                    "trazas": len({e.traza_id for e in eventos if e.traza_id})},
        "peticiones_clasificadas": {"fichas": sum(1 for f in filas if f["flujo"] == "fichas"),
                                    "busquedas": sum(1 for f in filas if f["flujo"] == "busquedas"),
                                    "por_variante": dict(Counter(f"{f['flujo']} · {f['variante']}" for f in filas))},
        "total": {flujo: _stats([f["total_ms"] for f in filas if f["flujo"] == flujo]) for flujo in ("fichas", "busquedas")},
        "por_ruta": grupos,
        "por_endpoint": por_endpoint(eventos),
        "por_modelo_y_tarea": por_modelo(eventos),
        "metas_latencia": comparar_metas(filas, Path(c.config.rutas["config"]) / "metas_calidad.yaml"),
    }
    grafica_capas(grupos.get("fichas", {}), "fichas", en_segundos=True)
    grafica_capas(grupos.get("busquedas", {}), "busquedas", en_segundos=False)
    configuracion = {"fuente": "tabla eventos (SQLite) de T1", "desde": desde,
                     "capas": CAPAS, "mapeo_metas": {k: list(v) for k, v in MAPEO_METAS.items()},
                     "total": "duración de la petición HTTP (C1) de la traza; si no hay, la del flujo (C2)"}
    guardar_resultado("desempeno", metricas, filas, configuracion, c)
    return metricas


if __name__ == "__main__":
    ejecutar(ClienteEval())
