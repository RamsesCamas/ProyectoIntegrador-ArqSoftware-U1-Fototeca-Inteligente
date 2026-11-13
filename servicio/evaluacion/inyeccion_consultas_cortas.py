"""Falsos positivos de `inyeccion_texto` en búsquedas normales, antes y después del mínimo de palabras (ADR-05).

    python -m evaluacion.inyeccion_consultas_cortas

τ_inyeccion (0.8392) se calibró con 300 descripciones completas del archivo como negativos
(`calibracion_h5.json`). Las búsquedas reales suelen ser más cortas, y en textos cortos la similitud de embeddings con
los prototipos de inyección sube. El E2E bloqueó una consulta de 4 palabras armada con el titular generado. Este
módulo mide el componente `verificar_inyeccion` (los mismos embeddings, prototipos y umbral del servicio, sin llamar a
los modelos de lenguaje) con dos reglas:

- **antes:** la similitud decide con cualquier largo (`min_palabras` = 0).
- **después:** la similitud solo decide desde `guardrails.min_palabras_similitud_inyeccion` palabras (5, el largo
  mínimo de las frases de inyección de calibración); las consultas más cortas pasan solo por los patrones.

Negativos: 300 descripciones humanas de fotos del archivo que no se usaron al calibrar τ ni en la exploración que
encontró el problema (semilla 2026 + 5), en cuatro formas: la frase completa, sus 4 primeras palabras de 4 letras o
más (como arma la consulta el E2E), las 2 primeras y la primera. También las consultas normales de
`consultas_guardrail` y las dos de la demo. Positivos: las 15 frases de `calibracion_inyeccion_texto` y las 10
inyecciones de `consultas_guardrail`. Escribe `evaluacion/resultados/inyeccion_consultas_cortas.json`.
"""
from __future__ import annotations

import random
import re

import numpy as np

from evaluacion.calidad import indice_xm
from evaluacion.comun import guardar_resultado, leer_conjunto, particiones, registro
from fototeca.dominio.errores import BloqueadoPorGuardrail
from fototeca.guardrails.entrada.texto import palabras, sanitizar_pii, verificar_inyeccion

SEMILLA = 2026
N_NEGATIVOS = 300
CONSULTAS_DEMO = ["mercado con frutas", "personas cargando canastas en un mercado, sin vehículos"]


def _bloqueada(texto: str, vector, protos, umbral: float, min_palabras: int) -> bool:
    try:
        verificar_inyeccion(texto, vector, protos, umbral, min_palabras)
        return False
    except BloqueadoPorGuardrail:
        return True


def _negativos() -> list[str]:
    """Descripciones del archivo fuera de la muestra de calibración (scripts/calibrar.py, h5) y de la exploración."""
    archivo = particiones()["archivo"]
    usadas = set(random.Random(SEMILLA + 1).sample(archivo, 400)[:300]) | set(random.Random(777).sample(archivo, 200))
    libres = sorted(set(archivo) - usadas)
    indice = indice_xm()
    return [indice[d]["es"][0] for d in random.Random(SEMILLA + 5).sample(libres, N_NEGATIVOS)]


def _formas(descripcion: str) -> dict[str, str]:
    largas = re.findall(r"\w{4,}", descripcion)
    return {"frase_completa": descripcion, "4_palabras": " ".join(largas[:4]) or "fotografía",
            "2_palabras": " ".join(largas[:2]) or "fotografía", "1_palabra": (largas or ["fotografía"])[0]}


def ejecutar(c) -> dict:
    umbral = float(c.config.parametro("guardrails.tau_inyeccion"))
    minimo = int(c.config.parametro("guardrails.min_palabras_similitud_inyeccion", 5))
    protos = c.contenedor.verificador_imagen.prototipos("inyeccion")
    consultas = leer_conjunto("consultas_guardrail")["items"]

    grupos: dict[str, list[tuple[str, str]]] = {}
    for i, d in enumerate(_negativos()):
        for forma, texto in _formas(d).items():
            grupos.setdefault(forma, []).append((f"neg-{i:03d}", texto))
    grupos["consultas_normales_guardrail"] = [(it["id"], it["texto"]) for it in consultas if it["tipo"] == "normal"]
    grupos["consultas_demo"] = [(f"demo-{i}", t) for i, t in enumerate(CONSULTAS_DEMO, 1)]
    positivos = {"calibracion_inyeccion_texto": [(f"cal-{i:02d}", it["texto"]) for i, it in
                                                 enumerate(leer_conjunto("calibracion_inyeccion_texto")["items"], 1)],
                 "consultas_guardrail_inyeccion": [(it["id"], it["texto"]) for it in consultas if it["tipo"] == "inyeccion"]}

    filas, metricas = [], {"negativos": {}, "positivos": {}}
    for clase, conjunto in (("negativos", grupos), ("positivos", positivos)):
        for grupo, items in conjunto.items():
            textos = [sanitizar_pii(t)[0] for _, t in items]       # como en la búsqueda: primero se enmascaran datos
            vectores = c.contenedor.embebedor.embeber_textos(textos, rol="simetrico")
            similitudes = np.max(vectores @ protos.T, axis=1)
            antes = [_bloqueada(t, v, protos, umbral, 0) for t, v in zip(textos, vectores)]
            despues = [_bloqueada(t, v, protos, umbral, minimo) for t, v in zip(textos, vectores)]
            solo_patrones = [_bloqueada(t, None, None, umbral, minimo) for t in textos]
            for (ident, _), t, s, a, d in zip(items, textos, similitudes, antes, despues):
                filas.append({"clase": clase, "grupo": grupo, "id": ident, "texto": t, "palabras": palabras(t),
                              "similitud": round(float(s), 4), "bloqueada_antes": a, "bloqueada_despues": d})
            n = len(textos)
            metricas[clase][grupo] = {
                "n": n, "palabras_p50": float(np.median([palabras(t) for t in textos])),
                "similitud": {"p50": round(float(np.median(similitudes)), 4),
                              "p95": round(float(np.percentile(similitudes, 95)), 4),
                              "max": round(float(np.max(similitudes)), 4)},
                "bloqueadas_antes": int(sum(antes)), "tasa_antes": round(sum(antes) / n, 4),
                "bloqueadas_despues": int(sum(despues)), "tasa_despues": round(sum(despues) / n, 4),
                "bloqueadas_solo_por_patrones": int(sum(solo_patrones)),
            }
            if clase == "negativos":
                metricas[clase][grupo]["ejemplos_bloqueados_antes"] = [t for t, a in zip(textos, antes) if a][:5]
            registro(f"{clase}/{grupo}: bloqueadas {sum(antes)} → {sum(despues)} de {n}")

    configuracion = {"tau_inyeccion": umbral, "min_palabras_similitud_inyeccion": minimo, "n_prototipos": int(len(protos)),
                     "semilla_negativos": SEMILLA + 5, "nota": "componente sin modelos de lenguaje; no usa --fraccion"}
    guardar_resultado("inyeccion_consultas_cortas", metricas, detalle=filas, configuracion=configuracion, cliente=c)
    return metricas


def main() -> None:
    from evaluacion.comun import ClienteEval
    ejecutar(ClienteEval())


if __name__ == "__main__":
    main()
