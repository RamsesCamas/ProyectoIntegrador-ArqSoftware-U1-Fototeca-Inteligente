# Diagramas de Fototeca Viva

Cada diagrama tiene su fuente en Mermaid (`.mmd`) y su imagen renderizada (`.png`) con el mismo nombre. Los diagramas
se escribieron a partir del código del servicio: el encabezado de cada `.mmd` dice qué archivos de `servicio/`,
`web/` o `docker-compose.yml` representa. Si el código cambia, se corrige primero la fuente y luego se vuelve a
renderizar.

## Cómo renderizarlos

```bash
docker compose --profile docs run --rm diagramas
```

- El servicio `diagramas` (perfil `docs` de `docker-compose.yml`) usa la imagen `minlag/mermaid-cli:12.0.0`
  (Mermaid 12.0.0, publicada para `linux/amd64` y `linux/arm64`). Corre sin red (`network_mode: none`), convierte cada
  `docs/diagramas/*.mmd` a `.png` (escala 2, fondo blanco) y termina. No forma parte de la operación ni del presupuesto
  de memoria de la demo.
- `mermaid-config.json` fija el tema, la fuente (DejaVu Sans, que trae la imagen), los márgenes y el ancho de las
  etiquetas, para que todos los diagramas se vean iguales.
- El contenedor escribe como el usuario `mermaidcli` (uid 1001). En Docker Desktop (Windows y macOS) no hace falta
  nada más; en Linux, la carpeta `docs/diagramas/` debe permitir escritura a ese usuario.
- En Mermaid, el punto y coma separa instrucciones: en los mensajes de los diagramas de secuencia se usa coma o «·».

## Índice

| N.º | Archivo | Título | Notación |
|---|---|---|---|
| 1 | `01-contexto` | Contexto de Fototeca Viva | C4, nivel 1 |
| 2 | `02-contenedores` | Contenedores | C4, nivel 2 |
| 3 | `03-capas` | Capas del servicio y dirección de las dependencias | Diagrama de capas |
| 4 | `04-componentes` | Componentes del contenedor `servicio` | C4, nivel 3 |
| 5 | `05-despliegue` | Despliegue local | Estilo UML de despliegue |
| 6 | `06-secuencia-ingesta` | Ingesta: `POST /documentos` (fotos y normas) y eliminación | UML de secuencia |
| 7 | `07-secuencia-ficha-normal` | Ficha normal: los 10 pasos del flujo de una consulta | UML de secuencia |
| 8 | `08-secuencia-ficha-cache` | Ficha desde la caché semántica (foto casi duplicada) | UML de secuencia |
| 9 | `09-secuencia-entrada-bloqueada` | Entrada bloqueada por los guardrails (422 con mensaje seguro) | UML de secuencia |
| 10 | `10-secuencia-ciclo-agente` | Ciclo de agente: recuperación pobre y reformulación | UML de secuencia |

## Explicación breve de cada diagrama

**Diagrama 1 · Contexto (C4, nivel 1).** Muestra a Fototeca Viva como una caja negra con sus tres tipos de persona:
el archivista (usuario principal, que carga, valida, busca y depura duplicados), la persona ciega o con baja visión
(beneficiaria, que lee el texto alternativo) y el administrador de TI (que prepara y levanta el sistema). Los sistemas
externos (la biblioteca de modelos de Ollama, Crossmodal-3600 con Open Images, el corpus normativo y el Tesauro de la
UNESCO) quedan dentro de un recuadro punteado porque solo se usan durante la preparación: en operación el sistema no
usa la red.

**Diagrama 2 · Contenedores (C4, nivel 2).** Los cuatro contenedores de `docker-compose.yml` y sus protocolos: el
navegador habla con `web` (nginx) por HTTP en el puerto 8080; `web` reenvía `/api/*` al `servicio` (FastAPI) y nunca
habla con Ollama ni con Qdrant (R8); el `servicio` llama a `ollama` (`/api/chat` y `/api/embed`) y a `qdrant` (API REST)
por HTTP/JSON, y guarda documentos, fichas, caché, eventos, retroalimentación y lotes en SQLite (volumen
`sqlite_datos`) y las fotos en `./data`. El contenedor efímero `modelos` (perfil `preparacion`) descarga los modelos.

**Diagrama 3 · Capas del servicio.** Las capas C1 a C7 y `dominio` apiladas con la dirección de sus dependencias (cada
capa usa solo capas inferiores) y, a un lado, las transversales T1 y T2. Muestra la inversión de dependencias: T1 y T2
definen sus puertos (`SumideroEventos` y `AlmacenRetroalimentacion`), C7 los implementa con SQLite y la raíz de
composición (`api/arranque.py`) los conecta. Los tres contratos de import-linter de `servicio/pyproject.toml`, que
`pytest` verifica en `pruebas/test_contratos.py`, aparecen en la nota inferior.

**Diagrama 4 · Componentes (C4, nivel 3).** Los módulos principales de cada capa dentro del contenedor `servicio` y
sus interfaces. Los hexágonos son los puertos de C7 (`ClienteLLM`, `Embebedor`, `AlmacenVectorial`,
`AlmacenDocumentos`, `AlmacenCache` y `AlmacenLotes`) y de T1 y T2; las flechas punteadas «puerto → adaptador» se
leen «lo implementa». Las capas superiores solo conocen los puertos; los adaptadores concretos (`OllamaCliente`,
`EmbebedorOllama`, `QdrantAlmacen` y los `*Sqlite`) los crea `arranque.py`.

**Diagrama 5 · Despliegue local.** Qué corre en la laptop de la demo: el navegador, la VM de Docker Desktop (WSL 2)
con los cuatro contenedores en la red de compose, sus imágenes con tag exacto, sus límites de memoria, sus puertos
publicados y sus volúmenes, más los contenedores efímeros de preparación, documentación y scripts. La nota resume el
presupuesto de memoria (suma de límites) y la prueba sin red de `docker-compose.sinred.yml`.

**Diagrama 6 · Secuencia de ingesta.** `POST /documentos` con una foto: guardrails de archivo y de EXIF, búsqueda de
duplicado exacto por SHA-256, embedding de la imagen, verificación de dominio antes de guardar (una captura de un
documento no entra al archivo), guardado, detección de casi duplicados en `fotos_img`, indexado e incremento de
`version_archivo` (que deja sin efecto la caché de búsquedas). La rama de normas muestra la
fragmentación y el cambio de versión del corpus (que deja sin efecto las fichas en caché), y el final muestra la
eliminación con la invalidación por la etiqueta `doc:{id}`.

**Diagrama 7 · Secuencia de una ficha normal.** El recorrido completo por las capas con las etiquetas de los diez
pasos del flujo de una consulta: traza, guardrails de entrada, caché, recuperación de ejemplos (que en Fototeca Viva
va antes del enrutador, porque este decide con señales de los vecinos), enrutamiento, generación por la ruta completa
(P1 y P3 con Qwen, con LFM3 de respaldo en P3) o la rápida (P2 con Qwen), guardrails de salida con su política, guardado en caché y
registro en T1, respuesta con fuentes y `meta`, y retroalimentación con validación que promueve la ficha como
ejemplo del RAG.

**Diagrama 8 · Secuencia de una ficha desde la caché.** La misma foto recortada: la ingesta registra el casi
duplicado y el flujo de la ficha encuentra un acierto semántico en dos niveles (fichas generadas en la caché SQLite o
fichas validadas del archivo en Qdrant). Se responde con la ficha del original, `cache = semantica` y `duplicado_de`,
sin llamar a ningún modelo de lenguaje.

**Diagrama 9 · Secuencia de una entrada bloqueada.** Dos casos que terminan en 422 con un mensaje seguro que no
repite el contenido: una búsqueda con inyección de instrucciones (heurística más similitud con prototipos) y la
captura de un documento que la verificación de dominio identifica como no fotografía al cargarla, antes de guardarla
(la misma verificación se repite al catalogar una foto ya guardada). En ambos se registra el evento de bloqueo en T1 y
no se consulta la caché ni ningún modelo de lenguaje.

**Diagrama 10 · Secuencia del ciclo de agente.** Una foto de una región que no está en el archivo: la recuperación
unificada es pobre (top-1 bajo o margen top-1 − top-5 pequeño), así que el agente reformula por la ruta pipeline (Qwen
describe la foto, la descripción y luego sus elementos se buscan como texto y todo se fusiona con RRF) hasta que la
recuperación mejora o se alcanza `MAX_ITER`; después enruta y genera la ficha, que informa `iteraciones_agente`.

## Convenciones

- **C4 con flowcharts.** Las vistas C4 (1, 2 y 4) se dibujan con flowcharts de Mermaid y la paleta habitual de C4:
  personas en azul oscuro, el sistema en azul, contenedores en azul medio, componentes en azul claro y sistemas
  externos en gris. El renderizador nativo de C4 de Mermaid encimaba etiquetas y flechas, así que se descartó.
- **Capas.** Las capas de negocio van en azul y las transversales en naranja. Los hexágonos son puertos
  (`typing.Protocol`).
- **Despliegue.** Se emulan los nodos UML con estereotipos («dispositivo», «entorno de ejecución», «contenedor»,
  «volumen») en subgrafos anidados.
- **Secuencias.** Cada participante está dentro de un recuadro con el nombre de su capa (C1 a C7, T1). Los adaptadores
  de C7 llevan una flecha hacia el contenedor que usan (por ejemplo, `QdrantAlmacen → qdrant`).
- **Umbrales.** Los diagramas nombran los umbrales (τ_dup, τ_ret, τ_fuera_dominio, τ_inyeccion…) sin su valor: los
  valores viven en `servicio/config/parametros.yaml` y se exponen en `GET /configuracion`. Las verificaciones que
  dependen de un umbral calibrado se comportan como muestran los diagramas cuando ese umbral existe; sin él,
  `fuera_de_dominio` y `texto_visible` aprueban y lo anotan en la traza, y el ciclo de agente no se activa.
