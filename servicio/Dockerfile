# Imagen del servicio: API, lógica en capas, scripts de preparación y evaluación.
# Dependencias gestionadas con uv por decisión del autor: se declaran con `==` en pyproject.toml, se resuelven en
# uv.lock (multiplataforma y con hashes: sirve para arm64 y amd64) y la imagen las instala con `uv sync --frozen`.
FROM ghcr.io/astral-sh/uv:0.13.5 AS uv

# ── Etapa base: Python + uv + fuentes. También sirve para regenerar uv.lock:
#    docker build --target base -t fototeca-base ./servicio
#    docker run --rm -v ./servicio:/app -w /app fototeca-base uv lock
FROM python:3.12.16-slim-bookworm AS base

# Fuentes para Pillow (texto en imágenes sintéticas) y matplotlib (gráficas)
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app \
    MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /app

# ── Etapa final
FROM base AS servicio

# Capa de dependencias: solo se reconstruye si cambian pyproject.toml o uv.lock.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

COPY . .

EXPOSE 8000
CMD ["uvicorn", "fototeca.api.principal:app", "--host", "0.0.0.0", "--port", "8000"]
