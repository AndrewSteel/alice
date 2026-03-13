# ALICE — AritifiaL Intelligence Communication Engine

A local-first, speech-first personal assistant that unifies smart home control, document management, finances, calendar, and mail under a single conversational interface. All AI inference runs locally — no cloud required.

---

## Development Status

| Phase         | Status     | Description                                              |
| ------------- | ---------- | -------------------------------------------------------- |
| Phase 0       | ✅ Deployed | Hardware setup, GPU configuration, storage layout        |
| Phase 1.1     | ✅ Deployed | Core stack: n8n, Ollama, Weaviate, PostgreSQL, React PWA |
| Phase 1.2     | ✅ Deployed | HA-first intent routing with semantic matching           |
| **Phase 1.5** | ✅ Deployed | JWT authentication, login screen, services sidebar       |
| Phase 2       | 🗓 Planned  | Speech gateway: Whisper STT + Piper TTS + Speaker-ID     |
| Phase 3       | 🗓 Planned  | Multi-user, display routing, security hardening          |

### Phase 1.2 Features

| ID     | Feature                                                             | Status      |
| ------ | ------------------------------------------------------------------- | ----------- |
| PROJ-1 | HA Intent Infrastructure (DB schema + Weaviate HAIntent collection) | ✅ Deployed  |
| PROJ-2 | FastAPI container + hassil intent expansion                         | ✅ Deployed  |
| PROJ-3 | HA-first chat handler with intent routing                           | ✅ Deployed  |
| PROJ-4 | HA auto-sync (MQTT → n8n → Weaviate)                                | ✅ Deployed  |
| PROJ-5 | Hassil native library integration (expansion engine upgrade)        | ✅ Deployed  |
| PROJ-6 | Hassil expansion_rules compatibility fix (all intents via hassil)   | ✅ Deployed  |

### Phase 1.5 Features

| ID      | Feature                                                                         | Status      |
| ------- | ------------------------------------------------------------------------------- | ----------- |
| PROJ-7  | JWT auth / login screen (bcrypt passwords, JWT sessions, ProtectedRoute)        | ✅ Deployed  |
| PROJ-8  | Services sidebar & landing page migration (old HTML dashboard → Alice sidebar)  | ✅ Deployed  |
| PROJ-9  | Chat-handler JWT protection (webhook auth guard + token validation)             | ✅ Deployed  |
| PROJ-10 | Weaviate intent lookup — migration to native n8n nodes                          | ✅ Deployed  |
| PROJ-11 | HA sync Python worker (replaces n8n alice-ha-intent-sync, credentials in .env) | ✅ Deployed  |
| PROJ-12 | Phase 2 security & UX hardening (nginx headers, rate-limiting, chat rename)     | ✅ Deployed  |
| PROJ-13 | Auth-endpoint rate-limiting (login brute-force protection)                      | ✅ Deployed  |
| PROJ-14 | Sidebar context-menu & session persistence                                      | ✅ Deployed  |

### DMS Pipeline Features

| ID      | Feature                                                                         | Status      |
| ------- | ------------------------------------------------------------------------------- | ----------- |
| PROJ-15 | DMS NAS folder management (CRUD via REST API + frontend)                        | ✅ Deployed  |
| PROJ-16 | DMS scanner & NAS multi-format scan                                             | ✅ Deployed  |
| PROJ-17 | DMS scanner multi-queue routing (PROJ-16 extension)                             | ✅ Deployed  |
| PROJ-18 | DMS text-extractor containers (pdf/ocr/txt/office → plaintext)                 | ✅ Deployed  |
| PROJ-19 | DMS processor workflow (LLM classification + Weaviate storage)                  | ✅ Deployed  |
| PROJ-20 | DMS document search tool (alice-tool-search)                                    | 🗓 Planned  |

---

## Architecture

```text
CLIENT (React PWA, HA Voice Devices)
    ↓
SPEECH GATEWAY [Phase 2] (Python: Whisper STT, Speaker-ID, Piper TTS)
    ↓
ORCHESTRATION (n8n + Ollama qwen3:14b via Tool-Use)
    ↓
DATA (Weaviate, PostgreSQL alice schema, Redis, NAS documents)
```

**Core principle:** One LLM call with native tool-use — no two-step routing. The model directly selects and executes tools: `home_assistant`, `search_documents`, `get_document_details`, `remember`, `recall`.

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

| Service                 | Purpose                                    |
| ----------------------- | ------------------------------------------ |
| `n8n`                   | AI orchestration, workflow engine          |
| `ollama-titan`          | LLM inference (TITAN X)                    |
| `weaviate`              | Vector search                              |
| `weaviate-transformers` | text2vec-transformers inference (RTX 3090) |
| `weaviate-multi2vec`    | CLIP multimodal embeddings (RTX 3090)      |
| `alice-ha-sync`         | HA entity sync worker (MQTT-triggered Python, replaces PROJ-4 n8n workflow) |
| `alice-dms-pdf`         | DMS text extractor: PDF → plaintext (pdfminer)                              |
| `alice-dms-ocr`         | DMS text extractor: image/scanned PDF → plaintext (Tesseract OCR)           |
| `alice-dms-office`      | DMS text extractor: Office documents → plaintext (LibreOffice headless)     |
| `alice-dms-txt`         | DMS text extractor: plain text passthrough                                  |
| `alice-auth`            | JWT authentication (FastAPI, bcrypt)       |
| `postgres`              | Structured data, alice schema, auth        |
| `redis`                 | Session cache, message queue               |
| `mqtt`                  | Event bus (alice/# topics)                 |
| `nginx`                 | Reverse proxy, React static files          |

---

## Memory Architecture (Three Tiers)

| Tier      | Store                            | Scope            | Contents                                |
| --------- | -------------------------------- | ---------------- | --------------------------------------- |
| Working   | PostgreSQL `alice.messages`      | Last 20 messages | Active session context                  |
| Long-term | Weaviate `AliceMemory`           | Permanent        | Semantic search over past conversations |
| Profile   | PostgreSQL `alice.user_profiles` | Permanent        | User facts, preferences                 |

---

## n8n Workflows

Workflows live in `workflows/`. Import via n8n UI or CLI. The main endpoint is `POST /webhook/alice`.

| Workflow                | Trigger                       | Purpose                        |
| ----------------------- | ----------------------------- | ------------------------------ |
| `alice-chat-handler`    | Webhook POST `/webhook/alice` | Main chat logic + memory       |
| `alice-tool-ha`         | Workflow call                 | Home Assistant REST API        |
| `alice-tool-search`     | Workflow call                 | Weaviate document search       |
| `alice-memory-transfer` | Schedule (daily)              | PostgreSQL → Weaviate transfer |
| `alice-dms-scanner`     | Schedule (hourly)             | NAS scan → MQTT queue          |
| `alice-dms-processor`   | Schedule (nightly)            | MQTT queue → Weaviate          |

---

## Domain Coverage

| Domain          | Capability                                                      |
| --------------- | --------------------------------------------------------------- |
| Smart Home      | Lights, climate, covers, locks, media players, switches, vacuum |
| Documents (DMS) | Invoices, bank statements, contracts, emails, securities        |
| Memory          | Persistent facts, conversation history, user preferences        |
| Finances        | [Phase 1.2+]                                                    |
| Calendar & Mail | [Phase 2+]                                                      |

---

## Latency Targets

| Phase                       | Target         | Maximum        |
| --------------------------- | -------------- | -------------- |
| LLM first token             | < 800 ms       | 1,500 ms       |
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
│   ├── automations/         # n8n, Weaviate, MQTT
│   ├── data/                # PostgreSQL
│   └── infra/               # nginx, Prometheus, Grafana, Gotify
├── docs/                    # Architecture docs and planning
│   └── planning/            # Concept documents (German)
├── features/                # Feature specs (PROJ-N-*.md) + INDEX.md
├── frontend/                # React + TypeScript + Tailwind PWA
├── schemas/                 # Weaviate collection schemas (JSON)
├── scripts/                 # Setup and init scripts
├── sql/                     # PostgreSQL schema migrations
├── workflows/               # n8n workflow exports (JSON)
├── scripts/                 # Operational scripts (sync, deploy, init)
│   └── sync-compose.sh      # Sync compose files to production server
└── .env.n8n.example         # Required n8n environment variables
```

---

## Quick Start (Development)

```bash
# 1. Copy and fill in environment file
cp .env.n8n.example docker/compose/automations/n8n/.env

# 2. Apply PostgreSQL schema
docker exec postgres psql -U alice_user -d alice -f sql/init-postgres.sql

# 3. Initialize Weaviate collections
./scripts/init-weaviate-schema.sh http://weaviate:8080

# 4. Set initial passwords for alice.users
./scripts/set-initial-passwords.sh

# 5. Start frontend dev server
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
