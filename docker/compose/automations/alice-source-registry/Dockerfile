FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Empty repo folder for the container test (no NAS). In production the own share is
# mounted over /mnt/nas/sot and hides it: if the share is missing, the folder is
# missing too and the service never creates a fresh repo. Writable for the non-root
# NAS account the service runs as.
RUN mkdir -p /mnt/nas/sot/source-of-truth && chmod 0777 /mnt/nas/sot/source-of-truth

# git needs a writable HOME when running as an account without passwd entry
ENV HOME=/tmp

# tini as PID 1 reaps orphaned children (detached git background processes would
# otherwise stay as zombies under uvicorn).
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8012"]
