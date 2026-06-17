# Feature Index

> Central tracking for all features. Updated by skills automatically.

## Status Legend
- **Roadmap** - `/init` done, feature identified in feature map, no spec file yet
- **Planned** - `/write-spec` done, full spec written, architecture not yet designed
- **Architected** - `/architecture` done, tech design approved, ready to build
- **In Progress** - `/frontend` or `/backend` active or completed, not yet in QA
- **In Review** - `/qa` active, testing in progress
- **Approved** - `/qa` passed, no critical/high bugs, ready to deploy
- **Deployed** - `/deploy` done, live in production

## Features

| ID      | Phase | Feature                                                                                                                             | Status   | Spec                                      | Created    |
| ------- | ----- | ----------------------------------------------------------------------------------------------------------------------------------- | -------- | ----------------------------------------- | ---------- |
| PROJ-40 | 2.1   | Speech Gateway Service — Python-Container, Wyoming (HA Voice) + HTTP/WS (WebApp), Whisper STT, Piper TTS; Mode 3 deferred → PROJ-42 | Deployed | [Spec](PROJ-40-speech-gateway-service.md) | 2026-05-21 |
| PROJ-41 | 2.1   | WebApp Voice Interface — Mikrofon-Button, Audio→Gateway, TTS-Playback im Browser                                                    | Deployed | [Spec](PROJ-41-webapp-voice-interface.md) | 2026-05-21 |
| PROJ-42 | 2.2   | Home Assistant Voice Integration — ESPHome Direct Wyoming Satellite, Hey Jarvis → Alice Pipeline, Device-Mapping                     | Deployed  | [Spec](PROJ-42-home-assistant-voice-integration.md) | 2026-05-21 |
| PROJ-43 | 2.2   | Speaker Recognition (Speaker-ID) — Voice-Embedding, Enrollment-Flow, Speaker→User/Rolle in Postgres                                 | Planned  | [Spec](PROJ-43-speaker-recognition.md)    | 2026-05-21 |
| PROJ-44 | 2.1   | DMS BankTransaction Lifecycle Cleanup — BUG-13-Fix: BankTransaction-Kinder bei Parent-BankStatement-Löschung mitlöschen             | Roadmap  | —                                         | 2026-05-21 |
| PROJ-45 | 2.3   | Display Registry & Output Router — Config-Tabelle (Wallpanel/TV/PC), n8n-Router nach display_target                                 | Roadmap  | —                                         | 2026-05-21 |
| PROJ-46 | 2.3   | Mail IMAP Integration — n8n IMAP-Connector, Metadaten in Weaviate, Mail-Query-Tools per Sprache/Text                                | Roadmap  | —                                         | 2026-05-21 |
| PROJ-47 | 2.1   | JWT WebSocket Log Leak Fix — BUG-LIVE-2: uvicorn WebSocket protocol logger schreibt `?token=<JWT>` in Container-Logs                | Deployed  | [Spec](PROJ-47-jwt-websocket-log-leak-fix.md) | 2026-06-02 |
| PROJ-48 | 2.1   | TTS First-Token Latency Reduction — BUG-LIVE-3: Zeit bis erstes TTS-Audio ~10.8 s statt < 3 s; alice-chat-stream first-sentence streaming | Deployed  | [Spec](PROJ-48-tts-first-token-latency.md) | 2026-06-02 |

| PROJ-49 | 2.2   | ESPHome Device Feedback — LED-Zustandsmaschine + Wake Sound; Clockwise/Blink/Counter-clockwise per State; Wake Sound Konsistenz | Deployed  | [Spec](PROJ-49-esphome-device-feedback.md) | 2026-06-15 |

| PROJ-50 | 2.2   | ESPHome Wyoming Frame Split — LED zeigt "Thinking" während LLM-Wartezeit; Gateway sendet separaten AudioStart/AudioStop für "Warte bitte…" + neuer Device-Zustand LLM_WAITING | Roadmap  | —                                         | 2026-06-15 |
| PROJ-51 | 2.2   | Chat-Protokoll-Speicherung & Titelgenerierung — Erweitertes Nachrichtenmodell (STT/Thinking/HA), 30-Tage-Retention, Auto-Titel nach erstem LLM-Austausch, Sidebar-Titel-Fix | Deployed  | [Spec](PROJ-51-chat-storage-and-title-generation.md) | 2026-06-17 |
| PROJ-52 | 2.2   | Admin-Chatarchiv — Neuer Settings-Tab: Liste aller Chats aller Nutzer (30 Tage), Detail-Ansicht mit allen Nachrichtentypen, Löschen-Funktion, Admin-only | Deployed  | [Spec](PROJ-52-admin-chat-archive.md) | 2026-06-17 |

<!-- Add features above this line -->

## Next Available ID: PROJ-53
