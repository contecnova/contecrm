# ═══════════════════════════════════════════════════════════════════════════
#  Imagen única para todos los servicios de contecrm
# ═══════════════════════════════════════════════════════════════════════════
#
# Una sola imagen y no una por servicio. La razón es operativa: ocho imágenes
# distintas significan ocho construcciones, ocho cachés y ocho oportunidades de
# que una vaya desfasada respecto de `crmcore`. Con una imagen, el servicio lo
# elige el comando de arranque:
#
#   docker run contecrm servicio tenancy
#
# El coste es que la imagen lleva las dependencias de todos. Se acota con
# `requirements.txt` común y lo específico de un servicio en el suyo, instalado
# solo si existe.
#
# Digest fijado, no solo etiqueta: `python:3.12-slim` apunta a imágenes distintas
# según el día, así que una reconstrucción podría traer otra base sin que nadie
# lo pidiera. Con digest, la imagen es la misma hasta que alguien la suba a
# propósito.

# ── Etapa de construcción ─────────────────────────────────────────────────
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# Lo que necesita psycopg para compilar si no encuentra rueda binaria. Va solo
# en esta etapa: la imagen final no lleva compilador, que es superficie de
# ataque y 300 MB.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

# Las dependencias primero y el código después: así un cambio en el código no
# invalida la capa de dependencias, que es la que tarda.
COPY requirements.txt ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install -r requirements.txt

COPY packages/ ./packages/
RUN /opt/venv/bin/pip install ./packages/crmcore

# ── Imagen final ──────────────────────────────────────────────────────────
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS servicio

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# `libpq5` es la biblioteca de cliente en tiempo de ejecución; `curl` lo usa el
# healthcheck del compose. Nada más: cada paquete de más es superficie.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 crm

COPY --from=build /opt/venv /opt/venv

WORKDIR /app
COPY --chown=crm:crm packages/ ./packages/
COPY --chown=crm:crm services/ ./services/
COPY --chown=crm:crm alembic/ ./alembic/
COPY --chown=crm:crm alembic.ini ./
COPY --chown=crm:crm scripts/ ./scripts/
COPY --chown=crm:crm deploy/ ./deploy/

# Usuario sin privilegios. Un proceso que no necesita root no debe correr como
# root: si alguien consigue ejecución dentro del contenedor, la diferencia entre
# root y este usuario es la diferencia entre escaparse y no.
USER crm

EXPOSE 8000

# `entrypoint.sh` resuelve qué servicio arrancar y aplica las migraciones si se
# le pide. Tener un punto de entrada y no ocho comandos distintos mantiene el
# arranque en un único sitio auditable.
COPY --chown=crm:crm deploy/entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["servicio", "gateway"]
