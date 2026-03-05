# Container image for the Linkerd Agent
#
# Must be built from the servers/mcp/ directory (needs openssl_agent package):
#   docker build -f linkerd_agent/Dockerfile -t todea-linkerd-agent:local .
# Run locally:
#   docker run --rm -p 3800:3800 todea-linkerd-agent:local

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
    curl --proto '=https' --tlsv1.2 -sSfL https://enterprise.buoyant.io/install | sh && \
    mv /root/.linkerd2/bin/linkerd /usr/local/bin/linkerd && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY linkerd_agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY linkerd_agent/app.py .
COPY linkerd_agent/config.py .
COPY linkerd_agent/schemas.py .
COPY linkerd_agent/tools.py .
COPY linkerd_agent/instructions.py .
COPY linkerd_agent/__init__.py .
COPY linkerd_agent/routes ./routes
COPY openssl_agent ./openssl_agent

ENV PORT=3800

EXPOSE 3800
CMD ["python", "app.py"]
