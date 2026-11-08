"""Enrutadores (ADR-03): el de fichas (ruta rápida o completa) y el de búsquedas (simple o compleja).

Fichas, sobre `eval_fichas` (60 fotos):
- Se reutilizan dos configuraciones del experimento de modelos: `qwen_rapida` (ruta rápida) y `lfm3_composicion`
  (ruta completa: P1 de Qwen + P3 de LFM3; su latencia incluye P1).
- Ruta correcta de cada foto: la rápida si su calidad (promedio del juez P7) está a 0.5 puntos o menos de la de la
  completa; si no, la completa.
- Señales por foto: las que calcula el propio servicio y devuelve en `meta.senales_enrutador` (consenso, acuerdo,
  texto visible y margen). Regla del servicio: completa si hay texto visible, acuerdo < τ_acuerdo o
  consenso < τ_consenso; si no, rápida.
- Se busca el par (τ_consenso, τ_acuerdo) que maximiza la exactitud con la restricción de que la latencia media no
  supere la mitad de la de «siempre completa». Candidatos: los puntos medios entre valores observados (más uno por
  debajo del mínimo y otro por encima del máximo). Desempates: mayor calidad media, menor latencia media y τ menores.
  Si ningún par cumple la restricción, se informa y se elige el de mayor exactitud sin ella.
- Exactitud FUERA DE MUESTRA: validación cruzada de 5 pliegues (semilla 2026); en cada pliegue los umbrales se
  eligen solo con los pliegues de entrenamiento. Se compara contra «siempre rápida», «siempre completa», los
  umbrales vigentes de la configuración y el oráculo. Los umbrales elegidos quedan en el JSON de resultados; este
  módulo no edita parametros.yaml.

Búsquedas, 40 consultas: 20 simples (la 1ª descripción en español de 20 fotos de la galería elegidas con semilla
2026, sin repetir los orígenes de las complejas) y las 20 de `consultas_complejas`.
- Antes de medir se sube la galería completa por la API: los relevantes son fotos de la galería, que no están en el
  archivo.
- Cada consulta corre sin forzar la ruta (la decisión del enrutador da la exactitud) y forzada por la ruta simple
  (sin P4) y por la compleja (con P4). Si la decisión automática coincide con una ruta forzada, la corrida
  automática ES esa corrida y no se repite. Siempre con `sin_cache=true`, k = 12 (el valor por defecto) y
  `filtros={"particion": "subida"}` en todas las corridas (el filtro no cambia la decisión del enrutador, que solo
  depende del texto).
- R@10 = fracción de los relevantes entre los 10 primeros resultados; acierto@10 y MRR como cifras extra. Los
  relevantes están marcados dentro de la galería, y la búsqueda queda limitada a las fotos subidas (la galería más
  cualquier otra foto subida por la evaluación), así que el archivo catalogado no compite por los primeros puestos.
  Una consulta bloqueada o con error cuenta con R@10 = 0.

    python -m evaluacion.enrutador [--rapido]
"""
from __future__ import annotations

import argparse
import os
import random
from collections import Counter

import numpy as np

from evaluacion.calidad import CONFIGURACIONES, indice_xm, intervalo_bootstrap
from evaluacion.comun import (SEMILLA, ClienteEval, Incremental, guardar_grafica, guardar_resultado, leer_conjunto,
                              particiones, percentiles, rapido, registro, tamano)
from evaluacion.r3_modelos import (COLORES, TINTA, TINTA_SECUNDARIA, Avance, barras, caso, escribir_csv,
                                   eval_fichas_muestra, exigir_servicios, generar_fichas, leyenda_comun, media,
                                   nueva_figura, subir)

RUTA_RAPIDA, RUTA_COMPLETA = "qwen_rapida", "lfm3_composicion"
MARGEN_CALIDAD = 0.5        # la rápida es «correcta» si su calidad está a ≤ 0.5 puntos de la completa
FRACCION_LATENCIA = 0.5     # restricción: latencia media ≤ la mitad de «siempre completa»
PLIEGUES = 5
K_BUSQUEDA = 12             # k por defecto de POST /busquedas
K_RECALL = 10
FILTRO_SUBIDAS = {"particion": "subida"}
ALCANCE_R10 = ("Los relevantes están marcados dentro de la galería y la búsqueda queda limitada a las fotos subidas "
               "(filtros = {\"particion\": \"subida\"}: la galería más cualquier otra foto subida por la evaluación), "
               "así que el archivo catalogado no compite. Una foto subida que se valida por retroalimentación cambia "
               "de partición y sale del filtro.")


# ───────────────────────────── fichas ─────────────────────────────
def filas_fichas(c: ClienteEval) -> list[dict]:
    g = generar_fichas(c, eval_fichas_muestra(), (RUTA_RAPIDA, RUTA_COMPLETA))
    filas = []
    avance = Avance("calidad de las dos rutas (juez P7)", len(g["ids"]))
    for x in g["ids"]:
        r = caso(c, RUTA_RAPIDA, x, g["registros"][RUTA_RAPIDA][x], g["p1"].get(x))
        k = caso(c, RUTA_COMPLETA, x, g["registros"][RUTA_COMPLETA][x], g["p1"].get(x))
        s = r.get("senales_enrutador") or k.get("senales_enrutador") or {}
        q_r, q_c = r.get("juez_promedio"), k.get("juez_promedio")
        correcta = None if q_r is None or q_c is None else ("rapida" if q_r >= q_c - MARGEN_CALIDAD else "completa")
        filas.append({
            "xm_id": x, "consenso": s.get("consenso"), "acuerdo": s.get("acuerdo"),
            "texto_visible": bool(s.get("texto_visible")), "margen": s.get("margen"),
            "senales_de": RUTA_RAPIDA if r.get("senales_enrutador") else (RUTA_COMPLETA if s else None),
            "calidad_rapida": q_r, "calidad_completa": q_c,
            "granite_rapida": r.get("granite_max"), "granite_completa": k.get("granite_max"),
            "latencia_rapida_s": r.get("latencia_ruta_s"), "latencia_completa_s": k.get("latencia_ruta_s"),
            "ruta_final_de_la_rapida": r.get("ruta_final"), "ruta_correcta": correcta})
        avance.paso()
    return filas


def utilizables(filas: list[dict]) -> list[dict]:
    claves = ("consenso", "acuerdo", "latencia_rapida_s", "latencia_completa_s")
    return [f for f in filas if f["ruta_correcta"] and all(f[k] is not None for k in claves)]


def predecir(f: dict, tau_consenso, tau_acuerdo) -> str:
    """La regla del servicio. Sin τ_consenso calibrado, el servicio elige la ruta conservadora (completa)."""
    if tau_consenso is None:
        return "completa"
    return "completa" if (f["texto_visible"] or f["acuerdo"] < tau_acuerdo or f["consenso"] < tau_consenso) else "rapida"


def evaluar_estrategia(filas: list[dict], rutas: list[str]) -> dict:
    def elegir(f, r, rapida, completa):
        return f[rapida] if r == "rapida" else f[completa]

    latencias = [elegir(f, r, "latencia_rapida_s", "latencia_completa_s") for f, r in zip(filas, rutas)]
    return {
        "n": len(filas),
        "exactitud": media([float(r == f["ruta_correcta"]) for f, r in zip(filas, rutas)]),
        "calidad_media": media([elegir(f, r, "calidad_rapida", "calidad_completa") for f, r in zip(filas, rutas)]),
        "granite_media": media([elegir(f, r, "granite_rapida", "granite_completa") for f, r in zip(filas, rutas)]),
        "latencia_media_s": media(latencias),
        "latencia_p50_s": round(float(np.percentile(latencias, 50)), 3) if latencias else None,
        "fraccion_rapida": media([float(r == "rapida") for r in rutas]),
    }


def candidatos(valores) -> list[float]:
    """Puntos medios entre valores observados, más uno que no deja ninguna foto por debajo (0 si las señales son no
    negativas, para no escribir un τ negativo) y otro que las deja todas."""
    u = np.unique(np.asarray(valores, dtype=float))
    if not u.size:
        return []
    inferior = max(0.0, float(u[0]) - 0.001) if u[0] >= 0 else float(u[0]) - 0.001
    return ([round(inferior, 5)] + [round(float(m), 5) for m in (u[:-1] + u[1:]) / 2]
            + [round(float(u[-1]) + 0.001, 5)])


def buscar_umbrales(filas: list[dict]) -> dict:
    """Barrido de (τ_consenso, τ_acuerdo): máxima exactitud con latencia media ≤ la mitad de «siempre completa»."""
    a = {k: np.array([f[k] for f in filas], dtype=float) for k in
         ("consenso", "acuerdo", "calidad_rapida", "calidad_completa", "latencia_rapida_s", "latencia_completa_s")}
    visible = np.array([f["texto_visible"] for f in filas], dtype=bool)
    rapida_correcta = np.array([f["ruta_correcta"] == "rapida" for f in filas], dtype=bool)
    limite = FRACCION_LATENCIA * float(np.mean(a["latencia_completa_s"]))
    mejor, evaluados, factibles = None, 0, 0
    for tc in candidatos(a["consenso"]):
        for ta in candidatos(a["acuerdo"]):
            rapida = ~visible & (a["acuerdo"] >= ta) & (a["consenso"] >= tc)
            exactitud = float(np.mean(rapida == rapida_correcta))
            calidad = float(np.mean(np.where(rapida, a["calidad_rapida"], a["calidad_completa"])))
            latencia = float(np.mean(np.where(rapida, a["latencia_rapida_s"], a["latencia_completa_s"])))
            factible = latencia <= limite
            evaluados += 1
            factibles += int(factible)
            clave = (not factible, -exactitud, -calidad, latencia, tc, ta)
            if mejor is None or clave < mejor[0]:
                mejor = (clave, tc, ta)
    _, tc, ta = mejor
    return {"tau_consenso": tc, "tau_acuerdo": ta, "factible": factibles > 0, "limite_latencia_s": round(limite, 3),
            "pares_evaluados": evaluados, "pares_factibles": factibles,
            **evaluar_estrategia(filas, [predecir(f, tc, ta) for f in filas])}


def validacion_cruzada(filas: list[dict]) -> dict:
    k = min(PLIEGUES, len(filas))
    orden = np.random.default_rng(SEMILLA).permutation(len(filas))
    rutas: list[str | None] = [None] * len(filas)
    por_pliegue = []
    for i, prueba in enumerate(np.array_split(orden, k)):
        en_prueba = {int(j) for j in prueba}
        u = buscar_umbrales([filas[j] for j in range(len(filas)) if j not in en_prueba])
        for j in en_prueba:
            rutas[j] = predecir(filas[j], u["tau_consenso"], u["tau_acuerdo"])
        por_pliegue.append({"pliegue": i + 1, "n_prueba": len(en_prueba), "tau_consenso": u["tau_consenso"],
                            "tau_acuerdo": u["tau_acuerdo"], "restriccion_cumplida_en_entrenamiento": u["factible"],
                            "exactitud_entrenamiento": u["exactitud"],
                            "exactitud_prueba": media([float(rutas[j] == filas[j]["ruta_correcta"]) for j in en_prueba])})
    return {"pliegues": k, "semilla": SEMILLA, **evaluar_estrategia(filas, rutas), "por_pliegue": por_pliegue,
            "rutas": rutas}


def evaluar_fichas(c: ClienteEval) -> tuple[dict, list[dict]]:
    filas = filas_fichas(c)
    u = utilizables(filas)
    ids_u = {f["xm_id"] for f in u}
    tc0 = c.config.parametro("enrutador_fichas.tau_consenso")
    ta0 = c.config.parametro("enrutador_fichas.tau_acuerdo", 0.25)
    salida = {
        "fotos": len(filas), "utilizables": len(u), "excluidas": [f["xm_id"] for f in filas if f["xm_id"] not in ids_u],
        "motivo_exclusion": "falta la calidad (juez) de alguna ruta, las señales o la latencia",
        "regla_ruta_correcta": f"rápida si calidad_rapida ≥ calidad_completa − {MARGEN_CALIDAD}; si no, completa",
        "ruta_correcta": dict(Counter(f["ruta_correcta"] for f in u)),
        "senales_tomadas_de": dict(Counter(str(f["senales_de"]) for f in u)),
        "rapida_que_escalo_a_completa": sum(1 for f in u if f["ruta_final_de_la_rapida"] == "completa"),
        "con_texto_visible": sum(1 for f in u if f["texto_visible"]),
    }
    if len(u) < 2:
        return {**salida, "pendiente": "no hay fotos suficientes con calidad, señales y latencia de ambas rutas"}, filas
    elegido = buscar_umbrales(u)
    cv = validacion_cruzada(u)
    for f, r in zip(u, cv.pop("rutas")):
        f["ruta_validacion_cruzada"] = r
    for f in u:
        f["ruta_umbrales_elegidos"] = predecir(f, elegido["tau_consenso"], elegido["tau_acuerdo"])
        f["ruta_umbrales_vigentes"] = predecir(f, tc0, ta0)
    n = len(u)
    estrategias = {
        "siempre_rapida": evaluar_estrategia(u, ["rapida"] * n),
        "siempre_completa": evaluar_estrategia(u, ["completa"] * n),
        "umbrales_vigentes": {**evaluar_estrategia(u, [f["ruta_umbrales_vigentes"] for f in u]),
                              "tau_consenso": tc0, "tau_acuerdo": ta0},
        "umbrales_elegidos_en_muestra": evaluar_estrategia(u, [f["ruta_umbrales_elegidos"] for f in u]),
        "validacion_cruzada_fuera_de_muestra": evaluar_estrategia(u, [f["ruta_validacion_cruzada"] for f in u]),
        "oraculo": evaluar_estrategia(u, [f["ruta_correcta"] for f in u]),
    }
    salida.update({
        "umbrales_elegidos": {"enrutador_fichas.tau_consenso": elegido["tau_consenso"],
                              "enrutador_fichas.tau_acuerdo": elegido["tau_acuerdo"],
                              "restriccion_latencia_cumplida": elegido["factible"],
                              "limite_latencia_s": elegido["limite_latencia_s"],
                              "nota": "los copia la sesión principal a config/parametros.yaml, con la evidencia en ADR-03"},
        "barrido": {k: elegido[k] for k in ("pares_evaluados", "pares_factibles", "factible", "limite_latencia_s")},
        "exactitud_en_muestra": elegido["exactitud"], "exactitud_fuera_de_muestra": cv.get("exactitud"),
        "validacion_cruzada": cv, "estrategias": estrategias,
        "umbrales_vigentes_nota": None if tc0 is not None else
        "τ_consenso sin calibrar en la configuración: el servicio elige siempre la ruta completa (conservadora)",
    })
    if not elegido["factible"]:
        salida["advertencia"] = ("Ningún par de umbrales cumple la restricción de latencia (ni siquiera «siempre rápida» "
                                 "baja de la mitad de «siempre completa»): se eligió el par de mayor exactitud sin ella.")
    return salida, filas


def graficas_fichas(fichas: dict, filas: list[dict]) -> list[str]:
    u = [f for f in filas if f.get("ruta_umbrales_elegidos")]
    if not u:
        return []
    elegidos = fichas["umbrales_elegidos"]
    tc, ta = elegidos["enrutador_fichas.tau_consenso"], elegidos["enrutador_fichas.tau_acuerdo"]
    fig, (ax,) = nueva_figura(7.0, 4.8)
    for i, (ruta, marca) in enumerate((("rapida", "o"), ("completa", "s"))):
        pts = [f for f in u if f["ruta_correcta"] == ruta]
        ax.scatter([f["consenso"] for f in pts], [f["acuerdo"] for f in pts], s=40, marker=marca, color=COLORES[i],
                   edgecolor="white", linewidth=1.2, zorder=3,
                   label=f"ruta correcta: {'rápida' if ruta == 'rapida' else 'completa'} (n = {len(pts)})")
    visibles = [f for f in u if f["texto_visible"]]
    if visibles:
        ax.scatter([f["consenso"] for f in visibles], [f["acuerdo"] for f in visibles], s=110, facecolors="none",
                   edgecolors=TINTA, linewidth=1, zorder=4, label="con texto visible (siempre completa)")
    ax.axvline(tc, color=TINTA_SECUNDARIA, linestyle="--", linewidth=1, zorder=2)
    ax.axhline(ta, color=TINTA_SECUNDARIA, linestyle="--", linewidth=1, zorder=2)
    ax.annotate(f"τ_consenso = {tc}", (tc, 1.0), xycoords=("data", "axes fraction"), xytext=(4, -12),
                textcoords="offset points", fontsize=8, color=TINTA_SECUNDARIA)
    ax.annotate(f"τ_acuerdo = {ta}", (0.0, ta), xycoords=("axes fraction", "data"), xytext=(4, 4),
                textcoords="offset points", fontsize=8, color=TINTA_SECUNDARIA)
    ax.set_xlabel("Consenso (media del coseno imagen-imagen de los 5 vecinos)")
    ax.set_ylabel("Acuerdo (Jaccard medio entre palabras clave)")
    ax.set_title("Señales del enrutador de fichas y umbrales elegidos\n(arriba a la derecha de ambas líneas: ruta rápida)")
    ax.legend(frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=2)
    guardar_grafica("enrutador_fichas_senales", fig)

    nombres = {"siempre_rapida": "siempre rápida", "siempre_completa": "siempre completa",
               "umbrales_vigentes": "umbrales vigentes", "umbrales_elegidos_en_muestra": "umbrales elegidos (en muestra)",
               "validacion_cruzada_fuera_de_muestra": "umbrales elegidos (fuera de muestra, 5 pliegues)",
               "oraculo": "oráculo (siempre la ruta correcta)"}
    puntos: dict[tuple, list[str]] = {}     # estrategias con el mismo resultado comparten punto y número
    for clave, e in fichas["estrategias"].items():
        if e.get("latencia_media_s") is not None and e.get("calidad_media") is not None:
            puntos.setdefault((round(e["latencia_media_s"], 2), round(e["calidad_media"], 3)), []).append(clave)
    fig, (ax,) = nueva_figura(6.6, 4.6)
    lineas = []
    for i, ((lat, cal), claves) in enumerate(sorted(puntos.items()), start=1):
        ax.scatter(lat, cal, s=46, color=COLORES[0], edgecolor="white", zorder=3)
        ax.annotate(str(i), (lat, cal), xytext=(6, 4) if i % 2 else (6, -13), textcoords="offset points", fontsize=9,
                    color=TINTA, fontweight="bold", zorder=4)
        e = fichas["estrategias"][claves[0]]
        lineas.append(f"{i}. {' = '.join(nombres.get(k, k) for k in claves)}\n    exactitud {e['exactitud']:.2f} · "
                      f"calidad {cal:.2f} · {lat:.1f} s")
    ax.text(1.03, 1.0, "\n".join(lineas), transform=ax.transAxes, va="top", ha="left", fontsize=8, color=TINTA,
            linespacing=1.4)
    limite = fichas["umbrales_elegidos"]["limite_latencia_s"]
    ax.axvline(limite, color=TINTA_SECUNDARIA, linestyle=":", linewidth=1)
    ax.annotate("límite: ½ de «siempre completa»", (limite, 0.02), xycoords=("data", "axes fraction"), xytext=(4, 0),
                textcoords="offset points", fontsize=7.5, color=TINTA_SECUNDARIA)
    ax.set_xlabel("Latencia media por foto (s)")
    ax.set_ylabel("Calidad media (juez P7, 0–5)")
    ax.set_title(f"Estrategias de enrutamiento de fichas (n = {len(u)} fotos)")
    guardar_grafica("enrutador_fichas_estrategias", fig)
    return ["evaluacion/graficas/enrutador_fichas_senales.png", "evaluacion/graficas/enrutador_fichas_estrategias.png"]


# ───────────────────────────── búsquedas ─────────────────────────────
def consultas_busqueda() -> list[dict]:
    galeria = sorted(particiones()["galeria_busqueda"])
    complejas = leer_conjunto("consultas_complejas")["items"]
    origenes = {it.get("origen") for it in complejas}
    indice = indice_xm()
    fotos = sorted(random.Random(SEMILLA).sample([x for x in galeria if x not in origenes], 20))
    simples = [{"id": f"cs-{i + 1:02d}", "tipo": "simple", "texto": indice[x]["es"][0].strip()[:300],
                "relevantes": [x], "origen": x, "restriccion": None} for i, x in enumerate(fotos)]
    compuestas = [{"id": it["id"], "tipo": "compleja", "texto": str(it["consulta"]).strip()[:300],
                   "relevantes": list(it.get("relevantes") or []), "origen": it.get("origen"),
                   "restriccion": it.get("restriccion")} for it in complejas]
    return simples[:tamano(len(simples))] + compuestas[:tamano(len(compuestas))]


def buscar(c: ClienteEval, inc: Incremental, config: str, q: dict, **opciones) -> dict:
    clave = f"{config}|{q['id']}"
    previo = inc.obtener(clave)
    if previo:
        return previo
    estado, cuerpo, seg = c.buscar(q["texto"], k=K_BUSQUEDA, sin_cache=True, filtros=FILTRO_SUBIDAS, **opciones)
    if estado == 503:       # infraestructura: se verifica (si sigue caída, se aborta) y se repite una vez
        exigir_servicios(c)
        estado, cuerpo, seg = c.buscar(q["texto"], k=K_BUSQUEDA, sin_cache=True, filtros=FILTRO_SUBIDAS, **opciones)
    meta = cuerpo.get("meta") or {}
    interpretada = cuerpo.get("consulta_interpretada") or {}
    reg = {"config": config, "consulta_id": q["id"], "estado_http": estado, "segundos": round(seg, 3),
           "error": (cuerpo.get("error") or {}).get("codigo"), "ruta": meta.get("ruta"), "modelo": meta.get("modelo"),
           "tiempo_ms": meta.get("tiempo_ms"), "tiempos_por_capa_ms": meta.get("tiempos_por_capa_ms"),
           "iteraciones_agente": meta.get("iteraciones_agente"), "traza_id": meta.get("traza_id"),
           "resultados": [r.get("documento_id") for r in cuerpo.get("resultados") or []],
           "consulta_interpretada": interpretada}
    return reg if estado == 503 else inc.guardar(clave, reg)


def ranking(reg: dict, relevantes: list[str], inverso: dict[str, str]) -> dict:
    rel = set(relevantes)
    if not rel:
        return {"recall@10": None, "acierto@10": None, "rr": None}
    if reg.get("estado_http") != 200:
        return {"recall@10": 0.0, "acierto@10": False, "rr": 0.0}
    lista = [inverso.get(d, d) for d in reg.get("resultados") or []]
    hallados = {x for x in lista[:K_RECALL] if x in rel}
    rango = next((i + 1 for i, x in enumerate(lista) if x in rel), None)
    return {"recall@10": round(len(hallados) / len(rel), 4), "acierto@10": bool(hallados),
            "rr": round(1 / rango, 4) if rango else 0.0}


def evaluar_busquedas(c: ClienteEval) -> tuple[dict, list[dict]]:
    consultas = consultas_busqueda()
    galeria = sorted(particiones()["galeria_busqueda"])
    relevantes = sorted({x for q in consultas for x in q["relevantes"]})
    a_subir = galeria if not rapido() else sorted(set(relevantes) | set(galeria[:tamano(len(galeria))]))
    docs, fallidas = subir(c, a_subir, "fotos de la galería")
    inverso = {d: x for x, d in docs.items()}
    inc = Incremental("enrutador_busquedas_subidas")     # nombre propio: nunca se mezcla con corridas sin filtro
    filas = []
    avance = Avance("búsquedas (automática, simple y compleja)", len(consultas))
    for q in consultas:
        auto = buscar(c, inc, "auto", q)
        por_ruta = {ruta: auto if (auto.get("estado_http") == 200 and auto.get("ruta") == ruta)
                    else buscar(c, inc, f"forzada_{ruta}", q, forzar_ruta=ruta) for ruta in ("simple", "compleja")}
        decision = auto.get("ruta") if auto.get("estado_http") == 200 else None
        interpretada = por_ruta["compleja"].get("consulta_interpretada") or {}
        fila = {"consulta_id": q["id"], "tipo": q["tipo"], "texto": q["texto"], "restriccion": q.get("restriccion"),
                "relevantes": q["relevantes"], "relevantes_no_subidos": [x for x in q["relevantes"] if x not in docs],
                "decision_automatica": decision, "enrutador_acierta": None if decision is None else decision == q["tipo"],
                "simple_reutiliza_auto": por_ruta["simple"] is auto, "compleja_reutiliza_auto": por_ruta["compleja"] is auto,
                "modelo_ruta_compleja": por_ruta["compleja"].get("modelo"),
                "p4_excluir": interpretada.get("excluir") or [],
                "p4_contiene_personas": (interpretada.get("filtros") or {}).get("contiene_personas")}
        for etiqueta, reg in (("auto", auto), ("simple", por_ruta["simple"]), ("compleja", por_ruta["compleja"])):
            fila.update({f"{etiqueta}_{k}": v for k, v in ranking(reg, q["relevantes"], inverso).items()})
            fila[f"{etiqueta}_latencia_s"] = round(reg["tiempo_ms"] / 1000, 3) if reg.get("tiempo_ms") is not None else None
            fila[f"{etiqueta}_estado_http"] = reg.get("estado_http")
        filas.append(fila)
        avance.paso()

    def latencia(clave: str, condicion=lambda f: True) -> dict:
        return percentiles([f[clave] for f in filas if f.get(clave) is not None and condicion(f)])

    def recall(tipo: str, ruta: str) -> dict:
        sel = [f for f in filas if f["tipo"] == tipo and f.get(f"{ruta}_recall@10") is not None]
        r10 = [f[f"{ruta}_recall@10"] for f in sel]
        return {"n": len(sel), "recall@10": media(r10), "ic95": intervalo_bootstrap(r10),
                "acierto@10": media([float(f[f"{ruta}_acierto@10"]) for f in sel]), "mrr": media([f[f"{ruta}_rr"] for f in sel])}

    con_decision = [f for f in filas if f["decision_automatica"]]
    tipos = [t for t in ("simple", "compleja") if any(f["tipo"] == t for f in filas)]
    pares = [f for f in filas if f["tipo"] == "compleja" and f.get("compleja_recall@10") is not None
             and f.get("simple_recall@10") is not None]
    dif = [f["compleja_recall@10"] - f["simple_recall@10"] for f in pares]
    metricas = {
        "consultas": dict(Counter(f["tipo"] for f in filas)),
        "exactitud_enrutador": {
            "exactitud": media([float(f["enrutador_acierta"]) for f in con_decision]), "n": len(con_decision),
            "por_tipo": {t: media([float(f["enrutador_acierta"]) for f in con_decision if f["tipo"] == t]) for t in tipos},
            "matriz_confusion": {f"etiqueta_{t}": dict(Counter(f["decision_automatica"] for f in con_decision
                                                               if f["tipo"] == t)) for t in tipos},
            "consultas_con_error": [f["consulta_id"] for f in filas if not f["decision_automatica"]]},
        "latencia_por_ruta_s": {"simple (sin P4)": latencia("simple_latencia_s"),
                                "compleja (con P4)": latencia("compleja_latencia_s")},
        "latencia_por_tipo_y_ruta_s": {t: {r: latencia(f"{r}_latencia_s", lambda f, t=t: f["tipo"] == t)
                                           for r in ("simple", "compleja")} for t in tipos},
        "latencia_con_la_decision_del_enrutador_s": {
            "todas": latencia("auto_latencia_s"),
            **{f"decidio_{r}": latencia("auto_latencia_s", lambda f, r=r: f["decision_automatica"] == r)
               for r in ("simple", "compleja")}},
        "recall@10": {t: {r: recall(t, r) for r in ("simple", "compleja", "auto")} for t in tipos},
        "complejas_con_p4_menos_sin_p4": {"campo": "recall@10", "n": len(dif), "media": media(dif),
                                          "ic95": intervalo_bootstrap(dif), "mejora": sum(1 for d in dif if d > 0),
                                          "empeora": sum(1 for d in dif if d < 0), "igual": sum(1 for d in dif if d == 0)},
        "p4": {"ruta_compleja_sin_modelo": sum(1 for f in filas if not f["modelo_ruta_compleja"]),
               "con_terminos_excluidos": sum(1 for f in filas if f["p4_excluir"]),
               "con_filtro_de_personas": sum(1 for f in filas if f["p4_contiene_personas"] is not None),
               "nota": "ruta_compleja_sin_modelo = P4 falló y el servicio buscó con el texto original"},
        "galeria": {"subidas": len(docs), "no_subidas": fallidas,
                    "relevantes_no_subidos": sorted({x for f in filas for x in f["relevantes_no_subidos"]})},
        "filtros": FILTRO_SUBIDAS, "alcance_r10": ALCANCE_R10,
    }
    return metricas, filas


def graficas_busquedas(m: dict) -> list[str]:
    tipos = [t for t in ("compleja", "simple") if t in m["recall@10"]]
    if not tipos:
        return []
    fig, (a1, a2) = nueva_figura(11.5, 4.2, 2)
    series = {"Sin P4 (ruta simple)": "simple", "Con P4 (ruta compleja)": "compleja"}
    barras(a1, [f"Consultas {'complejas' if t == 'compleja' else 'simples'}\nn = {m['recall@10'][t]['simple']['n']}" for t in tipos],
           {nombre: [m["recall@10"][t][r]["recall@10"] for t in tipos] for nombre, r in series.items()},
           {nombre: [m["recall@10"][t][r]["ic95"] for t in tipos] for nombre, r in series.items()}, leyenda=False)
    a1.set_ylim(0, 1.12)
    a1.set_ylabel("R@10 (búsqueda entre las fotos subidas)")
    a1.set_title("Recuperación con y sin descomposición P4")
    lat = m["latencia_por_ruta_s"]
    barras(a2, ["Mediana (p50)", "Percentil 95"],       # mismos colores por ruta que en el panel izquierdo
           {"Sin P4 (ruta simple)": [lat["simple (sin P4)"].get("p50_s"), lat["simple (sin P4)"].get("p95_s")],
            "Con P4 (ruta compleja)": [lat["compleja (con P4)"].get("p50_s"), lat["compleja (con P4)"].get("p95_s")]},
           formato="{:.1f}", leyenda=False)
    a2.set_ylabel("Latencia por consulta (s)")
    a2.set_title("Latencia de cada ruta (todas las consultas)")
    fig.suptitle("Enrutador de búsquedas: calidad y costo de cada ruta (bigotes: IC95)")
    leyenda_comun(fig, a1)
    fig.tight_layout(rect=(0, 0.07, 1, 0.93))
    guardar_grafica("enrutador_busquedas", fig)
    return ["evaluacion/graficas/enrutador_busquedas.png"]


# ───────────────────────────── ejecución ─────────────────────────────
def ejecutar(c: ClienteEval) -> dict:
    exigir_servicios(c)
    registro("Enrutador de fichas: ruta rápida contra completa sobre eval_fichas")
    fichas, filas = evaluar_fichas(c)
    registro("Enrutador de búsquedas: 20 simples + 20 complejas (sube la galería si falta)")
    busquedas, filas_busqueda = evaluar_busquedas(c)
    metricas = {"fichas": fichas, "busquedas": busquedas,
                "graficas": graficas_fichas(fichas, filas) + graficas_busquedas(busquedas),
                "detalle_busquedas": escribir_csv("enrutador_busquedas_detalle", filas_busqueda)}
    configuracion = {
        "fichas": {"ruta_rapida": {"configuracion": RUTA_RAPIDA, **CONFIGURACIONES[RUTA_RAPIDA]},
                   "ruta_completa": {"configuracion": RUTA_COMPLETA, **CONFIGURACIONES[RUTA_COMPLETA]},
                   "margen_calidad": MARGEN_CALIDAD, "fraccion_latencia": FRACCION_LATENCIA, "pliegues": PLIEGUES,
                   "semilla": SEMILLA, "enrutador_fichas_vigente": c.config.parametro("enrutador_fichas")},
        "busquedas": {"k": K_BUSQUEDA, "k_recall": K_RECALL, "sin_cache": True, "filtros": FILTRO_SUBIDAS,
                      "enrutador_busquedas_vigente": c.config.parametro("enrutador_busquedas")},
    }
    guardar_resultado("enrutador", metricas, filas, configuracion, c)
    if "umbrales_elegidos" in fichas:
        registro(f"umbrales elegidos: {fichas['umbrales_elegidos']}")
    return metricas


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rapido", action="store_true", help="la cuarta parte de los casos (prueba de humo)")
    if ap.parse_args().rapido:
        os.environ["FOTOTECA_EVAL_RAPIDO"] = "1"
    ejecutar(ClienteEval())


if __name__ == "__main__":
    main()
