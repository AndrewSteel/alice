# ALICE — ArtificiaL Intelligence Communication Engine

A local-first, speech-first personal assistant that unifies smart home control, document management, finances, mail and chat under a single conversational interface. All AI inference runs locally on dedicated hardware — no cloud required.

---

## Development Status

| Phase     | Status      | Description                                                                    |
| --------- | ----------- | ------------------------------------------------------------------------------ |
| Phase 0   | ✅ Deployed | Hardware setup, GPU configuration, storage layout                              |
| Phase 1   | ✅ Deployed | Core stack: n8n, Ollama, Weaviate, PostgreSQL, React PWA                       |
| Phase 1.2 | ✅ Deployed | HA-first intent routing with semantic matching                                 |
| Phase 1.5 | ✅ Deployed | JWT authentication, login screen, services sidebar                             |
| Phase 1.6 | ✅ Deployed | DMS pipeline v2, user management, streaming infrastructure, RS256 auth         |
| Phase 2.1 | ✅ Deployed | Speech gateway: Whisper STT + Piper TTS, WebApp voice, TTS latency tuning      |
| Phase 2.2 | ✅ Deployed | HA Voice Integration, Speaker-ID, ESPHome feedback, chat storage & archive     |
| Phase 2.3 | ✅ Deployed | Mail IMAP integration, Vision-Chat Flip-Cards, DMS thumbnail generation        |
| Phase 3   | 🗓 Planned  | Display routing (PROJ-45), multi-display output, deeper financial analysis     |

---

## Architecture

```text
CLIENT (React PWA + HA Voice Devices + ESPHome Wyoming Satellites)
    ↓
SPEECH GATEWAY (alice-speech-gateway — Python: Whisper large-v3 STT, Piper TTS,
    Wyoming protocol (port 10300) + WebSocket (port 10301), Speaker-ID via embeddings)
    ↓
CHAT SERVICE (alice-chat-stream — Python/FastAPI, SSE streaming)
    ↓
ORCHESTRATION (Ollama qwen3.5:27b-q4_K_M via native tool-use;
    n8n sub-workflows for HA, DMS, Mail tools)
    ↓
DATA (Weaviate, PostgreSQL alice schema, Redis, NAS documents)
```

**Core principle:** One LLM call with native tool-use — no two-step routing. The model directly selects and executes tools: `home_assistant`, `search_documents`, `get_document_details`, `search_mail`, `get_mail`, `remember`, `recall`.

**Streaming:** `alice-chat-stream` streams LLM tokens to the browser via Server-Sent Events. Tool status events, reasoning tokens, and `vision_results` events (for Flip-Card display) are pushed inline.

**Authentication:** JWTs are issued by `alice-auth` using RS256. The private key stays in alice-auth; other services verify tokens with the public key only — no shared secret crosses container boundaries.

---

## Key Design Principles

**AI-First** — The LLM is the decision-maker; all other systems (Home Assistant, Weaviate, Postgres) are tools it calls.

**Speech-First** — Voice is the primary interaction channel. Wakeword-activated ESPHome satellites and HA Voice devices connect via Wyoming protocol; browser push-to-talk uses WebSocket — both route through the same central pipeline.

**Local-First** — Accessible only via VPN. All inference (LLM, STT, TTS, embeddings) runs on local hardware.

**Graceful Degradation** — If a component fails, the system falls back to simpler behavior rather than failing entirely.

---

## Infrastructure

### Hardware

| Component                                             | Role                                       |
| ----------------------------------------------------- | ------------------------------------------ |
| Headless server (Ryzen 9 + RTX 3090 + TITAN X Pascal) | AI core, Docker stack                      |
| Proxmox server                                        | Home Assistant, Pi-hole, InfluxDB, Grafana |
| Synology NAS                                          | Document storage, backups, warm storage    |

### GPU Allocation

| Container                      | GPU      | VRAM     | Purpose                           |
| ------------------------------ | -------- | -------- | --------------------------------- |
| Ollama / alice-speech-gateway  | TITAN X  | ~14 GB   | qwen3.5:27b-q4_K_M inference + STT/TTS |
| wyoming-whisper                | TITAN X  | shared   | Whisper large-v3 STT              |
| weaviate-transformers          | RTX 3090 | ~1.5 GB  | text2vec embeddings               |
| weaviate-multi2vec             | RTX 3090 | ~0.8 GB  | CLIP image+text embeddings        |

### Storage

| Tier                | Mount       | Contents                                                    |
| ------------------- | ----------- | ----------------------------------------------------------- |
| Hot (980 Pro NVMe)  | `/srv/hot`  | AI models, Weaviate index, Whisper models, embedding caches |
| Warm (ZFS mirror)   | `/srv/warm` | PostgreSQL, n8n data, DMS thumbnails, persistent data       |
| Cold (Synology NAS) | `/mnt/nas`  | Source documents, mail attachments, backups                 |

### Docker Services

| Service                 | Purpose                                                                                      |
| ----------------------- | -------------------------------------------------------------------------------------------- |
| `alice-chat-stream`     | Primary chat endpoint: FastAPI/SSE streaming, JWT RS256 verification, vision_results events  |
| `alice-auth`            | JWT issuance (RS256), bcrypt password verification, OTP email                                |
| `alice-speech-gateway`  | Wyoming + WebSocket speech bridge: Whisper STT, Piper TTS, Speaker-ID embedding             |
| `alice-ha-sync`         | HA entity sync: conversation-filter, area registry, value placeholder expansion              |
| `alice-mail-reader`     | IMAP reader: fetches mail metadata → Weaviate; exposes search API for n8n tools             |
| `alice-dms-thumbnailer` | DMS thumbnail generation: PDF/Office/image → 400×400 JPEG; serves GET /thumbnail/{uuid}     |
| `alice-dms-pdf`         | DMS extractor: PDF → plaintext (pdfminer)                                                   |
| `alice-dms-ocr`         | DMS extractor: scanned PDF/image → plaintext (Tesseract OCR)                                |
| `alice-dms-office`      | DMS extractor: Office documents → plaintext (LibreOffice headless)                          |
| `alice-dms-txt`         | DMS extractor: plain text passthrough                                                        |
| `n8n`                   | Workflow engine: HA + DMS + mail tools, DMS pipeline, auth/session webhooks                 |
| `wyoming-whisper`       | Whisper large-v3 STT (Wyoming protocol, port 10300)                                         |
| `wyoming-piper`         | Piper TTS (Wyoming protocol, port 10200)                                                     |
| `ollama-titan`          | LLM inference — qwen3.5:27b-q4_K_M (TITAN X GPU)                                           |
| `ollama-3090`           | Secondary Ollama instance (RTX 3090, e.g. embedding tasks)                                  |
| `weaviate`              | Vector search                                                                                |
| `weaviate-transformers` | text2vec-transformers inference (RTX 3090)                                                   |
| `weaviate-multi2vec`    | CLIP multimodal embeddings (RTX 3090)                                                        |
| `postgres`              | Structured data: alice schema, auth sessions, messages, user profiles                       |
| `redis`                 | DMS state (hash index, queued files), session cache                                          |
| `mqtt`                  | Event bus (alice/# topics) — DMS pipeline, thumbnail triggers, HA sync                      |
| `nginx`                 | Reverse proxy, React static files, SSE proxy (buffering disabled)                           |

---

## Memory Architecture (Three Tiers)

| Tier      | Store                            | Scope            | Contents                                |
| --------- | -------------------------------- | ---------------- | --------------------------------------- |
| Working   | PostgreSQL `alice.messages`      | Last 20 messages | Active session context                  |
| Long-term | Weaviate `AliceMemory`           | Permanent        | Semantic search over past conversations |
| Profile   | PostgreSQL `alice.user_profiles` | Permanent        | User facts, preferences                 |

Chat sessions are stored for 30 days with auto-generated titles. Admins can browse all user sessions via the Settings → Chat Archive tab.

---

## n8n Workflows

Workflows live in `workflows/`. The streaming endpoint is `POST /api/stream/chat`; the legacy webhook fallback is `POST /api/webhook/alice`.

| Workflow                          | Trigger                         | Purpose                                               |
| --------------------------------- | ------------------------------- | ----------------------------------------------------- |
| `alice-tool-search`               | Workflow call                   | Weaviate hybrid search across all DMS collections     |
| `alice-mail-tools`                | Workflow call                   | Mail search and retrieval tools for LLM               |
| `alice-mail-api`                  | Webhook                         | Mail folder management API                            |
| `alice-mail-sync`                 | Schedule                        | IMAP → Weaviate mail sync                             |
| `alice-session-api`               | Webhook                         | Session list, detail, and delete endpoints            |
| `alice-session-cleanup`           | Schedule (daily)                | Purge sessions older than 30 days                     |
| `alice-dms-scanner`               | Schedule (hourly)               | NAS scan → lifecycle detection → MQTT queues          |
| `alice-dms-processor`             | Schedule (nightly)              | MQTT queue → LLM classify + extract → Weaviate        |
| `alice-dms-lifecycle`             | MQTT `alice/dms/lifecycle`      | Duplicate/move events: Weaviate PATCH, no LLM         |
| `alice-dms-thumbnailer`           | MQTT `alice/dms/done`           | Generate 400×400 thumbnail after DMS import           |
| `alice-dms-thumbnailer-backfill`  | Webhook POST (manual)           | Generate thumbnails for all existing Weaviate objects |
| `alice-dms-folder-api`            | Webhook `/webhook/dms/folders`  | Admin CRUD for NAS watched folders                    |

---

## DMS Pipeline

The Document Management System pipeline runs fully automated:

```text
NAS inbox folders (configured via admin UI)
    ↓ hourly — alice-dms-scanner (n8n)
    ↓ detects: new / duplicate / moved / changed
    ↓
MQTT queues (alice/dms/<type> per format)   MQTT alice/dms/lifecycle
    ↓                                            ↓
alice-dms-{pdf,ocr,txt,office}             alice-dms-lifecycle (n8n)
    → plaintext extraction                      → Weaviate PATCH, Redis update
    ↓
MQTT alice/dms/extracted
    ↓ nightly — alice-dms-processor (n8n)
    → LLM classification (qwen3.5:27b, 1× retry)
    → field extraction per document type
    → Weaviate storage (per-collection)
    → BankTransaction chunking for bank statements
    → MQTT alice/dms/done
    ↓
alice-dms-thumbnailer (n8n, MQTT-triggered)
    → HTTP POST alice-dms-thumbnailer:8004/generate
    → 400×400 JPEG saved to warm storage
    → Weaviate PATCH sets thumbnail_path
```

**Weaviate collections:** `Invoice`, `BankStatement`, `BankTransaction`, `Document`, `Email`, `SecuritySettlement`, `Contract`

**Thumbnail storage:** `/srv/warm/alice/thumbnails/{weaviate_uuid}.jpg` — served via `GET /api/dms/thumbnail/{uuid}` (JWT auth, placeholder on miss)

**Redis state:** `alice:dms:path_to_hash`, `alice:dms:hash_to_paths:<hash>`, `alice:dms:processed`, `alice:dms:queued_files`

---

## Vision-Chat (Flip-Cards)

When a DMS search returns multiple results, `alice-chat-stream` emits a `vision_results` SSE event alongside the normal text stream. The React frontend displays results as interactive **Flip-Cards** in a split-screen layout:

| Mode        | Vision panel | Text panel | Desktop layout     |
| ----------- | ------------ | ---------- | ------------------ |
| Text only   | hidden       | full width | default after login |
| Vision only | full width   | hidden     | after visual query |
| Split       | 2/3 width    | 1/3 width  | user-toggled       |

Each card has three faces: **Front** (thumbnail + metadata), **Back** (Weaviate schema fields), **Summary** (AI-generated summary). On mobile, swipe left/right switches between panels; portrait shows 2 cards/row, landscape 4 cards/row.

---

## Speech Pipeline

```text
ESPHome satellite / HA Voice device
    → Wyoming protocol (port 10300)
    → alice-speech-gateway
    → Whisper large-v3 STT (German, TITAN X)
    → alice-chat-stream (HTTP POST)
    → LLM response
    → Piper TTS (de_DE-thorsten-high)
    → Wyoming audio back to device

Browser push-to-talk
    → WebSocket (port 10301, /api/speech/)
    → alice-speech-gateway (same pipeline)
    → TTS audio stream back to browser
```

Speaker recognition identifies the active user from voice embeddings stored in PostgreSQL; the resolved user identity is passed to alice-chat-stream as the authenticated user context.

---

## Domain Coverage

| Domain          | Status      | Capability                                                                                            |
| --------------- | ----------- | ----------------------------------------------------------------------------------------------------- |
| Smart Home      | ✅ Deployed | Lights, climate, covers, locks, media players, switches, vacuum — conversation-exposed entities only  |
| Documents (DMS) | ✅ Deployed | Invoices, bank statements (+ per-transaction search), contracts, emails, securities; Flip-Card view   |
| Mail            | ✅ Deployed | IMAP sync → Weaviate; search and retrieve mails via natural language                                  |
| Memory          | ✅ Deployed | Persistent facts, 30-day conversation history, user preferences                                      |
| User Management | ✅ Deployed | Admin: create/deactivate/delete users, OTP reset, chat archive; self-service: password, email, profile |
| Voice           | ✅ Deployed | ESPHome Wyoming satellites, HA Voice devices, browser push-to-talk, Speaker-ID                       |
| Finances        | ✅ Deployed | Bank transaction search; deeper analysis planned for Phase 3                                          |
| Display Routing | 🗓 Planned  | Config table (wallpanel/TV/PC), n8n router per display target (PROJ-45)                              |

---

## Latency Targets

| Scenario                    | Target         | Maximum        |
| --------------------------- | -------------- | -------------- |
| LLM first token (streaming) | < 800 ms       | 1,500 ms       |
| LLM full response           | < 2,000 ms     | 4,000 ms       |
| HA tool execution           | < 300 ms       | 500 ms         |
| **End-to-end (text)**       | **< 3,000 ms** | **< 5,000 ms** |
| End-to-end (voice)          | < 2,000 ms     | 3,500 ms       |
| TTS first audio chunk       | < 3,000 ms     | 5,000 ms       |

---

## Repository Structure

```text
alice/
├── docker/compose/          # Docker Compose files per service category
│   ├── ai/                  # Ollama, Whisper, Piper, OpenWebUI
│   ├── automations/         # alice-chat-stream, alice-speech-gateway,
│   │                        #   alice-mail-reader, alice-dms-thumbnailer,
│   │                        #   alice-ha-sync, n8n, Weaviate, MQTT, DMS extractors
│   ├── data/                # PostgreSQL, Redis
│   └── infra/               # nginx, Prometheus, Grafana
├── features/                # Feature specs (PROJ-N-*.md) + INDEX.md
├── frontend/                # React + TypeScript + Tailwind PWA
│   └── src/components/
│       ├── Vision/          # FlipCard, VisionPanel, ThumbnailImage, FlipCardGrid
│       ├── Chat/            # ChatWindow, MessageList, InputArea
│       ├── Sidebar/         # Session list
│       └── Settings/        # Profile, user management, DMS folders, chat archive
├── schemas/                 # Weaviate collection schemas (JSON)
├── scripts/                 # Setup and operational scripts
│   ├── setup-database.sh         # Create DB + apply init-schema.sql
│   ├── set-initial-passwords.sh  # Interactive bcrypt password setup
│   ├── init-weaviate-schema.sh   # Initialize Weaviate collections
│   ├── proj55-add-thumbnail-path.sh  # Migrate thumbnail_path field to Weaviate
│   ├── deploy-frontend.sh        # Build + copy to nginx html/
│   └── sync-compose.sh           # Sync compose files to production server
├── sql/
│   ├── init-schema.sql           # Consolidated schema
│   └── seed-users.example.sql    # Template for initial users
├── workflows/               # n8n workflow exports (JSON)
└── .env.n8n.example         # Required n8n environment variables
```

---

## Quick Start (Development)

```bash
# 1. Copy and fill in environment file
cp .env.n8n.example docker/compose/automations/n8n/.env

# 2. Apply PostgreSQL schema
docker exec -i postgres psql -U user -d alice < sql/init-schema.sql

# 3. Seed users (copy example, fill in real names/emails)
cp sql/seed-users.example.sql sql/seed-users.sql
# edit sql/seed-users.sql, then:
docker exec -i postgres psql -U user -d alice < sql/seed-users.sql

# 4. Set initial passwords interactively
./scripts/set-initial-passwords.sh

# 5. Initialize Weaviate collections
./scripts/init-weaviate-schema.sh http://weaviate:8080

# 6. Add thumbnail_path field to Weaviate collections (PROJ-55)
./scripts/proj55-add-thumbnail-path.sh

# 7. Start frontend dev server
cd frontend && npm ci && npm run dev
```

See `CLAUDE.md` for full development reference and AI assistant instructions.

---

## Deployment

```bash
# Sync compose files to production server (ki.lan)
./scripts/sync-compose.sh

# Reload nginx after config changes
ssh stan@ki.lan "docker exec nginx nginx -s reload"

# Deploy frontend
./scripts/deploy-frontend.sh   # builds + copies to nginx html/
./scripts/sync-compose.sh      # syncs to server (both steps required)

# Rebuild a container after code changes (example)
ssh stan@ki.lan "docker compose -f /srv/compose/automations/alice-chat-stream/compose.yml up -d --build --force-recreate"

# One-time: generate thumbnails for all existing Weaviate documents
curl -X POST https://alice.happy-mining.de/api/webhook/alice-dms-thumbnailer-backfill
```

Access is restricted to VPN. Production host: `ki.lan`.

---

## Acknowledgements

The development workflow for this project is based on the **[AI Coding Starter Kit](https://github.com/AlexPEClub/ai-coding-starter-kit)** by **Alex Sprogis**, adapted with modifications for this project.

Created by **Alex Sprogis** – AI Product Engineer & Content Creator.

- [YouTube](https://www.youtube.com/@alex.sprogis)
- [Website](https://alexsprogis.de)
