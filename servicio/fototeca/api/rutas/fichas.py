"""POST /fichas (función principal), GET /fichas/{id}, POST /lotes y GET /lotes/{id}."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from fototeca.api.esquemas import respuestas_error
from fototeca.dominio.errores import NoEncontrado, PeticionInvalida
from fototeca.dominio.esquemas_ficha import Ficha, FichaRegistrada, Fuente
from fototeca.orquestacion.flujo_ficha import OpcionesFicha

router = APIRouter(tags=["Fichas"])


class PeticionFicha(BaseModel):
    documento_id: str = Field(examples=["xm-000411001ff7dd4f"])
    # Opciones solo para evaluación: se ignoran si MODO_EVALUACION no está activo (informe, §10.1).
    forzar_ruta: Literal["rapida", "completa"] | None = None
    sin_rag: bool = False
    sin_cache: bool = False
    max_iter: int | None = Field(None, ge=0, le=2)
    p1_previo: dict | None = None
    modelo_composicion: Literal["vision", "composicion"] | None = None


class MetaFicha(BaseModel):
    ruta: str
    modelos: dict[str, str]
    cache: Literal["ninguna", "exacta", "semantica"]
    guardrails: dict[str, list[dict]]
    iteraciones_agente: int
    duplicado_de: dict | None = None
    tiempo_ms: float
    tiempos_por_capa_ms: dict[str, float]
    traza_id: str | None
    version_configuracion: str
    aviso: str
    senales_enrutador: dict = Field(default_factory=dict)
    razones_enrutador: list[str] = Field(default_factory=list)
    revision: list[str] = Field(default_factory=list)
    transiciones: list[str] = Field(default_factory=list)
    recuperacion: dict | None = None


class RespuestaFicha(BaseModel):
    documento_id: str
    ficha: Ficha
    fuentes: dict[str, list[Fuente]]
    meta: MetaFicha


class PeticionLote(BaseModel):
    documento_ids: list[str] = Field(min_length=1, max_length=200)


class RespuestaLoteCreado(BaseModel):
    lote_id: str
    total: int


class RespuestaLote(BaseModel):
    lote_id: str
    estado: str
    total: int
    completadas: int
    fallidas: int
    en_proceso: str | None = None
    fichas: list[dict]
    errores: list[dict]


CUERPO_FICHA = {"requestBody": {"required": True, "content": {
    "application/json": {"schema": PeticionFicha.model_json_schema()},
    "multipart/form-data": {"schema": {"type": "object", "required": ["foto"],
                                       "properties": {"foto": {"type": "string", "format": "binary"}}}}}}}


def _opciones(request: Request, datos: dict) -> OpcionesFicha:
    if not request.app.state.contenedor.config.modo_evaluacion:
        return OpcionesFicha()
    return OpcionesFicha(forzar_ruta=datos.get("forzar_ruta"), sin_rag=bool(datos.get("sin_rag")),
                         sin_cache=bool(datos.get("sin_cache")),
                         max_iter=None if datos.get("max_iter") in (None, "") else int(datos["max_iter"]),
                         p1_previo=datos.get("p1_previo") if isinstance(datos.get("p1_previo"), dict) else None,
                         modelo_composicion=datos.get("modelo_composicion"))


@router.post("/fichas", response_model=RespuestaFicha, summary="Catalogar una foto (función principal)",
             openapi_extra=CUERPO_FICHA, responses=respuestas_error(400, 404, 413, 415, 422, 503, 504))
async def crear_ficha(request: Request):
    """Genera la ficha catalográfica IPTC de una foto ya cargada (`{"documento_id": …}`) o de una foto nueva
    enviada en `multipart/form-data` (campo `foto`). Cada campo indica sus fuentes; `meta` describe la ruta, los
    modelos, la caché, los guardrails, las iteraciones del agente y el tiempo por capa."""
    c = request.app.state.contenedor
    tipo = request.headers.get("content-type", "")
    if tipo.startswith("multipart/form-data"):
        formulario = await request.form()
        foto = formulario.get("foto")
        if not isinstance(foto, UploadFile) and not hasattr(foto, "read"):
            raise PeticionInvalida("Envía la foto en el campo `foto` del formulario.")
        contenido = await foto.read()
        ingesta = await run_in_threadpool(c.ingesta.ingerir_foto, contenido, foto.filename or "foto", {})
        documento_id, datos = ingesta.documento_id, dict(formulario)
    else:
        try:
            peticion = PeticionFicha.model_validate(await request.json())
        except (ValidationError, ValueError) as e:
            raise PeticionInvalida("El cuerpo debe ser JSON con `documento_id`.") from e
        documento_id, datos = peticion.documento_id, peticion.model_dump()
    respuesta = await run_in_threadpool(c.fichas.ejecutar, documento_id, _opciones(request, datos))
    return JSONResponse(respuesta)


@router.get("/fichas/{documento_id}", response_model=FichaRegistrada, summary="Obtener la ficha guardada",
            responses=respuestas_error(404))
def obtener_ficha(request: Request, documento_id: str) -> FichaRegistrada:
    ficha = request.app.state.contenedor.almacen_documentos.obtener_ficha(documento_id)
    if ficha is None:
        raise NoEncontrado("La foto no tiene ficha todavía.", documento_id=documento_id)
    return ficha


@router.post("/lotes", status_code=202, response_model=RespuestaLoteCreado, summary="Catalogar varias fotos (asíncrono)",
             responses=respuestas_error(400, 404))
def crear_lote(request: Request, peticion: PeticionLote) -> RespuestaLoteCreado:
    """Un solo trabajador procesa las fichas de una en una; consulta el progreso con `GET /lotes/{lote_id}`."""
    c = request.app.state.contenedor
    faltan = [d for d in peticion.documento_ids if c.almacen_documentos.obtener_documento(d) is None]
    if faltan:
        raise NoEncontrado("Algunos documentos no existen.", documento_ids=faltan[:10])
    lote_id = c.lotes.crear(peticion.documento_ids)
    return RespuestaLoteCreado(lote_id=lote_id, total=len(peticion.documento_ids))


@router.get("/lotes/{lote_id}", response_model=RespuestaLote, summary="Progreso y fichas de un lote",
            responses=respuestas_error(404))
def obtener_lote(request: Request, lote_id: str) -> RespuestaLote:
    return RespuestaLote(**request.app.state.contenedor.lotes.obtener(lote_id))
