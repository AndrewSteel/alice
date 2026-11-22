FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Default repo folder (container test without NAS). Writable for the non-root NAS
# account the service runs as; in production SOT_REPO_PATH points into the own share.
RUN mkdir -p /data/sot && chmod 0777 /data/sot

# git needs a writable HOME when running as an account without passwd entry
ENV HOME=/tmp

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8012"]
