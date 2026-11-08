"""Corpus normativo y tesauro (ADR-06). Requiere internet solo la primera vez.

    python -m scripts.preparar_corpus

- Normas (IPTC 2025.1, W3C WAI, WCAG 2.2 1.1.1, DCMI): se analiza el HTML con BeautifulSoup, se quita la
  navegación y se conservan los encabezados. Una regla o un campo por fragmento (unidades atómicas), objetivo de
  300–800 caracteres sin solapamiento; si una sección supera 1,200 caracteres se divide por párrafos con un
  solapamiento del 15 %. Metadatos: fuente, url, seccion, campo_iptc, licencia y version_corpus.
- Tesauro UNESCO: un documento por concepto con etiqueta en español; texto a embeber
  «{prefLabel_es}. Sinónimos: {altLabels_es}. {scopeNote_es}». Se reporta cuántos se descartaron.
- Reporte de R1 (sin contar el tesauro; 2,000 caracteres = 1 página) en evaluacion/resultados/corpus_r1.json.
- Versión del corpus: hash del contenido (si cambia, se invalidan las fichas en caché).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from fototeca.contexto.fragmentador import dividir, limpiar, slug
from scripts._descargas import DATA, EVAL, Manifiesto, ahora_iso, cargar_fuentes, descargar, json_guardar, registro

CORPUS = DATA / "corpus"
CRUDOS = CORPUS / "crudos"
FILAS_IPTC = ("Name", "Definition", "Help Text", "User Note(s)", "Implementation Note(s)", "Basic Specs")


def fragmentos_de(seccion_id: str, titulo: str, texto: str, parrafos: list[str], base: dict,
                  campo_iptc: str | None = None, encabezado: str | None = None) -> list[dict]:
    """`encabezado` («Norma — sección») se antepone a los fragmentos de una sección larga que se dividió."""
    salida = []
    for i, parte in enumerate(dividir(texto, parrafos, encabezado=encabezado)):
        fid = f"{base['id']}#{seccion_id}" + (f"-p{i + 1}" if i else "")
        salida.append({"id": fid, "fuente": base["fuente"], "url": base["url"], "seccion": titulo,
                       "campo_iptc": campo_iptc, "licencia": base["licencia"], "texto": parte})
    return salida


# ───────────────────────────── analizadores ─────────────────────────────
def analizar_iptc(html: str, base: dict) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    salida = []
    for h in soup.find_all(["h2", "h3", "h4"]):
        titulo = limpiar(h.get_text(" "))
        if not re.match(r"^\d+(\.\d+)*\.\s", titulo):
            continue   # solo las secciones numeradas de la especificación (sin portada, derechos ni historial)
        contenedor = h.parent if isinstance(h.parent, Tag) else None
        if contenedor is None:
            continue
        nombre_sin_num = re.sub(r"^\d+(\.\d+)*\.\s*", "", titulo)
        tabla = contenedor.find("table", recursive=True)
        filas = {}
        if tabla is not None and tabla.find_parent(class_=re.compile(r"sect\d")) is contenedor:
            for tr in tabla.find_all("tr"):
                celdas = [limpiar(c.get_text(" ")) for c in tr.find_all(["th", "td"])]
                if len(celdas) >= 2 and celdas[0] in FILAS_IPTC and celdas[1]:
                    filas[celdas[0]] = celdas[1]
        if filas.get("Definition"):
            partes = [f"{k}: {filas[k]}" for k in FILAS_IPTC if filas.get(k)]
            texto = f"IPTC Photo Metadata 2025.1 — {nombre_sin_num}. " + " ".join(partes)
            salida += fragmentos_de(h.get("id") or slug(titulo), titulo, texto, partes, base,
                                    campo_iptc=filas.get("Name", nombre_sin_num),
                                    encabezado=f"IPTC Photo Metadata 2025.1 — {nombre_sin_num}")
            continue
        # Sección de prosa: párrafos directos (sin subsecciones anidadas)
        parrafos = []
        for nodo in contenedor.find_all(["p", "li"], recursive=True):
            if nodo.find_parent(class_=re.compile(r"sect\d")) is contenedor and not nodo.find_parent("table"):
                t = limpiar(nodo.get_text(" "))
                if len(t) > 40:
                    parrafos.append(t)
        if parrafos:
            texto = f"IPTC Photo Metadata 2025.1 — {nombre_sin_num}. " + " ".join(parrafos)
            salida += fragmentos_de(h.get("id") or slug(titulo), titulo, texto, parrafos, base,
                                    encabezado=f"IPTC Photo Metadata 2025.1 — {nombre_sin_num}")
    return salida


COLECTABLES = ("p", "li", "td", "dd", "dt", "figcaption", "pre", "blockquote")


def _secciones_por_encabezado(main: Tag, niveles: tuple[str, ...]) -> list[tuple[str, list[str]]]:
    """Recorre `main` en orden y agrupa bajo el encabezado más reciente el texto de los elementos de bloque más
    externos (un <p> dentro de un <li> no se cuenta dos veces)."""
    secciones: list[tuple[str, list[str]]] = []
    actual: tuple[str, list[str]] | None = None
    for nodo in main.find_all(list(niveles) + list(COLECTABLES)):
        if nodo.name in niveles:
            actual = (limpiar(nodo.get_text(" ")), [])
            secciones.append(actual)
        elif actual is not None and nodo.find_parent(list(COLECTABLES)) is None:
            t = limpiar(nodo.get_text(" "))
            if len(t) > 25:
                actual[1].append(t)
    return [(t, p) for t, p in secciones if p]


EXCLUIR = re.compile(r"help improve|related resources|other w3c resources|back to top|contact|share|translations|"
                     r"status|table of contents", re.I)


def analizar_w3c(html: str, base: dict, prefijo_id: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    main = soup.find("main") or soup.body
    for basura in main.find_all(["nav", "script", "style", "aside", "footer", "form"]):
        basura.decompose()
    titulo_pagina = limpiar((main.find("h1") or soup.title).get_text(" "))
    salida = []
    # El h1 abre la primera sección: en varias páginas del tutorial (índice, consejos, árbol de decisión) el
    # contenido principal está entre el h1 y el primer h2.
    for titulo, parrafos in _secciones_por_encabezado(main, ("h1", "h2", "h3")):
        if EXCLUIR.search(titulo):
            continue
        es_intro = titulo == titulo_pagina
        texto = (f"{titulo_pagina}. " if es_intro else f"{titulo_pagina} — {titulo}. ") + " ".join(parrafos)
        seccion = titulo_pagina if es_intro else f"{titulo_pagina} › {titulo}"
        salida += fragmentos_de(f"{prefijo_id}{'introduccion' if es_intro else slug(titulo)}", seccion, texto,
                                parrafos, base, encabezado=titulo_pagina if es_intro else f"{titulo_pagina} — {titulo}")
    return salida


def analizar_dcmi(html: str, base: dict) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    salida = []
    for art in soup.find_all("article", id=True):
        tokens = [t for t in (limpiar(x) for x in art.get_text("|").split("|")) if t]

        def valor(etiqueta: str) -> str | None:
            return tokens[tokens.index(etiqueta) + 1] if etiqueta in tokens and tokens.index(etiqueta) + 1 < len(tokens) else None

        definicion = valor("Definition")
        if not definicion:
            continue
        etiqueta, comentario, uri = valor("Label") or art["id"], valor("Comment"), valor("URI")
        texto = f"DCMI Metadata Terms — {etiqueta} ({uri or art['id']}). Definition: {definicion}"
        if comentario and comentario not in ("Subproperty of", "Note"):
            texto += f" Comment: {comentario}"
        salida += fragmentos_de(art["id"], f"DCMI › {etiqueta}", texto, [texto], base,
                                encabezado=f"DCMI Metadata Terms — {etiqueta}")
    return salida


def analizar_tesauro(ruta_ttl: Path) -> tuple[list[dict], dict]:
    from rdflib import Graph
    from rdflib.namespace import RDF, SKOS
    g = Graph()
    g.parse(ruta_ttl, format="turtle")
    conceptos, descartados = [], 0

    def idioma(objetos, lengua: str) -> list[str]:
        return sorted({limpiar(str(o)) for o in objetos if getattr(o, "language", None) == lengua})

    for c in g.subjects(RDF.type, SKOS.Concept):
        pref = idioma(g.objects(c, SKOS.prefLabel), "es")
        if not pref:
            descartados += 1
            continue
        alt, nota = idioma(g.objects(c, SKOS.altLabel), "es"), idioma(g.objects(c, SKOS.scopeNote), "es")
        texto = f"{pref[0]}." + (f" Sinónimos: {', '.join(alt)}." if alt else "") + (f" {' '.join(nota)}" if nota else "")
        # Las etiquetas en inglés NO se indexan (el texto embebido es solo en español); sirven como verdad de
        # referencia para evaluar el mapeo etiqueta de Open Images (inglés) → concepto (evaluacion/r3_embeddings).
        en = idioma(g.objects(c, SKOS.prefLabel), "en") + idioma(g.objects(c, SKOS.altLabel), "en")
        conceptos.append({"uri": str(c), "etiqueta_es": pref[0], "alternativas_es": alt,
                          "nota_alcance": " ".join(nota), "texto": texto.strip(), "etiquetas_en": en})
    conceptos.sort(key=lambda x: x["uri"])
    return conceptos, {"conceptos_totales": len(conceptos) + descartados, "con_etiqueta_es": len(conceptos),
                       "descartados_sin_es": descartados}


def main() -> None:
    t0 = time.perf_counter()
    fuentes = cargar_fuentes()["corpus"]
    man = Manifiesto("corpus")
    normas: list[dict] = []
    documentos = []
    for f in fuentes["normas"]:
        for i, url in enumerate(f["urls"]):
            archivo = f"corpus/crudos/{f['id']}-{i + 1:02d}.html"
            descargar(url, archivo, man)
            html = (DATA / archivo).read_text(encoding="utf-8", errors="replace")
            base = {"id": f["id"], "fuente": f["fuente"], "url": url, "licencia": f["licencia"]}
            if f["tipo"] == "iptc":
                frags = analizar_iptc(html, base)
            elif f["tipo"] == "dcmi":
                frags = analizar_dcmi(html, base)
            else:
                prefijo = "" if f["tipo"] == "wcag" else (url.rstrip("/").rsplit("/", 1)[-1] + "/" if i else "")
                frags = analizar_w3c(html, base, prefijo)
            normas += frags
            documentos.append({"fuente": f["fuente"], "url": url, "fragmentos": len(frags),
                               "caracteres": sum(len(x["texto"]) for x in frags)})
            registro(f"{f['id']} · {url.rsplit('/', 2)[-2] if url.endswith('/') else url.rsplit('/', 1)[-1]}: {len(frags)} fragmentos")
    # ids únicos (un mismo ancla podría repetirse entre páginas)
    vistos: dict[str, int] = {}
    for fr in normas:
        if fr["id"] in vistos:
            vistos[fr["id"]] += 1
            fr["id"] = f"{fr['id']}-{vistos[fr['id']]}"
        else:
            vistos[fr["id"]] = 1

    t = fuentes["tesauro"]
    descargar(t["url"], t["archivo"], man)
    conceptos, info_tesauro = analizar_tesauro(DATA / t["archivo"])
    registro(f"tesauro: {info_tesauro}")

    contenido = json.dumps([normas, conceptos], ensure_ascii=False, sort_keys=True)
    version = hashlib.sha256(contenido.encode("utf-8")).hexdigest()[:12]
    for fr in normas:
        fr["version_corpus"] = version
    CORPUS.mkdir(parents=True, exist_ok=True)
    with open(CORPUS / "normas.jsonl", "w", encoding="utf-8") as fh:
        for fr in normas:
            fh.write(json.dumps(fr, ensure_ascii=False) + "\n")
    with open(CORPUS / "tesauro.jsonl", "w", encoding="utf-8") as fh:
        for c in conceptos:
            fh.write(json.dumps({**c, "licencia": t["licencia"], "version_corpus": version}, ensure_ascii=False) + "\n")
    json_guardar(CORPUS / "version.json", {"version_corpus": version, "generado": ahora_iso()})

    longitudes = [len(x["texto"]) for x in normas]
    caracteres = sum(longitudes)
    reporte = {
        "fecha": ahora_iso(), "version_corpus": version,
        "documentos_fuente_sin_tesauro": len(documentos), "fragmentos": len(normas),
        "caracteres_sin_tesauro": caracteres, "paginas_aprox_sin_tesauro": round(caracteres / 2000, 1),
        "criterio_r1": "20 documentos o 50 páginas como mínimo (2,000 caracteres = 1 página), sin contar el tesauro",
        "cumple_r1": len(documentos) >= 20 or caracteres / 2000 >= 50,
        "longitud_fragmentos": {"min": min(longitudes), "max": max(longitudes),
                                "media": round(sum(longitudes) / len(longitudes), 1),
                                "en_300_800": sum(300 <= x <= 800 for x in longitudes),
                                "menores_300": sum(x < 300 for x in longitudes), "mayores_800": sum(x > 800 for x in longitudes)},
        "por_documento": documentos, "tesauro": info_tesauro,
        "nota": "El corpus de fotos (Crossmodal-3600, 3,600 imágenes con descripciones) se cuenta aparte",
    }
    json_guardar(EVAL / "resultados" / "corpus_r1.json", reporte)
    registro(f"normas: {len(normas)} fragmentos, {reporte['paginas_aprox_sin_tesauro']} páginas aprox. · "
             f"R1 {'cumple' if reporte['cumple_r1'] else 'NO cumple'} · versión {version} · "
             f"{(time.perf_counter() - t0):.0f} s")


if __name__ == "__main__":
    main()
