# Container image for the Conversation Hub service
#
# Build locally:
#   docker build -t todea-conversation-hub:local ./servers/conversation-hub
# Run locally:
#   docker run --rm -p 3300:3300 todea-conversation-hub:local

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=3300

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

EXPOSE 3300

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "3300"]
