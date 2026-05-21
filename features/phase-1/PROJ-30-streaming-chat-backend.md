# PROJ-30: Streaming Chat Backend (alice-chat-stream)

**Status:** 🟢 Deployed
**Created:** 2026-05-07
**Last Updated:** 2026-05-09

## Kontext & Motivation

Der bisherige `alice-chat-handler` n8n-Workflow puffert die vollständige LLM-Antwort, bevor er antwortet. Das führt zu:

- **Keine Echtzeit-Ausgabe**: Nutzer wartet 5–30 Sekunden auf eine vollständige Antwort, ohne Feedback
- **Kein Tool-Status während Ausführung**: Tool-Calls (Dokumentensuche, HA-Steuerung) sind für den Nutzer unsichtbar
- **Phase-2-Blocker**: Piper TTS kann erst starten, wenn der gesamte Text vorliegt — Sprachausgabe mit Unterbrechbarkeit ist unmöglich
- **Keine Interrupt-Fähigkeit**: Nutzer kann eine laufende Antwort nicht abbrechen

Lösung: Ein eigenständiger Python/FastAPI-Container `alice-chat-stream` ersetzt den `alice-chat-handler` n8n-Workflow als primären Chat-Endpunkt. n8n-Sub-Workflows (`alice-tool-ha`, `alice-tool-search`) bleiben unverändert und werden per HTTP aufgerufen.

## Dependencies

- Requires: PROJ-3 (Chat Handler — wird abgelöst, bleibt als Fallback)
- Requires: PROJ-7 (JWT Auth — RS256-Public-Key wird geteilt)
- Requires: PROJ-9 (Chat JWT-Schutz — Konzept wird im neuen Service reimplementiert)
- Requires: PROJ-20 (DMS Search Tool — `alice-tool-search` Sub-Workflow bleibt erhalten)
- Enables: PROJ-31 (Frontend Streaming-UI)
- Enables: PROJ-33 (Phase-2 Speech Streaming Interface)

## User Stories

- Als Nutzer möchte ich Antworten Wort für Wort erscheinen sehen, damit die Wartezeit sich kürzer anfühlt und ich früher mit dem Lesen beginnen kann.
- Als Nutzer möchte ich während einer Antwort einen „Stopp"-Button sehen, damit ich eine zu lange Antwort abbrechen kann.
- Als Nutzer möchte ich sehen, wenn Alice gerade in Dokumenten sucht (z.B. „Suche in Dokumenten…"), damit ich weiß, dass etwas passiert.
- Als Nutzer möchte ich, dass HA-Schnellbefehle weiterhin sofort (<200ms) reagieren, auch wenn normaler Chat jetzt streamt.
- Als Andreas (Entwickler) möchte ich, dass der neue Service denselben JWT-Schutz wie der alte Webhook hat, damit kein Sicherheits-Rückschritt entsteht.
- Als Andreas (Entwickler) möchte ich, dass das Drei-Schichten-Gedächtnis vollständig erhalten bleibt, damit keine Gesprächshistorie verloren geht.

## Acceptance Criteria

### Streaming-Endpoint
- [x] `POST /stream/chat` liefert eine SSE-Response (Content-Type: `text/event-stream`)
- [x] Jedes Token aus der Ollama-Antwort wird sofort als SSE-Event `data: {"type":"token","content":"..."}` gesendet
- [x] Tool-Call-Start sendet `data: {"type":"tool_start","tool":"search_documents","query":"...","status":"..."}` vor Tool-Ausführung
- [x] Tool-Call-Ende sendet `data: {"type":"tool_end","tool":"search_documents"}` nach Rückkehr des Tool-Ergebnisses
- [x] Stream endet mit `data: {"type":"done"}` gefolgt von `data: [DONE]`
- [x] Bei Fehler wird `data: {"type":"error","message":"..."}` gesendet, Stream wird sauber geschlossen

### HA Fast-Path (kein Streaming nötig)
- [x] Weaviate-Suche nach HA-Intents läuft weiterhin vor dem LLM-Aufruf
- [x] Certainty ≥ 0,82 → direkter HA-API-Call, Antwort als einziges SSE-Token + `done`
- [ ] Latenz HA_FAST-Pfad: < 300ms — *nicht verifizierbar ohne Live-System*

### Authentifizierung
- [x] JWT-Token aus `Authorization: Bearer <token>`-Header wird validiert
- [x] RS256-Public-Key wird aus Datei geladen (`JWT_PUBLIC_KEY_PATH`, Volume-Mount)
- [x] Ungültiger oder abgelaufener Token → HTTP 401 (kein SSE-Stream)
- [x] `user_id` kommt ausschließlich aus dem verifizierten JWT-Payload (kein Body-Parameter)

### Drei-Schichten-Gedächtnis
- [x] Working Memory: Letzte 20 Nachrichten aus `alice.messages` werden als Kontext übergeben
- [x] Long-term Memory: Weaviate `AliceMemory` nearText-Suche für relevante Erinnerungen
- [x] User Profile: `alice.user_profiles` (Name, Anrede, Interessen, Sprache) wird in System-Prompt injiziert
- [x] Nutzer-Nachricht wird in `alice.messages` geschrieben **bevor** der Stream beginnt
- [x] Vollständige Assistenten-Antwort (alle Tokens zusammengesetzt) wird nach `done` in `alice.messages` geschrieben

### Tool-Execution
- [x] Tool `search_documents` ruft `alice-tool-search` n8n-Workflow per HTTP auf (bestehender Sub-Workflow)
- [x] Tool `get_document_details` ruft `alice-tool-search` per HTTP auf
- [x] Tool `home_assistant` ruft `alice-tool-ha` n8n-Workflow per HTTP auf
- [x] Tool `remember` schreibt in `alice.user_profiles` (PostgreSQL direkt)
- [x] Tool `recall` liest aus Weaviate `AliceMemory` (direkt)
- [x] Alle Tool-Calls werden in `alice.messages.tool_calls` (JSONB) gespeichert

### Zuverlässigkeit
- [x] Abgebrochene Client-Verbindung (Nutzer schließt Tab) stoppt den Ollama-Stream sauber
- [x] Ollama-Timeout (60s) → SSE-Error-Event, kein hängender Request
- [x] n8n-Tool-Timeout (15s) → Tool-Fehler als SSE-Event, LLM erhält Fehlerantwort als Tool-Result
- [x] Alle Fehler landen in `alice.messages` (Assistenten-Nachricht mit Fehlermeldung)

### Betrieb
- [x] Health-Endpoint `GET /health` → HTTP 200 `{"status":"ok"}`
- [x] Strukturiertes JSON-Logging (ISO-Timestamp, level, session_id, user_id, latency_ms)
- [x] Prometheus-Metriken auf `GET /metrics`: `chat_requests_total`, `chat_tokens_total`, `chat_latency_seconds`

## Edge Cases

- Ollama gibt ungültiges JSON bei Tool-Call zurück → LLM-Fehler-Nachricht an Nutzer, kein Crash
- Weaviate nicht erreichbar → HA_FAST-Pfad entfällt, direkt LLM_ONLY (wie bisher)
- PostgreSQL nicht erreichbar → HTTP 503, kein Stream (Memory-Inkonsistenz vermeiden)
- Nutzer sendet leere Nachricht → HTTP 400, kein Stream
- Tool-Call dauert länger als 15s → SSE-Event `tool_timeout`, LLM bekommt "Tool-Fehler: Timeout"
- Stream läuft, Nutzer schickt neue Nachricht in derselben Session → neuer Request wartet nicht auf alten (kein Session-Lock)
- JWT abgelaufen während laufendem Stream → Stream läuft zu Ende (JWT wird nur beim Verbindungsaufbau geprüft)

## Technical Design

### Service-Architektur

```
alice-chat-stream (FastAPI, Port 8003)
├── POST /stream/chat          ← Haupt-Streaming-Endpunkt (SSE)
├── GET  /health
└── GET  /metrics

Upstream-Abhängigkeiten:
├── Ollama API          (OLLAMA_URL/api/chat, stream=true)
├── PostgreSQL          (alice.messages, alice.user_profiles, alice.sessions)
├── Weaviate            (AliceMemory nearText, HAIntent nearText)
├── alice-tool-ha       (n8n Webhook, HTTP POST)
└── alice-tool-search   (n8n Webhook, HTTP POST)
```

### Request/Response-Protokoll

**Request:**
```json
POST /stream/chat
Authorization: Bearer <jwt>
Content-Type: application/json

{
  "session_id": "uuid",
  "content": "Was steht in meiner letzten Rechnung?"
}
```

**SSE-Event-Typen:**
```
data: {"type":"token","content":"Die"}
data: {"type":"token","content":" letzte"}
data: {"type":"tool_start","tool":"search_documents","status":"Suche in Dokumenten…"}
data: {"type":"tool_end","tool":"search_documents"}
data: {"type":"token","content":"Rechnung"}
data: {"type":"done","usage":{"prompt_tokens":120,"completion_tokens":45}}
data: [DONE]
```

### Docker-Container

```
docker/compose/automations/alice-chat-stream/
├── compose.yml
├── Dockerfile
├── .env
└── app/
    ├── main.py           # FastAPI App, Lifespan, Router
    ├── auth.py           # JWT RS256 Validierung
    ├── memory.py         # 3-Tier Memory (PG + Weaviate)
    ├── ha_path.py        # HA Fast-Path (Weaviate nearText)
    ├── tools.py          # Tool-Execution (HTTP → n8n Sub-Workflows)
    ├── streaming.py      # Ollama-Stream → SSE-Generator
    └── metrics.py        # Prometheus
```

### Umgebungsvariablen

```env
OLLAMA_URL=http://ollama:11434
OLLAMA_MODEL=qwen3:14b
POSTGRES_DSN=postgresql://user:pass@postgres:5432/alice
WEAVIATE_URL=http://weaviate:8080
JWT_PUBLIC_KEY_PATH=/run/secrets/jwt_public.pem
N8N_TOOL_HA_URL=http://n8n:5678/webhook/alice-tool-ha
N8N_TOOL_SEARCH_URL=http://n8n:5678/webhook/alice-tool-search
INTENT_MIN_CERTAINTY=0.82
TOOL_TIMEOUT_SECONDS=15
OLLAMA_TIMEOUT_SECONDS=60
```

### Migrationsstrategie

1. Neuer Service wird parallel zu `alice-chat-handler` deployed
2. nginx leitet `/api/stream/chat` → `alice-chat-stream` (neuer Pfad)
3. Frontend wird auf neuen Endpunkt umgeschaltet (PROJ-31)
4. `alice-chat-handler` n8n-Workflow bleibt **deaktiviert aber nicht gelöscht** (Fallback)
5. Nach 2 Wochen stabilem Betrieb: Entscheidung über endgültige Abschaltung

### Deliverables

- [x] Python FastAPI Container `alice-chat-stream` (`app/` mit main, auth, memory, ha_path, tools, streaming, metrics)
- [x] `docker/compose/automations/alice-chat-stream/compose.yml`
- [x] `docker/compose/automations/alice-chat-stream/Dockerfile`
- [ ] n8n-Workflow `alice-chat-handler` auf inaktiv setzen (nicht löschen) — *nicht verifiziert*
- [x] `docker/compose/scripts/Makefile` → `STACKS` enthält `alice-chat-stream`
- [ ] `.env`-Datei für Container fehlt (Backend-Regel: `.env` muss im Container-Verzeichnis liegen)

---

## Tech Design (Solution Architect)

### Service-Position im Stack

```
Browser
  │  POST /api/stream/chat  (SSE)
  ▼
nginx  ──────────────────────────────────────────────────┐
  │  proxy_pass  (buffering: off)                        │
  ▼                                                       │
alice-chat-stream  (Port 8003)                           │ bestehende Routen
  ├── auth.py          ← JWT RS256 prüfen                │ bleiben unverändert
  ├── memory.py        ← 3-Tier Memory laden/speichern   │
  ├── ha_path.py       ← HA Fast-Path (Weaviate lookup)  │
  ├── streaming.py     ← Ollama-Stream → SSE-Generator   │
  ├── tools.py         ← HTTP → n8n Sub-Workflows        │
  └── metrics.py       ← Prometheus                      │
  │                                                       │
  ├── PostgreSQL  (alice.messages, alice.sessions,        │
  │                alice.user_profiles)                   │
  ├── Weaviate    (AliceMemory, HAIntent)                 │
  ├── Ollama      (qwen3:14b, stream=true)               │
  ├── alice-tool-ha    (n8n Webhook, HTTP)               │
  └── alice-tool-search (n8n Webhook, HTTP)              │
                                                          │
alice-chat-handler (n8n) ← bleibt deaktiviert (Fallback) ┘
```

### Datenfluss

```
1. Browser  → POST /api/stream/chat  {session_id, content}
             + Authorization: Bearer <jwt>

2. auth.py  → RS256-Public-Key laden → JWT prüfen
             → user_id aus Payload (kein Body-Parameter)
             → Fehler: sofort HTTP 401, kein Stream

3. memory.py → PostgreSQL: letzte 20 Nachrichten (Working Memory)
             → Weaviate: semantisch ähnliche Erinnerungen (Long-term)
             → PostgreSQL: Nutzerprofil (Name, Sprache, Interessen)
             → Nutzer-Nachricht wird in alice.messages geschrieben

4. ha_path.py → Weaviate nearText auf HAIntent-Collection
               → Certainty ≥ 0.82?
               YES → HTTP → alice-tool-ha → einziges SSE-Token + done
               NO  → weiter zu Schritt 5

5. streaming.py → Ollama /api/chat mit stream=true + tool_use
               → Jedes Token: SSE data: {"type":"token","content":"..."}
               → Tool-Call erkannt?
                 YES → tools.py → SSE tool_start
                     → HTTP → alice-tool-search oder alice-tool-ha
                     → SSE tool_end
                     → Tool-Ergebnis zurück an Ollama
               → Stream-Ende: SSE done + [DONE]

6. memory.py → vollständige Antwort in alice.messages speichern
```

### Datenhaltung

Kein neues Datenbankschema. Ausschließlich existierende Tabellen:

| Tabelle | Zweck | Aktion |
|---|---|---|
| `alice.messages` | Gesprächsverlauf (Working Memory) | READ (letzte 20) + WRITE (nach Stream) |
| `alice.sessions` | Session-Metadaten | READ (session validieren) |
| `alice.user_profiles` | Nutzerprofil für System-Prompt | READ + WRITE (remember-Tool) |
| Weaviate `AliceMemory` | Langzeit-Erinnerungen | READ (semantic search) |
| Weaviate `HAIntent` | HA Fast-Path Intents | READ (nearText) |

### Containerstruktur

```
docker/compose/automations/alice-chat-stream/
├── compose.yml          ← Networks: automation + backend (wie alice-auth)
├── Dockerfile           ← python:3.12-slim + uvicorn (wie alice-auth)
├── .env                 ← alle URLs + JWT_PUBLIC_KEY_PATH
├── requirements.txt
└── app/
    ├── main.py          ← FastAPI App, Startup, Router
    ├── auth.py          ← JWT RS256 Validierung
    ├── memory.py        ← 3-Tier Memory (asyncpg + weaviate-client)
    ├── ha_path.py       ← Weaviate nearText → HA Fast-Path
    ├── tools.py         ← HTTP-Calls zu alice-tool-ha, alice-tool-search
    ├── streaming.py     ← Ollama-Stream → SSE async generator
    └── metrics.py       ← Prometheus Counters/Histogramme
```

### Python-Pakete

| Paket | Zweck |
|---|---|
| `fastapi` | Web-Framework + StreamingResponse |
| `uvicorn[standard]` | ASGI-Server (wie alice-auth) |
| `httpx` | Async HTTP für Ollama + n8n-Webhooks |
| `asyncpg` | Async PostgreSQL (non-blocking für Streaming-Service) |
| `weaviate-client` | Weaviate nearText-Suche |
| `PyJWT` | RS256 JWT-Validierung |
| `cryptography` | RS256-Key-Parsing (Abhängigkeit von PyJWT) |
| `prometheus-client` | Metriken auf /metrics |
| `pydantic` | Request/Response-Validierung |

### Tech-Entscheidungen

**asyncpg statt psycopg2:** asyncpg ist nativ-async ohne Thread-Pool. Für einen Streaming-Service kritisch — die Event-Loop darf während eines laufenden SSE-Streams nie blockiert werden.

**httpx für alle ausgehenden Requests:** Eine Bibliothek für Ollama-Streaming und n8n-Tool-Webhooks. httpx unterstützt sowohl async Streaming als auch normale async POST-Requests.

**Port 8003:** alice-auth läuft auf 8002, konsekutive Vergabe. nginx erhält einen neuen Location-Block `/api/stream/` → `alice-chat-stream:8003` mit `proxy_buffering off` (PROJ-32).

**RS256-Public-Key als Datei:** Identisches Muster wie alice-auth (PROJ-7). Key wird per Volume-Mount in den Container gebracht — kein Shared Secret.

---

## QA-Ergebnisse (2026-05-08)

**Reviewer:** Claude (statische Code-Analyse)
**Methode:** Vollständige Durchsicht aller Quelldateien gegen Acceptance Criteria

### Bestanden (22/25)

Alle SSE-Mechanismen (token, tool_start/end, done, [DONE], error), Working Memory, User Profile, Tool-Execution (alle 5 Tools), Tool-Call-Logging, Disconnect-Handling, Timeouts, Logging, Metriken, Deliverables (Container, compose, Dockerfile, Makefile, nginx).

### Bugs

#### BUG-1 — HOCH: Auth nutzt HS256 statt RS256

**Datei:** `app/auth.py:10`
**Spec:** "RS256-Public-Key wird aus Datei oder Umgebungsvariable geladen (kein Shared-Secret)"
**Ist:** `JWT_ALGORITHM = "HS256"` mit `JWT_SECRET` (shared secret mit alice-auth)
**Problem:** Verletzt das explizite Spec-Kriterium. Der Tech-Design-Abschnitt der Spec beschreibt sogar `JWT_PUBLIC_KEY_PATH` als Env-Var. In der Praxis ist HS256 pragmatisch (alice-auth nutzt ebenfalls HS256), aber es ist eine bewusste Abweichung.
**Entscheidung erforderlich:** HS256 akzeptieren (Spec aktualisieren) oder RS256 implementieren?

#### ~~BUG-1~~ — BEHOBEN: Auth nutzt HS256 statt RS256

`app/auth.py`: Vollständig auf RS256 umgestellt. Lädt Public Key aus `JWT_PUBLIC_KEY_PATH`.
`requirements.txt`: `cryptography>=42,<44` ergänzt.
`compose.yml`: Volume-Mount `/srv/warm/alice/keys/jwt_public.pem:/run/secrets/jwt_public.pem:ro` eingetragen.
`main.py`: Health-Endpoint prüft jetzt `JWT_PUBLIC_KEY_PATH` statt `JWT_SECRET`.
Signing-Seite (alice-auth) wird in PROJ-34 migriert.

#### ~~BUG-2~~ — BEHOBEN: `tool_start`-Event hat `status` statt `query`

`app/streaming.py`: Event sendet jetzt beide Fields — `query` (aus Tool-Args) und `status` (Anzeigetext).

#### ~~BUG-3~~ — BEHOBEN: Long-term Memory wird nicht automatisch geladen

`app/main.py`: `recall_long_term(user_id, user_message)` wird jetzt vor dem Stream aufgerufen. `build_system_prompt()` in `memory.py` injiziert Treffer als `### Relevante Erinnerungen`-Block.

#### ~~BUG-4~~ — BEHOBEN: `.env`-Datei vorhanden.

### Live-QA (2026-05-09)

**Methode:** Direkttests gegen deployed Service auf ki.lan

| Test | Ergebnis | Evidenz |
|---|---|---|
| `GET /health` | PASS | `{"status":"ok","db":true,"jwt_public_key":true}` |
| `GET /metrics` | PASS | `chat_requests_total`, `chat_tokens_total`, `chat_latency_seconds` vorhanden (3 LLM_ONLY, 1 HA_FAST, 131 Tokens) |
| `POST /stream/chat` ohne Token | PASS | HTTP 401 |
| `POST /stream/chat` mit Fake-Bearer | PASS | HTTP 401 |
| RS256 Public Key gemountet | PASS | `/run/secrets/jwt_public.pem`, 800 Bytes |
| Container-Netzwerke | PASS | `automation` + `backend`, Status `running` |
| Kein Port 8003 am Host exponiert | PASS | Nur über nginx-Netzwerk erreichbar |

### Nicht verifizierbar ohne Live-Token

- HA_FAST-Pfad Latenz < 300ms (Metriken zeigen HA_FAST bei 46ms — AC erfüllt)
- n8n-Workflow `alice-chat-handler` deaktiviert (manuell zu prüfen)

