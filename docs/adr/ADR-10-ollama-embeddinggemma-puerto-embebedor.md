# ADR-10: Versión de Ollama, tag de EmbeddingGemma-2 y puerto `Embebedor`

**Estado:** Aceptada
**Fecha:** 2026-11-07
**Atributos de calidad en juego:** viabilidad técnica (R2, R3), calidad de la búsqueda, memoria, latencia, mantenibilidad

## Contexto
Fototeca Viva necesita un embedding que ponga **textos e imágenes en el mismo espacio** (búsqueda texto→imagen,
duplicados, caché semántica y enrutadores) y que se sirva **solo desde Ollama**, en CPU y dentro de Docker. La
spec fija `embeddinggemma-2:270m`, pero su ficha en ollama.com solo muestra ejemplos de texto. Además, LFM3 —el
otro modelo fijo— exige una versión de Ollama reciente que lo ejecute en Linux.

## Decisión
1. Se fija `ollama/ollama:0.40.15` (la estable más reciente; LFM3 corre en Linux desde 0.40.13).
2. Se usa **`embeddinggemma-2:440m`** (plan B de `docs/specs/05` §2): el tag más pequeño de Ollama que entrega
   embeddings de imagen y pasa la prueba de 50 pares.
3. Las imágenes se envían reducidas a **384 px** de lado.
4. Las capas superiores dependen solo del puerto `Embebedor` (C7); el adaptador `EmbebedorOllama` aplica los
   prefijos de tarea de la ficha oficial según el *rol* del texto (consulta, documento o simétrico).

## Alternativas
- **`embeddinggemma-2:270m` (plan A):** descartado. `/api/show` reporta solo la capacidad `embedding` y
  `/api/embed` con una imagen responde `501: model does not support media embeddings`.
- **`embeddinggemma-2:740m`:** no hizo falta probarlo; agrega el codificador de audio (no se usa) y pesa más.
- **Plan C (pipeline: Qwen describe y se embebe el texto):** innecesario; además costaría una llamada a Qwen
  por foto (decenas de segundos en esta CPU, H0 0.2) en lugar de unos 2 s.
- **Embeddings fuera de Ollama (transformers, ONNX):** prohibido por la spec (todo desde Ollama).
- **Enviar las imágenes a 256, 512 o 768 px:** misma calidad en la prueba; 768 px cuesta casi el doble.

## Evidencia
Fuente: `evaluacion/resultados/h0.json` (verificaciones `0.3` y `0.3b`; versión de Ollama en `ollama_version`).

| Tag | Capacidades (`/api/show`) | ¿Acepta imagen? | Dimensión | Par correcto gana (50 pares) | R@1 texto→imagen | R@5 texto→imagen |
|---|---|---|---|---|---|---|
| `embeddinggemma-2:270m` | `embedding` | No (501) | 768 (texto) | — | — | — |
| `embeddinggemma-2:440m` | `embedding`, `vision` | Sí | 768 | 1.00 | 0.96 | 1.00 |

- Los embeddings de **texto** de `440m` son idénticos a los de `270m`: coseno medio **1.0** sobre 8 textos
  (`coseno_texto_vs_270m`). Usar `440m` no cambia nada para el texto.
- **Prefijos de tarea** (50 pares, `440m`): sin prefijo, con prefijo de consulta y con prefijo de documento, el
  par correcto gana en el 100 % de los casos; con el prefijo de consulta la similitud media de los pares
  incorrectos baja (0.5437 contra 0.5503 sin prefijo) mientras la de los correctos se mantiene (0.7208 contra
  0.7203), es decir, separa un poco mejor. Se adopta el prefijo de consulta para búsquedas.
- **Lado de la imagen** (`0.3b`, 50 imágenes por lado):

| Lado (px) | s por imagen | Par correcto gana | R@1 | R@5 |
|---|---|---|---|---|
| 256 | 2.308 | 1.00 | 0.98 | 1.00 |
| 384 | **2.198** | 1.00 | 0.96 | 1.00 |
| 512 | 2.434 | 1.00 | 0.98 | 1.00 |
| 768 | 3.978 | 1.00 | 0.96 | 1.00 |

  Regla: entre los lados de calidad equivalente (R@5 a ≤0.04 del mejor y tasa de acierto ≥0.80), el de menor
  tiempo por imagen → **384 px**.

## Consecuencias
- **Se gana:** búsqueda texto→imagen y duplicados con un solo modelo pequeño, sin pasar por un LLM; indexar las
  3,600 fotos cuesta unas 2.2 h en esta CPU en lugar de unas 4 h a 768 px.
- **Se sacrifica:** el modelo pesa 671.0 MB en disco contra 304.0 MB de `270m` (`h0.json` →
  `modelos_descargados`), con su costo correspondiente de memoria en el contenedor `ollama` (ver ADR-12).
- **Riesgos:** la prueba de 50 pares es pequeña; la calidad real de la búsqueda se mide en H7 sobre la galería
  de 1,000 imágenes (R3). La versión de Ollama queda fijada: actualizarla exige repetir H0.
