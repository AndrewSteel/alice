# Alice — Entwicklungsstand PROJ-1 bis PROJ-39

> **Stand:** 19. Mai 2026 · 38 von 39 Features im Status **Deployed** · 1 Feature **Planned** (PROJ-33)
>
> Dieses Dokument richtet sich an externe Stakeholder mit technischem Hintergrund, die sich einen vollständigen Überblick über den aktuellen Entwicklungsstand verschaffen möchten.

---

## 1. Systemarchitektur (Überblick)

Alice ist ein **local-first, AI-first Personal Assistant** mit Smart-Home-Integration. Der gesamte Stack läuft on-premise auf einem Heimserver und ist ausschließlich per VPN erreichbar.

```
CLIENT (React PWA · Home Assistant Voice Devices)
        ↓
nginx (Reverse Proxy · JWT-Auth · Rate-Limiting · SSE-Proxy)
        ↓
alice-chat-stream (FastAPI, SSE)   +   alice-auth (FastAPI, RS256)
        ↓
Ollama qwen3:14b  ←→  Weaviate (Vektor-DB)  ←→  PostgreSQL (alice-Schema)
        ↓
Home Assistant (Smart Home)  +  NAS (Dokumente)  +  MQTT  +  Redis
```

**Kernprinzip:** Ein einziger LLM-Aufruf mit native Tool-Use — kein zweistufiger Router. Das Sprachmodell entscheidet selbst, welches Tool es aufruft (`home_assistant`, `search_documents`, `get_document_details`, `remember`, `recall`). Seit PROJ-30 liefert der neue `alice-chat-stream`-Service Antworten token-weise als Server-Sent Events. Der frühere n8n-Chat-Handler ist deaktiviert (Fallback).

---

## 2. Entwicklungsphasen

| Phase     | Inhalt                                                          | Status          |
| --------- | --------------------------------------------------------------- | --------------- |
| Phase 0   | Hardware-Setup                                                  | ✅ Abgeschlossen |
| Phase 1   | Chat MVP (n8n + React + Home Assistant + DMS)                   | ✅ Abgeschlossen |
| Phase 1.5 | JWT-Authentifizierung + Login-Screen                            | ✅ Abgeschlossen |
| Phase 1.7 | Streaming-Backend, RS256-Migration, Chat-Redesign, HA-Sync Overhaul | ✅ Abgeschlossen |
| Phase 2   | Speech Gateway (Whisper STT + Piper TTS + Speaker-ID)           | Geplant (PROJ-33 vorbereitet) |
| Phase 3   | Multi-User, Display-Routing, Security Hardening                 | Geplant         |

---

## 3. Feature-Cluster

### 3.1 Home Assistant Intent Infrastructure (PROJ-1 bis PROJ-6, PROJ-11)

Dies ist die Grundlage der Smart-Home-Steuerung. Die Features bauen streng aufeinander auf.

#### PROJ-1 — HA Intent Infrastructure (Datenmodell)
Die **Datengrundlage** für alles, was mit Sprachbefehlen und Smart-Home zusammenhängt.

Neu erstellt:
- PostgreSQL-Tabellen `alice.ha_intent_templates` (Sprachbefehls-Vorlagen), `alice.ha_entities` (HA-Geräteregister), `alice.ha_sync_log` (Audit-Trail)
- Weaviate-Collection `HAIntent` — vektorisiert nur das `utterance`-Feld (z. B. „Küche hell machen"), alle anderen Felder als Filter-Metadaten

Designentscheidung: Nur der natürlichsprachliche Satz wird eingebettet. Das hält die Vektoren sauber und ermöglicht Schwellenwert-Filterung (Cosine-Similarität ≥ 0,82).

#### PROJ-2 — hassil-parser FastAPI Container
Ein dedizierter Python-Container, der die offiziellen Home Assistant Intent-Sätze von GitHub herunterlädt, die Hassil-Template-Syntax (z. B. `[bitte] {name} einschalten`) zu konkreten deutschen Äußerungen expandiert und sie in `alice.ha_intent_templates` schreibt.

- Endpoint `POST /intents/sync` → 55 Templates aus den offiziellen HA-Intent-Dateien importiert
- Max. 50 Muster pro Intent (konfigurierbar), um kombinatorische Explosion zu vermeiden
- Publiziert nach erfolgreichem Sync ein MQTT-Event `alice/ha/sync`, das den Entity-Sync auslöst

#### PROJ-3 — HA-First Chat Handler
Der n8n-Hauptworkflow `alice-chat-handler` (seit PROJ-30 deaktiviert, Fallback). Er entschied pro Nutzeranfrage, welchen Pfad er einschlägt:

1. **HA_FAST**: Weaviate-nearText-Suche findet einen Intent mit Certainty ≥ 0,82 → direkt zur HA REST API, ohne LLM
2. **HYBRID**: Weaviate findet Kandidaten, LLM wählt den besten aus
3. **LLM_ONLY**: Kein HA-Intent erkannt → LLM mit Tool-Use

#### PROJ-4 — HA Auto-Sync (MQTT → n8n → Weaviate)
Sobald ein neues HA-Gerät hinzukommt, sendet Home Assistant ein `ha_start`- oder `entity_created`-Event auf `alice/ha/sync`. Der Sync-Workflow verknüpfte jede Entität mit den passenden Intent-Templates und schrieb die expandierten Äußerungen in die `HAIntent`-Weaviate-Collection.

#### PROJ-5 + PROJ-6 — Hassil Library & Kompatibilitätsfix
PROJ-5 ersetzt den eigenen Regex-Parser durch die offizielle `hassil`-Bibliothek (v3.5+). PROJ-6 behebt eine Inkompatibilität zwischen HA-YAML-Expansion-Rules und der Library-API.

#### PROJ-11 — HA Sync Python Worker (Ablösung des n8n-Workflows)
Der Sync-Workflow wurde als eigenständigen **Python-Docker-Container** (`alice-ha-sync`) reimplementiert. Der Container:
- abonniert `alice/ha/sync` dauerhaft (persistente MQTT-Verbindung, exponential backoff)
- führt Full-Sync und inkrementellen Sync durch
- publiziert strukturiertes JSON auf `alice/system/ha-sync/info|warning|error`
- schreibt weiterhin in `alice.ha_sync_log` (PostgreSQL)

---

### 3.2 Authentication & Security (PROJ-7, PROJ-9, PROJ-12, PROJ-13)

#### PROJ-7 — JWT Auth / Login Screen
Ersetzt den Auto-Login-Modus durch echte Authentifizierung:

- Login-Screen mit Passwort-Formular (React)
- `alice-auth` FastAPI-Container (separat von n8n) für alle Auth-Operationen
- JWT-Token (RS256 seit PROJ-34), gespeichert in `localStorage`
- PostgreSQL-Tabellen: `alice.auth_sessions`, `alice.webauthn_challenges` (für Phase 2 vorbereitet)
- nginx leitet `/api/auth/*` an `alice-auth:8002`

#### PROJ-9 — Chat-Handler JWT-Schutz
Absicherung des Webhook-Endpunkts. JWT-Token wird im Authorization-Header validiert bevor der Chat-Handler ausgeführt wird. Konzept in `alice-chat-stream` (PROJ-30) reimplementiert.

#### PROJ-12 — Phase 2 Security & UX Hardening
1. **nginx Security Headers** — `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`
2. **Rate-Limiting Chat** — 20 Requests/Minute auf `/api/webhook/`; HTTP 429 mit nutzerfreundlicher Meldung
3. **Chat umbenennen** — Inline-Edit im Sidebar

#### PROJ-13 — Auth-Endpoint Rate-Limiting
Brute-Force-Schutz: 5 Requests/Minute via `map`-Direktive (nur POST-Requests werden gezählt).

---

### 3.3 Chat UI & Session Management (PROJ-8, PROJ-14)

#### PROJ-8 — Services Sidebar & Landing Page Migration
- Statische Landingpage ersetzt durch React-App
- Service-Links in `ServiceLinks`-Komponente in der Sidebar

#### PROJ-14 — Sidebar Context-Menu & Session-Persistenz
- Rechtsklick / Drei-Punkte-Menü: Session umbenennen, löschen
- Sessions überleben Browser-Neustarts (Persistenz in `localStorage`)
- Neue Sessions bekommen automatisch einen Titel aus dem ersten Satz der Anfrage

---

### 3.4 Document Management System (DMS) — PROJ-15 bis PROJ-25, PROJ-28, PROJ-29

Das DMS ist die umfangreichste Komponente und besteht aus einer vollständigen Datenpipeline: NAS-Scan → Textextraktion → LLM-Klassifikation → Weaviate-Indizierung → semantische Suche im Chat.

#### Überblick DMS-Pipeline

```
NAS (Inbox-Ordner)
    ↓  [alice-dms-scanner, stündlich 07-22 Uhr]
    ↓  SHA-256-Dedup via Redis
    ↓  Stabilitätsprüfung (5s Größenvergleich)
MQTT alice/dms/[pdf|ocr|txt|office]
    ↓  [4 Extractor-Container, dauerhaft]
    ├── dms-extractor-pdf   → pdf-parse (Node.js)
    ├── dms-extractor-ocr   → Tesseract (Python, deu+eng)
    ├── dms-extractor-txt   → direktes Lesen
    └── dms-extractor-office → LibreOffice headless
Redis List alice:dms:plaintext
    ↓  [alice-dms-processor, nächtlicher Batch]
    ↓  Ollama qwen3:14b: Klassifikation + Feldextraktion
Weaviate Collections (Invoice, BankStatement, Document,
                      Email, SecuritySettlement, Contract, BankTransaction)
    ↓  [alice-tool-search, im Chat-Handler als Tool]
Nutzer-Antwort im Chat
```

#### PROJ-15 — DMS NAS-Ordner-Verwaltung (CRUD)
- REST-API (`alice-dms-folder-api`): `GET/POST/PUT/DELETE /api/webhook/v1/dms/folders`
- Frontend: Settings-Tab „DMS" mit Tabelle + Formular (shadcn/ui)
- PostgreSQL: `alice.dms_watched_folders`

#### PROJ-16 — DMS Scanner & NAS Multi-Format-Scan
n8n-Workflow `alice-dms-scanner` (Schedule: `0 7-22 * * *`), rekursiver Scan, SHA-256-Dedup, OCR-Detection.

#### PROJ-17 — DMS Scanner Multi-Queue-Routing
Typenspezifisches Routing auf `alice/dms/pdf`, `alice/dms/ocr`, `alice/dms/txt`, `alice/dms/office`. Redis-basierte Stats-Counter.

#### PROJ-18 — DMS Text-Extractor-Container (4 Container)
Vier spezialisierte Docker-Container extrahieren Plaintext in Redis List `alice:dms:plaintext`.

#### PROJ-19 — DMS Processor Workflow (LLM-Klassifikation + Weaviate)
Nächtlicher n8n-Batch: Redis → LLM-Klassifikation → Feldextraktion → Weaviate-Insert.

#### PROJ-20 — DMS Document Search Tool (alice-tool-search)
Integration des DMS in den Chat als LLM-Tool. `search_documents` und `get_document_details` via LangChain Tool-Use.

#### PROJ-21 + PROJ-22 — DMS Lifecycle Management
Erkennung und Behandlung von Duplikaten, Verschiebungen und Dateiänderungen ohne erneuten LLM-Aufruf.

#### PROJ-23 — DMS Security Hardening
SQL-Injection-Fixes, GraphQL-Injection-Schutz (`className`-Allowlist + vollständiges Escaping).

#### PROJ-24 — DMS Operational Improvements
Scanner-Stats, LLM-Retry, MQTT Persistent Sessions, shutil.copy fix.

#### PROJ-25 — DMS Folder API Explicit Null Update
Explizites Null-Setzen von `suggested_type` / `description` via `null` vs. `undefined`.

#### PROJ-28 — DMS Verzeichnis-Reihenfolge (sort_order + Drag-and-Drop)
- Neue Spalte `sort_order` in `alice.dms_watched_folders`
- Drag-and-Drop via `@dnd-kit/sortable` im Frontend
- Scanner berücksichtigt `sort_order ASC, id ASC` bei der Verarbeitung

#### PROJ-29 — BankStatement Transaction Indexing (BankTransaction Collection)
Granulare Transaktionssuche für Kontoauszüge. Neue Weaviate-Collection `BankTransaction` (1 Objekt pro Buchung). Zweiphasige Verarbeitung im DMS-Processor: Header-Extraktion → Chunk-basierte Transaktionsextraktion.

---

### 3.5 User Management (PROJ-26, PROJ-27)

#### PROJ-26 — Admin Nutzerverwaltung
Vollständiger Nutzerverwaltungs-Flow: Anlegen (OTP per E-Mail, First-Login-Flow), Deaktivieren, Löschen.

#### PROJ-27 — Nutzerprofil selbst bearbeiten
Anzeigename, Interessen, Anrede, Sprache, E-Mail ändern, Passwort freiwillig ändern.

---

### 3.6 Streaming-Backend & nginx (PROJ-30, PROJ-31, PROJ-32)

#### PROJ-30 — Streaming Chat Backend (alice-chat-stream)
Der bisherige n8n-Chat-Handler pufferte vollständige LLM-Antworten (5–30s Wartezeit ohne Feedback). Lösung: Neuer Python/FastAPI-Container `alice-chat-stream` (Port 8003) ersetzt n8n als primären Chat-Endpunkt.

**Architektur:**
```
alice-chat-stream (FastAPI, Port 8003)
├── POST /stream/chat          ← Haupt-Streaming-Endpunkt (SSE)
├── GET  /health
└── GET  /metrics (Prometheus)

Upstream:
├── Ollama API (stream=true)
├── PostgreSQL (alice.messages, alice.user_profiles, alice.sessions)
├── Weaviate (AliceMemory nearText, HAIntent nearText)
├── alice-tool-ha  (n8n Webhook, HTTP)
└── alice-tool-search (n8n Webhook, HTTP)
```

**SSE-Event-Typen:**
```
data: {"type":"token","content":"Die"}
data: {"type":"thinking","content":"Ich prüfe..."}     ← seit PROJ-37
data: {"type":"tool_start","tool":"search_documents","status":"Suche nach 'Rechnung Nov'…"}
data: {"type":"tool_end","tool":"search_documents","ok":true,"summary":"3 Dokumente gefunden"}
data: {"type":"done","usage":{...}}
data: [DONE]
```

**Sicherheit:**
- RS256-JWT-Validierung (Public Key via Volume-Mount `/run/secrets/jwt_public.pem`)
- `user_id` ausschließlich aus verifiziertem JWT-Payload (kein Body-Parameter)
- HA_FAST-Pfad bleibt erhalten: Certainty ≥ 0,82 → direkter HA-Call, kein LLM (latenz ~46ms)
- n8n `alice-chat-handler` bleibt deaktiviert (Fallback, nicht gelöscht)

**Container-Module:** `main.py`, `auth.py`, `memory.py`, `ha_path.py`, `tools.py`, `streaming.py`, `metrics.py`

#### PROJ-31 — Frontend Streaming-UI
Umbau des React-Frontends von `fetch()`-Blockierung auf SSE-Streaming.

- **SSE-Transport:** `fetch()` + `ReadableStream` (nicht `EventSource`, da JWT-Header nicht möglich)
- **Token-Updates:** ID-basiertes In-Place-Update — kein Re-Render der gesamten Nachrichtenliste
- **Stopp-Button:** `AbortController.abort()` schließt SSE-Verbindung sofort
- **Fallback:** Falls `NEXT_PUBLIC_STREAM_API_URL` nicht gesetzt → alter Endpunkt
- Neue Pakete: `react-markdown`, `remark-gfm` (initial)

#### PROJ-32 — nginx Streaming-Konfiguration
- `proxy_buffering off` auf `/api/stream/` → SSE-Proxy
- Rate-Limiting auf Streaming-Endpunkt
- Neuer Location-Block für `alice-chat-stream:8003`

---

### 3.7 RS256-Migration (PROJ-34, PROJ-36)

#### PROJ-34 — alice-auth RS256 Migration
`alice-auth` signierte JWTs bisher mit HS256 (symmetrisch). Seit `alice-chat-stream` (PROJ-30) RS256-Verifikation erwartet, war eine Migration nötig.

**Ergebnis:**
- RSA-Schlüsselpaar (4096 Bit) auf Host: `/srv/warm/alice/keys/jwt_private.pem` (600) + `jwt_public.pem` (644)
- Private Key ausschließlich in `alice-auth` → Signieren; Public Key in alle Dienste gemountet → Verifikation
- Beide Dienste schlagen beim Start fail-fast, wenn Keys fehlen
- Dependency `cryptography>=42,<44` in beiden Services

#### PROJ-36 — RS256 Migration — Vollständige Umstellung aller Komponenten
Nach PROJ-34 blieb das n8n-JWT-Credential `4iUJhbFCSgQeHAGL` ("JWT Auth account") auf HS256 — alle n8n-Webhooks lieferten 403.

**Betroffene Fehler:**
1. **Sidebar:** 403 auf `GET /api/webhook/alice/sessions` → keine alten Chats sichtbar
2. **DMS:** 403 auf `GET /api/webhook/dms/folders` → Frontend zeigte "Zugriff verweigert"

**Fix:** n8n-Credential manuell auf RS256 + Public Key umgestellt, `JWT_SECRET` aus `n8n/.env` entfernt.

---

### 3.8 Chat Frontend Redesign & Streaming Verbosity (PROJ-35, PROJ-37, PROJ-38)

#### PROJ-35 — Chat Frontend Redesign — Nachrichten- und Eingabebereich
Das PROJ-31-Frontend hatte strukturelle Mängel: Segment-Modell (Präsentationslogik im State), ToolStatusChip (5 hardcodierte Tool-Namen, nicht erweiterbar), keine Textbreitenbegrenzung, kein Syntax Highlighting.

**Neues Rollen-Datenmodell:**
```typescript
type MessageRole = 'user' | 'assistant' | 'tool_call' | 'thinking' | 'error' | 'status';
```

**Neue Komponentenstruktur:**
```
components/Chat/
├── MessageRenderer.tsx    ← Role-Dispatch
├── renderers/
│   ├── AssistantMessage.tsx  ← 16px, Prose-Markdown, Syntax Highlighting
│   ├── UserMessage.tsx       ← 16px, rechtsbündige Bubble
│   ├── ToolCallMessage.tsx   ← 14px/grau, Tool-Name + Status
│   ├── ThinkingMessage.tsx   ← 14px/grau, Reasoning-Text
│   ├── ErrorMessage.tsx      ← roter Stil mit Icon
│   └── StatusMessage.tsx     ← 13px/grau
├── InputArea.tsx             ← Auto-Grow + Enter/Shift+Enter + Stop
└── types.ts                  ← MessageRole, Message-Interface

GELÖSCHT: MessageBubble.tsx, ToolStatusChip.tsx
```

**Kerneigenschaften:**
- `max-w-[760px]` zentrierte Spalte für optimale Lesbarkeit
- Syntax Highlighting via `rehype-highlight` + `highlight.js` (TypeScript, Python, JSON, Bash etc.)
- Auto-Scroll nur wenn ≤ 150px vom unteren Rand (kein Zwangs-Scroll bei Nutzer-Scroll)
- `Shift+Enter` für Zeilenumbruch, `Enter` sendet
- Tool-Calls und Thinking-Text als eigenständige `Message`-Objekte im Nachrichtenstrom

#### PROJ-37 — Streaming Verbosity — Thinking-Support und angereicherte Tool-Events
Aktiviert drei bisher nicht genutzte Fähigkeiten:

**Thinking-Stream:**
- `think: true` in Ollama-Anfrage → qwen3:14b liefert Reasoning-Tokens separat
- `message.thinking`-Chunks → SSE-Event `{"type":"thinking","content":"..."}` vor den `token`-Events
- Thinking-Tokens werden **nicht** in `alice.messages` gespeichert (flüchtig)
- `ThinkingMessage.tsx` (seit PROJ-35 vorbereitet) wird erstmals gerendert
- ENV-Var `OLLAMA_THINK` (default: `true`) — für Voice-Use-Cases deaktivierbar

**Angereicherte Tool-Events:**
- `tool_start.status` ist jetzt dynamisch: `"Suche nach 'Rechnung November 2025'…"` statt `"Suche in Dokumenten…"`
- `tool_end` enthält optionales `summary`-Feld: `"3 Dokumente gefunden"`, `"Ausgeführt"`, `"Gespeichert"`
- Alle Status-Texte auf 80 Zeichen begrenzt

**Frontend-Erweiterungen:**
- `handleThinking()` konvertiert den leeren `assistant`-Platzhalter in-place zu einer `thinking`-Nachricht
- Beim ersten `token` nach einem Thinking-Block: Thinking schließen, neue `assistant`-Nachricht öffnen
- `markStreamAborted` schließt auch offene `thinking`-Nachrichten beim Stopp

#### PROJ-38 — Sidebar Text-Truncation & Context-Menu Regression Fix
PROJ-35 verursachte zwei Regressions in der Sidebar:

1. **Text-Truncation fehlte:** Lange Chat-Titel liefen über und verdrängten den `⋯`-Button
2. **Context-Menu verschwunden:** Root cause war `display:table` des Radix `ScrollArea`-Viewports, der die Sidebar-Breite aufhob

**Fix:**
- `min-w-0` auf den Flex-Container der Sidebar-Zeile
- Radix ScrollArea Viewport: `display:table` → `display:block` via Tailwind-Selector
- shadcn `<Tooltip>` (dark-mode-kontrast: `bg-white text-black`) für vollständige Titel beim Hover
- `⋯`-Button (`shrink-0`) bleibt immer sichtbar — alle PROJ-14-Funktionen erhalten

---

### 3.9 HA-Sync Overhaul (PROJ-39)

#### PROJ-39 — alice-ha-sync Overhaul — Conversation Filter, Area Registry, Value Placeholder Expansion

Die in PROJ-11 deployete `alice-ha-sync`-Anwendung hatte drei strukturelle Fehler im HAIntent-Index:

**Problem 1 — Kein Conversation-Filter:**
`fetch_ha_entities()` holte alle ~2.100 HA-States ohne Expose-Check. `sensor.*`, `binary_sensor.*`, `person.*` etc. wurden indexiert — nie steuerbar per Sprache.

**Problem 2 — Falsche area_id/area_name:**
`area_id` wurde aus State-Attributen gelesen (fast immer `NULL`). Die Raumzuweisung ist in der HA Entity Registry gespeichert. Ergebnis: Utterances wie "Licht im Büro einschalten" wurden nie generiert.

**Problem 3 — Value-Placeholder übersprungen:**
Patterns mit `{value}`, `{temperature}` wurden komplett übersprungen. Befehle wie "Heizung auf 23 Grad" waren nicht in HAIntent.

**Lösung:** Neue Funktion `fetch_ha_websocket_data()` öffnet einmal pro Sync eine WebSocket-Verbindung zu HA und holt drei Datensätze:

| WebSocket-Befehl | Zweck |
|---|---|
| `homeassistant/expose_entity/list` | Set der entity_ids mit `conversation: true` |
| `config/entity_registry/list` | entity_id → area_id (direkte Raumzuweisung) |
| `config/device_registry/list` | device_id → area_id (Fallback über Device) |
| `config/area_registry/list` | area_id → area_name |

**Ergebnisse nach Deploy (live, ki.lan):**
- Expose-Filter: 14 Entitäten exposed → 2.099 gefiltert
- `alice.ha_entities`: 9 aktiv, alle mit nicht-NULL `area_id` + `area_name`
- HAIntent Weaviate: 93 Objekte (statt 70), davon 45 mit area-basierten Utterances
- nearText-Query `"Licht im Büro einschalten"` → Certainty 0,999 (weit über 0,82-Schwelle)
- `{value}` Expansion: Prozentwerte 10/25/50/75/100 für `light`, `media_player`; Temperatur 16–26°C für `climate`

**Sicherheit:** Fail-fast wenn Expose-API nicht erreichbar — kein Fallback auf alle Entitäten. Entity-IDs werden via Regex validiert (SQL-Injection, XSS-Schutz verifiziert live).

---

## 4. Abhängigkeitskette

```
PROJ-1 (DB + Weaviate Schema)
  └── PROJ-2 (hassil-parser Container)
        └── PROJ-3 (Chat Handler — deaktiviert seit PROJ-30)
              └── PROJ-9 (JWT-Schutz Chat)
              └── PROJ-20 (DMS Search Tool)
        └── PROJ-4 (HA Auto-Sync)
              └── PROJ-11 (Python Sync Worker)
                    └── PROJ-39 (HA-Sync Overhaul)
  └── PROJ-5 (hassil Library)
        └── PROJ-6 (hassil Fix)

PROJ-7 (JWT Auth, HS256 → RS256 via PROJ-34)
  └── PROJ-8 (Services Sidebar)
  └── PROJ-9 (Chat JWT-Schutz)
  └── PROJ-12 (Security Hardening)
        └── PROJ-13 (Auth Rate-Limiting)
  └── PROJ-26 (Admin User Management)
        └── PROJ-27 (Profil selbst bearbeiten)
  └── PROJ-34 (RS256 Migration alice-auth)
        └── PROJ-36 (RS256 Migration n8n Credential)

PROJ-30 (alice-chat-stream Backend, SSE)
  └── PROJ-31 (Frontend Streaming-UI)
        └── PROJ-35 (Chat Frontend Redesign)
              └── PROJ-37 (Streaming Verbosity — Thinking + Tool-Events)
              └── PROJ-38 (Sidebar Regression Fix)
  └── PROJ-32 (nginx SSE-Proxy)
  └── PROJ-33 (Phase-2 Speech Streaming Interface — Planned)
  └── PROJ-34 (RS256 — Signing-Seite)

PROJ-15 (DMS Folder Management)
  └── PROJ-16 (DMS Scanner)
        └── PROJ-17 (Multi-Queue Routing)
              └── PROJ-18 (4 Extractor Container)
                    └── PROJ-19 (DMS Processor)
                          └── PROJ-20 (DMS Search Tool)
                          └── PROJ-21 (Lifecycle Management)
                                └── PROJ-22 (Lifecycle Workflow)
                          └── PROJ-23 (Security Hardening)
                          └── PROJ-24 (Operational Improvements)
                          └── PROJ-29 (BankTransaction Indexing)
  └── PROJ-25 (Explicit Null Update)
  └── PROJ-28 (Sort Order + Drag-and-Drop)
```

---

## 5. Technologie-Stack (deployed)

| Kategorie            | Komponenten                                                                                                     |
| -------------------- | --------------------------------------------------------------------------------------------------------------- |
| **AI / LLM**         | Ollama qwen3:14b (RTX 3090, `think: true`), text2vec-transformers (Weaviate-Embedding, TITAN X)                 |
| **Orchestrierung**   | alice-chat-stream (FastAPI SSE), LangChain Tool-Use, n8n (Sub-Workflows: Tool-HA, Tool-Search, DMS, Auth)       |
| **Datenbank**        | PostgreSQL 15+ (`alice`-Schema, 14+ Tabellen), Weaviate (8 Collections + BankTransaction), Redis (AOF)          |
| **Messaging**        | Mosquitto MQTT (QoS 1, persistente Sessions)                                                                    |
| **Backend-Services** | alice-auth (FastAPI, RS256), alice-chat-stream (FastAPI, SSE, Port 8003), alice-ha-sync (Python), hassil-parser (FastAPI), 4× DMS Extractor |
| **Frontend**         | React + TypeScript + Vite + Tailwind CSS + shadcn/ui + react-markdown + rehype-highlight + @dnd-kit             |
| **Infrastruktur**    | nginx (Reverse Proxy, SSE-Proxy, Rate-Limiting, Security Headers), Docker Compose (17+ Container)               |
| **GPU**              | NVIDIA RTX 3090 (LLM-Inferenz + Thinking), TITAN X (text2vec-transformers Embedding)                            |

---

## 6. Services & n8n Workflows (Übersicht)

### Python/FastAPI Services

| Service              | Port | Zweck                                               |
| -------------------- | ---- | --------------------------------------------------- |
| `alice-auth`         | 8002 | Login, JWT RS256 Sign/Verify, Session-Management    |
| `alice-chat-stream`  | 8003 | Haupt-Chat-Endpunkt (SSE), 3-Tier-Memory, Tool-Use |

### n8n Workflows (aktiv)

| Workflow               | Trigger                   | Zweck                                     |
| ---------------------- | ------------------------- | ----------------------------------------- |
| `alice-tool-search`    | Execute Workflow          | Semantische Dokumentensuche in Weaviate   |
| `alice-tool-ha`        | Execute Workflow          | Home Assistant REST API                   |
| `alice-memory-transfer`| Schedule (täglich)        | PostgreSQL → Weaviate Langzeit-Gedächtnis |
| `alice-dms-scanner`    | Schedule (stündl. 07-22)  | NAS-Scan → MQTT-Queues                    |
| `alice-dms-processor`  | Schedule (nächtlich)      | Redis → LLM → Weaviate                    |
| `alice-dms-lifecycle`  | MQTT Trigger              | Duplikate + Verschiebungen ohne LLM       |
| `alice-dms-folder-api` | Webhook                   | Ordner-CRUD + Reorder für Admins          |
| Auth-Workflows (4×)    | Webhook                   | Login / Validate / Refresh / Logout       |
| `alice-session-api`    | Webhook                   | Session-CRUD für die Sidebar              |
| `alice-chat-handler`   | —                         | **Deaktiviert** (Fallback zu PROJ-3)      |

---

## 7. Drei-Schichten-Gedächtnis

| Tier                 | Speicher                         | Inhalt                                                   | Retention     |
| -------------------- | -------------------------------- | -------------------------------------------------------- | ------------- |
| **Working Memory**   | PostgreSQL `alice.messages`      | Letzte 20 Nachrichten der aktiven Session                | Session-Dauer |
| **Long-term Memory** | Weaviate `AliceMemory`           | Semantisch durchsuchbare Gesprächshistorie               | Dauerhaft     |
| **User Profile**     | PostgreSQL `alice.user_profiles` | Fakten + Präferenzen (Name, Interessen, Anrede, Sprache) | Dauerhaft     |

Thinking-Tokens (PROJ-37) sind **flüchtig** — sie werden nicht in `alice.messages` persistiert.

---

## 8. Sicherheitsarchitektur

- **Transport**: HTTPS (nginx, Let's Encrypt), ausschließlich VPN-Zugang
- **Authentifizierung**: JWT (RS256), validiert am nginx-/n8n-Webhook-Level; Private Key ausschließlich in `alice-auth`; Public Key verteilt an `alice-chat-stream` (und zukünftige Dienste)
- **Rate-Limiting**: 5 Req/min Login, 20 Req/min Chat (nginx `limit_req_zone`, HTTP 429)
- **Security Headers**: X-Frame-Options DENY, X-Content-Type-Options nosniff, Referrer-Policy, HSTS
- **SQL-Injection**: Durchgängig parametrisierte Queries (psycopg2 `%s`, n8n `queryReplacement`, asyncpg)
- **GraphQL-Injection**: Allowlists für Collection-Namen, vollständiges Escaping von Nutzereingaben
- **XSS**: React escaped alle Text-Inhalte; react-markdown v10 strippt Raw-HTML; keine `dangerouslySetInnerHTML`
- **HA-Entity-Injection**: Regex-Validierung von `entity_id` in `alice-ha-sync`
- **Secrets**: alle Credentials in `.env`-Dateien (gitignored), RSA-Keys als Volume-Mounts

---

## 9. Aktueller Gesamtstand

**38 von 39 Features** im Status **Deployed**. PROJ-33 (Phase-2 Speech Streaming Interface) ist **Planned**. Nächste freie Feature-ID: **PROJ-40**.

### Offene technische Schulden (niedrige Priorität)

- RLS-Policies auf HA-Infrastruktur-Tabellen sind noch permissiv (`USING TRUE`) — geplant für Phase 3
- DMS-Extractor-Container: kein DB-Connection-Pooling (akzeptabel bei niedriger Frequenz)
- PROJ-29 BUG-13: `BankTransaction`-Kinder werden beim Löschen des Parent-`BankStatement` via Lifecycle-Workflow nicht mitgelöscht (verwaiste Objekte in Weaviate, Medium-High)
- PROJ-29: Phase B hat kein Retry pro Chunk bei Ollama-Fehler → stille Teilverluste möglich
- PROJ-37 BUG-3: Kein Server-seitiges Cap auf Thinking-Volumen; kein Prometheus-Counter für Thinking-Tokens (Beobachtung nötig)
- PROJ-38 BUG-Med-1: Tooltip-Flash auf Touch-Geräten (iOS Safari) — niedrige Priorität
- PROJ-39 BUG-2: WebSocket `max_size=16MB`-Cap kann auf sehr großen HA-Installs zu `ha_unreachable`-Fehlern führen (Medium, selbstheilend beim nächsten Sync)
- PROJ-28 BUG-FE-1/2: Drag-and-Drop Race Condition bei schnellem Doppel-Drag (Low)

### Nächste Entwicklungsschritte (Phase 2)

- **PROJ-33** (Planned): Speech Streaming Interface — WebSocket-Schnittstelle für STT/TTS
- Speech Gateway: Whisper STT + Piper TTS + Speaker-ID (Python-Container)
- WebAuthn-Authentifizierung (Datenstruktur bereits vorbereitet)
- DMS Lifecycle: BankTransaction-Kinder beim Löschen des Parent-Auszugs mitlöschen (Follow-up PROJ-29 BUG-13)
- Multi-User-Display-Routing (Gespräche an den richtigen Bildschirm leiten)
- Thinking-Volume-Cap / Prometheus-Metrik für Thinking-Tokens (Follow-up PROJ-37 BUG-3)
