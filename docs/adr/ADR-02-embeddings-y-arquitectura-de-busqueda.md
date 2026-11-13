# ADR-02: Selección de embeddings (EmbeddingGemma-2 y granite) y arquitectura unificada, pipeline o híbrida

**Estado:** Aceptada
**Fecha:** 2026-11-08
**Atributos de calidad en juego:** calidad de la búsqueda texto→imagen en español (R@k), latencia de indexado y de
consulta, costo de cómputo en CPU, memoria, independencia del verificador de salida

## Contexto
Casi todo en Fototeca Viva depende de embeddings: la búsqueda por texto en español y por foto, la detección de casi
duplicados, la caché semántica, los enrutadores, los prototipos de los guardrails y el RAG de ejemplos y de normas. Hay
dos maneras de llevar una foto a un espacio donde se pueda comparar con texto:
- **unificada:** un modelo multimodal embebe la imagen y el texto en el mismo espacio;
- **pipeline:** un modelo de visión describe la imagen y se embebe esa descripción como texto.

El curso pide comparar al menos dos modelos de embeddings con evidencia medida, y la comparación unificada contra
pipeline es además el tema de la tesis del autor.

## Decisión
- **`embeddinggemma-2:440m` es el embedding principal** (el tag se eligió en ADR-10): imagen y texto en el mismo
  espacio para `fotos_img`, `fotos_txt`, `normas`, `tesauro` y `prototipos`, la caché semántica, los enrutadores y las
  verificaciones `fuera_de_dominio`, `texto_visible` y `apego_visual`. Los textos llevan el prefijo de tarea según su
  rol (consulta, documento o simétrico; `servicio/config/parametros.yaml`); las imágenes se envían a 384 px.
- **`granite-embedding:278m` es el segundo modelo:** compite en el experimento R3 (colección `fotos_txt_granite`) y,
  por ser independiente del principal, sirve de verificador en el guardrail `consistencia` (texto alternativo contra
  la descripción de P1).
- **Arquitectura híbrida adaptativa:** la ruta unificada va por defecto (imagen→imagen e imagen→texto fusionadas con
  RRF); la ruta pipeline (Qwen describe y se busca como texto) entra solo como reformulación del ciclo de agente cuando
  la recuperación es pobre (ADR-07). La búsqueda por texto consulta `fotos_img` (texto→imagen) y `fotos_txt`
  (texto→ficha validada) y las fusiona con RRF.

## Alternativas
- **Solo granite (texto):** no embebe imágenes; la búsqueda y los duplicados tendrían que pasar siempre por una
  descripción de Qwen. En H0, describir una foto con P1 tuvo una p50 de 34.28 s, contra 2.464 s del embedding de
  imagen (evidencia abajo).
- **Pipeline puro para toda la galería:** se mide en el experimento como alternativa, con su costo de cómputo; como
  ruta por defecto obligaría a describir cada foto con un modelo de lenguaje al ingerirla.
- **Embeddings fuera de Ollama** (CLIP o SigLIP con otra biblioteca): descartados por una restricción del proyecto:
  todos los modelos se sirven desde Ollama.
- **Un tercer modelo de embeddings de texto** (por ejemplo, de los sugeridos por el curso): costaría memoria en un
  contenedor que ya llegó a 4.592 GiB de 5.0 (ADR-12) sin cubrir la parte de imagen.

## Evidencia
Fuente: `evaluacion/resultados/r3_embeddings.json` (corrida del 2026-11-13 con `--fraccion 0.5`: la mitad de cada
conjunto; detalle por consulta en `r3_embeddings_detalle.csv` y gráfica en
`evaluacion/graficas/r3_embeddings_texto_imagen.png`). La consulta es la primera descripción en español de cada imagen
y la respuesta correcta es esa imagen.

**1. Texto→imagen, las cuatro arquitecturas sobre la misma sub-galería de 250 imágenes** (`metricas.texto_imagen`):

| Arquitectura | R@1 | R@5 | R@10 | MRR |
|---|---|---|---|---|
| **Unificado** (EmbeddingGemma-2 texto→imagen) | **0.9** | **0.992** | **1.0** | **0.9418** |
| Pipeline (Qwen describe + EmbeddingGemma-2 texto→texto) | 0.704 | 0.924 | 0.96 | 0.8013 |
| Pipeline (Qwen describe + granite texto→texto) | 0.48 | 0.716 | 0.832 | 0.5846 |
| Híbrido (RRF de unificado y pipeline con EmbeddingGemma-2) | 0.82 | 0.984 | 1.0 | 0.89 |

- **Por grupo** (`metricas.por_grupo`): en las 79 fotos de `regiones_excluidas` el unificado tiene R@1 de 0.8987 contra
  0.7595 del pipeline con EmbeddingGemma-2; en las 171 del resto de locales, 0.9006 contra 0.6784. Con consultas
  cortas (≤8 palabras, n = 102) el unificado tiene R@1 de 0.902 y el pipeline 0.6275; con consultas largas (n = 83),
  0.8916 y 0.7349. El pipeline acorta la distancia con consultas largas, pero no alcanza al unificado en ningún grupo.
- **Por locale** (`metricas.por_locale_R@10`): el unificado tiene R@10 de 1.0 en los 36 locales de la sub-galería.
- **Galería completa de 500 imágenes, solo unificado** (`metricas.texto_imagen_galeria_completa`): R@1 0.824, R@5
  0.982, R@10 0.992 y MRR 0.8926. No se compara con la tabla anterior: el R@k baja cuando crece la galería.
- **Costo del pipeline** (`metricas.costo_pipeline`): describir las 250 imágenes con Qwen tomó 1.65 h en total; el
  piloto de 20 descripciones dio 32.52 s por descripción, que para 1,000 imágenes serían 9.03 h. El unificado solo
  necesita el embedding de la imagen (p50 de 2.464 s en H0, tabla de abajo).

**2. Descripción→descripción** (segunda contra primera descripción humana; `metricas.descripcion_descripcion`):
EmbeddingGemma-2 tiene R@1 de 0.756 y MRR de 0.8384; granite, R@1 de 0.46 y MRR de 0.5873.

**3. Asignación de términos del tesauro** (100 etiquetas de Open Images con concepto esperado por coincidencia léxica;
`metricas.tesauro`): EmbeddingGemma-2 acierta 0.56 en top-1 y 0.69 en top-3; granite, 0.58 y 0.71. La diferencia es
de 2 etiquetas de 100. La plantilla de revisión manual de 50 pares está en
`evaluacion/revision_manual/plantilla_tesauro.csv`.

**4. Recuperación de normas** (20 consultas con su regla esperada; `metricas.normas`):

| Modelo | acierto@1 | acierto@4 (k de producción) | acierto@10 |
|---|---|---|---|
| EmbeddingGemma-2 | 0.25 | 0.65 | 0.8 |
| granite | 0.35 | 0.65 | 0.75 |

**Lectura.** El unificado tiene el mejor R@1, R@5 y MRR (en R@10 empata con el híbrido), supera al pipeline en R@1 en
todos los grupos y además es la arquitectura más barata. El híbrido queda por debajo del unificado (R@1 0.82 contra
0.9): fusionar siempre con el pipeline empeora el primer resultado. Por eso el pipeline no entra en la ruta por
defecto y se reserva para la reformulación del ciclo de agente, solo cuando la recuperación es pobre; ADR-07 mide si
en esos casos ayuda. Entre los dos modelos de texto, EmbeddingGemma-2 gana con claridad en texto→texto (R@1 0.756
contra 0.46), y en tesauro y normas quedan parejos.

**Datos de viabilidad ya medidos** (galería de 50 pares, no sustituye a la de R3). Fuente: `evaluacion/resultados/h0.json`
y `evaluacion/resultados/h0_memoria_por_modelo.txt`.

| Medición | EmbeddingGemma-2 (`440m`) | granite (`278m`) | Fuente |
|---|---|---|---|
| Acepta imágenes | sí | no (solo texto) | `verificaciones.0.3` y `verificaciones.0.4` |
| Dimensión | 768 | 768 | `verificaciones.0.3.candidatos` y `verificaciones.0.4.dimension` |
| 50 pares imagen–texto: el par correcto gana · R@1 · R@5 (imagen a 384 px) | 1.0 · 0.96 · 1.0 | — | `verificaciones.0.3b.por_lado.384` |
| Paráfrasis en español contra texto no relacionado (coseno) | — | 0.8173 contra 0.4067 | `verificaciones.0.4` |
| Longitud máxima de entrada medida | — | 512 tokens | `verificaciones.0.4.longitud_maxima_medida_tokens` |
| Embedding de imagen, p50 y p95 (n = 20) | 2.464 s · 2.775 s | — | `verificaciones.0.6.embedding_imagen` |
| Embedding de texto, p50 y p95 (n = 20) | 0.159 s · 0.297 s | 0.051 s · 0.129 s | `verificaciones.0.6.embedding_texto` y `embedding_texto_granite` |
| Tamaño en disco (bytes) | 671046782 | 562777301 | `modelos_descargados` |
| Memoria residente del proceso `llama-server` (VmRSS) | 924168 kB | 699712 kB | `h0_memoria_por_modelo.txt` |

## Consecuencias
- **Se gana:** búsqueda texto→imagen, duplicados y caché semántica con un solo modelo pequeño, sin llamar a un modelo
  de lenguaje; un verificador de salida que no comparte sesgos con el modelo principal.
- **Se sacrifica:** la calidad de la búsqueda depende de un modelo multimodal compacto; granite ocupa memoria solo para
  el experimento y para `consistencia`.
- **Por qué el compromiso es adecuado para el dominio y el equipo:** en CPU, embeber una imagen cuesta segundos y
  describirla con un modelo de lenguaje cuesta decenas de segundos (H0). Usar la ruta unificada por defecto y pagar el
  pipeline solo cuando la recuperación es pobre deja la búsqueda y la ingesta en tiempos razonables en la laptop.
- **Riesgos:** las cifras son de la corrida al 50 % de cada conjunto; la corrida completa puede moverlas. En tesauro
  y normas granite queda parejo o un poco arriba en acierto@1 (0.35 contra 0.25 en normas, sobre 20 consultas): si la
  corrida completa confirma esa ventaja, mover las colecciones `normas` y `tesauro` a granite se decide en un ADR
  nuevo. Las consultas de normas sobre texto alternativo son las que peor se recuperan (ADR-06).
