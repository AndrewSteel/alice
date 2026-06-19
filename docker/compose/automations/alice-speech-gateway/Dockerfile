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
# setuptools<81: starting with 81.0 the legacy `pkg_resources` module is no
# longer importable by default. webrtcvad 2.0.10 (unmaintained since 2017)
# still does `import pkg_resources` at module load, which would otherwise
# crash every BargeInController construction and take down /ws/voice.
RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir -U pip 'setuptools<81' wheel

WORKDIR /app

# Pin PyTorch to the last release that ships Maxwell (CC 5.2 / TITAN X) CUDA
# kernels. PyTorch >= 2.4 dropped SM 5.x; cu121 wheels run on any CUDA 12.x
# host. This must be installed BEFORE requirements.txt so pip does not upgrade
# it when resolving SpeechBrain's transitive torch dependency.
RUN pip install --no-cache-dir \
    "torch==2.3.1+cu121" \
    "torchaudio==2.3.1+cu121" \
    --index-url https://download.pytorch.org/whl/cu121

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# 10300 = Wyoming (HA Voice Devices), 10301 = WebSocket (WebApp via nginx)
EXPOSE 10300 10301

# --no-access-log: uvicorn's default access log writes the full request URI
# (including `?token=<JWT>` on WS handshakes) to stdout. The gateway emits
# its own structured JSON logs for session start/end/auth; suppressing the
# default access log keeps JWTs out of `docker logs`.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "10301", "--no-access-log"]
