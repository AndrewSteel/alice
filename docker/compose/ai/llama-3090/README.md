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
the `model` field:

| Model ID (`model` field) | Role |
| --- | --- |
| `qwen3.5:27b-q4_K_M` | chat/agent + vision (matches old Ollama name) |
| `mistral-small3.2:24b` | DMS text extraction (matches old Ollama name) |

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

### Step 1 — find the exact upstream models

The Ollama tags `qwen3.5:27b-q4_K_M` / `mistral-small3.2:24b` are local tags;
check what they actually are:

```bash
# on ki.lan
docker exec ollama-3090 ollama show qwen3.5:27b-q4_K_M --modelfile
docker exec ollama-3090 ollama show qwen3.5:27b-q4_K_M          # arch, params, quant, projector
docker exec ollama-3090 ollama show mistral-small3.2:24b --modelfile
```

Note the architecture / parameter count / quant, then pick the matching GGUF
repo on Hugging Face (official `Qwen/…-GGUF` / `mistralai/…` repos, or a known
re-quant like `bartowski/…`). Fill the two `<HF_REPO_*>` placeholders below.

### Step 2 — download to the model volume (on the host)

```bash
# one-time: huggingface CLI on the HOST (not the container)
pipx install "huggingface_hub[cli]"        # or: pip install -U "huggingface_hub[cli]"
# for gated repos (some Mistral repos): huggingface-cli login   # needs an HF token

cd /srv/hot/models/llama-cpp

# --- chat / vision model (qwen): language weights + vision projector ---
huggingface-cli download <HF_REPO_QWEN> \
  <QWEN_Q4_K_M_FILENAME>.gguf \
  <QWEN_MMPROJ_FILENAME>.gguf \
  --local-dir .

# --- DMS text model (mistral): language weights only ---
huggingface-cli download <HF_REPO_MISTRAL> \
  <MISTRAL_Q4_K_M_FILENAME>.gguf \
  --local-dir .
```

Then set the real filenames in `presets.ini` (`model =` / `mmproj =`).
Verify: `ls -lh /srv/hot/models/llama-cpp/*.gguf` — the qwen weights should be
~18–20 GB (Q4_K_M of a ~30 B model), mistral ~14 GB, the mmproj ~1–2 GB.

### Alternative — let llama.cpp pull from HF on first request

Instead of downloading, `presets.ini` can reference a repo directly; the router
fetches into `cache/` on the first request for that model:

```ini
[qwen3.5:27b-q4_K_M]
model  = hf:<HF_REPO_QWEN>:<Q4_K_M_TAG>
mmproj = hf:<HF_REPO_QWEN>:<MMPROJ_TAG>
```

Trade-offs: the container then needs outbound internet (and an `HF_TOKEN` env
for gated repos), and the **first** request blocks for the full ~20 GB
download. For the cutover, prefer Step 2 so the download happens up front and
you can verify quant parity before the hard switch.

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
