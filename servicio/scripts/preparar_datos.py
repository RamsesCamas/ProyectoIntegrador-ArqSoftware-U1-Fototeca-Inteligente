"""Preparación de datos: archivo fotográfico, particiones y conjuntos sintéticos (informe, §3.2). Requiere internet
solo la primera vez.

    python -m scripts.preparar_datos

1. Descarga XM3600 (imágenes, descripciones y atribuciones) y las etiquetas humanas de Open Images V7
   filtradas a las imágenes de XM3600 (idempotente, con manifiesto SHA-256).
2. Audita EXIF/GPS.
3. Calcula los embeddings de imagen de las 3,600 fotos con el embebedor principal (reanudable, en caché en
   `data/procesados/`; `indexar_archivo` los reutiliza).
4. Elige las 3 locales con menor similitud media al resto y forma las particiones con semilla 2026
   (`evaluacion/conjuntos/particiones.json`, versionado).
5. Genera los conjuntos sintéticos la primera vez o, si ya están versionados, materializa sus imágenes.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from fototeca.api.arranque import cargar_configuracion, construir_embebedores
from fototeca.dominio.errores import ServicioNoDisponible, TiempoAgotado
from scripts._descargas import (DATA, EVAL, Manifiesto, ahora_iso, cargar_fuentes, descargar,
                                filtrar_csv_remoto, json_guardar, registro)
from scripts._xm3600 import SEMILLA, asegurar_xm3600, directorio_imagenes, id_documento

CONJUNTOS = EVAL / "conjuntos"
PARTICIONES = CONJUNTOS / "particiones.json"
PROCESADOS = DATA / "procesados"
TAM_ARCHIVO = 2600
N_EXCLUIDAS = 3
LIMITE_LOTE_POR_IMAGEN_S = 30.0
REINTENTOS_LOTE = 2


def slug(texto: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in texto)


# ───────────────────────────── 1. Open Images ─────────────────────────────
def etiquetas_open_images(claves: set[str]) -> dict:
    oi = cargar_fuentes()["open_images"]
    man = Manifiesto("datos")
    descargar(oi["clases"]["url"], oi["clases"]["archivo"], man)
    filtrar_csv_remoto(oi["etiquetas_humanas"], oi["etiquetas_filtradas"], "ImageID", claves, man)
    nombres = {}
    with open(DATA / oi["clases"]["archivo"], newline="", encoding="utf-8") as f:
        for fila in csv.reader(f):
            if len(fila) >= 2 and fila[0].startswith("/"):
                nombres[fila[0]] = fila[1]
    por_imagen: dict[str, list[dict]] = defaultdict(list)
    with open(DATA / oi["etiquetas_filtradas"], newline="", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            if fila.get("Confidence") in ("1", "1.0"):
                etiqueta = {"id": fila["LabelName"], "nombre": nombres.get(fila["LabelName"], fila["LabelName"])}
                if etiqueta not in por_imagen[fila["ImageID"]]:
                    por_imagen[fila["ImageID"]].append(etiqueta)
    json_guardar(PROCESADOS / "oi_etiquetas_por_imagen.json", por_imagen)
    return por_imagen


# ───────────────────────────── 2. EXIF ─────────────────────────────
def auditar_exif(regs: list[dict], dir_img: Path) -> dict:
    n_exif = n_gps = 0
    for r in regs:
        with Image.open(dir_img / r["archivo"]) as im:
            exif = im.getexif()
            if len(exif):
                n_exif += 1
                n_gps += bool(exif.get_ifd(0x8825))
    return {"imagenes": len(regs), "con_exif": n_exif, "con_gps": n_gps}


# ───────────────────────────── 3. Embeddings de imagen ─────────────────────────────
def embeddings_imagenes(regs: list[dict], dir_img: Path, embebedor, lote: int = 32) -> tuple[list[str], np.ndarray]:
    """Embeddings de imagen de todas las fotos, reanudables (se guardan cada lote)."""
    ruta = PROCESADOS / f"emb_img_{slug(embebedor.nombre_modelo)}_{embebedor.lado_imagen_px}px.npz"
    hechos: dict[str, np.ndarray] = {}
    if ruta.exists():
        z = np.load(ruta, allow_pickle=False)
        hechos = dict(zip(z["ids"].tolist(), z["vectores"]))
    pendientes = [r for r in regs if r["clave"] not in hechos]
    if pendientes:
        registro(f"embeddings de imagen: {len(hechos)} en caché, {len(pendientes)} pendientes "
                 f"({embebedor.nombre_modelo}, {embebedor.lado_imagen_px}px)")
    # Proceso por lotes y sin usuario esperando: el tiempo límite interactivo de H0 (5 s por elemento) no aplica.
    # Se usa uno holgado y se reintenta el lote, para que la contención de CPU no tire una corrida de horas.
    embebedor.tiempo_limite_s = max(float(embebedor.tiempo_limite_s), LIMITE_LOTE_POR_IMAGEN_S)
    t0 = time.perf_counter()
    for i in range(0, len(pendientes), lote):
        parte = pendientes[i:i + lote]
        imagenes = [(dir_img / r["archivo"]).read_bytes() for r in parte]
        for intento in range(1, REINTENTOS_LOTE + 2):
            try:
                vectores = embebedor.embeber_imagenes(imagenes)
                break
            except (TiempoAgotado, ServicioNoDisponible) as e:
                if intento > REINTENTOS_LOTE:
                    raise
                registro(f"   lote {i // lote + 1}: {type(e).__name__}; reintento {intento} en 10 s")
                time.sleep(10)
        for r, v in zip(parte, vectores):
            hechos[r["clave"]] = v
        ids = list(hechos)
        np.savez(ruta.with_suffix(".tmp.npz"), ids=np.array(ids), vectores=np.stack([hechos[k] for k in ids]))
        ruta.with_suffix(".tmp.npz").replace(ruta)
        hecho = i + len(parte)
        seg = time.perf_counter() - t0
        registro(f"  {hecho}/{len(pendientes)} · {seg / hecho:.2f} s/imagen · faltan ~{(len(pendientes) - hecho) * seg / hecho / 60:.0f} min")
    claves = [r["clave"] for r in regs]
    return claves, np.stack([hechos[k] for k in claves])


# ───────────────────────────── 4. Particiones ─────────────────────────────
def similitud_por_locale(claves: list[str], locales: list[str], m: np.ndarray) -> dict[str, float]:
    sims = m @ m.T
    resultado = {}
    arr = np.array(locales)
    for loc in sorted(set(locales)):
        dentro = arr == loc
        resultado[loc] = round(float(sims[np.ix_(dentro, ~dentro)].mean()), 5)
    return resultado


def formar_particiones(regs: list[dict], sim_locale: dict[str, float], embebedor) -> dict:
    rng = random.Random(SEMILLA)
    excluidas = sorted(sorted(sim_locale, key=sim_locale.get)[:N_EXCLUIDAS])
    por_locale: dict[str, list[str]] = defaultdict(list)
    for r in sorted(regs, key=lambda r: r["clave"]):
        por_locale[r["locale"]].append(r["clave"])
    restantes = sorted(l for l in por_locale if l not in excluidas)
    base, extra = divmod(TAM_ARCHIVO, len(restantes))
    con_extra = set(rng.sample(restantes, extra))
    archivo, nuevas = [], []
    for loc in restantes:
        claves = por_locale[loc][:]
        rng.shuffle(claves)
        k = base + (1 if loc in con_extra else 0)
        archivo += claves[:k]
        nuevas += claves[k:]
    regiones = sorted(c for l in excluidas for c in por_locale[l])
    archivo, nuevas = sorted(archivo), sorted(nuevas)
    eval_nuevas = sorted(rng.sample(nuevas, 40))
    eval_regiones = sorted(rng.sample(regiones, 20))
    eval_fichas = eval_nuevas + eval_regiones
    libres_nuevas = sorted(set(nuevas) - set(eval_nuevas))
    ajuste_prompts = sorted(rng.sample(libres_nuevas, 10))
    aprendizaje = sorted(rng.sample(sorted(set(libres_nuevas) - set(ajuste_prompts)), 100))
    agente_extra = sorted(rng.sample(sorted(set(regiones) - set(eval_regiones)), 30))
    particiones = {
        "archivo": archivo, "nuevas": nuevas, "regiones_excluidas": regiones,
        "eval_fichas": eval_fichas, "galeria_busqueda": sorted(nuevas + regiones),
        # Subconjuntos fijados de antemano para que los experimentos no se crucen (informe, §10.2):
        "ajuste_prompts": ajuste_prompts,          # H4: refinamiento de prompts (nunca eval_fichas)
        "aprendizaje": aprendizaje,                # H7: curva de aprendizaje (sin solaparse con eval_fichas)
        "agente_extra": agente_extra,              # H7: ciclo de agente, 30 adicionales de regiones_excluidas
    }
    return {
        "generado": ahora_iso(), "semilla": SEMILLA,
        "criterio_exclusion": f"las {N_EXCLUIDAS} locales cuyas imágenes tienen menor similitud media "
                              f"(coseno, {embebedor.nombre_modelo}, imagen a {embebedor.lado_imagen_px}px) con el resto",
        "locales_excluidas": excluidas,
        "similitud_media_por_locale": dict(sorted(sim_locale.items(), key=lambda kv: kv[1])),
        "tamanos": {k: len(v) for k, v in particiones.items()},
        "particiones": {k: [id_documento(c) for c in v] for k, v in particiones.items()},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sin-sinteticos", action="store_true", help="no generar ni materializar los sintéticos")
    args = ap.parse_args()
    t0 = time.perf_counter()

    registro("1/5 · Crossmodal-3600")
    xm = asegurar_xm3600()
    regs = [r for r in xm["registros"] if r.get("archivo") and r.get("es")]
    dir_img = directorio_imagenes()
    registro(f"   {len(regs)} imágenes con descripciones en español")

    registro("2/5 · Open Images V7 (etiquetas humanas, streaming filtrado) y auditoría EXIF")
    etiquetas = etiquetas_open_images({r["clave"] for r in regs})
    exif = auditar_exif(regs, dir_img)
    registro(f"   {len(etiquetas)} imágenes con etiquetas positivas · EXIF: {exif}")

    registro("3/5 · Embeddings de imagen (reanudable)")
    config = cargar_configuracion()
    principal, _ = construir_embebedores(config)
    claves, matriz = embeddings_imagenes(regs, dir_img, principal)

    registro("4/5 · Locales excluidas y particiones (semilla 2026)")
    if PARTICIONES.exists():
        registro(f"   ya existen ({PARTICIONES.name}); no se regeneran para no cambiar los experimentos")
        part = json.loads(PARTICIONES.read_text(encoding="utf-8"))
    else:
        locales = [r["locale"] for r in regs]
        sim = similitud_por_locale(claves, locales, matriz)
        part = formar_particiones(regs, sim, principal)
        json_guardar(PARTICIONES, part)
    registro(f"   excluidas: {part['locales_excluidas']} · tamaños: {part['tamanos']}")

    resumen = {
        "fecha": ahora_iso(), "imagenes": len(regs), "locales": len({r['locale'] for r in regs}),
        "descripciones_es_por_imagen": dict(Counter(len(r["es"]) for r in regs)),
        "imagenes_con_etiquetas_open_images": len(etiquetas),
        "porcentaje_con_etiquetas": round(len(etiquetas) / len(regs), 4),
        "exif": exif, "embeddings_imagen": {"modelo": principal.nombre_modelo, "lado_px": principal.lado_imagen_px,
                                            "dimension": int(matriz.shape[1]), "n": int(matriz.shape[0])},
        "particiones": part["tamanos"], "locales_excluidas": part["locales_excluidas"],
    }

    if not args.sin_sinteticos:
        registro("5/5 · Conjuntos sintéticos")
        from scripts.generar_sinteticos import asegurar_sinteticos
        resumen["sinteticos"] = asegurar_sinteticos()

    # Evidencia de H2 (versionada en evaluacion/resultados/): manifiestos con SHA-256 y tamaño de data/ (≤ 2 GB)
    manifiestos = {}
    for ruta in sorted(DATA.glob("manifiesto_*.json")):
        entradas = json.loads(ruta.read_text(encoding="utf-8")).get("archivos", [])
        manifiestos[ruta.name] = {"entradas": len(entradas),
                                  "con_sha256": sum(1 for e in entradas if e.get("sha256"))}
    tam_b = sum(p.stat().st_size for p in DATA.rglob("*") if p.is_file())
    resumen["manifiestos"] = manifiestos
    resumen["data_bytes"] = tam_b
    resumen["data_gb"] = round(tam_b / 1e9, 3)
    resumen["data_dentro_de_2gb"] = tam_b <= 2e9
    resumen["minutos"] = round((time.perf_counter() - t0) / 60, 1)
    json_guardar(EVAL / "resultados" / "datos.json", resumen)
    registro(f"listo en {resumen['minutos']} min · data/ pesa {resumen['data_gb']} GB · manifiestos: {manifiestos}")


if __name__ == "__main__":
    main()
