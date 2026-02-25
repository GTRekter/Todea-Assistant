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

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py ./server.py
COPY http_utils.py ./http_utils.py
COPY linkerd_agent ./linkerd_agent

ENV MCP_PORT=3002

EXPOSE 3002
CMD ["python", "server.py"]
