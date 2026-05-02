FROM python:3.11-slim

WORKDIR /code

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

# Build context é /api do repo. Copia tudo pra /code/api/
# pra que `import api.main` funcione (imports relativos dentro do pacote).
COPY requirements.txt /code/api/
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /code/api/requirements.txt

COPY . /code/api/

# Cria __init__.py se não existir (garante pacote)
RUN touch /code/api/__init__.py /code/api/routers/__init__.py 2>/dev/null || true

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/code \
    PORT=8000

EXPOSE 8000

# Entrypoint multi-mode: API/worker/beat via SERVICE_MODE env
COPY entrypoint.sh /code/api/entrypoint.sh
RUN chmod +x /code/api/entrypoint.sh

# HEALTHCHECK condicional: api (HTTP /health) | worker/beat (sempre OK,
# Celery quem decide saúde). SERVICE_MODE setado via env do Easypanel.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD sh -c '[ "${SERVICE_MODE:-api}" != "api" ] || curl -f http://localhost:8000/health' || exit 1

ENTRYPOINT ["/code/api/entrypoint.sh"]
