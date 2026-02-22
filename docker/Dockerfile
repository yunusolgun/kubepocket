FROM python:3.11-slim
LABEL maintainer="KubePocket Team <info@kubepocket.com>"
LABEL version="3.0.0"

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/ ./api/
COPY collector/ ./collector/
COPY db/ ./db/
COPY prometheus_exporter/ ./prometheus_exporter/
COPY reporter/ ./reporter/
COPY alembic/ ./alembic/
COPY alembic.ini .

RUN mkdir -p /var/log/kubepocket

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000 8001

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

ENTRYPOINT ["/entrypoint.sh"]
