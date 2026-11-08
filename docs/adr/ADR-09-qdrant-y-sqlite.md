# ADR-09: Qdrant como base vectorial y SQLite para documentos, caché, eventos y retroalimentación; un adaptador por recurso (C7)

**Estado:** Aceptada
**Fecha:** 2026-11-08
**Atributos de calidad en juego:** memoria (límite de 512m para la base vectorial y presupuesto total), filtros por
metadatos, operación sin red en Windows, mantenibilidad (cambiar un recurso sin tocar las capas superiores)

## Contexto
El servicio necesita dos tipos de almacenamiento:
- **vectorial**, con filtros por metadatos (`validada`, `documento_id`, `particion`, `tipo`, `clase`), borrado por
  documento, conteo y lectura de vectores, para siete colecciones: `fotos_img`, `fotos_txt`, `fotos_txt_granite`,
  `fotos_desc_qwen`, `normas`, `tesauro` y `prototipos` (`servicio/fototeca/dominio/colecciones.py`);
- **relacional y de archivos**, para los documentos y sus fichas, los duplicados, el estado del archivo
  (`version_archivo`, `version_corpus`), la caché con TTL y etiquetas, los eventos de T1, la retroalimentación de T2 y los
  lotes, además de las fotos mismas.

Todo debe caber en el presupuesto de memoria (ADR-12), funcionar sin red y arrancar igual en Docker Desktop para Windows.
El curso pide un adaptador por recurso, de modo que cambiar de base vectorial no obligue a modificar las capas
superiores.

## Decisión
- **Qdrant v1.19.2** en su propio contenedor, con límite de 512m y volumen `qdrant_datos`, detrás del puerto
  `AlmacenVectorial`. El adaptador `QdrantAlmacen` usa la API REST por HTTP con `httpx` (sin cliente gRPC) y crea índices
  de carga útil para los campos de filtro.
- **SQLite** en un solo archivo (`fototeca.db`) dentro del volumen con nombre `sqlite_datos`, detrás de los puertos
  `AlmacenDocumentos`, `AlmacenCache`, `AlmacenLotes`, `SumideroEventos` (T1) y `AlmacenRetroalimentacion` (T2); las fotos
  van como archivos en `./data/fotos`. La caché semántica guarda sus vectores en SQLite y los compara con una búsqueda
  lineal en numpy, sin Redis.
- SQLite vive en un **volumen con nombre** y no en la carpeta montada `./data`, porque en Docker Desktop para Windows
  SQLite sobre carpetas montadas puede fallar por bloqueos o por el modo WAL.
- Solo la raíz de composición (`servicio/fototeca/api/arranque.py`) conoce las clases concretas; las capas superiores
  dependen de los `Protocol` de `servicio/fototeca/datos/puertos.py`.

## Alternativas
- **Chroma o FAISS dentro del proceso del servicio:** la memoria de los índices se sumaría al límite de 1536m del
  `servicio`, y FAISS no ofrece filtros por metadatos ni borrado por documento con la misma comodidad.
- **pgvector:** un contenedor de PostgreSQL para dos usos que SQLite y Qdrant ya cubren, con más memoria y más operación.
- **Redis para la caché:** otro contenedor y más memoria para una caché pequeña; además, la caché tiene que sobrevivir a
  un reinicio sin configuración extra.
- **Guardar también las fichas y la caché en Qdrant:** mezclaría datos relacionales (estados, TTL, etiquetas, lotes) con
  vectores, y la caché quedaría atada a la base vectorial.

## Evidencia
Fuente: `evaluacion/resultados/h0.json` → `verificaciones.0.5.docker_stats` (muestras de `docker stats` con los cuatro
modelos cargados y fichas en curso).

| Medición | Valor |
|---|---|
| Pico de memoria del contenedor `qdrant` | 0.21 GiB (`pico_por_contenedor_gib`) |
| Límite del contenedor `qdrant` | 0.5 GiB (`limite_por_contenedor_gib`) |
| Contenedores que alcanzaron su límite | ninguno (`contenedores_que_alcanzan_su_limite` vacío) |
| Suma de los picos en la ventana de medición | 4.813 GiB (`pico_suma_en_ventana_gib`) |

- Esa medición es de la verificación inicial de viabilidad, antes de indexar el archivo completo: es el piso de memoria
  de Qdrant, no su uso con las siete colecciones llenas.
- **Intercambiabilidad:** las pruebas del servicio sustituyen todos los adaptadores por versiones en memoria
  (`servicio/pruebas/falsos.py`: `AlmacenVectorialFalso`, `EmbebedorFalso`, `ClienteLLMFalso`…) sin cambiar ninguna capa
  superior, y el contrato de capas impide que una capa superior importe un adaptador (ADR-13).
- **pendiente:** la memoria de `qdrant` con las colecciones llenas, medida con `docker stats` durante el guion de la demo
  en la verificación final sin red, y la latencia de la recuperación por capa (`contexto` y `cache`) en
  `evaluacion/resultados/desempeno.json`.

## Consecuencias
- **Se gana:** la base vectorial queda aislada en su contenedor con un límite propio; SQLite no agrega procesos ni
  memoria aparte; cambiar Qdrant por otra base implica escribir un adaptador nuevo y cambiar una línea en `arranque.py`.
- **Se sacrifica:** SQLite admite un solo escritor a la vez (suficiente con un proceso del servicio y un trabajador de
  lotes, ADR-08) y la caché semántica hace una búsqueda lineal.
- **Riesgos:** si el archivo crece mucho, el límite de 512m de Qdrant puede quedarse corto; la medición con el índice
  completo lo dirá. La API REST de Qdrant debe mantenerse compatible si se actualiza la versión fijada.
