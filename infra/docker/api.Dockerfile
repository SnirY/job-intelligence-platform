# API image. Also used for the worker: both processes share the same Python
# dependency set, and one image means one thing to build and scan.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependency metadata first so an application-code change does not invalidate
# the dependency layer.
COPY packages/config/pyproject.toml packages/config/
COPY apps/api/pyproject.toml apps/api/
COPY apps/worker/pyproject.toml apps/worker/

COPY packages/config/src packages/config/src
COPY apps/api/src apps/api/src
COPY apps/worker/src apps/worker/src

RUN pip install ./packages/config ./apps/api ./apps/worker

COPY apps/api/alembic.ini apps/api/
COPY apps/api/migrations apps/api/migrations

# Drop privileges: a compromised process should not be root.
RUN useradd --create-home --uid 10001 jip && chown -R jip:jip /app
USER jip

EXPOSE 8000

CMD ["uvicorn", "jip_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
