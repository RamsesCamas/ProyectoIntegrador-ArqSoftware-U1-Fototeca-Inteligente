"""Adaptador de Ollama para el puerto `ClienteLLM` (C7): chat con imágenes, JSON Schema y `think:false`.

- El muestreo se envía siempre explícito (los modelos traen sus propios valores por defecto).
- La salida estructurada usa el parámetro `format` de `/api/chat` con el JSON Schema de cada prompt.
- Si una salida trae bloques `<think>…</think>`, se eliminan aquí y se marca `thinking_eliminado` (ADR-11).
- Errores: tiempo agotado → `TiempoAgotado`; servidor caído o error HTTP → `ServicioNoDisponible`. Los
  reintentos y el respaldo NO viven aquí: son responsabilidad del gateway (C6).
"""
from __future__ import annotations

import base64
import re

import httpx

from fototeca.datos.imagenes import preparar_imagen
from fototeca.dominio.entidades import Mensaje, OpcionesGeneracion, RespuestaLLM
from fototeca.dominio.errores import ServicioNoDisponible, TiempoAgotado

_THINK = re.compile(r"<think>.*?</think>", re.S)


class OllamaCliente:
    def __init__(self, url: str, modelos_requeridos: list[str], tiempo_conexion_s: float = 5.0,
                 lado_imagen_px: int = 768):
        self.url = url.rstrip("/")
        self.lado_imagen_px = int(lado_imagen_px)   # imágenes hacia el modelo de visión (H0, verificación 0.6)
        self.modelos_requeridos = list(dict.fromkeys(modelos_requeridos))
        self._http = httpx.Client(base_url=self.url, timeout=httpx.Timeout(tiempo_conexion_s, read=600.0))

    # ── estado para GET /health ──
    def estado(self) -> dict:
        try:
            version = self._http.get("/api/version", timeout=5.0).json().get("version")
            disponibles = {m["name"] for m in self._http.get("/api/tags", timeout=5.0).json().get("models", [])}
            cargados = {m["name"]: m.get("size") for m in self._http.get("/api/ps", timeout=5.0).json().get("models", [])}
        except Exception as e:  # noqa: BLE001
            return {"estado": "error", "error": f"Servidor de modelos no responde: {type(e).__name__}"}
        faltantes = [m for m in self.modelos_requeridos if m not in disponibles]
        return {
            "estado": "ok" if not faltantes else "error",
            "version": version,
            "modelos_requeridos": self.modelos_requeridos,
            "modelos_faltantes": faltantes,
            "modelos_cargados": sorted(cargados),
            "memoria_modelos_cargados_gib": round(sum(v or 0 for v in cargados.values()) / 2**30, 2),
        }

    def precalentar(self, modelo: str, opciones: dict | None = None) -> None:
        """Carga el modelo en memoria con keep_alive=-1 (evita la latencia de carga en la primera petición).

        `opciones` deben ser las mismas que usarán las peticiones (num_ctx y las propias del modelo): Ollama decide al
        cargar el proceso, p. ej., si sube el modelo de decodificación especulativa de Qwen (≈0.6 GB más), aunque
        luego cada petición lo desactive (ADR-12)."""
        try:
            if "embed" in modelo:
                r = self._http.post("/api/embed", json={"model": modelo, "input": ["precalentar"], "keep_alive": -1})
            else:
                r = self._http.post("/api/generate", json={"model": modelo, "keep_alive": -1, "options": opciones or {}})
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            raise ServicioNoDisponible(f"No se pudo cargar el modelo {modelo}: {type(e).__name__}") from e

    def generar(self, modelo: str, mensajes: list[Mensaje], *, imagenes: list[bytes] | None = None,
                esquema_json: dict | None = None, opciones: OpcionesGeneracion,
                tiempo_limite_s: float) -> RespuestaLLM:
        cuerpo_mensajes = [{"role": m.rol, "content": m.contenido} for m in mensajes]
        if imagenes:
            # Las imágenes se adjuntan al último mensaje del usuario (messages[].images en base64).
            ultimo = max(i for i, m in enumerate(cuerpo_mensajes) if m["role"] == "user")
            cuerpo_mensajes[ultimo]["images"] = [
                base64.b64encode(preparar_imagen(b, self.lado_imagen_px)).decode("ascii") for b in imagenes]
        cuerpo = {
            "model": modelo,
            "messages": cuerpo_mensajes,
            "stream": False,
            "think": opciones.think,
            "keep_alive": -1,
            "options": {"temperature": opciones.temperatura, "top_p": opciones.top_p,
                        "presence_penalty": opciones.presence_penalty, "num_ctx": opciones.num_ctx,
                        "num_predict": opciones.num_predict, **opciones.extra},
        }
        if esquema_json is not None:
            cuerpo["format"] = esquema_json
        try:
            r = self._http.post("/api/chat", json=cuerpo, timeout=httpx.Timeout(10.0, read=tiempo_limite_s))
        except httpx.TimeoutException as e:
            raise TiempoAgotado(f"{modelo} no respondió en {tiempo_limite_s:.0f} s") from e
        except httpx.HTTPError as e:
            raise ServicioNoDisponible(f"No se pudo contactar al servidor de modelos: {type(e).__name__}") from e
        if r.status_code >= 400:
            raise ServicioNoDisponible(f"Error del modelo {modelo} ({r.status_code}): {r.text[:200]}")
        d = r.json()
        texto = (d.get("message") or {}).get("content", "") or ""
        limpio = _THINK.sub("", texto).strip()
        return RespuestaLLM(
            texto=limpio, modelo=d.get("model", modelo),
            tokens_prompt=int(d.get("prompt_eval_count") or 0), tokens_salida=int(d.get("eval_count") or 0),
            duracion_total_ms=(d.get("total_duration") or 0) / 1e6, duracion_carga_ms=(d.get("load_duration") or 0) / 1e6,
            razon_fin=d.get("done_reason"), thinking_eliminado=limpio != texto.strip(),
        )
