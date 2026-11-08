"""Guardrails de entrada de la imagen que usan embeddings (docs/specs/06, C3; ADR-05).

- `fuera_de_dominio`: similitud de la imagen con los prototipos «una fotografía de una escena real» contra «una
  captura de un documento, tabla o interfaz». Si la diferencia queda bajo el umbral calibrado → bloquear (422).
- `inyeccion_en_imagen`, en dos etapas (decisión documentada en docs/bitacora.md):
  1. antes de enrutar, `texto_visible`: la imagen se compara con prototipos de «foto con texto escrito»; si se
     detecta texto, el enrutador manda la foto por la ruta completa (Qwen nunca la «lee» como instrucción);
  2. en la ruta completa, P1 copia el texto visible y aquí se combinan heurísticas («ignora», «instrucciones»,
     «system», «eres», «responde», «olvida»…) con la similitud contra los prototipos de inyección. Política: NO se
     bloquea la foto; el texto se aísla entre delimitadores en P3, se agrega una advertencia y, si la confianza
     es alta, la ficha queda `requiere_revision`.
Mientras un umbral no esté calibrado (H5), la verificación aprueba y lo deja anotado en lugar de bloquear a ciegas.
"""
from __future__ import annotations

import re

import numpy as np

from fototeca.datos.puertos import AlmacenVectorial, Embebedor
from fototeca.dominio import colecciones as col
from fototeca.dominio.configuracion import Configuracion
from fototeca.dominio.errores import BloqueadoPorGuardrail
from fototeca.guardrails.entrada.texto import PATRONES_INYECCION
from fototeca.guardrails.politicas import MENSAJES_SEGUROS, politica
from fototeca.guardrails.resultado import ResultadoGuardrail

PALABRAS_SPEC = re.compile(r"\b(ignor\w*|instruc\w*|system|sistema:|eres|responde\w*|olvid\w*|obedece\w*|prompt)\b", re.I)
_PATRONES = [re.compile(p, re.I) for p in PATRONES_INYECCION]


class VerificadorImagen:
    def __init__(self, config: Configuracion, vectorial: AlmacenVectorial, embebedor: Embebedor):
        self.config = config
        self.vectorial = vectorial
        self.embebedor = embebedor
        self._cache: dict[tuple[str, str], np.ndarray] = {}

    def prototipos(self, tipo: str, clase: str | None = None) -> np.ndarray:
        clave = (tipo, clase or "*")
        if clave not in self._cache:
            filtro = {"tipo": tipo, **({"clase": clase} if clase else {})}
            puntos = self.vectorial.vectores_por_filtro(col.PROTOTIPOS, filtro)
            self._cache[clave] = np.stack([v for _, v, _ in puntos]) if puntos else np.zeros((0, 1), np.float32)
        return self._cache[clave]

    def _diferencia(self, vector: np.ndarray, tipo: str, positiva: str, negativa: str) -> float | None:
        a, b = self.prototipos(tipo, positiva), self.prototipos(tipo, negativa)
        if not len(a) or not len(b):
            return None
        return float(np.max(a @ vector) - np.max(b @ vector))

    def fuera_de_dominio(self, vector: np.ndarray) -> ResultadoGuardrail:
        """valor = sim(foto) − sim(documento/tabla/interfaz). Bajo el umbral → no es una fotografía."""
        dif = self._diferencia(vector, "dominio", "fotografia", "fuera_de_dominio")
        umbral = self.config.parametro("guardrails.tau_fuera_dominio")
        if dif is None or umbral is None:
            return ResultadoGuardrail("fuera_de_dominio", "aprobada", valor=None if dif is None else round(dif, 4),
                                      detalle={"nota": "sin prototipos o umbral sin calibrar"})
        if dif < float(umbral):
            r = ResultadoGuardrail("fuera_de_dominio", "bloqueada", valor=round(dif, 4), umbral=float(umbral),
                                   politica_aplicada=politica("fuera_de_dominio"))
            raise BloqueadoPorGuardrail(MENSAJES_SEGUROS["fuera_de_dominio"], [r.a_dict()])
        return ResultadoGuardrail("fuera_de_dominio", "aprobada", valor=round(dif, 4), umbral=float(umbral))

    def texto_visible(self, vector: np.ndarray) -> ResultadoGuardrail:
        """valor = sim(foto con texto) − sim(foto sin texto). Sobre el umbral → hay texto visible (ruta completa)."""
        dif = self._diferencia(vector, "texto_visible", "con_texto", "sin_texto")
        umbral = self.config.parametro("guardrails.tau_texto_visible")
        if dif is None or umbral is None:
            return ResultadoGuardrail("texto_visible", "aprobada", valor=None if dif is None else round(dif, 4),
                                      detalle={"nota": "sin prototipos o umbral sin calibrar"})
        if dif >= float(umbral):
            return ResultadoGuardrail("texto_visible", "marcada", valor=round(dif, 4), umbral=float(umbral),
                                      politica_aplicada="ruta completa (el texto se aísla como dato)")
        return ResultadoGuardrail("texto_visible", "aprobada", valor=round(dif, 4), umbral=float(umbral))

    def inyeccion_en_texto_visible(self, textos: list[str]) -> ResultadoGuardrail:
        textos = [t for t in textos if isinstance(t, str) and t.strip()]
        if not textos:
            return ResultadoGuardrail("inyeccion_en_imagen", "aprobada", detalle={"texto_visible": 0})
        unido = " ".join(textos)
        heuristica = bool(PALABRAS_SPEC.search(unido)) or any(p.search(unido) for p in _PATRONES)
        protos = self.prototipos("inyeccion")
        similitud = None
        if len(protos):
            v = self.embebedor.embeber_textos([unido], rol="simetrico")[0]
            similitud = float(np.max(protos @ v))
        umbral = self.config.parametro("guardrails.tau_inyeccion")
        por_similitud = similitud is not None and umbral is not None and similitud >= float(umbral)
        detalle = {"texto_visible": len(textos), "heuristica": heuristica, "por_similitud": por_similitud,
                   "confianza_alta": heuristica and (por_similitud or umbral is None)}
        if heuristica or por_similitud:
            return ResultadoGuardrail("inyeccion_en_imagen", "marcada", valor=None if similitud is None else round(similitud, 4),
                                      umbral=None if umbral is None else float(umbral),
                                      politica_aplicada=politica("inyeccion_en_imagen"), detalle=detalle)
        return ResultadoGuardrail("inyeccion_en_imagen", "aprobada", valor=None if similitud is None else round(similitud, 4),
                                  umbral=None if umbral is None else float(umbral), detalle=detalle)
