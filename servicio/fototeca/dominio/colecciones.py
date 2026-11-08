"""Nombres de las colecciones vectoriales (informe, Tabla 7; ADR-09). Las comparten C2, C4 y C5."""

FOTOS_IMG = "fotos_img"                  # EmbeddingGemma-2, imagen: una entrada por foto
FOTOS_TXT = "fotos_txt"                  # EmbeddingGemma-2, texto: ficha validada o descripción de referencia
FOTOS_TXT_GRANITE = "fotos_txt_granite"  # granite, texto: lo mismo que fotos_txt (experimento R3 y consistencia)
FOTOS_DESC_QWEN = "fotos_desc_qwen"      # descripción de Qwen (ruta pipeline)
NORMAS = "normas"                        # fragmentos de IPTC, W3C y DCMI
TESAURO = "tesauro"                      # un concepto por entrada
PROTOTIPOS = "prototipos"                # prototipos para guardrails y para el enrutador de búsquedas

TODAS = (FOTOS_IMG, FOTOS_TXT, FOTOS_TXT_GRANITE, FOTOS_DESC_QWEN, NORMAS, TESAURO, PROTOTIPOS)
