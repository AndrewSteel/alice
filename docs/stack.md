# Stack: Alice

Verbindlich für die Software Factory und für die lokale Entwicklung. Details zu Konventionen stehen in `CLAUDE.md` und `.claude/rules/*.md`.

## Stack-Packs

- `docker-services`
- `postgres`
- `redis`
- `weaviate`
- `n8n`
- `nextjs-static`

## Überblick

| Bereich | Technik | Ort im Repo |
|---|---|---|
| Dienste | Python 3.12 (FastAPI/Starlette), je ein Docker-Container | `docker/compose/automations/<dienst>/` |
| Orchestrierung | n8n-Workflows (JSON-Export, Deploy macht der Mensch) | `workflows/` |
| Frontend | Next.js 15, statischer Export (`output: "export"`), Tailwind, Radix/shadcn, react-i18next | `frontend/` |
| Relationale Daten | PostgreSQL 16, Schema `alice` | `sql/init-schema.sql` |
| Kurzlebiger Zustand | Redis 7 | – |
| Vektoren / Suche | Weaviate 1.33 (multi2vec-clip, text2vec-transformers) | `schemas/`, `scripts/init-weaviate-schema.sh` |
| Inferenz | lokal (llama.cpp/Ollama hinter `alice-llm-gateway`) | `docker/compose/ai/` |
| Routing | nginx | `docker/compose/infra/nginx/` |

## Änderungen Phase 4 (geplant)

Beschlossen in der Phasenplanung 2026-11-20 (`docs/PRD.md`). Was noch nicht gebaut ist, gilt erst mit dem jeweiligen Feature.

| Bereich | Änderung | Feature | Test in der Factory |
|---|---|---|---|
| Quelle der Wahrheit | Eigener NAS-Ordner mit Markdown-Dateien, Git-versioniert (`git` im Dienst-Container) | PROJ-115 | temporäres Git-Repo im Job-Ordner |
| Orchestrierung | n8n entfällt; alle Workflows werden Python/FastAPI-Dienste. Stack-Pack `n8n` und `scripts/check-workflows.sh` werden erst bei der Abschaltung entfernt | PROJ-142 | wie alle Dienste |
| Agent-Framework | offen bis zum Spike; Favorit DeepSeek Harness (Node/TypeScript). Fällt die Wahl darauf, braucht `.factory/setup.json` einen Node-Check (setzt der Mensch lokal) | PROJ-133 | lokales LLM gemockt (OpenAI-kompatibler Fake-Server) |
| Cloud-LLM | unverändertes Claude Code CLI (`claude -p`) im Container, Login des Admins als Volume; später zusätzlich Anthropic API mit Budget-Stopp | PROJ-136, PROJ-137 | Fake-`claude`-Binary bzw. HTTP-Mock; nie echte Zugangsdaten |
| Queues/Events | keine neue Infrastruktur: MQTT, Redis (nur Queue/Lock), PostgreSQL (Zustand) | PROJ-115 ff. | Wegwerf-Postgres/Redis/MQTT |

## Tests

- Dienste: `scripts/test-services.sh` (pytest pro Dienst; Integrationstests gegen Wegwerf-Postgres/Redis aus `docker/test/compose.test.yml`)
- Container: `scripts/test-containers.sh` (baut jeden geänderten Dienst aus seinem `Dockerfile`, startet ihn mit den Wegwerf-Datenbanken, wartet auf den Healthcheck; Testwerte in `tests/container.env`, `tests/container-secrets/`, Rauchtest `tests/container-smoke.sh`)
- Kein Staging (entschieden 2026-11-24): nach dem Merge wird direkt deployt, Live-Tests laufen in Produktion. In den „Deploy-Schritte“ des PRs keine `scripts/stage.sh`-Schritte aufführen; was live zu prüfen ist, steht unter den Live-Tests
- n8n: `scripts/check-workflows.sh` (Struktur, Verbindungen, kein `console.log`)
- Frontend: `npx tsc --noEmit`, `npm run build`

## Was die Factory nie tut

- Nichts deployen: keine n8n-Workflows importieren, keine Container auf dem Server neu starten, kein `sync-compose.sh`, kein `deploy-frontend.sh`, kein `stage.sh`.
- `.factory/setup.json`, `scripts/test-services.sh`, `scripts/test-containers.sh`, `scripts/stage.sh` und `scripts/lib/` nicht ändern (geschützt, der Bau wird sonst abgelehnt).
- Keine echte Datenbank, kein echtes Weaviate, kein Home Assistant, kein produktives LLM ansprechen.
- Keine `.env`-Dateien anlegen oder lesen. Neue Variablen kommen als Platzhalter in die `.env.example` des Dienstes.
