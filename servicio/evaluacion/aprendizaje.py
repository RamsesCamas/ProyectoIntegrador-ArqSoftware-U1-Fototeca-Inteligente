"""Retroalimentación y curva de aprendizaje. Es una SIMULACIÓN, declarada como tal en los resultados.

Sobre la partición `aprendizaje` (100 fotos de `nuevas` que no se cruzan con eval_fichas), en 5 bloques de 20:
1. se cataloga el bloque por la API (flujo de producción, sin caché, para que solo influyan los ejemplos del RAG);
2. se mide cada ficha: similitud granite entre su texto alternativo y las referencias humanas (la máxima) y si «se
   aceptaría sin edición»: similitud ≥ p50 de la similitud granite entre referencias humanas de una misma foto (la 1ª
   contra las demás), calculada sobre las fotos de la partición con al menos dos referencias;
3. se envía la retroalimentación del bloque (POST /retroalimentacion con la traza de cada ficha): las referencias
   humanas hacen de «correcciones del archivista», con el mismo criterio que las fichas iniciales del archivo
   (titular y texto alternativo = la referencia más corta recortada a 120 y 250 caracteres; descripción = la 1ª),
   validar_ficha = true y útil = «se aceptaría sin edición». El comentario empieza con «[simulación]» para
   separarla de las opiniones reales.
Cada bloque se cataloga con las correcciones de los anteriores ya promovidas como ejemplos del RAG. La curva va contra
las correcciones acumuladas: los ejemplos de `fotos_txt` que no venían en el archivo inicial (fichas validadas por
archivista) antes de catalogar el bloque; así también cuentan validaciones previas, si las hubiera.

Análisis de retroalimentación (tabla de T2): útil y no útil por ruta y por modelo, con la simulación separada de las
opiniones reales del autor (si existen).

Estado que deja en la base: las fichas de la partición quedan VALIDADAS y promovidas como ejemplos (fotos_txt y
fotos_txt_granite con validada=true; fotos_img marcada como validada; version_archivo aumenta). El JSON lista los
documentos promovidos; la limpieza la decide la sesión principal. Para repetir la simulación desde cero hay que
reconstruir el archivo y borrar los casos `resultados/casos/*aprendizaje*.jsonl`. Con --rapido se usa el inicio de la
misma lista (bloques de 5), con casos aparte, y también se promueve.

    python -m evaluacion.aprendizaje
"""
from __future__ import annotations

import random

import numpy as np

from evaluacion.calidad import (asegurar_subidas, ficha_evaluacion, intervalo_bootstrap, referencias,
                                similitud_granite)
from evaluacion.comun import (SEMILLA, ClienteEval, Incremental, guardar_grafica, guardar_resultado, particiones,
                              percentiles, plt, rapido, registro, tamano, fraccion)

N_BLOQUES = 5
PREFIJO = "[simulación]"
PALETA = {"azul": "#2a78d6", "naranja": "#eb6834", "gris": "#9a9992"}


def _sufijo() -> str:
    # La curva depende de los bloques, que cambian con el tamaño: cada fracción guarda sus casos aparte.
    if rapido():
        return "_rapido"
    return "" if fraccion() >= 1.0 else f"_f{int(round(fraccion() * 100))}"


def fotos_y_bloques() -> tuple[list[str], list[list[str]]]:
    part = particiones()
    disponibles = sorted(set(part["aprendizaje"]) - set(part["eval_fichas"]))
    orden = random.Random(f"{SEMILLA}-aprendizaje").sample(disponibles, len(disponibles))
    fotos = orden[:tamano(len(orden))]
    tam = max(1, len(fotos) // N_BLOQUES)
    bloques = [fotos[i * tam:(i + 1) * tam] for i in range(N_BLOQUES - 1)] + [fotos[(N_BLOQUES - 1) * tam:]]
    return fotos, [b for b in bloques if b]


def umbral_aceptable(c: ClienteEval, fotos: list[str]) -> dict:
    """p50 de la similitud granite entre la 1ª referencia humana y las demás de la misma foto."""
    dobles = [x for x in fotos if len([r for r in referencias(x) if r.strip()]) >= 2]
    if not dobles:
        return {"umbral": None, "n": 0, "estado": "pendiente: ninguna foto tiene dos referencias"}
    textos, cortes = [], []
    for x in dobles:
        refs = [r for r in referencias(x) if r.strip()]
        cortes.append((len(textos), len(refs)))
        textos += refs
    m = c.contenedor.embebedor_secundario.embeber_textos(textos)
    sims = [float(np.max(m[i + 1:i + n] @ m[i])) for i, n in cortes]
    return {"umbral": round(float(np.percentile(sims, 50)), 4), "n": len(sims),
            "distribucion": percentiles(sims, "coseno"),
            "regla": "p50 de la similitud granite entre la 1ª referencia humana y las demás de la misma foto"}


def correcciones_de(xm: str) -> dict:
    from scripts.indexar_archivo import recortar
    refs = [r.strip() for r in referencias(xm) if r.strip()]
    corta = min(refs, key=len)
    return {"titular": recortar(corta, 120), "texto_alternativo": recortar(corta, 250), "descripcion": recortar(refs[0], 800)}


def ejemplos_promovidos(c: ClienteEval) -> int:
    """Ejemplos del RAG que no venían en el archivo inicial: solo una validación de archivista inserta en `fotos_txt`
    una foto de fuera de la partición «archivo»."""
    from fototeca.dominio import colecciones as col
    return c.contenedor.almacen_vectorial.contar(col.FOTOS_TXT, {"particion": {"no": "archivo"}})


def _fuentes_foto(respuesta: dict) -> set[str]:
    return {f.get("id") for fs in (respuesta.get("fuentes") or {}).values() for f in fs
            if isinstance(f, dict) and f.get("tipo") == "foto_similar"}


def analisis_t2(c: ClienteEval) -> dict:
    """Útil y no útil por ruta y por modelo (tabla retroalimentacion), simulación y opiniones reales por separado."""
    registros = c.contenedor.almacen_retroalimentacion.listar()

    def resumen(rs: list) -> dict:
        calificados = [r for r in rs if r.util is not None]
        por_ruta: dict[str, dict] = {}
        por_modelo: dict[str, dict] = {}
        for r in calificados:
            clave = "util" if r.util else "no_util"
            por_ruta.setdefault(r.ruta or "desconocida", {"util": 0, "no_util": 0})[clave] += 1
            for modelo in sorted(set((r.modelos or {}).values())):
                por_modelo.setdefault(modelo, {"util": 0, "no_util": 0})[clave] += 1
        for d in list(por_ruta.values()) + list(por_modelo.values()):
            d["tasa_util"] = round(d["util"] / (d["util"] + d["no_util"]), 4)
        return {"registros": len(rs), "calificados": len(calificados),
                "util": sum(1 for r in calificados if r.util), "no_util": sum(1 for r in calificados if not r.util),
                "tasa_util": round(sum(1 for r in calificados if r.util) / len(calificados), 4) if calificados else None,
                "con_validacion": sum(1 for r in rs if r.validar_ficha), "por_ruta": por_ruta, "por_modelo": por_modelo}

    simulados = [r for r in registros if (r.comentario or "").startswith(PREFIJO)]
    reales = [r for r in registros if not (r.comentario or "").startswith(PREFIJO)]
    return {"simulacion": resumen(simulados),
            "opiniones_reales": resumen(reales) if reales else {"estado": "pendiente: no hay opiniones reales registradas"},
            "nota": "En la simulación, «útil» = la ficha se aceptaría sin edición (regla del experimento, no una opinión)."}


def _ficha(c: ClienteEval, configuracion: str, xm: str, documento_id: str) -> dict:
    """POST /fichas reanudable; un 5xx (falla transitoria) se reintenta una vez por corrida."""
    reg = ficha_evaluacion(c, configuracion, xm, documento_id, sin_cache=True)
    if reg.get("estado_http", 0) >= 500:
        estado, cuerpo, seg = c.ficha(documento_id, sin_cache=True)
        reg = Incremental(f"fichas_{configuracion}").guardar(xm, {
            "documento_id": documento_id, "estado_http": estado, "respuesta": cuerpo, "segundos": round(seg, 3),
            "opciones": {"sin_cache": True}})
    return reg


def ejecutar(c: ClienteEval) -> dict:
    fotos, bloques = fotos_y_bloques()
    configuracion_fichas = f"aprendizaje{_sufijo()}"
    inc_bloques, inc_retro = Incremental(f"aprendizaje_bloques{_sufijo()}"), Incremental(f"aprendizaje_retro{_sufijo()}")
    umbral = umbral_aceptable(c, fotos)
    registro(f"aprendizaje (simulación) · {len(fotos)} fotos en {len(bloques)} bloques · umbral «aceptable» {umbral['umbral']}")
    version_archivo_inicial = c.contenedor.almacen_documentos.version_archivo()
    subidas = asegurar_subidas(c, fotos)
    promovidos: set[str] = set()
    filas, por_bloque, detenido = [], [], None
    for b, bloque in enumerate(bloques, start=1):
        marca = inc_bloques.obtener(f"bloque-{b}") or inc_bloques.guardar(
            f"bloque-{b}", {"correcciones_acumuladas_antes": ejemplos_promovidos(c), "fotos": bloque})
        # 1. catalogar
        fichas = {xm: _ficha(c, configuracion_fichas, xm, subidas[xm]) for xm in bloque}
        # 2. medir
        filas_bloque = []
        for xm in bloque:
            reg = fichas[xm]
            fila = {"bloque": b, "xm_id": xm, "documento_id": reg.get("documento_id"), "estado_http": reg.get("estado_http"),
                    "segundos": reg.get("segundos")}
            if reg.get("estado_http") == 200:
                resp = reg["respuesta"]
                alt = resp["ficha"].get("texto_alternativo") or ""
                sim = similitud_granite(c, alt, referencias(xm))
                fila.update(ruta=resp["meta"].get("ruta"), estado_ficha=resp["ficha"].get("estado"),
                            traza_id=resp["meta"].get("traza_id"), granite=sim,
                            aceptable=bool(sim is not None and umbral["umbral"] is not None and sim >= umbral["umbral"]),
                            cita_ejemplo_promovido=bool(_fuentes_foto(resp) & promovidos),
                            top1_recuperacion=(resp["meta"].get("recuperacion") or {}).get("top1"))
            filas_bloque.append(fila)
        # 3. retroalimentación del bloque
        for fila in filas_bloque:
            xm = fila["xm_id"]
            previo = inc_retro.obtener(xm)
            # Se reintenta lo que falló por causas pasajeras (5xx) o porque la ruta aún no existía (404 de la API).
            reintentar = previo is not None and (previo["estado_http"] >= 500 or previo.get("codigo_error") == "http_404")
            if (previo is None or reintentar) and fila.get("traza_id"):
                estado, cuerpo = c.retroalimentacion(
                    fila["traza_id"], util=fila["aceptable"], validar_ficha=True, correcciones=correcciones_de(xm),
                    comentario=f"{PREFIJO} bloque {b}: corrección con las referencias humanas de Crossmodal-3600")
                error = cuerpo.get("error") if isinstance(cuerpo, dict) else None
                previo = inc_retro.guardar(xm, {"estado_http": estado, "ficha_validada": bool((cuerpo or {}).get("ficha_validada")),
                                                "version_archivo": (cuerpo or {}).get("version_archivo"),
                                                "codigo_error": (error or {}).get("codigo")})
                if estado == 404 and (error or {}).get("codigo") == "http_404":
                    detenido = "pendiente: POST /retroalimentacion no está disponible en la API (404); la simulación se detuvo"
            if previo:
                fila.update(retro_estado_http=previo["estado_http"], ficha_validada=previo["ficha_validada"],
                            retro_error=previo.get("codigo_error"))
                if previo["ficha_validada"] and fila.get("documento_id"):
                    promovidos.add(fila["documento_id"])
            if detenido:
                break
        filas += filas_bloque
        ok = [f for f in filas_bloque if f.get("estado_http") == 200]
        sims = [f["granite"] for f in ok if f.get("granite") is not None]
        acept = [1.0 if f["aceptable"] else 0.0 for f in ok]      # un texto alternativo vacío no es aceptable
        resumen = {"bloque": b, "fotos": len(bloque), "fichas_medidas": len(ok),
                   "texto_alternativo_vacio": sum(1 for f in ok if f.get("granite") is None),
                   "correcciones_acumuladas_antes": marca["correcciones_acumuladas_antes"],
                   "granite_media": round(float(np.mean(sims)), 4) if sims else None,
                   "granite_p50": round(float(np.percentile(sims, 50)), 4) if sims else None,
                   "granite_ic95": intervalo_bootstrap(sims),
                   "aceptables_sin_edicion": int(sum(acept)), "tasa_aceptable": round(float(np.mean(acept)), 4) if acept else None,
                   "tasa_aceptable_ic95": intervalo_bootstrap(acept),
                   "rutas": {r: sum(1 for f in ok if f.get("ruta") == r) for r in sorted({f.get("ruta") for f in ok if f.get("ruta")})},
                   "requiere_revision": sum(1 for f in ok if f.get("estado_ficha") == "requiere_revision"),
                   "citan_un_ejemplo_promovido": sum(1 for f in ok if f.get("cita_ejemplo_promovido")),
                   "retro_enviadas": sum(1 for f in filas_bloque if f.get("retro_estado_http") is not None),
                   "fichas_validadas": sum(1 for f in filas_bloque if f.get("ficha_validada"))}
        por_bloque.append(resumen)
        registro(f"   bloque {b}: granite {resumen['granite_media']} · aceptables {resumen['tasa_aceptable']} · "
                 f"correcciones previas {resumen['correcciones_acumuladas_antes']} · validadas {resumen['fichas_validadas']}")
        if detenido:
            registro(f"   {detenido}")
            break

    tendencia = None
    medidos = [x for x in por_bloque if x["granite_media"] is not None]
    if len(medidos) >= 2:
        tendencia = {"granite_ultimo_menos_primero": round(medidos[-1]["granite_media"] - medidos[0]["granite_media"], 4),
                     "aceptable_ultimo_menos_primero": round(medidos[-1]["tasa_aceptable"] - medidos[0]["tasa_aceptable"], 4),
                     "nota": "comparar con los IC95 de cada bloque antes de afirmar una mejora"}
    metricas = {
        "simulacion": True,
        "estado": detenido or "completa",
        "descripcion": "Simulación: las referencias humanas hacen de correcciones del archivista (validar_ficha=true); "
                       "sin fine-tuning, el aprendizaje es la promoción de fichas validadas como ejemplos del RAG.",
        "umbral_aceptable_sin_edicion": umbral, "bloques": por_bloque, "tendencia": tendencia,
        "retroalimentacion_t2": analisis_t2(c),
        "estado_de_la_base": {
            "documentos_promovidos": sorted(promovidos), "n_promovidos": len(promovidos),
            "ejemplos_promovidos_en_fotos_txt": ejemplos_promovidos(c),
            "version_archivo_inicial": version_archivo_inicial,
            "version_archivo_final": c.contenedor.almacen_documentos.version_archivo(),
            "nota": "Las fichas promovidas quedan como ejemplos validados del RAG y cambian el contexto de otros "
                    "experimentos que se corran después; la limpieza la decide la sesión principal."},
    }
    if medidos:
        pyplot = plt()
        fig, (ax1, ax2) = pyplot.subplots(1, 2, figsize=(10, 3.6))
        x = [m["correcciones_acumuladas_antes"] for m in medidos]
        for ax, clave, ic, titulo, color in ((ax1, "granite_media", "granite_ic95", "Similitud granite del texto alternativo", PALETA["azul"]),
                                             (ax2, "tasa_aceptable", "tasa_aceptable_ic95", "Fichas aceptables sin edición", PALETA["naranja"])):
            y = [m[clave] for m in medidos]
            bajos = [m[clave] - m[ic][0] if m[ic] else 0 for m in medidos]
            altos = [m[ic][1] - m[clave] if m[ic] else 0 for m in medidos]
            ax.errorbar(x, y, yerr=[bajos, altos], color=color, lw=2, marker="o", ms=5, capsize=3)
            ax.set_xlabel("Correcciones acumuladas (ejemplos promovidos antes del bloque)")
            ax.set_title(titulo, fontsize=9)
        ax1.set_ylabel("Coseno (media del bloque, IC95)")
        ax2.set_ylabel("Proporción (IC95)")
        ax2.set_ylim(0, 1)
        if umbral["umbral"] is not None:
            ax1.axhline(umbral["umbral"], color=PALETA["gris"], lw=1, ls="--")
            ax1.text(x[0], umbral["umbral"], " umbral «aceptable»", va="bottom", fontsize=7)
        fig.suptitle("Curva de aprendizaje (simulación con las referencias como correcciones)", fontsize=10)
        guardar_grafica("aprendizaje_curva", fig)
    configuracion = {"bloques": len(bloques), "fotos": len(fotos), "opciones_ficha": {"sin_cache": True},
                     "configuracion_fichas": configuracion_fichas, "prefijo_comentario": PREFIJO,
                     "correcciones": "titular y texto alternativo = referencia más corta (120 y 250 caracteres); "
                                     "descripción = 1ª referencia (800)"}
    guardar_resultado("aprendizaje", metricas, filas, configuracion, c)
    return metricas


if __name__ == "__main__":
    ejecutar(ClienteEval())
