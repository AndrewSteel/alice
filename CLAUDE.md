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

---

## Project Overview

**Alice** is a local-first, AI-first, speech-first personal assistant and smart home controller. All inference runs on local hardware via Ollama (qwen3:14b). Access is only via VPN.

Docs are in German; code comments and commit messages should be in English.

→ **See `README.md`** for architecture, infrastructure, Docker services, n8n workflows, DMS pipeline, and full feature list.

---

## Development Commands

### Frontend (React/Next.js)

```bash
cd frontend && npm ci          # Install dependencies
cd frontend && npm run build   # Build for production
./scripts/deploy-frontend.sh   # Build + deploy to nginx html/
./scripts/sync-compose.sh      # Sync compose files to production server
```

### Database

```bash
# Apply consolidated schema (Phase 1 final)
docker exec -i postgres psql -U user -d alice < sql/init-schema.sql

# Seed users (copy example, edit, then run)
cp sql/seed-users.example.sql sql/seed-users.sql
docker exec -i postgres psql -U user -d alice < sql/seed-users.sql

# Initialize Weaviate collections
./scripts/init-weaviate-schema.sh
```

### n8n Workflows

Workflows are stored as JSON in `workflows/`. Don't deploy n8n-workflows directly — tell the user: `Deploy n8n-workflow {name}`.

Primary chat endpoint: `POST /api/stream/chat` (alice-chat-stream).
Legacy fallback: `POST /webhook/alice` (alice-chat-handler n8n workflow).

### Docker

Each service has its own compose file under `docker/compose/<category>/`. Use `./scripts/sync-compose.sh` to sync compose files to the server.

---

## Code Reference

### Frontend source structure (`frontend/src/`)

- `components/Auth/` — AuthProvider (Context), LoginScreen, ProtectedRoute
- `components/Chat/` — ChatContainer, MessageList, MessageRenderer, InputArea
- `components/Sidebar/` — session list with context-menu
- `components/Settings/` — SettingsPage (tabs: profile, user management, DMS folders)
- `hooks/useChatSessions.ts` — SSE stream handling, tool-status events, thinking tokens
- `services/api.js` — streaming chat API; `services/auth.js` — auth (JWT in localStorage)
- `services/dms.ts` — DMS folder CRUD

### PostgreSQL schema (`alice`)

All tables live in the `alice` schema. Schema source: `sql/init-schema.sql`.

Key tables:
- `alice.users` — users with role (`admin`/`user`/`guest`/`child`), bcrypt password, must_change_password
- `alice.permissions_home_assistant` — per-domain HA permissions with optional area/entity/time filters
- `alice.permissions_dms` — per-doc-type DMS permissions (doc_types: Invoice, BankStatement, BankTransaction, SecuritySettlement, Document, Email, Contract, *)
- `alice.permissions_system` / `alice.permissions_assistant` — system and chat feature permissions
- `alice.role_templates` — seeded permission templates; applied via `alice.init_user_permissions(user_id, role)`
- `alice.messages` / `alice.sessions` / `alice.user_profiles` — agent memory
- `alice.auth_sessions` / `alice.webauthn_challenges` — authentication
- `alice.dms_watched_folders` — NAS folders watched by DMS scanner (with sort_order)
- `alice.ha_entities` / `alice.ha_intent_templates` / `alice.ha_sync_log` — HA sync state

Permission check functions: `alice.check_ha_permission()`, `alice.check_dms_permission()`.

### Key Environment Variables

| Variable              | Used by            | Purpose                               |
| --------------------- | ------------------ | ------------------------------------- |
| `HA_URL`              | n8n, alice-ha-sync | Home Assistant base URL               |
| `HA_TOKEN`            | n8n, alice-ha-sync | Long-lived HA access token            |
| `OLLAMA_URL`          | alice-chat-stream  | Ollama inference endpoint             |
| `WEAVIATE_URL`        | n8n, alice-ha-sync | Weaviate HTTP endpoint                |
| `POSTGRES_CONNECTION` | n8n                | PostgreSQL connection string          |
| `REDIS_URL`           | n8n                | Redis connection URL                  |
| `MQTT_URL`            | n8n, extractors    | MQTT broker URL                       |
| `JWT_PUBLIC_KEY_PATH` | alice-chat-stream  | RS256 public key for JWT verification |

Full variable list: see `.env.n8n.example` and each container's `.env` file.

### nginx routing

Config lives in `docker/compose/infra/nginx/`. Key proxy rules:
- `/api/stream/` → `alice-chat-stream:8003` (SSE: buffering off, `proxy_read_timeout 300s`)
- `/api/webhook/` → `n8n:5678` (300s timeout)
- `/api/auth/` → `alice-auth:8001`
- Static files served from `nginx/html/alice/`

---

## Feature Tracking

All features are tracked in `features/INDEX.md`. Read it before starting any new feature. Feature specs go in `features/PROJ-X-feature-name.md`. Use `/requirements` skill to create new specs.

---

## Workflow Skills

Use skills for structured work:
- `/requirements` — create feature specs
- `/architecture` — design before building
- `/frontend` — build React components
- `/backend` — build n8n workflows / DB schemas
- `/qa` — test against acceptance criteria
- `/deploy` — deploy to production
