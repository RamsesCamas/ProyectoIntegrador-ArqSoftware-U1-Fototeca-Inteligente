# Imagen de las pruebas de punta a punta (E2E) de la web. Solo se usa en el perfil `pruebas`
# (docker-compose.e2e.yml); no forma parte de la operación.
#
# La imagen oficial de Playwright para Python trae Chromium y sus dependencias del sistema, pero no el paquete de
# Python: se instala aquí la MISMA versión, con pytest, desde requirements.txt (todo fijado con ==). Se construye
# una vez durante la preparación (con internet); después las pruebas corren sin red.
FROM mcr.microsoft.com/playwright/python:v1.64.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

COPY requirements.txt /tmp/requirements-e2e.txt
RUN pip install --no-cache-dir -r /tmp/requirements-e2e.txt

WORKDIR /e2e
CMD ["python", "-m", "pytest", "-q", "/e2e"]
