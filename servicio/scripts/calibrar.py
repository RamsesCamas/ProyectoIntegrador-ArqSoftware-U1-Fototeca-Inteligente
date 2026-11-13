"""Calibración de umbrales con datos (H4 y H5). Escribe evaluacion/resultados/calibracion_<fase>.json.

    python -m scripts.calibrar h4    # τ_ret, τ_consenso, τ_busqueda, τ_apego_visual, τ_consistencia
    python -m scripts.calibrar h5    # τ_fuera_dominio, τ_texto_visible, τ_inyeccion

Reglas (ADR-03, ADR-05 y ADR-07):
- τ_ret = p10 del top-1 de la recuperación de ejemplos en `nuevas` (sin `eval_fichas` ni `regiones_excluidas`).
- τ_consenso = p50 del consenso (media del coseno imagen-imagen de los 5 vecinos) en el mismo conjunto.
- τ_apego_visual = p5 de la similitud imagen–texto alternativo humano (la descripción más corta) en el archivo.
- τ_busqueda = p5 de la similitud imagen–descripción humana (la 1ª) en el archivo: piso de relevancia.
- τ_consistencia = p5 de la similitud granite entre dos descripciones humanas de una misma imagen en el archivo.
- H5 usa SOLO los conjuntos `calibracion_*` y el archivo; los conjuntos de evaluación quedan fuera de muestra.
Los valores se copian a config/parametros.yaml con su comentario; la versión de configuración cambia.
"""
from __future__ import annotations

import argparse
import json
import random

import numpy as np

from fototeca.api.arranque import cargar_configuracion, construir_contenedor
from fototeca.contexto.recuperador_ejemplos import RecuperadorEjemplos
from fototeca.guardrails.entrada.imagen import VerificadorImagen
from fototeca.modelos.enrutador_fichas import senales
from scripts._descargas import DATA, EVAL, ahora_iso, json_guardar, registro
from scripts._xm3600 import SEMILLA, cargar_indice
from scripts.preparar_datos import PROCESADOS, slug

CONJUNTOS = EVAL / "conjuntos"


def pct(valores, q) -> float:
    return round(float(np.percentile(np.asarray(valores, dtype=float), q)), 4)


def resumen(valores) -> dict:
    a = np.asarray(valores, dtype=float)
    return {"n": int(a.size), "p5": pct(a, 5), "p10": pct(a, 10), "p25": pct(a, 25), "p50": pct(a, 50),
            "p75": pct(a, 75), "p95": pct(a, 95), "min": round(float(a.min()), 4), "max": round(float(a.max()), 4)}


def _particiones() -> dict:
    return json.loads((CONJUNTOS / "particiones.json").read_text(encoding="utf-8"))["particiones"]


def _matriz_imagenes(c) -> tuple[dict, np.ndarray]:
    p = c.embebedor
    z = np.load(PROCESADOS / f"emb_img_{slug(p.nombre_modelo)}_{p.lado_imagen_px}px.npz", allow_pickle=False)
    return {k: i for i, k in enumerate(z["ids"].tolist())}, z["vectores"]


def h4(c) -> dict:
    part = _particiones()
    indice, m = _matriz_imagenes(c)
    calibracion = sorted(set(part["nuevas"]) - set(part["eval_fichas"]))
    rec = RecuperadorEjemplos(c.almacen_vectorial, c.embebedor, c.almacen_documentos)
    top1, consenso, margen = [], [], []
    for i, doc in enumerate(calibracion):
        v = m[indice[doc.removeprefix("xm-")]]
        r = rec.fusionar(v, rec.listas_unificadas(v, doc))
        top1.append(r.top1)
        margen.append(r.margen)
        consenso.append(senales(r.vecinos, False)["consenso"])
        if (i + 1) % 100 == 0:
            registro(f"   {i + 1}/{len(calibracion)} fotos de nuevas")
    regs, _ = cargar_indice()
    por_id = {f"xm-{r['clave']}": r for r in regs}
    rng = random.Random(SEMILLA)
    muestra = rng.sample(part["archivo"], 600)
    vec_img = np.stack([m[indice[d.removeprefix('xm-')]] for d in muestra])
    primeras = c.embebedor.embeber_textos([por_id[d]["es"][0] for d in muestra], rol="consulta")
    cortas = c.embebedor.embeber_textos([min(por_id[d]["es"], key=len) for d in muestra], rol="consulta")
    sim_desc = np.sum(vec_img * primeras, axis=1)
    # Piso de relevancia de la búsqueda: el nivel que alcanzan los pares imagen–descripción AJENOS (ruido). Con el p5
    # de los pares propios (versión anterior) solo pasaban coincidencias casi exactas: 3.2 fotos de 600 por consulta.
    matriz = vec_img @ np.asarray(primeras).T
    sim_ajenas = matriz[~np.eye(len(muestra), dtype=bool)]
    sim_alt = np.sum(vec_img * cortas, axis=1)
    dobles = [d for d in muestra if len(por_id[d]["es"]) >= 2]
    g1 = c.embebedor_secundario.embeber_textos([por_id[d]["es"][0] for d in dobles])
    g2 = c.embebedor_secundario.embeber_textos([por_id[d]["es"][1] for d in dobles])
    sim_granite = np.sum(g1 * g2, axis=1)
    return {
        "conjunto_calibracion": f"nuevas sin eval_fichas ({len(calibracion)} fotos); archivo (muestra de {len(muestra)})",
        "distribuciones": {"top1_recuperacion": resumen(top1), "margen_top1_top5": resumen(margen),
                           "consenso": resumen(consenso), "imagen_vs_descripcion_humana": resumen(sim_desc),
                           "imagen_vs_descripcion_ajena": {**resumen(sim_ajenas), "p99": pct(sim_ajenas, 99)},
                           "imagen_vs_texto_alternativo_humano": resumen(sim_alt),
                           "granite_desc_vs_desc_misma_imagen": resumen(sim_granite)},
        "umbrales": {"agente.tau_ret": pct(top1, 10), "enrutador_fichas.tau_consenso": pct(consenso, 50),
                     "enrutador_busquedas.tau_busqueda": pct(sim_ajenas, 95),
                     "guardrails.tau_apego_visual": pct(sim_alt, 5),
                     "guardrails.tau_consistencia": pct(sim_granite, 5)},
        "reglas": {"agente.tau_ret": "p10 del top-1 de recuperación en nuevas",
                   "enrutador_fichas.tau_consenso": "p50 del consenso entre vecinos en nuevas",
                   "enrutador_busquedas.tau_busqueda": "p95 de la similitud imagen–descripción ajena (piso de ruido)",
                   "guardrails.tau_apego_visual": "p5 de imagen–texto alternativo humano de la misma foto",
                   "guardrails.tau_consistencia": "p5 de granite entre dos descripciones humanas de la misma foto"},
        "resultados_por_consulta_sobre_tau_busqueda": round(float(np.mean((matriz >= pct(sim_ajenas, 95)).sum(axis=0))), 2),
        "fraccion_pobre_con_tau_ret_y_delta": round(float(np.mean([(t < pct(top1, 10)) or (mg < 0.02)
                                                                     for t, mg in zip(top1, margen)])), 4),
    }


def _umbral_balanceado(positivos: list[float], negativos: list[float], fpr_max: float = 0.01) -> dict:
    """El umbral con mejor exactitud balanceada cuya tasa de falsos positivos (negativos ≥ umbral) sea ≤ fpr_max."""
    candidatos = sorted(set(positivos + negativos))
    mejor = None
    for u in candidatos:
        tpr = float(np.mean([p >= u for p in positivos]))
        fpr = float(np.mean([n >= u for n in negativos]))
        if fpr <= fpr_max and (mejor is None or tpr - fpr > mejor["tpr"] - mejor["fpr"]):
            mejor = {"umbral": u, "tpr": round(tpr, 4), "fpr": round(fpr, 4)}
    if mejor is None:
        return {"umbral": round(max(negativos) + 1e-4, 4), "tpr": 0.0, "fpr": 0.0}
    # El candidato coincide con un caso de calibración (margen cero). Se usa el punto medio entre él y el valor
    # inmediato inferior: la TPR y la FPR en calibración no cambian, y los casos nuevos tienen margen.
    inferiores = [x for x in candidatos if x < mejor["umbral"]]
    limite = mejor["umbral"]
    mejor["umbral"] = round((limite + max(inferiores)) / 2, 4) if inferiores else round(limite, 4)
    mejor["candidato_en_calibracion"] = round(limite, 4)
    return mejor


def h5(c) -> dict:
    part = _particiones()
    indice, m = _matriz_imagenes(c)
    ver = VerificadorImagen(c.config, c.almacen_vectorial, c.embebedor)
    rng = random.Random(SEMILLA + 1)
    archivo = rng.sample(part["archivo"], 400)
    vec_archivo = [m[indice[d.removeprefix("xm-")]] for d in archivo]

    def diferencias(vectores, tipo, pos, neg):
        return [ver._diferencia(v, tipo, pos, neg) for v in vectores]

    def vectores_de(conjunto: str) -> list[np.ndarray]:
        items = json.loads((CONJUNTOS / f"{conjunto}.json").read_text(encoding="utf-8"))["items"]
        return list(c.embebedor.embeber_imagenes([(DATA / it["archivo"]).read_bytes() for it in items]))

    fdd = diferencias(vectores_de("calibracion_fuera_de_dominio"), "dominio", "fotografia", "fuera_de_dominio")
    fotos = diferencias(vec_archivo, "dominio", "fotografia", "fuera_de_dominio")
    # fuera de dominio: «positivo» = parece documento ⇒ diferencia BAJA; se invierte el signo para el umbral
    u_fdd = _umbral_balanceado([-x for x in fdd], [-x for x in fotos])
    con_texto = diferencias(vectores_de("calibracion_texto_visible"), "texto_visible", "con_texto", "sin_texto")
    sin_texto = diferencias(vec_archivo, "texto_visible", "con_texto", "sin_texto")
    u_txt = _umbral_balanceado(con_texto, sin_texto, fpr_max=0.10)
    inyecciones = [it["texto"] for it in json.loads((CONJUNTOS / "calibracion_inyeccion_texto.json").read_text(encoding="utf-8"))["items"]]
    regs, _ = cargar_indice()
    por_id = {f"xm-{r['clave']}": r for r in regs}
    normales = [por_id[d]["es"][0] for d in archivo[:300]]
    protos = ver.prototipos("inyeccion")
    sim = lambda textos: list(np.max(c.embebedor.embeber_textos(textos, rol="simetrico") @ protos.T, axis=1))  # noqa: E731
    s_iny, s_norm = sim(inyecciones), sim(normales)
    u_iny = _umbral_balanceado([float(x) for x in s_iny], [float(x) for x in s_norm], fpr_max=0.01)
    return {
        "conjuntos": {"positivos": ["calibracion_fuera_de_dominio", "calibracion_texto_visible", "calibracion_inyeccion_texto"],
                      "negativos": f"archivo (muestra de {len(archivo)} fotos y {len(normales)} descripciones)"},
        "distribuciones": {"dominio_fotos_archivo": resumen(fotos), "dominio_capturas": resumen(fdd),
                           "texto_visible_con_texto": resumen(con_texto), "texto_visible_archivo": resumen(sin_texto),
                           "inyeccion_frases": resumen(s_iny), "inyeccion_descripciones_normales": resumen(s_norm)},
        "umbrales": {"guardrails.tau_fuera_dominio": -u_fdd["umbral"], "guardrails.tau_texto_visible": u_txt["umbral"],
                     "guardrails.tau_inyeccion": u_iny["umbral"]},
        "desempeno_en_calibracion": {"fuera_de_dominio": u_fdd, "texto_visible": u_txt, "inyeccion_texto": u_iny},
        "regla": "umbral con mejor exactitud balanceada cuya tasa de falsos positivos sobre el archivo sea ≤ 1 % "
                 "(≤ 10 % para texto visible, cuyo costo es solo enviar la foto por la ruta completa); el umbral se "
                 "coloca en el punto medio entre ese candidato y el valor inmediato inferior",
        "nota_signo": "fuera de dominio se calibra con el signo invertido (positivo = diferencia baja): en "
                      "desempeno_en_calibracion el umbral aparece positivo y en umbrales con su signo real",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fase", choices=["h4", "h5"])
    args = ap.parse_args()
    c = construir_contenedor(cargar_configuracion())
    # Proceso por lotes sin usuario esperando: tiempo límite holgado (el de H0, 5 s por elemento, es interactivo)
    c.embebedor.tiempo_limite_s = max(float(c.embebedor.tiempo_limite_s), 30.0)
    registro(f"calibración {args.fase}")
    resultado = {"fecha": ahora_iso(), "fase": args.fase, "version_configuracion_previa":
                 c.config.version_configuracion(c.almacen_documentos.leer_estado("version_corpus", "sin_corpus")),
                 **(h4(c) if args.fase == "h4" else h5(c))}
    json_guardar(EVAL / "resultados" / f"calibracion_{args.fase}.json", resultado)
    registro("umbrales sugeridos: " + json.dumps(resultado["umbrales"], ensure_ascii=False))


if __name__ == "__main__":
    main()
