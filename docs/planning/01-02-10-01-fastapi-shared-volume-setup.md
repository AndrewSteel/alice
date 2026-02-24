# Feinkonzept Phase 1.2.10 - FastAPI Container mit Shared Volume für n8n

## Dokumentstatus

| Attribut | Wert |
| :-------- | :---- |
| **Dokumenttyp** | Feinkonzept |
| **Phase** | 1.2.10 |
| **Version** | 1.0 |
| **Status** | Entwurf |
| **Basiert auf** | Feinkonzept v1.2 |
| **Repository** | <https://github.com/AndrewSteel/alice> |

---

## Übersicht

Dieses Dokument beschreibt das Setup eines Python-basierten FastAPI-Containers, der über ein Shared Volume mit n8n kommuniziert. Dies ermöglicht effizienten Datenaustausch, besonders bei großen Datenmengen.

## Shared Volume Konzept

Beide Container (n8n und FastAPI) mounten das gleiche Host-Verzeichnis:
- **Host-Pfad**: `/srv/warm/n8n/inbox`
- **Container-Pfad**: `/data_inbox`

Dies ermöglicht schnellen Datenaustausch ohne Netzwerk-Overhead.

---

## Docker Compose Konfiguration

### FastAPI Container Setup

```yaml
version: '3.8'

services:
  fastapi-processor:
    build: .
    container_name: fastapi-processor
    restart: unless-stopped
    ports:
      - "8000:8000"  # oder einen anderen freien Port
    volumes:
      - /srv/warm/n8n/inbox:/data_inbox  # Gleiches Host-Verzeichnis!
      - ./app:/app  # Für Code-Updates ohne Rebuild
    environment:
      - DATA_INBOX_PATH=/data_inbox
      - PYTHONUNBUFFERED=1
    networks:
      - n8n_network  # Optional: gleiches Netzwerk wie n8n

networks:
  n8n_network:
    external: true  # Falls du ein bestehendes n8n-Netzwerk nutzt
```

---

## FastAPI Implementierung

### Hauptanwendung (app/main.py)

```python
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from pathlib import Path
import json
from typing import Optional
import uuid

app = FastAPI(title="Data Processor API")

DATA_INBOX = Path("/data_inbox")

class ProcessRequest(BaseModel):
    input_file: str  # Dateiname im shared volume
    operation: str
    params: Optional[dict] = {}

class ProcessResponse(BaseModel):
    job_id: str
    status: str
    output_file: Optional[str] = None

@app.post("/process", response_model=ProcessResponse)
async def process_data(request: ProcessRequest, background_tasks: BackgroundTasks):
    """
    Liest Daten aus shared volume, verarbeitet sie, schreibt Ergebnis zurück
    """
    job_id = str(uuid.uuid4())
    input_path = DATA_INBOX / request.input_file
    
    if not input_path.exists():
        raise HTTPException(status_code=404, detail=f"Input file not found: {request.input_file}")
    
    output_file = f"{job_id}_result.json"
    
    # Asynchrone Verarbeitung im Hintergrund
    background_tasks.add_task(
        process_file,
        input_path=input_path,
        output_file=output_file,
        operation=request.operation,
        params=request.params
    )
    
    return ProcessResponse(
        job_id=job_id,
        status="processing",
        output_file=output_file
    )

def process_file(input_path: Path, output_file: str, operation: str, params: dict):
    """Deine eigentliche Verarbeitungslogik"""
    try:
        # Daten laden
        with open(input_path, 'r') as f:
            data = json.load(f)
        
        # Verarbeitung (Beispiel)
        result = perform_operation(data, operation, params)
        
        # Ergebnis speichern
        output_path = DATA_INBOX / output_file
        with open(output_path, 'w') as f:
            json.dump(result, f, indent=2)
            
    except Exception as e:
        # Error handling - könnte auch in eine error-Datei geschrieben werden
        error_file = DATA_INBOX / f"{output_file}.error"
        error_file.write_text(str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy", "inbox_accessible": DATA_INBOX.exists()}
```

---

## n8n Workflow Integration

### Beispiel-Code für n8n Execute Command Node

```javascript
// 1. Große Daten in shared volume schreiben
const inputFile = `input_${Date.now()}.json`;
const fs = require('fs');
fs.writeFileSync(`/data_inbox/${inputFile}`, JSON.stringify($input.all()));

// 2. FastAPI aufrufen
const response = await $http.request({
  url: 'http://fastapi-processor:8000/process',
  method: 'POST',
  body: {
    input_file: inputFile,
    operation: 'transform',
    params: { /* deine Parameter */ }
  }
});

// 3. Ergebnis aus shared volume lesen (nach Verarbeitung)
const resultData = JSON.parse(
  fs.readFileSync(`/data_inbox/${response.output_file}`, 'utf8')
);

return resultData;
```

---

## Vergleich: Shared Volume vs. JSON-API

### Shared Volume (empfohlen für große Daten)

**Vorteile:**
- ✅ Sehr schnell für große Datenmengen (keine Netzwerk-Serialisierung)
- ✅ Keine Größenbeschränkungen durch HTTP
- ✅ Einfaches Error Handling über `.error` Files

**Nachteile:**
- ⚠️ Cleanup-Strategie notwendig (alte Dateien löschen)

### JSON-API (besser für kleine Daten)

**Vorteile:**
- ✅ Sauberes RESTful Design
- ✅ Einfacher zu debuggen
- ✅ Kann auch von außerhalb Docker genutzt werden

**Nachteile:**
- ⚠️ Payload-Limits bei sehr großen Daten

---

## Hybrid-Ansatz (Best of Both)

Kombiniere beide Methoden für maximale Flexibilität:

```python
@app.post("/process-inline")
async def process_inline(data: dict):
    """Für kleine Datenmengen: direkt JSON"""
    result = perform_operation(data, "transform", {})
    return {"result": result}

@app.post("/process-file")
async def process_file_based(request: ProcessRequest):
    """Für große Datenmengen: shared volume"""
    # Implementierung wie oben
    pass
```

### Entscheidungsmatrix

| Datengröße | Empfohlene Methode | Endpoint |
|------------|-------------------|----------|
| < 1 MB | JSON-API | `/process-inline` |
| > 1 MB | Shared Volume | `/process-file` |
| Streaming | Shared Volume | `/process-file` |

---

## Projekt-Struktur

```
fastapi-processor/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── processors/
│   │   ├── __init__.py
│   │   └── operations.py
│   └── utils/
│       ├── __init__.py
│       └── cleanup.py
└── README.md
```

---

## Dockerfile Beispiel

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app /app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

---

## requirements.txt

```txt
fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.0
```

---

## Nächste Schritte

1. **Cleanup-Strategie implementieren** für alte Dateien im shared volume
2. **Monitoring hinzufügen** (z.B. Prometheus metrics)
3. **Logging verbessern** für bessere Fehleranalyse
4. **Rate Limiting** für API-Schutz
5. **Authentifizierung** wenn extern erreichbar

---

## Troubleshooting

### Problem: Container kann nicht auf shared volume zugreifen

**Lösung:** Prüfe Berechtigungen auf Host:
```bash
sudo chown -R 1000:1000 /srv/warm/n8n/inbox
sudo chmod -R 755 /srv/warm/n8n/inbox
```

### Problem: n8n findet FastAPI-Service nicht

**Lösung:** Stelle sicher, dass beide Container im gleichen Docker-Netzwerk sind:
```bash
docker network inspect n8n_network
```

### Problem: Dateien werden nicht gefunden

**Lösung:** Prüfe, ob Pfade in beiden Containern übereinstimmen:
```bash
# Im n8n Container
docker exec n8n ls -la /data_inbox

# Im FastAPI Container
docker exec fastapi-processor ls -la /data_inbox
```

---

## Lizenz & Autor

- **Erstellt für**: Andreas' KI-First Smart Home Setup
- **Datum**: Februar 2026
- **Version**: 1.0
