# Container image for the MCP server
#
# Build locally:
#   docker build -t todea-mcp:local ./servers/mcp
# Run locally:
#   docker run --rm -p 3002:3002 todea-mcp:local

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install kubectl and Linkerd Enterprise CLI
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
    KUBECTL_VERSION=$(curl -sL https://dl.k8s.io/release/stable.txt) && \
    curl -sLO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" && \
    chmod +x kubectl && mv kubectl /usr/local/bin/kubectl && \
    curl --proto '=https' --tlsv1.2 -sSfL https://enterprise.buoyant.io/install | sh && \
    mv /root/.linkerd2/bin/linkerd /usr/local/bin/linkerd && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./app.py
COPY config.py ./config.py
COPY agent.py ./agent.py
COPY tools.py ./tools.py
COPY http_utils.py ./http_utils.py
COPY linkerd_agent ./linkerd_agent
COPY openssl_agent ./openssl_agent
COPY kubernetes_agent ./kubernetes_agent
COPY github_agent ./github_agent

ENV MCP_PORT=3002

EXPOSE 3002
CMD ["python", "app.py"]
