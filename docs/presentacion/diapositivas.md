# Esqueleto de las diapositivas · Fototeca Viva

**Duración:** 15 minutos de exposición y 5 de preguntas. Reparto: idea (2 min), arquitectura (3 min), modelos y
decisiones de RAG (3 min), demo en vivo (5 min) y resultados y limitaciones (2 min).

**Reglas de diseño:** una idea por diapositiva; diagramas y gráficas en lugar de párrafos (como máximo tres viñetas
cortas); letra grande; los diagramas se toman de `docs/diagramas/*.png` y las gráficas de `evaluacion/graficas/`. Toda
cifra que aparezca sale de `evaluacion/resultados/` y lleva su fuente en letra pequeña al pie.

---

## 1 · Portada · 0:00–0:15

- **Contenido:** «Fototeca Viva: catalogación accesible y trazable de archivos fotográficos». Autor, materia, docente.
- **Visual:** una ficha real de la web con sus chips de fuentes. [AUTOR: captura de pantalla de `catalogar.html`.]
- **Notas del orador:** «Les voy a mostrar un sistema que cataloga fotos como lo haría un catalogador con formación en
  accesibilidad, en una laptop, sin internet».

## 2 · El problema · 0:15–1:00

- **Contenido:** miles de fotos sin metadatos · sin texto alternativo no son accesibles · duplicados que nadie detecta.
- **Visual:** una cuadrícula de fotos sin título junto a una persona que usa lector de pantalla. [AUTOR: imagen con
  atribución si es de XM3600.]
- **Notas del orador:** quién es el usuario (el archivista de comunicación social o de una fototeca) y en qué momento de
  su trabajo lo usa (al recibir un lote de fotos de un evento). Beneficiarias: personas ciegas o con baja visión.

## 3 · Qué entrega (no es un chatbot) · 1:00–2:00

- **Contenido:** ficha IPTC con la fuente de cada campo · reporte de duplicados · búsqueda por texto o por foto con
  razones · panel de accesibilidad del archivo.
- **Visual:** la ficha con sus chips de fuentes, señalando un chip de regla, uno de tesauro y uno de foto similar.
- **Notas del orador:** lo original: (a) el archivo aprende de las correcciones sin fine-tuning, (b) trazabilidad por
  campo, (c) accesibilidad como objetivo, (d) arquitectura híbrida adaptativa con modelos de 1.7B parámetros o menos.
  Prueba rápida: si se quita la web, queda una API de catalogación útil.

## 4 · Contenedores · 2:00–3:00

- **Contenido:** cuatro contenedores, todo local, solo CPU.
- **Visual:** Figura 2 (`docs/diagramas/02-contenedores.png`).
- **Notas del orador:** la web solo habla con `/api/*` (R8); el servicio habla con Ollama y Qdrant por HTTP/JSON; SQLite
  guarda documentos, fichas, caché, eventos, retroalimentación y lotes. Límites de memoria: 7.0625 GiB en total
  (ADR-12).

## 5 · Capas del servicio · 3:00–4:00

- **Contenido:** C1–C7 con dependencias solo hacia abajo · T1 y T2 con sus propios puertos · tres contratos verificados
  en `pytest`.
- **Visual:** Figura 3 (`docs/diagramas/03-capas.png`).
- **Notas del orador:** explicar la inversión de dependencias de T1 y T2 (ADR-13) y que un import indebido rompe las
  pruebas (`servicio/pruebas/test_contratos.py`). Cambiar Qdrant por otra base vectorial es escribir un adaptador
  (ADR-09).

## 6 · Flujo de una ficha · 4:00–5:00

- **Contenido:** guardrails → caché → RAG → enrutador → modelos → guardrails → caché y traza → retroalimentación.
- **Visual:** Figura 7 (`docs/diagramas/07-secuencia-ficha-normal.png`), con zoom en la parte central, o una versión
  simplificada de los diez pasos. [AUTOR: decidir si se simplifica para la diapositiva.]
- **Notas del orador:** el paso 6 (recuperar ejemplos) va antes que el 5 (enrutar), porque el enrutador decide con los
  vecinos. Cada respuesta trae `meta` con la ruta, los modelos, la caché, los guardrails, las iteraciones del agente, el
  tiempo por capa y el `traza_id`.

## 7 · Modelos: quién hace qué · 5:00–6:00

- **Contenido:** Qwen3.5-0.8B = los ojos y la pluma (describe y compone las fichas) · LFM3-1.7B = el intérprete de
  búsquedas y el respaldo · EmbeddingGemma-2 = la memoria multimodal · granite = el auditor.
- **Visual:** la tabla comparativa de modelos de lenguaje del informe (Tabla 8), de
  `evaluacion/resultados/r3_modelos.json`, y la gráfica `evaluacion/graficas/r3_modelos_latencia.png`.
- **Notas del orador:** criterios: calidad (juez y métricas sin juez), guardrails, latencia, memoria, licencia e
  idioma, con una regla de decisión escrita antes de medir. La hipótesis era que LFM3, más grande, compondría mejor.
  Con la misma entrada, ni el juez (5.0 contra 4.95) ni las fichas que pasan sin revisión (22 contra 20 de 30) los
  separan con significancia, así que decide el costo: Qwen compone con p50 de 50.528 s contra 56.231 s
  (`r3_modelos.json`). Lección: en la primera corrida LFM3 «ganaba» porque copiaba el contexto y el juez no lo veía; al
  agregar la verificación `copia_contexto` la ventaja desapareció (ADR-01). La ruta rápida tarda menos (p50 31.291 s).
  Por qué no modelos más grandes: los cuatro ya ocupan el límite de memoria de `ollama` (pico de 4.592 GiB de 5.0,
  `evaluacion/resultados/h0.json` → `verificaciones.0.5.docker_stats`). Qué se sacrificó y por qué es adecuado
  (ADR-01).

## 8 · Unificado contra pipeline contra híbrido · 6:00–7:00

- **Contenido:** una pregunta de arquitectura: ¿embedding multimodal o «describir y buscar como texto»?
- **Visual:** la gráfica de R@k por arquitectura, `evaluacion/graficas/r3_embeddings_texto_imagen.png`.
- **Notas del orador:** sobre la misma galería de 250 imágenes, la foto correcta queda en primer lugar en 0.9 de las
  consultas con el unificado, 0.704 con el pipeline de Qwen y EmbeddingGemma-2, 0.48 con el de Qwen y granite, y 0.82
  con el híbrido (`evaluacion/resultados/r3_embeddings.json` → `metricas.texto_imagen`). La decisión: unificado por
  defecto y pipeline como reformulación del agente (ADR-02 y ADR-07). Mencionar el costo: describir las 250 imágenes
  con Qwen tomó 1.65 h (`metricas.costo_pipeline`); embeber una imagen tuvo una p50 de 2.464 s en la viabilidad
  (`h0.json` → `verificaciones.0.6`). Relación con la tesis.

## 9 · Enrutador y decisiones de RAG · 7:00–8:00

- **Contenido:** ruta rápida o completa según consenso, acuerdo y texto visible · RRF de dos listas · una regla por
  fragmento · caché semántica con τ_dup.
- **Visual:** una tabla pequeña con los parámetros y su justificación (k = 5 vecinos, k = 4 reglas, RRF k = 60, τ_dup y
  su barrido) y la curva de τ_dup, `evaluacion/graficas/cache_tau_dup.png`. Con τ_dup = 0.95: recall 0.94 en 150 casi
  duplicados y 1 de 75 fotos distintas con la ficha de otra (FPR 0.0133, meta ≤ 0.02); el recorte es la transformación
  más difícil (recall 0.7917) (`evaluacion/resultados/cache.json` → `metricas.fichas_semantica_tau_dup`).
- **Notas del orador:** ADR-03, ADR-04 y ADR-06; los umbrales se calibran con datos, no a ojo.

## 10 · Demo en vivo · 8:00–13:00

- **Contenido:** los nueve pasos, en una línea cada uno: sin red · ficha con fuentes · duplicado desde la caché ·
  bloqueo · ciclo de agente · validar · buscar · métricas · OpenAPI.
- **Visual:** cambiar al navegador y seguir `docs/presentacion/guion_demo.md`.
- **Notas del orador:** lanzar el lote del paso 5 al empezar la diapositiva 4. Plan B: el video.

## 11 · Resultados · 13:00–14:00

- **Contenido:** una tabla de 4 a 6 cifras clave: R@10 de la búsqueda, calidad con RAG contra sin RAG, bloqueos correctos
  y falsos positivos, respuestas incorrectas desde la caché, mejora del ciclo de agente y latencia p50 por ruta.
- **Visual:** la tabla y la gráfica de latencia por capa en barras apiladas: pendiente (H7), de
  `evaluacion/resultados/RESUMEN.md` y `evaluacion/graficas/`.
- **Notas del orador:** comentar un error típico del análisis de errores del informe. [AUTOR: elegir las cifras.]

## 12 · Limitaciones y trabajo futuro · 14:00–15:00

- **Contenido:** modelos pequeños (alucinaciones) · sesgos por región · solo CPU · el texto en las fotos como vector de
  inyección.
- **Visual:** la curva de aprendizaje (aceptación contra correcciones acumuladas): pendiente (H7), de
  `evaluacion/resultados/aprendizaje.json`.
- **Notas del orador:** cada ficha la valida una persona antes de publicarse; trabajo futuro y relación con la tesis.
  [AUTOR: cierre personal en una frase.]

## 13 · Preguntas · 15:00–20:00

- **Contenido:** «Gracias» y el enlace al repositorio.
- **Diapositivas de respaldo** (solo si hay preguntas):
  - Figura 5, despliegue local, con los límites de memoria (ADR-12);
  - Figura 8, ficha desde la caché, y Figura 9, entrada bloqueada;
  - Figura 10, ciclo de agente;
  - la tabla de los 13 ADR (Tabla 12 del informe);
  - la tabla de guardrails y sus políticas (ADR-05).
- **Preguntas probables para ensayar:** ¿por qué no un modelo más grande? (memoria y CPU, ADR-01 y ADR-12) · ¿cómo
  evitan que el texto de la foto dé órdenes al modelo? (ADR-05) · ¿qué pasa si la caché sirve la ficha de otra foto?
  (ADR-04) · ¿cómo saben que las capas se respetan? (ADR-13) · ¿por qué SQLite y no Redis? (ADR-09).
