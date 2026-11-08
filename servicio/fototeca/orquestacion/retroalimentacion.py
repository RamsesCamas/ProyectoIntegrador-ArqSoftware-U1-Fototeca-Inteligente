"""Retroalimentación y promoción de fichas validadas (C2): el archivo aprende de las correcciones sin fine-tuning.

`POST /retroalimentacion`:

    BUSCAR_TRAZA (la ficha o búsqueda debe existir en la bitácora; si no, 404)
      → VALIDAR_PETICION (campos editables, tipos y longitudes del esquema IPTC; 400 si algo no cumple)
      → [validar_ficha] PROMOVER: se aplican las correcciones y la ficha pasa a `validada`; se calcula el embedding
        de su descripción (EmbeddingGemma-2 y granite) y se inserta en `fotos_txt` y `fotos_txt_granite` con
        `validada=true`; su vector de imagen en `fotos_img` también queda `validada=true`; se invalida la caché de
        fichas que dependía de la foto (`doc:<id>`) y se incrementa `version_archivo`, lo que invalida la caché de
        búsquedas. A partir de ahí la ficha es un ejemplo más del RAG para fotos parecidas.
      → GUARDAR (T2 persiste la opinión ligada a la traza, con su ruta y sus modelos, y emite el evento)

Los embeddings se calculan antes de tocar el almacén: si el servidor de modelos o la base vectorial fallan, la
petición devuelve 503 y nada queda a medias (ni la ficha marcada como validada ni la opinión registrada).
"""
from __future__ import annotations

from typing import Callable

import numpy as np
from pydantic import ValidationError

from fototeca.datos.puertos import AlmacenCache, AlmacenDocumentos, AlmacenVectorial, Embebedor
from fototeca.dominio import colecciones as col
from fototeca.dominio.errores import NoEncontrado, PeticionInvalida
from fototeca.dominio.esquemas_ficha import Ficha, FichaRegistrada, Fuente, PalabraClave
from fototeca.guardrails.salida.reglas import CAMPOS_TEXTO, LIMITES
from fototeca.observabilidad.puertos import EventoCapa, SumideroEventos
from fototeca.observabilidad.registro import registrar
from fototeca.retroalimentacion.puertos import RegistroRetroalimentacion
from fototeca.retroalimentacion.servicio import ServicioRetroalimentacion

CAMPOS_EDITABLES = set(CAMPOS_TEXTO) | {"palabras_clave"}
EVENTOS_CIERRE = ("ficha_completa", "busqueda_completa")
NOMBRES = {"titular": "El titular", "descripcion": "La descripción", "texto_alternativo": "El texto alternativo",
           "descripcion_extendida": "La descripción extendida"}
PARTICION_VALIDADA = "validada_por_archivista"

NormalizarPalabras = Callable[[list[str]], tuple[list[PalabraClave], object]]


class FlujoRetroalimentacion:
    def __init__(self, servicio: ServicioRetroalimentacion, sumidero: SumideroEventos, documentos: AlmacenDocumentos,
                 vectorial: AlmacenVectorial, embebedor: Embebedor, embebedor_secundario: Embebedor,
                 cache: AlmacenCache | None, normalizar_palabras: NormalizarPalabras | None = None):
        self.servicio = servicio
        self.sumidero = sumidero
        self.documentos = documentos
        self.vectorial = vectorial
        self.embebedor = embebedor
        self.secundario = embebedor_secundario
        self.cache = cache
        self.normalizar_palabras = normalizar_palabras   # guardrail `tesauro` (C3), inyectado en la raíz de composición

    # ───────────────────────────── flujo ─────────────────────────────
    def registrar(self, traza_id: str, util: bool | None, comentario: str | None, correcciones: dict | None,
                  validar_ficha: bool) -> dict:
        cierre = self._cierre(traza_id)
        detalle = cierre.detalle or {}
        documento_id = detalle.get("documento_id")
        correcciones = dict(correcciones or {})
        comentario = (comentario or "").strip() or None
        desconocidos = set(correcciones) - CAMPOS_EDITABLES
        if desconocidos:
            raise PeticionInvalida(f"Campos no editables: {', '.join(sorted(desconocidos))}. Se pueden corregir: "
                                   f"{', '.join(sorted(CAMPOS_EDITABLES))}.")
        if validar_ficha and not documento_id:
            raise PeticionInvalida("Solo se puede validar la ficha de una foto; esta traza es de una búsqueda.")
        if util is None and not comentario and not correcciones and not validar_ficha:
            raise PeticionInvalida("La opinión está vacía: indica si fue útil, escribe un comentario o valida la ficha.")

        promocion: dict = {}
        if validar_ficha:
            nuevo = self._aplicar_correcciones(documento_id, correcciones, traza_id)   # 400/404 antes de escribir
            promocion = self._promover(nuevo, sorted(correcciones))
        modelos = detalle.get("modelos") or ({"busqueda": cierre.modelo} if cierre.modelo else {})
        registro = RegistroRetroalimentacion(traza_id=traza_id, util=util, documento_id=documento_id,
                                             comentario=comentario, correcciones=correcciones,
                                             validar_ficha=validar_ficha, ruta=cierre.ruta, modelos=modelos)
        identificador = self.servicio.guardar(registro)
        return {"registrado": True, "id": identificador, "traza_id": traza_id, "documento_id": documento_id,
                "ficha_validada": bool(promocion), "version_archivo": self.documentos.version_archivo(),
                "entradas_cache_invalidadas": promocion.get("entradas_cache_invalidadas"),
                "ficha": promocion.get("ficha")}

    def _cierre(self, traza_id: str) -> EventoCapa:
        """El evento con que terminó la ficha o la búsqueda de esa traza (liga la opinión con su ruta y modelos)."""
        eventos = self.sumidero.consultar(traza_id=traza_id)
        cierre = next((e for e in reversed(eventos) if e.capa == "C2" and e.evento in EVENTOS_CIERRE), None)
        if cierre is None:
            raise NoEncontrado("No existe una ficha o búsqueda con esa traza.", traza_id=traza_id)
        return cierre

    # ───────────────────────────── validación de la ficha ─────────────────────────────
    def _aplicar_correcciones(self, documento_id: str, correcciones: dict, traza_id: str) -> FichaRegistrada:
        registro = self.documentos.obtener_ficha(documento_id)
        if registro is None:
            raise NoEncontrado("La foto no tiene ficha que validar.", documento_id=documento_id)
        cambios: dict = {}
        for campo in CAMPOS_TEXTO:
            if campo not in correcciones:
                continue
            valor = correcciones[campo]
            if not isinstance(valor, str):
                raise PeticionInvalida(f"{NOMBRES[campo]} debe ser texto.")
            valor = " ".join(valor.split()) if campo != "descripcion_extendida" else valor.strip()
            if len(valor) > LIMITES[campo]:
                raise PeticionInvalida(f"{NOMBRES[campo]} debe tener {LIMITES[campo]} caracteres o menos "
                                       f"(tiene {len(valor)}).")
            cambios[campo] = valor
        fuentes = dict(registro.fuentes)
        archivista = Fuente(tipo="archivista", id=traza_id, titulo="Corrección del archivista")
        if "palabras_clave" in correcciones:
            lista = correcciones["palabras_clave"]
            if not isinstance(lista, list) or not all(isinstance(t, str) for t in lista):
                raise PeticionInvalida("`palabras_clave` debe ser una lista de términos (texto).")
            terminos = list(dict.fromkeys(t.strip() for t in lista if t.strip()))
            if self.normalizar_palabras:
                palabras, _ = self.normalizar_palabras(terminos)
            else:
                palabras = [PalabraClave(termino=t, origen="libre") for t in terminos]
            cambios["palabras_clave"] = palabras
            fuentes["palabras_clave"] = [archivista] + [Fuente(tipo="tesauro", id=p.uri, titulo=p.termino,
                                                               puntaje=p.similitud) for p in palabras if p.uri]
        for campo in CAMPOS_TEXTO:
            if campo in cambios:
                fuentes[campo] = [archivista]
        datos = {**registro.ficha.model_dump(), **cambios, "estado": "validada"}
        if not (datos.get("texto_alternativo") or "").strip():
            raise PeticionInvalida("Una ficha validada necesita texto alternativo (250 caracteres o menos).")
        try:
            ficha = Ficha.model_validate(datos)
        except ValidationError as e:
            errores = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:3])
            raise PeticionInvalida(f"La ficha corregida no cumple el esquema: {errores}.") from e
        origen = registro.origen if "archivista" in registro.origen else f"{registro.origen}+archivista"
        return registro.model_copy(update={"ficha": ficha, "fuentes": fuentes, "origen": origen})

    def _promover(self, nuevo: FichaRegistrada, campos: list[str]) -> dict:
        """La ficha validada se vuelve un ejemplo del RAG (fotos_txt, fotos_txt_granite y fotos_img)."""
        documento_id, ficha = nuevo.documento_id, nuevo.ficha
        texto = ficha.descripcion or ficha.texto_alternativo
        # 1) Primero lo que puede fallar por red (modelos y base vectorial): nada se escribe en el almacén antes.
        v_txt = np.asarray(self.embebedor.embeber_textos([texto], rol="documento"), dtype=np.float32)
        v_granite = np.asarray(self.secundario.embeber_textos([texto], rol="documento"), dtype=np.float32)
        previos = self.vectorial.vectores_por_filtro(col.FOTOS_IMG, {"documento_id": documento_id})
        if previos:
            _, v_img, carga_img = previos[0]
        else:   # la foto nunca se indexó (p. ej. falló al cargarla): se calcula su vector de imagen ahora
            v_img = self.embebedor.embeber_imagenes([self.documentos.obtener_foto(documento_id)])[0]
            doc = self.documentos.obtener_documento(documento_id) or {}
            carga_img = {"documento_id": documento_id, "particion": doc.get("particion") or PARTICION_VALIDADA}
        version = self.documentos.version_archivo() + 1
        carga_txt = {"documento_id": documento_id, "validada": True, "campo": "descripcion",
                     "particion": carga_img.get("particion") or PARTICION_VALIDADA, "version_archivo": version}
        for coleccion, vectores in ((col.FOTOS_TXT, v_txt), (col.FOTOS_TXT_GRANITE, v_granite)):
            self.vectorial.asegurar_coleccion(coleccion, int(vectores.shape[1]))
            self.vectorial.insertar(coleccion, [f"{documento_id}#descripcion"], vectores, [carga_txt])
        carga_img = {k: v for k, v in carga_img.items() if k != "id_externo"}
        self.vectorial.asegurar_coleccion(col.FOTOS_IMG, int(np.asarray(v_img).shape[-1]))
        self.vectorial.insertar(col.FOTOS_IMG, [documento_id], np.asarray(v_img, dtype=np.float32)[None, :],
                                [{**carga_img, "validada": True, "version_archivo": version}])
        # 2) El almacén: ficha validada, caché de fichas que dependía de la foto y versión del archivo.
        self.documentos.guardar_ficha(documento_id, nuevo)
        invalidadas = self.cache.invalidar_por_etiqueta(f"doc:{documento_id}") if self.cache else 0
        version = self.documentos.incrementar_version_archivo()
        registrar("C2", "promocion_ejemplo", documento_id=documento_id, campos=campos, cache_invalidada=invalidadas,
                  version_archivo=version, colecciones=[col.FOTOS_TXT, col.FOTOS_TXT_GRANITE, col.FOTOS_IMG])
        return {"entradas_cache_invalidadas": invalidadas, "ficha": ficha.model_dump()}
