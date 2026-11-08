"""Piezas compartidas por los módulos de evaluación que generan y califican fichas (informe, §10): R3 de modelos de
lenguaje, fichas con y sin RAG, enrutador, ciclo de agente y curva de aprendizaje.

Contrato para los módulos (todo es reanudable: cada resultado se guarda caso por caso en `resultados/casos/`):

- `indice_xm()` y `referencias(xm_id)`: el índice de Crossmodal-3600 y las descripciones humanas en español.
- `asegurar_subidas(c, xm_ids)`: sube por la API (POST /documentos) las fotos de XM3600 que NO están en el archivo
  (`nuevas`, `regiones_excluidas`…) y devuelve `{xm_id: documento_id}`. Las subidas quedan con `validada=false`,
  así que nunca aparecen como vecinas en el RAG (el recuperador filtra `validada=true`).
- `p1_unico(c, xm_id, documento_id)`: la descripción P1 de Qwen, calculada UNA sola vez por foto (R3, ADR-01: las
  composiciones con Qwen y con LFM3 reciben exactamente la misma entrada).
- `ficha_evaluacion(c, config, xm_id, documento_id, **opciones)`: POST /fichas con opciones de evaluación
  (`forzar_ruta`, `sin_rag`, `sin_cache`, `max_iter`, `p1_previo`, `modelo_composicion`), guardada por
  configuración. Dos módulos que piden la misma configuración comparten la generación.
- `calidad(c, xm_id, ficha)`: juez P7 (fidelidad y relevancia 0–5), similitud granite máxima con las referencias
  y chrF del texto alternativo contra las referencias.
"""
from __future__ import annotations

import hashlib
import json
import time
from functools import lru_cache
from pathlib import Path

import numpy as np

from evaluacion.comun import ClienteEval, Incremental, registro

DIR_PROMPTS_EVAL = Path(__file__).resolve().parent / "prompts"

# Configuraciones de ficha con nombre fijo: el mismo nombre = la misma generación compartida entre módulos.
CONFIGURACIONES = {
    # R3 (ADR-01) · las tres configuraciones de modelos de lenguaje
    "qwen_rapida": {"forzar_ruta": "rapida", "sin_cache": True},
    "qwen_composicion": {"forzar_ruta": "completa", "modelo_composicion": "vision", "sin_cache": True},
    "lfm3_composicion": {"forzar_ruta": "completa", "modelo_composicion": "composicion", "sin_cache": True},
    # Resultados con RAG · con RAG (el flujo de producción, con su enrutador) y sin RAG
    "con_rag": {"sin_cache": True},
    "sin_rag": {"sin_rag": True, "sin_cache": True},
    # Ciclo de agente (ADR-07) · con el ciclo (producción) y sin él
    "agente_con_ciclo": {"sin_cache": True},
    "agente_sin_ciclo": {"max_iter": 0, "sin_cache": True},
}


# ───────────────────────────── datos de referencia ─────────────────────────────
@lru_cache(maxsize=1)
def indice_xm() -> dict[str, dict]:
    """xm_id → registro de XM3600 (clave, locale, `es` con las descripciones en español, `ruta` del archivo)."""
    from scripts._xm3600 import cargar_indice
    regs, dir_img = cargar_indice()
    return {f"xm-{r['clave']}": {**r, "ruta": dir_img / r["archivo"]} for r in regs}


def referencias(xm_id: str) -> list[str]:
    return list(indice_xm()[xm_id]["es"])


# ───────────────────────────── fotos de evaluación ─────────────────────────────
def asegurar_subidas(c: ClienteEval, xm_ids: list[str]) -> dict[str, str]:
    inc = Incremental("subidas")
    salida: dict[str, str] = {}
    for x in xm_ids:
        previo = inc.obtener(x)
        if previo:
            salida[x] = previo["documento_id"]
            continue
        r = c.subir_foto(indice_xm()[x]["ruta"], nombre=f"{x}.jpg")
        if r.get("estado_http") not in (200, 201) or not r.get("documentos"):
            raise RuntimeError(f"No se pudo subir {x}: {json.dumps(r, ensure_ascii=False)[:300]}")
        doc = r["documentos"][0]
        inc.guardar(x, {"documento_id": doc["documento_id"], "duplicados": r.get("duplicados", [])})
        salida[x] = doc["documento_id"]
    return salida


# ───────────────────────────── generación ─────────────────────────────
def p1_unico(c: ClienteEval, xm_id: str, documento_id: str) -> dict:
    """{"p1": dict | None, "segundos": float, "modelo": str, "error": str | None}; se calcula una sola vez."""
    inc = Incremental("p1")
    previo = inc.obtener(xm_id)
    if previo:
        return previo
    imagen = c.contenedor.almacen_documentos.obtener_foto(documento_id)
    t0 = time.perf_counter()
    try:
        s = c.contenedor.gateway.ejecutar("P1", {}, imagenes=[imagen])
        registro_p1 = {"p1": s.datos, "modelo": s.modelo, "intentos": s.intentos, "error": None}
    except Exception as e:  # noqa: BLE001 — se registra y la composición recibe p1 = None
        registro_p1 = {"p1": None, "modelo": None, "intentos": None, "error": type(e).__name__}
    return inc.guardar(xm_id, {**registro_p1, "documento_id": documento_id,
                               "segundos": round(time.perf_counter() - t0, 3)})


def ficha_evaluacion(c: ClienteEval, config: str, xm_id: str, documento_id: str, **extra) -> dict:
    """POST /fichas con la configuración `config` (de CONFIGURACIONES, más `extra`). Devuelve el registro guardado:
    {"estado_http", "respuesta", "segundos", "opciones"}."""
    inc = Incremental(f"fichas_{config}")
    previo = inc.obtener(xm_id)
    if previo:
        return previo
    opciones = {**CONFIGURACIONES.get(config, {}), **extra}
    estado, cuerpo, seg = c.ficha(documento_id, **opciones)
    opciones_guardadas = {k: v for k, v in opciones.items() if k != "p1_previo"}
    return inc.guardar(xm_id, {"documento_id": documento_id, "estado_http": estado, "respuesta": cuerpo,
                               "segundos": round(seg, 3), "opciones": opciones_guardadas})


# ───────────────────────────── calidad ─────────────────────────────
@lru_cache(maxsize=1)
def _plantilla_juez():
    from fototeca.modelos.plantillas import leer_plantilla
    return leer_plantilla(DIR_PROMPTS_EVAL / "P7_juez.md")


def _gateway_juez(c: ClienteEval):
    from fototeca.modelos.gateway import Gateway
    plantillas = dict(c.contenedor.gateway.plantillas)
    plantillas["P7"] = _plantilla_juez()
    return Gateway(c.contenedor.cliente_llm, c.config, plantillas)


def juez(c: ClienteEval, xm_id: str, ficha: dict) -> dict:
    """P7 con LFM3 (temperatura 0). Devuelve {"fidelidad", "relevancia", "justificacion"} o {"error"}."""
    clave = hashlib.sha256(json.dumps([xm_id, ficha.get("titular"), ficha.get("texto_alternativo"),
                                       ficha.get("descripcion")], ensure_ascii=False).encode()).hexdigest()[:20]
    inc = Incremental("juez")
    previo = inc.obtener(clave)
    if previo:
        return previo
    variables = {"referencias": " | ".join(referencias(xm_id)), "titular": ficha.get("titular") or "",
                 "texto_alternativo": ficha.get("texto_alternativo") or "", "descripcion": ficha.get("descripcion") or ""}
    t0 = time.perf_counter()
    try:
        s = _gateway_juez(c).ejecutar("P7", variables, permitir_respaldo=False)
        datos = {"fidelidad": int(s.datos["fidelidad"]), "relevancia": int(s.datos["relevancia"]),
                 "justificacion": s.datos.get("justificacion", ""), "modelo": s.modelo}
    except Exception as e:  # noqa: BLE001
        datos = {"error": type(e).__name__}
    return inc.guardar(clave, {"xm_id": xm_id, **datos, "segundos": round(time.perf_counter() - t0, 3)})


def similitud_granite(c: ClienteEval, texto: str, refs: list[str]) -> float | None:
    """Máximo del coseno (granite) entre `texto` y cada referencia."""
    if not texto or not refs:
        return None
    m = c.contenedor.embebedor_secundario.embeber_textos([texto] + list(refs))
    return round(float(np.max(m[1:] @ m[0])), 4)


def chrf(texto: str, refs: list[str]) -> float | None:
    if not texto or not refs:
        return None
    from sacrebleu.metrics import CHRF
    return round(float(CHRF().sentence_score(texto, list(refs)).score), 2)


def calidad(c: ClienteEval, xm_id: str, ficha: dict, con_juez: bool = True) -> dict:
    """Métricas de calidad de una ficha contra las referencias humanas de su foto (R3 y resultados con RAG)."""
    refs = referencias(xm_id)
    alt = (ficha or {}).get("texto_alternativo") or ""
    j = juez(c, xm_id, ficha or {}) if con_juez else {}
    fid, rel = j.get("fidelidad"), j.get("relevancia")
    return {
        "juez_fidelidad": fid, "juez_relevancia": rel,
        "juez_promedio": round((fid + rel) / 2, 2) if fid is not None and rel is not None else None,
        "juez_error": j.get("error"),
        "granite_max": similitud_granite(c, alt, refs), "chrf": chrf(alt, refs),
        "alt_caracteres": len(alt), "alt_vacio": not alt,
    }


def resumen_numerico(valores: list[float | None]) -> dict:
    v = np.array([x for x in valores if x is not None], dtype=float)
    if not v.size:
        return {"n": 0}
    return {"n": int(v.size), "media": round(float(v.mean()), 4), "p50": round(float(np.percentile(v, 50)), 4),
            "p95": round(float(np.percentile(v, 95)), 4), "min": round(float(v.min()), 4), "max": round(float(v.max()), 4)}


def intervalo_bootstrap(valores: list[float], n: int = 1000, semilla: int = 2026) -> tuple[float, float] | None:
    """IC95 % de la media por bootstrap (para reportar la incertidumbre con muestras pequeñas)."""
    v = np.array([x for x in valores if x is not None], dtype=float)
    if v.size < 2:
        return None
    rng = np.random.default_rng(semilla)
    medias = rng.choice(v, size=(n, v.size), replace=True).mean(axis=1)
    return round(float(np.percentile(medias, 2.5)), 4), round(float(np.percentile(medias, 97.5)), 4)


def avisar(mensaje: str) -> None:
    registro(mensaje)
