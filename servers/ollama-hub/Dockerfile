# Container image for the Ollama Hub chat gateway
#
# Build locally:
#   docker build -t todea-ollama-hub:local ./servers/ollama-hub
# Run locally (requires an accessible Ollama server):
#   docker run --rm -p 3200:3200 -e OLLAMA_HOST=http://host.docker.internal:11434 todea-ollama-hub:local

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=3200

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

EXPOSE 3200

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "3200"]
