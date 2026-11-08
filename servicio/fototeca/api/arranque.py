"""Raíz de composición (C1): lee la configuración, construye los adaptadores de C7, los conecta con los
puertos (incluidos los de T1 y T2) y arma la aplicación FastAPI.

Es el único módulo que conoce las clases concretas de los adaptadores. Cambiar de base vectorial o de servidor
de modelos se resuelve aquí, sin tocar las capas superiores.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import yaml
from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.staticfiles import StaticFiles

from fototeca import __version__
from fototeca.api.errores import instalar_manejadores
from fototeca.api.middleware import MiddlewareTraza
from fototeca.api.rutas import busquedas as rutas_busquedas
from fototeca.api.rutas import documentos as rutas_documentos
from fototeca.api.rutas import fichas as rutas_fichas
from fototeca.api.rutas import observabilidad as rutas_observabilidad
from fototeca.api.rutas import sistema
from fototeca.cache.cache_busquedas import CacheBusquedas
from fototeca.cache.cache_fichas import CacheFichas
from fototeca.datos.cache_sqlite import CacheSqlite
from fototeca.datos.documentos_sqlite import DocumentosSqlite
from fototeca.datos.embebedor_ollama import EmbebedorOllama
from fototeca.datos.eventos_sqlite import EventosSqlite
from fototeca.datos.lotes_sqlite import LotesSqlite
from fototeca.datos.ollama_cliente import OllamaCliente
from fototeca.datos.puertos import (AlmacenCache, AlmacenDocumentos, AlmacenLotes, AlmacenVectorial, ClienteLLM,
                                    Embebedor)
from fototeca.datos.qdrant_almacen import QdrantAlmacen
from fototeca.datos.retroalimentacion_sqlite import RetroalimentacionSqlite
from fototeca.dominio.configuracion import Configuracion
from fototeca.guardrails.entrada.imagen import VerificadorImagen
from fototeca.modelos.enrutador_busquedas import EnrutadorBusquedas
from fototeca.modelos.gateway import Gateway
from fototeca.modelos.plantillas import cargar_plantillas, versiones
from fototeca.observabilidad.puertos import SumideroEventos
from fototeca.observabilidad.registro import configurar_sumidero
from fototeca.orquestacion.flujo_busqueda import FlujoBusqueda
from fototeca.orquestacion.flujo_ficha import FlujoFicha
from fototeca.orquestacion.ingesta import FlujoIngesta
from fototeca.orquestacion.lotes import GestorLotes
from fototeca.orquestacion.metricas import FlujoMetricas
from fototeca.orquestacion.retroalimentacion import FlujoRetroalimentacion
from fototeca.orquestacion.salud import FlujoSalud
from fototeca.retroalimentacion.puertos import AlmacenRetroalimentacion
from fototeca.retroalimentacion.servicio import ServicioRetroalimentacion

DIR_SERVICIO = Path(__file__).resolve().parents[2]
ESTATICOS = Path(__file__).resolve().parent / "estaticos"

DESCRIPCION = """
**Fototeca Viva** cataloga archivos fotográficos de forma accesible y trazable.

- `POST /fichas` genera la ficha IPTC de una foto; cada campo indica su fuente.
- `POST /busquedas` busca por texto en español o por foto y explica cada coincidencia.
- `GET /duplicados` reporta casi duplicados.
- `POST /retroalimentacion` liga la opinión del archivista a la traza; al validar una ficha, esta se vuelve un
  ejemplo más para catalogar fotos parecidas (el archivo aprende sin fine-tuning).
- `GET /metricas` resume latencias por capa, caché, guardrails, modelos, rutas, agente, retroalimentación y la
  accesibilidad del archivo.

Todas las respuestas llevan la cabecera `X-Traza-Id`. Los errores tienen la forma
`{"error": {"codigo", "mensaje", "traza_id"}}`.

> Las fichas y los resultados los generan modelos de IA y pueden contener errores. Revísalos antes de publicarlos.
"""

ETIQUETAS = [
    {"name": "Fichas", "description": "Catalogación de fotos (ficha IPTC con fuentes) y lotes asíncronos"},
    {"name": "Búsquedas", "description": "Búsqueda por texto en español o por foto, con razones"},
    {"name": "Documentos", "description": "Carga de fotos y normas, listado, eliminación y miniaturas"},
    {"name": "Duplicados", "description": "Grupos de casi duplicados detectados al cargar las fotos"},
    {"name": "Retroalimentación y métricas",
     "description": "Opinión ligada a la traza, validación de fichas (promoción a ejemplo del RAG) y métricas de "
                    "observabilidad y de accesibilidad del archivo"},
    {"name": "Sistema", "description": "Salud del servicio y configuración activa"},
]


def _env(nombre: str, por_defecto: str) -> str:
    return os.environ.get(nombre) or por_defecto


def cargar_configuracion(modo_evaluacion: bool | None = None) -> Configuracion:
    dir_config = Path(_env("FOTOTECA_CONFIG", str(DIR_SERVICIO / "config")))
    parametros = yaml.safe_load((dir_config / "parametros.yaml").read_text(encoding="utf-8"))
    datos = Path(_env("FOTOTECA_DATA", str(DIR_SERVICIO / "data")))
    modelos = {
        "vision": _env("MODELO_RAPIDO", "qwen3.5:0.8b"),
        "composicion": _env("MODELO_CAPAZ", "lfm3:1.7b-q4_K_M"),
        "embedding": _env("EMB_PRINCIPAL", "embeddinggemma-2:440m"),
        "embedding_secundario": _env("EMB_SECUNDARIO", "granite-embedding:278m"),
    }
    urls = {"ollama": _env("OLLAMA_URL", "http://ollama:11434"), "qdrant": _env("QDRANT_URL", "http://qdrant:6333")}
    rutas = {"datos": str(datos), "sqlite": str(datos / "sqlite" / "fototeca.db"),
             "fotos": str(datos / "fotos"), "config": str(dir_config)}
    if modo_evaluacion is None:
        modo_evaluacion = _env("MODO_EVALUACION", "0").lower() in ("1", "true", "si", "sí")
    return Configuracion(parametros=parametros, modelos=modelos, urls=urls, rutas=rutas,
                         versiones_prompts=versiones(cargar_plantillas()),
                         version_servicio=__version__, modo_evaluacion=modo_evaluacion)


def construir_embebedores(config: Configuracion) -> tuple[EmbebedorOllama, EmbebedorOllama]:
    """Embebedor principal (texto e imagen, EmbeddingGemma-2) y secundario (solo texto, granite).

    Los usan el servicio y los scripts de preparación, para que los vectores se calculen siempre igual.
    """
    p = config.parametro("embeddings", {}) or {}
    prefijos = p.get("prefijos", {})
    limite = float(config.parametro("tiempos_limite_s.embedding", 30))

    def de(modelo: str) -> dict:
        return prefijos.get(modelo.split(":")[0], {})

    principal = EmbebedorOllama(config.urls["ollama"], config.modelos["embedding"],
                                prefijos=de(config.modelos["embedding"]), acepta_imagenes=True,
                                lado_imagen_px=int(p.get("lado_imagen_px", 768)), lote=int(p.get("lote", 8)),
                                tiempo_limite_s=limite)
    secundario = EmbebedorOllama(config.urls["ollama"], config.modelos["embedding_secundario"],
                                 prefijos=de(config.modelos["embedding_secundario"]), acepta_imagenes=False,
                                 lote=int(p.get("lote_texto", 32)), tiempo_limite_s=limite)
    return principal, secundario


@dataclass
class Contenedor:
    """Objetos ya conectados que usan las rutas (se guarda en `app.state.contenedor`)."""

    config: Configuracion
    cliente_llm: ClienteLLM
    almacen_vectorial: AlmacenVectorial
    almacen_documentos: AlmacenDocumentos
    almacen_cache: AlmacenCache
    sumidero_eventos: SumideroEventos
    almacen_retroalimentacion: AlmacenRetroalimentacion
    embebedor: Embebedor
    embebedor_secundario: Embebedor
    salud: FlujoSalud
    ingesta: FlujoIngesta
    gateway: Gateway
    verificador_imagen: VerificadorImagen
    cache_fichas: CacheFichas
    fichas: FlujoFicha
    busquedas: FlujoBusqueda
    lotes: GestorLotes
    retroalimentacion: FlujoRetroalimentacion
    metricas: FlujoMetricas


def ensamblar(config: Configuracion, *, cliente_llm: ClienteLLM, almacen_vectorial: AlmacenVectorial,
              almacen_documentos: AlmacenDocumentos, almacen_cache: AlmacenCache, sumidero_eventos: SumideroEventos,
              almacen_retroalimentacion: AlmacenRetroalimentacion, almacen_lotes: AlmacenLotes, embebedor: Embebedor,
              embebedor_secundario: Embebedor) -> Contenedor:
    """Conecta los flujos de C2 con los adaptadores dados (reales o falsos en las pruebas)."""
    configurar_sumidero(sumidero_eventos)

    def version_corpus() -> str:
        return almacen_documentos.leer_estado("version_corpus", "sin_corpus") or "sin_corpus"

    salud = FlujoSalud(config, cliente_llm, almacen_vectorial, almacen_documentos, almacen_cache,
                       version_corpus=version_corpus)
    # C3 y C4 que usan los flujos (sus umbrales se calibran en H5; sin calibrar, las verificaciones de imagen
    # solo registran y no bloquean)
    verificador_imagen = VerificadorImagen(config, almacen_vectorial, embebedor)
    # `fuera_de_dominio` corre ya al cargar la foto: una captura de documento no entra al archivo (422)
    ingesta = FlujoIngesta(config, almacen_documentos, almacen_vectorial, embebedor, cache=almacen_cache,
                           verificador_dominio=verificador_imagen.fuera_de_dominio)
    # C6: una sola interfaz hacia los modelos (tabla de tareas P1–P6, tiempo límite, reintento y respaldo)
    gateway = Gateway(cliente_llm, config, cargar_plantillas())
    cache_fichas = CacheFichas(config, almacen_cache, almacen_vectorial, almacen_documentos)
    fichas = FlujoFicha(config, almacen_documentos, almacen_vectorial, embebedor, embebedor_secundario, gateway,
                        cache_fichas, verificador_imagen, version_corpus)
    busquedas = FlujoBusqueda(config, almacen_documentos, almacen_vectorial, embebedor, gateway,
                              CacheBusquedas(config, almacen_cache),
                              EnrutadorBusquedas(config, almacen_vectorial, embebedor), verificador_imagen,
                              version_corpus)
    lotes = GestorLotes(fichas, almacen_lotes)
    # T2 solo persiste y emite el evento; la promoción de la ficha validada al RAG de ejemplos la orquesta C2.
    # Las palabras clave corregidas pasan por el mismo guardrail `tesauro` (C3) que las del modelo.
    servicio_retroalimentacion = ServicioRetroalimentacion(almacen_retroalimentacion)
    retroalimentacion = FlujoRetroalimentacion(servicio_retroalimentacion, sumidero_eventos, almacen_documentos,
                                               almacen_vectorial, embebedor, embebedor_secundario, almacen_cache,
                                               normalizar_palabras=fichas.semanticos.normalizar_palabras)
    # `GET /metricas` combina T1 (eventos), T2 (opiniones) y el estado del archivo (C7)
    metricas = FlujoMetricas(sumidero_eventos, servicio_retroalimentacion, almacen_documentos)
    return Contenedor(config=config, cliente_llm=cliente_llm, almacen_vectorial=almacen_vectorial,
                      almacen_documentos=almacen_documentos, almacen_cache=almacen_cache,
                      sumidero_eventos=sumidero_eventos, almacen_retroalimentacion=almacen_retroalimentacion,
                      embebedor=embebedor, embebedor_secundario=embebedor_secundario, salud=salud, ingesta=ingesta,
                      gateway=gateway, verificador_imagen=verificador_imagen, cache_fichas=cache_fichas,
                      fichas=fichas, busquedas=busquedas, lotes=lotes, retroalimentacion=retroalimentacion,
                      metricas=metricas)


def construir_contenedor(config: Configuracion) -> Contenedor:
    sqlite = Path(config.rutas["sqlite"])
    principal, secundario = construir_embebedores(config)
    return ensamblar(
        config,
        # Qwen recibe las imágenes al lado calibrado en H0 (generacion.lado_max_imagen_px)
        cliente_llm=OllamaCliente(config.urls["ollama"], list(config.modelos.values()),
                                  lado_imagen_px=int(config.parametro("generacion.lado_max_imagen_px", 768))),
        almacen_vectorial=QdrantAlmacen(config.urls["qdrant"]),
        almacen_documentos=DocumentosSqlite(sqlite, config.rutas["fotos"], config.rutas["datos"]),
        almacen_cache=CacheSqlite(sqlite),
        sumidero_eventos=EventosSqlite(sqlite),
        almacen_retroalimentacion=RetroalimentacionSqlite(sqlite),
        almacen_lotes=LotesSqlite(sqlite),
        embebedor=principal,
        embebedor_secundario=secundario,
    )


def crear_app(contenedor: Contenedor | None = None, precalentar: bool | None = None) -> FastAPI:
    contenedor = contenedor or construir_contenedor(cargar_configuracion())
    if precalentar is None:
        precalentar = _env("FOTOTECA_PRECALENTAR", "1") == "1"

    @asynccontextmanager
    async def ciclo_de_vida(_: FastAPI):
        if precalentar:
            contenedor.salud.precalentar_en_segundo_plano()
            contenedor.lotes.reanudar_pendientes()   # lotes que quedaron a medias si el servicio se reinició
        yield

    app = FastAPI(title="Fototeca Viva · API", version=__version__, description=DESCRIPCION,
                  openapi_tags=ETIQUETAS, docs_url=None, redoc_url=None, lifespan=ciclo_de_vida)
    app.state.contenedor = contenedor
    app.add_middleware(MiddlewareTraza)
    instalar_manejadores(app)
    app.include_router(rutas_fichas.router)
    app.include_router(rutas_busquedas.router)
    app.include_router(rutas_documentos.router)
    app.include_router(rutas_observabilidad.router)
    app.include_router(sistema.router)

    # Swagger UI servido con assets locales (sin CDN): la demo funciona sin red.
    app.mount("/estaticos", StaticFiles(directory=ESTATICOS), name="estaticos")

    @app.get("/docs", include_in_schema=False)
    def documentacion():
        return get_swagger_ui_html(openapi_url=app.openapi_url, title="Fototeca Viva · API",
                                   swagger_js_url="/estaticos/swagger-ui-bundle.js",
                                   swagger_css_url="/estaticos/swagger-ui.css",
                                   swagger_favicon_url="/estaticos/favicon.png")

    return app
