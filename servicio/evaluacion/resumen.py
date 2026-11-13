"""Genera `evaluacion/resultados/RESUMEN.md` a partir de TODOS los `evaluacion/resultados/*.json` que existan.

Cada cifra se copia tal cual de su archivo, con su fuente (archivo › clave dentro del JSON). Lo que falta (un módulo
que no ha corrido o una clave que no existe) aparece como «pendiente». No calcula cifras nuevas ni llama al servicio.

    python -m evaluacion.resumen
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

from evaluacion.comun import RESULTADOS, ahora, registro

CONFIG = Path(os.environ.get("FOTOTECA_CONFIG", Path(__file__).resolve().parents[1] / "config"))
MAX_FILAS_POR_ARCHIVO = 400
MAX_TEXTO = 160
UNIFICADO = "unificado (EmbeddingGemma-2 texto→imagen)"

MODULOS = [("r3_embeddings", "R3 · embeddings y arquitectura de búsqueda"),
           ("r3_modelos", "R3 · modelos de lenguaje"),
           ("rag_fichas", "Resultados del producto con y sin RAG"),
           ("enrutador", "Enrutador de fichas y de búsquedas"),
           ("agente", "Ciclo de agente"),
           ("guardrails", "Guardrails de entrada y de salida"),
           ("cache", "Caché exacta y semántica"),
           ("aprendizaje", "Retroalimentación y curva de aprendizaje (simulación)"),
           ("desempeno", "Desempeño por capa (trazas)"),
           ("revision_manual", "Revisión manual del autor")]

# Cifras principales: (etiqueta, ruta de claves dentro del JSON). Si la clave no existe → «pendiente».
DESTACADOS: dict[str, list[tuple[str, tuple]]] = {
    "r3_embeddings": [
        ("Tamaño de la sub-galería (comparación de arquitecturas)", ("metricas", "galeria", "n")),
        ("R@10 texto→imagen · unificado", ("metricas", "texto_imagen", UNIFICADO, "R@10")),
        ("R@10 texto→imagen · pipeline Qwen + EmbeddingGemma-2", ("metricas", "texto_imagen", "pipeline (Qwen + EmbeddingGemma-2 texto→texto)", "R@10")),
        ("R@10 texto→imagen · pipeline Qwen + granite", ("metricas", "texto_imagen", "pipeline (Qwen + granite texto→texto)", "R@10")),
        ("R@10 texto→imagen · híbrido", ("metricas", "texto_imagen", "hibrido (RRF unificado + pipeline EmbeddingGemma-2)", "R@10")),
        ("MRR · unificado", ("metricas", "texto_imagen", UNIFICADO, "MRR")),
        ("Galería completa: n", ("metricas", "texto_imagen_galeria_completa", "n")),
        ("Galería completa: R@10 · unificado", ("metricas", "texto_imagen_galeria_completa", UNIFICADO, "R@10")),
        ("Segundos por descripción de Qwen (pipeline)", ("metricas", "costo_pipeline", "segundos_por_descripcion_qwen")),
        ("Descripción→descripción R@1 · EmbeddingGemma-2", ("metricas", "descripcion_descripcion", "EmbeddingGemma-2", "R@1")),
        ("Descripción→descripción R@1 · granite", ("metricas", "descripcion_descripcion", "granite", "R@1")),
        ("Tesauro exactitud top-1 · EmbeddingGemma-2", ("metricas", "tesauro", "por_modelo", "EmbeddingGemma-2", "exactitud_top1")),
        ("Tesauro exactitud top-1 · granite", ("metricas", "tesauro", "por_modelo", "granite", "exactitud_top1")),
        ("Normas acierto@4 · EmbeddingGemma-2", ("metricas", "normas", "por_modelo", "EmbeddingGemma-2", "acierto@4")),
        ("Normas acierto@4 · granite", ("metricas", "normas", "por_modelo", "granite", "acierto@4")),
    ],
    "guardrails": [
        ("Entradas problemáticas bien manejadas (tasa)", ("metricas", "entrada", "global", "tasa_correctas")),
        ("Entradas problemáticas (n)", ("metricas", "entrada", "global", "problematicas")),
        ("Falsos positivos sobre entradas normales (tasa)", ("metricas", "entrada", "global", "tasa_falsos_positivos")),
        ("Entradas normales (n)", ("metricas", "entrada", "global", "normales")),
        *[(etiqueta, ("metricas", "entrada", "por_verificacion", v, "tasa_correctas"))
          for etiqueta, v in (("Inyección en imagen marcada y aislada (tasa)", "inyeccion_en_imagen"),
                              ("Fuera de dominio bloqueado (tasa)", "fuera_de_dominio"),
                              ("GPS y datos del autor eliminados (tasa)", "exif_privacidad"),
                              ("Consultas con inyección bloqueadas (tasa)", "inyeccion_texto"),
                              ("Consultas con datos personales enmascaradas (tasa)", "pii_texto"))],
        ("Detector de inyección con el texto real: detección", ("metricas", "detector_inyeccion_componente", "tasa_deteccion")),
        ("Detector de inyección con el texto real: falsos positivos",
         ("metricas", "detector_inyeccion_componente", "tasa_falsos_positivos")),
        *[(f"Fichas con_rag donde se activó {v} (tasa)", ("metricas", "salida_fichas", "con_rag", "por_verificacion", v, "tasa_activacion"))
          for v in ("apego_visual", "consistencia", "atributos_sensibles", "fuentes")],
    ],
    "cache": [
        ("τ_dup elegido (ADR-04)", ("metricas", "fichas_semantica_tau_dup", "tau_elegido")),
        ("Criterio", ("metricas", "fichas_semantica_tau_dup", "criterio")),
        ("Recall en τ elegido", ("metricas", "fichas_semantica_tau_dup", "en_tau_elegido", "recall")),
        ("FPR (incorrectas servidas) en τ elegido", ("metricas", "fichas_semantica_tau_dup", "en_tau_elegido", "fpr")),
        ("τ_dup configurado", ("metricas", "fichas_semantica_tau_dup", "tau_configurado")),
        ("Recall en τ configurado", ("metricas", "fichas_semantica_tau_dup", "en_tau_configurado", "recall")),
        ("FPR en τ configurado", ("metricas", "fichas_semantica_tau_dup", "en_tau_configurado", "fpr")),
        ("Fichas: tasa de aciertos de la caché exacta", ("metricas", "fichas_exacta", "tasa_aciertos_exactos")),
        ("Fichas: p50 sin caché (s)", ("metricas", "fichas_exacta", "latencia_cliente_s", "sin_cache", "p50_s")),
        ("Fichas: p50 con caché (s)", ("metricas", "fichas_exacta", "latencia_cliente_s", "con_cache", "p50_s")),
        ("Fichas: reducción del p50 (%)", ("metricas", "fichas_exacta", "latencia_cliente_s", "reduccion_p50_porcentaje")),
        ("Búsquedas repetidas: tasa de aciertos exactos", ("metricas", "busquedas", "repetidas", "tasa_aciertos")),
        ("Búsquedas parafraseadas: tasa de aciertos semánticos", ("metricas", "busquedas", "parafraseadas", "tasa_aciertos")),
        ("Búsquedas parafraseadas: respuestas incorrectas servidas", ("metricas", "busquedas", "parafraseadas", "respuestas_incorrectas_servidas")),
        ("Búsquedas: reducción del p50 con caché exacta (%)", ("metricas", "busquedas", "latencia_cliente_s", "exacta", "reduccion_p50_porcentaje")),
        ("Prueba de invalidación aprobada", ("metricas", "invalidacion", "aprobada")),
    ],
    "aprendizaje": [
        ("Simulación", ("metricas", "simulacion")),
        ("Estado", ("metricas", "estado")),
        ("Umbral «aceptable sin edición»", ("metricas", "umbral_aceptable_sin_edicion", "umbral")),
        *[(f"Bloque {i + 1}: {nombre}", ("metricas", "bloques", i, clave))
          for i in range(5) for nombre, clave in (("correcciones previas", "correcciones_acumuladas_antes"),
                                                  ("similitud granite media", "granite_media"),
                                                  ("tasa aceptable sin edición", "tasa_aceptable"))],
        ("Fichas promovidas como ejemplos", ("metricas", "estado_de_la_base", "n_promovidos")),
        ("T2 (simulación): tasa de «útil»", ("metricas", "retroalimentacion_t2", "simulacion", "tasa_util")),
    ],
    "desempeno": [
        ("Eventos considerados", ("metricas", "ventana", "eventos")),
        ("Fichas: n", ("metricas", "total", "fichas", "n")),
        ("Fichas: media (ms)", ("metricas", "total", "fichas", "media_ms")),
        ("Fichas: p50 (ms)", ("metricas", "total", "fichas", "p50_ms")),
        ("Fichas: p95 (ms)", ("metricas", "total", "fichas", "p95_ms")),
        ("Fichas: máximo (ms)", ("metricas", "total", "fichas", "max_ms")),
        ("Búsquedas: n", ("metricas", "total", "busquedas", "n")),
        ("Búsquedas: media (ms)", ("metricas", "total", "busquedas", "media_ms")),
        ("Búsquedas: p50 (ms)", ("metricas", "total", "busquedas", "p50_ms")),
        ("Búsquedas: p95 (ms)", ("metricas", "total", "busquedas", "p95_ms")),
        ("Búsquedas: máximo (ms)", ("metricas", "total", "busquedas", "max_ms")),
    ],
    "revision_manual": [
        ("Fichas: estado", ("metricas", "fichas_juez_contra_humano", "estado")),
        ("Fichas: Spearman juez–humano (ambas dimensiones)", ("metricas", "fichas_juez_contra_humano", "ambas_dimensiones", "spearman")),
        ("Fichas: error absoluto medio juez–humano", ("metricas", "fichas_juez_contra_humano", "ambas_dimensiones", "error_absoluto_medio")),
        ("Guardrails: estado", ("metricas", "guardrails_activaciones", "estado")),
        ("Guardrails: precisión de las activaciones", ("metricas", "guardrails_activaciones", "precision")),
        ("Tesauro (esperado léxico): estado", ("metricas", "tesauro_esperado_lexico", "estado")),
        ("Tesauro (mapeo del sistema): precisión de los pares mapeados", ("metricas", "tesauro_mapeo_sistema", "precision_mapeadas")),
        ("Consultas complejas: estado", ("metricas", "consultas_complejas", "estado")),
    ],
}


# ───────────────────────────── utilidades ─────────────────────────────
class Falta(Exception):
    pass


def obtener(datos, ruta: tuple):
    nodo = datos
    for clave in ruta:
        if isinstance(nodo, dict) and clave in nodo:
            nodo = nodo[clave]
        elif isinstance(nodo, list) and isinstance(clave, int) and -len(nodo) <= clave < len(nodo):
            nodo = nodo[clave]
        else:
            raise Falta
    return nodo


def celda(valor) -> str:
    """El valor tal cual (JSON para números, booleanos, nulos y listas cortas), apto para una tabla Markdown."""
    texto = valor if isinstance(valor, str) else json.dumps(valor, ensure_ascii=False)
    return texto.replace("|", "\\|").replace("\n", " ")


def ruta_texto(ruta: tuple) -> str:
    return " › ".join(f"[{c}]" if isinstance(c, int) else str(c) for c in ruta)


def fuente(archivo: str, ruta: tuple) -> str:
    return f"`evaluacion/resultados/{archivo}` › {celda(ruta_texto(ruta))}"


def aplanar(obj, ruta: tuple = ()):
    """Hojas (ruta, valor). Las listas cortas de valores simples se muestran completas en una sola celda."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from aplanar(v, ruta + (k,))
    elif isinstance(obj, list):
        simples = all(isinstance(x, (int, float, bool, str, type(None))) for x in obj)
        if simples and len(obj) <= 12 and len(json.dumps(obj, ensure_ascii=False)) <= MAX_TEXTO:
            yield ruta, obj
        else:
            for i, v in enumerate(obj):
                yield from aplanar(v, ruta + (i,))
    else:
        yield ruta, obj


def leer_resultados() -> dict[str, dict | list]:
    datos = {}
    for ruta in sorted(RESULTADOS.glob("*.json")):
        try:
            datos[ruta.name] = json.loads(ruta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            datos[ruta.name] = {"_error_de_lectura": f"{type(e).__name__}: {e}"}
    return datos


# ───────────────────────────── secciones ─────────────────────────────
def seccion_estado(datos: dict) -> list[str]:
    ejecucion = (datos.get("ejecucion_evaluacion.json") or {}).get("modulos", {}) if isinstance(datos.get("ejecucion_evaluacion.json"), dict) else {}
    lineas = ["## 1. Estado de los módulos", "",
              "| Módulo | Qué mide | Archivo | Fecha | Modo | Versión de configuración | Última ejecución |",
              "|---|---|---|---|---|---|---|"]
    for modulo, descripcion in MODULOS:
        archivo = f"{modulo}.json"
        nombre_ejec = "analizar_revision_manual" if modulo == "revision_manual" else modulo
        ejec = ejecucion.get(nombre_ejec)
        ultima = f"{ejec.get('estado')} ({celda(ejec.get('segundos'))} s)" if ejec else "pendiente: sin registro"
        d = datos.get(archivo)
        if not isinstance(d, dict):
            lineas.append(f"| {modulo} | {descripcion} | pendiente: no existe `{archivo}` | — | — | — | {ultima} |")
            continue
        modo = ("rápido (prueba de humo)" if d.get("rapido") else
                f"parcial ({round(float(d['fraccion']) * 100)} % de cada conjunto)" if d.get("fraccion") not in (None, 1, 1.0)
                else "completo")
        lineas.append(f"| {modulo} | {descripcion} | `evaluacion/resultados/{archivo}` | {celda(d.get('fecha'))} | {modo} | "
                      f"{celda(d.get('version_configuracion'))} | {ultima} |")
    otros = [a for a in datos if a not in {f"{m}.json" for m, _ in MODULOS}]
    if otros:
        lineas += ["", "Otros archivos de resultados: " + ", ".join(f"`{a}`" for a in otros) + "."]
    return lineas + [""]


def seccion_destacados(datos: dict) -> list[str]:
    lineas = ["## 2. Cifras principales", ""]
    for modulo, descripcion in MODULOS:
        archivo = f"{modulo}.json"
        lineas += [f"### {descripcion}", ""]
        d = datos.get(archivo)
        if not isinstance(d, dict):
            generador = "analizar_revision_manual" if modulo == "revision_manual" else modulo
            lineas += [f"pendiente: el módulo `{generador}` todavía no ha generado `evaluacion/resultados/{archivo}`.", ""]
            continue
        if modulo not in DESTACADOS:
            n = sum(1 for _ in aplanar(d.get("metricas", d)))
            lineas += [f"Sus {n} cifras están en la sección 4 (`{archivo}`).", ""]
            continue
        lineas += ["| Métrica | Valor | Fuente |", "|---|---|---|"]
        for etiqueta, ruta in DESTACADOS[modulo]:
            try:
                valor = celda(obtener(d, ruta))
            except Falta:
                valor = "pendiente (la clave no existe en el archivo)"
            lineas.append(f"| {etiqueta} | {valor} | {fuente(archivo, ruta)} |")
        lineas.append("")
    return lineas


def seccion_metas(datos: dict) -> list[str]:
    lineas = ["## 3. Metas de calidad", "",
              "Las metas se leen de `servicio/config/metas_calidad.yaml`; lo medido sale del archivo de la columna «Fuente».", "",
              "| Meta | Valor meta | Medido | ¿Cumple? | Fuente |", "|---|---|---|---|---|"]
    try:
        metas = yaml.safe_load((CONFIG / "metas_calidad.yaml").read_text(encoding="utf-8")) or {}
    except OSError:
        return lineas + ["| — | pendiente: no se pudo leer metas_calidad.yaml | — | — | — |", ""]
    medidas = {
        ("latencia_s", k): ("desempeno.json", ("metricas", "metas_latencia", k), "medido_s", "cumple")
        for k in (metas.get("latencia_s") or {})}
    medidas.update({
        ("guardrails", "bloqueos_correctos_min"): ("guardrails.json", ("metricas", "entrada", "metas", "bloqueos_correctos_min"), "medido", "cumple"),
        ("guardrails", "falsos_positivos_max"): ("guardrails.json", ("metricas", "entrada", "metas", "falsos_positivos_max"), "medido", "cumple"),
        ("privacidad", "salidas_sin_gps_ni_sensibles"): ("guardrails.json", ("metricas", "entrada", "metas", "salidas_sin_gps_ni_sensibles"), "medido", "cumple"),
        ("cache_semantica", "incorrectas_desde_cache_max"): ("cache.json", ("metricas", "metas", "incorrectas_desde_cache_max"),
                                                            "medido_fichas_fpr_en_tau_elegido", "cumple_fichas_en_tau_elegido"),
    })
    for grupo, valores in metas.items():
        if not isinstance(valores, dict):
            continue
        for nombre, meta in valores.items():
            clave = (grupo, nombre)
            if clave == ("busqueda", "r10_texto_imagen"):
                lineas.append(f"| {grupo}.{nombre} | {celda(meta)} | ver «R3 · embeddings» en la sección 2 (R@10 de cada "
                              "arquitectura sobre la misma sub-galería) | — | `evaluacion/resultados/r3_embeddings.json` |")
                continue
            if clave not in medidas:
                lineas.append(f"| {grupo}.{nombre} | {celda(meta)} | pendiente: ningún módulo de esta evaluación la mide "
                              f"directamente | — | — |")
                continue
            archivo, ruta, campo_medido, campo_cumple = medidas[clave]
            try:
                d = obtener(datos.get(archivo), ruta)
                medido = d.get(campo_medido, d.get("estado", "pendiente")) if isinstance(d, dict) else d
                cumple = d.get(campo_cumple) if isinstance(d, dict) else None
                lineas.append(f"| {grupo}.{nombre} | {celda(meta)} | {celda(medido)} | "
                              f"{'sí' if cumple is True else 'no' if cumple is False else 'pendiente'} | {fuente(archivo, ruta)} |")
            except Falta:
                lineas.append(f"| {grupo}.{nombre} | {celda(meta)} | pendiente: falta `{archivo}` o la clave | — | — |")
    return lineas + [""]


def seccion_todas(datos: dict) -> list[str]:
    lineas = ["## 4. Todas las cifras por archivo", "",
              f"Hojas de cada JSON (bajo `metricas` si existe). Se omiten los textos de más de {MAX_TEXTO} caracteres y, "
              f"en archivos muy grandes, las filas después de la {MAX_FILAS_POR_ARCHIVO}.", ""]
    for archivo, d in datos.items():
        lineas += [f"### `evaluacion/resultados/{archivo}`", ""]
        if isinstance(d, dict):
            meta = [f"{k}: {celda(d[k])}" for k in ("fecha", "rapido", "fraccion", "version_configuracion") if k in d]
            hw = d.get("hardware") or {}
            if hw:
                meta.append("hardware: " + celda(", ".join(f"{k}={v}" for k, v in hw.items())))
            if meta:
                lineas += ["- " + "\n- ".join(meta), ""]
        base, prefijo = (d["metricas"], ("metricas",)) if isinstance(d, dict) and "metricas" in d else (d, ())
        hojas = list(aplanar(base, prefijo))
        largas = [h for h in hojas if isinstance(h[1], str) and len(h[1]) > MAX_TEXTO]
        hojas = [h for h in hojas if not (isinstance(h[1], str) and len(h[1]) > MAX_TEXTO)]
        if not hojas:
            lineas += ["(sin cifras)", ""]
            continue
        lineas += ["| Clave | Valor |", "|---|---|"]
        for ruta, valor in hojas[:MAX_FILAS_POR_ARCHIVO]:
            lineas.append(f"| {celda(ruta_texto(ruta))} | {celda(valor)} |")
        notas = []
        if len(hojas) > MAX_FILAS_POR_ARCHIVO:
            notas.append(f"{len(hojas) - MAX_FILAS_POR_ARCHIVO} filas más en el archivo")
        if largas:
            notas.append(f"{len(largas)} textos largos omitidos")
        if notas:
            lineas += ["", f"_({'; '.join(notas)}; ver el JSON)_"]
        lineas.append("")
    return lineas


def ejecutar(c=None) -> dict:
    datos = leer_resultados()
    lineas = ["# Resumen de resultados de la evaluación", "",
              f"> Generado automáticamente por `python -m evaluacion.resumen` el {ahora()}. Cada cifra se copia tal cual "
              "de su archivo en `evaluacion/resultados/`; la columna «Fuente» indica el archivo y la clave dentro del "
              "JSON. «pendiente» significa que el archivo o la clave todavía no existe. Las gráficas están en "
              "`evaluacion/graficas/` y el detalle caso por caso en `evaluacion/resultados/<modulo>_detalle.csv`.", ""]
    lineas += seccion_estado(datos) + seccion_destacados(datos) + seccion_metas(datos) + seccion_todas(datos)
    ruta = RESULTADOS / "RESUMEN.md"
    RESULTADOS.mkdir(parents=True, exist_ok=True)
    ruta.write_text("\n".join(lineas).rstrip() + "\n", encoding="utf-8")
    registro(f"resumen → {ruta.name} ({len(datos)} archivos JSON)")
    return {"archivos": len(datos), "ruta": str(ruta)}


if __name__ == "__main__":
    ejecutar(None)
