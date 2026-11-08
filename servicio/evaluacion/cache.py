"""Caché exacta y semántica (ADR-04): aciertos, respuestas incorrectas servidas, latencia con y sin caché, elección
de τ_dup e invalidación. Las fichas y búsquedas pasan por la API real con la caché ENCENDIDA.

1. Fichas · caché exacta: 50 fotos de `nuevas` que ningún otro experimento usa (fuera de eval_fichas, ajuste_prompts
   y aprendizaje). Por foto: carga → ficha (fallo de caché: se genera y se guarda) → la MISMA carga otra vez (debe
   devolver el mismo documento) → ficha (se espera un acierto exacto).
2. Fichas · caché semántica y τ_dup: `casi_duplicados_pos` (300 transformaciones de 150 fotos del archivo) y
   `casi_duplicados_neg` (150 pares de fotos distintas: cada foto con su vecino más cercano en el archivo). De cada
   transformada se calcula el embedding de imagen con el mismo adaptador del servicio y se busca su vecino más
   cercano en el archivo (vectores de preparar_datos). A un τ dado, hay acierto si ese coseno ≥ τ y es correcto si el
   vecino es la foto original; en los negativos, cada acierto es una respuesta incorrecta servida. Barrido de τ de
   0.90 a 0.99 en pasos de 0.01: tasa de aciertos, recall, FPR y precisión. Se elige el τ de máximo recall con
   FPR ≤ 2 % (empates: menor FPR y luego τ más alto). El valor elegido se escribe en el JSON; la configuración no se
   toca aquí.
3. Búsquedas: 30 fotos del archivo con dos descripciones en español. A = 1ª descripción (fallo esperado), A otra vez
   (acierto exacto esperado) y B = 2ª descripción como paráfrasis (acierto semántico si su coseno con A ≥ τ_busq).
   Cada acierto semántico se compara con la búsqueda fresca de B (sin caché): es una respuesta incorrecta servida si
   viene de la entrada de otra consulta o si la búsqueda fresca encuentra la foto en el top-k y la servida no.
4. Latencia con y sin caché: p50 (y p95) de los fallos contra los aciertos, con la reducción en porcentaje.
5. Invalidación (prueba automática): se elimina por la API una foto con ficha en caché y se verifica que su entrada
   ya no responde (ni en el almacén de la caché ni al volver a cargarla y pedir su ficha) y que la búsqueda en caché
   tampoco responde (la eliminación cambia version_archivo).

    python -m evaluacion.cache
"""
from __future__ import annotations

import hashlib
import random
import time
from pathlib import Path

import numpy as np
import yaml

from evaluacion.calidad import asegurar_subidas, indice_xm
from evaluacion.comun import (DATA, SEMILLA, ClienteEval, Incremental, guardar_grafica, guardar_resultado,
                              leer_conjunto, particiones, percentiles, plt, registro, tamano)

TAUS = [round(float(x), 2) for x in np.arange(0.90, 0.9901, 0.01)]
FPR_MAX = 0.02
LOTE_EMBEDDINGS = 8
PALETA = {"azul": "#2a78d6", "naranja": "#eb6834", "aqua": "#1baf7a", "amarillo": "#eda100", "gris": "#9a9992"}


# ───────────────────────────── utilidades ─────────────────────────────
def _muestra(candidatas: list[str], n: int, semilla: str) -> list[str]:
    """Muestra fija con semilla; con --rapido se toma el inicio de la MISMA muestra (la corrida completa la reutiliza)."""
    orden = random.Random(f"{SEMILLA}-{semilla}").sample(sorted(candidatas), min(n, len(candidatas)))
    return orden[:tamano(len(orden))]


def _documento_vigente(c: ClienteEval, xm: str, documento_id: str) -> tuple[str, bool]:
    """(documento_id, se_volvio_a_subir). Si la subida ya no existe (p. ej. se reconstruyó el archivo), se vuelve a
    subir; el id deriva del sha256, así que suele ser el mismo."""
    if c.contenedor.almacen_documentos.obtener_documento(documento_id):
        return documento_id, False
    r = c.subir_foto(indice_xm()[xm]["ruta"], nombre=f"{xm}.jpg")
    return (r.get("documentos") or [{}])[0].get("documento_id") or documento_id, True


def _resumen_ficha(estado: int, cuerpo: dict, segundos: float) -> dict:
    meta, ficha = (cuerpo or {}).get("meta", {}), (cuerpo or {}).get("ficha", {})
    return {"estado_http": estado, "segundos": round(segundos, 3), "cache": meta.get("cache"), "ruta": meta.get("ruta"),
            "tiempo_ms": meta.get("tiempo_ms"), "traza_id": meta.get("traza_id"), "duplicado_de": meta.get("duplicado_de"),
            "estado_ficha": ficha.get("estado"), "texto_alternativo": ficha.get("texto_alternativo")}


def _buscar(c: ClienteEval, texto: str, objetivo: str | None = None, **opciones) -> dict:
    estado, cuerpo, seg = c.buscar(texto, **opciones)
    meta = (cuerpo or {}).get("meta", {})
    ids = [r["documento_id"] for r in (cuerpo or {}).get("resultados", [])]
    return {"estado_http": estado, "segundos": round(seg, 3), "cache": meta.get("cache"), "ruta": meta.get("ruta"),
            "tiempo_ms": meta.get("tiempo_ms"), "traza_id": meta.get("traza_id"), "ids": ids,
            "rango_objetivo": ids.index(objetivo) + 1 if objetivo in ids else None,
            "consulta_semantica": ((cuerpo or {}).get("consulta_interpretada") or {}).get("consulta_semantica")}


def _p50(valores: list[float]) -> float | None:
    return round(float(np.percentile(valores, 50)), 4) if valores else None


def _reduccion(sin: list[float], con: list[float]) -> dict:
    p_sin, p_con = _p50(sin), _p50(con)
    return {"sin_cache": percentiles(sin, "s"), "con_cache": percentiles(con, "s"),
            "reduccion_p50_porcentaje": round((p_sin - p_con) / p_sin * 100, 2) if p_sin and p_con is not None else None}


# ───────────────────────────── 1. fichas · caché exacta ─────────────────────────────
def fotos_exacta() -> list[str]:
    part = particiones()
    ocupadas = set(part["eval_fichas"]) | set(part.get("ajuste_prompts", [])) | set(part.get("aprendizaje", []))
    return _muestra(sorted(set(part["nuevas"]) - ocupadas), 50, "cache-exacta")


def cache_exacta(c: ClienteEval) -> tuple[dict, list[dict]]:
    fotos = fotos_exacta()
    subidas = asegurar_subidas(c, fotos)
    primeras, pares = Incremental("cache_exacta_primera"), Incremental("cache_exacta")
    version = c.version_configuracion()
    casos = []
    for i, xm in enumerate(fotos, start=1):
        previo = pares.obtener(xm)
        if previo:
            casos.append(previo)
            continue
        doc, resubida = _documento_vigente(c, xm, subidas[xm])
        primera = primeras.obtener(xm)
        if (primera is None or resubida or primera.get("version_configuracion") != version
                or primera.get("documento_id") != doc):
            estado, cuerpo, seg = c.ficha(doc)
            primera = primeras.guardar(xm, {"documento_id": doc, "version_configuracion": version,
                                            **_resumen_ficha(estado, cuerpo, seg)})
        caso = {"seccion": "fichas_exacta", "xm_id": xm, "documento_id": doc, "version_configuracion": version,
                "primera": {k: v for k, v in primera.items() if k not in ("clave", "documento_id", "version_configuracion")}}
        if primera["estado_http"] == 200:
            recarga = c.subir_foto(indice_xm()[xm]["ruta"], nombre=f"{xm}.jpg")
            d = (recarga.get("documentos") or [{}])[0]
            estado, cuerpo, seg = c.ficha(doc)
            caso.update(recarga_estado_http=recarga.get("estado_http"), recarga_ya_existia=d.get("ya_existia"),
                        recarga_mismo_documento=d.get("documento_id") == doc,
                        segunda=_resumen_ficha(estado, cuerpo, seg))
            caso["misma_ficha"] = caso["segunda"]["texto_alternativo"] == primera.get("texto_alternativo")
        casos.append(pares.guardar(xm, caso))
        registro(f"   caché exacta {i}/{len(fotos)}: 1ª {primera.get('cache')} {primera.get('segundos')} s · "
                 f"2ª {caso.get('segunda', {}).get('cache')} {caso.get('segunda', {}).get('segundos')} s")

    validas = [x for x in casos if x["primera"].get("estado_http") == 200 and x.get("segunda")]
    limpias = [x for x in validas if x["primera"].get("cache") == "ninguna"]
    cacheables = [x for x in limpias if x["primera"].get("ruta") != "degradada"]
    aciertos = [x for x in cacheables if x["segunda"].get("cache") == "exacta"]
    sin = [x["primera"]["segundos"] for x in cacheables]
    con = [x["segunda"]["segundos"] for x in aciertos]
    metricas = {
        "n": len(casos), "con_ficha_200": len(validas),
        "primera_ya_venia_de_cache": len(validas) - len(limpias),
        "primera_degradada_no_se_guarda": len(limpias) - len(cacheables),
        "cacheables": len(cacheables), "aciertos_exactos": len(aciertos),
        "tasa_aciertos_exactos": round(len(aciertos) / len(cacheables), 4) if cacheables else None,
        "recarga_devuelve_el_mismo_documento": sum(1 for x in validas if x.get("recarga_mismo_documento")),
        "misma_ficha_servida": sum(1 for x in aciertos if x.get("misma_ficha")),
        "latencia_cliente_s": _reduccion(sin, con),
        "latencia_servidor_ms": {"sin_cache": percentiles([x["primera"]["tiempo_ms"] for x in cacheables
                                                            if x["primera"].get("tiempo_ms") is not None], "ms"),
                                 "con_cache": percentiles([x["segunda"]["tiempo_ms"] for x in aciertos
                                                           if x["segunda"].get("tiempo_ms") is not None], "ms")},
        "rutas_de_la_primera": {r: sum(1 for x in limpias if x["primera"].get("ruta") == r)
                                for r in sorted({x["primera"].get("ruta") for x in limpias if x["primera"].get("ruta")})},
    }
    return metricas, casos


# ───────────────────────────── 2. fichas · caché semántica (τ_dup) ─────────────────────────────
def barrido_tau_dup(c: ClienteEval) -> tuple[dict, list[dict]]:
    from scripts.preparar_datos import PROCESADOS, slug
    emb = c.contenedor.embebedor
    z = np.load(PROCESADOS / f"emb_img_{slug(emb.nombre_modelo)}_{emb.lado_imagen_px}px.npz", allow_pickle=False)
    fila_de = {f"xm-{k}": i for i, k in enumerate(z["ids"].tolist())}
    archivo = [d for d in sorted(particiones()["archivo"]) if d in fila_de]
    posicion = {d: i for i, d in enumerate(archivo)}
    m_archivo = z["vectores"][[fila_de[d] for d in archivo]]
    pos = leer_conjunto("casi_duplicados_pos")["items"]
    neg = leer_conjunto("casi_duplicados_neg")["items"]
    pos, neg = pos[:tamano(len(pos))], neg[:tamano(len(neg))]

    inc = Incremental("cache_casi_duplicados_pos")
    pendientes = [it for it in pos if not inc.obtener(it["id"])]
    if pendientes:
        registro(f"   embeddings de {len(pendientes)} transformadas ({emb.nombre_modelo}, {emb.lado_imagen_px}px)")
    for i in range(0, len(pendientes), LOTE_EMBEDDINGS):
        lote = pendientes[i:i + LOTE_EMBEDDINGS]
        t0 = time.perf_counter()
        vectores = emb.embeber_imagenes([(DATA / it["archivo"]).read_bytes() for it in lote])
        por_imagen = (time.perf_counter() - t0) / len(lote)
        for it, v in zip(lote, vectores):
            sims = m_archivo @ np.asarray(v, dtype=np.float32)
            orden = np.argsort(-sims)[:2]
            inc.guardar(it["id"], {"origen": it["origen"], "tipo": it["transformacion"]["tipo"],
                                   "sim_origen": round(float(sims[posicion[it["origen"]]]), 6),
                                   "top1_id": archivo[int(orden[0])], "top1_sim": round(float(sims[orden[0]]), 6),
                                   "top2_sim": round(float(sims[orden[1]]), 6), "segundos_embedding": round(por_imagen, 3)})
        if (i // LOTE_EMBEDDINGS + 1) % 10 == 0:
            registro(f"   {min(i + LOTE_EMBEDDINGS, len(pendientes))}/{len(pendientes)} transformadas")
    positivos = [inc.obtener(it["id"]) for it in pos]
    P, N = len(positivos), len(neg)

    def fila(tau: float) -> dict:
        aciertos = [p for p in positivos if p["top1_sim"] >= tau]
        correctos = sum(1 for p in aciertos if p["top1_id"] == p["origen"])
        incorrectos_pos = len(aciertos) - correctos
        servidas_neg = sum(1 for n in neg if n["similitud"] >= tau)
        servidas = correctos + incorrectos_pos + servidas_neg
        return {"tau": tau, "aciertos_positivos": len(aciertos), "tasa_aciertos_positivos": round(len(aciertos) / P, 4),
                "aciertos_correctos": correctos, "recall": round(correctos / P, 4),
                "aciertos_con_otra_foto_en_positivos": incorrectos_pos,
                "respuestas_incorrectas_servidas_negativos": servidas_neg, "fpr": round(servidas_neg / N, 4),
                "precision": round(correctos / servidas, 4) if servidas else None}

    barrido = [fila(t) for t in TAUS]
    cumplen = [f for f in barrido if f["fpr"] <= FPR_MAX]
    if cumplen:
        elegido = max(cumplen, key=lambda f: (f["recall"], -f["fpr"], f["tau"]))
        criterio = f"máximo recall con FPR ≤ {FPR_MAX:.0%} (empates: menor FPR y luego τ más alto)"
    else:
        elegido = min(barrido, key=lambda f: (f["fpr"], -f["recall"]))
        criterio = f"ningún τ del barrido cumple FPR ≤ {FPR_MAX:.0%}: se reporta el de menor FPR y se debe revisar"
    tau_actual = float(c.config.parametro("cache.fichas.tau_dup", 0.97))
    por_tipo = {}
    for tipo in sorted({p["tipo"] for p in positivos}):
        grupo = [p for p in positivos if p["tipo"] == tipo]
        por_tipo[tipo] = {"n": len(grupo),
                          "recall_en_tau_elegido": round(sum(p["top1_sim"] >= elegido["tau"] and p["top1_id"] == p["origen"]
                                                             for p in grupo) / len(grupo), 4),
                          "recall_en_tau_configurado": round(sum(p["top1_sim"] >= tau_actual and p["top1_id"] == p["origen"]
                                                                 for p in grupo) / len(grupo), 4),
                          "sim_origen_p50": round(float(np.percentile([p["sim_origen"] for p in grupo], 50)), 4)}
    metricas = {
        "n_positivos": P, "n_negativos": N, "barrido": barrido, "tau_elegido": elegido["tau"], "criterio": criterio,
        "en_tau_elegido": elegido, "tau_configurado": tau_actual, "en_tau_configurado": fila(tau_actual),
        "por_transformacion": por_tipo,
        "similitud_positivos_con_su_original": percentiles([p["sim_origen"] for p in positivos], "coseno"),
        "similitud_negativos_con_su_vecino": percentiles([n["similitud"] for n in neg], "coseno"),
        "positivos_cuyo_vecino_mas_cercano_no_es_el_original": sum(1 for p in positivos if p["top1_id"] != p["origen"]),
        "latencia_embedding_imagen": percentiles([p["segundos_embedding"] for p in positivos], "s"),
        "metodo": "positivos: vecino más cercano de cada transformada entre las fotos del archivo (embedding de imagen "
                  "del mismo adaptador del servicio); negativos: similitud de cada foto con su vecino distinto más "
                  "cercano, según el conjunto. Así se reproduce la caché semántica de fichas, que sirve la ficha de la "
                  "foto más parecida si su coseno ≥ τ_dup.",
        "nota": "τ elegido para ADR-04; aplicarlo en la configuración lo decide la sesión principal.",
    }
    detalle = [{"seccion": "tau_dup_positivo", "id": it["id"], **{k: v for k, v in p.items() if k != "clave"}}
               for it, p in zip(pos, positivos)]
    detalle += [{"seccion": "tau_dup_negativo", "id": n["id"], "origen": n["origen"], "vecino": n["vecino"],
                 "similitud": n["similitud"]} for n in neg]
    return metricas, detalle


# ───────────────────────────── 3. búsquedas ─────────────────────────────
def cache_busquedas(c: ClienteEval) -> tuple[dict, list[dict]]:
    regs = indice_xm()
    candidatas = [x for x in particiones()["archivo"]
                  if len(regs[x]["es"]) >= 2 and all(2 <= len(t.strip()) <= 300 for t in regs[x]["es"][:2])]
    fotos = _muestra(candidatas, 30, "cache-busquedas")
    tau_busq = float(c.config.parametro("cache.busquedas.tau_busq", 0.95))
    emb = c.contenedor.embebedor
    inc = Incremental("cache_busquedas")
    casos = []
    for i, xm in enumerate(fotos, start=1):
        previo = inc.obtener(xm)
        if previo:
            casos.append(previo)
            continue
        a, b = regs[xm]["es"][0].strip(), regs[xm]["es"][1].strip()
        va, vb = emb.embeber_textos([a, b], rol="consulta")   # los mismos vectores que compara la caché semántica
        caso = {"seccion": "busquedas", "xm_id": xm, "consulta_a": a, "consulta_b": b,
                "similitud_a_b": round(float(np.dot(va, vb)), 4)}
        caso["a1"] = _buscar(c, a, objetivo=xm)
        caso["a2"] = _buscar(c, a, objetivo=xm)
        caso["b"] = _buscar(c, b, objetivo=xm)
        caso["b_fresca"] = _buscar(c, b, objetivo=xm, sin_cache=True) if caso["b"]["cache"] == "semantica" else None
        if caso["b_fresca"]:
            servida, fresca = caso["b"], caso["b_fresca"]
            # La entrada de A guarda la respuesta de A: si la servida no es esa, vino de la entrada de otra consulta.
            otra_entrada = (servida["ids"] != caso["a1"]["ids"]
                            or servida["consulta_semantica"] != caso["a1"]["consulta_semantica"])
            perdio_objetivo = fresca["rango_objetivo"] is not None and servida["rango_objetivo"] is None
            union = set(servida["ids"]) | set(fresca["ids"])
            caso.update(semantica_de_otra_consulta=otra_entrada, semantica_pierde_la_foto=perdio_objetivo,
                        respuesta_incorrecta_servida=otra_entrada or perdio_objetivo,
                        jaccard_servida_fresca=round(len(set(servida["ids"]) & set(fresca["ids"])) / len(union), 4) if union else None)
        casos.append(inc.guardar(xm, caso))
        registro(f"   búsquedas {i}/{len(fotos)}: A {caso['a1']['cache']}→{caso['a2']['cache']} · B {caso['b']['cache']}")

    ok = [x for x in casos if all(x[k]["estado_http"] == 200 for k in ("a1", "a2", "b"))]
    limpias = [x for x in ok if x["a1"]["cache"] == "ninguna"]
    exactas = [x for x in limpias if x["a2"]["cache"] == "exacta"]
    semanticas = [x for x in ok if x["b"]["cache"] == "semantica"]
    incorrectas = [x for x in semanticas if x.get("respuesta_incorrecta_servida")]
    sims = [x["similitud_a_b"] for x in ok]
    sin = [x["a1"]["segundos"] for x in limpias] + [x["b"]["segundos"] for x in ok if x["b"]["cache"] == "ninguna"]
    metricas = {
        "n": len(casos), "sin_error": len(ok), "tau_busq": tau_busq,
        "repetidas": {"n": len(limpias), "primera_ya_venia_de_cache": len(ok) - len(limpias),
                      "aciertos_exactos": len(exactas),
                      "tasa_aciertos": round(len(exactas) / len(limpias), 4) if limpias else None},
        "parafraseadas": {"n": len(ok), "aciertos_semanticos": len(semanticas),
                          "tasa_aciertos": round(len(semanticas) / len(ok), 4) if ok else None,
                          "aciertos_exactos_por_normalizacion": sum(1 for x in ok if x["b"]["cache"] == "exacta"),
                          "respuestas_incorrectas_servidas": len(incorrectas),
                          "tasa_incorrectas_sobre_aciertos": round(len(incorrectas) / len(semanticas), 4) if semanticas else None,
                          "tasa_incorrectas_sobre_consultas": round(len(incorrectas) / len(ok), 4) if ok else None,
                          "similitud_a_b": percentiles(sims, "coseno"),
                          "pares_con_similitud_mayor_o_igual_a_tau_busq": sum(1 for s in sims if s >= tau_busq),
                          "definicion_incorrecta": "el acierto viene de la entrada de otra consulta, o la búsqueda fresca "
                                                   "de B encuentra la foto en el top-k y la respuesta servida no"},
        "encuentra_la_foto_top_k": {"a_sin_cache": sum(1 for x in limpias if x["a1"]["rango_objetivo"]),
                                    "b": sum(1 for x in ok if x["b"]["rango_objetivo"]),
                                    "nota": "las consultas son descripciones de fotos del archivo (la 1ª es la descripción "
                                            "indexada de su ficha): sirve para juzgar la respuesta servida por la caché, no "
                                            "la calidad de la búsqueda"},
        "latencia_cliente_s": {"exacta": _reduccion(sin, [x["a2"]["segundos"] for x in exactas]),
                               "semantica": _reduccion(sin, [x["b"]["segundos"] for x in semanticas])},
        "rutas_sin_cache": {r: sum(1 for x in limpias if x["a1"]["ruta"] == r)
                            for r in sorted({x["a1"]["ruta"] for x in limpias if x["a1"]["ruta"]})},
    }
    detalle = [{k: v for k, v in x.items() if k != "clave"} for x in casos]
    return metricas, detalle


# ───────────────────────────── 5. invalidación ─────────────────────────────
def invalidacion(c: ClienteEval, casos_exacta: list[dict]) -> dict:
    from fototeca.cache.claves import clave_ficha
    from fototeca.dominio import colecciones as col
    inc = Incremental("cache_invalidacion")
    previo = inc.obtener("prueba")
    if previo and not previo.get("error"):
        return previo
    candidatos = [x for x in casos_exacta if (x.get("segunda") or {}).get("cache") == "exacta"]
    if not candidatos:
        return {"estado": "pendiente: ninguna foto quedó en la caché exacta"}
    xm = candidatos[0]["xm_id"]
    doc, _ = _documento_vigente(c, xm, candidatos[0]["documento_id"])
    version = c.version_configuracion()
    p = {"xm_id": xm, "documento_id": doc, "version_configuracion": version}
    try:
        # Antes: la ficha responde desde la caché exacta (si cambió la versión, la 1ª petición la vuelve a guardar).
        estado, cuerpo, _ = c.ficha(doc)
        if (cuerpo.get("meta") or {}).get("cache") != "exacta":
            estado, cuerpo, _ = c.ficha(doc)
        p["ficha_antes"] = (cuerpo.get("meta") or {}).get("cache")
        sha = hashlib.sha256(c.contenedor.almacen_documentos.obtener_foto(doc)).hexdigest()
        clave = clave_ficha(sha, version)
        p["entrada_en_almacen_antes"] = c.contenedor.almacen_cache.obtener(clave) is not None
        vector = c.contenedor.almacen_vectorial.obtener_vectores(col.FOTOS_IMG, [doc]).get(doc)
        consulta = " ".join(indice_xm()[xm]["es"][0].split()[:8])
        p["consulta"] = consulta
        p["busqueda_1"] = _buscar(c, consulta)["cache"]
        p["busqueda_2_antes"] = _buscar(c, consulta)["cache"]
        # Eliminación por la API
        r = c.http.delete(f"/documentos/{doc}")
        cuerpo_del = r.json()
        p.update(eliminar_estado_http=r.status_code,
                 entradas_cache_invalidadas=cuerpo_del.get("entradas_cache_invalidadas"),
                 version_archivo_despues=cuerpo_del.get("version_archivo"))
        # Después: la entrada no responde
        p["entrada_en_almacen_despues"] = c.contenedor.almacen_cache.obtener(clave) is not None
        p["exacta_responde_despues"] = c.contenedor.cache_fichas.exacta(sha, version) is not None
        semantica = c.contenedor.cache_fichas.semantica(vector, version, None) if vector is not None else None
        p["semantica_responde_con_la_foto_eliminada"] = bool(semantica and (semantica.respuesta or {}).get("documento_id") == doc)
        p["busqueda_despues"] = _buscar(c, consulta)["cache"]
        # Por la API: se vuelve a cargar la misma foto y se pide su ficha → no debe venir de la caché exacta
        sub = c.subir_foto(indice_xm()[xm]["ruta"], nombre=f"{xm}.jpg")
        doc2 = (sub.get("documentos") or [{}])[0].get("documento_id")
        estado3, cuerpo3, seg3 = c.ficha(doc2) if doc2 else (None, {}, 0.0)
        meta3 = cuerpo3.get("meta") or {}
        p.update(recarga_documento_id=doc2, ficha_despues_estado_http=estado3, ficha_despues_cache=meta3.get("cache"),
                 ficha_despues_duplicado_de=meta3.get("duplicado_de"), ficha_despues_segundos=round(seg3, 3))
        # Un acierto semántico con OTRA foto parecida sería legítimo; lo que no debe pasar es que responda la entrada
        # eliminada (acierto exacto, o semántico que apunte a la propia foto).
        p["ficha_despues_no_viene_de_la_entrada_eliminada"] = bool(
            estado3 == 200 and p["ficha_despues_cache"] != "exacta"
            and (p["ficha_despues_cache"] != "semantica" or (p["ficha_despues_duplicado_de"] or {}).get("documento_id") != doc))
        p["aprobada"] = bool(p["ficha_antes"] == "exacta" and p["entrada_en_almacen_antes"]
                             and p["eliminar_estado_http"] == 200 and (p["entradas_cache_invalidadas"] or 0) >= 1
                             and not p["entrada_en_almacen_despues"] and not p["exacta_responde_despues"]
                             and not p["semantica_responde_con_la_foto_eliminada"]
                             and p["busqueda_2_antes"] in ("exacta", "semantica") and p["busqueda_despues"] == "ninguna"
                             and p["ficha_despues_no_viene_de_la_entrada_eliminada"])
    except Exception as e:  # noqa: BLE001 — la prueba queda registrada como fallida, con la causa
        p["error"] = f"{type(e).__name__}: {e}"[:300]
        p["aprobada"] = False
    registro(f"   invalidación: {'aprobada' if p.get('aprobada') else 'NO aprobada'}")
    return inc.guardar("prueba", p)


# ───────────────────────────── gráficas ─────────────────────────────
def graficas(semantica: dict, exacta: dict, busquedas: dict) -> None:
    pyplot = plt()
    fig, (ax1, ax2) = pyplot.subplots(1, 2, figsize=(10, 3.8))
    b = semantica["barrido"]
    taus = [f["tau"] for f in b]
    ax1.plot(taus, [f["tasa_aciertos_positivos"] for f in b], color=PALETA["azul"], lw=2, marker="o", ms=4,
             label="aciertos sobre positivos")
    ax1.plot(taus, [f["recall"] for f in b], color=PALETA["aqua"], lw=2, marker="o", ms=4, label="recall (foto original)")
    ax1.plot(taus, [f["fpr"] for f in b], color=PALETA["naranja"], lw=2, marker="o", ms=4,
             label="FPR (incorrectas servidas en negativos)")
    ax1.axhline(FPR_MAX, color=PALETA["gris"], lw=1, ls="--")
    ax1.axvline(semantica["tau_elegido"], color=PALETA["gris"], lw=1, ls=":")
    ax1.text(semantica["tau_elegido"], 1.02, f"τ elegido = {semantica['tau_elegido']}", ha="center", fontsize=8)
    ax1.set_ylim(0, 1.08)
    ax1.set_xlabel("τ_dup")
    ax1.set_ylabel("Proporción")
    ax1.set_title(f"Barrido de τ_dup (positivos={semantica['n_positivos']}, negativos={semantica['n_negativos']})", fontsize=9)
    ax1.legend(fontsize=7, frameon=False, loc="center left")
    puntos = [f for f in b if f["precision"] is not None]
    ax2.plot([f["recall"] for f in puntos], [f["precision"] for f in puntos], color=PALETA["azul"], lw=2, marker="o", ms=4)
    for f in puntos:
        if f["tau"] in (taus[0], semantica["tau_elegido"], taus[-1]):
            ax2.annotate(f"τ={f['tau']}", (f["recall"], f["precision"]), textcoords="offset points", xytext=(4, -10), fontsize=7)
    ax2.set_xlim(0, 1.02)
    ax2.set_ylim(0, 1.05)
    ax2.set_xlabel("Recall")
    ax2.set_ylabel("Precisión")
    ax2.set_title("Precisión contra recall de la caché semántica de fichas", fontsize=9)
    guardar_grafica("cache_tau_dup", fig)

    grupos = [("Fichas (caché exacta)", exacta["latencia_cliente_s"]),
              ("Búsquedas (exacta)", busquedas["latencia_cliente_s"]["exacta"]),
              ("Búsquedas (semántica)", busquedas["latencia_cliente_s"]["semantica"])]
    grupos = [(n, d) for n, d in grupos if d["sin_cache"].get("n") and d["con_cache"].get("n")]
    if not grupos:
        return
    fig, ax = pyplot.subplots(figsize=(7, 3.4))
    x = np.arange(len(grupos))
    sin = [d["sin_cache"]["p50_s"] for _, d in grupos]
    con = [d["con_cache"]["p50_s"] for _, d in grupos]
    ax.bar(x - 0.2, sin, width=0.38, color=PALETA["naranja"], edgecolor="white", linewidth=1, label="sin caché (p50)")
    ax.bar(x + 0.2, con, width=0.38, color=PALETA["azul"], edgecolor="white", linewidth=1, label="con caché (p50)")
    for i, (_, d) in enumerate(grupos):
        if d["reduccion_p50_porcentaje"] is not None:
            ax.text(i, max(sin[i], con[i]) * 1.15, f"−{d['reduccion_p50_porcentaje']}%", ha="center", fontsize=8)
    ax.set_yscale("log")
    ax.set_xticks(x, [n for n, _ in grupos], fontsize=8)
    ax.set_ylabel("Segundos (escala logarítmica)")
    ax.set_title("Latencia con y sin caché (p50, medida en el cliente)")
    ax.legend(fontsize=8, frameon=False)
    guardar_grafica("cache_latencia", fig)


# ───────────────────────────── principal ─────────────────────────────
def ejecutar(c: ClienteEval) -> dict:
    registro("caché · τ_dup (casi duplicados)")
    semantica, detalle_sem = barrido_tau_dup(c)
    registro(f"   τ_dup elegido: {semantica['tau_elegido']} ({semantica['criterio']})")
    registro("caché · búsquedas repetidas y parafraseadas")
    busquedas, detalle_bus = cache_busquedas(c)
    registro("caché · fichas: cargas repetidas idénticas")
    exacta, detalle_ex = cache_exacta(c)
    registro("caché · invalidación")
    prueba = invalidacion(c, detalle_ex)

    metas = yaml.safe_load((Path(c.config.rutas["config"]) / "metas_calidad.yaml").read_text(encoding="utf-8"))
    meta_incorrectas = (metas.get("cache_semantica") or {}).get("incorrectas_desde_cache_max")
    meta_cache_p50 = (metas.get("latencia_s") or {}).get("ficha_cache_p50")
    p50_cache = exacta["latencia_cliente_s"]["con_cache"].get("p50_s")
    comparacion = {
        "incorrectas_desde_cache_max": {
            "meta": meta_incorrectas,
            "medido_fichas_fpr_en_tau_elegido": semantica["en_tau_elegido"]["fpr"],
            "medido_fichas_fpr_en_tau_configurado": semantica["en_tau_configurado"]["fpr"],
            "medido_busquedas_incorrectas_sobre_consultas": busquedas["parafraseadas"]["tasa_incorrectas_sobre_consultas"],
            "cumple_fichas_en_tau_elegido": None if meta_incorrectas is None else semantica["en_tau_elegido"]["fpr"] <= meta_incorrectas},
        "ficha_cache_p50_s": {"meta": meta_cache_p50, "medido": p50_cache,
                              "cumple": None if meta_cache_p50 is None or p50_cache is None else p50_cache <= meta_cache_p50},
    }
    metricas = {"fichas_exacta": exacta, "fichas_semantica_tau_dup": semantica, "busquedas": busquedas,
                "invalidacion": prueba, "metas": comparacion}
    graficas(semantica, exacta, busquedas)
    detalle = ([{"seccion": "fichas_exacta", **{k: v for k, v in x.items() if k not in ("clave", "seccion")}} for x in detalle_ex]
               + detalle_sem + detalle_bus + [{"seccion": "invalidacion", **{k: v for k, v in prueba.items() if k != "clave"}}])
    configuracion = {"tau_dup_configurado": semantica["tau_configurado"], "tau_busq": busquedas["tau_busq"],
                     "taus_barridos": TAUS, "fpr_max": FPR_MAX, "ttl_fichas_s": c.config.parametro("cache.fichas.ttl_s"),
                     "ttl_busquedas_s": c.config.parametro("cache.busquedas.ttl_s"),
                     "fotos_cache_exacta": len(detalle_ex), "busquedas": busquedas["n"]}
    guardar_resultado("cache", metricas, detalle, configuracion, c)
    return metricas


if __name__ == "__main__":
    ejecutar(ClienteEval())
