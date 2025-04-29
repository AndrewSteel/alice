FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

# Architektur-Variablen & Versionsangabe
ARG TARGETARCH
ARG TARGETVARIANT
ARG WYOMING_WHISPER_VERSION='2.4.0'

# 1. System-Pakete installieren (inkl. venv)  
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential \
        python3 \
        python3-venv \
        python3-dev \
        python3-pip; \
    \
    # 2. Virtual Environment anlegen  
    python3 -m venv /opt/venv; \
    \
    # 3. Pip & Co. im venv aktualisieren  
    /opt/venv/bin/pip install --no-cache-dir -U pip setuptools wheel hf_xet; \
    \
    # 4. Wyoming-Faster-Whisper installieren  
    /opt/venv/bin/pip install --no-cache-dir \
        --extra-index-url https://www.piwheels.org/simple \
        "wyoming-faster-whisper @ https://github.com/rhasspy/wyoming-faster-whisper/archive/refs/tags/v${WYOMING_WHISPER_VERSION}.tar.gz"; \
    \
    # 5. Nicht mehr benötigte Build-Tools entfernen  
    apt-get purge -y --auto-remove \
        build-essential \
        python3-dev; \
    rm -rf /var/lib/apt/lists/*

# 6. venv ins PATH aufnehmen, damit python & pip standardmäßig aus /opt/venv kommen  
ENV PATH="/opt/venv/bin:$PATH"

# Arbeitsverzeichnis und Startskript
WORKDIR /usr/src
COPY run.sh .

# Ports und Start
EXPOSE 10300
ENTRYPOINT ["bash", "run.sh"]
