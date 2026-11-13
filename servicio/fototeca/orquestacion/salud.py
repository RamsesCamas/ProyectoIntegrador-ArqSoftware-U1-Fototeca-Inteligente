"""Flujo de salud y configuración: consulta el estado de cada recurso y precalienta los modelos."""
from __future__ import annotations

import threading
import time

from fototeca.datos.puertos import AlmacenCache, AlmacenDocumentos, AlmacenVectorial, ClienteLLM
from fototeca.dominio.configuracion import Configuracion
from fototeca.observabilidad.registro import medir, registrar

# Nombre y descripción legibles de cada componente (la web los muestra tal cual, sin conocer los recursos).
DESCRIPCIONES = {
    "servicio": ("Servicio (API)", "FastAPI con las capas C1–C7"),
    "ollama": ("Servidor de modelos (Ollama)", "Modelos de lenguaje y de embeddings, en CPU"),
    "qdrant": ("Base vectorial (Qdrant)", "Embeddings de fotos, normas y tesauro"),
    "almacen": ("Almacén de documentos", "Fotos, metadatos y fichas (SQLite y archivos)"),
    "cache": ("Caché", "Fichas y búsquedas ya resueltas (SQLite)"),
}


class FlujoSalud:
    def __init__(self, config: Configuracion, cliente_llm: ClienteLLM, almacen_vectorial: AlmacenVectorial,
                 almacen_documentos: AlmacenDocumentos, almacen_cache: AlmacenCache,
                 version_corpus: callable = lambda: "sin_corpus"):
        self.config = config
        self.cliente_llm = cliente_llm
        self.almacen_vectorial = almacen_vectorial
        self.almacen_documentos = almacen_documentos
        self.almacen_cache = almacen_cache
        self.version_corpus = version_corpus
        self.precalentamiento: dict = {"estado": "pendiente"}
        self._inicio = time.time()

    def verificar(self) -> dict:
        with medir("C2", "health") as d:
            componentes = {
                "ollama": self.cliente_llm.estado(),
                "qdrant": self.almacen_vectorial.estado(),
                "almacen": self.almacen_documentos.estado(),
                "cache": self.almacen_cache.estado(),
            }
            criticos = ("ollama", "qdrant", "almacen")
            if any(componentes[c].get("estado") != "ok" for c in criticos):
                estado = "error"
            elif componentes["cache"].get("estado") != "ok" or self.precalentamiento.get("estado") == "en_curso":
                estado = "degradado"
            else:
                estado = "ok"
            d["resultado"] = estado
        componentes = {"servicio": {"estado": "ok", "segundos_activo": round(time.time() - self._inicio)},
                       **componentes}
        for clave, (nombre, descripcion) in DESCRIPCIONES.items():
            componentes[clave] = {"nombre": nombre, "descripcion": descripcion, **componentes[clave]}
        return {
            "estado": estado,
            "componentes": componentes,
            "precalentamiento": self.precalentamiento,
            "versiones": {"servicio": self.config.version_servicio,
                          "configuracion": self.config.version_configuracion(self.version_corpus()),
                          "corpus": self.version_corpus()},
        }

    def configuracion(self) -> dict:
        return {
            "version_configuracion": self.config.version_configuracion(self.version_corpus()),
            "version_servicio": self.config.version_servicio,
            "version_corpus": self.version_corpus(),
            "modelos": self.config.modelos,
            "versiones_prompts": self.config.versiones_prompts,
            "parametros": self.config.parametros,
            "modo_evaluacion": self.config.modo_evaluacion,
        }

    def precalentar_en_segundo_plano(self) -> None:
        threading.Thread(target=self._precalentar, name="precalentar-modelos", daemon=True).start()

    def _opciones_carga(self, modelo: str) -> dict:
        """Las opciones con que se cargará el proceso del modelo: las mismas que el gateway envía en cada petición."""
        por_modelo = (self.config.parametro("generacion.por_modelo", {}) or {}).get(modelo, {})
        return {"num_ctx": int(self.config.parametro("generacion.num_ctx", 4096)), **(por_modelo.get("extra") or {})}

    def _precalentar(self) -> None:
        modelos = list(dict.fromkeys(self.config.modelos.values()))
        self.precalentamiento = {"estado": "en_curso", "modelos": modelos}
        t0 = time.perf_counter()
        fallidos = []
        for modelo in modelos:
            try:
                self.cliente_llm.precalentar(modelo, self._opciones_carga(modelo))
            except Exception as e:  # noqa: BLE001
                fallidos.append({"modelo": modelo, "error": str(e)[:160]})
        self.precalentamiento = {"estado": "error" if fallidos else "listo", "modelos": modelos,
                                 "segundos": round(time.perf_counter() - t0, 1), "fallidos": fallidos}
        registrar("C2", "precalentamiento", duracion_ms=(time.perf_counter() - t0) * 1000,
                  resultado=self.precalentamiento["estado"], modelos=modelos)
