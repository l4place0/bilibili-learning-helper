FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies (cached layer)
COPY pyproject.toml .
RUN uv pip install --system --no-cache .

COPY . .

RUN mkdir -p data/cache/audio data/cache/transcripts

# Pre-download Whisper model (avoids first-run download delay)
ARG WHISPER_MODEL=medium
RUN python3 -c "import whisper; whisper.load_model('${WHISPER_MODEL}')"

EXPOSE 8000

RUN useradd -m -r appuser && chown -R appuser:appuser /app
USER appuser

CMD ["uvicorn", "core.main:app", "--host", "0.0.0.0", "--port", "8000"]
