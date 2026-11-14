# Diapositivas · Fototeca Viva

**Duración:** 15 minutos de exposición y 5 de preguntas. Reparto aproximado: proyecto (2 min), arquitectura de
software (2 min), arquitectura de modelos (2 min), decisiones (3 min), resultados (1 min), demo en vivo (5 min) y
limitaciones (0.5 min). [AUTOR: ajustar después del ensayo.]

**Versión diseñada:** el mazo de 21 diapositivas está en el artifact «Fototeca Viva · Arquitectura» (privado; se
exporta a PDF o PPTX desde Compartir › Exportar). Las notas del orador están en cada diapositiva. Para presentar sin
internet, llevar la exportación en PDF.

**Reglas de diseño:** estilo «Mesa de luz», el mismo de la web (mesa clara, película oscura, etiqueta de papel y lápiz
graso naranja solo para marcar). Títulos descriptivos y cortos; una idea por diapositiva; las explicaciones van en las
notas. Toda cifra sale de `evaluacion/resultados/` y su fuente aparece al pie.

---

## Proyecto

1. **Fototeca Viva** (portada). Tira de película con seis fotos del archivo de prueba; autor, materia y docente.
2. **Fotos sin catalogar.** Tres fotos con su campo vacío: no aparece al buscar, no es accesible, se cataloga dos
   veces.
3. **Ficha IPTC con la fuente de cada campo.** Ficha real (`casos/fichas_con_rag.jsonl`) con sus fuentes al margen:
   foto similar 0.87, regla W3C 0.80 y 0.78, «Mar» en el Tesauro UNESCO 0.94.

## Arquitectura de software

4. **Ejecución local en CPU.** Privacidad, 11 de 11 pasos sin internet (`demo_sin_red.json`), sin pago por llamada,
   versiones fijadas. Consecuencia: ≤ 1.7B parámetros; ficha p50 de 25.996 s (rápida) y 56.793 s (completa)
   (`desempeno.json`).
5. **Vista de contenedores.** web, servicio, ollama, qdrant, SQLite y `./data`, y el contenedor de preparación. Límites y
   picos (`h9_memoria.json`): ollama 5 GiB · 4.429, qdrant 0.5 GiB · 0.443, servicio 1.5 GiB · 0.081, web 0.0625 GiB.
6. **Capas del servicio.** C1–C7 y dominio, T1 y T2 con sus puertos; import-linter en pytest: 3 contratos, 0 rotos
   (`contrato_capas.json`).

## Arquitectura de modelos

7. **Modelos y tareas.** Qwen3.5-0.8B (P1, P2, P3, P6), LFM3-1.7B (P4, P5, P7), EmbeddingGemma-2 440m (vecinos, caché,
   enrutadores, guardrails) y granite (consistencia, R3).
8. **Flujo de una ficha.** Ocho pasos con su capa y, en carriles, el modelo de cada paso; el ciclo de agente entre
   Ejemplos y Enrutar.
9. **Gateway de modelos (C6).** Tabla de tareas, JSON Schema sin razonamiento (100 % válido a la primera,
   `r3_modelos.json`), reintento y respaldo, un turno por modelo. Tiempos límite recalibrados
   (`calibracion_tiempos_limite.json`): 58 → 92 s, 64 → 70 s y 90 → 109 s.

## Decisiones (ADR)

10. **Decisiones de arquitectura.** Los 13 ADR con su archivo de evidencia; se presentan seis.
11. **ADR-01 · Modelo de composición.** Calidad 4.88 / 4.95 / 5.00; sin revisión 18, 20 y 22 de 30; p50 31.3 / 50.5 /
    56.2 s; memoria 0.83 / 0.83 / 1.39 GB (`r3_modelos.json`). Ningún IC95 excluye 0: decide la latencia.
12. **ADR-02 · Arquitectura de embeddings.** R@1 0.9 unificado, 0.82 híbrido, 0.704 y 0.48 pipelines; describir 250
    imágenes con Qwen tomó 1.65 h (`r3_embeddings.json`).
13. **ADR-03 · Enrutador de fichas.** Estrategias (`enrutador.json`); regla: ruta completa si hay texto visible o
    consenso < 0.6768; 0.83 de exactitud fuera de muestra.
14. **ADR-04 · Umbral de la caché semántica.** Barrido de τ_dup: con 0.95, 141 de 150 casi duplicados y 1 de 75 fichas
    ajenas; ficha desde la caché en 0.023 s contra 69.312 s (`cache.json`).
15. **ADR-05 · Guardrails y políticas.** Bloquear, sanitizar, aislar y marcar, reintentar; 29 de 33 entradas bien
    manejadas (meta 0.9), 1 de 23 falsos positivos, 10 de 10 fotos con GPS limpias (`guardrails.json`).
16. **ADR-07 · Ciclo de agente.** Máquina de estados con MAX_ITER = 2; se activó en 3 de 25 fotos, 0 de 3 mejoraron,
    24.167 s de p50 añadido (`agente.json`).

## Cierre

17. **Resultados.** Siete cifras: R@1 · R@10 0.9 · 1.0; fuentes válidas 84 de 84 · 0 de 90; guardrails 29 de 33 · 1 de
    23; caché 0.94 · 1 de 75; ficha p50 25.996 · 56.793 · 0.023 s; búsqueda p95 0.359 · 6.815 s; 11 de 11 pasos sin red.
18. **Aprendizaje sin fine-tuning.** Cuatro pasos de la promoción y la curva de la simulación: 0.6788 en el bloque 1 y
    0.7396 en el 5, con intervalos que se traslapan (`aprendizaje.json`).
19. **Demo sin red.** Los once pasos de `guion_demo.md` con el tiempo de cada uno en el ensayo del 14 de noviembre.
20. **Limitaciones.** Modelos pequeños, latencia en CPU, guardrails en 0.8788, ciclo de agente sin mejora, aprendizaje
    sin efecto demostrado, 36 locales de XM3600. Trabajo futuro: medir de nuevo la búsqueda compleja con τ_excluir =
    0.73 y las latencias en la laptop de la demo.
21. **Preguntas.** Repositorio y créditos de las fotos (Open Images vía Crossmodal-3600, CC BY 2.0).

**Preguntas probables:** ¿por qué no un modelo más grande? (ADR-01 y ADR-12) · ¿cómo se evita que el texto de una foto
dé órdenes al modelo? (ADR-05) · ¿qué pasa si la caché sirve la ficha de otra foto? (ADR-04) · ¿cómo se comprueba que
las capas se respetan? (ADR-13) · ¿por qué SQLite y no Redis? (ADR-08 y ADR-09).
