# Custom Ollama runtime image with the model pre-baked.
# Build and import into k3d so the model is on disk at container start — no pull delay.
#
# Build:
#   docker build -t todea-ollama-runtime:local ./servers/ollama-runtime
# Import into k3d:
#   k3d image import todea-ollama-runtime:local -c <cluster-name>

ARG MODEL=llama3.1:8b

FROM ollama/ollama:latest

ARG MODEL
ENV MODEL=${MODEL}

# Start the Ollama server in the background, pull the model, then shut down.
# The model weights end up in /root/.ollama/models and are baked into this layer.
RUN ollama serve & \
    OLLAMA_PID=$! && \
    echo "Waiting for Ollama to be ready..." && \
    until ollama list > /dev/null 2>&1; do sleep 1; done && \
    echo "Pulling model ${MODEL}..." && \
    ollama pull ${MODEL} && \
    echo "Model pulled. Shutting down." && \
    kill $OLLAMA_PID && \
    wait $OLLAMA_PID 2>/dev/null || true
