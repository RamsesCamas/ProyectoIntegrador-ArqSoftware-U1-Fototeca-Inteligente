"""Ejecuta la evaluación completa en orden, mide el tiempo de cada módulo y sigue aunque uno falle.

    python -m evaluacion.ejecutar_todo                          # todo
    python -m evaluacion.ejecutar_todo --rapido                 # prueba de humo: tamaños a la cuarta parte
    python -m evaluacion.ejecutar_todo --solo guardrails,cache  # solo esos módulos (en el orden de abajo)
    python -m evaluacion.ejecutar_todo --desde cache            # de ese módulo en adelante

Orden: r3_embeddings, r3_modelos, rag_fichas, enrutador, agente, guardrails, cache, aprendizaje (el último que genera
fichas: promueve ejemplos validados y cambiaría el RAG de los demás), desempeno (lee las trazas de todo lo anterior),
analizar_revision_manual (solo lee las plantillas del autor) y resumen. Cada módulo expone `ejecutar(c)`; todos son
reanudables, así que volver a correr retoma donde se quedó. Si un módulo falla, se anota con su error y se sigue con el
siguiente. Los tiempos quedan en `evaluacion/resultados/ejecucion_evaluacion.json`.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
import traceback

ORDEN = ["r3_embeddings", "r3_modelos", "rag_fichas", "enrutador", "agente", "guardrails", "cache", "aprendizaje",
         "desempeno", "analizar_revision_manual", "resumen"]
SIN_CLIENTE = {"analizar_revision_manual", "resumen"}     # no necesitan la API


def elegir(solo: str | None, desde: str | None) -> list[str]:
    modulos = list(ORDEN)
    if solo:
        pedidos = [m.strip() for m in solo.split(",") if m.strip()]
        desconocidos = sorted(set(pedidos) - set(ORDEN))
        if desconocidos:
            raise SystemExit(f"Módulos desconocidos: {', '.join(desconocidos)}. Disponibles: {', '.join(ORDEN)}")
        modulos = [m for m in ORDEN if m in pedidos]
    if desde:
        if desde not in ORDEN:
            raise SystemExit(f"Módulo desconocido en --desde: {desde}. Disponibles: {', '.join(ORDEN)}")
        modulos = [m for m in modulos if ORDEN.index(m) >= ORDEN.index(desde)]
    return modulos


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rapido", action="store_true", help="tamaños a la cuarta parte (FOTOTECA_EVAL_RAPIDO=1)")
    ap.add_argument("--solo", help="módulos separados por coma")
    ap.add_argument("--desde", help="empieza en este módulo")
    args = ap.parse_args(argv)
    if args.rapido:
        os.environ["FOTOTECA_EVAL_RAPIDO"] = "1"
    modulos = elegir(args.solo, args.desde)

    # Se importa después de fijar FOTOTECA_EVAL_RAPIDO (los módulos lo leen al ejecutarse).
    from evaluacion.comun import RESULTADOS, ahora, rapido, registro
    registro(f"evaluación · {'RÁPIDA (prueba de humo) · ' if rapido() else ''}módulos: {', '.join(modulos)}")
    ruta_registro = RESULTADOS / "ejecucion_evaluacion.json"
    try:
        historial = json.loads(ruta_registro.read_text(encoding="utf-8")) if ruta_registro.exists() else {}
    except json.JSONDecodeError:
        historial = {}
    historial.setdefault("modulos", {})

    def guardar() -> None:
        historial["actualizado"] = ahora()
        RESULTADOS.mkdir(parents=True, exist_ok=True)
        temporal = ruta_registro.with_name(ruta_registro.name + ".tmp")
        temporal.write_text(json.dumps(historial, ensure_ascii=False, indent=2), encoding="utf-8")
        temporal.replace(ruta_registro)

    cliente, error_cliente = None, None
    if any(m not in SIN_CLIENTE for m in modulos):
        try:
            from evaluacion.comun import ClienteEval
            cliente = ClienteEval()
        except Exception as e:  # noqa: BLE001 — se reporta y siguen los módulos que no lo necesitan
            error_cliente = f"{type(e).__name__}: {e}"
            registro(f"no se pudo crear el cliente de la API: {error_cliente}")

    fallidos = []
    t_total = time.perf_counter()
    for nombre in modulos:
        registro(f"── {nombre} ──")
        inicio, t0 = ahora(), time.perf_counter()
        entrada = {"inicio": inicio, "rapido": rapido()}
        try:
            if cliente is None and nombre not in SIN_CLIENTE:
                raise RuntimeError(f"sin cliente de la API ({error_cliente})")
            modulo = importlib.import_module(f"evaluacion.{nombre}")
            modulo.ejecutar(cliente)
            entrada.update(estado="ok", error=None)
        except KeyboardInterrupt:
            entrada.update(estado="interrumpido", error="KeyboardInterrupt", segundos=round(time.perf_counter() - t0, 1),
                           fin=ahora())
            historial["modulos"][nombre] = entrada
            guardar()
            registro("interrumpido: vuelve a correr con --desde " + nombre + " para retomar")
            return 130
        except Exception as e:  # noqa: BLE001 — se anota y se sigue con el siguiente módulo
            entrada.update(estado="error", error=f"{type(e).__name__}: {e}"[:500],
                           traza=traceback.format_exc(limit=6)[-3000:])
            fallidos.append(nombre)
            registro(f"   ERROR en {nombre}: {entrada['error']}")
        entrada.update(fin=ahora(), segundos=round(time.perf_counter() - t0, 1))
        historial["modulos"][nombre] = entrada
        guardar()
        registro(f"   {nombre}: {entrada['estado']} en {entrada['segundos'] / 60:.1f} min")

    registro(f"evaluación terminada en {(time.perf_counter() - t_total) / 60:.1f} min · "
             f"{len(modulos) - len(fallidos)} ok · {len(fallidos)} con error" + (f" ({', '.join(fallidos)})" if fallidos else ""))
    return 1 if fallidos else 0


if __name__ == "__main__":
    sys.exit(main())
