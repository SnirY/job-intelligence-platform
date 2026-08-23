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
COPY packages/ai-core/pyproject.toml packages/ai-core/
COPY packages/prompts/pyproject.toml packages/prompts/
COPY packages/job-sources/pyproject.toml packages/job-sources/
COPY apps/api/pyproject.toml apps/api/
COPY apps/worker/pyproject.toml apps/worker/

COPY packages/config/src packages/config/src
COPY packages/ai-core/src packages/ai-core/src
COPY packages/prompts/src packages/prompts/src
COPY packages/job-sources/src packages/job-sources/src
COPY apps/api/src apps/api/src
COPY apps/worker/src apps/worker/src

# Local path installs, in dependency order. jip-api depends on jip-ai-core,
# jip-prompts and jip-job-sources, and none of them is published anywhere —
# without them here pip goes looking on PyPI and fails with "No matching
# distribution found".
#
# That is exactly what happened when job-sources was added. The dependency went
# into `apps/api/pyproject.toml` and `requirements-dev.txt`, every host check
# passed, and this file was not touched — the Compose job in CI is what catches
# it, and CI has been blocked on billing since 2026-08-15. The first thing to
# notice was a person trying to bring the stack up.
#
# **A new Python package belongs in four places**, and this is the one that is
# easy to miss: its own `pyproject.toml`, the root tooling config,
# `requirements-dev.txt`, and here.
RUN pip install ./packages/config ./packages/ai-core ./packages/prompts \
    ./packages/job-sources ./apps/api ./apps/worker

COPY apps/api/alembic.ini apps/api/
COPY apps/api/migrations apps/api/migrations

# Drop privileges: a compromised process should not be root.
RUN useradd --create-home --uid 10001 jip && chown -R jip:jip /app
USER jip

EXPOSE 8000

CMD ["uvicorn", "jip_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
