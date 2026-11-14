"""Web · los colores viven solo en los tokens de :root de web/css/base.css y cumplen el contraste AA.

- Los tokens (`--nombre: valor`) se definen SOLO en los bloques :root de base.css; ningún otro CSS los define.
- Fuera de esos bloques no hay colores literales (hexadecimales, rgb()/hsl() ni nombres de color) en NINGÚN
  web/css/*.css, en los módulos JavaScript ni en los HTML: los componentes y las gráficas usan tokens (`var(--…)`) o
  clases `.serie-N`.
- Todo `var(--token)` que usan los CSS y el JavaScript está definido en :root de base.css (un nombre mal escrito no
  falla en el navegador: simplemente no pinta).
- Cada página enlaza css/base.css y su propio css/<página>.css; ningún CSS queda huérfano.
- El favicon (SVG en data URI, que el navegador dibuja fuera de la página y no puede leer tokens) solo usa colores que
  son valores de tokens.
- Todo icono que usan los HTML (`#i-nombre`) y el JavaScript (`icono("nombre")`) existe en js/iconos.js.
- Los pares de tokens de texto cumplen 4.5:1 y los de componentes (bordes, foco, iconos con significado, series de
  gráficas) 3:1 (WCAG 2.x, luminancia relativa sRGB), incluidos los de la barra lateral, la montura y la lupa.

Lee la web montada en el contenedor `servicio` (FOTOTECA_WEB o /app/web_estatica), como pruebas/test_web_r8.py.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import unquote

import pytest

WEB = Path(os.environ.get("FOTOTECA_WEB", "/app/web_estatica"))
BASE_CSS = "base.css"
PAGINAS = {"index.html": "inicio", "catalogar.html": "catalogar", "buscar.html": "buscar",
           "duplicados.html": "duplicados", "archivo.html": "archivo", "metricas.html": "metricas"}

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
FUNCION_COLOR = re.compile(r"\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(", re.IGNORECASE)
# Nombres de color de CSS (CSS Color 4). `transparent` y `currentColor` no son colores de la paleta: se permiten.
NOMBRES_COLOR = """aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown
burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan darkgoldenrod
darkgray darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen
darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray dimgrey dodgerblue
firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green greenyellow grey honeydew
hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan
lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen lightskyblue lightslategray
lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine mediumblue mediumorchid
mediumpurple mediumseagreen mediumslateblue mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream
mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid palegoldenrod palegreen
paleturquoise palevioletred papayawhip peachpuff peru pink plum powderblue purple rebeccapurple red rosybrown royalblue
saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen
steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke yellow yellowgreen""".split()
NOMBRE_COLOR = re.compile(r"(?<![\w-])(?:" + "|".join(NOMBRES_COLOR) + r")(?![\w-])", re.IGNORECASE)
PROPIEDAD_COLOR = re.compile(r"(?:^|[;{\s\"'`])(?:color|background(?:-color)?|fill|stroke|border(?:-[a-z]+)*|outline(?:-color)?|"
                             r"box-shadow|text-decoration(?:-color)?|accent-color|caret-color)\s*:", re.IGNORECASE)
DEFINICION_TOKEN = re.compile(r"(?<![\w-])--[\w-]+\s*:")


def _sin_comentarios_css(texto: str) -> str:
    return re.sub(r"/\*.*?\*/", "", texto, flags=re.DOTALL)


def _sin_comentarios_js(texto: str) -> str:
    texto = re.sub(r"/\*.*?\*/", "", texto, flags=re.DOTALL)
    # Comentarios de línea (sin tocar URLs dentro de cadenas: la web no usa «//» en cadenas salvo el espacio de nombres SVG)
    return "\n".join(re.sub(r"(^|[^:\"'`])//.*$", r"\1", linea) for linea in texto.splitlines())


def _bloques_root(css: str) -> tuple[str, str]:
    """Devuelve (contenido de los bloques `:root { … }`, resto del CSS sin esos bloques)."""
    dentro, fuera, i = [], [], 0
    for m in re.finditer(r":root\s*\{", css):
        fuera.append(css[i:m.start()])
        profundidad, j = 1, m.end()
        while profundidad and j < len(css):
            profundidad += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
        dentro.append(css[m.end():j - 1])
        i = j
    fuera.append(css[i:])
    return "\n".join(dentro), "\n".join(fuera)


@pytest.fixture(scope="module")
def web():
    if not (WEB / "css" / BASE_CSS).is_file():
        pytest.skip(f"No está montada la carpeta web en {WEB}")
    css = {p.name: _sin_comentarios_css(p.read_text(encoding="utf-8")) for p in sorted((WEB / "css").glob("*.css"))}
    raiz, resto_base = _bloques_root(css[BASE_CSS])
    tokens = dict(re.findall(r"--([\w-]+)\s*:\s*([^;]+);", raiz))
    resto = {BASE_CSS: resto_base, **{n: t for n, t in css.items() if n != BASE_CSS}}
    js = {p.name: _sin_comentarios_js(p.read_text(encoding="utf-8")) for p in sorted((WEB / "js").glob("*.js"))}
    html = {p.name: p.read_text(encoding="utf-8") for p in sorted(WEB.glob("*.html"))}
    assert tokens, "base.css no define tokens en :root"
    return {"css": css, "raiz": raiz, "resto": resto, "tokens": tokens, "js": js, "html": html}


def test_tokens_solo_en_root_de_base(web):
    hallazgos = []
    for nombre, texto in web["resto"].items():
        if nombre != BASE_CSS and re.search(r":root\b", texto):
            hallazgos.append(f"{nombre}: bloque :root (los tokens van solo en base.css)")
        for linea in texto.splitlines():
            if DEFINICION_TOKEN.search(linea):
                hallazgos.append(f"{nombre}: {linea.strip()[:100]}")
    assert not hallazgos, "Tokens definidos fuera de :root de base.css:\n" + "\n".join(hallazgos[:20])


def test_css_sin_colores_fuera_de_root(web):
    hallazgos = []
    for nombre, texto in web["resto"].items():
        for linea in texto.splitlines():
            if HEX.search(linea) or FUNCION_COLOR.search(linea):
                hallazgos.append(f"{nombre}: {linea.strip()[:120]}")
                continue
            # Nombres de color solo en valores de declaraciones (los selectores pueden contener cualquier palabra)
            for decl in re.findall(r"[\w-]+\s*:\s*[^;{}]+", linea):
                if NOMBRE_COLOR.search(decl.split(":", 1)[1]):
                    hallazgos.append(f"{nombre}: {linea.strip()[:120]}")
                    break
    assert not hallazgos, "Colores literales fuera de :root de base.css:\n" + "\n".join(hallazgos[:20])


def test_js_sin_colores_literales(web):
    hallazgos = []
    for nombre, texto in web["js"].items():
        for n, linea in enumerate(texto.splitlines(), 1):
            if (re.search(r"[\"'`]\s*#[0-9a-fA-F]{3,8}\s*[\"'`]", linea) or FUNCION_COLOR.search(linea)
                    or re.search(r"(?:fill|stroke|color|background)\s*[:=]\s*[\"'`]?\s*#[0-9a-fA-F]{3,8}", linea, re.IGNORECASE)):
                hallazgos.append(f"{nombre}:{n}: {linea.strip()[:120]}")
            # Estilos en línea con color (style: "…color: …" o .style.color/background/fill = …)
            elif re.search(r"\bstyle\s*:\s*[\"'`][^\"'`]*?(?:color|background|fill|stroke)\s*:", linea, re.IGNORECASE) or \
                    re.search(r"\.style\.(?:color|background\w*|fill|stroke|borderColor)\s*=", linea):
                hallazgos.append(f"{nombre}:{n}: {linea.strip()[:120]}")
    assert not hallazgos, "Colores fijos en el JavaScript (usar tokens o clases .serie-N):\n" + "\n".join(hallazgos)


def _favicons(html: str) -> list[str]:
    return [unquote(h) for h in re.findall(r"<link[^>]*rel=\"icon\"[^>]*href=\"(data:image/svg\+xml,[^\"]+)\"", html)]


def test_html_sin_colores_en_linea(web):
    hallazgos = []
    for nombre, texto in web["html"].items():
        if re.search(r"<style\b", texto, re.IGNORECASE):
            hallazgos.append(f"{nombre}: bloque <style>")
        for estilo in re.findall(r"\bstyle\s*=\s*[\"']([^\"']*)", texto, re.IGNORECASE):
            if HEX.search(estilo) or FUNCION_COLOR.search(estilo) or PROPIEDAD_COLOR.search(" " + estilo):
                hallazgos.append(f"{nombre}: style=\"{estilo[:80]}\"")
        # Fuera del favicon (que se revisa aparte), ningún color literal en atributos de SVG en línea
        sin_favicon = re.sub(r"<link[^>]*rel=\"icon\"[^>]*>", "", texto)
        for atributo in re.findall(r"\b(?:fill|stroke|color|stop-color)\s*=\s*\"([^\"]*)\"", sin_favicon):
            if HEX.search(atributo) or FUNCION_COLOR.search(atributo) or NOMBRE_COLOR.search(atributo):
                hallazgos.append(f"{nombre}: atributo de color {atributo}")
    assert not hallazgos, "\n".join(hallazgos)


def test_favicon_solo_con_colores_de_tokens(web):
    """El favicon no puede leer var(--…): cada color que usa debe ser el valor de un token de :root."""
    valores = {v.strip().lower() for v in web["tokens"].values()}
    hallazgos = []
    for nombre, texto in web["html"].items():
        iconos = _favicons(texto)
        if not iconos:
            hallazgos.append(f"{nombre}: sin favicon SVG")
        for svg in iconos:
            for color in HEX.findall(svg):
                if color.lower() not in valores:
                    hallazgos.append(f"{nombre}: el favicon usa {color}, que no es valor de ningún token")
            if FUNCION_COLOR.search(svg):
                hallazgos.append(f"{nombre}: el favicon usa una función de color")
    assert not hallazgos, "\n".join(hallazgos)


def test_todo_token_usado_esta_definido(web):
    definidos = set(web["tokens"])
    usados = set()
    for texto in list(web["css"].values()) + list(web["js"].values()) + list(web["html"].values()):
        usados |= set(re.findall(r"var\(\s*--([\w-]+)", texto))
    faltan = sorted(usados - definidos)
    assert not faltan, f"Tokens usados pero no definidos en :root de base.css: {faltan}"


def test_cada_pagina_enlaza_base_y_su_css(web):
    hallazgos = []
    for pagina, propio in PAGINAS.items():
        texto = web["html"].get(pagina)
        if texto is None:
            hallazgos.append(f"falta {pagina}")
            continue
        hojas = re.findall(r"<link[^>]*rel=\"stylesheet\"[^>]*href=\"([^\"]+)\"", texto)
        if hojas != ["css/base.css", f"css/{propio}.css"]:
            hallazgos.append(f"{pagina}: enlaza {hojas} (se espera base.css y luego {propio}.css)")
        if not (WEB / "css" / f"{propio}.css").is_file():
            hallazgos.append(f"{pagina}: no existe css/{propio}.css")
    huerfanos = set(web["css"]) - {BASE_CSS} - {f"{p}.css" for p in PAGINAS.values()}
    if huerfanos:
        hallazgos.append(f"CSS que no enlaza ninguna página: {sorted(huerfanos)}")
    assert not hallazgos, "\n".join(hallazgos)


def test_iconos_usados_existen(web):
    """Un nombre de icono mal escrito no falla en el navegador: el <use> simplemente no pinta nada."""
    sprite = web["js"].get("iconos.js", "")
    trazos = re.search(r"const TRAZOS\s*=\s*\{(.*?)\n\};", sprite, re.DOTALL)
    ilustraciones = re.search(r"const ILUSTRACIONES\s*=\s*\{(.*?)\n\};", sprite, re.DOTALL)
    assert trazos and ilustraciones, "iconos.js no define TRAZOS e ILUSTRACIONES"
    clave = r"^\s*(?:\"([\w-]+)\"|([\w]+))\s*:"
    nombres = {a or b for a, b in re.findall(clave, trazos.group(1), re.MULTILINE)}
    nombres_il = {a or b for a, b in re.findall(clave, ilustraciones.group(1), re.MULTILINE)}
    assert len(nombres) >= 35, f"iconos.js define solo {len(nombres)} iconos"
    usados = set()
    for texto in web["html"].values():
        usados |= {("i", n) for n in re.findall(r"href=\"#i-([\w-]+)\"", texto)}
    for texto in web["js"].values():
        usados |= {("i", n) for n in re.findall(r"\bicono\(\s*[\"']([\w-]+)[\"']", texto)}
        usados |= {("il", n) for n in re.findall(r"\bilustracion\(\s*[\"']([\w-]+)[\"']", texto)}
    faltan = sorted(f"{t}-{n}" for t, n in usados if n not in (nombres if t == "i" else nombres_il))
    assert not faltan, f"Iconos usados que no existen en iconos.js: {faltan}"


def test_series_de_graficas_definidas(web):
    """Cada clase .serie-N del CSS tiene su token --grafica-N y comun.js no usa series que no existan."""
    clases = set()
    for texto in web["resto"].values():
        clases |= set(re.findall(r"\.serie-(\d+)\b", texto))
    assert clases, "ningún CSS define clases .serie-N"
    assert {f"grafica-{n}" for n in clases} <= set(web["tokens"])
    usadas = set(re.findall(r":\s*(\d+)\b", re.search(r"SERIE_CAPA\s*=\s*\{([^}]*)\}", web["js"]["comun.js"]).group(1)))
    assert usadas <= clases, f"SERIE_CAPA usa series sin clase: {sorted(usadas - clases)}"


# ───────────────────────────── contraste WCAG 2.x sobre los tokens ─────────────────────────────
def _resolver(tokens: dict[str, str], nombre: str, vistos: frozenset = frozenset()) -> str:
    valor = tokens[nombre].strip()
    m = re.fullmatch(r"var\(\s*--([\w-]+)\s*\)", valor)
    if m and m.group(1) not in vistos:
        return _resolver(tokens, m.group(1), vistos | {nombre})
    return valor


def _rgba(valor: str) -> tuple[float, float, float, float]:
    v = valor.strip()
    if v.startswith("#"):
        h = v[1:]
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a
    m = re.fullmatch(r"rgba?\(([^)]*)\)", v)
    if not m:
        raise ValueError(f"color no reconocido: {valor}")
    partes = [float(x) for x in re.split(r"[\s,/]+", m.group(1).strip()) if x]
    return partes[0], partes[1], partes[2], partes[3] if len(partes) > 3 else 1.0


def _color(tokens: dict[str, str], ref: str) -> tuple[float, float, float]:
    """`token` o `token@fondo` (un color con transparencia se mezcla sobre su fondo; sin fondo, sobre blanco)."""
    arriba, _, abajo = ref.partition("@")
    r, g, b, a = _rgba(_resolver(tokens, arriba))
    base = _color(tokens, abajo) if abajo else (255.0, 255.0, 255.0)
    return r * a + base[0] * (1 - a), g * a + base[1] * (1 - a), b * a + base[2] * (1 - a)


def _luminancia(c: tuple[float, float, float]) -> float:
    def lineal(v: float) -> float:
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (lineal(x) for x in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _razon(tokens, uno: str, otro: str) -> float:
    a, b = _luminancia(_color(tokens, uno)), _luminancia(_color(tokens, otro))
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


TIPOS_CHIP = ["regla", "tesauro", "foto", "archivista", "referencia", "etiqueta"]
TEXTO = [  # (primer plano, fondo): texto normal, ≥ 4.5:1
    ("texto", "fondo"), ("texto", "superficie"), ("texto", "superficie-2"), ("texto-suave", "fondo"),
    ("texto-suave", "superficie"), ("texto-suave", "superficie-2"), ("enlace", "fondo"), ("enlace", "superficie"),
    ("enlace", "acento-fondo"), ("acento", "superficie"), ("acento", "acento-fondo"), ("acento-texto", "acento"),
    ("acento-texto", "acento-hover"), ("texto", "acento-fondo"), ("texto-suave", "acento-fondo"),
    ("cabecera-texto", "cabecera-fondo"), ("cabecera-texto-suave", "cabecera-fondo"), ("cabecera-texto", "nav-hover-fondo@cabecera-fondo"),
    ("nav-activo-texto", "nav-activo-fondo"), ("aviso", "aviso-fondo"), ("aviso", "fondo"), ("aviso", "superficie"),
    ("ok", "ok-fondo"), ("error", "error-fondo"), ("error", "superficie"), ("acento-texto", "error"), ("acento-texto", "error-hover"),
    ("info", "info-fondo"), ("texto", "info-fondo"), ("texto-suave", "info-fondo"), ("texto", "aviso-fondo"),
    ("texto", "chip-fondo"), ("texto-suave", "chip-fondo"), *[("texto", f"chip-{t}-fondo") for t in TIPOS_CHIP],
    *[("texto-suave", f"chip-{t}-fondo") for t in TIPOS_CHIP],   # puntaje en mono dentro del chip
    ("enlace", "chip-tesauro-fondo"), ("enlace", "chip-regla-fondo"),
    ("insignia-foto-texto", "insignia-foto-fondo@foto-fondo"), ("insignia-foto-texto", "insignia-foto-fondo@lupa-fondo"),
    ("pie-texto", "pie-fondo"),
    # v3: barra lateral (y barra superior), cabeceras de panel, montura, lupa, mesa de luz y control segmentado
    ("lateral-texto", "lateral-fondo"), ("lateral-texto-suave", "lateral-fondo"),
    ("lateral-texto", "lateral-activo-fondo@lateral-fondo"), ("lateral-texto-suave", "lateral-activo-fondo@lateral-fondo"),
    ("texto", "panel-cabecera-fondo"), ("texto-suave", "panel-cabecera-fondo"), ("enlace", "panel-cabecera-fondo"),
    ("texto", "montura"), ("texto-suave", "montura"), ("lupa-texto", "lupa-fondo"), ("lupa-texto-suave", "lupa-fondo"),
    ("texto", "mesa-fondo"), ("texto-suave", "mesa-fondo"), ("acento", "mesa-fondo"), ("superficie", "texto"),
    ("texto-suave", "esqueleto-fondo"),
]
COMPONENTES = [  # (primer plano, fondo): bordes, foco, indicadores e iconos con significado, ≥ 3:1
    ("borde-fuerte", "superficie"), ("borde-fuerte", "superficie-2"), ("borde-fuerte", "mesa-fondo"), ("acento", "superficie"),
    ("foco", "fondo"), ("foco", "superficie"), ("foco", "aviso-fondo"), ("foco", "info-fondo"), ("foco", "panel-cabecera-fondo"),
    ("foco-cabecera", "cabecera-fondo"), ("foco-cabecera", "lateral-fondo"), ("foco-cabecera", "lupa-fondo"),
    # Página actual del menú: el indicador naranja y el fondo activo se distinguen del grafito
    ("nav-activo-fondo", "cabecera-fondo"), ("nav-activo-borde", "cabecera-fondo"), ("lateral-marca", "lateral-fondo"),
    ("lateral-marca", "lateral-activo-fondo@lateral-fondo"),
    ("chip-borde", "fondo"), ("chip-borde", "superficie"), ("chip-borde", "chip-fondo"),
    *[(f"chip-{t}-borde", "fondo") for t in TIPOS_CHIP], *[(f"chip-{t}-borde", f"chip-{t}-fondo") for t in TIPOS_CHIP],
    ("error", "superficie"), ("info", "info-fondo"), ("info", "superficie"), ("aviso", "aviso-fondo"), ("aviso", "superficie"),
    # Medidor (relleno contra su pista) y segmento elegido del control segmentado
    ("ok", "grafica-pista"), ("aviso", "grafica-pista"), ("error", "grafica-pista"), ("texto", "superficie"),
]


def test_contraste_aa_de_los_tokens(web):
    tokens = web["tokens"]
    series = sorted((k for k in tokens if re.fullmatch(r"grafica-\d+", k)), key=lambda k: int(k.split("-")[1]))
    graficas = [(s, f) for s in series for f in ("superficie", "superficie-2", "grafica-pista")]
    fallas = []
    for minimo, pares in ((4.5, TEXTO), (3.0, COMPONENTES + graficas)):
        for uno, otro in pares:
            r = _razon(tokens, uno, otro)
            if r < minimo:
                fallas.append(f"{uno} sobre {otro}: {r:.2f} < {minimo}")
    assert not fallas, "Pares de tokens bajo el mínimo AA:\n" + "\n".join(fallas)
