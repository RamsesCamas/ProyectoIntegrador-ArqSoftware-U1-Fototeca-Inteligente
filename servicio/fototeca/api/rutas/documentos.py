"""POST/GET/DELETE /documentos y GET /fotos/{id}/miniatura."""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from fototeca.api.esquemas import ErrorDetalle, respuestas_error
from fototeca.dominio.errores import ArchivoDemasiadoGrande, ErrorDominio, PeticionInvalida
from fototeca.observabilidad.traza import traza_actual

router = APIRouter(tags=["Documentos"])


class Duplicado(BaseModel):
    documento_id: str
    similitud: float
    tipo: Literal["exacto", "semantico"]


class ResultadoDocumento(BaseModel):
    documento_id: str | None = None
    nombre: str
    tipo: str
    fragmentos: int = 0
    ya_existia: bool = False
    duplicados: list[Duplicado] = Field(default_factory=list)
    guardrails: list[dict] = Field(default_factory=list)
    error: ErrorDetalle | None = None


class RespuestaCarga(BaseModel):
    documentos: list[ResultadoDocumento]
    creados: int
    version_archivo: int | None = None
    traza_id: str | None = None


class DocumentoListado(BaseModel):
    documento_id: str
    tipo: str
    nombre: str
    fecha: str
    estado_ficha: str | None = None
    particion: str | None = None
    titular: str | None = Field(None, description="Titular de la ficha guardada; null si no hay ficha o está vacío")
    texto_alternativo: str | None = Field(None, description="Texto alternativo de la ficha guardada (el `alt` de la "
                                                            "miniatura); null si no hay ficha o está vacío")


class RespuestaListado(BaseModel):
    total: int
    pagina: int
    por_pagina: int
    documentos: list[DocumentoListado]


class RespuestaEliminacion(BaseModel):
    documento_id: str
    eliminado: bool
    vectores_eliminados: int
    entradas_cache_invalidadas: int
    version_archivo: int


@router.post("/documentos", status_code=201, response_model=RespuestaCarga,
             summary="Cargar fotos o documentos normativos",
             responses=respuestas_error(400, 413, 415, 422, 503))
def cargar(request: Request,
           archivos: list[UploadFile] = File(..., description="Una o varias fotos (JPEG o PNG, ≤10 MB) o normas "
                                                              "(HTML, Markdown, PDF o TXT)"),
           tipo: Literal["foto", "norma"] = Form("foto"),
           metadatos: str | None = Form(None, description='JSON opcional, p. ej. {"fuente": "...", "licencia": "..."}')):
    """Fotos: se validan (contenido real, tamaño y lados), se les quita el EXIF sensible, se guardan, se calcula su
    embedding, se detectan casi duplicados y se indexan. Normas: se fragmentan (una regla por fragmento), se
    embeben y se indexan. Con un solo archivo, un rechazo devuelve su código (413, 415 o 422); con varios, cada
    resultado indica su error y la respuesta es 201 si al menos uno se cargó."""
    try:
        meta = json.loads(metadatos) if metadatos else {}
        if not isinstance(meta, dict):
            raise ValueError
    except ValueError as e:
        raise PeticionInvalida("`metadatos` debe ser un objeto JSON.") from e
    flujo = request.app.state.contenedor.ingesta
    maximo = float(request.app.state.contenedor.config.parametro("guardrails.tamano_max_mb", 10))
    resultados, errores = [], []
    for archivo in archivos:
        nombre = archivo.filename or "sin_nombre"
        try:
            if archivo.size is not None and archivo.size > maximo * 1024 * 1024:
                raise ArchivoDemasiadoGrande(f"El archivo pesa {archivo.size / 2**20:.1f} MB; el máximo es {maximo:g} MB.")
            contenido = archivo.file.read()
            r = flujo.ingerir_foto(contenido, nombre, meta) if tipo == "foto" else flujo.ingerir_norma(contenido, nombre, meta)
            resultados.append(ResultadoDocumento(**asdict(r)))
        except ErrorDominio as e:
            if len(archivos) == 1:
                raise
            errores.append(e)
            resultados.append(ResultadoDocumento(nombre=nombre, tipo=tipo, error=ErrorDetalle(
                codigo=e.codigo, mensaje=getattr(e, "mensaje_seguro", e.mensaje), traza_id=traza_actual())))
    creados = sum(1 for r in resultados if r.error is None)
    if creados == 0 and errores:
        raise errores[0]
    cuerpo = RespuestaCarga(documentos=resultados, creados=creados,
                            version_archivo=request.app.state.contenedor.almacen_documentos.version_archivo(),
                            traza_id=traza_actual())
    return JSONResponse(cuerpo.model_dump(), status_code=201)


@router.get("/documentos", response_model=RespuestaListado, summary="Listar documentos indexados",
            responses=respuestas_error(400))
def listar(request: Request, tipo: Literal["foto", "norma"] | None = Query(None),
           pagina: int = Query(1, ge=1), por_pagina: int = Query(24, ge=1, le=200)) -> RespuestaListado:
    almacen = request.app.state.contenedor.almacen_documentos
    docs = almacen.listar(tipo, pagina, por_pagina)
    return RespuestaListado(total=almacen.contar(tipo), pagina=pagina, por_pagina=por_pagina,
                            documentos=[DocumentoListado(**asdict(d)) for d in docs])


@router.delete("/documentos/{documento_id}", response_model=RespuestaEliminacion,
               summary="Eliminar un documento, sus vectores, su ficha y la caché afectada",
               responses=respuestas_error(404, 503))
def eliminar(request: Request, documento_id: str) -> RespuestaEliminacion:
    return RespuestaEliminacion(**request.app.state.contenedor.ingesta.eliminar(documento_id))


@router.get("/fotos/{documento_id}/miniatura", summary="Miniatura JPEG (512 px como máximo, sin EXIF)",
            response_class=Response, responses={200: {"content": {"image/jpeg": {}}}, **respuestas_error(404)})
def miniatura(request: Request, documento_id: str, lado: int = Query(512, ge=64, le=512)) -> Response:
    contenido = request.app.state.contenedor.ingesta.miniatura(documento_id, lado)
    return Response(contenido, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})
