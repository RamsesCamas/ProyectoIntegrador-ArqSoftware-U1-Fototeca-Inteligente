"""R3 · Selección de modelos de lenguaje (ADR-01): tabla comparativa (modelo, parámetros y cuantización, calidad
0–5, latencia, memoria y licencia) y conclusión sobre qué modelo se usa en cada ruta.

Tres configuraciones sobre `eval_fichas` (60 fotos), siempre por la API (POST /fichas en MODO_EVALUACION), para
que la evaluación pase por todas las capas y deje trazas:
- `qwen_rapida`: P2, Qwen con visión y las fichas vecinas (ruta rápida forzada);
- `qwen_composicion`: P3 compuesto por Qwen (solo texto) a partir de la descripción P1;
- `lfm3_composicion`: P3 compuesto por LFM3 a partir de la MISMA descripción P1.
P1 se calcula UNA vez por foto (`calidad.p1_unico`) y se pasa como `p1_previo` a las dos composiciones.

Métodos (quedan también en el JSON, clave `metodos`):
- Calidad: juez P7 (fidelidad y relevancia de 0 a 5; «calidad» = su promedio), similitud granite máxima entre el
  texto alternativo y las referencias en español, y chrF. Una ficha sin texto (error HTTP o ficha degradada) vale 0
  y no se manda al juez; un texto alternativo vacío vale 0 en granite y en chrF.
- JSON válido a la primera: en la traza (tabla `eventos`), el PRIMER evento C6 `llamada_modelo` de la tarea de
  composición (P2 en la ruta rápida, P3 en la completa) tiene `resultado = ok` con `intento = 1` y sin respaldo, es
  decir, el JSON cumplió el esquema sin reintento. Un tiempo agotado o un error de transporte en ese primer intento
  cuenta como «no». Sin traza no hay dato (se reporta el n).
- Pasa los guardrails de salida: la ficha final tiene un estado distinto de `requiere_revision`.
- Latencia de la ruta: `meta.tiempo_ms`; en las composiciones se le suma el P1 calculado aparte (`p1_unico`), que en
  producción forma parte de la ruta completa. También se reportan los tiempos por capa.
- Memoria: `/api/ps` de Ollama con el modelo cargado (pesos, caché KV para `num_ctx` y búferes). `docker stats` no
  es accesible desde el contenedor `servicio`; como referencia de RSS se cita H0
  (`evaluacion/resultados/h0_memoria_por_modelo.txt`).
- Tamaño en disco y cuantización: `/api/tags` y `/api/show`. Licencia: tabla de docs/LICENCIAS-Y-CORPUS.md.

El módulo también expone las piezas que reutilizan `rag_fichas`, `enrutador` y `agente`: subidas, generación
reanudable, lectura de trazas, calidad por caso, agregados y gráficas.

    python -m evaluacion.r3_modelos [--rapido]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
from collections import Counter

import numpy as np

from evaluacion.calidad import (CONFIGURACIONES, asegurar_subidas, calidad, ficha_evaluacion, intervalo_bootstrap,
                                p1_unico, resumen_numerico)
from evaluacion.comun import (RESULTADOS, ClienteEval, Incremental, ahora, guardar_grafica, guardar_resultado,
                              particiones, percentiles, plt, registro, tamano)

CONFIGS_R3 = ("qwen_rapida", "qwen_composicion", "lfm3_composicion")
COMPOSICIONES = ("qwen_composicion", "lfm3_composicion")
ROL_MODELO = {"qwen_rapida": "vision", "qwen_composicion": "vision", "lfm3_composicion": "composicion"}
ETIQUETA = {"qwen_rapida": "ruta rápida (P2 con visión y vecinos)",
            "qwen_composicion": "composición P3 (solo texto, desde P1)",
            "lfm3_composicion": "composición P3 (desde el mismo P1)"}
ETIQUETA_CORTA = {"qwen_rapida": "Qwen\nruta rápida (P2)", "qwen_composicion": "Qwen\ncomposición (P3)",
                  "lfm3_composicion": "LFM3\ncomposición (P3)"}
TAREAS_GENERACION = ("P2", "P3")
CAMPOS_TEXTO = ("titular", "texto_alternativo", "descripcion")
CAPAS = ("guardrails_entrada", "contexto", "enrutador", "modelo_vision", "modelo_composicion", "guardrails_salida")
FUENTE_LICENCIAS = "docs/LICENCIAS-Y-CORPUS.md (tabla de modelos)"
LICENCIAS = {   # copiadas de FUENTE_LICENCIAS; un modelo que no esté aquí se reporta como pendiente
    "qwen3.5:0.8b": "Apache 2.0",
    "lfm3:1.7b-q4_K_M": "LFM Open License v1.0 (Liquid AI)",
    "embeddinggemma-2:440m": "Apache 2.0",
    "granite-embedding:278m": "Apache 2.0 (IBM)",
}
EVENTOS_TRAZA = {("C6", "llamada_modelo"), ("C6", "enrutar"), ("C6", "p1_fallo"), ("C5", "recuperar_ejemplos"),
                 ("C2", "evaluar_recuperacion"), ("C2", "reformular"), ("C2", "generacion_fallida"),
                 ("C2", "ficha_degradada")}
# Paleta categórica de referencia (skill dataviz), asignada siempre en el mismo orden; tinta y rejilla neutras.
COLORES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
TINTA, TINTA_SECUNDARIA, REJILLA = "#0b0b0b", "#52514e", "#dddcd8"

METODOS = {
    "calidad": "juez P7 (LFM3, temperatura 0; fidelidad y relevancia 0–5, calidad = su promedio), similitud granite "
               "máxima del texto alternativo con las referencias en español de XM3600 y chrF. Ficha sin texto = 0 "
               "(no se manda al juez); texto alternativo vacío = 0 en granite y chrF",
    "json_valido_primera": "primer evento C6 `llamada_modelo` de la tarea de composición (P2 en la ruta rápida, P3 "
                           "en la completa) con resultado `ok`, intento 1 y sin respaldo; tiempo agotado o error de "
                           "transporte en ese intento = no; sin traza = sin dato",
    "pasa_guardrails_salida": "estado final de la ficha distinto de `requiere_revision`",
    "latencia": "meta.tiempo_ms; en las composiciones se suma el P1 calculado aparte (p1_unico)",
    "memoria": "/api/ps de Ollama con el modelo cargado (precalentado con keep_alive -1); referencia RSS de H0",
    "intervalos": "IC95 de la media por bootstrap (1,000 remuestreos, semilla 2026); diferencias pareadas por foto",
}


# ───────────────────────────── utilidades ─────────────────────────────
def tasa(valores) -> dict:
    v = [bool(x) for x in valores if x is not None]
    return {"tasa": round(sum(v) / len(v), 4) if v else None, "n": len(v)}


def media(valores) -> float | None:
    v = [float(x) for x in valores if x is not None]
    return round(float(np.mean(v)), 4) if v else None


def fmt(x, decimales: int = 2) -> str:
    return "pendiente" if x is None else f"{x:.{decimales}f}"


def fmt_ic(ic, decimales: int = 2) -> str:
    return "pendiente" if not ic else f"[{ic[0]:.{decimales}f}, {ic[1]:.{decimales}f}]"


def fmt_pct(t) -> str:
    return "pendiente" if t is None else f"{t * 100:.0f} %"


class Avance:
    """Avance en el log. El ritmo solo cuenta los pasos lentos (los casos reanudados del JSONL son instantáneos)."""

    def __init__(self, etiqueta: str, total: int, cada: int = 10):
        self.etiqueta, self.total, self.cada = etiqueta, total, max(1, cada)
        self.hechos = self.nuevos = self._avisado = 0
        self.segundos_nuevos = 0.0
        self.marca = time.perf_counter()

    def paso(self, n: int = 1) -> None:
        t = time.perf_counter()
        dt, self.marca = t - self.marca, t
        self.hechos += n
        if dt > 0.5 * n:
            self.nuevos += n
            self.segundos_nuevos += dt
        if self.hechos - self._avisado >= self.cada or self.hechos >= self.total:
            self._avisado = self.hechos
            texto = f"   {self.etiqueta}: {self.hechos}/{self.total}"
            if self.nuevos:
                ritmo = self.segundos_nuevos / self.nuevos
                texto += f" · {ritmo:.1f} s por caso nuevo · faltan ~{(self.total - self.hechos) * ritmo / 60:.0f} min"
            registro(texto)


def exigir_servicios(c: ClienteEval) -> None:
    """Aborta si Ollama o Qdrant no responden: una falla de infraestructura no es un resultado del sistema y no
    debe quedar guardada como tal en los resultados incrementales."""
    llm, vec = c.contenedor.cliente_llm.estado(), c.contenedor.almacen_vectorial.estado()
    problemas = []
    if llm.get("estado") != "ok":
        problemas.append(f"Ollama: {llm.get('error') or 'faltan modelos ' + str(llm.get('modelos_faltantes'))}")
    if vec.get("estado") != "ok":
        problemas.append(f"Qdrant: {vec.get('error')}")
    if problemas:
        raise RuntimeError("Servicios no disponibles; no se evalúa. " + "; ".join(problemas))


def eval_fichas_muestra() -> list[str]:
    """`eval_fichas` (40 de `nuevas` + 20 de `regiones_excluidas`). Con --rapido se toma la cuarta parte de CADA
    grupo, igual en todos los módulos, para que compartan las generaciones."""
    part = particiones()
    regiones = set(part["regiones_excluidas"])
    normales = [x for x in part["eval_fichas"] if x not in regiones]
    excluidas = [x for x in part["eval_fichas"] if x in regiones]
    return normales[:tamano(len(normales))] + excluidas[:tamano(len(excluidas))]


# ───────────────────────────── subidas y generación ─────────────────────────────
def subir(c: ClienteEval, xm_ids: list[str], etiqueta: str = "fotos", bloque: int = 50) -> tuple[dict[str, str], list[str]]:
    """Sube por la API las fotos que falten (`calidad.asegurar_subidas`, reanudable), en bloques y con avance.
    Una foto rechazada (p. ej. por un guardrail de entrada) se registra y no detiene la evaluación."""
    previas = set(Incremental("subidas").casos)
    pendientes = sum(1 for x in xm_ids if x not in previas)
    if pendientes:
        registro(f"subiendo {pendientes} {etiqueta} por POST /documentos (cada una calcula su embedding de imagen)")
    mapa: dict[str, str] = {}
    fallidas: list[str] = []
    avance = Avance(f"subidas ({etiqueta})", len(xm_ids), cada=bloque * 4)
    for i in range(0, len(xm_ids), bloque):
        parte = xm_ids[i:i + bloque]
        try:
            mapa.update(asegurar_subidas(c, parte))
        except RuntimeError:
            exigir_servicios(c)
            for x in parte:
                try:
                    mapa.update(asegurar_subidas(c, [x]))
                except RuntimeError as e:
                    fallidas.append(x)
                    registro(f"   no se pudo subir {x}: {str(e)[:200]}")
        avance.paso(len(parte))
    return mapa, fallidas


def generar(c: ClienteEval, config: str, xm_id: str, documento_id: str, **extra) -> dict:
    """`calidad.ficha_evaluacion` con una salvaguarda: un 503 (Ollama o Qdrant no respondieron) es una falla de
    infraestructura, no un resultado; se verifica la infraestructura (si sigue caída, se aborta) y se repite una vez."""
    reg = ficha_evaluacion(c, config, xm_id, documento_id, **extra)
    if reg.get("estado_http") != 503:
        return reg
    exigir_servicios(c)
    opciones = {**CONFIGURACIONES.get(config, {}), **extra}
    estado, cuerpo, seg = c.ficha(documento_id, **opciones)
    registro(f"   {config}/{xm_id}: 503 → repetido, ahora {estado}")
    return Incremental(f"fichas_{config}").guardar(xm_id, {
        "documento_id": documento_id, "estado_http": estado, "respuesta": cuerpo, "segundos": round(seg, 3),
        "opciones": {k: v for k, v in opciones.items() if k != "p1_previo"}})


def generar_fichas(c: ClienteEval, xm_ids: list[str], configs=CONFIGS_R3) -> dict:
    """Sube las fotos, calcula P1 una sola vez (si alguna configuración compone) y genera las fichas de cada
    configuración, todo reanudable. Devuelve {"ids", "documentos", "p1", "registros": {config: {xm_id: registro}},
    "fallidas"}."""
    docs, fallidas = subir(c, xm_ids, "fotos de evaluación")
    ids = [x for x in xm_ids if x in docs]
    p1: dict[str, dict] = {}
    if any(k in COMPOSICIONES for k in configs):
        avance = Avance("P1 (una vez por foto)", len(ids))
        for x in ids:
            p1[x] = p1_unico(c, x, docs[x])
            avance.paso()
    registros: dict[str, dict[str, dict]] = {k: {} for k in configs}
    for config in configs:
        avance = Avance(f"fichas {config}", len(ids))
        for x in ids:
            previo = (p1.get(x) or {}).get("p1")
            extra = {"p1_previo": previo} if config in COMPOSICIONES and isinstance(previo, dict) else {}
            registros[config][x] = generar(c, config, x, docs[x], **extra)
            avance.paso()
    return {"ids": ids, "documentos": docs, "p1": p1, "registros": registros, "fallidas": fallidas}


# ───────────────────────────── trazas ─────────────────────────────
_trazas: Incremental | None = None


def eventos_traza(c: ClienteEval, traza_id: str | None) -> list[dict] | None:
    """Eventos de interés de una traza (C2, C5 y C6). Se copian al JSONL de casos para no depender de que la tabla
    `eventos` siga intacta en una corrida posterior. None si no hay traza."""
    global _trazas
    if not traza_id:
        return None
    if _trazas is None:
        _trazas = Incremental("trazas_evaluacion")
    previo = _trazas.obtener(traza_id)
    if previo:
        return previo["eventos"]
    eventos = c.contenedor.sumidero_eventos.consultar(traza_id=traza_id)
    if not eventos:
        return None
    compactos = [{"capa": e.capa, "evento": e.evento, "resultado": e.resultado, "modelo": e.modelo, "ruta": e.ruta,
                  "duracion_ms": e.duracion_ms, "detalle": e.detalle or {}}
                 for e in eventos if (e.capa, e.evento) in EVENTOS_TRAZA]
    return _trazas.guardar(traza_id, {"eventos": compactos})["eventos"]


def resumen_generacion(eventos: list[dict] | None) -> dict:
    """Primera llamada de la tarea de composición (P2 en la ruta rápida, P3 en la completa): ¿JSON válido a la
    primera? = resultado `ok` en el intento 1 y sin respaldo (el gateway registra un evento por intento)."""
    if eventos is None:
        return {"con_traza": False, "json_valido_primera": None}
    llamadas = [e for e in eventos if e["capa"] == "C6" and e["evento"] == "llamada_modelo"]
    gen = [e for e in llamadas if (e.get("detalle") or {}).get("tarea") in TAREAS_GENERACION]
    primera = gen[0] if gen else {}
    d = primera.get("detalle") or {}
    valido = (primera.get("resultado") == "ok" and int(d.get("intento") or 1) == 1 and not d.get("respaldo")) \
        if primera else None
    return {
        "con_traza": True,
        "json_valido_primera": valido, "intento_primera": d.get("intento"), "respaldo_primera": d.get("respaldo"),
        "resultado_primera": primera.get("resultado"), "tarea_primera": d.get("tarea"),
        "modelo_primera": primera.get("modelo"), "razon_fin_primera": d.get("razon_fin"),
        "tokens_prompt_primera": d.get("tokens_prompt"), "tokens_salida_primera": d.get("tokens_salida"),
        "llamadas_generacion": len(gen),
        "json_invalidos": sum(1 for e in gen if e.get("resultado") == "json_invalido"),
        "tiempos_agotados": sum(1 for e in gen if e.get("resultado") == "tiempo_agotado"),
        "respaldo_usado": any((e.get("detalle") or {}).get("respaldo") for e in gen),
        "llamadas_por_tarea": dict(Counter(str((e.get("detalle") or {}).get("tarea")) for e in llamadas)),
    }


# ───────────────────────────── calidad por caso ─────────────────────────────
def medir_calidad(c: ClienteEval, xm_id: str, ficha: dict | None) -> dict:
    if not ficha or not any((ficha.get(k) or "").strip() for k in CAMPOS_TEXTO):
        return {"ficha_vacia": True, "juez_fidelidad": 0, "juez_relevancia": 0, "juez_promedio": 0.0, "juez_error": None,
                "granite_max": 0.0, "chrf": 0.0, "alt_caracteres": 0, "alt_vacio": True}
    q = calidad(c, xm_id, ficha)
    if q.get("alt_vacio"):          # sin texto alternativo, sus métricas de similitud valen 0 (no «sin dato»)
        q["granite_max"], q["chrf"] = 0.0, 0.0
    return {"ficha_vacia": False, **q}


def caso(c: ClienteEval, config: str, xm_id: str, reg: dict, p1: dict | None = None) -> dict:
    """Un caso medido: respuesta de la API + traza + calidad. `ficha` va completa (no al CSV: ver `fila_csv`)."""
    cuerpo = reg.get("respuesta") or {}
    ok = reg.get("estado_http") == 200 and isinstance(cuerpo.get("ficha"), dict)
    ficha = cuerpo["ficha"] if ok else None
    meta = (cuerpo.get("meta") or {}) if ok else {}
    traza = meta.get("traza_id") or (cuerpo.get("error") or {}).get("traza_id")
    gen = resumen_generacion(eventos_traza(c, traza))
    con_p1_previo = config in COMPOSICIONES and isinstance((p1 or {}).get("p1"), dict)
    p1_aparte = float(p1.get("segundos") or 0.0) if con_p1_previo else 0.0
    tiempo = meta.get("tiempo_ms")
    capas = meta.get("tiempos_por_capa_ms") or {}
    modelos = meta.get("modelos") or {}
    return {
        "config": config, "xm_id": xm_id, "documento_id": reg.get("documento_id"),
        "estado_http": reg.get("estado_http"), "error": None if ok else (cuerpo.get("error") or {}).get("codigo"),
        "ruta_final": meta.get("ruta"), "modelo_vision": modelos.get("vision"),
        "modelo_composicion": modelos.get("composicion"), "estado_ficha": ficha.get("estado") if ficha else None,
        "pasa_guardrails_salida": bool(ficha) and ficha.get("estado") != "requiere_revision",
        "revision": meta.get("revision") or [], "iteraciones_agente": meta.get("iteraciones_agente"),
        "senales_enrutador": meta.get("senales_enrutador") or {}, "recuperacion": meta.get("recuperacion"),
        "latencia_ficha_s": round(tiempo / 1000, 3) if tiempo is not None else None,
        "p1_aparte_s": round(p1_aparte, 3) if con_p1_previo else None,
        "latencia_ruta_s": round(tiempo / 1000 + p1_aparte, 3) if tiempo is not None else None,
        **{f"capa_{k}_s": (round(capas[k] / 1000, 3) if capas.get(k) is not None else None) for k in CAPAS},
        **medir_calidad(c, xm_id, ficha),
        **{f"gen_{k}": v for k, v in gen.items()},
        "traza_id": traza, "ficha": ficha,
    }


def fila_csv(x: dict) -> dict:
    ficha = x.get("ficha") or {}
    return {**{k: v for k, v in x.items() if k != "ficha"}, "titular": ficha.get("titular"),
            "texto_alternativo": ficha.get("texto_alternativo")}


def agregar(casos: list[dict]) -> dict:
    """Métricas agregadas de una configuración."""
    def columna(k):
        return [x.get(k) for x in casos]

    def con_ic(k):
        return {**resumen_numerico(columna(k)), "ic95": intervalo_bootstrap(columna(k))}

    return {
        "n": len(casos),
        "errores_http": sum(1 for x in casos if x.get("estado_http") != 200),
        "fichas_vacias": sum(1 for x in casos if x.get("ficha_vacia")),
        "juez_errores": sum(1 for x in casos if x.get("juez_error")),
        "juez_fidelidad": con_ic("juez_fidelidad"), "juez_relevancia": con_ic("juez_relevancia"),
        "juez_promedio": con_ic("juez_promedio"),
        "juez_promedio_solo_fichas_con_texto": resumen_numerico([x.get("juez_promedio") for x in casos
                                                                 if not x.get("ficha_vacia")]),
        "granite_max": con_ic("granite_max"), "chrf": con_ic("chrf"),
        "json_valido_primera": {**tasa(columna("gen_json_valido_primera")),
                                "casos_sin_traza": sum(1 for x in casos if not x.get("gen_con_traza"))},
        "pasa_guardrails_salida": {**tasa(columna("pasa_guardrails_salida")),
                                   "sin_requiere_revision": sum(1 for v in columna("pasa_guardrails_salida") if v)},
        # Por qué quedó cada ficha en `requiere_revision` (una ficha puede tener varios motivos).
        "motivos_revision": dict(Counter(m for x in casos for m in (x.get("revision") or [])).most_common()),
        "latencia_ruta_s": percentiles([v for v in columna("latencia_ruta_s") if v is not None]),
        "latencia_ficha_s": percentiles([v for v in columna("latencia_ficha_s") if v is not None]),
        "latencia_por_capa_s": {k: percentiles([v for v in columna(f"capa_{k}_s") if v is not None]) for k in CAPAS},
        "tokens_prompt_primera": resumen_numerico(columna("gen_tokens_prompt_primera")),
        "tokens_salida_primera": resumen_numerico(columna("gen_tokens_salida_primera")),
        "razon_fin_primera": dict(Counter(str(v) for v in columna("gen_razon_fin_primera") if v)),
        "ruta_final": dict(Counter(str(v) for v in columna("ruta_final"))),
        "modelo_composicion_final": dict(Counter(str(v) for v in columna("modelo_composicion") if v)),
        "iteraciones_agente_media": media(columna("iteraciones_agente")),
    }


def diferencia_pareada(a: dict[str, dict], b: dict[str, dict], campo: str) -> dict:
    """Diferencia por foto (a − b) en las fotos que tienen el dato en ambas configuraciones."""
    comunes = [x for x in a if x in b and a[x].get(campo) is not None and b[x].get(campo) is not None]
    d = [float(a[x][campo]) - float(b[x][campo]) for x in comunes]
    return {"campo": campo, "n": len(d), "media": media(d), "ic95": intervalo_bootstrap(d),
            "a_mayor": sum(1 for v in d if v > 0), "b_mayor": sum(1 for v in d if v < 0),
            "empates": sum(1 for v in d if v == 0)}


def escribir_csv(nombre: str, filas: list[dict]) -> str | None:
    """Detalle adicional caso por caso, con el mismo formato que `comun.guardar_resultado`."""
    if not filas:
        return None
    RESULTADOS.mkdir(parents=True, exist_ok=True)
    columnas = sorted({k for fila in filas for k in fila})
    ruta = RESULTADOS / f"{nombre}.csv"
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columnas)
        w.writeheader()
        for fila in filas:
            w.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in fila.items()})
    return f"evaluacion/resultados/{ruta.name}"


# ───────────────────────────── gráficas ─────────────────────────────
def nueva_figura(ancho: float = 7.5, alto: float = 3.8, columnas: int = 1):
    figura, ejes = plt().subplots(1, columnas, figsize=(ancho, alto), squeeze=False)
    ejes = list(ejes[0])
    for ax in ejes:
        ax.grid(axis="y", color=REJILLA, linewidth=0.6)
        ax.set_axisbelow(True)
        ax.tick_params(colors=TINTA_SECUNDARIA, labelcolor=TINTA)
    return figura, ejes


def barras(ax, categorias: list[str], series: dict[str, list], intervalos: dict[str, list] | None = None,
           formato: str = "{:.2f}", leyenda: bool = True) -> None:
    """Barras agrupadas: un color por serie en orden fijo, IC95 como bigotes y el valor sobre la barra si son pocas."""
    n = max(1, len(series))
    ancho = 0.8 / n
    x = np.arange(len(categorias))
    rotular = len(categorias) * n <= 8
    for i, (nombre, valores) in enumerate(series.items()):
        v = np.array([np.nan if y is None else float(y) for y in valores])
        pos = x + (i - (n - 1) / 2) * ancho
        ax.bar(pos, np.nan_to_num(v), width=ancho * 0.9, color=COLORES[i], label=nombre, edgecolor="white",
               linewidth=1.5, zorder=2)
        ics = (intervalos or {}).get(nombre) or [None] * len(categorias)
        for p, y, ic in zip(pos, v, ics):
            if np.isnan(y):
                continue
            tope = y
            if ic:
                ax.errorbar(p, y, yerr=[[max(0.0, y - ic[0])], [max(0.0, ic[1] - y)]], color=TINTA_SECUNDARIA,
                            capsize=3, linewidth=1, zorder=3)
                tope = max(y, ic[1])
            if rotular:
                ax.annotate(formato.format(y), (p, tope), xytext=(0, 3), textcoords="offset points", ha="center",
                            va="bottom", fontsize=7.5, color=TINTA_SECUNDARIA)
    ax.set_xticks(x, categorias)
    if leyenda and len(series) > 1:     # en la cabecera, sobre el área de datos (el título lleva `pad`)
        ax.legend(loc="lower left", bbox_to_anchor=(0.0, 1.0), ncol=min(3, len(series)), frameon=False, fontsize=8,
                  borderaxespad=0.3)


def leyenda_comun(figura, ax, columnas: int = 2) -> None:
    """Una sola leyenda al pie de la figura: los colores significan la misma serie en todos los paneles."""
    manejadores, etiquetas = ax.get_legend_handles_labels()
    figura.legend(manejadores, etiquetas, loc="lower center", ncol=columnas, frameon=False, fontsize=8.5)


# ───────────────────────────── modelos: ficha técnica y memoria ─────────────────────────────
def _ollama(c: ClienteEval, metodo: str, ruta: str, **kw) -> dict | None:
    http = getattr(c.contenedor.cliente_llm, "_http", None)
    try:
        if http is None:
            import httpx
            http = httpx.Client(base_url=c.config.urls["ollama"])
        r = http.request(metodo, ruta, timeout=120.0, **kw)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001 — se reporta como pendiente
        registro(f"aviso: Ollama {ruta} no respondió ({type(e).__name__})")
        return None


def ficha_tecnica(c: ClienteEval, modelos: list[str]) -> dict:
    """Parámetros, cuantización, tamaño en disco, contexto y capacidades (/api/tags y /api/show) y licencia."""
    tags = {m.get("name"): m for m in ((_ollama(c, "GET", "/api/tags") or {}).get("models") or [])}
    salida = {}
    for m in modelos:
        show = _ollama(c, "POST", "/api/show", json={"model": m}) or {}
        t = tags.get(m) or {}
        det = show.get("details") or t.get("details") or {}
        info = show.get("model_info") or {}
        contexto = next((v for k, v in info.items() if k.endswith(".context_length")), None)
        licencia_show = next((l.strip() for l in (show.get("license") or "").splitlines() if l.strip()), None)
        salida[m] = {
            "parametros": det.get("parameter_size"), "parametros_exactos": info.get("general.parameter_count"),
            "cuantizacion": det.get("quantization_level"), "formato": det.get("format"), "familia": det.get("family"),
            "tamano_disco_bytes": t.get("size"),
            "tamano_disco_gb": round(t["size"] / 1e9, 3) if t.get("size") else None,
            "digest": (t.get("digest") or "")[:12] or None, "contexto_maximo_tokens": contexto,
            "capacidades": show.get("capabilities"),
            "licencia": LICENCIAS.get(m, f"pendiente: el modelo no está en {FUENTE_LICENCIAS}"),
            "licencia_fuente": FUENTE_LICENCIAS,
            "licencia_ollama_show_primera_linea": licencia_show[:120] if licencia_show else None,
        }
    return salida


def memoria_cargada(c: ClienteEval, modelos: list[str]) -> dict:
    """Carga cada modelo (keep_alive -1, sin generar) y lee su memoria en /api/ps."""
    salida = {}
    for m in modelos:
        try:
            c.contenedor.cliente_llm.precalentar(m)
        except Exception as e:  # noqa: BLE001
            salida[m] = {"pendiente": f"no se pudo cargar el modelo ({type(e).__name__})"}
            continue
        ps = _ollama(c, "GET", "/api/ps") or {}
        x = next((p for p in ps.get("models") or [] if m in (p.get("name"), p.get("model"))), None)
        if not x or not x.get("size"):
            salida[m] = {"pendiente": "el modelo no aparece en /api/ps"}
            continue
        salida[m] = {"memoria_bytes": int(x["size"]), "memoria_gb": round(x["size"] / 1e9, 3),
                     "memoria_gib": round(x["size"] / 2**30, 3), "vram_bytes": x.get("size_vram"),
                     "contexto_cargado": x.get("context_length"), "medido": ahora(),
                     "cargados_a_la_vez": sorted(p.get("name") for p in ps.get("models") or [])}
    return salida


def rss_h0() -> dict:
    """RSS por proceso llama-server medido en H0 (referencia; no se vuelve a medir aquí)."""
    ruta = RESULTADOS / "h0_memoria_por_modelo.txt"
    fuente = "evaluacion/resultados/h0_memoria_por_modelo.txt"
    if not ruta.exists():
        return {"fuente": fuente, "pendiente": "no existe el archivo", "por_modelo": {}}
    texto = ruta.read_text(encoding="utf-8")
    rss = {m.group(1): int(m.group(2)) for m in re.finditer(r"^(sha256-[0-9a-f]+)\s+VmRSS:\s+(\d+)\s*kB", texto, re.M)}
    por_modelo, en_blobs = {}, False
    for linea in texto.splitlines():
        if linea.startswith("##"):
            en_blobs = linea.startswith("## blobs")
            continue
        partes = linea.split()
        if en_blobs and len(partes) >= 2:
            blob = next((b for b in partes[1:] if b in rss), None)
            if blob:
                kb = rss[blob]
                por_modelo[partes[0]] = {"blob": blob, "vmrss_kb": kb, "vmrss_gb": round(kb * 1024 / 1e9, 3),
                                         "vmrss_gib": round(kb / 2**20, 3)}
    primera = texto.splitlines()[0].lstrip("# ").strip() if texto.strip() else None
    return {"fuente": fuente, "contexto": primera, "por_modelo": por_modelo}


# ───────────────────────────── tabla y conclusión ─────────────────────────────
def tabla_r3(agg: dict, modelos: dict, info: dict, memoria: dict, rss: dict) -> tuple[list[dict], str]:
    filas = []
    for k in CONFIGS_R3:
        m, a = modelos[k], agg[k]
        i, mem = info.get(m) or {}, memoria.get(m) or {}
        lat = a["latencia_ruta_s"]
        filas.append({
            "configuracion": k, "modelo": m, "rol": ETIQUETA[k], "parametros": i.get("parametros"),
            "cuantizacion": i.get("cuantizacion"), "calidad_0_5": a["juez_promedio"].get("media"),
            "calidad_ic95": a["juez_promedio"].get("ic95"), "latencia_media_s": lat.get("media_s"),
            "latencia_p50_s": lat.get("p50_s"), "latencia_p95_s": lat.get("p95_s"), "memoria_gb": mem.get("memoria_gb"),
            "memoria_rss_h0_gb": ((rss.get("por_modelo") or {}).get(m) or {}).get("vmrss_gb"),
            "tamano_disco_gb": i.get("tamano_disco_gb"), "licencia": i.get("licencia"),
            "granite_max_media": a["granite_max"].get("media"), "chrf_media": a["chrf"].get("media"),
            "json_valido_primera": a["json_valido_primera"].get("tasa"),
            "pasa_guardrails_salida": a["pasa_guardrails_salida"].get("tasa"), "n": a["n"],
        })
    lineas = ["| Modelo (configuración) | Parámetros / cuantización | Calidad (0–5) | Latencia (s) | Memoria (GB) | Licencia |",
              "|---|---|---|---|---|---|"]
    for f in filas:
        ic = f["calidad_ic95"]
        calidad_txt = fmt(f["calidad_0_5"]) + (f" (IC95 {ic[0]:.2f}–{ic[1]:.2f})" if ic else "")
        lat_txt = f"{fmt(f['latencia_media_s'], 1)} (p50 {fmt(f['latencia_p50_s'], 1)} · p95 {fmt(f['latencia_p95_s'], 1)})"
        mem_txt = fmt(f["memoria_gb"]) + (f" (RSS H0 {f['memoria_rss_h0_gb']:.2f})" if f["memoria_rss_h0_gb"] else "")
        lineas.append(f"| {f['modelo']} · {f['rol']} | {f['parametros'] or 'pendiente'} / {f['cuantizacion'] or 'pendiente'} "
                      f"| {calidad_txt} | {lat_txt} | {mem_txt} | {f['licencia']} |")
    nota = ("Calidad: promedio de fidelidad y relevancia del juez P7 (LFM3, temperatura 0) contra las descripciones "
            "humanas en español de XM3600. Latencia: media de la ruta en CPU (p50 y p95 entre paréntesis); las "
            "composiciones incluyen P1. Memoria: /api/ps con el modelo cargado; entre paréntesis, el RSS del proceso "
            "medido en H0.")
    return filas, "\n".join(lineas) + "\n\n" + nota


def ganador_composicion(dif_comp: dict, dif_guard: dict, p50: dict) -> str:
    """LFM3 o Qwen para P3, en este orden: (1) la de mayor calidad del juez si el IC95 de la diferencia pareada
    excluye 0; (2) si no, la que deja más fichas sin `requiere_revision` (guardrails de salida: fuentes, consistencia,
    apego visual) si el IC95 de esa diferencia pareada excluye 0; (3) si tampoco, la de menor latencia p50."""
    for dif in (dif_comp, dif_guard):
        ic = (dif or {}).get("ic95")
        if ic and ic[0] > 0:
            return "lfm3_composicion"
        if ic and ic[1] < 0:
            return "qwen_composicion"
    a, b = p50.get("lfm3_composicion"), p50.get("qwen_composicion")
    return "qwen_composicion" if (a is not None and b is not None and b < a) else "lfm3_composicion"


def conclusion(agg: dict, modelos: dict, info: dict, memoria: dict, dif_comp: dict, dif_guard: dict,
               dif_rapida: dict, ganador: str, num_ctx) -> dict:
    """Conclusión escrita SOLO a partir de los números medidos (regla de decisión explícita)."""
    q = {k: agg[k]["juez_promedio"].get("media") for k in CONFIGS_R3}
    p50 = {k: agg[k]["latencia_ruta_s"].get("p50_s") for k in CONFIGS_R3}
    jv = {k: agg[k]["json_valido_primera"].get("tasa") for k in CONFIGS_R3}
    ml, mq = modelos["lfm3_composicion"], modelos["qwen_composicion"]
    ic = dif_comp.get("ic95")
    if ic is None:
        veredicto = "no hay datos suficientes para decidir entre las dos composiciones"
    elif ic[0] > 0:
        veredicto = f"{ml} compone fichas de mayor calidad con la misma entrada; los datos respaldan usarlo en P3"
    elif ic[1] < 0:
        veredicto = f"{mq} compone fichas de mayor calidad que {ml}; los datos NO respaldan a {ml} en P3 (revisar ADR-01)"
    else:
        icg = dif_guard.get("ic95")
        pg = {k: agg[k]["pasa_guardrails_salida"].get("tasa") for k in CONFIGS_R3}
        guard = (f"{fmt_pct(pg['lfm3_composicion'])} contra {fmt_pct(pg['qwen_composicion'])} de fichas sin "
                 f"`requiere_revision` (diferencia pareada {fmt(dif_guard.get('media'))}, IC95 {fmt_ic(icg)})")
        if icg and (icg[0] > 0 or icg[1] < 0):
            veredicto = (f"la diferencia de calidad del juez no es significativa (el IC95 incluye 0), pero los guardrails "
                         f"de salida sí separan a las dos composiciones: {guard}; gana {modelos[ganador]}")
        else:
            veredicto = (f"ni la calidad del juez ni los guardrails de salida ({guard}) separan a las dos composiciones; "
                         f"decide el costo y la composición más rápida es {modelos[ganador]} "
                         f"(p50 {fmt(p50[ganador], 1)} s)")
    composicion = (f"Composición (ruta completa, P3) con la misma descripción P1: {ml} obtiene calidad "
                   f"{fmt(q['lfm3_composicion'])} y {mq} {fmt(q['qwen_composicion'])} (diferencia {ml} − {mq}: "
                   f"{fmt(dif_comp.get('media'))}, IC95 {fmt_ic(ic)}, n = {dif_comp.get('n')}); latencia p50 de la ruta "
                   f"{fmt(p50['lfm3_composicion'], 1)} s contra {fmt(p50['qwen_composicion'], 1)} s; JSON válido a la "
                   f"primera {fmt_pct(jv['lfm3_composicion'])} contra {fmt_pct(jv['qwen_composicion'])}. "
                   f"Conclusión: {veredicto}.")
    vision = [m for m in sorted(set(modelos.values())) if "vision" in ((info.get(m) or {}).get("capacidades") or [])]
    icr = dif_rapida.get("ic95")
    if icr is None:
        calidad_txt = "sin datos suficientes de calidad"
    elif icr[1] < 0:
        calidad_txt = "con menor calidad (el IC95 queda por debajo de 0)"
    elif icr[0] > 0:
        calidad_txt = "con mayor calidad (el IC95 queda por encima de 0)"
    else:
        calidad_txt = "sin diferencia significativa de calidad (el IC95 incluye 0)"
    lr, lc = p50["qwen_rapida"], p50[ganador]
    ahorro = (1 - lr / lc) if (lr is not None and lc) else None
    rapida = (f"Ruta rápida (P2): modelos con visión según /api/show: {', '.join(vision) or 'pendiente'}. "
              f"{modelos['qwen_rapida']} con visión y vecinos obtiene calidad {fmt(q['qwen_rapida'])} contra "
              f"{fmt(q[ganador])} de la ruta completa con {modelos[ganador]} (diferencia {fmt(dif_rapida.get('media'))}, "
              f"IC95 {fmt_ic(icr)}, n = {dif_rapida.get('n')}), {calidad_txt}; latencia p50 {fmt(lr, 1)} s contra "
              f"{fmt(lc, 1)} s" + (f" ({ahorro * 100:.0f} % menos)." if ahorro is not None and ahorro > 0
                                   else " (sin ahorro de latencia)."))
    d = dif_rapida.get("media")
    compromiso = ("Compromiso: " + (f"la ruta rápida cambia la calidad media en {d:+.2f} puntos" if d is not None
                                    else "el cambio de calidad de la ruta rápida queda pendiente")
                  + (f" y la latencia p50 en {-ahorro * 100:+.0f} %" if ahorro is not None else "")
                  + "; el enrutador de fichas (ADR-03, evaluacion/enrutador.py) decide foto por foto cuándo conviene.")
    recursos = "; ".join(
        f"{m}: {fmt((memoria.get(m) or {}).get('memoria_gb'))} GB cargado (/api/ps), "
        f"{fmt((info.get(m) or {}).get('tamano_disco_gb'))} GB en disco, "
        f"{(info.get(m) or {}).get('cuantizacion') or 'cuantización pendiente'}, "
        f"contexto máximo {(info.get(m) or {}).get('contexto_maximo_tokens') or 'pendiente'} tokens, "
        f"licencia {(info.get(m) or {}).get('licencia')}" for m in sorted(set(modelos.values())))
    tokens = {k: agg[k]["tokens_prompt_primera"].get("p50") for k in CONFIGS_R3}
    contexto = (f"Ventana de contexto: se usa num_ctx = {num_ctx}; el prompt de generación mide p50 "
                + ", ".join(f"{fmt(tokens[k], 0)} tokens en {k}" for k in CONFIGS_R3) + ".")
    return {
        "modelo_por_ruta": {"rapida": f"{modelos['qwen_rapida']} (P2 con visión)",
                            "completa": f"{modelos['qwen_rapida']} (P1) + {modelos[ganador]} (P3)"},
        "composicion": composicion, "ruta_rapida": rapida, "compromiso": compromiso, "recursos": recursos,
        "ventana_contexto": contexto,
        "idioma": "Todas las métricas de calidad se miden contra descripciones humanas en español (XM3600): "
                  "reflejan el desempeño en español.",
        "regla_de_decision": "P3: gana la composición de mayor calidad del juez si el IC95 de la diferencia pareada "
                             "excluye 0; si no, la que deja más fichas sin `requiere_revision` si el IC95 de esa "
                             "diferencia pareada excluye 0; si tampoco, la de menor latencia p50.",
    }


# ───────────────────────────── gráficas del R3 ─────────────────────────────
def graficas_r3(agg: dict) -> list[str]:
    n = max(agg[k]["n"] for k in CONFIGS_R3)
    cats = [ETIQUETA_CORTA[k] for k in CONFIGS_R3]
    fig, (ax,) = nueva_figura(7.5, 3.9)
    barras(ax, cats, {"Fidelidad": [agg[k]["juez_fidelidad"].get("media") for k in CONFIGS_R3],
                      "Relevancia": [agg[k]["juez_relevancia"].get("media") for k in CONFIGS_R3]},
           {"Fidelidad": [agg[k]["juez_fidelidad"].get("ic95") for k in CONFIGS_R3],
            "Relevancia": [agg[k]["juez_relevancia"].get("ic95") for k in CONFIGS_R3]})
    ax.set_ylim(0, 5.6)
    ax.set_ylabel("Puntaje del juez P7 (0–5)")
    ax.set_title(f"Calidad de la ficha por configuración (n = {n} fotos; bigotes: IC95)", pad=24)
    guardar_grafica("r3_modelos_calidad", fig)
    fig, (ax,) = nueva_figura(7.5, 3.9)
    barras(ax, cats, {"Mediana (p50)": [agg[k]["latencia_ruta_s"].get("p50_s") for k in CONFIGS_R3],
                      "Percentil 95": [agg[k]["latencia_ruta_s"].get("p95_s") for k in CONFIGS_R3]}, formato="{:.1f}")
    ax.set_ylabel("Latencia de la ruta (s)")
    ax.set_title("Latencia por configuración en CPU (las composiciones incluyen P1)", pad=24)
    guardar_grafica("r3_modelos_latencia", fig)
    return ["evaluacion/graficas/r3_modelos_calidad.png", "evaluacion/graficas/r3_modelos_latencia.png"]


# ───────────────────────────── ejecución ─────────────────────────────
def ejecutar(c: ClienteEval) -> dict:
    exigir_servicios(c)
    xm_ids = eval_fichas_muestra()
    registro(f"R3 · modelos de lenguaje: {len(xm_ids)} fotos × {len(CONFIGS_R3)} configuraciones")
    g = generar_fichas(c, xm_ids, CONFIGS_R3)
    casos: dict[str, dict[str, dict]] = {k: {} for k in CONFIGS_R3}
    for k in CONFIGS_R3:
        avance = Avance(f"calidad {k} (juez P7, granite, chrF)", len(g["ids"]))
        for x in g["ids"]:
            casos[k][x] = caso(c, k, x, g["registros"][k][x], g["p1"].get(x))
            avance.paso()
    agg = {k: agregar(list(casos[k].values())) for k in CONFIGS_R3}
    modelos = {k: c.config.modelos[ROL_MODELO[k]] for k in CONFIGS_R3}
    unicos = sorted(set(modelos.values()))
    info = ficha_tecnica(c, unicos)
    memoria = memoria_cargada(c, unicos)
    rss = rss_h0()
    p50 = {k: agg[k]["latencia_ruta_s"].get("p50_s") for k in CONFIGS_R3}
    dif_comp = diferencia_pareada(casos["lfm3_composicion"], casos["qwen_composicion"], "juez_promedio")
    dif_guard = diferencia_pareada(casos["lfm3_composicion"], casos["qwen_composicion"], "pasa_guardrails_salida")
    ganador = ganador_composicion(dif_comp, dif_guard, p50)
    dif_rapida = diferencia_pareada(casos["qwen_rapida"], casos[ganador], "juez_promedio")
    tabla, markdown = tabla_r3(agg, modelos, info, memoria, rss)
    num_ctx = c.config.parametro("generacion.num_ctx")
    p1 = g["p1"]
    metricas = {
        "conjunto": {"nombre": "eval_fichas", "fotos": len(g["ids"]), "no_subidas": g["fallidas"]},
        "por_configuracion": agg,
        "diferencias_pareadas": {
            "lfm3_composicion_menos_qwen_composicion": {**diferencia_pareada(
                casos["lfm3_composicion"], casos["qwen_composicion"], "juez_promedio"),
                "granite": diferencia_pareada(casos["lfm3_composicion"], casos["qwen_composicion"], "granite_max"),
                "chrf": diferencia_pareada(casos["lfm3_composicion"], casos["qwen_composicion"], "chrf"),
                "pasa_guardrails_salida": dif_guard},
            f"qwen_rapida_menos_{ganador}": dif_rapida},
        "tabla": tabla, "tabla_markdown": markdown,
        "conclusion": conclusion(agg, modelos, info, memoria, dif_comp, dif_guard, dif_rapida, ganador, num_ctx),
        "modelos": info, "memoria_api_ps": memoria, "memoria_rss_h0": rss,
        "docker_stats": "no se puede leer desde el contenedor `servicio` (sin acceso al socket de Docker); medir "
                        "desde el host con `docker stats`. Referencia de H0: evaluacion/resultados/h0_docker_stats.jsonl",
        "ventana_contexto": {"num_ctx": num_ctx,
                             "presupuesto_prompt_tokens": c.config.parametro("recuperacion.presupuesto_prompt_tokens", 2000),
                             "contexto_maximo_por_modelo": {m: (info.get(m) or {}).get("contexto_maximo_tokens") for m in unicos},
                             "tokens_prompt_generacion_p50": {k: agg[k]["tokens_prompt_primera"].get("p50") for k in CONFIGS_R3}},
        "p1": {"fotos": len(p1), "fallidas": sum(1 for v in p1.values() if not isinstance(v.get("p1"), dict)),
               "segundos": percentiles([v["segundos"] for v in p1.values() if v.get("segundos") is not None])},
        "metodos": METODOS,
        "graficas": graficas_r3(agg),
    }
    detalle = [fila_csv(casos[k][x]) for k in CONFIGS_R3 for x in g["ids"]]
    configuracion = {"configuraciones": {k: CONFIGURACIONES[k] for k in CONFIGS_R3}, "modelos": modelos,
                     "generacion": c.config.parametro("generacion"), "tiempos_limite_s": c.config.parametro("tiempos_limite_s")}
    guardar_resultado("r3_modelos", metricas, detalle, configuracion, c)
    registro("tabla R3:\n" + markdown)
    return metricas


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rapido", action="store_true", help="la cuarta parte de los casos (prueba de humo)")
    if ap.parse_args().rapido:
        os.environ["FOTOTECA_EVAL_RAPIDO"] = "1"
    ejecutar(ClienteEval())


if __name__ == "__main__":
    main()
