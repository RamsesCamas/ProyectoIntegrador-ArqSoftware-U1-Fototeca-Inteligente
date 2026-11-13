"""Adaptadores falsos para probar las capas superiores sin Ollama ni Qdrant (implementan los puertos de C7)."""
from __future__ import annotations

import hashlib
import io

import numpy as np
from PIL import Image

from fototeca.dominio.entidades import RespuestaLLM, ResultadoVectorial


class ClienteLLMFalso:
    def __init__(self, modelos: list[str], disponible: bool = True, respuestas: list[str] | None = None):
        self.modelos = modelos
        self.disponible = disponible
        self.precalentados: list[str] = []
        self.respuestas = list(respuestas or [])
        self.llamadas: list[dict] = []

    def estado(self) -> dict:
        if not self.disponible:
            return {"estado": "error", "error": "Servidor de modelos no responde"}
        return {"estado": "ok", "version": "falso", "modelos_requeridos": self.modelos, "modelos_faltantes": [],
                "modelos_cargados": self.modelos}

    def precalentar(self, modelo: str, opciones: dict | None = None) -> None:
        self.precalentados.append(modelo)
        self.opciones_precalentar = getattr(self, "opciones_precalentar", {})
        self.opciones_precalentar[modelo] = opciones

    def generar(self, modelo, mensajes, *, imagenes=None, esquema_json=None, opciones, tiempo_limite_s):
        self.llamadas.append({"modelo": modelo, "mensajes": mensajes, "imagenes": len(imagenes or [])})
        texto = self.respuestas.pop(0) if self.respuestas else "{}"
        return RespuestaLLM(texto=texto, modelo=modelo, tokens_prompt=10, tokens_salida=10)


def _normalizar(v: np.ndarray) -> np.ndarray:
    return (v / max(np.linalg.norm(v), 1e-12)).astype(np.float32)


class EmbebedorFalso:
    """Imágenes: el vector es la imagen reducida a 4×4 en gris (fotos parecidas → vectores parecidos).
    Textos: un vector pseudoaleatorio determinista por texto."""

    def __init__(self, nombre: str = "falso", acepta_imagenes: bool = True):
        self.nombre_modelo = nombre
        self.dimension = 16
        self.acepta_imagenes = acepta_imagenes
        self.lado_imagen_px = 384

    def embeber_textos(self, textos, rol="documento") -> np.ndarray:
        filas = []
        for t in textos:
            semilla = int.from_bytes(hashlib.sha256(t.encode()).digest()[:8], "big")
            filas.append(_normalizar(np.random.default_rng(semilla).normal(size=16)))
        return np.stack(filas) if filas else np.zeros((0, 16), np.float32)

    def embeber_imagenes(self, imagenes) -> np.ndarray:
        if not self.acepta_imagenes:
            raise NotImplementedError("solo texto")
        filas = []
        for b in imagenes:
            with Image.open(io.BytesIO(b)) as im:
                v = np.asarray(im.convert("L").resize((4, 4)), dtype=np.float32).ravel() + 1.0
            filas.append(_normalizar(v - v.mean() * 0.5))
        return np.stack(filas)


def _cumple(carga: dict, filtro: dict | None) -> bool:
    for clave, valor in (filtro or {}).items():
        if isinstance(valor, dict) and "no" in valor:
            if carga.get(clave) == valor["no"]:
                return False
        elif isinstance(valor, dict) and "en" in valor:
            if carga.get(clave) not in valor["en"]:
                return False
        elif carga.get(clave) != valor:
            return False
    return True


class AlmacenVectorialFalso:
    def __init__(self, disponible: bool = True):
        self.disponible = disponible
        self.colecciones: dict[str, dict] = {}

    def estado(self) -> dict:
        if not self.disponible:
            return {"estado": "error", "error": "Base vectorial no responde"}
        return {"estado": "ok", "version": "falso",
                "colecciones": {n: len(c["puntos"]) for n, c in self.colecciones.items()}}

    def asegurar_coleccion(self, nombre: str, dimension: int) -> None:
        self.colecciones.setdefault(nombre, {"dimension": dimension, "puntos": {}})

    def insertar(self, coleccion, ids, vectores, cargas) -> None:
        self.asegurar_coleccion(coleccion, len(vectores[0]))
        for i, v, c in zip(ids, np.asarray(vectores), cargas):
            self.colecciones[coleccion]["puntos"][i] = (np.asarray(v, np.float32), dict(c))

    def buscar(self, coleccion, vector, k, filtro=None):
        puntos = self.colecciones.get(coleccion, {}).get("puntos", {})
        candidatos = [(i, float(np.dot(v, vector)), c) for i, (v, c) in puntos.items() if _cumple(c, filtro)]
        candidatos.sort(key=lambda t: -t[1])
        return [ResultadoVectorial(id=i, puntaje=s, carga=c) for i, s, c in candidatos[:k]]

    def eliminar(self, coleccion, ids) -> None:
        for i in ids:
            self.colecciones.get(coleccion, {}).get("puntos", {}).pop(i, None)

    def eliminar_por_documento(self, coleccion, documento_id) -> None:
        puntos = self.colecciones.get(coleccion, {}).get("puntos", {})
        for i in [i for i, (_, c) in puntos.items() if c.get("documento_id") == documento_id]:
            puntos.pop(i)

    def contar(self, coleccion, filtro=None) -> int:
        puntos = self.colecciones.get(coleccion, {}).get("puntos", {})
        return sum(1 for _, c in puntos.values() if _cumple(c, filtro))

    def obtener_vectores(self, coleccion, ids):
        puntos = self.colecciones.get(coleccion, {}).get("puntos", {})
        return {i: puntos[i][0] for i in ids if i in puntos}

    def vectores_por_filtro(self, coleccion, filtro=None):
        puntos = self.colecciones.get(coleccion, {}).get("puntos", {})
        return [(i, v, c) for i, (v, c) in puntos.items() if _cumple(c, filtro)]
