# alice-speech-gateway — STT (faster-whisper, CUDA) + sentence-streaming TTS pipeline.
# Replaces wyoming-whisper; inherits the TITAN X GPU and port 10300.
FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

# faster-whisper needs cuDNN 9 (provided by the -cudnn- base image) and ffmpeg
# for audio decoding of arbitrary WebApp uploads.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        python3-pip \
        python3-dev \
        ffmpeg \
        build-essential; \
    rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:$PATH"
RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir -U pip setuptools wheel

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# 10300 = Wyoming (HA Voice Devices), 10301 = WebSocket (WebApp via nginx)
EXPOSE 10300 10301

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "10301"]
