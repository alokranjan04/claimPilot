# ---- ClaimPilot container image ----
# Multi-stage: install deps with uv, then a slim runtime.

FROM python:3.12-slim AS builder

# uv for fast, reproducible installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Install dependencies first (better layer caching), incl. the azure extra.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra azure --no-install-project

# Now copy the source and install the project itself.
COPY README.md ./
COPY src ./src
COPY evals ./evals
RUN uv sync --frozen --no-dev --extra azure


FROM python:3.12-slim AS runtime

# Run as a non-root user (security baseline).
RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

# Bring over the resolved virtualenv and the app.
COPY --from=builder /app /app
COPY ui ./ui
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PROVIDER=azure

USER appuser
EXPOSE 8000

# API process. Azure auth is via the Container App's managed identity
# (DefaultAzureCredential) — no keys baked into the image.
# The background worker runs in-process via the FastAPI lifespan at M8;
# Default: API process. For the worker, override the command with:
#   python -m claimpilot.api.worker_main
CMD ["uvicorn", "claimpilot.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
