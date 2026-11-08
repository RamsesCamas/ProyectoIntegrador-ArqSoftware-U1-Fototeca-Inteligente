"""Crossmodal-3600 (XM3600): descarga, extracción de imágenes e índice clave → locale, descripciones, archivo.

El formato de `captions.zip` se inspeccionó en H0 (verificación 0.7): un `captions.jsonl` con `image/key`,
`image/locale` y una clave por idioma con `{"caption": [...]}`.
"""
from __future__ import annotations

import io
import json
import random
import re
import tarfile
import zipfile
from pathlib import Path

from scripts._descargas import DATA, Manifiesto, ahora_iso, cargar_fuentes, descargar, json_guardar

INDICE_XM = DATA / "procesados" / "xm3600_indice.json"
SEMILLA = 2026


def leer_descripciones(ruta_zip: Path) -> tuple[list[dict], dict]:
    """Analiza captions.zip sin suponer el formato: lo inspecciona y lo describe."""
    estructura: dict = {}
    registros: list[dict] = []
    with zipfile.ZipFile(ruta_zip) as z:
        nombres = z.namelist()
        estructura["miembros"] = nombres[:20]
        candidatos = [n for n in nombres if n.endswith((".jsonl", ".json"))]
        estructura["archivo_analizado"] = candidatos[0] if candidatos else None
        if not candidatos:
            return [], estructura
        with z.open(candidatos[0]) as f:
            for i, linea in enumerate(io.TextIOWrapper(f, encoding="utf-8")):
                linea = linea.strip()
                if not linea:
                    continue
                rec = json.loads(linea)
                if i == 0:
                    estructura["claves_primer_registro"] = sorted(rec.keys())[:60]
                    ejemplo_es = rec.get("es")
                    estructura["ejemplo_es"] = ejemplo_es if not isinstance(ejemplo_es, dict) else {
                        k: (v[:2] if isinstance(v, list) else v) for k, v in ejemplo_es.items()}
                clave = rec.get("image/key") or rec.get("key") or rec.get("image_key") or rec.get("id")
                locale = rec.get("image/locale") or rec.get("locale")
                es = rec.get("es")
                if isinstance(es, dict):
                    es = es.get("caption") or es.get("captions") or []
                if isinstance(es, str):
                    es = [es]
                en = rec.get("en")
                if isinstance(en, dict):
                    en = en.get("caption") or []
                registros.append({"clave": clave, "locale": locale, "es": list(es or []), "en": list(en or [])})
    return registros, estructura


def extraer_imagenes(ruta_tgz: Path, destino: Path) -> int:
    destino.mkdir(parents=True, exist_ok=True)
    existentes = len(list(destino.glob("*.jpg")))
    if existentes >= 3600:
        return existentes
    patron = re.compile(r"^[\w./-]+\.(jpe?g|png)$", re.I)
    n = 0
    with tarfile.open(ruta_tgz, "r:gz") as tar:
        for miembro in tar:
            if not miembro.isfile() or not patron.match(miembro.name) or ".." in miembro.name:
                continue
            nombre = Path(miembro.name).name
            with tar.extractfile(miembro) as src, open(destino / nombre, "wb") as dst:
                dst.write(src.read())
            n += 1
    return n


def asegurar_xm3600() -> dict:
    """Descarga XM3600 (si falta), extrae imágenes y construye el índice."""
    fuentes = cargar_fuentes()["xm3600"]
    man = Manifiesto("datos")
    for clave in ("imagenes", "descripciones", "atribuciones"):
        descargar(fuentes[clave]["url"], fuentes[clave]["archivo"], man)
    dir_img = DATA / fuentes["directorio_imagenes"]
    n_img = extraer_imagenes(DATA / fuentes["imagenes"]["archivo"], dir_img)
    registros, estructura = leer_descripciones(DATA / fuentes["descripciones"]["archivo"])
    archivos = {p.stem: p.name for p in dir_img.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")}
    for r in registros:
        r["archivo"] = archivos.get(r["clave"])
    json_guardar(INDICE_XM, {"generado": ahora_iso(), "estructura": estructura, "registros": registros})
    return {"n_imagenes_extraidas": n_img, "estructura": estructura, "registros": registros, "dir": dir_img}


def directorio_imagenes() -> Path:
    return DATA / cargar_fuentes()["xm3600"]["directorio_imagenes"]


def cargar_indice() -> tuple[list[dict], Path]:
    if not INDICE_XM.exists():
        asegurar_xm3600()
    datos = json.loads(INDICE_XM.read_text(encoding="utf-8"))
    regs = [r for r in datos["registros"] if r.get("archivo") and r.get("es")]
    return regs, directorio_imagenes()


def muestra(regs: list[dict], n: int, semilla: int = SEMILLA) -> list[dict]:
    regs = sorted(regs, key=lambda r: r["clave"])
    return random.Random(semilla).sample(regs, n)


def id_documento(clave: str) -> str:
    """Identificador estable de una foto de XM3600 en el archivo (docs/specs/03: `xm-<clave>`)."""
    return f"xm-{clave}"
