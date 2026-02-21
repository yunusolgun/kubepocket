# Dockerfile
FROM python:3.11-slim

LABEL maintainer="KubePocket Team <info@kubepocket.com>"
LABEL description="Kubernetes cost and resource monitoring with anomaly detection and forecasting"
LABEL version="2.0.0"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    sqlite3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY api/ ./api/
COPY collector/ ./collector/
COPY db/ ./db/
COPY prometheus_exporter/ ./prometheus_exporter/
COPY reporter/ ./reporter/

# Create necessary directories
RUN mkdir -p /data /var/log/kubepocket

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Volumes for persistent data
VOLUME ["/data", "/var/log/kubepocket"]

# Expose ports
EXPOSE 8000 8001

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Entrypoint
ENTRYPOINT ["/entrypoint.sh"]