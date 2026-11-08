"""Verificaciones de salida que usan modelos (docs/specs/06, C3; ADR-05).

- `apego_visual`: similitud en EmbeddingGemma-2 entre la IMAGEN y el texto alternativo, contra el percentil 5 de
  la similitud imagen–descripción humana en el archivo. Política: reintentar por la ruta completa si venía de la
  rápida; si vuelve a fallar, marcar (la decide C2).
- `consistencia`: similitud en granite (verificador independiente) entre el texto alternativo y la descripción
  de Qwen (P1), contra el percentil 5 de la similitud entre dos descripciones humanas de una misma imagen.
  Política: marcar. Solo aplica cuando existe P1 (ruta completa o ciclo de agente).
- `atributos_sensibles`: el léxico detecta → P6 (Qwen, solo texto) confirma → se elimina la frase; C2 reintenta
  una vez y luego marca.
- `tesauro`: cada palabra clave se normaliza al concepto más cercano si la similitud supera τ_tesauro; si no,
  queda como término libre. Política: sanitizar.
"""
from __future__ import annotations

import numpy as np

from fototeca.contexto.tesauro import Tesauro
from fototeca.datos.puertos import Embebedor
from fototeca.dominio.configuracion import Configuracion
from fototeca.dominio.esquemas_ficha import Ficha, PalabraClave
from fototeca.guardrails.politicas import politica
from fototeca.guardrails.resultado import ResultadoGuardrail
from fototeca.guardrails.salida.reglas import detectar_sensibles, eliminar_frases
from fototeca.modelos.gateway import Gateway


class GuardrailsSemanticos:
    def __init__(self, config: Configuracion, embebedor: Embebedor, embebedor_secundario: Embebedor,
                 tesauro: Tesauro, gateway: Gateway | None):
        self.config = config
        self.embebedor = embebedor
        self.secundario = embebedor_secundario
        self.tesauro = tesauro
        self.gateway = gateway

    def _umbral(self, nombre: str) -> float | None:
        valor = self.config.parametro(f"guardrails.{nombre}")
        return None if valor is None else float(valor)

    def apego_visual(self, vector_imagen: np.ndarray, texto_alternativo: str) -> ResultadoGuardrail:
        v = self.embebedor.embeber_textos([texto_alternativo], rol="consulta")[0]
        sim = float(np.dot(vector_imagen, v))
        umbral = self._umbral("tau_apego_visual")
        if umbral is None:
            return ResultadoGuardrail("apego_visual", "aprobada", valor=round(sim, 4),
                                      detalle={"nota": "umbral sin calibrar"})
        if sim < umbral:
            return ResultadoGuardrail("apego_visual", "marcada", valor=round(sim, 4), umbral=umbral,
                                      politica_aplicada=politica("apego_visual"))
        return ResultadoGuardrail("apego_visual", "aprobada", valor=round(sim, 4), umbral=umbral)

    def consistencia(self, texto_alternativo: str, descripcion_p1: str | None) -> ResultadoGuardrail | None:
        if not descripcion_p1:
            return None
        a, b = self.secundario.embeber_textos([texto_alternativo, descripcion_p1])
        sim = float(np.dot(a, b))
        umbral = self._umbral("tau_consistencia")
        if umbral is not None and sim < umbral:
            return ResultadoGuardrail("consistencia", "marcada", valor=round(sim, 4), umbral=umbral,
                                      politica_aplicada=politica("consistencia"))
        return ResultadoGuardrail("consistencia", "aprobada", valor=round(sim, 4), umbral=umbral)

    def atributos_sensibles(self, ficha: Ficha) -> tuple[Ficha, ResultadoGuardrail]:
        hallazgos = detectar_sensibles(ficha)
        if not hallazgos:
            return ficha, ResultadoGuardrail("atributos_sensibles", "aprobada", detalle={"etapa": "lexico"})
        confirmados: dict[str, list[str]] = {}
        for campo, fragmentos in hallazgos.items():
            if self.gateway is None:
                confirmados[campo] = fragmentos
                continue
            salida = self.gateway.ejecutar("P6", {"campo": getattr(ficha, campo)})
            if salida.datos.get("sensible"):
                confirmados[campo] = [f for f in salida.datos.get("fragmentos", []) if f] or fragmentos
        if not confirmados:
            return ficha, ResultadoGuardrail("atributos_sensibles", "aprobada",
                                             detalle={"etapa": "P6", "descartados_por_P6": sum(map(len, hallazgos.values()))})
        limpia = eliminar_frases(ficha, confirmados)
        return limpia, ResultadoGuardrail("atributos_sensibles", "sanitizado", valor=float(sum(map(len, confirmados.values()))),
                                          politica_aplicada=politica("atributos_sensibles"),
                                          detalle={"campos": sorted(confirmados)})

    def normalizar_palabras(self, palabras: list[str]) -> tuple[list[PalabraClave], ResultadoGuardrail]:
        tau = float(self.config.parametro("guardrails.tau_tesauro", 0.75))
        normalizadas, vistas = [], set()
        for _, pc in self.tesauro.normalizar(palabras, tau):
            clave = pc.uri or pc.termino.lower()
            if clave not in vistas:
                vistas.add(clave)
                normalizadas.append(pc)
        en_tesauro = sum(1 for p in normalizadas if p.origen == "tesauro")
        return normalizadas, ResultadoGuardrail("tesauro", "sanitizado" if en_tesauro else "aprobada",
                                                valor=float(en_tesauro), umbral=tau,
                                                politica_aplicada=politica("tesauro") if en_tesauro else None,
                                                detalle={"tesauro": en_tesauro, "libres": len(normalizadas) - en_tesauro})
