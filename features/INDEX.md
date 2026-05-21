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

| ID      | Phase | Feature                                                                                                                         | Status  | Spec | Created |
| ------- | ----- | ------------------------------------------------------------------------------------------------------------------------------- | ------- | ---- | ------- |
| PROJ-40 | 2.1   | Speech Gateway Service — Python-Container, Wyoming (HA Voice) + HTTP/WS (WebApp), Whisper STT, Piper TTS                       | Architected | [Spec](PROJ-40-speech-gateway-service.md) | 2026-05-21 |
| PROJ-41 | 2.1   | WebApp Voice Interface — Mikrofon-Button, Audio→Gateway, TTS-Playback im Browser                                               | Roadmap | —    | 2026-05-21 |
| PROJ-42 | 2.2   | Home Assistant Voice Integration — Wyoming STT/TTS, Wakeword→KI→TTS auf HA-Gerät                                               | Roadmap | —    | 2026-05-21 |
| PROJ-43 | 2.2   | Speaker Recognition (Speaker-ID) — Voice-Embedding, Enrollment-Flow, Speaker→User/Rolle in Postgres                            | Roadmap | —    | 2026-05-21 |
| PROJ-44 | 2.1   | DMS BankTransaction Lifecycle Cleanup — BUG-13-Fix: BankTransaction-Kinder bei Parent-BankStatement-Löschung mitlöschen        | Roadmap | —    | 2026-05-21 |
| PROJ-45 | 2.3   | Display Registry & Output Router — Config-Tabelle (Wallpanel/TV/PC), n8n-Router nach display_target                            | Roadmap | —    | 2026-05-21 |
| PROJ-46 | 2.3   | Mail IMAP Integration — n8n IMAP-Connector, Metadaten in Weaviate, Mail-Query-Tools per Sprache/Text                           | Roadmap | —    | 2026-05-21 |

<!-- Add features above this line -->

## Next Available ID: PROJ-47
