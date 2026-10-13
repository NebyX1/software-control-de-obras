# Contexto de build: raíz del proyecto (ver docker-compose.yml).
# Se conserva el layout del repositorio (/app/backend): la configuración deriva
# rutas como root/backend/migrations desde la ubicación del paquete.
FROM python:3.11.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd --system cc \
    && useradd --system --gid cc --home-dir /app --shell /usr/sbin/nologin cc

WORKDIR /app

COPY backend/requirements.lock /tmp/requirements.lock
RUN pip install -r /tmp/requirements.lock && rm /tmp/requirements.lock

COPY backend/ ./backend/

RUN mkdir -p /var/lib/cc/documents /var/lib/cc/models \
    && chown -R cc:cc /var/lib/cc

WORKDIR /app/backend

ENV FLASK_APP=wsgi.py \
    FLASK_RUN_HOST=0.0.0.0 \
    DOCUMENT_ROOT=/var/lib/cc/documents \
    MODEL_CACHE=/var/lib/cc/models

USER cc

EXPOSE 5006

CMD ["gunicorn", "--bind", "0.0.0.0:5006", "--workers", "1", "--threads", "8", "--timeout", "120", "--access-logfile", "-", "wsgi:app"]
