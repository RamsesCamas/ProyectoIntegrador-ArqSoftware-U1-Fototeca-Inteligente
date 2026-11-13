"""Banco de ajuste de prompts (H4): genera fichas por las dos rutas para las 10 fotos de `ajuste_prompts`.

    python -m scripts.ajustar_prompts [--etiqueta v1] [--rutas rapida,completa]

`ajuste_prompts` son 10 fotos de `nuevas` reservadas para este fin (nunca `eval_fichas`, para que la evaluación quede fuera de muestra). Por
cada foto y ruta guarda la ficha, las referencias humanas, la similitud granite del texto alternativo con ellas,
si el JSON fue válido a la primera (eventos C6 de la traza), los guardrails de salida y la latencia. Sirve para
decidir ajustes de redacción de P1–P3, que se registran subiendo la versión del prompt. Escribe
`evaluacion/resultados/ajuste_prompts_<etiqueta>.json`; las fotos se eliminan al final.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter

import numpy as np
from fastapi.testclient import TestClient

from fototeca.api.arranque import cargar_configuracion, construir_contenedor, crear_app
from fototeca.modelos.plantillas import versiones
from scripts._descargas import EVAL, ahora_iso, json_guardar, registro
from scripts._xm3600 import cargar_indice


def valido_a_la_primera(eventos, tarea: str) -> bool | None:
    llamadas = [e for e in eventos if e.capa == "C6" and e.evento == "llamada_modelo" and (e.detalle or {}).get("tarea") == tarea]
    if not llamadas:
        return None
    primera = llamadas[0]
    return primera.resultado == "ok" and (primera.detalle or {}).get("intento") == 1 and not (primera.detalle or {}).get("respaldo")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--etiqueta", default="v1")
    ap.add_argument("--rutas", default="rapida,completa", help="rutas a probar, separadas por coma")
    args = ap.parse_args()
    rutas = tuple(r for r in ("rapida", "completa") if r in args.rutas.split(","))
    config = cargar_configuracion(modo_evaluacion=True)
    c = construir_contenedor(config)
    http = TestClient(crear_app(c, precalentar=False))
    regs, dir_img = cargar_indice()
    por_id = {f"xm-{r['clave']}": r for r in regs}
    part = json.loads((EVAL / "conjuntos" / "particiones.json").read_text(encoding="utf-8"))["particiones"]
    casos, subidas = [], {}
    for i, xm in enumerate(part["ajuste_prompts"]):
        r = http.post("/documentos", data={"tipo": "foto"},
                      files=[("archivos", (f"{xm}.jpg", (dir_img / por_id[xm]["archivo"]).read_bytes(), "image/jpeg"))])
        doc = subidas[xm] = r.json()["documentos"][0]["documento_id"]
        refs = por_id[xm]["es"]
        for ruta in rutas:
            t0 = time.perf_counter()
            resp = http.post("/fichas", json={"documento_id": doc, "forzar_ruta": ruta, "sin_cache": True})
            segundos = round(time.perf_counter() - t0, 2)
            cuerpo = resp.json()
            meta = cuerpo.get("meta", {})
            eventos = c.sumidero_eventos.consultar(traza_id=meta.get("traza_id")) if meta.get("traza_id") else []
            alt = (cuerpo.get("ficha") or {}).get("texto_alternativo") or ""
            sim = None
            if alt:
                m = c.embebedor_secundario.embeber_textos([alt] + list(refs))
                sim = round(float(np.max(m[1:] @ m[0])), 4)
            p1 = [e.detalle for e in eventos if e.capa == "C6" and (e.detalle or {}).get("tarea") == "P1"]
            casos.append({
                "xm": xm, "ruta_pedida": ruta, "estado_http": resp.status_code, "segundos": segundos,
                "ficha": cuerpo.get("ficha"), "fuentes": cuerpo.get("fuentes"), "referencias": refs,
                "granite_alt_vs_referencias": sim,
                "valido_a_la_primera": valido_a_la_primera(eventos, "P2" if ruta == "rapida" else "P3"),
                "llamadas_p1": len(p1), "guardrails_salida": [(g["verificacion"], g["resultado"])
                                                              for g in meta.get("guardrails", {}).get("salida", [])],
                "revision": meta.get("revision"), "modelos": meta.get("modelos"),
            })
            registro(f"   {i + 1}/10 {xm} {ruta}: HTTP {resp.status_code} · {segundos} s · granite {sim}")
    for doc in subidas.values():
        http.delete(f"/documentos/{doc}")
    resumen = {}
    for ruta in rutas:
        cs = [x for x in casos if x["ruta_pedida"] == ruta]
        sims = [x["granite_alt_vs_referencias"] for x in cs if x["granite_alt_vs_referencias"] is not None]
        resumen[ruta] = {
            "n": len(cs), "http_200": sum(x["estado_http"] == 200 for x in cs),
            "validos_a_la_primera": sum(bool(x["valido_a_la_primera"]) for x in cs),
            "granite_media": round(float(np.mean(sims)), 4) if sims else None,
            "alt_vacios": sum(1 for x in cs if not (x.get("ficha") or {}).get("texto_alternativo")),
            "requiere_revision": sum(1 for x in cs if (x.get("ficha") or {}).get("estado") == "requiere_revision"),
            "copia_contexto": dict(Counter(r for x in cs for v, r in x["guardrails_salida"] if v == "copia_contexto")),
            "titulares_vacios": sum(1 for x in cs if not (x.get("ficha") or {}).get("titular")),
            "palabras_clave_media": round(float(np.mean([len((x.get("ficha") or {}).get("palabras_clave") or [])
                                                         for x in cs])), 2) if cs else None,
            "segundos_p50": float(np.percentile([x["segundos"] for x in cs], 50)) if cs else None,
        }
    json_guardar(EVAL / "resultados" / f"ajuste_prompts_{args.etiqueta}.json",
                 {"fecha": ahora_iso(), "etiqueta": args.etiqueta, "versiones_prompts": versiones(c.gateway.plantillas),
                  "resumen": resumen, "casos": casos})
    registro("resumen: " + json.dumps(resumen, ensure_ascii=False))


if __name__ == "__main__":
    main()
