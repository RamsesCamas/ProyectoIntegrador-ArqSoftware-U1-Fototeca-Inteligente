# ADR-02: Selección de embeddings (EmbeddingGemma-2 y granite) y arquitectura unificada, pipeline o híbrida

**Estado:** Propuesta
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
**pendiente:** experimento R3 de embeddings en `evaluacion/resultados/r3_embeddings.json`:
1. texto→imagen en `galeria_busqueda` (la consulta es la primera descripción en español de cada imagen): R@1, R@5,
   R@10 y MRR para **unificado** (EmbeddingGemma-2), **pipeline** (descripciones de Qwen comparadas con
   EmbeddingGemma-2 y con granite) e **híbrido** (RRF), por locale y por longitud de la consulta, con el tiempo total de
   las descripciones como costo del pipeline;
2. descripción→descripción (segunda contra primera descripción): EmbeddingGemma-2 contra granite;
3. asignación de términos del tesauro: exactitud top-1 y top-3;
4. recuperación de normas: acierto@k sobre 20 consultas con su regla esperada.

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
- **Riesgos:** la prueba de H0 tiene 50 pares; el rendimiento puede variar por región o idioma de origen de la foto
  (el análisis por locale de R3 lo mostrará). Si el pipeline o el híbrido ganan con claridad, el diseño por defecto se
  revisa en un ADR nuevo.
