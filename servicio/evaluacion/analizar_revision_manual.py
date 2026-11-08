"""Análisis de la revisión manual (tareas del autor) y escritura protegida de las plantillas.

Cuando el autor llena las plantillas de `evaluacion/revision_manual/`, este módulo calcula:

- `plantilla_fichas.csv` (la genera rag_fichas): acuerdo entre el juez (P7) y el humano en fidelidad y relevancia
  (0–5): correlación de Spearman (rangos promedio en los empates, calculada con numpy) y error absoluto medio, por
  dimensión y con las dos dimensiones juntas.
- `plantilla_guardrails.csv` (la genera guardrails): precisión de las activaciones de los guardrails de salida
  (proporción que el autor marca como correctas), global y por verificación.
- `plantilla_tesauro.csv` (la genera r3_embeddings): precisión del concepto esperado por coincidencia léxica.
  `muestra_mapeo_oi_tesauro.csv` (la genera indexar_archivo): precisión del mapeo del sistema (embeddings con
  τ_tesauro) sobre los pares mapeados y, si hay suficientes pares revisados, un umbral sugerido.
- `plantilla_consultas.csv` (la genera generar_sinteticos): proporción de consultas complejas naturales y de
  relevantes correctos.

Si una plantilla no existe o no tiene respuestas del autor, se reporta «pendiente» con la razón. No llama a modelos.

    python -m evaluacion.analizar_revision_manual
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from pathlib import Path

import numpy as np

from evaluacion.comun import REVISION, guardar_resultado, registro

PRECISION_MINIMA_TESAURO = 0.90      # misma regla con la que indexar_archivo calibra τ_tesauro
MINIMO_PARES_TESAURO = 10


# ───────────────────────────── lectura y escritura de plantillas ─────────────────────────────
def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos, sin lo que va entre paréntesis y sin espacios sobrantes."""
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).lower()
    t = re.sub(r"\(.*?\)", "", t)
    return re.sub(r"\s+", " ", t).strip()


def ruta_visible(ruta: Path) -> str:
    return f"evaluacion/revision_manual/{ruta.name}"


def leer_plantilla(ruta: Path) -> tuple[list[str], list[dict]]:
    """Lee el CSV aunque el autor lo haya guardado con otra codificación o con «;» (Excel en español)."""
    crudo = ruta.read_bytes()
    for codificacion in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            texto = crudo.decode(codificacion)
            break
        except UnicodeDecodeError:
            continue
    primera = texto.splitlines()[0] if texto.strip() else ""
    separador = max((",", ";", "\t"), key=primera.count) if primera else ","
    lector = csv.DictReader(io.StringIO(texto), delimiter=separador)
    filas = [f for f in lector if any((v or "").strip() for v in f.values() if isinstance(v, str))]
    return list(lector.fieldnames or []), filas


def columna(encabezados: list[str], prefijo: str) -> str | None:
    """El encabezado cuyo nombre normalizado empieza con `prefijo` (p. ej. «humano_fidelidad (0-5)»)."""
    p = normalizar(prefijo)
    return next((e for e in encabezados if normalizar(e).startswith(p)), None)


def plantilla_con_respuestas(ruta: Path, columnas_humanas: tuple[str, ...]) -> bool:
    """True si la plantilla existe y alguna columna del autor ya tiene datos (entonces no se sobrescribe)."""
    if not ruta.exists():
        return False
    try:
        encabezados, filas = leer_plantilla(ruta)
    except Exception:  # noqa: BLE001 — si no se puede leer, mejor no tocarla
        return True
    humanas = [e for e in encabezados if any(normalizar(e).startswith(normalizar(h)) for h in columnas_humanas)]
    return any((f.get(h) or "").strip() for f in filas for h in humanas)


def escribir_plantilla(ruta: Path, encabezados: list[str], filas: list[list], columnas_humanas: tuple[str, ...]) -> dict:
    """Escribe la plantilla de revisión SOLO si el autor todavía no la llenó (protege su trabajo)."""
    if plantilla_con_respuestas(ruta, columnas_humanas):
        registro(f"   {ruta.name}: el autor ya la llenó; no se sobrescribe")
        return {"ruta": ruta_visible(ruta), "estado": "conservada: ya tiene respuestas del autor"}
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(ruta.name + ".tmp")
    with open(temporal, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(encabezados)
        w.writerows(filas)
    temporal.replace(ruta)
    return {"ruta": ruta_visible(ruta), "estado": "escrita", "filas": len(filas)}


# ───────────────────────────── valores del autor ─────────────────────────────
def si_no(valor: str | None) -> float | None:
    """«si»→1, «no»→0, «parcial»→0.5; vacío o no interpretable → None."""
    v = normalizar(valor or "").strip(" .")
    if not v:
        return None
    if v in ("si", "s", "yes", "y", "1", "true", "verdadero", "x", "correcto", "correcta"):
        return 1.0
    if v in ("no", "n", "0", "false", "falso", "incorrecto", "incorrecta"):
        return 0.0
    if v in ("parcial", "p", "0.5", "0,5", "medio"):
        return 0.5
    return None


def numero(valor: str | None) -> float | None:
    v = (valor or "").strip().replace(",", ".")
    try:
        return float(v) if v else None
    except ValueError:
        return None


def rangos_promedio(x: np.ndarray) -> np.ndarray:
    """Rangos 1..n con el promedio en los empates (lo que usa Spearman)."""
    x = np.asarray(x, dtype=float)
    orden = np.argsort(x, kind="mergesort")
    r = np.empty(len(x), dtype=float)
    r[orden] = np.arange(1, len(x) + 1)
    _, inverso, cuentas = np.unique(x, return_inverse=True, return_counts=True)
    return (np.bincount(inverso, weights=r) / cuentas)[inverso]


def spearman(a: list[float], b: list[float]) -> float | None:
    """ρ de Spearman = correlación de Pearson entre los rangos. None si una de las dos series es constante."""
    if len(a) < 3:
        return None
    ra, rb = rangos_promedio(np.asarray(a)), rangos_promedio(np.asarray(b))
    if ra.std() == 0 or rb.std() == 0:
        return None
    return round(float(np.corrcoef(ra, rb)[0, 1]), 4)


def _pendiente(ruta: Path, razon: str) -> dict:
    return {"estado": f"pendiente: {razon}", "plantilla": ruta_visible(ruta)}


# ───────────────────────────── análisis por plantilla ─────────────────────────────
def analizar_fichas() -> dict:
    ruta = REVISION / "plantilla_fichas.csv"
    if not ruta.exists():
        return _pendiente(ruta, "la plantilla no existe todavía (la genera rag_fichas)")
    encabezados, filas = leer_plantilla(ruta)
    salida = {"estado": "ok", "plantilla": ruta_visible(ruta), "filas": len(filas), "por_dimension": {}}
    todos_j, todos_h = [], []
    for dim in ("fidelidad", "relevancia"):
        cj, ch = columna(encabezados, f"juez_{dim}"), columna(encabezados, f"humano_{dim}")
        if not cj or not ch:
            salida["por_dimension"][dim] = {"estado": "pendiente: faltan las columnas del juez o del humano"}
            continue
        pares = [(numero(f.get(cj)), numero(f.get(ch))) for f in filas]
        sin_juez = sum(1 for j, h in pares if h is not None and j is None)
        pares = [(j, h) for j, h in pares if j is not None and h is not None]
        if not pares:
            salida["por_dimension"][dim] = {"estado": "pendiente: el autor no ha calificado esta dimensión",
                                            "revisadas_sin_juez": sin_juez}
            continue
        j, h = np.array([p[0] for p in pares]), np.array([p[1] for p in pares])
        todos_j += list(j)
        todos_h += list(h)
        salida["por_dimension"][dim] = {"n": len(pares), "spearman": spearman(list(j), list(h)),
                                        "error_absoluto_medio": round(float(np.mean(np.abs(j - h))), 4),
                                        "media_juez": round(float(j.mean()), 4), "media_humano": round(float(h.mean()), 4),
                                        "sesgo_juez_menos_humano": round(float((j - h).mean()), 4),
                                        "acuerdo_exacto": round(float(np.mean(j == h)), 4),
                                        "revisadas_sin_juez": sin_juez}
    if not todos_j:
        return {**salida, "estado": "pendiente: el autor no ha llenado las columnas humano_* de la plantilla"}
    salida["ambas_dimensiones"] = {"n": len(todos_j), "spearman": spearman(todos_j, todos_h),
                                   "error_absoluto_medio": round(float(np.mean(np.abs(np.array(todos_j) - np.array(todos_h)))), 4)}
    return salida


def analizar_guardrails() -> dict:
    ruta = REVISION / "plantilla_guardrails.csv"
    if not ruta.exists():
        return _pendiente(ruta, "la plantilla no existe todavía (la genera el módulo guardrails)")
    encabezados, filas = leer_plantilla(ruta)
    cc, cv = columna(encabezados, "activacion_correcta"), columna(encabezados, "verificacion")
    if not cc:
        return _pendiente(ruta, "falta la columna activacion_correcta")
    revisadas = [(f.get(cv, "") if cv else "", si_no(f.get(cc))) for f in filas]
    validas = [(v, x) for v, x in revisadas if x is not None]
    if not validas:
        return {**_pendiente(ruta, "el autor no ha marcado ninguna activación"), "filas": len(filas)}
    por_verificacion = {}
    for v in sorted({v for v, _ in validas}):
        xs = [x for vv, x in validas if vv == v]
        por_verificacion[v] = {"revisadas": len(xs), "correctas": int(sum(x == 1.0 for x in xs)),
                               "precision": round(float(np.mean([x == 1.0 for x in xs])), 4)}
    return {"estado": "ok", "plantilla": ruta_visible(ruta), "filas": len(filas), "revisadas": len(validas),
            "no_interpretables": sum(1 for f in filas if (f.get(cc) or "").strip() and si_no(f.get(cc)) is None),
            "correctas": int(sum(x == 1.0 for _, x in validas)),
            "precision": round(float(np.mean([x == 1.0 for _, x in validas])), 4),
            "por_verificacion": por_verificacion}


def analizar_tesauro_lexico() -> dict:
    ruta = REVISION / "plantilla_tesauro.csv"
    if not ruta.exists():
        return _pendiente(ruta, "la plantilla no existe todavía (la genera r3_embeddings)")
    encabezados, filas = leer_plantilla(ruta)
    cc, cu = columna(encabezados, "esperado_correcto"), columna(encabezados, "concepto_correcto")
    if not cc:
        return _pendiente(ruta, "falta la columna esperado_correcto")
    marcas = [si_no(f.get(cc)) for f in filas]
    validas = [m for m in marcas if m is not None]
    if not validas:
        return {**_pendiente(ruta, "el autor no ha revisado ningún par"), "filas": len(filas)}
    return {"estado": "ok", "plantilla": ruta_visible(ruta), "filas": len(filas), "revisadas": len(validas),
            "esperado_correcto": int(sum(m == 1.0 for m in validas)),
            "precision_esperado_lexico": round(float(np.mean([m == 1.0 for m in validas])), 4),
            "correcciones_con_uri": sum(1 for f in filas if cu and (f.get(cu) or "").strip())}


def analizar_tesauro_mapeo() -> dict:
    ruta = REVISION / "muestra_mapeo_oi_tesauro.csv"
    if not ruta.exists():
        return _pendiente(ruta, "la muestra no existe todavía (la genera indexar_archivo)")
    encabezados, filas = leer_plantilla(ruta)
    cc, cm, cs = columna(encabezados, "correcto"), columna(encabezados, "mapeado_con_umbral"), columna(encabezados, "similitud")
    if not cc or not cm or not cs:
        return _pendiente(ruta, "faltan columnas (correcto, mapeado_con_umbral o similitud)")
    revisadas = []
    for f in filas:
        marca = si_no(f.get(cc))
        if marca is None:
            continue
        mapeado = normalizar(f.get(cm) or "") in ("true", "1", "si", "verdadero")
        revisadas.append({"mapeado": mapeado, "correcto": marca == 1.0, "similitud": numero(f.get(cs))})
    if not revisadas:
        return {**_pendiente(ruta, "el autor no ha revisado ningún par"), "filas": len(filas)}
    mapeadas = [r for r in revisadas if r["mapeado"]]
    salida = {"estado": "ok", "plantilla": ruta_visible(ruta), "filas": len(filas), "revisadas": len(revisadas),
              "revisadas_mapeadas": len(mapeadas),
              "precision_mapeadas": round(float(np.mean([r["correcto"] for r in mapeadas])), 4) if mapeadas else None}
    con_sim = sorted((r for r in mapeadas if r["similitud"] is not None), key=lambda r: r["similitud"])
    curva = []
    for i, r in enumerate(con_sim):
        resto = con_sim[i:]
        curva.append({"tau": r["similitud"], "pares": len(resto),
                      "precision": round(float(np.mean([x["correcto"] for x in resto])), 4)})
    validos = [p for p in curva if p["precision"] >= PRECISION_MINIMA_TESAURO and p["pares"] >= MINIMO_PARES_TESAURO]
    salida["umbral_sugerido"] = (
        {"tau": min(p["tau"] for p in validos),
         "regla": f"el τ más bajo (entre las similitudes revisadas y mapeadas) con precisión ≥ {PRECISION_MINIMA_TESAURO} "
                  f"y ≥ {MINIMO_PARES_TESAURO} pares; solo puede subir el umbral actual (los pares no mapeados no muestran "
                  "concepto)"}
        if validos else
        {"tau": None, "razon": f"no hay un umbral con precisión ≥ {PRECISION_MINIMA_TESAURO} y ≥ {MINIMO_PARES_TESAURO} "
                               "pares revisados"})
    salida["curva_precision"] = curva
    return salida


def analizar_consultas() -> dict:
    ruta = REVISION / "plantilla_consultas.csv"
    if not ruta.exists():
        return _pendiente(ruta, "la plantilla no existe todavía (la genera preparar_datos con generar_sinteticos)")
    encabezados, filas = leer_plantilla(ruta)
    cn, cr = columna(encabezados, "consulta_es_natural"), columna(encabezados, "relevantes_correctos")
    naturales = [si_no(f.get(cn)) for f in filas] if cn else []
    relevantes = [si_no(f.get(cr)) for f in filas] if cr else []
    naturales = [x for x in naturales if x is not None]
    relevantes = [x for x in relevantes if x is not None]
    if not naturales and not relevantes:
        return {**_pendiente(ruta, "el autor no ha revisado ninguna consulta"), "filas": len(filas)}
    return {"estado": "ok", "plantilla": ruta_visible(ruta), "filas": len(filas),
            "consulta_natural": {"revisadas": len(naturales),
                                 "proporcion_si": round(float(np.mean([x == 1.0 for x in naturales])), 4) if naturales else None},
            "relevantes_correctos": {"revisadas": len(relevantes),
                                     "si": sum(1 for x in relevantes if x == 1.0),
                                     "parcial": sum(1 for x in relevantes if x == 0.5),
                                     "no": sum(1 for x in relevantes if x == 0.0),
                                     "puntaje_medio (si=1, parcial=0.5, no=0)":
                                         round(float(np.mean(relevantes)), 4) if relevantes else None}}


def ejecutar(c=None) -> dict:
    metricas = {"fichas_juez_contra_humano": analizar_fichas(), "guardrails_activaciones": analizar_guardrails(),
                "tesauro_esperado_lexico": analizar_tesauro_lexico(), "tesauro_mapeo_sistema": analizar_tesauro_mapeo(),
                "consultas_complejas": analizar_consultas()}
    for nombre, m in metricas.items():
        registro(f"   {nombre}: {m.get('estado')}")
    guardar_resultado("revision_manual", metricas,
                      configuracion={"directorio": "evaluacion/revision_manual/",
                                     "valores_aceptados": "si/sí/no/parcial (sin importar mayúsculas ni acentos); "
                                                          "calificaciones 0–5 con punto o coma decimal"},
                      cliente=c)
    return metricas


if __name__ == "__main__":
    ejecutar(None)
