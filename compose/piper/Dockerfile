FROM debian:stable-slim

# Versionen
ARG WYOMING_PIPER_VERSION='1.5.2'
ARG BINARY_PIPER_VERSION='2023.11.14-2'

# 1. System-Basispakete installieren und venv anlegen
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        curl \
        python3 \
        python3-venv \
        python3-pip; \
    \
    # 2. Virtual Environment erstellen
    python3 -m venv /opt/venv; \
    \
    # 3. Pip/Setuptools/Wheel im venv aktuell halten
    /opt/venv/bin/pip install --no-cache-dir -U pip setuptools wheel; \
    \
    # 4. Deine Python-Bibliothek drin installieren
    /opt/venv/bin/pip install --no-cache-dir \
        "wyoming-piper @ https://github.com/rhasspy/wyoming-piper/archive/refs/tags/v${WYOMING_PIPER_VERSION}.tar.gz"; \
    \
    # 5. Binaries von Piper ausrollen
    curl -L "https://github.com/rhasspy/piper/releases/download/v${BINARY_PIPER_VERSION}/piper_linux_x86_64.tar.gz" \
        | tar -zxvf - -C /usr/share; \
    \
    # 6. Cleanup
    rm -rf /var/lib/apt/lists/*

# 7. venv in den PATH bringen, damit python & pip standardmäßig aus /opt/venv kommen
ENV PATH="/opt/venv/bin:$PATH"

# Arbeitsverzeichnis und Startskript
WORKDIR /usr/src
COPY run.sh .

EXPOSE 10200

ENTRYPOINT ["bash", "run.sh"]
