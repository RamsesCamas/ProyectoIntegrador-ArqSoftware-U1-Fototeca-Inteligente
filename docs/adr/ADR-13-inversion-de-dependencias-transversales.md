# ADR-13: Inversión de dependencias para T1 y T2: puertos propios y raíz de composición

**Estado:** Aceptada
**Fecha:** 2026-11-08
**Atributos de calidad en juego:** mantenibilidad (dependencias solo hacia abajo y sin ciclos), capacidad de prueba,
cumplimiento verificable de la arquitectura en capas (R6)

## Contexto
La regla de la arquitectura es que cada capa use solo capas inferiores y que las transversales (T1, observabilidad, y
T2, retroalimentación) puedan ser usadas por todas. Pero T1 y T2 necesitan persistir datos (eventos y opiniones) en
SQLite, cuyos adaptadores viven en C7, y C7 también necesita registrar eventos. Si T1 importara el adaptador de C7 y C7
importara T1, habría un ciclo, y las transversales dejarían de ser independientes de las capas de negocio.

## Decisión
- **T1 define su puerto** `SumideroEventos` (`servicio/fototeca/observabilidad/puertos.py`) y **T2 define el suyo**,
  `AlmacenRetroalimentacion` (`servicio/fototeca/retroalimentacion/puertos.py`).
- **C7 los implementa:** `datos/eventos_sqlite.py` (`EventosSqlite`) y `datos/retroalimentacion_sqlite.py`
  (`RetroalimentacionSqlite`).
- **La raíz de composición** (`servicio/fototeca/api/arranque.py`) crea los adaptadores y los conecta: llama a
  `configurar_sumidero(...)` con el `EventosSqlite` para T1 y entrega el `RetroalimentacionSqlite` como
  `AlmacenRetroalimentacion` (campo `almacen_retroalimentacion` del `Contenedor`) para T2.
- Las capas de negocio usan T1 (`registrar()`, `medir()`, `traza_actual()`) y T2; T1 y T2 no importan ninguna capa de
  negocio, y `dominio` no importa nada interno.
- Todo se hace cumplir con **tres contratos de import-linter** en `servicio/pyproject.toml`:
  1. «Capas del servicio (C1→C7)», de tipo `layers`: `api`, `orquestacion`, `guardrails`, `cache`, `contexto`,
     `modelos`, `datos` y `dominio`, en ese orden;
  2. «Transversales independientes», de tipo `forbidden`: `observabilidad` y `retroalimentacion` no pueden importar
     C1–C7;
  3. «Dominio sin dependencias internas», de tipo `forbidden`: `dominio` no puede importar T1 ni T2.

## Alternativas
- **Que T1 y T2 escriban directamente en SQLite:** las transversales tendrían detalles de persistencia y duplicarían lo
  que hace C7; cambiar de almacén obligaría a tocarlas.
- **Solo bitácora a la salida estándar:** no habría datos consultables para `GET /metricas` ni para ligar la
  retroalimentación con su traza.
- **Una capa «infraestructura» aparte, fuera del contrato:** escondería las dependencias en lugar de ordenarlas.
- **Variables globales en C7 que T1 consulte:** recrearía el ciclo de importaciones.

## Evidencia
- **Pruebas automáticas** en `servicio/pruebas/test_contratos.py`, que corren dentro de `pytest`:
  - `test_contrato_de_capas_se_cumple`: ejecuta `lint-imports` sobre el código real y exige que se cumplan los tres
    contratos y que ninguno se rompa;
  - `test_contrato_detecta_import_indebido`: en una copia del paquete agrega un import de C7 hacia C1 y exige que el
    contrato falle (prueba negativa);
  - `test_transversal_no_puede_importar_negocio`: en una copia agrega un import de T1 hacia C7 y exige que falle el
    contrato «Transversales independientes» (prueba negativa).
- **pendiente:** la salida registrada de `lint-imports` y de esas pruebas (contratos cumplidos y rotos, y resultado de
  las pruebas negativas) en `evaluacion/resultados/contrato_capas.json`.

## Consecuencias
- **Se gana:** las dependencias van siempre hacia abajo y sin ciclos; T1 y T2 se prueban con sumideros falsos; la
  arquitectura no depende de la disciplina de quien programa, porque una importación indebida rompe `pytest`.
- **Se sacrifica:** una indirección más (puerto + adaptador + conexión en `arranque.py`) para algo tan simple como
  guardar un evento.
- **Riesgos:** import-linter solo ve importaciones de Python; una dependencia escondida (por ejemplo, un objeto de capa
  superior pasado como argumento sin tipo) no la detecta. La revisión del diagrama de componentes complementa al
  contrato.
