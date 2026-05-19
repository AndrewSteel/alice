# ALICE — AritifiaL Intelligence Communication Engine

A local-first, speech-first personal assistant that unifies smart home control, document management, finances, calendar, mail and chat under a single conversational interface. All AI inference runs locally — no cloud required.

---

## Development Status

| Phase     | Status     | Description                                                            |
| --------- | ---------- | ---------------------------------------------------------------------- |
| Phase 0   | ✅ Deployed | Hardware setup, GPU configuration, storage layout                      |
| Phase 1   | ✅ Deployed | Core stack: n8n, Ollama, Weaviate, PostgreSQL, React PWA               |
| Phase 1.2 | ✅ Deployed | HA-first intent routing with semantic matching                         |
| Phase 1.5 | ✅ Deployed | JWT authentication, login screen, services sidebar                     |
| Phase 1.6 | ✅ Deployed | DMS pipeline v2, user management, streaming infrastructure, RS256 auth |
| Phase 2   | 🗓 Planned  | Speech gateway: Whisper STT + Piper TTS + Speaker-ID                   |
| Phase 3   | 🗓 Planned  | Multi-user, display routing, security hardening                        |

---

## Architecture

```text
CLIENT (React PWA, HA Voice Devices)
    ↓
SPEECH GATEWAY [Phase 2] (Python: Whisper STT, Speaker-ID, Piper TTS)
    ↓
CHAT SERVICE (alice-chat-stream — Python/FastAPI, SSE streaming)
    ↓
ORCHESTRATION (Ollama qwen3:14b via tool-use; n8n sub-workflows for HA + DMS)
    ↓
DATA (Weaviate, PostgreSQL alice schema, Redis, NAS documents)
```

**Core principle:** One LLM call with native tool-use — no two-step routing. The model directly selects and executes tools: `home_assistant`, `search_documents`, `get_document_details`, `remember`, `recall`.

**Streaming:** `alice-chat-stream` (PROJ-30) streams LLM tokens to the browser via Server-Sent Events. Tool status events and (optionally) reasoning tokens are pushed inline. The legacy `alice-chat-handler` n8n workflow remains as a fallback.

**Authentication:** JWTs are issued by `alice-auth` using RS256 (RSA key pair). The private key stays in alice-auth; other services (alice-chat-stream, n8n) verify tokens with the public key only — no shared secret crosses container boundaries.

---

## Key Design Principles

**AI-First** — The LLM is the decision-maker; all other systems (Home Assistant, Weaviate, Postgres) are tools it calls.

**Speech-First** — Voice is the primary interaction channel. Wakeword-activated HA Voice devices and a browser push-to-talk button both route through the same central pipeline.

**Local-First** — Accessible only via VPN. All inference runs on local hardware; cloud models are not used.

**Graceful Degradation** — If a component fails, the system falls back to simpler behavior rather than failing entirely.

---

## Infrastructure

### Hardware

| Component                                             | Role                                       |
| ----------------------------------------------------- | ------------------------------------------ |
| Headless server (Ryzen 9 + RTX 3090 + TITAN X Pascal) | AI core, Docker stack                      |
| Proxmox server                                        | Home Assistant, Pi-hole, InfluxDB, Grafana |
| Synology NAS                                          | Document storage, backups                  |

### GPU Allocation

| Container             | GPU      | VRAM    | Purpose                    |
| --------------------- | -------- | ------- | -------------------------- |
| Ollama (LLM)          | TITAN X  | ~7.4 GB | qwen3:14b inference        |
| weaviate-transformers | RTX 3090 | ~1.5 GB | text2vec embeddings        |
| weaviate-multi2vec    | RTX 3090 | ~0.8 GB | CLIP image+text embeddings |
| Whisper STT [Phase 2] | RTX 3090 | TBD     | Speech-to-text             |

### Storage

| Tier                | Mount       | Contents                                      |
| ------------------- | ----------- | --------------------------------------------- |
| Hot (980 Pro NVMe)  | `/srv/hot`  | AI models, Weaviate index, embedding caches   |
| Warm (ZFS mirror)   | `/srv/warm` | PostgreSQL, n8n data, persistent service data |
| Cold (Synology NAS) | —           | Documents, backups                            |

### Docker Services

| Service                 | Purpose                                                                                      |
| ----------------------- | -------------------------------------------------------------------------------------------- |
| `alice-chat-stream`     | Primary chat endpoint: FastAPI/SSE streaming, JWT RS256 verification (PROJ-30)               |
| `alice-auth`            | JWT issuance (RS256), bcrypt password verification, OTP email (PROJ-7/34)                    |
| `alice-ha-sync`         | HA entity sync: conversation-filter, area registry, value placeholder expansion (PROJ-11/39) |
| `alice-dms-pdf`         | DMS text extractor: PDF → plaintext (pdfminer)                                               |
| `alice-dms-ocr`         | DMS text extractor: scanned PDF/image → plaintext (Tesseract OCR)                            |
| `alice-dms-office`      | DMS text extractor: Office documents → plaintext (LibreOffice headless)                      |
| `alice-dms-txt`         | DMS text extractor: plain text passthrough                                                   |
| `n8n`                   | Workflow engine: sub-workflows for HA + DMS tools, DMS pipeline, auth webhooks               |
| `ollama-titan`          | LLM inference (TITAN X GPU)                                                                  |
| `weaviate`              | Vector search                                                                                |
| `weaviate-transformers` | text2vec-transformers inference (RTX 3090)                                                   |
| `weaviate-multi2vec`    | CLIP multimodal embeddings (RTX 3090)                                                        |
| `postgres`              | Structured data: alice schema, auth sessions, user profiles                                  |
| `redis`                 | DMS state (hash index, queued files), session cache                                          |
| `mqtt`                  | Event bus (alice/# topics) — DMS pipeline, HA sync                                           |
| `nginx`                 | Reverse proxy, React static files, SSE proxy (buffering disabled)                            |

---

## Memory Architecture (Three Tiers)

| Tier      | Store                            | Scope            | Contents                                |
| --------- | -------------------------------- | ---------------- | --------------------------------------- |
| Working   | PostgreSQL `alice.messages`      | Last 20 messages | Active session context                  |
| Long-term | Weaviate `AliceMemory`           | Permanent        | Semantic search over past conversations |
| Profile   | PostgreSQL `alice.user_profiles` | Permanent        | User facts, preferences                 |

---

## n8n Workflows

Workflows live in `workflows/`. Import via n8n UI. The streaming endpoint is `POST /api/stream/chat`; the legacy webhook fallback is `POST /webhook/alice`.

| Workflow                | Trigger                        | Purpose                                        |
| ----------------------- | ------------------------------ | ---------------------------------------------- |
| `alice-tool-ha`         | Workflow call                  | Home Assistant REST API tool                   |
| `alice-tool-search`     | Workflow call                  | Weaviate document + transaction search tool    |
| `alice-memory-transfer` | Schedule (daily)               | PostgreSQL → Weaviate long-term memory         |
| `alice-dms-scanner`     | Schedule (hourly)              | NAS scan → lifecycle detection → MQTT queues   |
| `alice-dms-processor`   | Schedule (nightly)             | MQTT queue → LLM classify + extract → Weaviate |
| `alice-dms-lifecycle`   | MQTT `alice/dms/lifecycle`     | Duplicate/move events: Weaviate PATCH, no LLM  |
| `alice-dms-folder-api`  | Webhook `/webhook/dms/folders` | Admin CRUD for NAS watched folders             |
| Auth workflows          | Webhook                        | Login / validate / refresh / logout            |

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
    → LLM classification (qwen3:14b, 1× retry)
    → field extraction per document type
    → Weaviate storage (per-collection)
    → BankTransaction chunking for bank statements
```

**Weaviate collections:** `Invoice`, `BankStatement`, `BankTransaction`, `Document`, `Email`, `SecuritySettlement`, `Contract`

**Redis state:** `alice:dms:path_to_hash`, `alice:dms:hash_to_paths:<hash>`, `alice:dms:processed`, `alice:dms:queued_files`

---

## Domain Coverage

| Domain          | Capability                                                                                           |
| --------------- | ---------------------------------------------------------------------------------------------------- |
| Smart Home      | Lights, climate, covers, locks, media players, switches, vacuum — conversation-exposed entities only |
| Documents (DMS) | Invoices, bank statements (+ per-transaction search), contracts, emails, securities                  |
| Memory          | Persistent facts, conversation history, user preferences                                             |
| User Management | Admin: create/deactivate/delete users, OTP reset; self-service: password, email, profile             |
| Finances        | Bank transaction search (PROJ-29); deeper analysis planned                                           |
| Calendar & Mail | [Phase 2+]                                                                                           |

---

## Latency Targets

| Scenario                    | Target         | Maximum        |
| --------------------------- | -------------- | -------------- |
| LLM first token (streaming) | < 800 ms       | 1,500 ms       |
| LLM full response           | < 2,000 ms     | 4,000 ms       |
| HA tool execution           | < 300 ms       | 500 ms         |
| **End-to-end (text)**       | **< 3,000 ms** | **< 5,000 ms** |
| End-to-end (voice, Phase 2) | < 2,000 ms     | 3,500 ms       |

---

## Repository Structure

```text
alice/
├── docker/compose/          # Docker Compose files per service category
│   ├── ai/                  # Ollama, Whisper, Piper, OpenWebUI
│   ├── automations/         # n8n, Weaviate, MQTT, alice-chat-stream
│   ├── data/                # PostgreSQL, Redis
│   └── infra/               # nginx, Prometheus, Grafana, Gotify
├── features/                # Feature specs (PROJ-N-*.md) + INDEX.md
├── frontend/                # React + TypeScript + Tailwind PWA
├── schemas/                 # Weaviate collection schemas (JSON)
├── scripts/                 # Setup and operational scripts
│   ├── setup-database.sh    # Create DB + apply init-schema.sql
│   ├── set-initial-passwords.sh  # Interactive bcrypt password setup
│   ├── init-weaviate-schema.sh   # Initialize Weaviate collections
│   ├── deploy-frontend.sh   # Build + copy to nginx html/
│   └── sync-compose.sh      # Sync compose files to production server
├── sql/
│   ├── init-schema.sql      # Consolidated schema (Phase 1 final)
│   └── seed-users.example.sql  # Template for initial users (copy → seed-users.sql)
├── workflows/               # n8n workflow exports (JSON)
└── .env.n8n.example         # Required n8n environment variables
```

---

## Quick Start (Development)

```bash
# 1. Copy and fill in environment file
cp .env.n8n.example docker/compose/automations/n8n/.env

# 2. Apply PostgreSQL schema (consolidated Phase 1 final)
docker exec -i postgres psql -U user -d alice < sql/init-schema.sql

# 3. Seed users (copy example, fill in real names/emails)
cp sql/seed-users.example.sql sql/seed-users.sql
# edit sql/seed-users.sql, then:
docker exec -i postgres psql -U user -d alice < sql/seed-users.sql

# 4. Set initial passwords interactively
./scripts/set-initial-passwords.sh

# 5. Initialize Weaviate collections
./scripts/init-weaviate-schema.sh http://weaviate:8080

# 6. Start frontend dev server
cd frontend && npm ci && npm run dev
```

See `CLAUDE.md` for full development reference and AI assistant instructions.

---

## Deployment

```bash
# Sync compose files to production server (ki.lan)
./scripts/sync-compose.sh

# Deploy frontend
cd frontend && npm run build
./scripts/deploy-frontend.sh
```

Access is restricted to VPN. Production host: `ki.lan`.

---

## Acknowledgements

The development workflow for this project is based on the **[AI Coding Starter Kit](https://github.com/AlexPEClub/ai-coding-starter-kit)** by **Alex Sprogis**, adapted with some modifications for this project.

Created by **Alex Sprogis** – AI Product Engineer & Content Creator.

- [YouTube](https://www.youtube.com/@alex.sprogis)
- [Website](https://alexsprogis.de)
