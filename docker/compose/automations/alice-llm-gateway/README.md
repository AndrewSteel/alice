# alice-llm-gateway (PROJ-111)

Priority gateway in front of `llama-3090`. llama.cpp has one slot
(`parallel = 1`) and serves strictly first-come-first-served, so a chat request
used to wait behind the whole DMS analysis queue. The gateway hands the slot
out by priority: **human before machine**.

| Tier          | Callers (key name in `clients`)                                                          |
| ------------- | ---------------------------------------------------------------------------------------- |
| `interactive` | `chat-stream` (WebApp + Voice PE), `openwebui`, `external` (`llama3090.happy-mining.de`) |
| `background`  | `n8n` (all workflows), `dms-extractor-image`, and any key not marked `interactive`       |

- When the slot frees up, the oldest waiting interactive request goes next;
  only if none waits, the oldest background request. FIFO within a tier.
- At most **one** chat completion is forwarded to `llama-3090` at any time. A
  running background request is never aborted.
- The tier comes from the caller's key only — nothing in the request can change it.
- A caller that hangs up while waiting is dropped from the queue; one that
  hangs up while running frees the slot and the upstream connection is closed
  (llama.cpp stops generating).
- Queue wait is **not** limited by the gateway; the callers' own timeouts apply
  (chat 120 s, extractor 300 s). `UPSTREAM_READ_TIMEOUT_SECONDS` (default 900)
  only guards against a hung `llama-3090`.
- The queue is in memory. A gateway restart drops waiting requests; callers see
  an error and use their normal error paths. There is no direct fallback to
  `llama-3090`.

## Endpoints (port 8011)

| Path                        | Auth       | Notes                                                                                                     |
| --------------------------- | ---------- | --------------------------------------------------------------------------------------------------------- |
| `POST /v1/chat/completions` | caller key | queued for the slot; body and response (incl. SSE stream, reasoning, tool calls) passed through unchanged |
| `GET /v1/models`            | caller key | forwarded directly, does not use the GPU slot (router metadata)                                           |
| `GET /health`               | –          | gateway liveness + `upstream` reachability + queue lengths                                                |
| `GET /metrics`              | –          | Prometheus (internal only; nginx returns 404 externally)                                                  |

Everything else returns 404 — the gateway is not an open proxy onto llama.cpp.
Missing/wrong key → `401`, nothing forwarded. `llama-3090` unreachable → `502`
(`504` on connect/read timeout); upstream error statuses are passed through.

## Observability

One JSON log line per request (`docker logs alice-llm-gateway`):

```json
{"event": "llm_request", "caller": "chat-stream", "tier": "interactive", "path": "/v1/chat/completions",
 "queued": true, "wait_ms": 1840, "upstream_ms": 3120, "outcome": "ok", "status": 200}
```

`outcome`: `ok` | `error` | `timeout` | `client_abort`. Rejected keys log
`llm_request_rejected`.

Prometheus job `llm-gateway`:

| Metric                                       | Labels                                 |
| -------------------------------------------- | -------------------------------------- |
| `llm_gateway_queue_length`                   | `tier`                                 |
| `llm_gateway_slot_busy`                      | –                                      |
| `llm_gateway_queue_wait_seconds` (histogram) | `tier`                                 |
| `llm_gateway_upstream_seconds` (histogram)   | `tier`                                 |
| `llm_gateway_requests_total`                 | `tier`, `outcome`                      |
| `llm_gateway_rejected_total`                 | `reason` (`unauthorized`, `too_large`) |

e.g. p95 chat wait: `histogram_quantile(0.95, rate(llm_gateway_queue_wait_seconds_bucket{tier="interactive"}[1h]))`.

## Secrets (server only, never committed)

| Path                                 | Mode            | Content                                                          |
| ------------------------------------ | --------------- | ---------------------------------------------------------------- |
| `/srv/warm/llm-gateway/`             | `700 root:root` |                                                                  |
| `/srv/warm/llm-gateway/clients`      | `600 root:root` | `<name> <tier> <key>` per caller — format in `clients.example`   |
| `/srv/warm/llama-3090/llama_api_key` | `600 root:root` | existing llama key, mounted read-only; known only to the gateway |

## Rollout (order matters)

1. **Network + secrets** on the server:

   ```bash
   docker network create llm            # or: make networks
   sudo mkdir -p /srv/warm/llm-gateway && sudo chmod 700 /srv/warm/llm-gateway
   # one key per caller: openssl rand -hex 32
   sudo cp clients.example /srv/warm/llm-gateway/clients && sudo chmod 600 /srv/warm/llm-gateway/clients
   sudo $EDITOR /srv/warm/llm-gateway/clients
   cp .env.example .env
   ```

2. **Attach llama-3090 to `llm` without restarting it** (keeps the old networks
   until step 5): `docker network connect llm llama-3090`
3. **Start + test the gateway**:
   `docker compose -f /srv/compose/automations/alice-llm-gateway/compose.yml up -d --build`,
   then `curl -s http://alice-llm-gateway:8011/health` (from a container on
   `frontend`) → `"upstream": true`; a `GET /v1/models` with a caller key → 200.
4. **Switch callers one at a time** (`OLLAMA_URL=http://alice-llm-gateway:8011`,
   `OLLAMA_API_KEY=<own key>`), recreating each: `alice-chat-stream`,
   `dms-extractor-image`, `n8n`, `openwebui`. **OpenWebUI ignores
   `OPENAI_API_BASE_URL`/`OPENAI_API_KEY` after its first start** (PersistentConfig
   in `webui.db`) — set the connection in the UI instead: *Admin Panel → Settings →
   Connections → OpenAI API*: URL `http://alice-llm-gateway:8011/v1`, key = the
   `openwebui` gateway key, then "Verify connection". Watch `docker logs -f alice-llm-gateway` for each caller's first
   `llm_request` line. Then nginx (`llama-3090.conf`) reload — external users
   need the new `external` key. Reload Prometheus (job `llm-gateway`).
5. **Isolate llama-3090**: `docker compose -f /srv/compose/ai/llama-3090/compose.yml up -d`
   (compose now lists only `llm`). From now on the gateway cannot be bypassed.
   Check: `docker exec n8n wget -qO- http://llama-3090:11434/health` must fail.
6. Optional: rotate `/srv/warm/llama-3090/llama_api_key` (the old value was in
   five `.env` files) and recreate `llama-3090` + `alice-llm-gateway`.

## Rollback

1. `ai/llama-3090/compose.yml`: `networks: [frontend, backend, automation]`
   (+ the three external network definitions), `up -d`.
2. Callers back to `OLLAMA_URL=http://llama-3090:11434` and
   `OLLAMA_API_KEY=<llama-3090 key>` (`/srv/warm/llama-3090/llama_api_key`);
   OpenWebUI: connection in the Admin UI (see rollout step 4) back to
   `http://llama-3090:11434/v1` + llama key. Recreate each.
3. nginx `llama-3090.conf`: `set $llama_3090_upstream http://llama-3090:11434;`, reload.
4. `docker compose -f …/alice-llm-gateway/compose.yml down`.

No data migration either way — the gateway keeps no state.

## Tests

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Integration tests run the real gateway and a fake `llama-3090` under uvicorn
(real HTTP, streaming and disconnects) — no Docker or GPU needed.
