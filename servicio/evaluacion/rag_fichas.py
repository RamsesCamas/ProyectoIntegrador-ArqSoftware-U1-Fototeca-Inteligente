"""Resultados del producto con RAG: con RAG contra sin RAG, acierto@5 de la recuperación de ejemplos, fidelidad
al contexto y plantilla de revisión manual.

1. Con RAG (el flujo de producción, con su enrutador) contra sin RAG (`sin_rag=true`) sobre `eval_fichas` (60
   fotos; referencia: las descripciones en español de XM3600 y las etiquetas humanas de Open Images): juez P7,
   similitud granite, chrF, recall de palabras clave contra Open Images, % de campos con fuente válida y fidelidad
   al contexto. Todo por la API (POST /fichas), reanudable caso por caso.
2. Acierto@5 de la recuperación de ejemplos para cada foto de `nuevas` («normales») y de `regiones_excluidas`, con
   el mismo recuperador del servicio (sin modelos de lenguaje).
3. `revision_manual/plantilla_fichas.csv`: 20 fichas con RAG al azar (semilla 2026) para la calificación humana.
   No se sobrescribe si el autor ya escribió calificaciones.

Métodos (quedan también en el JSON, clave `metodos`):
- Recall de palabras clave: cada etiqueta de Open Images de la foto (inglés) cuenta como recuperada si alguna
  palabra clave de la ficha (español) tiene coseno granite ≥ τ con ella. τ se calibra con pares de traducción: las
  etiquetas de Open Images que coinciden exactamente en inglés con un concepto del tesauro (prefLabel/altLabel@en)
  frente a la etiqueta en español de ese concepto (positivos) y frente a la de otro concepto al azar (negativos); τ
  maximiza TPR − FPR. granite es multilingüe e independiente del embebedor con el que el sistema normaliza al
  tesauro. Cifra secundaria: recall exacto vía el tesauro (la URI de la palabra clave tiene esa etiqueta en inglés).
- Campos con fuente válida: de los campos con texto entre titular, descripción y texto alternativo (los que revisa
  el guardrail `fuentes`), los que conservan al menos una fuente tras quitar los ids que no estaban en el contexto.
- Fidelidad al contexto: citas válidas / (válidas + inválidas). Válidas: las fuentes que la respuesta conserva por
  campo (en `palabras_clave` se descuentan las que agrega la normalización al tesauro); inválidas:
  `invalidas_quitadas` del guardrail `fuentes`. Para el tesauro solo hay cota inferior: las inválidas no traen tipo.
- Acierto@5: un vecino es «semánticamente cercano» si la similitud granite entre su descripción validada y la
  referencia de la foto (máximo sobre sus descripciones humanas en español) es ≥ al percentil 75 de esa misma
  similitud contra TODAS las fichas validadas (el universo del que elige el recuperador). Se reportan también el
  percentil 90, el acierto@1 y la probabilidad de acierto con 5 fichas tomadas al azar.

    python -m evaluacion.rag_fichas [--rapido]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
from collections import Counter
from pathlib import Path

import numpy as np

from evaluacion.calidad import CONFIGURACIONES, indice_xm, intervalo_bootstrap, juez, referencias, resumen_numerico
from evaluacion.comun import (DATA, REVISION, SEMILLA, ClienteEval, Incremental, guardar_grafica, guardar_resultado,
                              particiones, registro, tamano)
from evaluacion.r3_modelos import (Avance, agregar, barras, caso, diferencia_pareada, escribir_csv,
                                   eval_fichas_muestra, exigir_servicios, fila_csv, generar, leyenda_comun, media,
                                   nueva_figura, subir)
from fototeca.dominio import colecciones as col

CONFIGS_RAG = ("con_rag", "sin_rag")
NOMBRE = {"con_rag": "Con RAG", "sin_rag": "Sin RAG"}
CAMPOS_FUENTE = ("titular", "descripcion", "texto_alternativo")
PERCENTILES = (75, 90)
K_VECINOS = 5
COLUMNAS_PLANTILLA = ["xm_id", "documento_id", "archivo_imagen", "referencias", "titular", "texto_alternativo",
                      "descripcion", "palabras_clave", "estado_ficha", "ruta", "juez_fidelidad", "juez_relevancia",
                      "juez_justificacion", "humano_fidelidad (0-5)", "humano_relevancia (0-5)", "comentario"]
METODOS = {
    "recall_palabras_clave_oi": "etiqueta de Open Images (inglés) recuperada si alguna palabra clave (español) tiene "
                                "coseno granite ≥ τ; τ calibrado con pares de traducción del tesauro (máximo TPR − FPR)",
    "recall_exacto_tesauro": "la URI de alguna palabra clave tiene la etiqueta de Open Images en inglés",
    "campos_con_fuente_valida": "campos con texto (titular, descripción, texto alternativo) que conservan ≥1 fuente "
                                "tras quitar los ids que no estaban en el contexto",
    "fidelidad_contexto": "citas válidas / (válidas + `invalidas_quitadas` del guardrail `fuentes`); para el tesauro "
                          "solo cota inferior (las inválidas no traen tipo)",
    "acierto@5": "algún vecino con similitud granite (descripción validada vs. referencia en español, máximo sobre "
                 "referencias) ≥ percentil 75 de esa similitud contra todas las fichas validadas",
    "ficha_vacia": "error HTTP o ficha degradada: calidad 0, recall 0 y sin citas",
}


# ───────────────────────────── datos ─────────────────────────────
def vectores_imagen_xm(c: ClienteEval) -> dict[str, np.ndarray]:
    """Embeddings de imagen de todas las fotos de XM3600 (los mismos que indexó el archivo), de la preparación."""
    from scripts.preparar_datos import PROCESADOS, slug
    e = c.contenedor.embebedor
    z = np.load(PROCESADOS / f"emb_img_{slug(e.nombre_modelo)}_{e.lado_imagen_px}px.npz", allow_pickle=False)
    return {f"xm-{k}": v for k, v in zip(z["ids"].tolist(), z["vectores"])}


def etiquetas_open_images() -> dict[str, list[str]]:
    """xm_id → nombres (inglés) de las etiquetas humanas positivas de Open Images."""
    from scripts.preparar_datos import PROCESADOS
    ruta = PROCESADOS / "oi_etiquetas_por_imagen.json"
    if not ruta.exists():
        return {}
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    return {f"xm-{k}": sorted({e["nombre"] for e in v if e.get("nombre")}) for k, v in datos.items()}


# ───────────────────────────── cruce de idiomas ─────────────────────────────
class CruceIdiomas:
    """Etiqueta de Open Images (inglés) ↔ palabra clave de la ficha (español) con el coseno de granite."""

    def __init__(self, c: ClienteEval):
        self.embebedor = c.contenedor.embebedor_secundario
        self._memo: dict[str, np.ndarray] = {}
        ruta = DATA / "corpus" / "tesauro.jsonl"
        self.conceptos = [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()] \
            if ruta.exists() else []
        self.ingles_por_uri = {x["uri"]: {e.lower() for e in x.get("etiquetas_en", [])} for x in self.conceptos}

    def vectores(self, textos: list[str]) -> np.ndarray:
        faltan = sorted({t for t in textos if t not in self._memo})
        if faltan:
            for t, v in zip(faltan, self.embebedor.embeber_textos(faltan)):
                self._memo[t] = v
        return np.stack([self._memo[t] for t in textos])

    def _similitudes(self, pares: list[tuple[str, str]]) -> np.ndarray:
        return np.sum(self.vectores([a for a, _ in pares]) * self.vectores([b for _, b in pares]), axis=1)

    def calibrar(self, nombres_oi: list[str], n_max: int = 300) -> dict:
        por_en: dict[str, dict] = {}
        for x in self.conceptos:
            for e in x.get("etiquetas_en", []):
                por_en.setdefault(e.lower(), x)
        pares = [(n, por_en[n.lower()]) for n in sorted(set(nombres_oi)) if n.lower() in por_en]
        origen = ("etiquetas de Open Images con coincidencia exacta en inglés con un concepto del tesauro "
                  "(prefLabel/altLabel@en) frente a la etiqueta en español de ese concepto")
        if len(pares) < 30:
            pares = [(x["etiquetas_en"][0], x) for x in self.conceptos if x.get("etiquetas_en") and x.get("etiqueta_es")]
            origen = "pares inglés–español de los conceptos del tesauro (prefLabel@en frente a prefLabel@es)"
        if len({x["uri"] for _, x in pares}) < 2:
            return {"umbral": None, "pendiente": "no hay pares de traducción suficientes para calibrar el umbral"}
        rng = random.Random(SEMILLA)
        muestra = rng.sample(pares, min(n_max, len(pares)))
        if len({x["uri"] for _, x in muestra}) < 2:
            muestra = pares
        positivos = [(en, x["etiqueta_es"]) for en, x in muestra]
        negativos = []
        for en, x in muestra:
            otro = rng.choice(muestra)[1]
            while otro["uri"] == x["uri"]:
                otro = rng.choice(muestra)[1]
            negativos.append((en, otro["etiqueta_es"]))
        s_pos, s_neg = self._similitudes(positivos), self._similitudes(negativos)

        def youden(u: float) -> float:
            return float(np.mean(s_pos >= u) - np.mean(s_neg >= u))

        mejor = max((float(u) for u in np.unique(np.concatenate([s_pos, s_neg]))), key=lambda u: (youden(u), u))
        tau = round(mejor, 4)
        return {"umbral": tau, "tpr": round(float(np.mean(s_pos >= tau)), 4), "fpr": round(float(np.mean(s_neg >= tau)), 4),
                "youden_j": round(youden(tau), 4), "n_positivos": len(positivos), "n_negativos": len(negativos),
                "origen_pares": origen, "modelo": self.embebedor.nombre_modelo,
                "similitud_positivos": resumen_numerico(s_pos.tolist()),
                "similitud_negativos": resumen_numerico(s_neg.tolist()),
                "regla": "τ maximiza TPR − FPR (índice de Youden); en empate, el τ mayor"}

    def recall(self, etiquetas: list[str], palabras: list[str], umbral: float) -> dict:
        if not palabras:
            return {"recall": 0.0, "recuperadas": []}
        mejor = (self.vectores(etiquetas) @ self.vectores(palabras).T).max(axis=1)
        recuperadas = [e for e, v in zip(etiquetas, mejor) if v >= umbral]
        return {"recall": round(len(recuperadas) / len(etiquetas), 4), "recuperadas": recuperadas}

    def recall_exacto(self, etiquetas: list[str], palabras: list[dict]) -> float:
        ingles = set().union(*[self.ingles_por_uri.get(p.get("uri"), set()) for p in palabras if p.get("uri")])
        return round(sum(1 for e in etiquetas if e.lower() in ingles) / len(etiquetas), 4)


# ───────────────────────────── fuentes y fidelidad al contexto ─────────────────────────────
def metricas_fuentes(cuerpo: dict) -> dict:
    ficha = cuerpo.get("ficha") or {}
    fuentes = cuerpo.get("fuentes") or {}
    presentes = [k for k in CAMPOS_FUENTE if (ficha.get(k) or "").strip()]
    con_fuente = [k for k in presentes if fuentes.get(k)]
    salida_g = ((cuerpo.get("meta") or {}).get("guardrails") or {}).get("salida") or []
    g = next((x for x in reversed(salida_g) if x.get("verificacion") == "fuentes"), None)
    base = {"campos_presentes": len(presentes), "campos_con_fuente": len(con_fuente),
            "guardrail_fuentes": (g or {}).get("resultado")}
    if g is None:       # la salida del modelo no llegó a la verificación de fuentes (p. ej. ficha degradada)
        return {**base, "citas_validas": None, "citas_invalidas": None, "citas_validas_por_tipo": {}}
    normalizadas = sum(1 for p in ficha.get("palabras_clave") or [] if p.get("uri"))
    por_tipo: Counter = Counter()
    for campo, lista in fuentes.items():
        lista = lista or []
        if campo == "palabras_clave":   # al final van las que agrega la normalización al tesauro, no el modelo
            lista = lista[:max(0, len(lista) - normalizadas)]
        por_tipo.update(str(f.get("tipo")) for f in lista)
    invalidas = (g.get("detalle") or {}).get("invalidas_quitadas")
    if invalidas is None:
        invalidas = g.get("valor") or 0
    return {**base, "citas_validas": sum(por_tipo.values()), "citas_invalidas": int(invalidas),
            "citas_validas_por_tipo": dict(por_tipo)}


def caso_rag(c: ClienteEval, config: str, xm_id: str, reg: dict, etiquetas: dict, cruce: CruceIdiomas,
             umbral: float | None) -> dict:
    base = caso(c, config, xm_id, reg)
    ficha = base.get("ficha")
    fuentes = metricas_fuentes(reg.get("respuesta") or {}) if ficha else {
        "campos_presentes": 0, "campos_con_fuente": 0, "guardrail_fuentes": None, "citas_validas": None,
        "citas_invalidas": None, "citas_validas_por_tipo": {}}
    palabras = (ficha or {}).get("palabras_clave") or []
    terminos = [p["termino"] for p in palabras if p.get("termino")]
    oi = etiquetas.get(xm_id) or []
    r = cruce.recall(oi, terminos, umbral) if (oi and umbral is not None) else None
    return {**base, **fuentes, "palabras_clave": terminos, "oi_etiquetas": oi,
            "recall_oi": r["recall"] if r else None, "oi_recuperadas": r["recuperadas"] if r else None,
            "recall_oi_exacto_tesauro": cruce.recall_exacto(oi, palabras) if oi else None}


def agregar_rag(casos: list[dict]) -> dict:
    con_dato = [x for x in casos if x.get("citas_validas") is not None]
    validas = sum(x["citas_validas"] for x in con_dato)
    invalidas = sum(x.get("citas_invalidas") or 0 for x in con_dato)
    por_tipo: Counter = Counter()
    for x in con_dato:
        por_tipo.update(x.get("citas_validas_por_tipo") or {})
    presentes = sum(x.get("campos_presentes") or 0 for x in casos)
    con_fuente = sum(x.get("campos_con_fuente") or 0 for x in casos)
    con_oi = [x for x in casos if x.get("recall_oi") is not None]
    recall = [x["recall_oi"] for x in con_oi]
    total_oi = sum(len(x["oi_etiquetas"]) for x in con_oi)
    tes = por_tipo.get("tesauro", 0)
    return {
        **agregar(casos),
        "campos_con_fuente_valida": {"tasa": round(con_fuente / presentes, 4) if presentes else None,
                                     "campos_con_texto": presentes, "campos_con_fuente": con_fuente},
        "fidelidad_contexto": {"tasa": round(validas / (validas + invalidas), 4) if validas + invalidas else None,
                               "citas_validas": validas, "citas_invalidas": invalidas, "fichas_con_dato": len(con_dato),
                               "citas_validas_por_tipo": dict(por_tipo),
                               "tesauro_cota_inferior": round(tes / (tes + invalidas), 4) if tes + invalidas else None},
        "recall_palabras_clave_oi": {**resumen_numerico(recall), "ic95": intervalo_bootstrap(recall),
                                     "micro": round(sum(len(x.get("oi_recuperadas") or []) for x in con_oi) / total_oi, 4)
                                     if total_oi else None, "fotos_con_etiquetas": len(con_oi)},
        "recall_palabras_clave_oi_exacto_tesauro": resumen_numerico([x.get("recall_oi_exacto_tesauro") for x in con_oi]),
        "palabras_clave_por_ficha": resumen_numerico([len(x.get("palabras_clave") or []) for x in casos if x.get("ficha")]),
    }


# ───────────────────────────── acierto@5 de la recuperación de ejemplos ─────────────────────────────
class CriterioVecinos:
    """«Vecino semánticamente cercano»: similitud granite entre la descripción validada del vecino y la referencia
    de la foto (máximo sobre sus descripciones en español) ≥ percentil q de esa similitud contra TODAS las fichas
    validadas. Lo usan `rag_fichas` (acierto@5) y `agente` (¿mejora la recuperación al reformular?)."""

    def __init__(self, c: ClienteEval, percentiles=PERCENTILES):
        self.c = c
        self.embebedor = c.contenedor.embebedor_secundario
        self.percentiles = tuple(percentiles)
        puntos = c.contenedor.almacen_vectorial.vectores_por_filtro(col.FOTOS_TXT_GRANITE, {"validada": True})
        self.ids = [(carga or {}).get("documento_id") or ide.split("#")[0] for ide, _, carga in puntos]
        self.posicion = {d: i for i, d in enumerate(self.ids)}
        self.matriz = np.stack([v for _, v, _ in puntos]).astype(np.float32) if puntos else None
        self._refs: dict[str, np.ndarray] = {}
        self._otros: dict[str, np.ndarray | None] = {}
        registro(f"criterio de vecinos: {len(self.ids)} fichas validadas en {col.FOTOS_TXT_GRANITE}")

    def precargar(self, xm_ids: list[str]) -> None:
        faltan = [x for x in dict.fromkeys(xm_ids) if x not in self._refs]
        textos = [t for x in faltan for t in referencias(x)]
        if not textos:
            return
        m = self.embebedor.embeber_textos(textos)
        i = 0
        for x in faltan:
            n = len(referencias(x))
            self._refs[x] = m[i:i + n]
            i += n

    def _vector(self, documento_id: str) -> np.ndarray | None:
        if documento_id in self.posicion:
            return self.matriz[self.posicion[documento_id]]
        if documento_id not in self._otros:     # ficha validada que no está en la colección granite
            reg = self.c.contenedor.almacen_documentos.obtener_ficha(documento_id)
            texto = (reg.ficha.descripcion or reg.ficha.texto_alternativo) if reg else ""
            self._otros[documento_id] = self.embebedor.embeber_textos([texto])[0] if texto.strip() else None
        return self._otros[documento_id]

    def evaluar(self, xm_id: str, vecinos: list[str], k: int = K_VECINOS) -> dict:
        if self.matriz is None:
            return {"pendiente": "no hay fichas validadas en la colección granite"}
        self.precargar([xm_id])
        refs = self._refs.get(xm_id)
        if refs is None or not len(refs):
            return {"pendiente": "la foto no tiene descripciones de referencia en español"}
        distribucion = (refs @ self.matriz.T).max(axis=0)
        sims = []
        for d in (vecinos or [])[:k]:
            v = self._vector(d)
            sims.append(None if v is None else float((refs @ v).max()))
        validas = [s for s in sims if s is not None]
        n = len(distribucion)
        salida = {"vecinos_evaluados": len(sims), "sim_vecinos": [None if s is None else round(s, 4) for s in sims]}
        for q in self.percentiles:
            u = float(np.percentile(distribucion, q))
            debajo = int(np.sum(distribucion < u))
            azar = 1.0 - float(np.prod([max(debajo - i, 0) / (n - i) for i in range(min(k, n))]))
            salida.update({f"umbral_p{q}": round(u, 4), f"acierto@{k}_p{q}": any(s >= u for s in validas),
                           f"acierto@1_p{q}": bool(sims) and sims[0] is not None and sims[0] >= u,
                           f"azar@{k}_p{q}": round(azar, 4)})
        return salida


def resumen_acierto(filas: list[dict]) -> dict:
    salida = {"n": len(filas), "top1_imagen": resumen_numerico([f.get("top1_imagen") for f in filas])}
    for q in PERCENTILES:
        a5 = [float(f[f"acierto@{K_VECINOS}_p{q}"]) for f in filas if f.get(f"acierto@{K_VECINOS}_p{q}") is not None]
        salida[f"p{q}"] = {"acierto@5": media(a5), "ic95": intervalo_bootstrap(a5),
                           "acierto@1": media([float(f[f"acierto@1_p{q}"]) for f in filas if f.get(f"acierto@1_p{q}") is not None]),
                           "azar@5": media([f.get(f"azar@{K_VECINOS}_p{q}") for f in filas])}
    return salida


def acierto_recuperacion(c: ClienteEval, criterio: CriterioVecinos) -> tuple[dict, list[dict]]:
    part = particiones()
    grupos = {"normales": sorted(part["nuevas"]), "regiones_excluidas": sorted(part["regiones_excluidas"])}
    vectores = vectores_imagen_xm(c)
    subidas = Incremental("subidas").casos
    rec = c.contenedor.fichas.recuperador
    metricas, filas = {}, []
    for grupo, ids in grupos.items():
        ids = [x for x in ids[:tamano(len(ids))] if x in vectores]
        criterio.precargar(ids)
        avance = Avance(f"acierto@5 · {grupo}", len(ids), cada=200)
        del_grupo = []
        for x in ids:
            propio = (subidas.get(x) or {}).get("documento_id") or x     # nunca su propia copia subida
            r = rec.fusionar(vectores[x], rec.listas_unificadas(vectores[x], propio))
            del_grupo.append({"grupo": grupo, "xm_id": x, "top1_imagen": r.top1, "margen": round(r.margen, 4),
                              "vecinos": r.ids(), **criterio.evaluar(x, r.ids())})
            avance.paso()
        metricas[grupo] = resumen_acierto(del_grupo)
        filas += del_grupo
    return metricas, filas


# ───────────────────────────── revisión manual ─────────────────────────────
def _ruta_imagen(xm_id: str) -> str:
    ruta = Path(indice_xm()[xm_id]["ruta"])
    try:
        return f"data/{ruta.relative_to(DATA).as_posix()}"
    except ValueError:
        return ruta.name


def _tiene_calificaciones(ruta: Path) -> bool:
    with open(ruta, newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            if any((v or "").strip() for k, v in fila.items() if k and (k.startswith("humano_") or k == "comentario")):
                return True
    return False


def escribir_plantilla(c: ClienteEval, casos_con_rag: dict[str, dict]) -> dict:
    ruta, relativa = REVISION / "plantilla_fichas.csv", "evaluacion/revision_manual/plantilla_fichas.csv"
    if ruta.exists() and _tiene_calificaciones(ruta):
        registro(f"{relativa} ya tiene calificaciones del autor: no se sobrescribe")
        return {"ruta": relativa, "estado": "conservada: ya tiene calificaciones del autor"}
    candidatas = sorted(x for x, cs in casos_con_rag.items() if cs.get("ficha") and not cs.get("ficha_vacia"))
    elegidas = sorted(random.Random(SEMILLA).sample(candidatas, min(20, len(candidatas))))
    REVISION.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUMNAS_PLANTILLA)
        for x in elegidas:
            cs = casos_con_rag[x]
            ficha = cs["ficha"]
            j = juez(c, x, ficha)       # ya calculado al medir la calidad: no vuelve a llamar al modelo
            justificacion = j.get("justificacion") or (f"error del juez: {j['error']}" if j.get("error") else "")
            w.writerow([x, cs.get("documento_id"), _ruta_imagen(x), " | ".join(referencias(x)), ficha.get("titular", ""),
                        ficha.get("texto_alternativo", ""), ficha.get("descripcion", ""),
                        " | ".join(p.get("termino", "") for p in ficha.get("palabras_clave") or []),
                        ficha.get("estado", ""), cs.get("ruta_final") or "", j.get("fidelidad", ""),
                        j.get("relevancia", ""), justificacion, "", "", ""])
    registro(f"plantilla de revisión manual → {relativa} ({len(elegidas)} fichas)")
    return {"ruta": relativa, "estado": "escrita", "fichas": len(elegidas), "de": len(candidatas),
            "semilla": SEMILLA, "configuracion": "con_rag", "columnas": COLUMNAS_PLANTILLA}


# ───────────────────────────── gráficas ─────────────────────────────
def graficas_rag(agg: dict, recuperacion: dict) -> list[str]:
    fig, (a1, a2, a3) = nueva_figura(13.0, 4.2, 3)
    barras(a1, ["Fidelidad", "Relevancia"],
           {NOMBRE[k]: [agg[k]["juez_fidelidad"].get("media"), agg[k]["juez_relevancia"].get("media")] for k in CONFIGS_RAG},
           {NOMBRE[k]: [agg[k]["juez_fidelidad"].get("ic95"), agg[k]["juez_relevancia"].get("ic95")] for k in CONFIGS_RAG},
           leyenda=False)
    a1.set_ylim(0, 5.6)
    a1.set_ylabel("Juez P7 (0–5)")
    a1.set_title("Calidad según el juez")
    barras(a2, ["Similitud\ngranite", "Recall de\npalabras clave", "Campos con\nfuente válida"],
           {NOMBRE[k]: [agg[k]["granite_max"].get("media"), agg[k]["recall_palabras_clave_oi"].get("media"),
                        agg[k]["campos_con_fuente_valida"].get("tasa")] for k in CONFIGS_RAG}, leyenda=False)
    a2.set_ylim(0, 1.12)
    a2.set_ylabel("Similitud o proporción (0–1)")
    a2.set_title("Similitud, recall y trazabilidad")
    barras(a3, ["chrF"], {NOMBRE[k]: [agg[k]["chrf"].get("media")] for k in CONFIGS_RAG},
           {NOMBRE[k]: [agg[k]["chrf"].get("ic95")] for k in CONFIGS_RAG}, formato="{:.1f}", leyenda=False)
    a3.set_ylim(0, 100)
    a3.set_ylabel("chrF (0–100)")
    a3.set_title("Coincidencia con las referencias")
    fig.suptitle(f"Con RAG contra sin RAG en eval_fichas (n = {agg['con_rag']['n']} fotos; bigotes: IC95; "
                 f"recall contra las etiquetas de Open Images)")
    leyenda_comun(fig, a1)
    fig.tight_layout(rect=(0, 0.07, 1, 0.93))
    guardar_grafica("rag_fichas_con_sin_rag", fig)
    grupos = [g for g in ("normales", "regiones_excluidas") if g in recuperacion]
    fig, (ax,) = nueva_figura(6.8, 3.9)
    barras(ax, [f"{'Normales (nuevas)' if g == 'normales' else 'Regiones excluidas'}\nn = {recuperacion[g]['n']}" for g in grupos],
           {"Recuperador de ejemplos": [recuperacion[g]["p75"]["acierto@5"] for g in grupos],
            "5 fichas al azar": [recuperacion[g]["p75"]["azar@5"] for g in grupos]},
           {"Recuperador de ejemplos": [recuperacion[g]["p75"]["ic95"] for g in grupos]})
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("Acierto@5 (criterio: percentil 75)")
    ax.set_title("Acierto@5 de la recuperación de ejemplos", pad=24)
    guardar_grafica("rag_fichas_acierto5", fig)
    return ["evaluacion/graficas/rag_fichas_con_sin_rag.png", "evaluacion/graficas/rag_fichas_acierto5.png"]


# ───────────────────────────── ejecución ─────────────────────────────
def ejecutar(c: ClienteEval) -> dict:
    exigir_servicios(c)
    xm_ids = eval_fichas_muestra()
    registro(f"RAG · con RAG contra sin RAG: {len(xm_ids)} fotos")
    docs, fallidas = subir(c, xm_ids, "fotos de evaluación")
    ids = [x for x in xm_ids if x in docs]
    registros: dict[str, dict[str, dict]] = {k: {} for k in CONFIGS_RAG}
    for k in CONFIGS_RAG:
        avance = Avance(f"fichas {k}", len(ids))
        for x in ids:
            registros[k][x] = generar(c, k, x, docs[x])
            avance.paso()
    etiquetas = etiquetas_open_images()
    cruce = CruceIdiomas(c)
    calibracion = cruce.calibrar([n for v in etiquetas.values() for n in v])
    registro(f"cruce de idiomas: τ = {calibracion.get('umbral')} (TPR {calibracion.get('tpr')}, FPR {calibracion.get('fpr')})")
    casos: dict[str, dict[str, dict]] = {k: {} for k in CONFIGS_RAG}
    for k in CONFIGS_RAG:
        avance = Avance(f"calidad {k} (juez P7, granite, chrF, Open Images)", len(ids))
        for x in ids:
            casos[k][x] = caso_rag(c, k, x, registros[k][x], etiquetas, cruce, calibracion.get("umbral"))
            avance.paso()
    agg = {k: agregar_rag(list(casos[k].values())) for k in CONFIGS_RAG}
    diferencias = {campo: diferencia_pareada(casos["con_rag"], casos["sin_rag"], campo)
                   for campo in ("juez_promedio", "juez_fidelidad", "juez_relevancia", "granite_max", "chrf", "recall_oi")}
    criterio = CriterioVecinos(c)
    recuperacion, filas_recuperacion = acierto_recuperacion(c, criterio)
    plantilla = escribir_plantilla(c, casos["con_rag"])
    metricas = {
        "conjunto": {"nombre": "eval_fichas", "fotos": len(ids), "no_subidas": fallidas,
                     "con_etiquetas_open_images": sum(1 for x in ids if etiquetas.get(x))},
        "por_configuracion": agg,
        "con_rag_menos_sin_rag": diferencias,
        "cruce_idiomas": calibracion,
        "acierto_recuperacion_ejemplos": recuperacion,
        "plantilla_revision_manual": plantilla,
        "metodos": METODOS,
        "graficas": graficas_rag(agg, recuperacion),
        "detalle_recuperacion": escribir_csv("rag_fichas_recuperacion_detalle", filas_recuperacion),
    }
    detalle = [fila_csv(casos[k][x]) for k in CONFIGS_RAG for x in ids]
    configuracion = {"configuraciones": {k: CONFIGURACIONES[k] for k in CONFIGS_RAG},
                     "recuperacion": c.config.parametro("recuperacion"), "percentiles_criterio_vecinos": PERCENTILES,
                     "k_vecinos": K_VECINOS, "embebedor_criterio_y_cruce": c.contenedor.embebedor_secundario.nombre_modelo}
    guardar_resultado("rag_fichas", metricas, detalle, configuracion, c)
    return metricas


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rapido", action="store_true", help="la cuarta parte de los casos (prueba de humo)")
    if ap.parse_args().rapido:
        os.environ["FOTOTECA_EVAL_RAPIDO"] = "1"
    ejecutar(ClienteEval())


if __name__ == "__main__":
    main()
