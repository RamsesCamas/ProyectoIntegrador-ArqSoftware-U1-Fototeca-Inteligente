"""C3 · Guardrails de entrada y salida.

Cada verificación devuelve un `ResultadoGuardrail` (aprobada, sanitizado, marcada o bloqueada) y aplica la
política definida en `politicas.py`: bloquear, sanitizar, marcar o reintentar (docs/specs/06, C3; ADR-05).
"""
