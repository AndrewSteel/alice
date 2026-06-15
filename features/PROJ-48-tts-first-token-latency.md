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

Root cause: qwen3:14b is a reasoning model. With `think: true` (the default), it generates an internal reasoning phase before any visible content tokens. The gateway's `chat_client.py` ignores `thinking` events — so the audio pipeline starves for ~9.6 s while the model reasons. The streaming and sentence-accumulation pipeline are already correct; the problem is the silence during the thinking phase.

The fix is not to disable thinking (answer quality must be preserved), but to **fill the silence audibly**: when the first thinking token arrives, the gateway immediately synthesizes a short spoken acknowledgement ("Warte bitte, ich muss kurz überlegen." / "Warten Sie bitte…") and plays it. The LLM continues reasoning in the background; the actual response follows via the existing sentence-by-sentence TTS pipeline.

## Dependencies

- Requires: PROJ-40 (Speech Gateway Service) — gateway calls `alice-chat-stream` for LLM inference
- Requires: PROJ-41 (WebApp Voice Interface) — defines the 3 s performance budget this feature fulfils

## User Stories

- Als Nutzer möchte ich Alice's erste Sprachantwort innerhalb von 3 Sekunden nach meiner Spracheingabe hören, damit das Gespräch sich natürlich und flüssig anfühlt.

- Als Nutzer möchte ich nicht 10 Sekunden auf die erste Audioausgabe warten müssen, damit ich nicht das Gefühl habe, dass das System eingefroren ist.

- Als Nutzer möchte ich eine Rückmeldung hören ("Warte bitte…" / "Warten Sie bitte…"), wenn Alice länger nachdenkt, damit ich weiß dass die Anfrage verarbeitet wird — sowohl in der WebApp (zusätzlich zur visuellen Anzeige) als auch am ESPHome-Gerät (ausschließlich auditiv).

- Als Systementwickler möchte ich, dass die Anrede in der Wartebotschaft der hinterlegten Nutzereinstellung (Du/Sie) entspricht.

## Acceptance Criteria

- [ ] Zeit von `end_of_utterance` bis zum ersten empfangenen TTS-Chunk beim Client beträgt **< 3 s** — gemessen mit einer kurzen Anfrage, mit qwen3:14b auf der lokalen 3090 (WebApp voice und ESPHome)
- [ ] Der erste `tts_generating`-Status-Event trifft beim Client ein, bevor die vollständige LLM-Antwort fertig ist
- [ ] Sobald der erste Thinking-Token von Ollama eintrifft, synthesiert das Gateway die Wartebotschaft und streamt sie als erstes Audio an den Client
- [ ] Die Wartebotschaft lautet "Warte bitte, ich muss kurz überlegen." bei Anrede `du`, und "Warten Sie bitte, ich muss kurz überlegen." bei Anrede `sie`
- [ ] Die Anrede wird aus `alice.user_profiles.preferences.anrede` gelesen; fehlender Eintrag fällt auf `du` zurück
- [ ] Nach der Wartebotschaft folgt die eigentliche LLM-Antwort nahtlos via Sentence-by-Sentence-TTS — keine Doppelung, keine Lücke im Satz
- [ ] Barge-In während der Wartebotschaft bricht die Wiedergabe korrekt ab — kein "phantom"-TTS danach
- [ ] Mode 1 (STT → Texteingabe ohne Voice-Antwort) ist nicht betroffen — keine Wartebotschaft, keine Latenz-Regression
- [ ] Text-only Chat (WebApp Textkanal, n8n) empfängt das neue `thinking_start`-SSE-Event, ignoriert es stillschweigend — keine Regression
- [ ] Die vollständige LLM-Antwort wird korrekt als zusammenhängendes Gespräch gespeichert; die Wartebotschaft wird nicht in die Gesprächshistorie geschrieben

## Edge Cases

- **Ollama denkt sehr kurz (< 1 s)**: Wartebotschaft wird noch synthetisiert, aber der erste Content-Token trifft bereits ein, bevor die Wiedergabe endet. Die Sentence-Queue puffert den ersten Satz — keine Überlappung, natürliche Abfolge.
- **Barge-In während Wartebotschaft**: `_interrupt`-Flag unterbricht Synthese und Sendung; kein weiterer TTS-Aufruf für die restlichen Sätze der aktuellen Antwort.
- **Nutzer hat keine `anrede` in den Einstellungen**: Fallback auf `"du"` → "Warte bitte, ich muss kurz überlegen."
- **OLLAMA_THINK=false (env override)**: Kein Thinking-Token → kein `thinking_start`-Event → keine Wartebotschaft. Pipeline verhält sich wie bisher, Content-Token kommen sofort.
- **Kein Thinking-Token im ersten Chunk**: Manche Ollama-Versionen emittieren thinking und content im gleichen Chunk. `thinking_start` wird nur ausgelöst, wenn tatsächlich ein Thinking-Token vor dem ersten Content-Token eintrifft.
- **Sehr lange Antwort (> 5 Sätze)**: Wartebotschaft + alle Sätze der LLM-Antwort werden als separate Sentence-Queue-Einträge sequenziell synthesiert.
- **Ollama-Timeout / Verbindungsfehler**: Gateway sendet `session_ended`-Event; Wartebotschaft kann bereits abgespielt worden sein — kein Phantom-TTS danach.

## Technical Requirements

- **Scope**: `alice-chat-stream` (Python-Service, 2 Dateien) und `alice-speech-gateway` (3 Dateien)
- **Kein Modellwechsel, kein Thinking-Disable**: qwen3:14b mit `think: true` bleibt unverändert
- **Neues SSE-Event** `thinking_start`: Emittiert von `alice-chat-stream` genau einmal pro Turn, sobald der erste Thinking-Token von Ollama eintrifft. Enthält `anrede` des Nutzers.
- **Anrede-Quelle**: `alice.user_profiles.preferences.anrede` — wird in `alice-chat-stream` bereits via `load_user_profile()` geladen; kein zusätzlicher DB-Zugriff nötig
- **Wartebotschaft im Gateway**: `alice-speech-gateway/config.py` definiert `SPEECH_THINKING` dict mit Du/Sie-Varianten; `pipeline.py` wählt die passende aus
- **Ziel-Latenz**: ≤ 3 s bis erstes Audio (STT ~0.6 s + Zeit bis erster Thinking-Token ~0.3 s + TTS-Synthesis Wartebotschaft ~0.2 s ≈ 1.1 s — gut unter Budget)
- **Keine DB-Schema-Änderungen**: `anrede` existiert bereits als JSONB-Feld in `preferences`

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Root Cause

The existing gateway pipeline is already architecturally correct for sentence-level TTS streaming: `pipeline.py` has a 3-stage concurrent pipeline (LLM token stream → `SentenceAccumulator` → Piper TTS → audio send). Tokens are yielded one-by-one from Ollama via SSE and the `SentenceAccumulator` dispatches each complete sentence to TTS immediately. There is no buffering or streaming problem.

The bottleneck is the **thinking phase of qwen3:14b**. With `OLLAMA_THINK=true`, the model generates `thinking` tokens (internal reasoning) before any `content` tokens. The gateway ignores these, so the audio pipeline is idle for ~9.6 s. Disabling thinking would eliminate the delay but sacrifice answer quality. Instead, we bridge the silence with an immediate spoken acknowledgement.

### How It Works

When the gateway receives the first `thinking_start` event (~0.3 s after the Ollama call), it puts a short waiting message into the existing `sentence_queue` as the very first item. The `_tts_consumer` task picks it up and synthesises it immediately via Piper — first audio arrives at ~1.1 s. The LLM continues reasoning in the background. When content tokens start flowing (~9.6 s), the `SentenceAccumulator` queues them as sentences and the pipeline continues without any structural change.

```
t=0.0s  Gateway sends request to alice-chat-stream
t=0.6s  STT complete, ai_processing status sent
t=0.9s  Ollama emits first thinking token
        → alice-chat-stream emits: {"type":"thinking_start","anrede":"du"}
        → gateway puts "Warte bitte, ich muss kurz überlegen." into sentence_queue
t=1.1s  Piper synthesises → first audio chunk sent to client  ✓ (<3s budget met)
t=9.6s  Ollama emits first content token
        → SentenceAccumulator builds first sentence → sentence_queue
        → Piper synthesises → audio continues
```

### Component Structure

```
alice-chat-stream (Python service)
+-- main.py          ← extract anrede from profile; pass to stream_chat()
+-- streaming.py     ← emit {"type":"thinking_start","anrede":"..."} on first thinking token

alice-speech-gateway (Python service)
+-- config.py        ← add SPEECH_THINKING = {"du": "...", "sie": "..."}
+-- chat_client.py   ← yield ChatEvent("thinking_start", anrede) — currently dropped
+-- pipeline.py      ← on thinking_start: put waiting message into sentence_queue
    (sentence_accumulator.py, tts.py, ws_transport.py, wyoming_transport.py unchanged)
```

### Waiting Messages (`config.py`)

| `anrede` | Text |
|---|---|
| `du` (default) | `"Warte bitte, ich muss kurz überlegen."` |
| `sie` | `"Warten Sie bitte, ich muss kurz überlegen."` |

### `thinking_start` SSE Event

New event type emitted by `alice-chat-stream`, exactly once per turn, on the first thinking token:

```
data: {"type":"thinking_start","anrede":"du"}
```

`alice-chat-stream` already loads the user profile (`load_user_profile()`) before streaming — `anrede` is read from `profile["preferences"].get("anrede", "du")`. No additional DB query.

### Files Changed (5)

| File | Change |
|---|---|
| `alice-chat-stream/app/main.py` | Extract `anrede` from profile; pass to `stream_chat()` |
| `alice-chat-stream/app/streaming.py` | Emit `thinking_start` once when first thinking token arrives; add `anrede` param |
| `alice-speech-gateway/app/config.py` | Add `SPEECH_THINKING` dict (Du/Sie waiting messages) |
| `alice-speech-gateway/app/chat_client.py` | Yield `ChatEvent("thinking_start", anrede)` — currently silently dropped |
| `alice-speech-gateway/app/pipeline.py` | On `thinking_start` event: `await sentence_queue.put(SPEECH_THINKING[anrede])` |

### No Changes Needed

- `sentence_accumulator.py` — unchanged
- `tts.py`, `ws_transport.py`, `wyoming_transport.py` — unchanged
- No database schema changes (anrede already in user_profiles.preferences JSONB)
- No n8n workflow changes
- No frontend changes
- No new package dependencies

### Expected Timing After Fix

| Event | Time |
|---|---|
| STT complete | t ≈ 0.6 s |
| First `thinking_start` event | t ≈ 0.9 s |
| **First audio chunk (waiting message)** | **t ≈ 1.1 s** ✓ |
| LLM reasoning complete, first content token | t ≈ 10 s |
| First content sentence TTS | t ≈ 10.5 s |

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
