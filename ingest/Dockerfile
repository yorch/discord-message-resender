# syntax=docker/dockerfile:1

FROM python:3.13-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    ROUTES_PATH=/app/config/routes.yaml

# git is required for the pinned git dependency (discord.py-self is sourced from
# a commit on main, not PyPI); python:3.13-slim ships without it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

RUN useradd --create-home --uid 10001 resender && chown -R resender:resender /app
USER resender

CMD ["python", "-m", "resender"]
