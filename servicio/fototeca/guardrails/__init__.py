"""C3 · Guardrails de entrada y salida.

Cada verificación devuelve un `ResultadoGuardrail` (aprobada, sanitizado, marcada o bloqueada) y aplica la
política definida en `politicas.py`: bloquear, sanitizar, marcar o reintentar (ADR-05).
"""
