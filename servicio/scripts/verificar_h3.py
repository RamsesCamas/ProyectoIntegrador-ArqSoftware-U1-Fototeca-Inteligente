"""Verificación de H3 con los adaptadores REALES (Ollama y Qdrant), después de `indexar_archivo`.

    python -m scripts.verificar_h3

Criterios (docs/specs/12 → H3):
1. Qdrant tiene las colecciones con el número de puntos esperado.
2. Al subir una foto con GPS, el GPS ya no aparece en el archivo guardado ni en la miniatura.
3. `DELETE /documentos/{id}` elimina los vectores (y el documento).
Escribe `evaluacion/resultados/h3_verificacion.json`. La foto de prueba se elimina al final: el archivo queda igual.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from fototeca.api.arranque import cargar_configuracion, construir_contenedor, crear_app
from fototeca.dominio import colecciones as col
from fototeca.guardrails.entrada.exif import detectar
from scripts._descargas import DATA, EVAL, ahora_iso, json_guardar, registro


def esperados(config) -> dict[str, int]:
    part = json.loads((EVAL / "conjuntos" / "particiones.json").read_text(encoding="utf-8"))["tamanos"]
    tesauro = sum(1 for linea in (DATA / "corpus" / "tesauro.jsonl").open(encoding="utf-8") if linea.strip())
    normas = sum(1 for linea in (DATA / "corpus" / "normas.jsonl").open(encoding="utf-8") if linea.strip())
    proto = yaml.safe_load((Path(config.rutas["config"]) / "prototipos.yaml").read_text(encoding="utf-8"))
    n_proto = (sum(len(v) for v in proto["consulta"].values()) + len(proto["inyeccion"])
               + sum(len(v) for t in ("dominio", "texto_visible") for v in proto[t].values()))
    return {col.FOTOS_IMG: part["archivo"], col.FOTOS_TXT: part["archivo"], col.FOTOS_TXT_GRANITE: part["archivo"],
            col.TESAURO: tesauro, col.NORMAS: normas, col.PROTOTIPOS: n_proto, col.FOTOS_DESC_QWEN: 0}


def main() -> None:
    config = cargar_configuracion()
    c = construir_contenedor(config)
    http = TestClient(crear_app(c, precalentar=False))
    resultado: dict = {"fecha": ahora_iso()}

    registro("1/3 · Puntos por colección")
    esperado = esperados(config)
    reales = {n: c.almacen_vectorial.contar(n) for n in col.TODAS}
    resultado["colecciones"] = {n: {"esperado": esperado.get(n), "real": reales[n], "ok": reales[n] == esperado.get(n)}
                                for n in col.TODAS}

    registro("2/3 · Foto con GPS: archivo guardado y miniatura")
    items = json.loads((EVAL / "conjuntos" / "gps_sintetico.json").read_text(encoding="utf-8"))["items"]
    ruta = DATA / items[0]["archivo"]
    original = ruta.read_bytes()
    antes = c.almacen_vectorial.contar(col.FOTOS_IMG)
    t0 = time.perf_counter()
    r = http.post("/documentos", data={"tipo": "foto"}, files=[("archivos", (ruta.name, original, "image/jpeg"))])
    subida_s = round(time.perf_counter() - t0, 3)
    cuerpo = r.json()
    doc = cuerpo["documentos"][0]["documento_id"]
    guardada = c.almacen_documentos.obtener_foto(doc)
    miniatura = http.get(f"/fotos/{doc}/miniatura")
    resultado["gps"] = {
        "foto": items[0]["archivo"], "estado_http_subida": r.status_code, "segundos_subida": subida_s,
        "exif_original": detectar(original), "exif_guardado": detectar(guardada),
        "exif_miniatura": detectar(miniatura.content), "estado_http_miniatura": miniatura.status_code,
        "guardrails_ingesta": cuerpo.get("documentos", [{}])[0].get("guardrails"),
    }
    resultado["gps"]["ok"] = (resultado["gps"]["exif_original"]["gps"] is True
                              and resultado["gps"]["exif_guardado"]["gps"] is False
                              and resultado["gps"]["exif_miniatura"]["gps"] is False)

    registro("3/3 · DELETE elimina los vectores")
    con_foto = c.almacen_vectorial.contar(col.FOTOS_IMG)
    vectores_antes = len(c.almacen_vectorial.obtener_vectores(col.FOTOS_IMG, [doc]))
    d = http.delete(f"/documentos/{doc}")
    despues = c.almacen_vectorial.contar(col.FOTOS_IMG)
    resultado["eliminacion"] = {
        "estado_http": d.status_code, "respuesta": d.json(), "puntos_fotos_img": {"antes_de_subir": antes,
                                                                                 "con_la_foto": con_foto,
                                                                                 "despues_de_eliminar": despues},
        "vectores_del_documento_antes": vectores_antes,
        "vectores_del_documento_despues": len(c.almacen_vectorial.obtener_vectores(col.FOTOS_IMG, [doc])),
        "documento_existe_despues": c.almacen_documentos.obtener_documento(doc) is not None,
        "miniatura_despues": http.get(f"/fotos/{doc}/miniatura").status_code,
    }
    e = resultado["eliminacion"]
    e["ok"] = (d.status_code == 200 and con_foto == antes + 1 and despues == antes and e["vectores_del_documento_antes"] == 1
               and e["vectores_del_documento_despues"] == 0 and not e["documento_existe_despues"]
               and e["miniatura_despues"] == 404)
    resultado["ok"] = all(x["ok"] for x in resultado["colecciones"].values()) and resultado["gps"]["ok"] and e["ok"]
    json_guardar(EVAL / "resultados" / "h3_verificacion.json", resultado)
    registro(f"H3: {'OK' if resultado['ok'] else 'REVISAR'} · colecciones {reales}")


if __name__ == "__main__":
    main()
