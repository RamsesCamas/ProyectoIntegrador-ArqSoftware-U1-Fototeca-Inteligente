"""Fototeca Viva: catalogación accesible y trazable de archivos fotográficos.

Arquitectura en capas (docs/specs/02-arquitectura.md). Cada capa importa solo de las capas inferiores;
el contrato se verifica con import-linter dentro de pytest (pruebas/test_contratos.py):

    C1 api → C2 orquestacion → C3 guardrails → C4 cache → C5 contexto → C6 modelos → C7 datos → dominio
    Transversales: T1 observabilidad y T2 retroalimentacion (no importan capas de negocio).
"""

__version__ = "0.1.0"
