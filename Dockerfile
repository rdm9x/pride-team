# syntax=docker/dockerfile:1.7
#
# pride-team — production Docker image.
# Multi-stage build: builder колесит wheel'ы, runner ставит их offline.
# Цель: < 250 MB, non-root, healthcheck на /healthz, EXPOSE 5000.

ARG PYTHON_VERSION=3.12

# ──────────────────────────────────────────────────────────────────────────────
# Stage 1: builder — собираем wheel'ы зависимостей.
# build-essential нужен только тут (для возможных C-extension build из sdist).
# ──────────────────────────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS builder

WORKDIR /build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip wheel --no-cache-dir --wheel-dir=/wheels -r requirements.txt

# ──────────────────────────────────────────────────────────────────────────────
# Stage 2: runner — минимальный slim, ставим wheel'ы offline.
# tini — корректный init (PID 1) для proper signal handling.
# curl — для HEALTHCHECK.
# ──────────────────────────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS runner

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PRIDE_DASHBOARD_HOST=0.0.0.0 \
    PRIDE_DASHBOARD_PORT=5000 \
    PRIDE_TASKS_DB=/app/data/tasks.db \
    PYTHONPATH=/app/mcp_server

# tini + curl (рантайм), создаём non-root юзера pride (UID/GID 1000).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 pride \
    && useradd  --system --uid 1000 --gid pride --home-dir /app --shell /usr/sbin/nologin pride

WORKDIR /app

# Сначала ставим зависимости (offline из /wheels) — кэш-слой переживает изменения кода.
COPY --from=builder /wheels /wheels
COPY requirements.txt ./
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# Копируем код приложения (директории переименованы из кириллицы в латиницу).
COPY --chown=pride:pride dashboard/   /app/dashboard/
COPY --chown=pride:pride mcp_server/  /app/mcp_server/
COPY --chown=pride:pride roles/       /app/roles/
COPY --chown=pride:pride commands/    /app/commands/
COPY --chown=pride:pride llm/         /app/llm/

# data/ — runtime-volume, БД и логи пишутся сюда. Создаём с правами pride.
RUN mkdir -p /app/data && chown -R pride:pride /app/data

USER pride

EXPOSE 5000

# /healthz уже реализован в dashboard/app.py (строка 891).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:5000/healthz || exit 1

# tini как PID 1 — корректно обрабатывает SIGTERM/SIGINT (Ctrl-C, docker stop).
ENTRYPOINT ["tini", "--"]
CMD ["python", "dashboard/app.py"]
