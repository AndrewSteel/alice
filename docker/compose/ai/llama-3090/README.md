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

Router keeps ONE model resident (`--models-max 1`) and has **no idle-unload**
(replaces Ollama's `OLLAMA_KEEP_ALIVE=-1`): a model stays loaded until a request
for the *other* model evicts it. Request a model by its preset section name in
the `model` field.

The **model IDs keep the old Ollama tag strings** (`qwen3.5:27b-q4_K_M`,
`mistral-small3.2:24b`) so no consumer prompt/config changes — but those tags
are local names, the actual upstream models are:

| Model ID (`model` field) | Actual model | Role |
| --- | --- | --- |
| `qwen3.5:27b-q4_K_M` | **Qwen3-VL-30B-A3B-Instruct** (MoE, ~30 B total / ~3 B active), Q4_K_M + F16 mmproj | chat/agent + vision |
| `mistral-small3.2:24b` | **Mistral-Small-3.2-24B-Instruct-2506** (dense 24 B), Q4_K_M, text only | DMS text extraction |

### VRAM budget (the 3090's 24 GB is shared)

Permanently resident on the RTX 3090, independent of llama.cpp:

| Container | Model | VRAM |
| --- | --- | --- |
| `weaviate-transformers` | paraphrase-multilingual-MiniLM-L12-v2 | ~3.3 GB |
| `weaviate-multi2vec` | CLIP-ViT-B-32-multilingual-v1 | ~1.4 GB |
| **Weaviate total** | | **~4.7 GB** → leaves **~19 GB** for llama.cpp |

| llama.cpp model (one at a time) | VRAM |
| --- | --- |
| Qwen3-VL-30B-A3B Q4_K_M (~18.6 GB) + F16 mmproj (~1.1 GB) + KV @ ctx 8192 | **~20 GB** — tight, this is the constraint |
| Mistral-Small-24B Q4_K_M (~14 GB) + KV | ~15 GB — comfortable |

Under Ollama this exact pairing (qwen + both Weaviate modules) already ran at
**~23.7 / 24 GB** with ~0.9 GB free — so it works, but there is no slack.
`presets.ini` therefore ships `ctx-size = 8192` (vs. the model's 262 k max); the
DMS extraction prompts and the chat agent loop stay well under that. If qwen
fails to load at cutover, drop `ctx-size` further (4096) before touching
anything else. Both models at once do **not** fit → `--models-max 1`. The Qwen
MoE loads/unloads noticeably faster than a dense model of similar size, which
softens the model-switch gap.

### Daily model timeline (all UTC — n8n cron runs UTC)

| ~Time | Trigger | Resident model after |
| --- | --- | --- |
| 02:00 | `alice-dms-processor` (nightly DMS run) | mistral |
| 05:00 | `alice-llm-model-warmup` (this feature) | **qwen** — warmed before the working day so the first morning chat has no cold-load delay |
| daytime | chat / agent requests | qwen (stays resident, no idle-unload) |

`load-on-startup = true` on qwen in `presets.ini` also warms it right after a
container (re)start.

## Files on the server (Docker volume `/srv/hot/models/llama-cpp/`)

- `presets.ini` — copy from `presets.ini.example`, fill in the real GGUF
  filenames. NOT synced by `sync-compose.sh`.
- `*.gguf` + `mmproj-*.gguf` — the quantised model + (qwen only) the vision
  projector. Same quant level (q4_K_M) as the retired Ollama models.
- `cache/` — llama.cpp HF download cache (only used by the `hf:` preset form).

## Getting the GGUF files onto the server

Unlike Ollama, `llama-server` has **no model registry and no `ollama pull`**.
The `ghcr.io/ggml-org/llama.cpp:server-cuda` image also ships **no Python and no
`huggingface-cli`** — download on the host, not inside the container.

### About the vision projector (`mmproj`)

A vision model is two GGUF files: the **language weights** (`*-q4_k_m.gguf`) and
a separate **multimodal projector** (`mmproj-*.gguf`, the image encoder).
Ollama bundles both in one manifest, which is why you never saw a separate file.
llama.cpp needs the projector passed explicitly (`mmproj =` in the preset) —
without it the model silently ignores images.

- **qwen** is used for chat **and** vision (`dms-extractor-image`,
  `alice-dms-image-description-backfill`) → needs `model` **+** `mmproj`.
- **mistral** is only used for DMS **text** extraction (classification, field
  extraction from plaintext) → `model` only, no `mmproj`.

If you ever need to re-check what the Ollama tags map to:

```bash
# on ki.lan
docker exec ollama-3090 ollama show qwen3.5:27b-q4_K_M          # arch qwen35, 27.8B, vision, Q4_K_M
docker exec ollama-3090 ollama show mistral-small3.2:24b        # Mistral Small 3.2
```

### Download to the model volume (on the host)

```bash
# one-time: huggingface CLI on the HOST (not the container)
pipx install "huggingface_hub[cli]"        # or: pip install -U "huggingface_hub[cli]"

cd /srv/hot/models/llama-cpp

# --- chat / vision model: Qwen3-VL-30B-A3B-Instruct (weights + vision projector) ---
huggingface-cli download Qwen/Qwen3-VL-30B-A3B-Instruct-GGUF \
  Qwen3VL-30B-A3B-Instruct-Q4_K_M.gguf \
  mmproj-Qwen3VL-30B-A3B-Instruct-F16.gguf \
  --local-dir .

# --- DMS text model: Mistral-Small-3.2-24B-Instruct-2506, weights only ---
# Option A: official repo (GATED — needs `huggingface-cli login` + accepting the
#           licence at https://huggingface.co/mistralai/Mistral-Small-3.2-24B-Instruct-2506)
huggingface-cli download mistralai/Mistral-Small-3.2-24B-Instruct-2506-GGUF \
  <official-Q4_K_M-filename>.gguf --local-dir .
# Option B: open community re-quant (no login) — recommended if you don't want
#           to deal with the gate. Same base model, Q4_K_M:
huggingface-cli download bartowski/mistralai_Mistral-Small-3.2-24B-Instruct-2506-GGUF \
  mistralai_Mistral-Small-3.2-24B-Instruct-2506-Q4_K_M.gguf --local-dir .
```

Then set the filenames in `presets.ini`:

```ini
[qwen3.5:27b-q4_K_M]
model  = Qwen3VL-30B-A3B-Instruct-Q4_K_M.gguf
mmproj = mmproj-Qwen3VL-30B-A3B-Instruct-F16.gguf
load-on-startup  = true
reasoning-format = deepseek

[mistral-small3.2:24b]
model = mistralai_Mistral-Small-3.2-24B-Instruct-2506-Q4_K_M.gguf
```

Verify: `ls -lh /srv/hot/models/llama-cpp/*.gguf` — Qwen Q4_K_M ≈ 18.6 GB,
mmproj-F16 ≈ 1.1 GB, Mistral Q4_K_M ≈ 14 GB.

### Alternative — let llama.cpp pull from HF on first request

Instead of downloading, reference the repo directly; the router fetches into
`cache/` on the first request for that model:

```ini
[qwen3.5:27b-q4_K_M]
model  = hf:Qwen/Qwen3-VL-30B-A3B-Instruct-GGUF:Q4_K_M
mmproj = hf:Qwen/Qwen3-VL-30B-A3B-Instruct-GGUF:mmproj-F16
```

Trade-offs: the container then needs outbound internet (and an `HF_TOKEN` env
for the gated Mistral repo), and the **first** request blocks for the full
~20 GB download. For the cutover, prefer the explicit download above so it
happens up front and you can verify quant parity before the hard switch.

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
