# ADR-05: Verificaciones de los guardrails y política ante cada falla

**Estado:** Propuesta
**Fecha:** 2026-11-08
**Atributos de calidad en juego:** seguridad (inyección de instrucciones), privacidad (EXIF, GPS, datos personales,
atributos sensibles), apego de la ficha a la imagen, falsos positivos, latencia añadida

## Contexto
Las entradas de Fototeca Viva son archivos que llegan de cualquier lado (fotos con metadatos de ubicación, capturas de
pantalla, fotos con letreros que contienen instrucciones) y textos de búsqueda escritos por personas. Las salidas son
fichas que redactan modelos pequeños y que se van a publicar con la foto. Cada falla necesita una política explícita:
bloquear, sanitizar, marcar para revisión, reintentar o aislar.

## Decisión
Cada verificación devuelve un `ResultadoGuardrail` (verificación, resultado `aprobada`/`sanitizado`/`marcada`/`bloqueada`,
valor, umbral y política aplicada) que viaja en `meta.guardrails` y en la traza. Las políticas viven en un solo lugar,
`servicio/fototeca/guardrails/politicas.py`:

| Verificación | Dónde | Cómo | Política ante la falla |
|---|---|---|---|
| `archivo_valido` | entrada, foto | contenido real JPEG o PNG (Pillow, no la extensión), tamaño máximo y lados mínimo y máximo | **bloquear**: 413, 415 o 422 con mensaje seguro |
| `exif_privacidad` | entrada, foto | GPS, número de serie, autor, XMP e IPTC | **sanitizar** antes de guardar y dejar constancia |
| `fuera_de_dominio` | entrada, foto: al cargarla (antes de guardarla) y otra vez al catalogar | similitud de la imagen con prototipos de «fotografía de una escena real» contra «captura de un documento, tabla o interfaz» | **bloquear**: 422 «Esto no parece una fotografía…»; la captura no entra al archivo |
| `texto_visible` | entrada, foto | similitud con prototipos de foto con texto escrito | **marcar**: la ficha va por la ruta completa (ADR-03) |
| `inyeccion_en_imagen` | entrada, foto (ruta completa) | patrones («ignora», «instrucciones», «system», «olvida»…) y similitud con prototipos de inyección sobre el texto visible que copia P1 | **aislar**: no se bloquea la foto; el texto pasa a P3 como dato entre delimitadores, se agrega una advertencia y, con confianza alta, la ficha queda `requiere_revision` |
| `pii_texto` | entrada, búsqueda | expresiones regulares de CURP, RFC, correo, teléfono y tarjeta (con dígito de Luhn) | **sanitizar**: enmascarar y continuar |
| `inyeccion_texto` | entrada, búsqueda | patrones y similitud con prototipos de inyección | **bloquear**: 422 con mensaje seguro que no repite el contenido |
| `esquema` | salida, ficha | el JSON valida contra el esquema Pydantic | **reintentar** una vez con el error; después, respaldo o ficha degradada |
| `reglas_iptc` | salida, ficha | texto alternativo no vacío y de 250 caracteres o menos, sin «imagen de»/«foto de»; titular de 120 o menos | **sanitizar** (recortar por oración y normalizar el inicio); si queda vacío, reintentar |
| `atributos_sensibles` | salida, ficha | léxico en español y P6 con Qwen solo si el léxico detecta algo | **reintentar** una vez sin la frase; luego eliminarla y **marcar** |
| `tesauro` | salida, ficha | cada palabra clave al concepto más cercano si supera τ_tesauro | **sanitizar**: concepto del tesauro o término libre |
| `apego_visual` | salida, ficha | similitud imagen–texto alternativo en EmbeddingGemma-2 contra un percentil bajo de imagen–descripción humana | **reintentar** por la ruta completa si venía de la rápida; si no, **marcar** |
| `consistencia` | salida, ficha | similitud en granite entre el texto alternativo y la descripción de P1 | **marcar** |
| `fuentes` | salida, ficha | cada campo cita ids que existían en el contexto | **sanitizar** (quitar las inválidas); campo sin fuentes: **marcar** |
| `salida_busqueda` | salida, búsqueda | no exponer rutas internas, EXIF, GPS ni hashes | **sanitizar**, y siempre con el aviso de IA |

Mientras un umbral no esté calibrado (τ_fuera_dominio, τ_texto_visible, τ_apego_visual, τ_consistencia), la verificación
aprueba y lo anota en la traza: no bloquea a ciegas. Los umbrales salen de `scripts/calibrar.py` con conjuntos de
calibración separados de los de evaluación.

## Alternativas
- **Bloquear toda foto con texto visible:** produciría falsos positivos con letreros, carteles y señales, que son parte
  legítima de un archivo fotográfico.
- **Un modelo de lenguaje como clasificador de todas las entradas:** decenas de segundos más por petición en CPU; se
  reserva P6 para confirmar lo que el léxico ya detectó.
- **Guardar la foto con su EXIF y filtrarlo al mostrarla:** el dato sensible quedaría en disco; se quita antes de
  guardar.
- **Rechazar la ficha completa ante cualquier falla de salida:** el archivista perdería el trabajo; se prefiere
  reintentar, sanitizar o marcar `requiere_revision` y dejar la decisión a una persona.

## Evidencia
**pendiente:** `evaluacion/resultados/guardrails.json`, por verificación: bloqueos o marcas correctas, falsos positivos,
latencia añadida y política aplicada, sobre `inyeccion_imagen` (15), `fuera_de_dominio` (15), `gps_sintetico` (20) y
`consultas_guardrail` (25: 10 con inyección, 5 con datos personales y 10 normales), con `texto_benigno_imagen` (15) y
20 fotos normales como casos que no deben activarse; más las activaciones de salida sobre las 60 fichas evaluadas
(`apego_visual`, `consistencia`, `atributos_sensibles` y `fuentes`), de las que el autor revisa 10 a mano. Las metas son
90 % o más de bloqueos correctos y 10 % o menos de falsos positivos (`servicio/config/metas_calidad.yaml`). Los umbrales
calibrados saldrán en `evaluacion/resultados/calibracion_h4.json` y `calibracion_h5.json`.

**τ_tesauro.** El valor inicial (0.75, `servicio/config/parametros.yaml`) nunca se midió para el cruce de etiquetas de
Open Images en inglés a conceptos del tesauro en español, así que se calibra al indexar el archivo con un **proxy
léxico**: el concepto esperado de una etiqueta es el que la tiene, en singular o plural, entre sus etiquetas en inglés.
Sobre esas etiquetas se elige el τ más bajo con precisión de 0.90 o más y al menos 20 mapeos aceptados (si ninguno
llega, el de mayor F1). El mapeo sigue siendo por embeddings: el proxy solo define el esperado. La regla se fijó antes
de ver los datos (`servicio/scripts/indexar_archivo.py`). **pendiente:** el τ elegido y su curva en
`evaluacion/resultados/calibracion_tesauro.json`, y la recalibración cuando el autor revise los 50 pares.

Dato que ya existe: ninguna de las fotos del corpus trae EXIF ni GPS (`evaluacion/resultados/h0.json` →
`verificaciones.0.7.exif`: `imagenes_con_exif` 0 y `con_gps` 0); por eso el guardrail de EXIF se prueba con copias a las
que se les inyecta un GPS sintético. Las pruebas unitarias de las verificaciones de entrada están en
`servicio/pruebas/test_guardrails_entrada.py`.

## Consecuencias
- **Se gana:** cada falla tiene una política conocida y visible en la respuesta (`meta.guardrails`) y en el panel de
  métricas; la privacidad se protege antes de guardar.
- **Se sacrifica:** latencia en la salida (embeddings para `apego_visual` y `consistencia`, y P6 cuando el léxico detecta
  algo), y la heurística de patrones solo cubre los idiomas y frases previstos.
- **Riesgos:** las inyecciones nuevas que no se parezcan a los patrones ni a los prototipos pueden pasar (por eso el
  texto visible nunca se trata como instrucción, se detecte o no); un umbral mal calibrado puede bloquear fotos
  legítimas.
