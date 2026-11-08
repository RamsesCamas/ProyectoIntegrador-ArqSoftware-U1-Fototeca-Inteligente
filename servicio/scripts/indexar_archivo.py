"""Indexado del archivo (H3; colecciones de ADR-09). Se ejecuta después de preparar_datos y preparar_corpus.

    python -m scripts.indexar_archivo

Reconstruye DESDE CERO las colecciones vectoriales y el estado del archivo (borra subidas, fichas y caché previas):
1. `tesauro` (un concepto por entrada) y `normas` (fragmentos) con EmbeddingGemma-2, rol «documento».
2. Fichas iniciales de las 2,600 fotos del archivo, SIN modelos de lenguaje (escritas por humanos):
   descripción = 1ª descripción en español; texto alternativo = la más corta, recortada a 250 caracteres;
   titular = la más corta, recortada a 120 (decisión documentada aquí); palabras clave = etiquetas de
   Open Images normalizadas al tesauro por embeddings con umbral τ_tesauro (se reporta la tasa de mapeo y
   se deja una muestra de 50 pares para revisión).
3. `fotos_img` (vectores de imagen calculados en preparar_datos), `fotos_txt` (EmbeddingGemma-2) y
   `fotos_txt_granite` (granite) con `validada=true`.
4. Documentos y fichas en SQLite; `version_corpus` y `version_archivo`.
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
import re
import time
from collections import Counter
from pathlib import Path

import numpy as np

from fototeca.api.arranque import cargar_configuracion, construir_contenedor
from fototeca.contexto.tesauro import Tesauro
from fototeca.dominio import colecciones as col
from fototeca.dominio.esquemas_ficha import Ficha, FichaRegistrada, Fuente, PalabraClave
from scripts._descargas import DATA, EVAL, ahora_iso, json_guardar, registro
from scripts._xm3600 import SEMILLA, cargar_indice
from scripts.preparar_datos import PROCESADOS, slug

CONJUNTOS = EVAL / "conjuntos"
REVISION = EVAL / "revision_manual"


def recortar(texto: str, maximo: int) -> str:
    """Recorta en un límite de palabra sin pasar de `maximo` caracteres."""
    texto = re.sub(r"\s+", " ", texto).strip()
    if len(texto) <= maximo:
        return texto
    corte = texto.rfind(" ", 0, maximo - 1)
    return texto[:corte if corte > maximo // 2 else maximo - 1].rstrip(" ,;:") + "…"


def leer_jsonl(ruta: Path) -> list[dict]:
    with open(ruta, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def calibrar_tau_tesauro(top1: dict, conceptos: list[dict], tau_inicial: float, precision_minima: float = 0.90,
                         minimo_aceptados: int = 20) -> dict:
    """Barrido de τ (0.50–0.95) sobre las etiquetas con concepto esperado por coincidencia léxica en inglés.
    Regla fijada antes de ver los datos: el τ más bajo con precisión ≥ 0.90 y al menos 20 mapeos aceptados (más
    recall sin sacrificar precisión); si ninguno la alcanza, el τ de mayor F1. Si no hay pares con esperado, se
    conserva el τ inicial."""
    from scripts._tesauro_lexico import esperado, indice_ingles
    indice = indice_ingles(conceptos)
    pares = [(t, pc.uri, pc.similitud, esperado(t, indice)) for t, pc in top1.items()]
    con_esperado = [p for p in pares if p[3] and p[2] is not None]
    curva = []
    for tau in [round(x, 2) for x in np.arange(0.50, 0.951, 0.01)]:
        aceptados = [p for p in con_esperado if p[2] >= tau]
        correctos = sum(1 for p in aceptados if p[1] == p[3])
        precision = correctos / len(aceptados) if aceptados else None
        recall = correctos / len(con_esperado) if con_esperado else None
        f1 = (2 * precision * recall / (precision + recall)) if precision and recall else 0.0
        curva.append({"tau": tau, "aceptados": len(aceptados), "correctos": correctos,
                      "precision": None if precision is None else round(precision, 4),
                      "recall": None if recall is None else round(recall, 4), "f1": round(f1, 4)})
    validos = [c for c in curva if c["precision"] is not None and c["precision"] >= precision_minima
               and c["aceptados"] >= minimo_aceptados]
    if not con_esperado:
        elegido, criterio = tau_inicial, "sin pares con esperado léxico: se conserva el τ inicial"
    elif validos:
        elegido = min(c["tau"] for c in validos)
        criterio = f"el τ más bajo con precisión ≥ {precision_minima} y ≥ {minimo_aceptados} mapeos aceptados"
    else:
        elegido = max(curva, key=lambda c: c["f1"])["tau"]
        criterio = f"ningún τ alcanza precisión ≥ {precision_minima}: τ de mayor F1"
    top1_correcto = sum(1 for p in con_esperado if p[1] == p[3])
    return {
        "fecha": ahora_iso(), "metodo": "proxy léxico: el concepto esperado es el que tiene la etiqueta de Open "
        "Images (inglés, singular o plural) entre sus etiquetas @en; el mapeo del sistema es por embeddings",
        "etiquetas": len(pares), "con_esperado_lexico": len(con_esperado),
        "exactitud_top1_sin_umbral": round(top1_correcto / len(con_esperado), 4) if con_esperado else None,
        "tau_inicial": tau_inicial, "tau_elegido": float(elegido), "criterio": criterio, "curva": curva,
        "nota": "Se recalibra cuando el autor revise los 50 pares de evaluacion/revision_manual/.",
    }


def documento_de_norma(url: str) -> str:
    partes = [p for p in re.split(r"[/:.#?]+", url.lower()) if p and p not in ("http", "https", "www", "html", "org")]
    return "norma-" + "-".join(partes)[-80:]


def main() -> None:
    t0 = time.perf_counter()
    config = cargar_configuracion()
    c = construir_contenedor(config)
    vec, docs = c.almacen_vectorial, c.almacen_documentos
    principal, granite = c.embebedor, c.embebedor_secundario
    dim, dim_g = principal.dimension, granite.dimension
    tau_tesauro = float(config.parametro("guardrails.tau_tesauro", 0.75))
    registro(f"embeddings: {principal.nombre_modelo} ({dim}d) y {granite.nombre_modelo} ({dim_g}d) · τ_tesauro {tau_tesauro}")

    registro("0/5 · Reconstrucción desde cero (colecciones, documentos, fichas y caché)")
    for nombre in col.TODAS:
        vec.recrear_coleccion(nombre, dim_g if nombre == col.FOTOS_TXT_GRANITE else dim)
    with docs.conexion() as con:
        con.executescript("DELETE FROM duplicados; DELETE FROM fichas; DELETE FROM documentos; DELETE FROM estado_archivo;")
    with c.almacen_cache.conexion() as con:
        con.executescript("DELETE FROM cache_etiquetas; DELETE FROM cache;")
    for m in (DATA / "miniaturas").glob("*.jpg"):
        m.unlink(missing_ok=True)

    registro("1/5 · Tesauro y normas")
    conceptos = leer_jsonl(DATA / "corpus" / "tesauro.jsonl")
    v = principal.embeber_textos([x["texto"] for x in conceptos], rol="documento")
    vec.insertar(col.TESAURO, [f"tesauro:{x['uri']}" for x in conceptos], v,
                 [{k: x[k] for k in ("uri", "etiqueta_es", "alternativas_es", "nota_alcance", "licencia", "version_corpus")}
                  for x in conceptos])
    normas = leer_jsonl(DATA / "corpus" / "normas.jsonl")
    for n in normas:
        n["documento_id"] = documento_de_norma(n["url"])
    v = principal.embeber_textos([n["texto"] for n in normas], rol="documento")
    vec.insertar(col.NORMAS, [n["id"] for n in normas], v, [{k: val for k, val in n.items() if k != "id"} for n in normas])
    por_documento = Counter(n["documento_id"] for n in normas)
    docs.guardar_lote([{"documento_id": d, "tipo": "norma", "nombre": next(n["fuente"] for n in normas if n["documento_id"] == d),
                        "particion": "corpus", "metadatos": {"url": next(n["url"] for n in normas if n["documento_id"] == d),
                                                             "fragmentos": k, "licencia": next(n["licencia"] for n in normas if n["documento_id"] == d)}}
                       for d, k in por_documento.items()])
    registro(f"   {len(conceptos)} conceptos · {len(normas)} fragmentos de {len(por_documento)} documentos normativos")
    # Prototipos (config/prototipos.yaml): consultas e inyecciones se comparan texto↔texto (rol simétrico);
    # dominio y texto visible se comparan contra la IMAGEN (el texto hace de consulta).
    import yaml
    proto = yaml.safe_load((Path(config.rutas["config"]) / "prototipos.yaml").read_text(encoding="utf-8"))
    filas = [("consulta", clase, t, "simetrico") for clase, ts in proto["consulta"].items() for t in ts]
    filas += [("inyeccion", "inyeccion", t, "simetrico") for t in proto["inyeccion"]]
    filas += [(tipo, clase, t, "consulta") for tipo in ("dominio", "texto_visible")
              for clase, ts in proto[tipo].items() for t in ts]
    vectores = []
    for rol in ("simetrico", "consulta"):
        grupo = [f for f in filas if f[3] == rol]
        vectores.append((grupo, principal.embeber_textos([f[2] for f in grupo], rol=rol)))
    for grupo, v in vectores:
        vec.insertar(col.PROTOTIPOS, [f"proto:{f[0]}:{f[1]}:{i}" for i, f in enumerate(grupo)], v,
                     [{"tipo": f[0], "clase": f[1], "texto": f[2], "rol": f[3]} for f in grupo])
    registro(f"   {len(filas)} prototipos")

    registro("2/5 · Fichas iniciales del archivo (sin modelos de lenguaje)")
    regs, dir_img = cargar_indice()
    por_clave = {r["clave"]: r for r in regs}
    part = json.loads((CONJUNTOS / "particiones.json").read_text(encoding="utf-8"))
    archivo = [d.removeprefix("xm-") for d in part["particiones"]["archivo"]]
    etiquetas = json.loads((PROCESADOS / "oi_etiquetas_por_imagen.json").read_text(encoding="utf-8"))
    nombres_unicos = sorted({e["nombre"] for k in archivo for e in etiquetas.get(k, [])})
    # τ_tesauro con un proxy léxico (ADR-05): el mapeo es por embeddings; el umbral se elige
    # sobre las etiquetas cuya traducción esperada se conoce por coincidencia léxica en inglés.
    top1 = dict(Tesauro(vec, principal).normalizar(nombres_unicos, umbral=-1.0))
    calibracion = calibrar_tau_tesauro(top1, conceptos, tau_tesauro)
    tau_tesauro = calibracion["tau_elegido"]
    json_guardar(EVAL / "resultados" / "calibracion_tesauro.json", calibracion)
    registro(f"   τ_tesauro = {tau_tesauro} ({calibracion['criterio']})")
    mapeo = {t: (pc if pc.similitud is not None and pc.similitud >= tau_tesauro
                 else PalabraClave(termino=t, uri=None, origen="libre", similitud=pc.similitud))
             for t, pc in top1.items()}
    fichas, documentos = [], []
    for clave in archivo:
        r = por_clave[clave]
        es = [x.strip() for x in r["es"] if x.strip()]
        corta_i = min(range(len(es)), key=lambda i: len(es[i]))
        palabras, fuentes_pc, vistos = [], [], set()
        for e in etiquetas.get(clave, []):
            pc = mapeo.get(e["nombre"])
            if pc and pc.origen == "tesauro" and pc.uri not in vistos:
                vistos.add(pc.uri)
                palabras.append(pc)
                fuentes_pc += [Fuente(tipo="etiqueta_open_images", id=e["id"], titulo=e["nombre"]),
                               Fuente(tipo="tesauro", id=pc.uri, titulo=pc.termino, puntaje=pc.similitud)]
        doc_id = f"xm-{clave}"
        ref = lambda i: Fuente(tipo="referencia_humana", id=f"xm3600:{clave}#es-{i + 1}",  # noqa: E731
                               titulo="Descripción de referencia (Crossmodal-3600, CC BY 4.0)")
        ficha = Ficha(titular=recortar(es[corta_i], 120), descripcion=recortar(es[0], 800),
                      texto_alternativo=recortar(es[corta_i], 250), palabras_clave=palabras, estado="validada")
        fichas.append(FichaRegistrada(documento_id=doc_id, ficha=ficha, origen="referencia_humana", fuentes={
            "titular": [ref(corta_i)], "descripcion": [ref(0)], "texto_alternativo": [ref(corta_i)],
            "palabras_clave": fuentes_pc}))
        ruta = dir_img / r["archivo"]
        documentos.append({"documento_id": doc_id, "tipo": "foto", "nombre": r["archivo"], "particion": "archivo",
                           "sha256": hashlib.sha256(ruta.read_bytes()).hexdigest(),
                           "metadatos": {"ruta_relativa": str(ruta.relative_to(DATA)), "locale": r["locale"],
                                         "clave": clave, "fuente": "Crossmodal-3600"}})
    docs.guardar_lote(documentos)
    docs.guardar_fichas_lote(fichas)
    con_palabras = sum(1 for f in fichas if f.ficha.palabras_clave)
    mapeados = [t for t, pc in mapeo.items() if pc.origen == "tesauro"]
    registro(f"   {len(fichas)} fichas · etiquetas únicas {len(nombres_unicos)}, mapeadas {len(mapeados)} · "
             f"fotos con ≥1 palabra clave {con_palabras}")

    registro("3/5 · Vectores de las fotos del archivo")
    z = np.load(PROCESADOS / f"emb_img_{slug(principal.nombre_modelo)}_{principal.lado_imagen_px}px.npz", allow_pickle=False)
    indice = {k: i for i, k in enumerate(z["ids"].tolist())}
    ids = [f"xm-{k}" for k in archivo]
    carga = [{"documento_id": f"xm-{k}", "particion": "archivo", "locale": por_clave[k]["locale"], "validada": True,
              "version_archivo": 1} for k in archivo]
    vec.insertar(col.FOTOS_IMG, ids, z["vectores"][[indice[k] for k in archivo]], carga)
    descripciones = [f.ficha.descripcion for f in fichas]
    vec.insertar(col.FOTOS_TXT, [f"{i}#descripcion" for i in ids], principal.embeber_textos(descripciones, rol="documento"),
                 [{**cg, "campo": "descripcion"} for cg in carga])
    vec.insertar(col.FOTOS_TXT_GRANITE, [f"{i}#descripcion" for i in ids], granite.embeber_textos(descripciones),
                 [{**cg, "campo": "descripcion"} for cg in carga])

    registro("4/5 · Estado del archivo")
    version_corpus = json.loads((DATA / "corpus" / "version.json").read_text(encoding="utf-8"))["version_corpus"]
    docs.escribir_estado("version_corpus", version_corpus)
    docs.escribir_estado("version_archivo", "1")

    registro("5/5 · Reporte")
    sims = sorted(pc.similitud for pc in mapeo.values() if pc.similitud is not None)
    rng = random.Random(SEMILLA)
    muestra = rng.sample(sorted(mapeo.items()), min(50, len(mapeo)))
    REVISION.mkdir(parents=True, exist_ok=True)
    with open(REVISION / "muestra_mapeo_oi_tesauro.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["etiqueta_open_images", "concepto_tesauro_mas_cercano", "uri", "similitud", "mapeado_con_umbral",
                    "correcto (si/no)", "comentario"])
        for etiqueta, pc in muestra:
            w.writerow([etiqueta, pc.termino if pc.origen == "tesauro" else "", pc.uri or "", pc.similitud,
                        pc.origen == "tesauro", "", ""])
    reporte = {
        "fecha": ahora_iso(), "segundos": round(time.perf_counter() - t0, 1),
        "modelos": {"principal": principal.nombre_modelo, "secundario": granite.nombre_modelo,
                    "lado_imagen_px": principal.lado_imagen_px},
        "colecciones": {n: vec.contar(n) for n in col.TODAS},
        "documentos": {"fotos": docs.contar("foto"), "normas": docs.contar("norma")},
        "fichas": docs.contar_fichas(),
        "mapeo_open_images_tesauro": {
            "umbral": tau_tesauro, "calibracion_umbral": "evaluacion/resultados/calibracion_tesauro.json",
            "etiquetas_unicas": len(nombres_unicos), "mapeadas": len(mapeados),
            "tasa_mapeo": round(len(mapeados) / max(1, len(nombres_unicos)), 4),
            "fotos_con_al_menos_una_palabra_clave": con_palabras,
            "porcentaje_fotos_con_palabras": round(con_palabras / max(1, len(fichas)), 4),
            "similitud_top1": {"p10": float(np.percentile(sims, 10)), "p50": float(np.percentile(sims, 50)),
                               "p90": float(np.percentile(sims, 90))} if sims else None,
            "muestra_revision": "evaluacion/revision_manual/muestra_mapeo_oi_tesauro.csv",
        },
        "version_corpus": version_corpus,
    }
    json_guardar(EVAL / "resultados" / "indexado.json", reporte)
    registro(f"listo en {reporte['segundos'] / 60:.1f} min · colecciones {reporte['colecciones']}")


if __name__ == "__main__":
    main()
