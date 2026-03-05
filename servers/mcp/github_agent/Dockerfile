# Container image for the GitHub Agent
#
# Build:
#   docker build -t todea-github-agent:local ./servers/mcp/github_agent
# Run locally:
#   docker run --rm -p 3600:3600 todea-github-agent:local

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY config.py .
COPY tools.py .
COPY __init__.py .
COPY routes ./routes

ENV PORT=3600

EXPOSE 3600
CMD ["python", "app.py"]
