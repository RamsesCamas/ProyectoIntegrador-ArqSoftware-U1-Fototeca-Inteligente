"""Fragmentación de documentos normativos y extracción de texto de varios formatos (C5; ADR-06).

Regla (ADR-06): una regla o un campo por fragmento, porque son unidades atómicas; objetivo de
300–800 caracteres sin solapamiento. Si una sección supera 1,200 caracteres, se divide por párrafos con un
solapamiento del 15 %. La usan `scripts/preparar_corpus.py` y la ingesta por la API (`POST /documentos`, tipo
norma), así que hay una sola implementación.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass

MAX_SECCION, OBJETIVO_MAX, SOLAPE = 1200, 800, 0.15
FORMATOS_NORMA = {"html", "htm", "md", "markdown", "pdf", "txt"}


def limpiar(texto: str) -> str:
    return re.sub(r"\s+", " ", (texto or "").replace(" ", " ")).strip()


def slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", texto.lower()).strip("-")[:60] or "seccion"


def dividir(texto: str, parrafos: list[str] | None = None, encabezado: str | None = None) -> list[str]:
    """Una sección de 1,200 caracteres o menos es un fragmento. Si es mayor, se divide por párrafos (≤800) y cada
    fragmento repite el final del anterior (15 %), cortado en un límite de palabra.

    Con `encabezado` (p. ej. «Norma — sección»), cada fragmento que no empiece con él lo lleva al inicio, para que
    un fragmento suelto conserve de qué norma y sección viene al recuperarse."""
    partes = _dividir(texto, parrafos)
    if encabezado:
        partes = [p if p.startswith(encabezado) else f"{encabezado}. {p}" for p in partes]
    return partes


def _dividir(texto: str, parrafos: list[str] | None) -> list[str]:
    if len(texto) <= MAX_SECCION:
        return [texto]
    partes: list[str] = []
    actual = ""
    for p in (parrafos or re.split(r"(?<=[.!?])\s+", texto)):
        while len(p) > OBJETIVO_MAX:   # párrafo gigante: se corta por oración o por palabra
            corte = max(p.rfind(". ", 0, OBJETIVO_MAX), p.rfind(" ", 0, OBJETIVO_MAX))
            corte = corte if corte > 200 else OBJETIVO_MAX
            if actual:
                partes.append(actual)
                actual = ""
            partes.append(p[:corte + 1].strip())
            p = p[corte + 1:].strip()
        if actual and len(actual) + len(p) + 1 > OBJETIVO_MAX:
            partes.append(actual)
            actual = p
        else:
            actual = f"{actual} {p}".strip()
    if actual:
        partes.append(actual)
    con_solape = [partes[0]]
    for previo, siguiente in zip(partes, partes[1:]):
        cola = previo[-int(len(previo) * SOLAPE):]
        cola = cola[cola.find(" ") + 1:] if " " in cola else cola
        con_solape.append(f"… {cola} {siguiente}".strip())
    return con_solape


@dataclass
class Seccion:
    titulo: str
    parrafos: list[str]


def secciones_de_texto(texto: str, extension: str) -> list[Seccion]:
    """Extrae secciones (título + párrafos) de un documento HTML, Markdown, PDF o texto plano."""
    extension = extension.lower().lstrip(".")
    if extension in ("html", "htm"):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(texto, "lxml")
        cuerpo = soup.find("main") or soup.body or soup
        for basura in cuerpo.find_all(["nav", "script", "style", "aside", "footer", "form", "header"]):
            basura.decompose()
        secciones: list[Seccion] = []
        actual = Seccion(limpiar((soup.title.get_text(" ") if soup.title else "") or "Documento"), [])
        secciones.append(actual)
        for nodo in cuerpo.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "dd", "pre", "blockquote"]):
            if nodo.name in ("h1", "h2", "h3", "h4"):
                actual = Seccion(limpiar(nodo.get_text(" ")), [])
                secciones.append(actual)
            elif nodo.find_parent(["p", "li", "td", "dd", "pre", "blockquote"]) is None:
                t = limpiar(nodo.get_text(" "))
                if len(t) > 25:
                    actual.parrafos.append(t)
        return [s for s in secciones if s.parrafos]
    if extension in ("md", "markdown"):
        secciones = [Seccion("Documento", [])]
        bloque: list[str] = []

        def cerrar():
            if bloque:
                secciones[-1].parrafos.append(limpiar(" ".join(bloque)))
                bloque.clear()

        for linea in texto.splitlines():
            m = re.match(r"^\s{0,3}#{1,6}\s+(.*)", linea)
            if m:
                cerrar()
                secciones.append(Seccion(limpiar(m.group(1)), []))
            elif not linea.strip():
                cerrar()
            else:
                bloque.append(re.sub(r"^\s*[-*+]\s+|^\s*\d+\.\s+", "", linea))
        cerrar()
        return [s for s in secciones if s.parrafos]
    # txt (y el texto ya extraído de un PDF): párrafos separados por líneas en blanco
    parrafos = [limpiar(p) for p in re.split(r"\n\s*\n", texto) if limpiar(p)]
    return [Seccion("Documento", parrafos)] if parrafos else []


def texto_de_pdf(contenido: bytes) -> str:
    from pypdf import PdfReader
    lector = PdfReader(io.BytesIO(contenido))
    return "\n\n".join((pagina.extract_text() or "") for pagina in lector.pages)


def fragmentar_documento(contenido: bytes, extension: str, base: dict) -> list[dict]:
    """Convierte un documento normativo en fragmentos con metadatos (id, fuente, seccion, texto…)."""
    extension = extension.lower().lstrip(".")
    if extension not in FORMATOS_NORMA:
        raise ValueError(f"Formato de norma no soportado: {extension}")
    texto = texto_de_pdf(contenido) if extension == "pdf" else contenido.decode("utf-8", errors="replace")
    fragmentos: list[dict] = []
    for seccion in secciones_de_texto(texto, "txt" if extension == "pdf" else extension):
        cuerpo = f"{seccion.titulo}. " + " ".join(seccion.parrafos)
        for i, parte in enumerate(dividir(cuerpo, seccion.parrafos, encabezado=seccion.titulo)):
            fid = f"{base['id']}#{slug(seccion.titulo)}" + (f"-p{i + 1}" if i else "")
            fragmentos.append({**{k: v for k, v in base.items() if k != "id"}, "id": fid,
                               "seccion": seccion.titulo, "texto": parte})
    vistos: dict[str, int] = {}
    for f in fragmentos:
        if f["id"] in vistos:
            vistos[f["id"]] += 1
            f["id"] = f"{f['id']}-{vistos[f['id']]}"
        else:
            vistos[f["id"]] = 1
    return fragmentos
