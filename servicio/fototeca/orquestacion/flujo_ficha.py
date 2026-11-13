"""Flujo de la ficha (C2): máquina de estados explícita con ciclo de agente (ADR-07).

    RECIBIR → GUARDRAILS_ENTRADA ─(falla bloqueante)→ 422 con mensaje seguro
            → CACHE ─(acierto)→ GUARDRAILS_SALIDA_LIGEROS → RESPONDER
            → RECUPERAR_EJEMPLOS (unificado: imagen→imagen + imagen→texto, RRF)
            → EVALUAR_RECUPERACION ─(pobre y iteración < MAX_ITER)→ REFORMULAR → EVALUAR_RECUPERACION
            → ENRUTAR → GENERAR (rápida | completa) → GUARDRAILS_SALIDA
                 ─(falla reintentable y reintentos < 1)→ GENERAR (con la retroalimentación del validador)
                 ─(falla no reintentable)→ FICHA_DEGRADADA (requiere_revision)
            → GUARDAR → RESPONDER

Cada transición se registra en la traza (T1). Recuperación pobre: top-1 < τ_ret o top-1 − top-5 < δ_margen.
REFORMULAR es la ruta pipeline: Qwen describe (P1), la descripción se busca como texto en `fotos_txt` y se
fusiona con RRF; en la 2ª iteración se usan los `elementos` de P1 como consultas separadas. MAX_ITER = 2.
"""
from __future__ import annotations

import hashlib
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import numpy as np

from fototeca.cache.cache_fichas import CacheFichas
from fototeca.contexto.ensamblador_prompt import Contexto, id_foto, id_regla, id_tesauro, variables_p2, variables_p3
from fototeca.contexto.recuperador_ejemplos import Recuperacion, RecuperadorEjemplos
from fototeca.contexto.recuperador_normas import RecuperadorNormas
from fototeca.contexto.tesauro import Tesauro
from fototeca.datos.puertos import AlmacenDocumentos, AlmacenVectorial, Embebedor
from fototeca.dominio import colecciones as col
from fototeca.dominio.configuracion import Configuracion
from fototeca.dominio.errores import NoEncontrado, ServicioNoDisponible, TiempoAgotado
from fototeca.dominio.esquemas_ficha import Ficha, FichaRegistrada, Fuente, PalabraClave
from fototeca.guardrails.entrada.imagen import VerificadorImagen
from fototeca.guardrails.resultado import ResultadoGuardrail
from fototeca.guardrails.salida.reglas import (aplicar_reglas_iptc, recortar_longitudes, verificar_esquema,
                                              verificar_fuentes)
from fototeca.guardrails.salida.semanticas import GuardrailsSemanticos
from fototeca.modelos.enrutador_fichas import DecisionRuta, EnrutadorFichas
from fototeca.modelos.gateway import Gateway, SalidaTarea
from fototeca.modelos.plantillas import esquema_con_fuentes
from fototeca.observabilidad.registro import registrar
from fototeca.observabilidad.traza import traza_actual

AVISO = "Ficha generada por modelos de IA; puede contener errores. Revísala antes de publicarla."
CAPAS_TIEMPO = ("guardrails_entrada", "cache", "contexto", "enrutador", "modelo_vision", "modelo_composicion",
                "guardrails_salida")


@dataclass
class OpcionesFicha:
    """Opciones solo para evaluación (la API las ignora si MODO_EVALUACION no está activo)."""

    forzar_ruta: str | None = None
    sin_rag: bool = False
    sin_cache: bool = False
    max_iter: int | None = None
    p1_previo: dict | None = None             # R3 (ADR-01): misma descripción P1 para comparar composiciones
    modelo_composicion: str | None = None     # R3: «vision» (Qwen) o «composicion» (LFM3) para P3


@dataclass
class EstadoFicha:
    documento_id: str
    imagen: bytes
    vector: np.ndarray
    sha256: str
    opciones: OpcionesFicha
    version: str = ""
    version_corpus: str = ""
    guardrails_entrada: list[dict] = field(default_factory=list)
    guardrails_salida: list[dict] = field(default_factory=list)
    texto_visible_detectado: bool = False
    recuperacion: Recuperacion | None = None
    iteraciones: int = 0
    p1: dict | None = None
    p1_fallo: bool = False
    decision: DecisionRuta | None = None
    ruta: str = ""
    salida: SalidaTarea | None = None
    ficha: Ficha | None = None
    fuentes: dict[str, list[Fuente]] = field(default_factory=dict)
    advertencias: list[str] = field(default_factory=list)
    modelos: dict[str, str] = field(default_factory=dict)
    cache: str = "ninguna"
    duplicado_de: dict | None = None
    reintentos_generacion: int = 0
    revision: list[str] = field(default_factory=list)
    tiempos: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    transiciones: list[str] = field(default_factory=list)
    respuesta_cache: dict | None = None
    contexto: Contexto | None = None


class _Cronometro:
    def __init__(self, estado: EstadoFicha, capa: str):
        self.estado, self.capa = estado, capa

    def __enter__(self):
        self.t0 = time.perf_counter()

    def __exit__(self, *_):
        self.estado.tiempos[self.capa] += (time.perf_counter() - self.t0) * 1000


def recuperacion_pobre(config: Configuracion, top1: float, margen: float) -> bool:
    """Regla del ciclo de agente (ADR-07): top-1 bajo τ_ret o margen top-1/top-5 bajo δ. Sin τ calibrado, nunca."""
    tau = config.parametro("agente.tau_ret")
    if tau is None:
        return False
    return top1 < float(tau) or margen < float(config.parametro("agente.delta_margen", 0.02))


class FlujoFicha:
    def __init__(self, config: Configuracion, documentos: AlmacenDocumentos, vectorial: AlmacenVectorial,
                 embebedor: Embebedor, embebedor_secundario: Embebedor, gateway: Gateway, cache: CacheFichas,
                 verificador_imagen: VerificadorImagen, version_corpus):
        self.config = config
        self.documentos = documentos
        self.vectorial = vectorial
        self.embebedor = embebedor
        self.gateway = gateway
        self.cache = cache
        self.verificador_imagen = verificador_imagen
        self.version_corpus = version_corpus
        self.recuperador = RecuperadorEjemplos(vectorial, embebedor, documentos,
                                               k=int(config.parametro("recuperacion.k_ejemplos", 5)),
                                               rrf_k=int(config.parametro("recuperacion.rrf_k", 60)))
        self.normas = RecuperadorNormas(vectorial, embebedor, k=int(config.parametro("recuperacion.k_normas", 4)))
        self.tesauro = Tesauro(vectorial, embebedor)
        self.enrutador = EnrutadorFichas(config)
        self.semanticos = GuardrailsSemanticos(config, embebedor, embebedor_secundario, self.tesauro, gateway)

    # ───────────────────────────── máquina de estados ─────────────────────────────
    def ejecutar(self, documento_id: str, opciones: OpcionesFicha | None = None) -> dict:
        t0 = time.perf_counter()
        doc = self.documentos.obtener_documento(documento_id)
        if not doc or doc["tipo"] != "foto":
            raise NoEncontrado("La foto no existe.", documento_id=documento_id)
        imagen = self.documentos.obtener_foto(documento_id)
        vectores = self.vectorial.obtener_vectores(col.FOTOS_IMG, [documento_id])
        vector = vectores.get(documento_id)
        if vector is None:
            vector = self.embebedor.embeber_imagenes([imagen])[0]
        e = EstadoFicha(documento_id=documento_id, imagen=imagen, vector=np.asarray(vector, dtype=np.float32),
                        sha256=hashlib.sha256(imagen).hexdigest(), opciones=opciones or OpcionesFicha())
        # Los guardrails que ya corrieron al cargar la foto (archivo válido, EXIF, fuera de dominio) se reportan aquí
        e.guardrails_entrada = [{**g, "etapa": "ingesta"} for g in (doc.get("metadatos") or {}).get("guardrails_ingesta", [])]
        e.version_corpus = self.version_corpus()
        e.version = self.config.version_configuracion(e.version_corpus)
        e.modelos["embedding"] = self.embebedor.nombre_modelo
        pasos = {
            "GUARDRAILS_ENTRADA": self._guardrails_entrada, "CACHE": self._cache,
            "RECUPERAR_EJEMPLOS": self._recuperar, "EVALUAR_RECUPERACION": self._evaluar,
            "REFORMULAR": self._reformular, "ENRUTAR": self._enrutar, "GENERAR": self._generar,
            "GUARDRAILS_SALIDA": self._guardrails_salida, "FICHA_DEGRADADA": self._degradar,
            "GUARDRAILS_SALIDA_LIGEROS": self._salida_ligera, "GUARDAR": self._guardar,
        }
        estado = "GUARDRAILS_ENTRADA"
        while estado != "RESPONDER":
            siguiente = pasos[estado](e)
            e.transiciones.append(f"{estado}→{siguiente}")
            registrar("C2", "transicion", de=estado, a=siguiente, documento_id=documento_id)
            estado = siguiente
        respuesta = self._responder(e, (time.perf_counter() - t0) * 1000)
        meta = respuesta["meta"]
        registrar("C2", "ficha_completa", duracion_ms=meta["tiempo_ms"], ruta=e.ruta, cache=e.cache,
                  documento_id=documento_id, tiempos_por_capa_ms=meta["tiempos_por_capa_ms"],
                  guardrails=meta["guardrails"], iteraciones_agente=e.iteraciones, modelos=e.modelos,
                  estado_ficha=e.ficha.estado if e.ficha else None)
        return respuesta

    # ── estados ──
    def _guardrails_entrada(self, e: EstadoFicha) -> str:
        with _Cronometro(e, "guardrails_entrada"):
            r_dom = self.verificador_imagen.fuera_de_dominio(e.vector)     # lanza 422 si no es una foto
            r_txt = self.verificador_imagen.texto_visible(e.vector)
        e.guardrails_entrada += [r_dom.a_dict(), r_txt.a_dict()]
        e.texto_visible_detectado = r_txt.resultado == "marcada"
        return "CACHE"

    def _cache(self, e: EstadoFicha) -> str:
        if e.opciones.sin_cache:
            return "RECUPERAR_EJEMPLOS"
        with _Cronometro(e, "cache"):
            acierto = self.cache.exacta(e.sha256, e.version) or self.cache.semantica(e.vector, e.version, e.documento_id)
        if acierto:
            e.cache = acierto.tipo
            e.duplicado_de = acierto.duplicado_de
            e.respuesta_cache = acierto.respuesta
            registrar("C4", "acierto", cache=acierto.tipo, nivel=acierto.nivel, duplicado_de=acierto.duplicado_de)
            return "GUARDRAILS_SALIDA_LIGEROS"
        registrar("C4", "fallo", cache="ninguna")
        return "RECUPERAR_EJEMPLOS"

    def _recuperar(self, e: EstadoFicha) -> str:
        if e.opciones.sin_rag:
            e.recuperacion = Recuperacion([], 0.0, 0.0, {})
            return "ENRUTAR"
        with _Cronometro(e, "contexto"):
            listas = self.recuperador.listas_unificadas(e.vector, e.documento_id)
            e.recuperacion = self.recuperador.fusionar(e.vector, listas)
        registrar("C5", "recuperar_ejemplos", top1=e.recuperacion.top1, top5=e.recuperacion.top5,
                  vecinos=e.recuperacion.ids(), iteracion=e.iteraciones)
        return "EVALUAR_RECUPERACION"

    def _max_iter(self, e: EstadoFicha) -> int:
        if e.opciones.max_iter is not None:
            return e.opciones.max_iter
        return int(self.config.parametro("agente.max_iter", 2))

    def _es_pobre(self, r: Recuperacion) -> bool:
        return recuperacion_pobre(self.config, r.top1, r.margen)

    def _evaluar(self, e: EstadoFicha) -> str:
        pobre = self._es_pobre(e.recuperacion)
        registrar("C2", "evaluar_recuperacion", pobre=pobre, top1=e.recuperacion.top1, margen=round(e.recuperacion.margen, 4),
                  iteracion=e.iteraciones, max_iter=self._max_iter(e))
        if pobre and e.iteraciones < self._max_iter(e):
            return "REFORMULAR"
        return "ENRUTAR"

    def _describir(self, e: EstadoFicha) -> None:
        """P1 una sola vez por ficha (la reutilizan el ciclo de agente y la ruta completa)."""
        if e.p1 is not None or e.p1_fallo:
            return
        if self.config.modo_evaluacion and e.opciones.p1_previo:
            e.p1 = dict(e.opciones.p1_previo)
            e.modelos["vision"] = self.config.modelos["vision"]
        if e.p1 is not None:
            return
        with _Cronometro(e, "modelo_vision"):
            try:
                s = self.gateway.ejecutar("P1", {}, imagenes=[e.imagen])
                e.p1 = s.datos
                e.modelos["vision"] = s.modelo
            except (ServicioNoDisponible, TiempoAgotado) as ex:
                e.p1_fallo = True
                e.advertencias.append("No se pudo obtener la descripción objetiva de la imagen; se usaron solo las "
                                      "fotos similares.")
                registrar("C6", "p1_fallo", error=type(ex).__name__)
        if e.p1 is not None:
            if [t for t in e.p1.get("texto_visible", []) if isinstance(t, str) and t.strip()]:
                # P1 vio texto escrito (p. ej. durante el ciclo de agente, antes de enrutar): la ficha va por la ruta
                # completa, donde ese texto entra a P3 aislado como dato, nunca por la rápida (Qwen lo «leería»).
                e.texto_visible_detectado = True
            r = self.verificador_imagen.inyeccion_en_texto_visible(e.p1.get("texto_visible", []))
            e.guardrails_entrada.append(r.a_dict())
            if r.resultado == "marcada":
                e.advertencias.append("La foto contiene texto visible; se trató como dato, no como instrucción.")
                if r.detalle.get("confianza_alta"):
                    e.revision.append("posible inyección de instrucciones en el texto de la imagen")

    def _reformular(self, e: EstadoFicha) -> str:
        e.iteraciones += 1
        self._describir(e)
        if e.p1 is None:
            return "ENRUTAR"
        with _Cronometro(e, "contexto"):
            consultas = [e.p1.get("descripcion_visual", "")] if e.iteraciones == 1 else e.p1.get("elementos", [])[:5]
            nuevas = self.recuperador.listas_texto(consultas, e.documento_id, prefijo=f"texto_it{e.iteraciones}")
            listas = {**e.recuperacion.listas, **nuevas}
            antes = e.recuperacion.top1
            e.recuperacion = self.recuperador.fusionar(e.vector, listas)
        registrar("C2", "reformular", iteracion=e.iteraciones, consultas=len(consultas), top1_antes=antes,
                  top1_despues=e.recuperacion.top1, vecinos=e.recuperacion.ids())
        return "EVALUAR_RECUPERACION"

    def _enrutar(self, e: EstadoFicha) -> str:
        with _Cronometro(e, "enrutador"):
            e.decision = self.enrutador.decidir(e.recuperacion.vecinos, e.texto_visible_detectado)
            e.ruta = e.decision.ruta
            if self.config.modo_evaluacion and e.opciones.forzar_ruta in ("rapida", "completa"):
                e.ruta = e.opciones.forzar_ruta
                e.decision.razones.append(f"ruta forzada por evaluación: {e.ruta}")
            if e.ruta == "completa" and e.p1_fallo:
                e.ruta = "rapida"
                e.decision.razones.append("sin descripción objetiva (P1 falló): ruta rápida con advertencia")
        registrar("C6", "enrutar", ruta=e.ruta, senales=e.decision.senales, razones=e.decision.razones)
        return "GENERAR"

    def _contexto(self, e: EstadoFicha, consulta_tesauro: str) -> Contexto:
        vecinos = list(e.recuperacion.vecinos)
        palabras = [p.termino for v in vecinos if v.ficha for p in v.ficha.ficha.palabras_clave]
        reglas = self.normas.recuperar(palabras)
        tau = float(self.config.parametro("guardrails.tau_tesauro", 0.75))
        terminos = self.tesauro.candidatos(consulta_tesauro, k=int(self.config.parametro("recuperacion.k_tesauro", 10)),
                                           umbral=tau) if consulta_tesauro else []
        return Contexto(vecinos=vecinos, reglas=reglas, terminos=terminos, sin_rag=e.opciones.sin_rag)

    def _generar(self, e: EstadoFicha) -> str:
        retroalimentacion = e.revision[-1] if e.reintentos_generacion else None
        try:
            if e.ruta == "completa":
                self._describir(e)
                if e.p1 is None:
                    e.ruta = "rapida"
            if e.ruta == "completa":
                with _Cronometro(e, "contexto"):
                    e.contexto = self._contexto(e, e.p1.get("descripcion_visual", ""))
                    variables = variables_p3(e.p1, e.contexto, self.gateway.plantillas["P3"].sistema,
                                             presupuesto=int(self.config.parametro("recuperacion.presupuesto_prompt_tokens", 2000)),
                                             caracteres_por_token=float(self.config.parametro("recuperacion.caracteres_por_token", 3.5)))
                if retroalimentacion:
                    variables["descripcion_visual"] += f"\n(Corrección pedida por el validador: {retroalimentacion})"
                rol = e.opciones.modelo_composicion if (self.config.modo_evaluacion and
                                                        e.opciones.modelo_composicion in ("vision", "composicion")) else None
                gramatica = esquema_con_fuentes(self.gateway.plantillas["P3"].esquema,
                                                e.contexto.ids_citables("completa"))
                with _Cronometro(e, "modelo_composicion"):
                    e.salida = self.gateway.ejecutar("P3", variables, rol=rol, esquema_gramatica=gramatica)
                e.modelos["composicion"] = e.salida.modelo
                if e.salida.respaldo:
                    e.advertencias.append(f"Se usó el modelo de respaldo ({e.salida.modelo}) para componer la ficha.")
            else:
                with _Cronometro(e, "contexto"):
                    descripcion = " ".join(v.ficha.ficha.descripcion for v in e.recuperacion.vecinos[:2] if v.ficha)
                    e.contexto = self._contexto(e, descripcion)
                    variables = variables_p2(e.contexto)
                gramatica = esquema_con_fuentes(self.gateway.plantillas["P2"].esquema,
                                                e.contexto.ids_citables("rapida"))
                with _Cronometro(e, "modelo_vision"):
                    e.salida = self.gateway.ejecutar("P2", variables, imagenes=[e.imagen], esquema_gramatica=gramatica)
                e.modelos["vision"] = e.salida.modelo
        except (ServicioNoDisponible, TiempoAgotado) as ex:
            registrar("C2", "generacion_fallida", ruta=e.ruta, error=type(ex).__name__)
            e.revision.append(f"la generación falló ({type(ex).__name__})")
            return "FICHA_DEGRADADA"
        return "GUARDRAILS_SALIDA"

    def _guardrails_salida(self, e: EstadoFicha) -> str:
        datos = dict(e.salida.datos)
        datos.setdefault("descripcion", "")
        datos.setdefault("descripcion_extendida", "")
        datos.setdefault("advertencias", [])
        palabras_crudas = [p for p in datos.get("palabras_clave", []) if isinstance(p, str)]
        # Los modelos citan con alias cortos (F1, R1, T1); aquí se traducen a los ids reales del contexto.
        fuentes_crudas = e.contexto.resolver_citas(datos.get("fuentes", {})) if e.contexto else datos.get("fuentes", {})
        datos["palabras_clave"] = []
        datos["advertencias"] = [a for a in datos.get("advertencias", []) if isinstance(a, str)]
        resultados: list[ResultadoGuardrail] = []
        with _Cronometro(e, "guardrails_salida"):
            crudos, recortes = recortar_longitudes({k: datos[k] for k in ("titular", "descripcion", "texto_alternativo",
                                                                          "descripcion_extendida", "advertencias")
                                                    if k in datos})
            ficha, r = verificar_esquema(crudos)
            resultados.append(r)
            if ficha is None:
                e.guardrails_salida += [x.a_dict() for x in resultados]
                return self._reintentar_o_degradar(e, "el JSON no cumple el esquema de la ficha")
            ficha, r = aplicar_reglas_iptc(ficha, recortes)
            resultados.append(r)
            if r.resultado == "marcada":
                e.guardrails_salida += [x.a_dict() for x in resultados]
                return self._reintentar_o_degradar(e, "el texto alternativo quedó vacío; escribe uno de 250 caracteres o menos")
            ficha, r = self.semanticos.atributos_sensibles(ficha)
            resultados.append(r)
            if r.resultado == "sanitizado" and e.reintentos_generacion == 0:
                e.guardrails_salida += [x.a_dict() for x in resultados]
                return self._reintentar_o_degradar(e, "no atribuyas a las personas etnia, religión, salud, discapacidad u "
                                                      "orientación, ni las identifiques por nombre")
            if r.resultado == "sanitizado":
                e.revision.append("se eliminaron atributos sensibles")
            palabras, r = self.semanticos.normalizar_palabras(palabras_crudas)
            resultados.append(r)
            ficha = ficha.model_copy(update={"palabras_clave": palabras})
            r = self.semanticos.apego_visual(e.vector, ficha.texto_alternativo)
            resultados.append(r)
            if r.resultado == "marcada":
                if e.ruta == "rapida" and e.reintentos_generacion == 0 and not e.p1_fallo:
                    e.guardrails_salida += [x.a_dict() for x in resultados]
                    e.ruta = "completa"
                    e.reintentos_generacion += 1
                    e.revision.append("el texto alternativo no se apegaba a la imagen; se reintentó por la ruta completa")
                    return "GENERAR"
                e.revision.append("el texto alternativo tiene poco apego visual a la imagen")
            r = self.semanticos.consistencia(ficha.texto_alternativo, (e.p1 or {}).get("descripcion_visual"))
            if r is not None:
                resultados.append(r)
                if r.resultado == "marcada":
                    e.revision.append("el texto alternativo no es consistente con la descripción objetiva")
            ids_validos = e.contexto.ids_validos() if e.contexto else set()
            presentes = {c for c in ("titular", "descripcion", "texto_alternativo") if getattr(ficha, c)}
            limpias, r = verificar_fuentes(fuentes_crudas, ids_validos, campos=("titular", "descripcion",
                                                                                 "texto_alternativo"), campos_presentes=presentes)
            resultados.append(r)
            if r.resultado == "marcada" and not e.opciones.sin_rag:
                e.revision.append("hay campos sin fuente verificable")
        e.guardrails_salida += [x.a_dict() for x in resultados]
        e.fuentes = self._fuentes(e, limpias, ficha)
        e.advertencias += ficha.advertencias
        estado = "requiere_revision" if e.revision else "borrador"
        e.ficha = ficha.model_copy(update={"estado": estado, "advertencias": list(dict.fromkeys(e.advertencias))})
        return "GUARDAR"

    def _reintentar_o_degradar(self, e: EstadoFicha, motivo: str) -> str:
        e.revision.append(motivo)
        if e.reintentos_generacion < 1:
            e.reintentos_generacion += 1
            return "GENERAR"
        return "FICHA_DEGRADADA"

    def _degradar(self, e: EstadoFicha) -> str:
        """Último recurso: ficha armada solo con los vecinos, en estado requiere_revision."""
        vecinos = e.recuperacion.vecinos if e.recuperacion else []
        conteo = Counter((p.termino, p.uri) for v in vecinos if v.ficha for p in v.ficha.ficha.palabras_clave)
        palabras = [PalabraClave(termino=t, uri=u, origen="tesauro" if u else "libre") for (t, u), _ in conteo.most_common(6)]
        e.advertencias.append("No se pudo generar la ficha con los modelos; se armó solo con las fotos similares. "
                              "Revísala y complétala.")
        e.ficha = Ficha(palabras_clave=palabras, advertencias=list(dict.fromkeys(e.advertencias)), estado="requiere_revision")
        e.fuentes = {"palabras_clave": [Fuente(tipo="foto_similar", id=v.documento_id, puntaje=v.similitud_imagen)
                                        for v in vecinos[:3]]}
        e.ruta = e.ruta or "degradada"
        registrar("C2", "ficha_degradada", motivo=e.revision[-1] if e.revision else None)
        return "GUARDAR"

    def _salida_ligera(self, e: EstadoFicha) -> str:
        """Acierto de caché: la ficha ya pasó sus guardrails; solo se revisan el esquema y las reglas IPTC."""
        with _Cronometro(e, "guardrails_salida"):
            ficha, r1 = verificar_esquema(e.respuesta_cache.get("ficha", {}))
            if ficha is not None:
                ficha, r2 = aplicar_reglas_iptc(ficha)
                e.guardrails_salida += [r1.a_dict(), r2.a_dict()]
        if ficha is None:
            e.respuesta_cache = None
            e.cache = "ninguna"
            return "RECUPERAR_EJEMPLOS"
        e.fuentes = {k: [Fuente.model_validate(f) for f in v] for k, v in e.respuesta_cache.get("fuentes", {}).items()}
        e.ruta = "cache"
        if e.duplicado_de:
            # La ficha es de OTRA foto (posible duplicado): se entrega como propuesta para revisar, nunca como
            # validada, y se guarda para esta foto (ADR-04).
            e.advertencias.append(f"Posible duplicado de {e.duplicado_de['documento_id']} "
                                  f"(similitud {e.duplicado_de['similitud']}). La ficha se tomó de esa foto; revísala.")
            e.revision.append("ficha tomada de un posible duplicado")
            ficha = ficha.model_copy(update={"estado": "requiere_revision",
                                             "advertencias": list(dict.fromkeys(ficha.advertencias + e.advertencias))})
            if self.documentos.obtener_ficha(e.documento_id) is None:
                self.documentos.guardar_ficha(e.documento_id, FichaRegistrada(
                    documento_id=e.documento_id, ficha=ficha, fuentes=e.fuentes, origen="cache", traza_id=traza_actual()))
        e.ficha = ficha
        return "RESPONDER"

    def _guardar(self, e: EstadoFicha) -> str:
        previa = self.documentos.obtener_ficha(e.documento_id)
        if previa is not None and previa.ficha.estado == "validada":
            # Una ficha validada (por el archivista o de referencia humana) nunca se sobrescribe con una propuesta del
            # modelo: la nueva se entrega en la respuesta, pero no se guarda.
            e.advertencias.append("La foto ya tiene una ficha validada; esta propuesta no la reemplazó.")
            e.ficha = e.ficha.model_copy(update={"advertencias": list(dict.fromkeys(e.advertencias))})
            registrar("C2", "ficha_no_guardada", motivo="ya existe una ficha validada", documento_id=e.documento_id)
        else:
            registro = FichaRegistrada(documento_id=e.documento_id, ficha=e.ficha, fuentes=e.fuentes, origen="modelo",
                                       traza_id=traza_actual())
            self.documentos.guardar_ficha(e.documento_id, registro)
        if not e.opciones.sin_cache and e.ruta != "degradada":
            respuesta = {"documento_id": e.documento_id, "ficha": e.ficha.model_dump(),
                         "fuentes": {k: [f.model_dump() for f in v] for k, v in e.fuentes.items()},
                         "meta": {"ruta": e.ruta}}
            fuente_docs = [e.documento_id] + [f.id for fs in e.fuentes.values() for f in fs if f.tipo == "foto_similar"]
            with _Cronometro(e, "cache"):
                self.cache.guardar(e.sha256, e.version, e.vector, respuesta, fuente_docs, e.version_corpus)
        return "RESPONDER"

    # ── utilidades ──
    def _fuentes(self, e: EstadoFicha, limpias: dict[str, list[str]], ficha: Ficha) -> dict[str, list[Fuente]]:
        ctx = e.contexto or Contexto()
        por_id: dict[str, Fuente] = {}
        for v in ctx.vecinos:
            por_id[id_foto(v.documento_id)] = Fuente(tipo="foto_similar", id=v.documento_id, puntaje=v.similitud_imagen,
                                                     titulo=v.ficha.ficha.titular if v.ficha else None)
        for r in ctx.reglas:
            texto = (r.carga.get("texto") or "").strip()
            por_id[id_regla(r)] = Fuente(tipo="regla", id=r.id, titulo=r.carga.get("seccion"), puntaje=round(r.puntaje, 4),
                                         url=r.carga.get("url"),
                                         extracto=(texto[:280].rsplit(" ", 1)[0] + "…") if len(texto) > 280 else texto or None)
        for t in ctx.terminos:
            por_id[id_tesauro(t)] = Fuente(tipo="tesauro", id=t.carga.get("uri", t.id), titulo=t.carga.get("etiqueta_es"),
                                           puntaje=round(t.puntaje, 4))
        salida = {campo: [por_id[i] for i in ids if i in por_id] for campo, ids in limpias.items()}
        salida = {k: v for k, v in salida.items() if v}
        tesauro = [Fuente(tipo="tesauro", id=p.uri, titulo=p.termino, puntaje=p.similitud) for p in ficha.palabras_clave if p.uri]
        if tesauro:
            salida["palabras_clave"] = salida.get("palabras_clave", []) + tesauro
        return salida

    def _responder(self, e: EstadoFicha, tiempo_ms: float) -> dict:
        senales = e.decision.senales if e.decision else {}
        return {
            "documento_id": e.documento_id,
            "ficha": e.ficha.model_dump(),
            "fuentes": {k: [f.model_dump() for f in v] for k, v in e.fuentes.items()},
            "meta": {
                "ruta": e.ruta, "modelos": e.modelos, "cache": e.cache,
                "guardrails": {"entrada": e.guardrails_entrada, "salida": e.guardrails_salida},
                "iteraciones_agente": e.iteraciones, "duplicado_de": e.duplicado_de,
                "senales_enrutador": senales, "razones_enrutador": e.decision.razones if e.decision else [],
                "recuperacion": {"top1": e.recuperacion.top1, "top5": e.recuperacion.top5} if e.recuperacion else None,
                "revision": e.revision, "transiciones": e.transiciones,
                "tiempo_ms": round(tiempo_ms, 1),
                "tiempos_por_capa_ms": {c: round(e.tiempos.get(c, 0.0), 1) for c in CAPAS_TIEMPO if c in e.tiempos},
                "traza_id": traza_actual(), "version_configuracion": e.version, "aviso": AVISO,
            },
        }
