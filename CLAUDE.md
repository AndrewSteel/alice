# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Alice** is a local-first, AI-first, speech-first personal assistant and smart home controller. The system uses n8n as the central AI orchestrator with Ollama (qwen3:14b) for LLM inference, with Weaviate for vector search and PostgreSQL for structured data/memory. Access is only via VPN.

Docs are in German; code comments and commit messages should be in English.

## Key Commands

### Frontend (React/Vite)
```bash
cd frontend && npm ci          # Install dependencies
cd frontend && npm run build   # Build for production
./scripts/deploy-frontend.sh   # Build + deploy to nginx html/ (root, finance_upload excluded)
```

### Database
```bash
# Initialize PostgreSQL schema (alice.* schema)
docker exec postgres psql -U user -d alice -f /path/to/sql/init-postgres.sql

# Seed users (kept out of git - create separately)
docker exec postgres psql -U user -d alice -f /path/to/sql/seed-users.sql

# Initialize Weaviate collections
./scripts/init-weaviate-schema.sh
```

### n8n Workflows
Workflows are stored as JSON in `workflows/`. Import/export via n8n UI or CLI. The main chat endpoint is `POST /webhook/alice`.

### Docker
Each service has its own compose file under `docker/compose/<category>/`. Use `sync-compose.sh` to sync compose files to the server.

## Architecture

### Layered System
```
CLIENT (React PWA, HA Voice Devices)
    ↓
SPEECH GATEWAY [Phase 2] (Python: Whisper STT, Speaker-ID, Piper TTS)
    ↓
ORCHESTRATION (n8n + Ollama qwen3:14b via Tool-Use)
    ↓
DATA (Weaviate, PostgreSQL alice schema, Redis, NAS documents)
```

### Principle: One LLM call with Tool-Use (not two-step router)
The LLM uses native function calling to directly select and execute tools. Available tools: `home_assistant`, `search_documents`, `get_document_details`, `remember`, `recall`.

### Three-Tier Memory
- **Tier 1 (Working)**: PostgreSQL `alice.messages` — last 20 messages of active session
- **Tier 2 (Long-term)**: Weaviate `AliceMemory` — semantic search over past conversations
- **Tier 3 (Profile)**: PostgreSQL `alice.user_profiles` — permanent user facts/preferences

### n8n Workflows (in `workflows/`)
| Workflow                | Trigger                       | Purpose                                   |
| ----------------------- | ----------------------------- | ----------------------------------------- |
| `alice-chat-handler`    | Webhook POST `/webhook/alice` | Main chat logic + memory                  |
| `alice-tool-ha`         | Workflow call                 | Home Assistant REST API                   |
| `alice-tool-search`     | Workflow call                 | Weaviate document search                  |
| `alice-memory-transfer` | Schedule (daily)              | PostgreSQL → Weaviate transfer            |
| `alice-dms-scanner`     | Schedule (hourly)             | NAS scan → MQTT queue                     |
| `alice-dms-processor`   | Schedule (nightly)            | MQTT queue → Weaviate                     |
| Auth workflows          | Webhook                       | Login/validate/refresh/logout (Phase 1.5) |

### DMS Pipeline
NAS inbox folders → `alice/dms/new` MQTT topic → PDF extraction + LLM classification → Weaviate collections (Rechnung, Kontoauszug, Dokument, Email, WertpapierAbrechnung, Vertrag).

### PostgreSQL Schema (`alice`)
All tables live in the `alice` schema. Key tables:
- `alice.users` — users with role (`admin`/`user`/`guest`/`child`)
- `alice.permissions_home_assistant` — per-domain HA permissions with optional area/entity/time filters
- `alice.permissions_dms` — per-doc-type DMS permissions
- `alice.permissions_system` / `alice.permissions_assistant` — system and chat feature permissions
- `alice.role_templates` — seeded permission templates; applied via `alice.init_user_permissions(user_id, role)`
- `alice.messages` / `alice.sessions` / `alice.user_profiles` — agent memory
- `alice.auth_sessions` / `alice.webauthn_challenges` — authentication

Permission checks use PL/pgSQL functions: `alice.check_ha_permission()` and `alice.check_dms_permission()`.

### Weaviate Collections
Defined in `schemas/` directory as JSON files. Key collections: `AliceMemory`, `Rechnung`, `Kontoauszug`, `Dokument`, `Email`, `WertpapierAbrechnung`, `Vertrag`. Vectorizer: `text2vec-transformers` on the TITAN X GPU.

### Frontend (in `frontend/src/`)
React + TypeScript + Tailwind CSS. Key structure:
- `components/Auth/` — AuthProvider (Context), LoginScreen, ProtectedRoute
- `components/Chat/` — ChatContainer, MessageList, MessageBubble, InputArea
- `components/Sidebar/` — session list
- `hooks/useChat.js` — sends messages with `user_id` from AuthContext
- `services/api.js` — chat API; `services/auth.js` — auth (JWT in localStorage)

**Phase 1 note**: Auth runs in "auto-login" mode (default user `andreas`). Phase 1.5 adds real password login. Phase 2 adds WebAuthn + speaker recognition.

### Infrastructure
- **nginx** (`docker/compose/infra/`) — reverse proxy + serves React static files from `nginx/html/alice/`; `/api/webhook/*` → n8n (300s timeout, no buffering for streaming)
- **Docker networks**: `frontend`, `backend`, `automation` (external, defined in `docker/compose/infra/networks/`)
- **Storage**: Hot (`/srv/hot`) for AI models/Weaviate index; Warm ZFS-mirror (`/srv/warm`) for persistent data (n8n, postgres, logs)
- **Monitoring**: Prometheus + Grafana + node_exporter + cadvisor + DCGM (GPU)

### Key Environment Variables
n8n needs: `HA_URL`, `HA_TOKEN`, `OLLAMA_URL`, `WEAVIATE_URL`, `POSTGRES_CONNECTION`, `REDIS_URL`, `MQTT_URL`, `JWT_SECRET`

## Feature Tracking

All features are tracked in `features/INDEX.md`. Read it before starting any new feature. Feature specs go in `features/PROJ-X-feature-name.md`. Use `/requirements` skill to create new specs.

## Development Phases

- **Phase 0**: Hardware setup ✅
- **Phase 1**: Chat MVP (n8n + React + HA + DMS) — current focus
- **Phase 1.5**: JWT auth / login screen
- **Phase 2**: Speech gateway (Whisper STT + Piper TTS + Speaker-ID)
- **Phase 3**: Multi-user handling, display routing, security hardening

## Workflow Skills

Use skills for structured work:
- `/requirements` — create feature specs
- `/architecture` — design before building
- `/frontend` — build React components
- `/backend` — build n8n workflows / DB schemas
- `/qa` — test against acceptance criteria
- `/deploy` — deploy to production
