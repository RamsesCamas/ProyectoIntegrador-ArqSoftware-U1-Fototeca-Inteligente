"""Ciclo de agente (ADR-07): ¿reformular la recuperación de ejemplos ayuda cuando la recuperación inicial es pobre?

Conjunto: las 20 fotos de `regiones_excluidas` que están en `eval_fichas` más las 30 de `agente_extra` (de la misma
partición), donde se espera una recuperación inicial pobre. Dos configuraciones por la API (reanudables): con el
ciclo (`agente_con_ciclo`, el flujo de producción) y sin él (`agente_sin_ciclo`, `max_iter = 0`).

Métricas:
- % de casos que activan el ciclo: `meta.iteraciones_agente > 0` en la corrida con ciclo.
- % que mejora después de reformular: el acierto@5 de los vecinos pasa de 0 a 1 (criterio de
  `rag_fichas.CriterioVecinos`: algún vecino con similitud granite ≥ p75 de su distribución contra todas las fichas
  validadas) o la similitud imagen-imagen del top-1 sube más que δ (`agente.delta_margen` de la configuración). Los
  vecinos y el top-1 antes de reformular salen del primer evento C5 `recuperar_ejemplos` de la traza (o de la
  corrida sin ciclo); los de después, del último evento C2 `reformular` y de `meta.recuperacion`. Se reporta sobre
  los casos que activan el ciclo (la definición) y sobre todos.
- Iteraciones promedio, latencia añadida (con ciclo − sin ciclo, por foto; puede ser negativa si cambia la ruta) y
  calidad de la ficha con y sin ciclo (juez P7, granite y chrF; diferencias pareadas con IC95).

    python -m evaluacion.agente [--rapido]
"""
from __future__ import annotations

import argparse
import os
from collections import Counter

from evaluacion.calidad import CONFIGURACIONES, resumen_numerico
from evaluacion.comun import ClienteEval, guardar_grafica, guardar_resultado, particiones, percentiles, registro, tamano
from evaluacion.r3_modelos import (Avance, agregar, barras, caso, diferencia_pareada, escribir_csv, eventos_traza,
                                   exigir_servicios, fila_csv, generar, leyenda_comun, media, nueva_figura, subir,
                                   tasa)
from evaluacion.rag_fichas import K_VECINOS, CriterioVecinos

CON, SIN = "agente_con_ciclo", "agente_sin_ciclo"
CLAVE_ACIERTO = f"acierto@{K_VECINOS}_p75"
METODOS = {
    "activa_ciclo": "meta.iteraciones_agente > 0 en la corrida con ciclo",
    "mejora": "entre los que activan: acierto@5 de vecinos (criterio de rag_fichas, percentil 75) pasa de 0 a 1, o "
              "el top-1 imagen-imagen sube más que δ = agente.delta_margen",
    "vecinos_antes_y_despues": "primer evento C5 recuperar_ejemplos y último evento C2 reformular de la traza",
    "latencia_anadida": "meta.tiempo_ms con ciclo − sin ciclo, por foto",
    "calidad": "juez P7, granite y chrF; ficha sin texto = 0; diferencias pareadas con IC95 bootstrap",
}


def conjunto_agente() -> tuple[list[str], dict[str, str]]:
    """Las fotos de `regiones_excluidas` que están en `eval_fichas` + `agente_extra` (cuarta parte con --rapido)."""
    part = particiones()
    regiones = set(part["regiones_excluidas"])
    base = [x for x in part["eval_fichas"] if x in regiones]
    extra = list(part["agente_extra"])
    grupo = {**{x: "eval_fichas_regiones" for x in base}, **{x: "agente_extra" for x in extra}}
    return base[:tamano(len(base))] + extra[:tamano(len(extra))], grupo


def recuperacion_de_traza(eventos: list[dict] | None) -> dict:
    """Vecinos y top-1 antes y después de reformular, según la traza."""
    if not eventos:
        return {}
    inicial = next((e for e in eventos if e["capa"] == "C5" and e["evento"] == "recuperar_ejemplos"), None)
    reformulaciones = [e for e in eventos if e["capa"] == "C2" and e["evento"] == "reformular"]
    evaluaciones = [e for e in eventos if e["capa"] == "C2" and e["evento"] == "evaluar_recuperacion"]
    d0 = (inicial or {}).get("detalle") or {}
    dn = (reformulaciones[-1].get("detalle") or {}) if reformulaciones else {}
    e0 = (evaluaciones[0].get("detalle") or {}) if evaluaciones else {}
    return {"vecinos_iniciales": d0.get("vecinos"), "top1_inicial": d0.get("top1"),
            "vecinos_finales": dn.get("vecinos") or d0.get("vecinos"), "top1_final": dn.get("top1_despues", d0.get("top1")),
            "reformulaciones_en_traza": len(reformulaciones), "pobre_inicial": e0.get("pobre"),
            "margen_inicial": e0.get("margen")}


def _primero(*valores):
    return next((v for v in valores if v is not None), None)


def caso_agente(c: ClienteEval, x: str, grupo: str | None, reg_con: dict, reg_sin: dict, criterio: CriterioVecinos,
                delta: float) -> tuple[dict, dict, dict]:
    con, sin = caso(c, CON, x, reg_con), caso(c, SIN, x, reg_sin)
    rc = recuperacion_de_traza(eventos_traza(c, con.get("traza_id")))
    rs = recuperacion_de_traza(eventos_traza(c, sin.get("traza_id")))
    vecinos_ini = rc.get("vecinos_iniciales") or rs.get("vecinos_iniciales")
    vecinos_fin = rc.get("vecinos_finales") or vecinos_ini
    top1_ini = _primero(rc.get("top1_inicial"), (sin.get("recuperacion") or {}).get("top1"))
    top1_fin = _primero((con.get("recuperacion") or {}).get("top1"), rc.get("top1_final"))
    iteraciones = con.get("iteraciones_agente")
    activa = None if iteraciones is None else iteraciones > 0
    a_ini = criterio.evaluar(x, vecinos_ini).get(CLAVE_ACIERTO) if vecinos_ini else None
    a_fin = criterio.evaluar(x, vecinos_fin).get(CLAVE_ACIERTO) if vecinos_fin else None
    de_0_a_1 = a_ini is False and a_fin is True
    sube_top1 = None if top1_ini is None or top1_fin is None else (top1_fin - top1_ini) > delta
    lat_con, lat_sin = con.get("latencia_ficha_s"), sin.get("latencia_ficha_s")
    fila = {
        "xm_id": x, "grupo": grupo, "activa_ciclo": activa, "iteraciones": iteraciones,
        "pobre_inicial": _primero(rc.get("pobre_inicial"), rs.get("pobre_inicial")),
        "margen_inicial": _primero(rc.get("margen_inicial"), rs.get("margen_inicial")),
        "top1_inicial": top1_ini, "top1_final": top1_fin,
        "cambio_top1": round(top1_fin - top1_ini, 4) if None not in (top1_ini, top1_fin) else None,
        "acierto5_inicial": a_ini, "acierto5_final": a_fin, "acierto5_de_0_a_1": de_0_a_1,
        "top1_sube_mas_que_delta": sube_top1,
        "mejora": None if not activa else bool(de_0_a_1 or sube_top1),
        "vecinos_iniciales": vecinos_ini, "vecinos_finales": vecinos_fin,
        "latencia_con_ciclo_s": lat_con, "latencia_sin_ciclo_s": lat_sin,
        "latencia_anadida_s": round(lat_con - lat_sin, 3) if None not in (lat_con, lat_sin) else None,
        "ruta_con_ciclo": con.get("ruta_final"), "ruta_sin_ciclo": sin.get("ruta_final"),
        "calidad_con_ciclo": con.get("juez_promedio"), "calidad_sin_ciclo": sin.get("juez_promedio"),
        "granite_con_ciclo": con.get("granite_max"), "granite_sin_ciclo": sin.get("granite_max"),
        "estado_http_con": con.get("estado_http"), "estado_http_sin": sin.get("estado_http"),
    }
    return fila, con, sin


def bloque(filas: list[dict]) -> dict:
    activan = [f for f in filas if f["activa_ciclo"]]
    return {
        "n": len(filas),
        "activa_ciclo": tasa([f["activa_ciclo"] for f in filas]),
        "mejora_entre_los_que_activan": tasa([f["mejora"] for f in activan]),
        "mejora_sobre_todos": tasa([bool(f["mejora"]) for f in filas]),
        "iteraciones_media": media([f["iteraciones"] for f in filas]),
        "iteraciones_media_los_que_activan": media([f["iteraciones"] for f in activan]),
        "iteraciones_distribucion": dict(Counter(str(f["iteraciones"]) for f in filas)),
        "latencia_anadida_s": percentiles([f["latencia_anadida_s"] for f in filas if f["latencia_anadida_s"] is not None]),
        "latencia_anadida_los_que_activan_s": percentiles([f["latencia_anadida_s"] for f in activan
                                                           if f["latencia_anadida_s"] is not None]),
    }


def resumen_agente(filas: list[dict], casos_con: dict, casos_sin: dict, configuracion: dict) -> dict:
    validas = [f for f in filas if f["activa_ciclo"] is not None]
    activan = [f for f in validas if f["activa_ciclo"]]
    ids_activan = {f["xm_id"] for f in activan}
    salida = {
        "configuracion_agente": configuracion, "fotos": len(filas), "con_dato": len(validas),
        **bloque(validas),
        "por_grupo": {g: bloque([f for f in validas if f["grupo"] == g]) for g in sorted({str(f["grupo"]) for f in validas})},
        "criterios_de_mejora_los_que_activan": {
            "acierto5_de_0_a_1": sum(1 for f in activan if f["acierto5_de_0_a_1"]),
            "top1_sube_mas_que_delta": sum(1 for f in activan if f["top1_sube_mas_que_delta"]),
            "ambos": sum(1 for f in activan if f["acierto5_de_0_a_1"] and f["top1_sube_mas_que_delta"])},
        "acierto5_vecinos": {
            "inicial_todos": tasa([f["acierto5_inicial"] for f in validas]),
            "final_todos": tasa([f["acierto5_final"] for f in validas]),
            "inicial_los_que_activan": tasa([f["acierto5_inicial"] for f in activan]),
            "final_los_que_activan": tasa([f["acierto5_final"] for f in activan])},
        "top1_imagen": {"inicial": resumen_numerico([f["top1_inicial"] for f in validas]),
                        "final": resumen_numerico([f["top1_final"] for f in validas]),
                        "cambio_los_que_activan": resumen_numerico([f["cambio_top1"] for f in activan])},
        "latencia_con_ciclo_s": percentiles([f["latencia_con_ciclo_s"] for f in validas if f["latencia_con_ciclo_s"] is not None]),
        "latencia_sin_ciclo_s": percentiles([f["latencia_sin_ciclo_s"] for f in validas if f["latencia_sin_ciclo_s"] is not None]),
        "rutas": {"con_ciclo": dict(Counter(str(f["ruta_con_ciclo"]) for f in validas)),
                  "sin_ciclo": dict(Counter(str(f["ruta_sin_ciclo"]) for f in validas))},
        "calidad": {
            "con_ciclo": agregar(list(casos_con.values())), "sin_ciclo": agregar(list(casos_sin.values())),
            "con_menos_sin": {k: diferencia_pareada(casos_con, casos_sin, k) for k in ("juez_promedio", "granite_max", "chrf")},
            "con_menos_sin_los_que_activan": {k: diferencia_pareada({x: casos_con[x] for x in ids_activan if x in casos_con},
                                                                    {x: casos_sin[x] for x in ids_activan if x in casos_sin}, k)
                                              for k in ("juez_promedio", "granite_max", "chrf")}},
        "metodos": METODOS,
    }
    if configuracion.get("tau_ret") is None:
        salida["advertencia"] = ("agente.tau_ret no está calibrado en la configuración: el servicio nunca considera pobre "
                                 "la recuperación y el ciclo no se activa.")
    return salida


def graficas_agente(m: dict) -> list[str]:
    fig, (a1, a2, a3) = nueva_figura(13.5, 4.1, 3)
    a5 = m["acierto5_vecinos"]
    nombres = ("Sin ciclo (recuperación inicial)", "Con ciclo (tras reformular)")
    barras(a1, ["Todas las fotos", "Las que activan\nel ciclo"],
           {nombres[0]: [a5["inicial_todos"]["tasa"], a5["inicial_los_que_activan"]["tasa"]],
            nombres[1]: [a5["final_todos"]["tasa"], a5["final_los_que_activan"]["tasa"]]}, leyenda=False)
    a1.set_ylim(0, 1.12)
    a1.set_ylabel("Acierto@5 de los vecinos (p75)")
    activa, mejora = m["activa_ciclo"]["tasa"], m["mejora_entre_los_que_activan"]["tasa"]
    a1.set_title("Recuperación de ejemplos\n" + (f"activa el ciclo {activa * 100:.0f} %" if activa is not None else "")
                 + (f" · mejora {mejora * 100:.0f} % de los que activan" if mejora is not None else ""), fontsize=9)
    q = m["calidad"]
    barras(a2, ["Fidelidad", "Relevancia"],
           {nombres[0]: [q["sin_ciclo"]["juez_fidelidad"].get("media"), q["sin_ciclo"]["juez_relevancia"].get("media")],
            nombres[1]: [q["con_ciclo"]["juez_fidelidad"].get("media"), q["con_ciclo"]["juez_relevancia"].get("media")]},
           {nombres[0]: [q["sin_ciclo"]["juez_fidelidad"].get("ic95"), q["sin_ciclo"]["juez_relevancia"].get("ic95")],
            nombres[1]: [q["con_ciclo"]["juez_fidelidad"].get("ic95"), q["con_ciclo"]["juez_relevancia"].get("ic95")]},
           leyenda=False)
    a2.set_ylim(0, 5.6)
    a2.set_ylabel("Juez P7 (0–5)")
    a2.set_title("Calidad de la ficha (bigotes: IC95)", fontsize=9)
    barras(a3, ["Mediana (p50)", "Percentil 95"],
           {nombres[0]: [m["latencia_sin_ciclo_s"].get("p50_s"), m["latencia_sin_ciclo_s"].get("p95_s")],
            nombres[1]: [m["latencia_con_ciclo_s"].get("p50_s"), m["latencia_con_ciclo_s"].get("p95_s")]},
           formato="{:.1f}", leyenda=False)
    a3.set_ylabel("Latencia de la ficha (s)")
    a3.set_title("Latencia", fontsize=9)
    fig.suptitle(f"Ciclo de agente en fotos de regiones excluidas (n = {m['con_dato']})")
    leyenda_comun(fig, a1)
    fig.tight_layout(rect=(0, 0.07, 1, 0.92))
    guardar_grafica("agente_ciclo", fig)
    return ["evaluacion/graficas/agente_ciclo.png"]


def ejecutar(c: ClienteEval) -> dict:
    exigir_servicios(c)
    ids, grupos = conjunto_agente()
    configuracion = {"tau_ret": c.config.parametro("agente.tau_ret"),
                     "delta_margen": float(c.config.parametro("agente.delta_margen", 0.02)),
                     "max_iter": c.config.parametro("agente.max_iter", 2)}
    registro(f"Ciclo de agente: {len(ids)} fotos · {configuracion}")
    docs, fallidas = subir(c, ids, "fotos de regiones excluidas")
    ids = [x for x in ids if x in docs]
    registros: dict[str, dict[str, dict]] = {CON: {}, SIN: {}}
    for k in (CON, SIN):
        avance = Avance(f"fichas {k}", len(ids))
        for x in ids:
            registros[k][x] = generar(c, k, x, docs[x])
            avance.paso()
    criterio = CriterioVecinos(c)
    criterio.precargar(ids)
    filas, casos_con, casos_sin = [], {}, {}
    avance = Avance("calidad con y sin ciclo (juez P7) y recuperación", len(ids))
    for x in ids:
        fila, casos_con[x], casos_sin[x] = caso_agente(c, x, grupos.get(x), registros[CON][x], registros[SIN][x],
                                                       criterio, configuracion["delta_margen"])
        filas.append(fila)
        avance.paso()
    metricas = resumen_agente(filas, casos_con, casos_sin, configuracion)
    metricas["no_subidas"] = fallidas
    metricas["graficas"] = graficas_agente(metricas)
    metricas["detalle_fichas"] = escribir_csv("agente_fichas_detalle", [fila_csv(v) for d in (casos_con, casos_sin)
                                                                        for v in d.values()])
    guardar_resultado("agente", metricas, filas, {"configuraciones": {k: CONFIGURACIONES[k] for k in (CON, SIN)},
                                                  "agente": configuracion}, c)
    return metricas


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rapido", action="store_true", help="la cuarta parte de los casos (prueba de humo)")
    if ap.parse_args().rapido:
        os.environ["FOTOTECA_EVAL_RAPIDO"] = "1"
    ejecutar(ClienteEval())


if __name__ == "__main__":
    main()
