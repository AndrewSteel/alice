# CLAUDE.md

## Behavioral guidelines to reduce common LLM coding mistakes

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## Project Overview

**Alice** is a local-first, AI-first, speech-first personal assistant and smart home controller. The system uses n8n as the central AI orchestrator with Ollama (qwen3:14b) for LLM inference, with Weaviate for vector search and PostgreSQL for structured data/memory. Access is only via VPN.

Docs are in German; code comments and commit messages should be in English.

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

Workflows are stored as JSON in `workflows/`. Don't deploy n8n-workflow. Tell user: 'Deploy n8n-workflow {name}'. The main chat endpoint is `POST /webhook/alice`.

### Docker

Each service has its own compose file under `docker/compose/<category>/`. Use `scipts/sync-compose.sh` to sync compose files to the server.

## Architecture

### Layered System

```text
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

NAS inbox folders → `alice/dms/new` MQTT topic → PDF extraction + LLM classification → Weaviate collections (Invoice, BankStatement, Document, Email, SecuritySettlement, Contract).

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

Defined in `schemas/` directory as JSON files. Key collections: `AliceMemory`, `Invoice`, `BankStatement`, `BankTransaction`, `Document`, `Email`, `SecuritySettlement`, `Contract`. Vectorizer: `text2vec-transformers` on the TITAN X GPU.

### Frontend (in `frontend/src/`)

React + TypeScript + Tailwind CSS. Key structure:
- `components/Auth/` — AuthProvider (Context), LoginScreen, ProtectedRoute
- `components/Chat/` — ChatContainer, MessageList, MessageBubble, InputArea
- `components/Sidebar/` — session list
- `hooks/useChat.js` — sends messages with `user_id` from AuthContext
- `services/api.js` — chat API; `services/auth.js` — auth (JWT in localStorage)

### Infrastructure

- **nginx** (`docker/compose/infra/`) — reverse proxy + serves React static files from `nginx/html/alice/`; `/api/webhook/*` → n8n (300s timeout, no buffering for streaming)
- **Docker networks**: `frontend`, `backend`, `automation` (external, defined in `docker/compose/infra/networks/`)
- **Storage**: Hot (`/srv/hot`) for AI models/Weaviate index; Warm ZFS-mirror (`/srv/warm`) for persistent data (n8n, postgres, logs)
- **Monitoring**: Prometheus + Grafana + node_exporter + cadvisor + DCGM (GPU)

### Key Environment Variables

n8n needs: `HA_URL`, `HA_TOKEN`, `OLLAMA_URL`, `WEAVIATE_URL`, `POSTGRES_CONNECTION`, `REDIS_URL`, `MQTT_URL`, `JWT_SECRET`

## Feature Tracking

All features are tracked in `features/INDEX.md`. Read it before starting any new feature. Feature specs go in `features/PROJ-X-feature-name.md`. Use `/requirements` skill to create new specs.

## Workflow Skills

Use skills for structured work:
- `/requirements` — create feature specs
- `/architecture` — design before building
- `/frontend` — build React components
- `/backend` — build n8n workflows / DB schemas
- `/qa` — test against acceptance criteria
- `/deploy` — deploy to production
