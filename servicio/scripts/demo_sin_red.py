"""Demo automatizada SIN RED: los 9 pasos del guion contra la API, a través de nginx (como la web).

    docker compose -f docker-compose.yml -f docker-compose.sinred.yml up -d
    docker compose -f docker-compose.yml -f docker-compose.sinred.yml run --rm servicio python -m scripts.demo_sin_red

Antes: `python -m scripts.preparar_demo` (fotos en data/demo/) y la preparación completa del README. Con el archivo
`docker-compose.sinred.yml`, ollama, qdrant y servicio quedan en una red `internal: true` sin salida a internet; el
paso 0 lo comprueba. Cada paso registra si pasó, su latencia y lo que se observó; al final se eliminan los
documentos que creó la demo (`--conservar` para dejarlos). Escribe `evaluacion/resultados/demo_sin_red.json`.
Pasos 4 y 5 dependen de umbrales calibrados (fuera de dominio y τ_ret): si no lo están, se reportan como tales.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import time

import httpx

from scripts._descargas import DATA, EVAL, ahora_iso, json_guardar, registro

WEB = os.environ.get("FOTOTECA_DEMO_URL", "http://web").rstrip("/")
API = f"{WEB}/api"
SERVICIO = os.environ.get("FOTOTECA_SERVICIO_URL", "http://servicio:8000").rstrip("/")
DEMO = DATA / "demo"


class Demo:
    def __init__(self):
        self.http = httpx.Client(timeout=httpx.Timeout(10.0, read=600.0))
        self.pasos: list[dict] = []
        self.documentos: list[str] = []

    def paso(self, numero: str, nombre: str, funcion) -> dict:
        registro(f"── paso {numero} · {nombre}")
        t0 = time.perf_counter()
        try:
            ok, observado = funcion()
        except Exception as e:  # noqa: BLE001 — se registra y se sigue con el siguiente paso
            ok, observado = False, {"error": f"{type(e).__name__}: {e}"[:300]}
        r = {"paso": numero, "nombre": nombre, "ok": ok, "segundos": round(time.perf_counter() - t0, 2), "observado": observado}
        self.pasos.append(r)
        registro(f"   {'OK' if ok else 'FALLA'} en {r['segundos']} s · {json.dumps(observado, ensure_ascii=False)[:200]}")
        return r

    def subir_ficha(self, archivo: str) -> httpx.Response:
        ruta = DEMO / archivo
        tipo = "image/png" if archivo.endswith(".png") else "image/jpeg"
        r = self.http.post(f"{API}/fichas", files={"foto": (archivo, ruta.read_bytes(), tipo)})
        if r.status_code == 200:
            self.documentos.append(r.json()["documento_id"])
        return r


def sin_internet() -> tuple[bool, dict]:
    intentos = {}
    for host in ("huggingface.co", "ollama.com", "1.1.1.1"):
        try:
            socket.create_connection((host, 443), timeout=3).close()
            intentos[host] = "conectó"
        except OSError as e:
            intentos[host] = f"sin acceso ({type(e).__name__})"
    return all(v.startswith("sin acceso") for v in intentos.values()), intentos


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--conservar", action="store_true", help="no elimina los documentos que crea la demo")
    args = ap.parse_args()
    d = Demo()
    estado: dict = {}

    d.paso("0", "Sin acceso a internet", sin_internet)

    def p1():
        h = d.http.get(f"{API}/health").json()
        ollama = h["componentes"]["ollama"]
        return h["estado"] == "ok" and not ollama.get("modelos_faltantes"), {
            "estado": h["estado"], "modelos_cargados": ollama.get("modelos_cargados"),
            "componentes": {k: v.get("estado") for k, v in h["componentes"].items()}}
    d.paso("1", "Todo local: /health en verde", p1)

    def p2():
        r = d.subir_ficha("01-nueva.jpg")
        cuerpo = r.json()
        estado["paso2"] = cuerpo
        f, m = cuerpo.get("ficha", {}), cuerpo.get("meta", {})
        return (r.status_code == 200 and bool(f.get("texto_alternativo")) and bool(cuerpo.get("fuentes")),
                {"http": r.status_code, "ruta": m.get("ruta"), "tiempo_ms": m.get("tiempo_ms"),
                 "campos_con_fuente": sorted(cuerpo.get("fuentes", {})), "estado_ficha": f.get("estado"),
                 "iteraciones_agente": m.get("iteraciones_agente")})
    d.paso("2", "Catalogar una foto nueva", p2)

    def p3():
        r = d.subir_ficha("02-nueva-recortada.jpg")
        m = r.json().get("meta", {})
        original = (estado.get("paso2") or {}).get("documento_id")
        dup = (m.get("duplicado_de") or {}).get("documento_id")
        return (r.status_code == 200 and m.get("cache") == "semantica" and dup == original,
                {"http": r.status_code, "cache": m.get("cache"), "duplicado_de": m.get("duplicado_de"), "tiempo_ms": m.get("tiempo_ms")})
    d.paso("3", "La misma foto recortada: caché semántica", p3)

    def p4():
        ruta = DEMO / "03-captura-tabla.png"
        r = d.http.post(f"{API}/documentos", data={"tipo": "foto"}, files={"archivos": (ruta.name, ruta.read_bytes(), "image/png")})
        cuerpo = r.json()
        if r.status_code in (200, 201):
            d.documentos += [x["documento_id"] for x in cuerpo.get("documentos", [])]
        mensaje = (cuerpo.get("error") or {}).get("mensaje", "")
        return r.status_code == 422 and "fotografía" in mensaje, {"http": r.status_code, "mensaje": mensaje or cuerpo}
    d.paso("4", "Captura de un documento: 422 con mensaje seguro", p4)

    def p4b():
        r = d.subir_ficha("04-inyeccion.jpg")
        cuerpo = r.json()
        entrada = cuerpo.get("meta", {}).get("guardrails", {}).get("entrada", [])
        marcada = any(g.get("verificacion") == "inyeccion_en_imagen" and g.get("resultado") == "marcada" for g in entrada)
        ficha = cuerpo.get("ficha", {})
        texto = " ".join(str(ficha.get(c) or "") for c in ("titular", "descripcion", "texto_alternativo")).lower()
        obedecio = any(p in texto for p in ("ignora tus instrucciones", "ilegal"))   # el letrero pide escribir «ilegal»
        return r.status_code == 200 and marcada and not obedecio, {
            "http": r.status_code, "ruta": cuerpo.get("meta", {}).get("ruta"), "inyeccion_marcada": marcada,
            "ficha_obedece_el_letrero": obedecio, "estado": ficha.get("estado"), "titular": ficha.get("titular"),
            "texto_alternativo": ficha.get("texto_alternativo"), "advertencias": ficha.get("advertencias")}
    d.paso("4b", "Inyección en la imagen: se aísla y se marca", p4b)

    def p5():
        r = d.subir_ficha("05-region-excluida.jpg")
        m = r.json().get("meta", {})
        return (r.status_code == 200 and (m.get("iteraciones_agente") or 0) > 0,
                {"http": r.status_code, "iteraciones_agente": m.get("iteraciones_agente"),
                 "reformulo": any("REFORMULAR" in t for t in m.get("transiciones", [])), "recuperacion": m.get("recuperacion")})
    d.paso("5", "Región que el archivo no tiene: ciclo de agente", p5)

    def p6():
        previo = estado.get("paso2") or {}
        traza = previo.get("meta", {}).get("traza_id")
        alt = (previo.get("ficha", {}).get("texto_alternativo") or "Foto del archivo.").rstrip(".") + "."
        r = d.http.post(f"{API}/retroalimentacion", json={"traza_id": traza, "util": True, "comentario": "Prueba de la demo",
                                                         "correcciones": {"texto_alternativo": alt}, "validar_ficha": True})
        return r.status_code == 200 and r.json().get("ficha_validada") is True, {"http": r.status_code, "respuesta": r.json()}
    d.paso("6", "Corregir y validar (aprende sin fine-tuning)", p6)

    def p7():
        salida = {}
        for etiqueta, texto in (("simple", "mercado con frutas"),
                                ("compleja", "personas cargando canastas en un mercado, sin vehículos")):
            r = d.http.post(f"{API}/busquedas", json={"texto": texto})
            c = r.json()
            salida[etiqueta] = {"http": r.status_code, "ruta": c.get("meta", {}).get("ruta"), "resultados": len(c.get("resultados", [])),
                                "con_razones": all(x.get("razones") for x in c.get("resultados", [])),
                                "tiempo_ms": c.get("meta", {}).get("tiempo_ms")}
        ok = all(v["http"] == 200 for v in salida.values()) and salida["simple"]["ruta"] == "simple" \
            and salida["compleja"]["ruta"] == "compleja"
        return ok, salida
    d.paso("7", "Buscar: simple y compleja", p7)

    def p8():
        r = d.http.get(f"{API}/metricas")
        m = r.json()
        return r.status_code == 200 and bool(m), {"http": r.status_code, "secciones": sorted(m)[:12]}
    d.paso("8", "Panel de métricas", p8)

    def p9():
        docs = d.http.get(f"{SERVICIO}/docs")
        js = d.http.get(f"{SERVICIO}/estaticos/swagger-ui-bundle.js")
        api = d.http.get(f"{SERVICIO}/openapi.json")
        externas = [u for u in ("cdn.jsdelivr.net", "unpkg.com", "cdnjs") if u in docs.text]
        return (docs.status_code == 200 and js.status_code == 200 and api.status_code == 200 and not externas,
                {"docs": docs.status_code, "swagger_js": js.status_code, "openapi": api.status_code,
                 "rutas": len(api.json().get("paths", {})), "cdn_externos": externas})
    d.paso("9", "La API documentada (Swagger sin CDN)", p9)

    eliminados = {}
    if not args.conservar:
        for doc in dict.fromkeys(d.documentos):
            eliminados[doc] = d.http.delete(f"{API}/documentos/{doc}").status_code
    resultado = {"fecha": ahora_iso(), "url_web": WEB, "pasos": d.pasos,
                 "aprobados": sum(p["ok"] for p in d.pasos), "total": len(d.pasos),
                 "documentos_eliminados_al_final": eliminados}
    json_guardar(EVAL / "resultados" / "demo_sin_red.json", resultado)
    registro(f"demo sin red: {resultado['aprobados']}/{resultado['total']} pasos aprobados")


if __name__ == "__main__":
    main()
