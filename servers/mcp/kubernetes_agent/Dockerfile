# Container image for the Kubernetes Agent
#
# Build:
#   docker build -t todea-kubernetes-agent:local ./servers/mcp/kubernetes_agent
# Run locally:
#   docker run --rm -p 3700:3700 todea-kubernetes-agent:local

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
    KUBECTL_VERSION=$(curl -sL https://dl.k8s.io/release/stable.txt) && \
    curl -sLO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" && \
    chmod +x kubectl && mv kubectl /usr/local/bin/kubectl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY config.py .
COPY tools.py .
COPY instructions.py .
COPY __init__.py .
COPY routes ./routes

ENV PORT=3700

EXPOSE 3700
CMD ["python", "app.py"]
