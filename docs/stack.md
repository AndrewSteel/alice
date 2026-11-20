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

## Tests

- Dienste: `scripts/test-services.sh` (pytest pro Dienst; Integrationstests gegen Wegwerf-Postgres/Redis aus `docker/test/compose.test.yml`)
- Container: `scripts/test-containers.sh` (baut jeden geänderten Dienst aus seinem `Dockerfile`, startet ihn mit den Wegwerf-Datenbanken, wartet auf den Healthcheck; Testwerte in `tests/container.env`, `tests/container-secrets/`, Rauchtest `tests/container-smoke.sh`)
- Staging vor dem Deploy (nur der Mensch): `scripts/stage.sh <dienst> <PR>` startet `<dienst>-staging` neben der Produktion mit echter `.env`, ohne nginx-Route und ohne den DNS-Namen des Produktivdienstes
- n8n: `scripts/check-workflows.sh` (Struktur, Verbindungen, kein `console.log`)
- Frontend: `npx tsc --noEmit`, `npm run build`

## Was die Factory nie tut

- Nichts deployen: keine n8n-Workflows importieren, keine Container auf dem Server neu starten, kein `sync-compose.sh`, kein `deploy-frontend.sh`, kein `stage.sh`.
- `.factory/setup.json`, `scripts/test-services.sh`, `scripts/test-containers.sh`, `scripts/stage.sh` und `scripts/lib/` nicht ändern (geschützt, der Bau wird sonst abgelehnt).
- Keine echte Datenbank, kein echtes Weaviate, kein Home Assistant, kein produktives LLM ansprechen.
- Keine `.env`-Dateien anlegen oder lesen. Neue Variablen kommen als Platzhalter in die `.env.example` des Dienstes.
