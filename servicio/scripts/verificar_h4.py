"""Aceptación de H4 (la ficha de principio a fin) con los modelos REALES.

    python -m scripts.verificar_h4

1. 10 fotos de `nuevas` producen una ficha válida con fuentes, por las dos rutas (`forzar_ruta`, solo evaluación).
2. Una foto de `regiones_excluidas` activa el ciclo de agente (se ve en la traza).
3. La búsqueda simple y la compleja funcionan.
4. La respuesta tiene todos los campos `meta` de `03`.

Las fotos de prueba salen de `nuevas` y `regiones_excluidas` SIN tocar `eval_fichas`, `aprendizaje`,
`ajuste_prompts` ni `agente_extra` (los conjuntos de H7 quedan fuera de muestra). Se suben por la API, sin caché, y
al final se eliminan para dejar el archivo como estaba. Escribe `evaluacion/resultados/h4_aceptacion.json` y el
detalle caso por caso en `evaluacion/resultados/casos/h4_aceptacion.jsonl`.
"""
from __future__ import annotations

import json
import random
import time

from fastapi.testclient import TestClient

from fototeca.api.arranque import cargar_configuracion, construir_contenedor, crear_app
from scripts._descargas import EVAL, ahora_iso, json_guardar, registro
from scripts._recuperacion import foto_clara, recuperacion_de
from scripts._xm3600 import SEMILLA, cargar_indice

META_FICHA = ("ruta", "modelos", "cache", "guardrails", "iteraciones_agente", "duplicado_de", "tiempo_ms",
              "tiempos_por_capa_ms", "traza_id", "version_configuracion", "aviso")
META_BUSQUEDA = ("ruta", "modelo", "cache", "guardrails", "iteraciones_agente", "tiempo_ms", "tiempos_por_capa_ms",
                 "traza_id", "aviso")
CASOS = EVAL / "resultados" / "casos" / "h4_aceptacion.jsonl"


def ficha_valida(cuerpo: dict) -> dict:
    f = cuerpo.get("ficha") or {}
    fuentes = cuerpo.get("fuentes") or {}
    meta = cuerpo.get("meta") or {}
    alt = f.get("texto_alternativo") or ""
    return {
        "titular": bool(f.get("titular")), "alt_no_vacio": bool(alt), "alt_max_250": len(alt) <= 250,
        "con_fuentes": sum(len(v) for v in fuentes.values()) > 0, "campos_con_fuente": sorted(fuentes),
        "meta_completo": all(k in meta for k in META_FICHA), "meta_faltantes": [k for k in META_FICHA if k not in meta],
        "estado": f.get("estado"),
    }


def main() -> None:
    inicio = time.perf_counter()
    config = cargar_configuracion(modo_evaluacion=True)
    c = construir_contenedor(config)
    http = TestClient(crear_app(c, precalentar=False))
    regs, dir_img = cargar_indice()
    por_id = {f"xm-{r['clave']}": r for r in regs}
    part = json.loads((EVAL / "conjuntos" / "particiones.json").read_text(encoding="utf-8"))["particiones"]
    reservadas = set(part["eval_fichas"]) | set(part["aprendizaje"]) | set(part["ajuste_prompts"]) | set(part["agente_extra"])
    rng = random.Random(f"{SEMILLA}-aceptacion-h4")
    nuevas = rng.sample(sorted(set(part["nuevas"]) - reservadas), 10)
    # Caso del ciclo de agente: fotos de `regiones_excluidas` cuya recuperación es pobre según la regla del flujo
    # (τ_ret es el p10 de `nuevas`, así que al azar solo ~1 de cada 10 activaría el ciclo).
    candidatas = recuperacion_de(c, sorted(set(part["regiones_excluidas"]) - reservadas))
    pobres = sorted((x for x in candidatas if x["pobre"] and foto_clara(c, x)), key=lambda x: x["top1"])
    regiones = [x["xm"] for x in pobres[:3]]
    prevision = {x["xm"]: x for x in candidatas}
    registro(f"   regiones_excluidas: {len(pobres)} de {len(candidatas)} con recuperación pobre según la regla del flujo")
    CASOS.parent.mkdir(parents=True, exist_ok=True)
    CASOS.write_text("", encoding="utf-8")
    subidas: dict[str, str] = {}

    def subir(xm: str) -> str:
        ruta = dir_img / por_id[xm]["archivo"]
        r = http.post("/documentos", data={"tipo": "foto"}, files=[("archivos", (f"{xm}.jpg", ruta.read_bytes(), "image/jpeg"))])
        r.raise_for_status()
        subidas[xm] = r.json()["documentos"][0]["documento_id"]
        return subidas[xm]

    def guardar_caso(caso: dict) -> None:
        with open(CASOS, "a", encoding="utf-8") as f:
            f.write(json.dumps(caso, ensure_ascii=False, default=str) + "\n")

    fichas, agente, busquedas = [], [], []
    try:
        registro("1/3 · 10 fotos de nuevas por las dos rutas")
        for i, xm in enumerate(nuevas):
            doc = subir(xm)
            for ruta in ("rapida", "completa"):
                t0 = time.perf_counter()
                r = http.post("/fichas", json={"documento_id": doc, "forzar_ruta": ruta, "sin_cache": True})
                segundos = round(time.perf_counter() - t0, 2)
                cuerpo = r.json()
                caso = {"tipo": "ficha", "xm": xm, "ruta_pedida": ruta, "estado_http": r.status_code, "segundos": segundos}
                if r.status_code == 200:
                    m = cuerpo["meta"]
                    caso.update(ruta=m["ruta"], modelos=m["modelos"], validez=ficha_valida(cuerpo),
                                guardrails_salida=[(g["verificacion"], g["resultado"]) for g in m["guardrails"]["salida"]],
                                revision=m.get("revision"), texto_alternativo=cuerpo["ficha"]["texto_alternativo"],
                                titular=cuerpo["ficha"]["titular"], referencias=por_id[xm]["es"],
                                tiempos_por_capa_ms=m["tiempos_por_capa_ms"])
                else:
                    caso["error"] = cuerpo
                fichas.append(caso)
                guardar_caso(caso)
                registro(f"   {i + 1}/10 {xm} {ruta}: HTTP {r.status_code} en {segundos} s"
                         f"{' · ' + caso.get('ruta', '') if r.status_code == 200 else ''}")

        registro("2/3 · Ciclo de agente con regiones_excluidas")
        for xm in regiones:
            doc = subir(xm)
            r = http.post("/fichas", json={"documento_id": doc, "sin_cache": True})
            cuerpo = r.json()
            meta = cuerpo.get("meta", {})
            eventos = c.sumidero_eventos.consultar(traza_id=meta.get("traza_id")) if meta.get("traza_id") else []
            reformulaciones = [e.detalle for e in eventos if e.evento == "reformular"]
            caso = {"tipo": "agente", "xm": xm, "estado_http": r.status_code, "iteraciones": meta.get("iteraciones_agente"),
                "recuperacion_prevista": prevision[xm],
                    "reformulaciones_en_traza": reformulaciones, "recuperacion": meta.get("recuperacion"),
                    "ruta": meta.get("ruta"), "transiciones": meta.get("transiciones"), "traza_id": meta.get("traza_id")}
            agente.append(caso)
            guardar_caso(caso)
            registro(f"   {xm}: iteraciones {caso['iteraciones']} · reformulaciones en la traza {len(reformulaciones)}")
            if caso["iteraciones"]:
                break

        registro("3/3 · Búsquedas simple y compleja")
        complejas = json.loads((EVAL / "conjuntos" / "consultas_complejas.json").read_text(encoding="utf-8"))["items"]
        muestra_archivo = rng.choice(sorted(part["archivo"]))
        consultas = [("simple", por_id[muestra_archivo]["es"][0], muestra_archivo), ("compleja", complejas[0]["consulta"], None)]
        for esperada, texto, objetivo in consultas:
            t0 = time.perf_counter()
            r = http.post("/busquedas", json={"texto": texto, "sin_cache": True})
            segundos = round(time.perf_counter() - t0, 2)
            cuerpo = r.json()
            meta = cuerpo.get("meta", {})
            ids = [x["documento_id"] for x in cuerpo.get("resultados", [])]
            caso = {"tipo": "busqueda", "esperada": esperada, "texto": texto, "estado_http": r.status_code, "segundos": segundos,
                    "ruta": meta.get("ruta"), "modelo": meta.get("modelo"), "resultados": len(ids),
                    "meta_completo": all(k in meta for k in META_BUSQUEDA),
                    "consulta_interpretada": cuerpo.get("consulta_interpretada"),
                    "objetivo_en_top10": (objetivo in ids[:10]) if objetivo else None,
                    "con_razones": all(x.get("razones") for x in cuerpo.get("resultados", []))}
            busquedas.append(caso)
            guardar_caso(caso)
            registro(f"   {esperada}: HTTP {r.status_code} · ruta {caso['ruta']} · {len(ids)} resultados en {segundos} s")

    finally:
        # Aunque una etapa falle, las fotos de prueba no se quedan en el archivo.
        registro("Limpieza: se eliminan las fotos de prueba")
        eliminadas = {xm: http.delete(f"/documentos/{doc}").status_code for xm, doc in subidas.items()}

    ok_fichas = [f for f in fichas if f["estado_http"] == 200 and f["validez"]["titular"] and f["validez"]["alt_no_vacio"]
                 and f["validez"]["alt_max_250"] and f["validez"]["con_fuentes"] and f["validez"]["meta_completo"]]
    por_ruta = {ruta: {"pedidas": sum(1 for f in fichas if f["ruta_pedida"] == ruta),
                       "validas_con_fuentes": sum(1 for f in ok_fichas if f["ruta_pedida"] == ruta),
                       "segundos": sorted(f["segundos"] for f in fichas if f["ruta_pedida"] == ruta)}
                for ruta in ("rapida", "completa")}
    resumen = {
        "fecha": ahora_iso(), "minutos": round((time.perf_counter() - inicio) / 60, 1),
        "version_configuracion": c.config.version_configuracion(c.almacen_documentos.leer_estado("version_corpus", "")),
        "criterios": {
            "fichas_validas_con_fuentes_por_ruta": {r: v["validas_con_fuentes"] for r, v in por_ruta.items()},
            "ciclo_de_agente_activado": any(a["iteraciones"] for a in agente),
            "busqueda_simple_ok": busquedas[0]["estado_http"] == 200 and busquedas[0]["ruta"] == "simple",
            "busqueda_compleja_ok": busquedas[1]["estado_http"] == 200 and busquedas[1]["ruta"] == "compleja",
            "meta_completo_en_todas": all(f.get("validez", {}).get("meta_completo") for f in fichas)
                                      and all(b["meta_completo"] for b in busquedas),
        },
        "por_ruta": por_ruta, "agente": agente, "busquedas": busquedas,
        "fotos": {"nuevas": nuevas, "regiones_excluidas": regiones[:len(agente)]}, "eliminadas": eliminadas,
        "seleccion_agente": {"candidatas": len(candidatas),
                             "con_recuperacion_pobre": sum(1 for x in candidatas if x["pobre"]),
                             "pobres_y_claras": len(pobres),
                             "regla": "flujo_ficha.recuperacion_pobre (top-1 < τ_ret o margen < δ)"},
        "detalle": str(CASOS.relative_to(EVAL)),
    }
    json_guardar(EVAL / "resultados" / "h4_aceptacion.json", resumen)
    registro("criterios: " + json.dumps(resumen["criterios"], ensure_ascii=False))


if __name__ == "__main__":
    main()
