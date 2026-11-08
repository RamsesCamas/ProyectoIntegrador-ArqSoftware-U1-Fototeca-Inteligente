"""Flujo de búsqueda (C2; docs/specs/06, C2 «Búsqueda»):

    GUARDRAILS_ENTRADA → CACHE → ENRUTAR (simple | compleja | imagen) → [P4] → RECUPERAR
      → EVALUAR (sin resultados ≥ τ_busqueda y iteración < 2 → P5 reformular → RECUPERAR)
      → RAZONES → GUARDRAILS_SALIDA (no exponer rutas, EXIF ni GPS) → RESPONDER

`excluir` (P4) se aplica penalizando el puntaje de los resultados cuya ficha menciona un término excluido o se
parece a él (coseno ≥ τ_excluir entre el término y el vector de texto de la ficha). Método documentado en ADR-03.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict

import numpy as np

from fototeca.cache.cache_busquedas import CacheBusquedas
from fototeca.contexto.fusion import rrf
from fototeca.datos.puertos import AlmacenDocumentos, AlmacenVectorial, Embebedor
from fototeca.dominio import colecciones as col
from fototeca.dominio.configuracion import Configuracion
from fototeca.dominio.errores import ServicioNoDisponible, TiempoAgotado
from fototeca.guardrails.entrada.archivo import verificar_archivo
from fototeca.guardrails.entrada.exif import sanitizar
from fototeca.guardrails.entrada.imagen import VerificadorImagen
from fototeca.guardrails.entrada.texto import sanitizar_pii, verificar_inyeccion
from fototeca.guardrails.resultado import ResultadoGuardrail
from fototeca.modelos.enrutador_busquedas import EnrutadorBusquedas
from fototeca.modelos.gateway import Gateway
from fototeca.observabilidad.registro import registrar
from fototeca.observabilidad.traza import traza_actual

AVISO = "Resultados ordenados por modelos de IA; pueden contener errores."
PERSONAS = re.compile(r"\b(persona|personas|hombre|hombres|mujer|mujeres|niñ[oa]s?|gente|chic[oa]s?|señor|señora|"
                      r"joven|jóvenes|bebé|turistas?|vendedor\w*|trabajador\w*|familia|pareja|grupo de)\b", re.I)
CLAVES_PROHIBIDAS = ("ruta_relativa", "gps", "exif", "sha256", "metadatos")


class FlujoBusqueda:
    def __init__(self, config: Configuracion, documentos: AlmacenDocumentos, vectorial: AlmacenVectorial,
                 embebedor: Embebedor, gateway: Gateway, cache: CacheBusquedas, enrutador: EnrutadorBusquedas,
                 verificador_imagen: VerificadorImagen, version_corpus):
        self.config = config
        self.documentos = documentos
        self.vectorial = vectorial
        self.embebedor = embebedor
        self.gateway = gateway
        self.cache = cache
        self.enrutador = enrutador
        self.verificador_imagen = verificador_imagen
        self.version_corpus = version_corpus

    # ───────────────────────────── por texto ─────────────────────────────
    def buscar_texto(self, texto: str, k: int = 12, filtros: dict | None = None, sin_cache: bool = False,
                     forzar_ruta: str | None = None) -> dict:
        t0 = time.perf_counter()
        tiempos: dict[str, float] = defaultdict(float)
        guardrails: list[dict] = []
        modelo = None
        iteraciones = 0
        p = self.config.parametro
        version = self.config.version_configuracion(self.version_corpus())

        marca = time.perf_counter()
        limpio, r_pii = sanitizar_pii(texto.strip())
        guardrails.append(r_pii.a_dict())
        v_sim = self.embebedor.embeber_textos([limpio], rol="simetrico")[0]
        protos = self.verificador_imagen.prototipos("inyeccion")
        guardrails.append(verificar_inyeccion(limpio, v_sim, protos if len(protos) else None,
                                              float(p("guardrails.tau_inyeccion", 0.80))).a_dict())
        tiempos["guardrails_entrada"] += (time.perf_counter() - marca) * 1000

        version_archivo = self.documentos.version_archivo()
        marca = time.perf_counter()
        v_consulta = self.embebedor.embeber_textos([limpio], rol="consulta")[0]
        if not sin_cache:
            previo = self.cache.exacta(limpio, filtros, version_archivo, version)
            tipo_cache = "exacta" if previo else None
            if previo is None:
                semantico = self.cache.semantica(v_consulta, version_archivo, version)
                if semantico:
                    previo, tipo_cache = semantico[0], "semantica"
            if previo:
                tiempos["cache"] += (time.perf_counter() - marca) * 1000
                registrar("C4", "acierto", cache=tipo_cache, espacio="busquedas")
                previo["meta"].update(cache=tipo_cache, tiempo_ms=round((time.perf_counter() - t0) * 1000, 1),
                                      traza_id=traza_actual(), tiempos_por_capa_ms={c: round(v, 1) for c, v in tiempos.items()},
                                      guardrails={"entrada": guardrails, "salida": previo["meta"]["guardrails"]["salida"]})
                self._registrar_cierre(previo)
                return previo
        tiempos["cache"] += (time.perf_counter() - marca) * 1000

        marca = time.perf_counter()
        decision = self.enrutador.decidir_texto(limpio, v_sim)
        ruta = forzar_ruta if (self.config.modo_evaluacion and forzar_ruta in ("simple", "compleja")) else decision.ruta
        tiempos["enrutador"] += (time.perf_counter() - marca) * 1000
        interpretada = {"consulta_semantica": limpio, "excluir": [], "filtros": {"contiene_personas": None},
                        "terminos_tesauro": []}
        if ruta == "compleja":
            marca = time.perf_counter()
            try:
                s = self.gateway.ejecutar("P4", {"consulta": limpio})
                modelo = s.modelo
                interpretada = {"consulta_semantica": s.datos.get("consulta_semantica") or limpio,
                                "excluir": [x for x in s.datos.get("excluir", []) if x],
                                "filtros": {"contiene_personas": s.datos.get("contiene_personas")},
                                "terminos_tesauro": [x for x in s.datos.get("terminos", []) if x]}
            except (ServicioNoDisponible, TiempoAgotado):
                registrar("C2", "p4_fallo_busqueda_simple")   # último recurso: búsqueda simple con el texto original
            tiempos["modelo_composicion"] += (time.perf_counter() - marca) * 1000

        consultas = [interpretada["consulta_semantica"]]
        tau = float(p("enrutador_busquedas.tau_busqueda", 0.0) or 0.0)
        max_iter = 2
        while True:
            marca = time.perf_counter()
            resultados = self._recuperar(consultas, k, interpretada)
            tiempos["contexto"] += (time.perf_counter() - marca) * 1000
            suficientes = [r for r in resultados if r["coseno_imagen"] >= tau]
            if suficientes or iteraciones >= max_iter or not tau:
                break
            iteraciones += 1
            marca = time.perf_counter()
            try:
                s = self.gateway.ejecutar("P5", {"consulta": limpio})
                modelo = modelo or s.modelo
                consultas = [c for c in s.datos.get("reformulaciones", []) if c][:3] or consultas
            except (ServicioNoDisponible, TiempoAgotado):
                tiempos["modelo_composicion"] += (time.perf_counter() - marca) * 1000
                break
            tiempos["modelo_composicion"] += (time.perf_counter() - marca) * 1000
            registrar("C2", "reformular_busqueda", iteracion=iteraciones, consultas=consultas)

        relevantes = [r for r in resultados if r["coseno_imagen"] >= tau] if tau else resultados
        salida = self._responder(relevantes, interpretada, ruta, modelo, guardrails, iteraciones, t0, tiempos, version)
        if not sin_cache:
            self.cache.guardar(limpio, filtros, version_archivo, version, v_consulta, salida)
        self._registrar_cierre(salida)
        return salida

    @staticmethod
    def _registrar_cierre(respuesta: dict) -> None:
        m = respuesta["meta"]
        registrar("C2", "busqueda_completa", duracion_ms=m["tiempo_ms"], ruta=m["ruta"], cache=m["cache"],
                  modelo=m.get("modelo"), tiempos_por_capa_ms=m["tiempos_por_capa_ms"], guardrails=m["guardrails"],
                  iteraciones_agente=m["iteraciones_agente"], resultados=len(respuesta["resultados"]))

    def _recuperar(self, consultas: list[str], k: int, interpretada: dict) -> list[dict]:
        vectores = self.embebedor.embeber_textos(consultas, rol="consulta")
        listas = []
        for v in vectores:
            listas.append(self.vectorial.buscar(col.FOTOS_IMG, v, k * 2))
            listas.append(self.vectorial.buscar(col.FOTOS_TXT, v, k * 2))
        fusion = rrf(listas, limite=k * 2)
        excluir = interpretada.get("excluir") or []
        v_excluir = self.embebedor.embeber_textos(excluir, rol="consulta") if excluir else None
        personas = (interpretada.get("filtros") or {}).get("contiene_personas")
        tau_excluir = float(self.config.parametro("enrutador_busquedas.tau_excluir", 0.6))
        vec_txt = self.vectorial.obtener_vectores(col.FOTOS_TXT, [f"{c}#descripcion" for c, _, _ in fusion]) if excluir else {}
        # Coseno texto→imagen con la consulta principal para TODOS los candidatos (misma escala para el umbral)
        sin_img = [c for c, _, d in fusion if not any(n % 2 == 0 for n in d["cosenos"])]
        extra = {c: float(np.dot(v, vectores[0])) for c, v in self.vectorial.obtener_vectores(col.FOTOS_IMG, sin_img).items()}
        salida = []
        for c, puntaje, detalle in fusion:
            reg = self.documentos.obtener_ficha(c)
            f = reg.ficha if reg else None
            texto_ficha = " ".join([f.titular, f.descripcion, f.texto_alternativo] + [x.termino for x in f.palabras_clave]) if f else ""
            cos_img = max([v for n, v in detalle["cosenos"].items() if n % 2 == 0], default=extra.get(c))
            cos_txt = max([v for n, v in detalle["cosenos"].items() if n % 2 == 1], default=None)
            penalizacion, razones_pen = 1.0, []
            for termino, v in zip(excluir, v_excluir if v_excluir is not None else []):
                vt = vec_txt.get(f"{c}#descripcion")
                parecido = vt is not None and float(np.dot(v, vt)) >= tau_excluir
                if termino.lower() in texto_ficha.lower() or parecido:
                    penalizacion *= 0.5
                    razones_pen.append(f"Penalizada: la ficha se relaciona con «{termino}», que se pidió excluir")
            if personas is not None and f is not None:
                tiene = bool(PERSONAS.search(texto_ficha))
                if tiene != personas:
                    penalizacion *= 0.5
                    razones_pen.append("Penalizada: " + ("la ficha menciona personas" if tiene else "la ficha no menciona personas"))
            salida.append({"documento_id": c, "puntaje_rrf": puntaje * penalizacion,
                           "coseno_imagen": round(cos_img, 4) if cos_img is not None else 0.0,
                           "coseno_texto": cos_txt, "ficha": f, "penalizaciones": razones_pen})
        salida.sort(key=lambda r: -r["puntaje_rrf"])
        return salida[:k]

    def _razones(self, r: dict, interpretada: dict) -> list[str]:
        razones = []
        if r["coseno_imagen"]:
            razones.append(f"Similitud texto→imagen {r['coseno_imagen']:.2f}")
        if r["coseno_texto"] is not None:
            razones.append(f"Similitud con la ficha validada {r['coseno_texto']:.2f}")
        f = r["ficha"]
        if f is not None:
            terminos = {t.lower() for t in interpretada.get("terminos_tesauro", [])}
            palabras_consulta = set(re.findall(r"\w{4,}", interpretada.get("consulta_semantica", "").lower()))
            for pc in f.palabras_clave:
                if pc.termino.lower() in terminos or pc.termino.lower() in palabras_consulta:
                    razones.append(f"Coincide con el término del tesauro «{pc.termino}»" if pc.origen == "tesauro"
                                   else f"Coincide con la palabra clave «{pc.termino}»")
        return razones + r["penalizaciones"]

    def _responder(self, resultados, interpretada, ruta, modelo, guardrails, iteraciones, t0, tiempos, version) -> dict:
        marca = time.perf_counter()
        items = [{"documento_id": r["documento_id"], "puntaje": round(r["coseno_imagen"] or r["coseno_texto"] or 0.0, 4),
                  "miniatura_url": f"/api/fotos/{r['documento_id']}/miniatura",
                  "titular": r["ficha"].titular if r["ficha"] else None,
                  "texto_alternativo": r["ficha"].texto_alternativo if r["ficha"] else None,
                  "razones": self._razones(r, interpretada)} for r in resultados]
        expuestas = [k for it in items for k in it if k in CLAVES_PROHIBIDAS]
        salida_g = ResultadoGuardrail("salida_busqueda", "aprobada" if not expuestas else "sanitizado",
                                      detalle={"campos_internos_expuestos": expuestas})
        tiempos["guardrails_salida"] += (time.perf_counter() - marca) * 1000
        return {
            "resultados": items,
            "mensaje": None if items else "No encontré fotos que coincidan con la búsqueda. Prueba con otras palabras.",
            "consulta_interpretada": interpretada,
            "meta": {"ruta": ruta, "modelo": modelo, "cache": "ninguna",
                     "guardrails": {"entrada": guardrails, "salida": [salida_g.a_dict()]},
                     "iteraciones_agente": iteraciones, "tiempo_ms": round((time.perf_counter() - t0) * 1000, 1),
                     "tiempos_por_capa_ms": {c: round(v, 1) for c, v in tiempos.items()},
                     "traza_id": traza_actual(), "version_configuracion": version, "aviso": AVISO},
        }

    # ───────────────────────────── por imagen ─────────────────────────────
    def buscar_imagen(self, contenido: bytes, k: int = 12) -> dict:
        t0 = time.perf_counter()
        tiempos: dict[str, float] = defaultdict(float)
        marca = time.perf_counter()
        imagen, r1 = verificar_archivo(contenido)
        limpio, r2 = sanitizar(contenido, imagen.formato)       # la imagen de consulta no se guarda
        vector = self.embebedor.embeber_imagenes([limpio])[0]
        r3 = self.verificador_imagen.fuera_de_dominio(vector)
        tiempos["guardrails_entrada"] += (time.perf_counter() - marca) * 1000
        marca = time.perf_counter()
        encontrados = self.vectorial.buscar(col.FOTOS_IMG, vector, k)
        tiempos["contexto"] += (time.perf_counter() - marca) * 1000
        tau_dup = float(self.config.parametro("cache.fichas.tau_dup", 0.97))
        resultados = []
        for r in encontrados:
            doc = r.carga.get("documento_id", r.id)
            reg = self.documentos.obtener_ficha(doc)
            razones = [f"Similitud imagen→imagen {r.puntaje:.2f}"]
            if r.puntaje >= tau_dup:
                razones.append("Posible duplicado de esta foto")
            resultados.append({"documento_id": doc, "puntaje": round(r.puntaje, 4),
                               "miniatura_url": f"/api/fotos/{doc}/miniatura",
                               "titular": reg.ficha.titular if reg else None,
                               "texto_alternativo": reg.ficha.texto_alternativo if reg else None, "razones": razones})
        version = self.config.version_configuracion(self.version_corpus())
        respuesta = {"resultados": resultados, "mensaje": None if resultados else "El archivo todavía no tiene fotos.",
                "consulta_interpretada": {"consulta_semantica": None, "excluir": [], "filtros": {}, "terminos_tesauro": []},
                "meta": {"ruta": "imagen", "modelo": None, "cache": "ninguna",
                         "guardrails": {"entrada": [r1.a_dict(), r2.a_dict(), r3.a_dict()],
                                        "salida": [ResultadoGuardrail("salida_busqueda", "aprobada").a_dict()]},
                         "iteraciones_agente": 0, "tiempo_ms": round((time.perf_counter() - t0) * 1000, 1),
                         "tiempos_por_capa_ms": {c: round(v, 1) for c, v in tiempos.items()},
                         "traza_id": traza_actual(), "version_configuracion": version, "aviso": AVISO}}
        self._registrar_cierre(respuesta)
        return respuesta
