"""Web · los colores viven solo en los tokens de :root (web/css/estilos.css) y cumplen el contraste AA.

- Fuera de :root no hay colores literales (hexadecimales, rgb()/hsl() ni nombres de color) en el CSS, en los módulos
  JavaScript ni en los HTML: los componentes y las gráficas usan tokens (`var(--…)`) o clases `.serie-N`.
- Todo `var(--token)` que usan el CSS y el JavaScript está definido en :root (un nombre mal escrito no falla en el
  navegador: simplemente no pinta).
- Los pares de tokens de texto cumplen 4.5:1 y los de componentes (bordes de chips, foco, series de gráficas) 3:1
  (WCAG 2.x, luminancia relativa sRGB).

Lee la web montada en el contenedor `servicio` (FOTOTECA_WEB o /app/web_estatica), como pruebas/test_web_r8.py.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

WEB = Path(os.environ.get("FOTOTECA_WEB", "/app/web_estatica"))

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
    if not (WEB / "css" / "estilos.css").is_file():
        pytest.skip(f"No está montada la carpeta web en {WEB}")
    css = _sin_comentarios_css((WEB / "css" / "estilos.css").read_text(encoding="utf-8"))
    raiz, resto = _bloques_root(css)
    tokens = dict(re.findall(r"--([\w-]+)\s*:\s*([^;]+);", raiz))
    js = {p.name: _sin_comentarios_js(p.read_text(encoding="utf-8")) for p in sorted((WEB / "js").glob("*.js"))}
    html = {p.name: p.read_text(encoding="utf-8") for p in sorted(WEB.glob("*.html"))}
    assert tokens, "estilos.css no define tokens en :root"
    return {"raiz": raiz, "resto": resto, "tokens": tokens, "js": js, "html": html}


def test_css_sin_colores_fuera_de_root(web):
    hallazgos = []
    for n, linea in enumerate(web["resto"].splitlines(), 1):
        if HEX.search(linea) or FUNCION_COLOR.search(linea):
            hallazgos.append(linea.strip())
            continue
        # Nombres de color solo en valores de declaraciones (los selectores pueden contener cualquier palabra)
        for decl in re.findall(r"[\w-]+\s*:\s*[^;{}]+", linea):
            if NOMBRE_COLOR.search(decl.split(":", 1)[1]):
                hallazgos.append(linea.strip())
                break
    assert not hallazgos, "Colores literales fuera de :root en estilos.css:\n" + "\n".join(hallazgos[:20])


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


def test_html_sin_colores_en_linea(web):
    hallazgos = []
    for nombre, texto in web["html"].items():
        if re.search(r"<style\b", texto, re.IGNORECASE):
            hallazgos.append(f"{nombre}: bloque <style>")
        for estilo in re.findall(r"\bstyle\s*=\s*[\"']([^\"']*)", texto, re.IGNORECASE):
            if HEX.search(estilo) or FUNCION_COLOR.search(estilo) or PROPIEDAD_COLOR.search(" " + estilo):
                hallazgos.append(f"{nombre}: style=\"{estilo[:80]}\"")
    assert not hallazgos, "\n".join(hallazgos)


def test_todo_token_usado_esta_definido(web):
    definidos = set(web["tokens"])
    usados = set(re.findall(r"var\(\s*--([\w-]+)", web["resto"] + web["raiz"]))
    for texto in web["js"].values():
        usados |= set(re.findall(r"var\(\s*--([\w-]+)", texto))
    faltan = sorted(usados - definidos)
    assert not faltan, f"Tokens usados pero no definidos en :root: {faltan}"


def test_series_de_graficas_definidas(web):
    """Cada clase .serie-N del CSS tiene su token --grafica-N y comun.js no usa series que no existan."""
    clases = set(re.findall(r"\.serie-(\d+)\b", web["resto"]))
    assert clases, "estilos.css no define clases .serie-N"
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


TEXTO = [  # (primer plano, fondo): texto normal, ≥ 4.5:1
    ("texto", "fondo"), ("texto", "superficie"), ("texto", "superficie-2"), ("texto-suave", "fondo"),
    ("texto-suave", "superficie"), ("texto-suave", "superficie-2"), ("enlace", "fondo"), ("enlace", "superficie"),
    ("enlace", "acento-fondo"), ("acento", "superficie"), ("acento-texto", "acento"), ("acento-texto", "acento-hover"),
    ("texto", "acento-fondo"), ("texto-suave", "acento-fondo"),
    ("cabecera-texto", "cabecera-fondo"), ("cabecera-texto-suave", "cabecera-fondo"), ("cabecera-texto", "nav-hover-fondo@cabecera-fondo"),
    ("nav-activo-texto", "nav-activo-fondo"), ("aviso", "aviso-fondo"), ("aviso", "fondo"), ("ok", "ok-fondo"),
    ("error", "error-fondo"), ("error", "superficie"), ("acento-texto", "error"), ("acento-texto", "error-hover"),
    ("info", "info-fondo"), ("texto", "info-fondo"), ("texto-suave", "info-fondo"), ("texto", "aviso-fondo"),
    ("texto", "chip-fondo"), ("texto", "chip-regla-fondo"), ("texto", "chip-tesauro-fondo"), ("texto", "chip-foto-fondo"),
    ("texto", "chip-archivista-fondo"), ("texto", "chip-referencia-fondo"), ("texto", "chip-etiqueta-fondo"),
    ("enlace", "chip-tesauro-fondo"), ("enlace", "chip-regla-fondo"), ("error", "error-fondo"),
    ("insignia-foto-texto", "insignia-foto-fondo@foto-fondo"), ("pie-texto", "pie-fondo"),
]
COMPONENTES = [  # (primer plano, fondo): bordes, foco y series de gráficas, ≥ 3:1
    ("borde-fuerte", "superficie"), ("borde-fuerte", "superficie-2"), ("acento", "superficie"), ("foco", "fondo"),
    ("foco", "superficie"), ("foco-cabecera", "cabecera-fondo"),
    # Página actual del menú: la pestaña y su subrayado se distinguen de la cabecera
    ("nav-activo-fondo", "cabecera-fondo"), ("nav-activo-borde", "cabecera-fondo"),
    ("chip-borde", "fondo"), ("chip-borde", "superficie"), ("chip-regla-borde", "fondo"), ("chip-tesauro-borde", "fondo"),
    ("chip-foto-borde", "fondo"), ("chip-archivista-borde", "fondo"), ("chip-referencia-borde", "fondo"),
    ("chip-etiqueta-borde", "fondo"), ("error", "superficie"), ("info", "info-fondo"), ("info", "superficie"),
    ("aviso", "aviso-fondo"),
]


def test_contraste_aa_de_los_tokens(web):
    tokens = web["tokens"]
    series = sorted((k for k in tokens if re.fullmatch(r"grafica-\d+", k)), key=lambda k: int(k.split("-")[1]))
    fallas = []
    for minimo, pares in ((4.5, TEXTO), (3.0, COMPONENTES + [(s, "superficie") for s in series] + [(s, "superficie-2") for s in series])):
        for uno, otro in pares:
            r = _razon(tokens, uno, otro)
            if r < minimo:
                fallas.append(f"{uno} sobre {otro}: {r:.2f} < {minimo}")
    assert not fallas, "Pares de tokens bajo el mínimo AA:\n" + "\n".join(fallas)
