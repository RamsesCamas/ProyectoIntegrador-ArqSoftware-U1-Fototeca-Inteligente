"""R3 · Selección de embeddings y de arquitectura de búsqueda (ADR-02).

Es un experimento de MODELOS, así que usa los adaptadores de C7 directamente (no la API), con la misma preparación
de imágenes y los mismos prefijos que producción.

1. Texto→imagen en la galería: unificado (EmbeddingGemma-2 texto→imagen), pipeline (Qwen describe cada imagen con
   P1 y se compara texto→texto con EmbeddingGemma-2 y con granite) e híbrido (RRF de unificado y pipeline). La
   consulta es la 1ª descripción en español; la imagen correcta es la de esa descripción. R@1, R@5, R@10 y MRR, por
   locale y por longitud de la consulta. Las tres arquitecturas se comparan sobre la MISMA sub-galería (la que Qwen
   describe); el unificado se reporta además sobre la galería COMPLETA de 1,000 (sus vectores de imagen ya están en
   el npz de preparar_datos, solo se embeben las consultas). Las cifras de las dos galerías no son comparables entre
   sí: el R@k baja cuando la galería crece. Las descripciones de Qwen se guardan en `data/procesados/desc_qwen.jsonl`.
2. Descripción→descripción (2ª contra 1ª descripción): EmbeddingGemma-2 contra granite.
3. Asignación de términos del tesauro: etiqueta de Open Images → concepto esperado por coincidencia léxica única en
   inglés (singular/plural; `scripts._tesauro_lexico`, la misma regla con la que indexar_archivo calibra τ_tesauro);
   exactitud top-1 y top-3. 50 se revisan a mano (plantilla_tesauro.csv).
4. Recuperación de normas: 20 consultas con las reglas esperadas (`consultas_normas`), acierto@k.

    python -m evaluacion.r3_embeddings
"""
from __future__ import annotations

import json
import random
import time
from collections import defaultdict

import numpy as np

from evaluacion.comun import (CONJUNTOS, DATA, REVISION, SEMILLA, Incremental, guardar_grafica, guardar_resultado,
                              particiones, plt, registro, tamano)

K = (1, 5, 10)
UNIFICADO = "unificado (EmbeddingGemma-2 texto→imagen)"


def metricas_ranking(sims: np.ndarray) -> dict:
    """`sims[i, j]`: similitud de la consulta i con el documento j; el correcto de i es j = i."""
    orden = np.argsort(-sims, axis=1)
    rangos = np.array([int(np.where(orden[i] == i)[0][0]) + 1 for i in range(sims.shape[0])])
    return {**{f"R@{k}": round(float(np.mean(rangos <= k)), 4) for k in K}, "MRR": round(float(np.mean(1.0 / rangos)), 4),
            "_rangos": rangos}


def rrf_matrices(*matrices: np.ndarray, k: int = 60) -> np.ndarray:
    total = np.zeros_like(matrices[0])
    for m in matrices:
        rangos = np.argsort(np.argsort(-m, axis=1), axis=1) + 1
        total += 1.0 / (k + rangos)
    return total


def describir_galeria(c, galeria: list[str], indice: dict, dir_img) -> dict[str, str]:
    """P1 de Qwen sobre cada imagen de la galería (una sola vez; reanudable)."""
    from fototeca.modelos.gateway import Gateway
    from fototeca.modelos.plantillas import cargar_plantillas
    inc = Incremental("r3_desc_qwen")
    gw = Gateway(c.contenedor.cliente_llm, c.config, cargar_plantillas())
    t0, hechos = time.perf_counter(), 0
    for i, doc in enumerate(galeria):
        if inc.obtener(doc):
            continue
        inicio = time.perf_counter()
        try:
            s = gw.ejecutar("P1", {}, imagenes=[(dir_img / indice[doc]["archivo"]).read_bytes()])
            inc.guardar(doc, {"descripcion": s.datos.get("descripcion_visual", ""), "elementos": s.datos.get("elementos", []),
                              "modelo": s.modelo, "segundos": round(time.perf_counter() - inicio, 2)})
        except Exception as e:  # noqa: BLE001 — se registra y se sigue
            inc.guardar(doc, {"descripcion": "", "error": type(e).__name__, "segundos": round(time.perf_counter() - inicio, 2)})
        hechos += 1
        if hechos % 20 == 0:
            ritmo = (time.perf_counter() - t0) / hechos
            registro(f"   P1 galería {i + 1}/{len(galeria)} · {ritmo:.1f} s/imagen · faltan ~{(len(galeria) - i - 1) * ritmo / 3600:.1f} h")
    return {d: inc.obtener(d)["descripcion"] for d in galeria}


def guardar_desc_qwen(procesados) -> str:
    """Copia las descripciones P1 de Qwen (casos de `resultados/casos/r3_desc_qwen.jsonl`) a
    `data/procesados/desc_qwen.jsonl`, una línea por imagen, para reutilizarlas sin volver a llamar al modelo.
    Escritura atómica."""
    casos = Incremental("r3_desc_qwen").casos
    ruta = procesados / "desc_qwen.jsonl"
    temporal = ruta.with_name(ruta.name + ".tmp")
    with open(temporal, "w", encoding="utf-8") as f:
        for doc in sorted(casos):
            x = casos[doc]
            f.write(json.dumps({"documento_id": doc, "descripcion": x.get("descripcion", ""),
                                "elementos": x.get("elementos", []), "modelo": x.get("modelo"),
                                "segundos": x.get("segundos"), "error": x.get("error")}, ensure_ascii=False) + "\n")
    temporal.replace(ruta)
    registro(f"descripciones de Qwen → {ruta} ({len(casos)} imágenes)")
    return str(ruta)


def analisis_por_grupo(rangos: dict[str, np.ndarray], locales: list[str], consultas: list[str],
                       excluidas: set[str]) -> tuple[dict, dict]:
    """R@k por grupo (regiones excluidas contra el resto; consultas cortas contra largas) y R@10 por locale."""
    longitudes = np.array([len(q.split()) for q in consultas])
    tercios = np.percentile(longitudes, [33, 66])
    por_grupo = defaultdict(dict)
    for nombre, r in rangos.items():
        for etiqueta, mascara in {"regiones_excluidas": np.array([l in excluidas for l in locales]),
                                  "resto_de_locales": np.array([l not in excluidas for l in locales]),
                                  f"consulta_corta (≤{int(tercios[0])} palabras)": longitudes <= tercios[0],
                                  f"consulta_larga (>{int(tercios[1])} palabras)": longitudes > tercios[1]}.items():
            if mascara.any():
                por_grupo[etiqueta][nombre] = {f"R@{k}": round(float(np.mean(r[mascara] <= k)), 4) for k in K} | {"n": int(mascara.sum())}
    por_locale = {loc: {n: round(float(np.mean(r[np.array(locales) == loc] <= 10)), 4) for n, r in rangos.items()}
                  for loc in sorted(set(locales))}
    return dict(por_grupo), por_locale


def ejecutar(c) -> dict:
    from scripts._xm3600 import cargar_indice
    from scripts.preparar_datos import PROCESADOS, slug
    regs, dir_img = cargar_indice()
    indice = {f"xm-{r['clave']}": r for r in regs}
    part = particiones()
    emb, granite = c.contenedor.embebedor, c.contenedor.embebedor_secundario
    z = np.load(PROCESADOS / f"emb_img_{slug(emb.nombre_modelo)}_{emb.lado_imagen_px}px.npz", allow_pickle=False)
    vec_img = {f"xm-{k}": v for k, v in zip(z["ids"].tolist(), z["vectores"])}

    # Tamaño de la galería del pipeline: se estima con 20 descripciones; si las 1,000 tardarían > 3 h, se usan 500.
    rng = random.Random(SEMILLA)
    galeria_total = sorted(part["galeria_busqueda"])
    previas = Incremental("r3_desc_qwen")
    muestra_tiempo = [x["segundos"] for x in previas.casos.values() if "segundos" in x][:20]
    if len(muestra_tiempo) < 20:
        describir_galeria(c, galeria_total[:20], indice, dir_img)
        muestra_tiempo = [x["segundos"] for x in Incremental("r3_desc_qwen").casos.values()][:20]
    segundos_por_imagen = float(np.mean(muestra_tiempo))
    estimado_h = segundos_por_imagen * len(galeria_total) / 3600
    n_galeria = len(galeria_total) if estimado_h <= 3 else 500
    galeria = sorted(galeria_total[:20] + rng.sample(galeria_total[20:], tamano(n_galeria) - 20)) if n_galeria < len(galeria_total) \
        else galeria_total
    galeria = galeria[:tamano(len(galeria))]
    registro(f"galería: {len(galeria)} imágenes (estimado para 1,000: {estimado_h:.1f} h a {segundos_por_imagen:.1f} s/imagen)")

    consultas = [indice[d]["es"][0] for d in galeria]
    q_emb = emb.embeber_textos(consultas, rol="consulta")
    m_img = np.stack([vec_img[d] for d in galeria])
    sims_unif = q_emb @ m_img.T
    descripciones = describir_galeria(c, galeria, indice, dir_img)
    ruta_desc_qwen = guardar_desc_qwen(PROCESADOS)
    textos_desc = [descripciones[d] or "" for d in galeria]
    d_emb = emb.embeber_textos(textos_desc, rol="documento")
    sims_pipe_emb = q_emb @ d_emb.T
    q_gr, d_gr = granite.embeber_textos(consultas), granite.embeber_textos(textos_desc)
    sims_pipe_gr = q_gr @ d_gr.T
    sims_hib = rrf_matrices(sims_unif, sims_pipe_emb)
    configuraciones = {UNIFICADO: sims_unif,
                       "pipeline (Qwen + EmbeddingGemma-2 texto→texto)": sims_pipe_emb,
                       "pipeline (Qwen + granite texto→texto)": sims_pipe_gr,
                       "hibrido (RRF unificado + pipeline EmbeddingGemma-2)": sims_hib}
    texto_imagen = {}
    rangos = {}
    for nombre, s in configuraciones.items():
        m = metricas_ranking(s)
        rangos[nombre] = m.pop("_rangos")
        texto_imagen[nombre] = m
    # Análisis por locale y por longitud de la consulta
    locales = [indice[d]["locale"] for d in galeria]
    excluidas = set(json.loads((CONJUNTOS / "particiones.json").read_text(encoding="utf-8"))["locales_excluidas"])
    por_grupo, por_locale = analisis_por_grupo(rangos, locales, consultas, excluidas)

    # 1b. Unificado sobre la galería COMPLETA (misma consulta: 1ª descripción en español)
    galeria_completa = galeria_total[:tamano(len(galeria_total))]
    if galeria_completa == galeria:
        rangos_completa = rangos[UNIFICADO]
        unificado_completa = dict(texto_imagen[UNIFICADO])
        consultas_completa, locales_completa = consultas, locales
    else:
        consultas_completa = [indice[d]["es"][0] for d in galeria_completa]
        locales_completa = [indice[d]["locale"] for d in galeria_completa]
        m = metricas_ranking(emb.embeber_textos(consultas_completa, rol="consulta")
                             @ np.stack([vec_img[d] for d in galeria_completa]).T)
        rangos_completa = m.pop("_rangos")
        unificado_completa = m
    por_grupo_completa, por_locale_completa = analisis_por_grupo({UNIFICADO: rangos_completa}, locales_completa,
                                                                 consultas_completa, excluidas)
    texto_imagen_completa = {"n": len(galeria_completa), UNIFICADO: unificado_completa,
                             "nota": "galería completa; no comparable con la sub-galería (el R@k baja al crecer la galería)"}

    # 2. Descripción→descripción (2ª contra 1ª)
    con_dos = [d for d in galeria if len(indice[d]["es"]) >= 2]
    a = [indice[d]["es"][1] for d in con_dos]
    b = [indice[d]["es"][0] for d in con_dos]
    desc_desc = {"EmbeddingGemma-2": metricas_ranking(emb.embeber_textos(a, rol="consulta") @ emb.embeber_textos(b, rol="documento").T),
                 "granite": metricas_ranking(granite.embeber_textos(a) @ granite.embeber_textos(b).T)}
    for v in desc_desc.values():
        v.pop("_rangos")

    # 3. Tesauro y 4. normas
    tesauro = evaluar_tesauro(c, emb, granite)
    normas = evaluar_normas(c, emb, granite)

    fig = plt().figure(figsize=(8, 3.6))
    ax = fig.add_subplot(111)
    nombres = list(texto_imagen)
    for i, k in enumerate(K):
        ax.bar(np.arange(len(nombres)) + (i - 1) * 0.25, [texto_imagen[n][f"R@{k}"] for n in nombres], width=0.25, label=f"R@{k}")
    ax.set_xticks(np.arange(len(nombres)), [n.split(" (")[0] + "\n" + n.split("(")[1].rstrip(")") for n in nombres], fontsize=7)
    ax.set_ylim(0, 1)
    ax.set_ylabel("Acierto")
    ax.set_title(f"Búsqueda texto→imagen en la galería (n={len(galeria)})")
    ax.legend()
    guardar_grafica("r3_embeddings_texto_imagen", fig)

    costo = {"segundos_por_descripcion_qwen": round(segundos_por_imagen, 2),
             "horas_estimadas_para_1000": round(estimado_h, 2),
             "horas_totales_descripciones": round(sum(x.get("segundos", 0) for x in Incremental("r3_desc_qwen").casos.values()) / 3600, 2),
             "descripciones_guardadas_en": "data/procesados/desc_qwen.jsonl"}
    metricas = {"galeria": {"n": len(galeria), "decision_tamano": f"todas ({len(galeria_total)})" if n_galeria == len(galeria_total)
                            else "500 (regla del experimento: si describir las 1,000 con Qwen tardaría más de 3 h, "
                                 "se usan 500)"},
                "texto_imagen": texto_imagen, "por_grupo": por_grupo, "por_locale_R@10": por_locale,
                "texto_imagen_galeria_completa": texto_imagen_completa,
                "por_grupo_galeria_completa": por_grupo_completa, "por_locale_R@10_galeria_completa": por_locale_completa,
                "costo_pipeline": costo, "descripcion_descripcion": desc_desc, "tesauro": tesauro, "normas": normas}
    # Un nombre corto y único por configuración (las dos de pipeline empiezan igual)
    cortos = dict(zip(configuraciones, ("unificado", "pipeline_embeddinggemma", "pipeline_granite", "hibrido")))
    detalle = [{"documento_id": d, "locale": loc, "consulta": q, **{f"rango_{cortos[n]}": int(r[i]) for n, r in rangos.items()}}
               for i, (d, loc, q) in enumerate(zip(galeria, locales, consultas))]
    guardar_resultado("r3_embeddings", metricas, detalle, {"modelo_principal": emb.nombre_modelo, "modelo_secundario": granite.nombre_modelo,
                                                           "lado_imagen_px": emb.lado_imagen_px,
                                                           "galeria_pipeline": len(galeria),
                                                           "galeria_completa": len(galeria_completa),
                                                           "desc_qwen": ruta_desc_qwen}, c)
    return metricas


def evaluar_tesauro(c, emb, granite) -> dict:
    """Etiqueta de Open Images (inglés) → concepto del tesauro (español). Esperado: coincidencia léxica ÚNICA de la
    etiqueta en inglés (singular o plural) con prefLabel/altLabel@en del concepto; las formas ambiguas se descartan
    (`scripts._tesauro_lexico`, la misma regla que usa indexar_archivo para calibrar τ_tesauro)."""
    from scripts._tesauro_lexico import esperado, indice_ingles
    from scripts.preparar_datos import PROCESADOS
    conceptos = [json.loads(l) for l in (DATA / "corpus" / "tesauro.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    indice_en = indice_ingles(conceptos)
    etiquetas = json.loads((PROCESADOS / "oi_etiquetas_por_imagen.json").read_text(encoding="utf-8"))
    nombres = sorted({e["nombre"] for v in etiquetas.values() for e in v})
    esperados = {n: esperado(n, indice_en) for n in nombres}
    con_esperado = [n for n in nombres if esperados[n]]
    rng = random.Random(SEMILLA)
    muestra = sorted(rng.sample(con_esperado, min(tamano(200), len(con_esperado))))
    textos = [x["texto"] for x in conceptos]
    uris = [x["uri"] for x in conceptos]
    resultados = {}
    for nombre, e, rol_q, rol_d in (("EmbeddingGemma-2", emb, "consulta", "documento"), ("granite", granite, "documento", "documento")):
        mc = e.embeber_textos(textos, rol=rol_d)
        mq = e.embeber_textos(muestra, rol=rol_q)
        orden = np.argsort(-(mq @ mc.T), axis=1)[:, :3]
        top1 = [uris[o[0]] == esperados[m] for m, o in zip(muestra, orden)]
        top3 = [esperados[m] in [uris[j] for j in o] for m, o in zip(muestra, orden)]
        resultados[nombre] = {"exactitud_top1": round(float(np.mean(top1)), 4), "exactitud_top3": round(float(np.mean(top3)), 4)}
    from evaluacion.analizar_revision_manual import escribir_plantilla
    plantilla = escribir_plantilla(
        REVISION / "plantilla_tesauro.csv",
        ["etiqueta_open_images", "concepto_esperado_uri", "esperado_correcto (si/no)",
         "concepto_correcto (uri, si el esperado no es correcto)", "comentario"],
        [[m, esperados[m], "", "", ""] for m in muestra[:50]],
        columnas_humanas=("esperado_correcto", "concepto_correcto", "comentario"))
    return {"etiquetas_unicas": len(nombres), "etiquetas_con_esperado": len(con_esperado), "evaluadas": len(muestra),
            "por_modelo": resultados, "plantilla_revision": plantilla,
            "metodo_esperado": "coincidencia léxica única de la etiqueta en inglés (singular o plural) con "
                               "prefLabel/altLabel@en del concepto (scripts._tesauro_lexico; formas ambiguas descartadas); "
                               "50 se revisan a mano (plantilla_tesauro.csv)"}


def evaluar_normas(c, emb, granite) -> dict:
    ruta = CONJUNTOS / "consultas_normas.json"
    if not ruta.exists():
        return {"estado": "pendiente: falta evaluacion/conjuntos/consultas_normas.json"}
    consultas = json.loads(ruta.read_text(encoding="utf-8"))["items"]
    normas = [json.loads(l) for l in (DATA / "corpus" / "normas.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    ids = [n["id"] for n in normas]
    # Si el corpus se regeneró y cambió algún id, la consulta sin esperadas vigentes no se puede calificar.
    vigentes = set(ids)
    inexistentes = sorted({e for q in consultas for e in q["esperadas"] if e not in vigentes})
    validas = [q for q in consultas if any(e in vigentes for e in q["esperadas"])]
    if not validas:
        return {"estado": "pendiente: ninguna regla esperada existe en el corpus actual", "esperadas_inexistentes": inexistentes}
    resultados = {}
    por_tipo: dict[str, dict] = defaultdict(dict)
    for nombre, e, rq, rd in (("EmbeddingGemma-2", emb, "consulta", "documento"), ("granite", granite, "documento", "documento")):
        mn = e.embeber_textos([n["texto"] for n in normas], rol=rd)
        mq = e.embeber_textos([q["consulta"] for q in validas], rol=rq)
        orden = np.argsort(-(mq @ mn.T), axis=1)
        acierto = {k: np.array([any(ids[j] in q["esperadas"] for j in o[:k]) for q, o in zip(validas, orden)]) for k in (1, 4, 10)}
        resultados[nombre] = {f"acierto@{k}": round(float(v.mean()), 4) for k, v in acierto.items()}
        tipos = np.array([q.get("tipo", "sin_tipo") for q in validas])
        for tipo in sorted(set(tipos)):
            por_tipo[tipo][nombre] = {f"acierto@{k}": round(float(v[tipos == tipo].mean()), 4) for k, v in acierto.items()} \
                | {"n": int((tipos == tipo).sum())}
    return {"consultas": len(validas), "por_modelo": resultados, "por_tipo": dict(por_tipo),
            "esperadas_inexistentes": inexistentes, "k_produccion": int(c.config.parametro("recuperacion.k_normas", 4)),
            "metodo": "consultas redactadas a partir del contenido de los fragmentos; esperadas marcadas por lectura "
                      "(evaluacion/conjuntos/consultas_normas.json)"}


if __name__ == "__main__":
    from evaluacion.comun import ClienteEval
    ejecutar(ClienteEval())
