"""Calibra τ_excluir: el coseno desde el que una búsqueda penaliza una ficha por parecerse a lo que se pidió excluir.

    docker compose run --rm servicio python -m scripts.calibrar_tau_excluir

En la búsqueda compleja (`flujo_busqueda._recuperar`), una ficha se penaliza (× 0.5) si contiene literalmente el
término excluido o si el coseno entre el término (EmbeddingGemma-2, rol «consulta») y el vector `#descripcion` de la
ficha en `fotos_txt` llega a τ_excluir. Hasta ahora τ_excluir valía 0.6 por omisión, sin calibrar: con «personas
cargando canastas en un mercado, sin vehículos» se penalizaban los 12 resultados, aunque casi ninguno tenga vehículos.

Para varios términos de exclusión típicos mide ese coseno contra TODAS las fichas del archivo (xm-…) y lo cruza con
una etiqueta por palabras clave en el texto de la ficha (titular, descripción, texto alternativo y palabras clave):
- por término: AUC, la fracción de fichas SIN el término que se penalizarían (falsos positivos) y la de fichas CON el
  término (aciertos) a varios umbrales, y el percentil 95 de los cosenos de las fichas sin el término;
- regla fijada antes de ver los datos: τ_excluir = el máximo, entre términos, de ese percentil 95, redondeado hacia
  arriba a la centésima. Así ningún término penaliza a más del 5 % de las fichas que no lo tienen; la coincidencia
  literal del término sigue penalizando aparte.

Solo lee: no escribe en el archivo, la caché ni la base vectorial. Escribe evaluacion/resultados/calibracion_tau_excluir.json.
"""
from __future__ import annotations

import math
import re

import numpy as np

from fototeca.api.arranque import cargar_configuracion, construir_contenedor
from fototeca.dominio import colecciones as col
from scripts._descargas import EVAL, ahora_iso, json_guardar, registro

SALIDA = EVAL / "resultados" / "calibracion_tau_excluir.json"
UMBRALES = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]
PERCENTIL = 95

# Etiqueta por palabras clave (aproximada): qué fichas «tienen» lo que se pide excluir
TERMINOS = {
    "vehículos": r"autos?|carros?|coches?|cami[oó]n|camiones|camionetas?|autob[uú]s(es)?|motos?|motocicletas?|"
                 r"bicicletas?|taxis?|tractor(es)?|tren(es)?|tranv[ií]as?|veh[ií]culos?|furgonetas?|jeeps?|buggys?",
    "animales": r"animal(es)?|perr[oa]s?|gat[oa]s?|caball[oa]s?|vacas?|ovejas?|cabras?|cerd[oa]s?|p[aá]jar[oa]s?|aves?|"
                r"patos?|gallinas?|pez|peces|elefantes?|monos?|llamas?|alpacas?|burr[oa]s?|camellos?|ardillas?|"
                r"conejos?|osos?|leones?|tigres?|ciervos?|venados?|insectos?|mariposas?|abejas?",
    "comida": r"comida|alimentos?|frutas?|verduras?|pan(es)?|pasteles?|postres?|carnes?|sopas?|tacos?|pizzas?|"
              r"ensaladas?|desayunos?|dulces?|galletas?|quesos?|arroz|platillos?",
    "agua": r"agua|mar|r[ií]os?|lagos?|playas?|oc[eé]anos?|cascadas?|lluvia|piscinas?|estanques?|olas?",
    "edificios": r"edificios?|casas?|iglesias?|catedral(es)?|torres?|rascacielos|templos?|castillos?|palacios?|"
                 r"fachadas?|museos?|hoteles?",
    "nieve": r"nieve|nevad[oa]s?|nevando",
}


def _auc(pos: np.ndarray, neg: np.ndarray) -> float:
    """AUC por Mann-Whitney: probabilidad de que una ficha con el término tenga más coseno que una sin él."""
    todos = np.concatenate([pos, neg])
    rangos = todos.argsort().argsort() + 1.0
    return float((rangos[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def main() -> None:
    config = cargar_configuracion()
    c = construir_contenedor(config)
    vectores = {i[: -len("#descripcion")]: v for i, v, _ in c.almacen_vectorial.vectores_por_filtro(col.FOTOS_TXT)
                if i.startswith("xm-") and i.endswith("#descripcion")}
    textos = {}
    for doc in sorted(vectores):
        reg = c.almacen_documentos.obtener_ficha(doc)
        if reg is not None:
            f = reg.ficha
            textos[doc] = " ".join([f.titular, f.descripcion, f.texto_alternativo] + [x.termino for x in f.palabras_clave])
    ids = sorted(textos)
    matriz = np.stack([vectores[i] for i in ids])
    registro(f"{len(ids)} fichas del archivo con vector #descripcion")

    por_termino, percentiles, medidos = {}, [], {}
    for termino, patron in TERMINOS.items():
        v = c.embebedor.embeber_textos([termino], rol="consulta")[0]
        cos = matriz @ v
        etiqueta = np.array([bool(re.search(rf"\b({patron})\b", textos[i], re.I)) for i in ids])
        pos, neg = cos[etiqueta], cos[~etiqueta]
        medidos[termino] = (pos, neg)
        p95 = float(np.percentile(neg, PERCENTIL))
        percentiles.append(p95)
        por_termino[termino] = {
            "fichas_con_termino": int(etiqueta.sum()), "fichas_sin_termino": int((~etiqueta).sum()),
            "auc": round(_auc(pos, neg), 3),
            "coseno_mediana_con": round(float(np.median(pos)), 3), "coseno_mediana_sin": round(float(np.median(neg)), 3),
            f"percentil_{PERCENTIL}_sin": round(p95, 3),
            "por_umbral": {f"{u:.2f}": {"penaliza_sin_termino": round(float((neg >= u).mean()), 3),
                                         "penaliza_con_termino": round(float((pos >= u).mean()), 3)} for u in UMBRALES},
        }
        registro(f"{termino}: AUC {por_termino[termino]['auc']} · p{PERCENTIL} sin el término {p95:.3f} · "
                 f"a 0.60 penaliza {por_termino[termino]['por_umbral']['0.60']['penaliza_sin_termino']:.0%} de las fichas sin él")

    tau = math.ceil(max(percentiles) * 100) / 100
    con_tau = {t: {"penaliza_sin_termino": round(float((neg >= tau).mean()), 3),
                   "penaliza_con_termino": round(float((pos >= tau).mean()), 3)} for t, (pos, neg) in medidos.items()}
    json_guardar(SALIDA, {
        "modulo": "calibracion_tau_excluir",
        "fecha": ahora_iso(),
        "descripcion": __doc__.strip().splitlines()[0],
        "metodo": ("coseno entre el término excluido (embedding de consulta) y el vector #descripcion de cada ficha del "
                   "archivo; etiqueta por palabras clave en titular, descripción, texto alternativo y palabras clave"),
        "regla": f"τ_excluir = máximo entre términos del percentil {PERCENTIL} de las fichas sin el término, hacia arriba a 0.01",
        "modelo_embedding": config.modelos.get("embedding"),
        "fichas": len(ids),
        "tau_anterior": 0.6,
        "tau_excluir": tau,
        "penalizacion_sin_termino_con_tau": con_tau,
        "por_termino": por_termino,
    })
    registro(f"τ_excluir = {tau} → {SALIDA}")


if __name__ == "__main__":
    main()
