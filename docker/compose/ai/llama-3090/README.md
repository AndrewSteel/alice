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

The model IDs are the **preset section names** and must be **colon-free** —
llama.cpp parses a `:` in a section name as a `name:tag` split and rewrites it
(`[qwen3.5:27b-q4_K_M]` got exposed as `qwen3.5:Q4_K_M`). Consumers send these
strings in the `model` field (`$env.OLLAMA_MODEL` / `OLLAMA_MODEL_DMS` /
`OLLAMA_VISION_MODEL`):

| Model ID (`model` field) | Actual model | Role |
| --- | --- | --- |
| `qwen3-vl-30b` | **Qwen3-VL-30B-A3B-Instruct** (MoE, ~30 B total / ~3 B active), Q4_K_M + F16 mmproj | chat/agent + vision |
| `mistral-small-3.2-24b` | **Mistral-Small-3.2-24B-Instruct-2506** (dense 24 B), Q4_K_M, text only | DMS text extraction |

### VRAM budget (the 3090's 24 GB is shared)

Measured on 2026-09-02 with qwen loaded and `parallel = 1`:

| Process | VRAM | Note |
| --- | --- | --- |
| `llama-server` (qwen3-vl-30b, ctx 16384, mmproj, image-min-tokens 1024, parallel 1) | **~20.9 GB** | one model resident |
| `weaviate-transformers` (MiniLM) | ~0.8 GB | was ~3.3 GB → `PYTORCH_CUDA_ALLOC_CONF` cap on the container brought it down |
| `weaviate-multi2vec` (CLIP) | ~1.4 GB | unchanged — vision encoder, kept on GPU |
| **Total** | **~23.1 / 24 GB** | ~1.5 GB free |
| — Mistral-Small-24B instead of qwen | ~14 GB + Weaviate → ~16 GB | comfortable |

`ctx-size = 16384` is the **working minimum for the agent tool loop** (last 20
turns + system prompt + 7-tool schema + up to 4 rounds of tool-result JSON;
search hits can be large). 8192 overflows the moment a search returns many
results — and the agent loop is the whole reason for this migration.

Two settings keep qwen inside the shared budget:

- **`parallel = 1`** in the qwen preset — one KV-cache slot instead of the
  default 4. Alice runs one sequential chat stream per user; 4 slots × 16k ctx
  would cost ~3–4 GB extra and OOM. Concurrent chats serialise (fine for 1–2
  users).
- **`PYTORCH_CUDA_ALLOC_CONF`** on `t2v-transformers` (in
  `weaviate/compose.yml`) — caps the CUDA caching allocator; MiniLM is ~470 MB,
  the 3.3 GB was mostly reserve, now ~0.8 GB.

`image-min-tokens = 1024` (also in the qwen preset) is a quality setting, not a
VRAM one: Qwen3-VL needs ≥1024 image tokens for reliable grounding, otherwise it
down-samples the (already ≤1024 px) DMS images too far and the descriptions get
vague.

**Headroom is thin (~1.5 GB).** If qwen OOMs under load:
`ctx-size 16384 → 12288` in the preset, or run `t2v-transformers` on CPU
(`ENABLE_CUDA=0` + drop its `deploy.resources` block; costs ~50–150 ms per text
embedding, acceptable — the chat path is LLM-generation-bound). `multi2vec-clip`
must stay on the GPU (CPU image encoding ≈ 300–800 ms/image, too slow for the
DMS image pipeline). Both LLMs at once do **not** fit → `--models-max 1`. The
Qwen MoE loads/unloads faster than a dense model of similar size, which softens
the model-switch gap.

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

Permissions (the container runs as **root** — no `user:` in the compose):

| Path | Mode | Owner | Why |
| --- | --- | --- | --- |
| `/srv/hot/models/llama-cpp/` | `750` | `root:docker` | mirrors `…/models/ollama`; not a secret |
| `*.gguf`, `presets.ini` | `640` | `root:docker` | public weights / filenames + params only |
| `/srv/warm/llama-3090/` | `700` | `root:root` | holds the API key |
| `/srv/warm/llama-3090/llama_api_key` | `600` | `root:root` | **secret** — only the container (root) reads it |

## Getting the GGUF files onto the server

Unlike Ollama, `llama-server` has **no model registry and no `ollama pull`**.
The `ghcr.io/ggml-org/llama.cpp:server-cuda` image also ships **no Python and no
Hugging Face CLI** — download on the host, not inside the container.

> The CLI is `hf` (from the `huggingface_hub` package). The old
> `huggingface-cli` entrypoint is deprecated and no longer works — use `hf`.

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
# one-time: the Hugging Face CLI on the HOST (not the container)
pipx install "huggingface_hub[cli]"        # or: pip install -U "huggingface_hub[cli]"
# provides the `hf` command (NOT the deprecated `huggingface-cli`)

cd /srv/hot/models/llama-cpp

# --- chat / vision model: Qwen3-VL-30B-A3B-Instruct (weights + vision projector) ---
hf download Qwen/Qwen3-VL-30B-A3B-Instruct-GGUF \
  Qwen3VL-30B-A3B-Instruct-Q4_K_M.gguf \
  mmproj-Qwen3VL-30B-A3B-Instruct-F16.gguf \
  --local-dir .

# --- DMS text model: Mistral-Small-3.2-24B-Instruct-2506, weights only ---
# Option A: official repo (GATED — run `hf auth login` first + accept the
#           licence at https://huggingface.co/mistralai/Mistral-Small-3.2-24B-Instruct-2506)
hf download mistralai/Mistral-Small-3.2-24B-Instruct-2506-GGUF \
  <official-Q4_K_M-filename>.gguf --local-dir .
# Option B: open community re-quant (no login) — recommended if you don't want
#           to deal with the gate. Same base model, Q4_K_M:
hf download bartowski/mistralai_Mistral-Small-3.2-24B-Instruct-2506-GGUF \
  mistralai_Mistral-Small-3.2-24B-Instruct-2506-Q4_K_M.gguf --local-dir .
```

Then set the presets in `presets.ini`. **Section names must be colon-free**
(they are the model IDs consumers send) and **paths must be absolute** — the
router spawns each sub-server with a working directory that is not `/models`,
so a bare filename fails with "No such file or directory":

```ini
[qwen3-vl-30b]
model  = /models/Qwen3VL-30B-A3B-Instruct-Q4_K_M.gguf
mmproj = /models/mmproj-Qwen3VL-30B-A3B-Instruct-F16.gguf
load-on-startup  = true
image-min-tokens = 1024   ; Qwen3-VL grounding quality
parallel         = 1      ; one KV slot — VRAM (see VRAM budget above)
reasoning-format = deepseek

[mistral-small-3.2-24b]
model = /models/mistralai_Mistral-Small-3.2-24B-Instruct-2506-Q4_K_M.gguf
```

Check the file names first: `docker exec llama-3090 ls -la /models/`.
Verify sizes: Qwen Q4_K_M ≈ 18.6 GB, mmproj-F16 ≈ 1.1 GB, Mistral Q4_K_M ≈ 14 GB.
After (re)start, `GET /v1/models` (with the bearer token) must list exactly
`qwen3-vl-30b` and `mistral-small-3.2-24b`.

### Alternative — let llama.cpp pull from HF on first request

Instead of downloading, reference the repo directly; the router fetches into
`cache/` on the first request for that model:

```ini
[qwen3-vl-30b]
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
`.env`). Server-side only, never committed. `600 root:root` — see the
permissions table above.

Generate it as any high-entropy string (no format requirement):

```bash
sudo mkdir -p /srv/warm/llama-3090 && sudo chmod 700 /srv/warm/llama-3090
printf '%s' "$(openssl rand -hex 32)" | sudo tee /srv/warm/llama-3090/llama_api_key >/dev/null
sudo chmod 600 /srv/warm/llama-3090/llama_api_key
```

Then put the **same** value as `OLLAMA_API_KEY=` into every consumer `.env`
(alice-chat-stream, dms-extractor-image, n8n, openwebui).

## Rollback

Stop `llama-3090`, start `ollama-3090`, revert consumer `.env` to
`http://ollama-3090:11434` + Ollama model names, restore `ollama-3090.conf` as
a proxy and disable `llama-3090.conf`, re-sync, reload nginx. The
`ollama-3090` container definition and its model volume are kept for a grace
period — see the PROJ-99 spec.
