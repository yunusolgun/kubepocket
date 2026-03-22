# ── Stage 1: Build ────────────────────────────────────────────────
# Compiles C extensions (psycopg2, cryptography, numpy, scikit-learn).
# gcc/g++ are only needed here — not in the final image.
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: Runtime ──────────────────────────────────────────────
# Lean final image — no build tools, only runtime dependencies.
FROM python:3.11-slim

LABEL maintainer="KubePocket Team <yunus.olgun@outlook.com>"
LABEL version="3.0.0"

WORKDIR /app

# Runtime system deps only (curl for healthcheck, netcat for init container)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    netcat-openbsd \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy compiled Python packages from builder
COPY --from=builder /install /usr/local

# Application code
COPY api/                ./api/
COPY collector/          ./collector/
COPY db/                 ./db/
COPY prometheus_exporter/ ./prometheus_exporter/
COPY reporter/           ./reporter/
COPY alembic/            ./alembic/
COPY alembic.ini         .
COPY licensing/          ./licensing/

RUN mkdir -p /var/log/kubepocket

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000 8001

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app

ENTRYPOINT ["/entrypoint.sh"]
