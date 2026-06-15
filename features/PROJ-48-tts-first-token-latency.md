# PROJ-48: TTS First-Token Latency Reduction

## Status: Architected
**Created:** 2026-06-02
**Last Updated:** 2026-06-15

## Background

BUG-LIVE-3 from the PROJ-41 live QA. The PROJ-41 spec sets a performance budget: *"Erste TTS-Audio-Wiedergabe beginnt innerhalb von < 3 s nach Ende der Spracheingabe (Gateway-Budget; Frontend-Overhead < 100 ms)".* The live test measured ~10.8 s — 3.6× over budget.

Wire trace from the live test (2026-06-01):
```
[t=2.6s ] end_of_utterance sent by client
[t=3.32s] status='stt_complete'         → STT ~0.6 s  ✓
[t=3.32s] status='ai_processing'
[t=12.92s] status='tts_generating'     → LLM first sentence ~9.6 s  ✗
[t=13.39s] first TTS chunk             → TTS first chunk ~0.47 s  ✓
```

The bottleneck is entirely in `alice-chat-stream`: qwen3:14b on the local 3090 takes ~9.6 s to produce the first sentence. The gateway and TTS pipeline are fast enough. The fix requires `alice-chat-stream` to begin streaming a sentence to the TTS pipeline as soon as it is complete — not after the full LLM response is ready.

## Dependencies

- Requires: PROJ-40 (Speech Gateway Service) — gateway calls `alice-chat-stream` for LLM inference
- Requires: PROJ-41 (WebApp Voice Interface) — defines the 3 s performance budget this feature fulfils

## User Stories

- Als Nutzer möchte ich Alice's erste Sprachantwort innerhalb von 3 Sekunden nach meiner Spracheingabe hören, damit das Gespräch sich natürlich und flüssig anfühlt.

- Als Nutzer möchte ich nicht 10 Sekunden auf die erste Audioausgabe warten müssen, damit ich nicht das Gefühl habe, dass das System eingefroren ist.

- Als Systementwickler möchte ich, dass `alice-chat-stream` Token-für-Token ans Gateway streamt, damit das Gateway die erste vollständige Sentence sofort an Piper TTS übergeben kann.

## Acceptance Criteria

- [ ] Zeit von `end_of_utterance` bis zum ersten empfangenen TTS-Chunk im Browser beträgt **< 3 s** — gemessen mit einer kurzen Anfrage (1–2 Sätze Antwort), mit qwen3:14b auf der lokalen 3090
- [ ] Der erste `tts_generating`-Status-Event trifft beim Client ein, bevor die vollständige LLM-Antwort fertig ist (Streaming-Verhalten nachweisbar im Wire Trace)
- [ ] Das Gateway beginnt die TTS-Synthese sobald der erste vollständige Satz aus dem LLM-Stream vorliegt — kein vollständiges Buffern der LLM-Antwort
- [ ] Mode 1 (STT → Texteingabe) ist nicht betroffen — `/ws/stt` latency bleibt < 3 s (Regression-Check)
- [ ] Die vollständige LLM-Antwort wird korrekt als zusammenhängendes Gespräch gespeichert (keine Verkürzung durch Early-Flush)
- [ ] Bei einem Barge-In während der TTS-Wiedergabe wird die laufende Sentence korrekt abgebrochen — kein "phantom"-TTS nach dem Interrupt

## Edge Cases

- **Sehr kurze Antwort (1 Satz)**: Gateway puffert keinen Token über Satzende hinaus; Satz wird sofort an TTS übergeben.
- **Sehr lange Antwort (>5 Sätze)**: Jeder Satz wird einzeln synthetisiert und als separate TTS-Chunk-Sequenz gestreamt — kein vollständiges Warten auf Antwortende.
- **LLM-Satz endet mitten im Stream-Chunk**: Gateway muss Satzgrenzen (`"."`, `"!"`, `"?"`) erkennen und erst dann die TTS-Synthese anstoßen — kein Split am Token-Boundary.
- **Barge-In während erster Satz synthetisiert wird**: Laufende TTS wird sofort abgebrochen; kein weiterer TTS-Call für die restlichen Sätze der aktuellen LLM-Antwort.
- **alice-chat-stream streamt zu langsam für Echtzeit-TTS**: Piper TTS spricht schneller als der LLM neue Sätze liefert → TTS-Stille-Lücke zwischen Sätzen. Akzeptabel, solange erstes Audio innerhalb von 3 s beginnt.
- **Ollama-Timeout / Verbindungsfehler**: Gateway muss `session_ended`-Event senden und die Session sauber beenden, nicht hängen bleiben.

## Technical Requirements

- **Scope**: `alice-chat-stream` (Python-Service) und `alice-speech-gateway` (`ws_transport.py`, Voice-Session-Handler)
- **LLM streaming**: `alice-chat-stream` `/stream/chat`-Endpoint muss Server-Sent Events (SSE) oder Chunked Transfer an den Gateway liefern — ein Token pro Frame
- **Sentence detection im Gateway**: Gateway sammelt LLM-Tokens bis zu einem Satzende-Zeichen (`[.!?]` gefolgt von Leerzeichen oder Antwortende), gibt den gesamten Satz an Piper TTS weiter
- **Ziel-Latenz**: ≤ 3 s total (STT ~0.6 s + LLM first-sentence ~1.5–2 s + TTS first-chunk ~0.5 s). Der LLM-Anteil muss von ~9.6 s auf ≤ 2 s sinken.
- **Kein Modellwechsel erforderlich**: qwen3:14b soll weiterhin genutzt werden; das Latenz-Problem ist ein Streaming-/Buffering-Problem, kein Modellproblem.

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Root Cause

The existing gateway pipeline is already architecturally correct for sentence-level TTS streaming: `pipeline.py` has a 3-stage concurrent pipeline (LLM token stream → `SentenceAccumulator` → Piper TTS → audio send). Tokens are yielded one-by-one from Ollama via SSE and the `SentenceAccumulator` dispatches each complete sentence to TTS immediately. There is no buffering problem.

The actual bottleneck is **`OLLAMA_THINK=true` (the default in `alice-chat-stream`)**. qwen3:14b is a reasoning model. With `think: true`, it generates internal reasoning tokens (the `thinking` field) before producing any visible `content`. The gateway's `chat_client.py` explicitly ignores `thinking` events — so the pipeline receives no content tokens for ~9.6 s while the model reasons, then gets the full response in a burst.

The fix: **disable thinking mode for voice sessions only.** Text-only chat sessions (WebApp, n8n) continue using thinking mode unchanged.

### Component Structure

No new components. Changes are confined to two existing services:

```
alice-chat-stream (Python service)
+-- ChatRequest model       ← add optional voice_mode flag
+-- streaming.py            ← pass think=False to Ollama when voice_mode=True

alice-speech-gateway (Python service)
+-- chat_client.py          ← set voice_mode=True in request payload
    (pipeline.py, sentence_accumulator.py unchanged — already correct)
```

### Data Flow (after fix)

```
[Voice turn]
Browser/ESPHome → Gateway STT → alice-chat-stream (voice_mode=True)
  → Ollama (think=False) → content tokens stream immediately
  → SentenceAccumulator → Piper TTS → audio stream → client

[Text turn — unchanged]
Browser → alice-chat-stream (voice_mode absent/False)
  → Ollama (think=True) → thinking tokens + content tokens
  → SSE to browser
```

### What Changes (3 files, all surgical)

| File | Change |
|---|---|
| `alice-chat-stream/app/main.py` | Add `voice_mode: bool = False` to `ChatRequest` model; pass it to `stream_chat()` |
| `alice-chat-stream/app/streaming.py` | Add `think: bool = True` parameter to `stream_chat()`; use it in the Ollama payload |
| `alice-speech-gateway/app/chat_client.py` | Add `"voice_mode": True` to the request payload in `stream_reply()` |

### Expected Latency After Fix

| Phase | Before | After |
|---|---|---|
| STT | ~0.6 s | ~0.6 s (unchanged) |
| LLM first sentence | ~9.6 s | ~1.5–2.0 s (no reasoning phase) |
| TTS first chunk | ~0.47 s | ~0.5 s (unchanged) |
| **Total** | **~10.8 s** | **~2.6–3.1 s** |

### No Changes Needed

- `pipeline.py` — 3-stage pipeline already starts TTS on the first complete sentence
- `sentence_accumulator.py` — already splits on `.!?\n` correctly
- `tts.py`, `ws_transport.py`, `wyoming_transport.py` — unchanged
- No database schema changes
- No n8n workflow changes
- No frontend changes
- No new dependencies

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
