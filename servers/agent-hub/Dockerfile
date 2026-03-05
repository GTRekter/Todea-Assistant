# Container image for the unified Hub (Google / Ollama / Azure)
#
# Build locally:
#   docker build -t todea-agent-hub:local ./servers/agent-hub
# Run locally:
#   docker run --rm -p 3100:3100 todea-agent-hub:local

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=3100

# Install kubectl
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
    curl -LO "https://dl.k8s.io/release/$(curl -Ls https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
    install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl && \
    rm kubectl && \
    apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

EXPOSE 3100

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "3100"]
