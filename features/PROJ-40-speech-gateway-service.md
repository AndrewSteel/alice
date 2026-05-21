# PROJ-40: Speech Gateway Service

## Status: Architected
**Created:** 2026-05-21
**Last Updated:** 2026-05-21

## Dependencies
- Requires: PROJ-1 (User Authentication) — JWT-Validierung für WebApp-Clients
- Required by: PROJ-41 (WebApp Voice Interface) — konsumiert STT- und Full-Voice-Endpunkt
- Required by: PROJ-42 (HA Voice Integration) — konsumiert den Wyoming-Endpunkt
- Extended by: PROJ-43 (Speaker Recognition) — wird in diesen Service integriert
- Depends on: alice-chat-stream — interner AI-Pipeline-Endpunkt
- Depends on: wyoming-piper — TTS-Service (bestehender Container)

## User Stories

- Als Nutzer möchte ich ein Mikrofon-Icon in der WebApp drücken, sprechen und
  den transkribierten Text als Eingabeprompt sehen, damit ich Sprache statt
  Tastatur zur Texteingabe verwenden kann.

- Als Nutzer möchte ich ein Audio-Icon in der WebApp drücken und ein vollständiges
  Sprachgespräch mit Alice führen — ohne Texteingabe oder Textausgabe — damit
  ich Alice hands-free bedienen kann.

- Als Nutzer möchte ich, dass die Sprachausgabe beginnt, sobald Alice den ersten
  vollständigen Satz generiert hat, damit die gefühlte Latenz kürzer ist.

- Als Nutzer möchte ich Alice durch Sprechen unterbrechen können, damit wir eine
  natürliche Konversation führen können.

- Als Nutzer möchte ich, dass das Gespräch nach einer vollständigen Antwort offen
  bleibt und ich direkt weiterreden kann, ohne erneut ein Icon zu drücken.

- Als Nutzer möchte ich über ein HA Voice Device im Wohnzimmer mit Alice sprechen
  — nicht nur für HA-Steuerung, sondern für beliebige Fragen — mit denselben
  Gesprächsfähigkeiten wie über die WebApp.

- Als Nutzer möchte ich bei Fehlern immer eine gesprochene Rückmeldung erhalten,
  damit ich nie vor einem stillen Gerät stehe.

- Als Admin möchte ich HA Voice Devices über eine Konfigurationsdatei festen
  Nutzern zuordnen, damit Anfragen vom richtigen Nutzerprofil bearbeitet werden.

## Acceptance Criteria

### Modus 1 — STT-Endpunkt (WebApp, Mikrofon-Icon)
- [ ] Der Gateway exponiert einen WebSocket-Endpunkt (z.B. `/ws/stt`) für
      reine Transkription
- [ ] Client sendet fertig aufgezeichnete Audio-Datei (push-to-talk)
- [ ] Gateway liefert den transkribierten Text zurück; kein KI-Aufruf, kein TTS
- [ ] Authentifizierung via JWT (Header oder Query-Parameter)

### Modus 2 — Full-Voice-Pipeline (WebApp, Audio-Icon)
- [ ] Der Gateway exponiert einen WebSocket-Endpunkt (z.B. `/ws/voice`) für
      die vollständige Sprachkonversation
- [ ] Der Client streamt Audio kontinuierlich ab dem Moment des Button-Drucks;
      kein Push-to-Talk, keine serverseitige Vorab-Pufferung der vollständigen Aufnahme
- [ ] Die Session endet ausschließlich durch explizite User-Aktion (Stop-Button,
      erkannte Abschluss-Phrase) oder Silence-Timeout — nicht durch Audio-Inhalt allein
- [ ] Gateway übernimmt STT → alice-chat-stream → Piper TTS → Audio zurück
- [ ] Keine Textausgabe — ausschließlich Audio-Antwort
- [ ] Authentifizierung via JWT

### Modus 3 — Wyoming-Endpunkt (HA Voice Device)
- [ ] Der Gateway exponiert einen Wyoming-kompatiblen Endpunkt (Port 10300)
      und ersetzt damit den wyoming-whisper-Container vollständig
- [ ] HA Voice Devices können nach Wakeword-Erkennung Audio an den Gateway
      senden; der Gateway führt dieselbe Full-Voice-Pipeline wie Modus 2 aus
- [ ] Jede Device-ID wird über eine Konfigurationsdatei (YAML/JSON,
      in Docker-Volume gemountet) einem Nutzer (user_id) zugeordnet
- [ ] Unbekannte Device-IDs erhalten eine gesprochene Fehlerantwort

### Sentence-Level TTS Streaming (Modus 2 + 3)
- [ ] LLM-Token-Stream wird zu vollständigen Sätzen akkumuliert
      (Trennung bei `.`, `!`, `?`, Zeilenumbruch)
- [ ] Jeder vollständige Satz wird sofort an Piper TTS übergeben —
      ohne auf die vollständige KI-Antwort zu warten
- [ ] TTS-Audio-Chunks werden sofort an den Client gestreamt
- [ ] Satz 2 wird in Piper verarbeitet während Satz 1 noch abgespielt wird
      (Pipeline-Parallelismus)

### Barge-In / Interrupt (Modus 2 + 3)
- [ ] Während einer laufenden TTS-Ausgabe empfängt der Gateway weiterhin
      Audio-Chunks vom Client
- [ ] Stufe 1 — VAD-Vorfilter: Ein leichtgewichtiger Voice-Activity-Detector
      (z.B. WebRTC VAD oder silero-vad) prüft eingehende Chunks; offensichtliche
      Stille und Hintergrundgeräusche werden verworfen, ohne Whisper aufzurufen
- [ ] Stufe 2 — STT: Sprachähnliche Segmente werden durch Whisper transkribiert
- [ ] Stufe 3 — Intent-Klassifikation (regelbasiert, MVP): Das Transkript wird
      gegen eine konfigurierbare Liste deutscher Interrupt-Phrasen geprüft
      (z.B. "Stop", "Stopp", "Halt", "warte mal", "Moment",
      "Ich habe eine Frage", "kurze Nachfrage", "da widerspreche ich");
      nur bei einem Treffer wird ein Interrupt ausgelöst
- [ ] Transkripte ohne Interrupt-Intent (Fernseher, Radio, Hintergrundgespräche)
      werden stillschweigend verworfen — die laufende Pipeline läuft weiter
- [ ] Bei erkanntem Interrupt: Ollama-Stream wird gestoppt, ausstehende
      TTS-Chunks werden verworfen; das Interrupt-Transkript wird unmittelbar
      als neue Eingabe in die Pipeline eingespeist
- [ ] Die Konversations-Session bleibt bei Interrupt erhalten (gleiche session_id)
- [ ] [PROJ-43 Hook] Die Architektur sieht einen optionalen vierten Schritt vor:
      Speaker-Verifikation — Interrupt wird nur ausgelöst wenn das Barge-In-Audio
      vom selben User stammt wie die laufende Session; dieser Schritt ist deaktiviert
      bis PROJ-43 integriert ist

### Continued Conversation (Modus 2 + 3)
- [ ] Nach vollständiger TTS-Ausgabe bleibt die Session offen und wartet
      auf neue Spracheingabe
- [ ] Session endet automatisch nach konfiguriertem Silence-Timeout
      ohne neue Eingabe (Standard: 30s)
- [ ] Session endet sofort wenn alice-chat-stream ein `conversation_end`-Event
      sendet (z.B. bei Abschluss-Phrasen wie "Danke")
- [ ] Client kann die Session aktiv beenden (WebSocket-Close oder
      explizites Stop-Event)
- [ ] Der WebApp-Client wird über Zwischenstatus informiert:
      `stt_complete`, `ai_processing`, `tts_generating`, `session_ended`

### Fehlerbehandlung
- [ ] Bei jedem Fehler (STT-Fehler, KI-Timeout, TTS-Fehler) liefert der
      Gateway eine gesprochene Fehlerantwort auf Deutsch
- [ ] KI-Timeout ist konfigurierbar (Standard: 15s)
- [ ] Einzige Ausnahme: Fällt Piper TTS selbst aus, wird der Fehler geloggt
      und die Verbindung geschlossen (TTS ist Voraussetzung für gesprochene Fehler)
- [ ] Ungültige oder abgelaufene JWTs werden mit einer WS-Fehlermeldung
      abgelehnt — kein STT, kein KI-Aufruf

### Allgemein
- [ ] Mehrere Clients können gleichzeitig Anfragen stellen; kein globaler Lock
- [ ] Der Gateway verwendet die TITAN X GPU
      (ID: `GPU-ed6554a1-fe67-5286-11c3-a19c2f3554a6`)
- [ ] STT: faster-whisper large-v3, Deutsch als Standardsprache

## Edge Cases

- **Stille / kein Sprachinhalt**: Whisper liefert leeres Transkript →
  Gateway antwortet mit "Ich habe nichts verstanden, bitte wiederholen."
- **Audio zu kurz (< 0.5s)**: Gateway verwirft ohne Whisper-Aufruf,
  gesprochene Rückmeldung
- **Unbekannte Device-ID (Wyoming)**: Gesprochene Fehlerantwort, kein KI-Aufruf
- **alice-chat-stream nicht erreichbar**: Gesprochene Fehlerantwort nach Timeout;
  andere laufende Sessions bleiben unberührt
- **Barge-In bei letztem TTS-Satz**: Bereits gesendete Audio-Chunks werden
  im Client zu Ende abgespielt; keine weiteren Chunks werden gesendet
- **Barge-In-Kandidat ohne Interrupt-Intent**: Whisper transkribiert Audio
  eines Fernsehers oder Radios — Intent-Klassifikator findet keine Interrupt-Phrase
  → Segment wird verworfen, TTS läuft weiter; kein false positive
- **Barge-In-Kandidat mit leerem Whisper-Transkript**: VAD hat fälschlicherweise
  ein Segment als sprachähnlich markiert → leeres Transkript → kein Intent-Check,
  kein Interrupt
- **conversation_end während Barge-In**: Laufende neue Eingabe hat Vorrang;
  conversation_end wird ignoriert
- **Silence-Timeout feuert während Nutzer gerade beginnt zu sprechen**:
  Eingehende Audio-Aktivität setzt den Timeout zurück
- **Client trennt Verbindung mid-stream**: Laufende STT/KI/TTS-Prozesse
  werden abgebrochen, Ressourcen freigegeben
- **HA Voice Device unterstützt kein Barge-In**: Gerät sendet kein Audio
  während TTS läuft → kein Interrupt; Conversation läuft normal zu Ende
  (firmware-seitige Einschränkung, nicht Gateway-Fehler)

## Technical Requirements

- **Performance**: End-to-End < 3s (WebApp), < 4s (HA Voice Device)
- **Concurrency**: Mehrere gleichzeitige Sessions; graceful degradation
  bei Ressourcenengpass
- **GPU**: TITAN X — gleiche Zuweisung wie bisheriger wyoming-whisper
- **Ports**: 10300 (Wyoming), 10301 (WebSocket, WebApp)
- **Sprache**: Deutsch (Standard); konfigurierbar per Umgebungsvariable
- **Container**: Ersetzt wyoming-whisper vollständig
- **Konfiguration**: Device→User-Mapping als YAML/JSON in Docker-Volume;
  Timeouts als Umgebungsvariablen
- **Sicherheit**: Nur im VPN erreichbar; JWT für WebApp;
  Wyoming-Endpunkt vertraut internem Docker-Netz

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Container Overview

New Python container **`alice-speech-gateway`** that:
- **Replaces** the existing `wyoming-whisper` container (inherits port 10300)
- **Keeps** `wyoming-piper` running — the gateway calls it as a client
- Adds **two new WebSocket endpoints** on port 10301 for the WebApp

### Internal Structure

```
alice-speech-gateway (Python, ports 10300 + 10301)
│
├── Wyoming Server (port 10300)           ← replaces wyoming-whisper
│   └── HA Voice Device sessions → VoicePipeline
│
├── WebSocket Server (port 10301)         ← new, for WebApp
│   ├── /ws/stt   → STT-only session
│   └── /ws/voice → VoicePipeline session
│
├── VoicePipeline (one per active session)
│   ├── STT Engine           ← faster-whisper large-v3, shared GPU model
│   ├── Chat Client          ← calls alice-chat-stream SSE endpoint
│   ├── Sentence Accumulator ← splits token stream at . ! ? newline
│   ├── TTS Client           ← calls wyoming-piper via Wyoming protocol
│   └── Barge-In Controller  ← 3-stage filter: VAD → Whisper → Intent classifier
│       ├── VAD Pre-filter   ← rejects silence/noise without Whisper call
│       ├── Background STT   ← Whisper on speech-like segments during TTS playback
│       ├── Intent Classifier ← rule-based: matches interrupt phrases (configurable list)
│       └── [PROJ-43 Hook]   ← optional speaker verification (disabled until PROJ-43)
│
├── Session Registry (in-memory only)
├── JWT Validator (RS256 public key, same cert as alice-auth)
├── Device Mapper (reads device-mapping.yaml from Docker volume)
└── Config Loader (env vars for timeouts, language, GPU ID)
```

### Data Flow

**Mode 1 — STT only (`/ws/stt`):**
```
Browser → audio bytes → faster-whisper → transcript text → Browser
```

**Mode 2 — Full Voice (`/ws/voice`):**
```
Browser → continuous audio stream
  → [main path] VAD detects end of utterance
      → faster-whisper → text
      → alice-chat-stream (SSE token stream)
      → Sentence Accumulator (splits at . ! ?)
      → wyoming-piper (per sentence, pipelined)
      → audio chunks → Browser
  → [barge-in path, parallel during TTS playback]
      → VAD pre-filter → speech-like segment?
      → faster-whisper (background) → transcript
      → Intent Classifier → interrupt phrase matched?
      → [PROJ-43] Speaker match?
      → yes: cancel main pipeline, transcript → new main path input
      → no: discard, main pipeline continues
```

**Mode 3 — Wyoming / HA Voice Device (port 10300):**
```
HA Voice Device → Wyoming audio
  → device-mapping.yaml → user_id
  → faster-whisper → text
  → alice-chat-stream (SSE token stream)
  → Sentence Accumulator
  → wyoming-piper (per sentence, pipelined)
  → audio chunks → HA Voice Device
```

### Data Model

| What | Where stored | Notes |
|---|---|---|
| Active voice sessions | In-memory only | Each WebSocket connection = one session object |
| Device→User mapping | YAML file in Docker volume | Read at startup; no database needed |
| Session history / messages | Owned by alice-chat-stream | Gateway is stateless across restarts |
| JWT public key | Env var path | Same public key as alice-auth service |

No new PostgreSQL tables required. The gateway forwards `session_id` to alice-chat-stream, which owns conversation history.

### Tech Decisions

| Decision | Choice | Why |
|---|---|---|
| Language | Python (asyncio) | faster-whisper and wyoming are Python-native; async required for concurrent sessions |
| WebSocket framework | FastAPI + uvicorn | Clean WebSocket support; consistent with alice-chat-stream stack |
| STT | faster-whisper large-v3, CUDA | Same model as current wyoming-whisper; GPU-accelerated |
| GPU sharing | Single model instance loaded at startup | Avoids reloading VRAM per request; shared across concurrent sessions |
| TTS | wyoming-piper via Wyoming client mode | Reuses existing Piper container; avoids duplication |
| AI backend | alice-chat-stream SSE endpoint | Existing internal endpoint; session_id passed through for history |
| Sentence streaming | Accumulate tokens, split at `.!?` newline | TTS starts before LLM finishes — reduces perceived latency |
| Barge-in trigger | Post-Whisper intent classification, not raw audio | Raw audio alone cannot distinguish user intent from TV/radio/background noise |
| Barge-in stage 1 | VAD pre-filter (WebRTC VAD or silero-vad) | Avoids Whisper GPU call for obvious silence/noise; fast, CPU-only |
| Barge-in stage 2 | Background Whisper during TTS playback | Shared model instance; parallel asyncio task, low overhead when no speech detected |
| Barge-in stage 3 | Rule-based intent classifier (MVP) | Configurable phrase list in YAML; no LLM call needed for MVP; extension path to Option C (rule pre-filter + LLM confirmation) if false negatives become a problem |
| Barge-in stage 4 | PROJ-43 speaker verification hook | Interface defined now; disabled until PROJ-43 delivers speaker embeddings |
| JWT auth | RS256 public key validation | WebApp endpoints require auth; Wyoming trusts Docker internal network only |
| Config | YAML volume + env vars | Device mapping and interrupt phrase list updatable without container rebuild |

### Ports & Networking

| Port | Protocol | Consumer |
|---|---|---|
| 10300 | Wyoming (TCP) | HA Voice Devices (replaces wyoming-whisper) |
| 10301 | WebSocket (HTTP upgrade) | WebApp via nginx proxy |

**nginx change:** Add proxy rule `/api/speech/` → `alice-speech-gateway:10301` (WebSocket upgrade, buffering off, `proxy_read_timeout 300s`).

### Dependencies (Python packages)

| Package | Purpose |
|---|---|
| `faster-whisper` | GPU STT inference |
| `wyoming` | Wyoming protocol server + client |
| `fastapi` + `uvicorn` | WebSocket server |
| `httpx` | Async SSE client for alice-chat-stream |
| `pyjwt` + `cryptography` | RS256 JWT validation |
| `pyyaml` | Device→User mapping config |

### Scope Boundary

This feature does NOT include:
- WebApp UI changes (→ PROJ-41)
- Speaker Recognition enrollment and embedding (→ PROJ-43); the gateway only provides the hook interface
- HA Voice pipeline configuration in Home Assistant (→ PROJ-42)

### Extension Path: Barge-In Option C

If the rule-based intent classifier (MVP) produces too many false negatives in real use, the upgrade path is **Option C (hybrid)**:
1. Rule-based classifier runs first as before
2. On a rule match, a secondary LLM call (lightweight Ollama model, e.g. qwen3:1.7b) confirms intent
3. Only confirmed matches trigger the interrupt

This adds ~300–600ms to the interrupt decision latency but eliminates borderline false positives from ambiguous phrases. No architectural changes required — only the Intent Classifier component is swapped out.

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
