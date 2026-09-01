# llama-3090 (PROJ-99)

llama.cpp `llama-server` in **router mode** on the RTX 3090. Replaces the
retired `ollama-3090` Ollama instance as the single inference endpoint for all
Alice consumers. `ollama-titan` (TITAN X, Jupyter) is unaffected.

## Endpoint

- Internal: `http://llama-3090:11434` — OpenAI-compatible, paths under `/v1`
  (`/v1/chat/completions`, `/v1/models`). `/health` for liveness.
- External (VPN only): `https://llama3090.happy-mining.de`
  (nginx `conf.d/llama-3090.conf`). The old `ollama3090.happy-mining.de`
  returns a permanent 301 to this host.

## Models (dynamic, one resident at a time)

Router loads a model on first request and unloads it after 15 min idle
(`--sleep-idle-seconds 900`, `--models-max 1`). Request a model by its
preset section name in the `model` field:

| Model ID (`model` field) | Role |
| --- | --- |
| `qwen3.5:27b-q4_K_M` | chat/agent + vision (matches old Ollama name) |
| `mistral-small3.2:24b` | DMS text extraction (matches old Ollama name) |

## Files on the server (Docker volume `/srv/hot/models/llama-cpp/`)

- `presets.ini` — copy from `presets.ini.example`, fill in the real GGUF
  filenames. NOT synced by `sync-compose.sh`.
- `*.gguf` + `*-mmproj-*.gguf` — the quantised model + vision projector.
  Same quant level (q4_K_M) as the retired Ollama models.
- `cache/` — llama.cpp HF download cache.

## Secret

`/srv/warm/llama-3090/llama_api_key` — single line, the bearer token every
consumer sends as `Authorization: Bearer <key>` (`OLLAMA_API_KEY` in consumer
`.env`). Server-side only, never committed.

## Rollback

Stop `llama-3090`, start `ollama-3090`, revert consumer `.env` to
`http://ollama-3090:11434` + Ollama model names, restore `ollama-3090.conf` as
a proxy and disable `llama-3090.conf`, re-sync, reload nginx. The
`ollama-3090` container definition and its model volume are kept for a grace
period — see the PROJ-99 spec.
