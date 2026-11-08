# Uso de inteligencia artificial en el desarrollo de Fototeca Viva

Este documento declara cómo se usó la inteligencia artificial (IA) para desarrollar Fototeca Viva, como piden los
lineamientos éticos y académicos del proyecto integrador. Sintetiza el material de trabajo del proceso, que no forma
parte del repositorio y que conserva el autor: las especificaciones que escribió para guiar al asistente, las
instrucciones de trabajo, el seguimiento por hito y la bitácora de decisiones. La versión breve está al final del
informe técnico (`docs/informe/informe.md`).

**Autor:** Ramsés Alejandro Camas Nájera. **Versión:** noviembre de 2026, antes de la evaluación completa (sección 5).

## 1. Herramientas

En el proyecto hay dos usos de IA que no deben confundirse:

| | Asistente de desarrollo | Modelos del producto |
|---|---|---|
| **Qué es** | **Claude Code**, el agente de programación de Anthropic, con el modelo **Claude Opus 5.5** | Qwen3.5-0.8B (visión), LFM3-1.7B (catalogador), EmbeddingGemma-2 (embeddings de texto e imagen) y granite-embedding-278m (segundo embedding y verificador) |
| **Papel** | Escribir código, pruebas, scripts, evaluación, diagramas y borradores; ejecutar comandos y mediciones | Generar fichas, embeddings y búsquedas: son componentes del sistema y son lo que se evalúa |
| **Dónde corre** | Servicio de Anthropic, usado desde una sesión en el equipo del autor | Contenedor `ollama`, en CPU y sin red |
| **¿Está en el entregable?** | No | Sí, con tags fijos |

**El producto no usa ninguna API de IA en la nube.** Los modelos se sirven con Ollama dentro de `docker compose`, con
las funciones en la nube de Ollama desactivadas (`OLLAMA_NO_CLOUD=1` en `docker-compose.yml`), e internet solo se usa
para la preparación (imágenes de Docker, modelos, datos y corpus). El asistente de desarrollo, en cambio, sí es un
servicio en la nube: Anthropic procesó lo que leyó durante las sesiones (código, documentos y salidas de comandos), es
decir, el propio proyecto y datos públicos, sin datos personales (sección 6).

**Diseño.** El diseño de la idea, la selección de los modelos y las decisiones de arquitectura los dirigió el autor,
con apoyo de Claude (Anthropic) como asistente de diseño. [AUTOR: precisar la herramienta y el modelo usados en esta
etapa.]

**Forma de trabajo.** El autor abrió una sesión de Claude Code en su equipo, una Mac con Docker Desktop (la máquina
virtual de Docker tiene una CPU Apple `aarch64` de 8 núcleos: `evaluacion/resultados/h0.json` → `hardware_contenedor`).
Le dio un encargo inicial y lo siguió por control remoto desde el celular, por donde también le dio instrucciones. El
asistente ejecutaba `docker`, `git` y `python` en ese equipo y avanzaba por hitos: H0 viabilidad, H1 esqueleto, H2 datos
y corpus, H3 ingesta e indexado, H4 ficha de principio a fin, H5 guardrails y caché, H6 observabilidad,
retroalimentación y web, H7 evaluación, H8 documentación y H9 verificación final. En cada hito seguía el mismo
protocolo: releer las especificaciones del hito, implementar solo lo que pide, verificar cada criterio de aceptación con
un comando o una prueba real y con `pytest`, registrar la evidencia, hacer el commit e informar el estado en pocas
líneas. Todos los commits llevan la línea `Co-Authored-By: Claude Opus 5.5`.

**Subagentes.** Por instrucción del autor, el trabajo independiente se repartió entre subagentes de Claude Code que
trabajaban en paralelo (evaluación de fichas, evaluación del sistema, web, documentación, limpieza de referencias y la
redacción de este documento), cada uno con sus propios archivos. La integración, las verificaciones, los commits y los
`push` los hizo la sesión principal.

## 2. Qué hizo el autor y qué hizo el asistente

**El autor:**

- **Definió el problema y el producto:** para quién es (quien administra el archivo fotográfico de una institución),
  qué entrega (fichas IPTC con la fuente de cada campo, un reporte de casi duplicados y resultados de búsqueda) y por
  qué no es un chatbot.
- **Escribió las especificaciones que guiaron al asistente:** requisitos y atributos de calidad medibles; arquitectura
  objetivo (contenedores con sus límites de memoria, capas C1–C7 y T1–T2 con sus interfaces); contratos de la API;
  fuentes de datos y licencias; los cuatro modelos y su papel; las primeras versiones de los prompts y de sus esquemas
  JSON; el diseño de la evaluación; la lista de ADR; la web; la estructura del informe; y el plan por hitos con
  criterios de aceptación, planes B y reglas de alto.
- **Fijó las reglas no negociables:** todo local, en CPU y con `docker compose`; modelos fijos, sin sustituciones
  silenciosas; capas verificadas con import-linter; ninguna cifra fuera de `evaluacion/resultados/`; solo fuentes con
  licencia; presupuesto de memoria; versiones fijadas; y privacidad.
- **Se reservó las decisiones de fondo**, como reemplazar un modelo o excluir una fuente. Hasta esta versión no hizo
  falta tomar ninguna: el único cambio de modelo (`embeddinggemma-2:270m` → `embeddinggemma-2:440m`) era el plan B
  previsto en las especificaciones (ADR-10).
- **Decidió durante el desarrollo:**

| Decisión del autor | Cómo se aplicó |
|---|---|
| Gestionar las dependencias de Python con `uv` | `==` en `servicio/pyproject.toml`, lock multiplataforma con hashes (`servicio/uv.lock`) y `requirements.txt` exportado del lock, con una prueba que verifica que coincidan |
| Commits por checkpoint | Desde H2, al menos dos commits por hito («HX (1/2)» y «HX (2/2)») |
| Repositorio remoto en GitHub | `push` después de cada checkpoint, con una revisión previa del historial para descartar secretos |
| Trabajo en paralelo con agentes | Subagentes con archivos propios (sección 1) |
| Entregar el repositorio como producto | El material de trabajo del asistente (instrucciones, especificaciones, documentos del curso y bitácoras) no se publica: lo conserva el autor, las decisiones registradas pasan a los ADR y el uso de IA se resume aquí |
| Evaluación completa en otra máquina | Se ejecutará en una máquina más potente (sección 5) |

**El asistente (Claude Code):**

- **Escribió** la configuración de `docker compose`; el servicio en capas (`servicio/fototeca/`); los archivos de
  prompts, a partir de las versiones de las especificaciones y con ajustes medidos y registrados (como la versión 2 de
  P1 en H0); la web (`web/`); los scripts (`servicio/scripts/`); las pruebas (`servicio/pruebas/` y
  `servicio/pruebas_e2e/`); los módulos de evaluación (`servicio/evaluacion/`); los diagramas (`docs/diagramas/`); los
  ADR (`docs/adr/`); `docs/LICENCIAS-Y-CORPUS.md`; el `README.md`; y los borradores del informe, del guion de la demo y
  de las diapositivas.
- **Ejecutó y midió en el equipo del autor** la verificación de viabilidad de H0, que cubre modelos, memoria,
  latencias, datos y licencias confirmadas en sus páginas de origen (`evaluacion/resultados/h0.json`), y la preparación
  del corpus normativo (`evaluacion/resultados/corpus_r1.json`).
- **Tomó decisiones menores** dentro del margen de las especificaciones (el tamaño de imagen para cada modelo, los
  tiempos límite, el muestreo de Qwen), registradas con fecha y motivo. Las que afectan la arquitectura quedaron como
  ADR: ADR-10, ADR-11 y ADR-12 salen de H0.

## 3. Cómo se controló la calidad y la honestidad

- **Pruebas automáticas** (`docker compose run --rm servicio pytest -q`): adaptadores falsos que implementan los puertos
  de datos y modelos (`servicio/pruebas/falsos.py`) para probar flujos, API, guardrails, caché y observabilidad sin
  Ollama ni Qdrant; solo existen en las pruebas, y el sistema siempre corre con los modelos reales. Además, el contrato
  de capas con import-linter (`servicio/pruebas/test_contratos.py`), con una prueba negativa automática en la que un
  import prohibido tiene que romper el contrato (en H1 también se hizo a mano y se revirtió); que la web solo hable con
  la API (`servicio/pruebas/test_web_r8.py`); y que las dependencias estén fijadas
  (`servicio/pruebas/test_dependencias.py`). Aparte, las pruebas de punta a punta recorren la web con Playwright contra
  el sistema levantado (`servicio/pruebas_e2e/`, con `docker-compose.e2e.yml`). Estas pruebas verifican la lógica, los
  contratos y la integración, no la calidad de lo que generan los modelos: eso lo mide la evaluación.
- **Integridad de las cifras.** Toda cifra medida en los documentos sale de `evaluacion/resultados/` con su ruta; lo
  que no se ha medido dice «pendiente» con la razón, y un ADR sin evidencia medida queda como «Propuesta». Estaba
  prohibido inventar cifras, citas, licencias o resultados, y también simular un componente para que pareciera
  funcionar. Las reglas de decisión se fijaron antes de ver los datos (una que estaba mal planteada se corrigió antes
  de usarla), y la calidad de las fichas no depende solo de un modelo juez: se suman métricas sin juez (similitud con
  granite y chrF contra las descripciones humanas) y una revisión manual del autor, con la que se mide el acuerdo entre
  el juez y una persona.
- **Regla de alto.** Si un criterio fallaba, el asistente probaba el plan B documentado; si también fallaba, debía
  detenerse, documentar el bloqueo (comando, salida, alternativas probadas y qué tiene que decidir el autor) y seguir
  solo con el trabajo independiente. Las ambigüedades menores se resolvieron con la opción más conservadora y quedaron
  registradas con fecha y motivo. Hasta esta versión, ningún bloqueo llegó al autor.

**Incidentes reales y cómo se resolvieron:**

| Incidente | Qué pasó y cómo se resolvió | Evidencia |
|---|---|---|
| EmbeddingGemma-2 sin imágenes | El tag `270m` respondió `501: model does not support media embeddings`. Se aplicó el plan B previsto: `440m`, que acepta imágenes y produce los mismos vectores de texto | `evaluacion/resultados/h0.json` → `verificaciones.0.3`; ADR-10 |
| Repetición degenerada de Qwen | Con `presence_penalty` en 0 (lo fijaba el propio adaptador al sobrescribir el muestreo), Qwen repetía elementos de las listas hasta agotar el tope de tokens y el JSON quedaba truncado: 3 de 5 respuestas válidas. Con el 1.5 que trae el modelo, sin *draft* y con un P1 más breve: 5 de 5 | `h0.json` → `verificaciones.0.2_corrida1` y `verificaciones.0.2`; ADR-11 |
| Proceso de modelo terminado por memoria | El kernel mató un proceso del modelo cuando el contenedor `ollama` llegó a su límite. Causa: Ollama lanza `llama-server` sin `--cache-ram`, que por defecto guarda hasta 8192 MiB de estados de prompt por modelo. Se desactivó (`LLAMA_ARG_CACHE_RAM=0`) sin cambiar modelos ni límites, se repitieron las mediciones y se descartaron las latencias contaminadas | `evaluacion/resultados/h0_cgroup_ollama_antes.txt` (`oom_kill 1`), `h0_cgroup_ollama.txt` (`oom_kill 0`) y `h0_llama_server_cache_ram.txt`; ADR-12 |
| Una conclusión sesgada | Una primera lectura sugería que la decodificación especulativa (modelo *draft*) aceleraba a Qwen, pero la latencia total estaba sesgada por la caché de prompts. Se decidió por la velocidad de generación (11.55 tokens/s sin *draft* contra 6.07 con él) y Qwen corre sin *draft* | `h0.json` → `verificaciones.0.6b.analisis` |
| Contención de CPU | Con varios subagentes activos, un lote de embeddings rebasó su tiempo límite y cortó la preparación de datos. Los scripts por lotes usan ahora un límite propio, con reintentos; el riesgo para la demo (embeber una foto mientras Qwen genera) se mide en H9 | Bitácora del proceso (la conserva el autor) |

## 4. Qué debe revisar el autor

- **Las marcas `[AUTOR: …]`** del informe (`docs/informe/informe.md`), de la presentación (`docs/presentacion/`) y de
  `docs/LICENCIAS-Y-CORPUS.md`: portada, motivación y contacto con usuarios, caso local, conclusiones, relación con la
  tesis, estado final de los ADR, análisis de errores, formato de las referencias, licencia de LFM3 para el uso
  académico y qué partes revisó o reescribió a mano.
- **Las revisiones manuales** con las plantillas de `evaluacion/revision_manual/`, que generan los scripts de
  preparación y de evaluación: fichas, mapeos de etiquetas al tesauro (con ellos se recalibra su umbral), consultas
  complejas y activaciones de los guardrails de salida. Además, cronometrar la catalogación manual de una muestra de
  fotos para la métrica de valor.
- **La demo:** repetir las mediciones de latencia y de memoria en la laptop de la demo (Windows) y grabar el video de
  respaldo con `docs/presentacion/guion_demo.md`.
- **Las conclusiones**, que dependen de la evaluación completa: las cifras clave y el paso de los ADR de «Propuesta» a
  «Aceptada» (o su reemplazo por un ADR nuevo) se deciden con los resultados.
- **Este documento**, para confirmar que describe fielmente su participación.

## 5. Limitaciones y estado

- **La evaluación completa está pendiente.** Sus módulos están en `servicio/evaluacion/`, pero ejecutarlos con los
  modelos requiere, según una estimación de planeación (no es una medición), del orden de 15 a 25 horas de CPU en el
  equipo de desarrollo. Por decisión del autor se ejecutará en otra máquina más potente, con
  `docker compose run --rm servicio python -m evaluacion.ejecutar_todo`. Hasta entonces, los resultados de H7 figuran
  como «pendiente» en el informe y los ADR que dependen de ellos siguen como «Propuesta».
- **Las latencias dependen de la máquina.** Cada archivo de resultados registra el hardware en que se midió: H0 se midió
  en el equipo de desarrollo, la evaluación será en otra máquina y la demo, en una laptop Windows. Las cifras solo se
  comparan diciendo de dónde sale cada una.
- **Hitos abiertos.** Al escribir esta versión seguían en curso la indexación del archivo, las calibraciones y las
  pruebas de aceptación con los modelos reales, y faltaba la verificación final (H9), con la prueba sin red.
- **Lo que produjo el asistente puede contener errores.** Las pruebas, la regla de las cifras y el registro de
  decisiones reducen el riesgo, pero no sustituyen la revisión del autor (sección 4).

## 6. Privacidad y datos

- **Solo fuentes con licencia abierta** (Crossmodal-3600, Open Images V7, IPTC Photo Metadata, el tutorial de imágenes
  del W3C, WCAG 2.2, DCMI Metadata Terms y el Tesauro de la UNESCO), con el origen y la licencia de cada una en
  `docs/LICENCIAS-Y-CORPUS.md`. Los datos no se versionan: los descargan los scripts de preparación.
- **Sin datos personales:** ninguna foto del corpus trae EXIF ni GPS (`evaluacion/resultados/h0.json` →
  `verificaciones.0.7.exif`). Para probar el guardrail de EXIF se generan 20 copias con GPS **sintético**, y las
  consultas de prueba con datos personales usan datos ficticios.
- **En el producto:** la ingesta quita del EXIF el GPS, el número de serie y el autor, y las miniaturas no llevan
  metadatos; la ficha no identifica personas por nombre ni infiere atributos sensibles (guardrail
  `atributos_sensibles`); y todas las páginas de la web avisan que las fichas y los resultados los generan modelos de IA
  y pueden contener errores.
- **En el desarrollo:** el repositorio no versiona `.env` ni `data/`, y el historial se revisó antes del primer `push`.
