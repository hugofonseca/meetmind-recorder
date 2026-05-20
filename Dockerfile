FROM python:3.11-slim

# System packages: Opus for voice capture, ffmpeg for audio compression
RUN apt-get update && apt-get install -y --no-install-recommends \
    libopus0 \
    libopus-dev \
    libffi-dev \
    libnacl-dev \
    python3-dev \
    gcc \
    git \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY .env* ./

# Persistent output directory for WAV files
RUN mkdir -p meeting_audio

# Non-root user for security
RUN useradd -m -u 1000 botuser && chown -R botuser:botuser /app
USER botuser

CMD ["python", "main.py"]
