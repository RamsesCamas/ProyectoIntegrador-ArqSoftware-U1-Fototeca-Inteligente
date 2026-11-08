"""POST /retroalimentacion, GET /metricas y GET /duplicados."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from fototeca.api.esquemas import respuestas_error
from fototeca.dominio.errores import PeticionInvalida
from fototeca.dominio.esquemas_ficha import Ficha

router = APIRouter()
ETIQUETA = "Retroalimentación y métricas"


# ───────────────────────────── retroalimentación ─────────────────────────────
class PeticionRetroalimentacion(BaseModel):
    traza_id: str = Field(min_length=4, max_length=40, examples=["c7f2a1b3"],
                          description="`meta.traza_id` de la ficha o de la búsqueda que se califica")
    util: bool | None = Field(None, description="Útil (true) / no útil (false)")
    comentario: str | None = Field(None, max_length=1000, examples=["El texto alternativo omite el toldo"])
    correcciones: dict[str, str | list[str]] = Field(
        default_factory=dict, description="Campos corregidos: titular, descripcion, texto_alternativo, "
                                          "descripcion_extendida (texto) o palabras_clave (lista de términos)",
        examples=[{"texto_alternativo": "Puesto de mercado con mangos y piñas bajo un toldo azul."}])
    validar_ficha: bool = Field(False, description="Aplica las correcciones, deja la ficha `validada` y la promueve "
                                                   "como ejemplo del RAG")


class RespuestaRetroalimentacion(BaseModel):
    registrado: bool
    id: int
    traza_id: str
    documento_id: str | None = None
    ficha_validada: bool
    version_archivo: int = Field(description="Cambia al validar una ficha: invalida la caché de búsquedas")
    entradas_cache_invalidadas: int | None = None
    ficha: Ficha | None = Field(None, description="La ficha ya validada (palabras clave normalizadas al tesauro)")


@router.post("/retroalimentacion", response_model=RespuestaRetroalimentacion, summary="Registrar una opinión",
             tags=[ETIQUETA], responses=respuestas_error(400, 404, 503))
def retroalimentacion(request: Request, peticion: PeticionRetroalimentacion) -> RespuestaRetroalimentacion:
    """Liga la opinión (útil o no, comentario y correcciones) con la traza de la ficha o de la búsqueda, para
    analizarla por ruta y por modelo. Con `validar_ficha`, aplica las correcciones, deja la ficha `validada`, calcula
    su embedding y la inserta en las colecciones de ejemplos con `validada=true`: desde ese momento guía la ficha
    de las fotos parecidas (el archivo aprende de las correcciones sin fine-tuning). 404 si la traza no existe."""
    r = request.app.state.contenedor.retroalimentacion.registrar(peticion.traza_id, peticion.util, peticion.comentario,
                                                                 peticion.correcciones, peticion.validar_ficha)
    return RespuestaRetroalimentacion(**r)


# ───────────────────────────── métricas ─────────────────────────────
class Percentiles(BaseModel):
    n: int
    p50_ms: float | None = None
    p95_ms: float | None = None
    media_ms: float | None = None
    max_ms: float | None = None


class TasaCache(BaseModel):
    consultas: int
    aciertos_exactos: int
    aciertos_semanticos: int
    tasa_aciertos: float | None = None


class ActivacionGuardrail(BaseModel):
    verificacion: str | None = None
    resultado: str | None = None
    n: int


class UsoModelo(BaseModel):
    llamadas: int
    tokens_prompt: int
    tokens_salida: int
    tiempo_ms: float
    respaldos: int
    tiempos_agotados: int
    json_invalido: int


class ResumenRetroalimentacion(BaseModel):
    total: int
    util: int
    no_util: int
    tasa_util: float | None = None
    con_comentario: int
    fichas_validadas: int
    campos_corregidos: dict[str, int]
    por_ruta: dict[str, dict[str, int]] = Field(description="Útil / no útil por ruta (rapida, completa, simple…)")
    por_modelo: dict[str, dict[str, int]] = Field(description="Útil / no útil por modelo que intervino")


class Accesibilidad(BaseModel):
    fotos: int
    alt_validado: int = Field(description="Fotos con ficha validada y texto alternativo no vacío")
    fichas_validadas: int
    requiere_revision: int
    borrador: int
    sin_ficha: int
    porcentaje_alt_validado: float | None = Field(None, description="Proporción (0–1) de fotos con texto alternativo "
                                                                    "validado")
    porcentaje_requiere_revision: float | None = None
    porcentaje_sin_ficha: float | None = None


class RespuestaMetricas(BaseModel):
    desde: str | None = Field(None, description="Inicio del periodo en UTC (null: todo el historial)")
    generado: str
    eventos_considerados: int
    latencia_por_endpoint: dict[str, Percentiles] = Field(description="«MÉTODO /ruta/{id}» → p50/p95 en ms")
    latencia_por_capa: dict[str, dict[str, Percentiles]] = Field(
        description="Por flujo (fichas, busquedas) y etapa: guardrails, caché, contexto, enrutador, modelos y total")
    latencia_por_evento: dict[str, dict[str, Percentiles]] = Field(
        description="Por capa de la arquitectura (C1–C7, T1, T2) y evento medido")
    cache: dict[str, TasaCache]
    guardrails: list[ActivacionGuardrail]
    bloqueos: dict[str, int]
    modelos: dict[str, UsoModelo]
    rutas: dict[str, int] = Field(description="«flujo:ruta» → veces que se eligió")
    iteraciones_agente: dict[str, int] = Field(description="Fichas: iteraciones del ciclo de agente → número de fichas")
    iteraciones_agente_busquedas: dict[str, int] = Field(description="Búsquedas: reformulaciones → número de búsquedas")
    retroalimentacion: ResumenRetroalimentacion
    accesibilidad: Accesibilidad


def normalizar_desde(desde: str | None) -> str | None:
    """Cualquier fecha ISO 8601 → instante UTC con segundos, comparable con las marcas de tiempo guardadas.
    Sin zona horaria se asume UTC. Un «+» sin codificar en la URL llega como espacio: se repone."""
    if not desde or not desde.strip():
        return None
    texto = re.sub(r"(T[\d:.]+) (\d{2}:?\d{2})$", r"\1+\2", desde.strip())
    texto = re.sub(r"[Zz]$", "+00:00", texto)
    try:
        instante = datetime.fromisoformat(texto)
    except ValueError as e:
        raise PeticionInvalida("`desde` debe ser una fecha ISO 8601, por ejemplo 2026-11-08T00:00:00Z.") from e
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=timezone.utc)
    return instante.astimezone(timezone.utc).isoformat(timespec="seconds")


@router.get("/metricas", response_model=RespuestaMetricas, tags=[ETIQUETA],
            summary="Métricas de observabilidad y accesibilidad del archivo", responses=respuestas_error(400))
def metricas(request: Request, desde: str | None = Query(None, description="Fecha ISO 8601 (p. ej. 2026-11-08T00:00:00Z)")
             ) -> RespuestaMetricas:
    """Latencia p50/p95 por endpoint, por etapa de cada flujo y por capa; aciertos de caché exactos y semánticos;
    activaciones de guardrails; uso por modelo; rutas del enrutador; iteraciones del agente; retroalimentación por
    ruta y por modelo; y accesibilidad del archivo (porcentaje de fotos con texto alternativo validado)."""
    return request.app.state.contenedor.metricas.obtener(normalizar_desde(desde))


# ───────────────────────────── duplicados ─────────────────────────────
class DocumentoDuplicado(BaseModel):
    id: str
    similitud: float = Field(description="Mayor similitud (coseno de imagen) con otra foto del grupo")
    titular: str | None = None
    texto_alternativo: str | None = None


class GrupoDuplicados(BaseModel):
    grupo_id: str
    documentos: list[DocumentoDuplicado]


@router.get("/duplicados", response_model=list[GrupoDuplicados], tags=["Duplicados"],
            summary="Grupos de casi duplicados")
def duplicados(request: Request) -> list[GrupoDuplicados]:
    """Fotos que la ingesta detectó como casi duplicadas (recortes, recompresiones, marcos), agrupadas: si A se
    parece a B y B a C, las tres quedan en el mismo grupo."""
    return [GrupoDuplicados(**g) for g in request.app.state.contenedor.metricas.duplicados()]
