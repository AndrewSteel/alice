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
| PROJ-43 | 2.2   | Speaker Recognition (Speaker-ID) — Voice-Embedding, Enrollment-Flow, Speaker→User/Rolle in Postgres                                 | Deployed | [Spec](PROJ-43-speaker-recognition.md)    | 2026-05-21 |
| PROJ-44 | 2.1   | DMS BankTransaction Lifecycle Cleanup — BUG-13-Fix: BankTransaction-Kinder bei Parent-BankStatement-Löschung mitlöschen             | Deployed  | [Spec](PROJ-44-dms-bank-transaction-lifecycle-cleanup.md) | 2026-05-21 |
| PROJ-45 | 2.3   | Display Registry & Output Router — Config-Tabelle (Wallpanel/TV/PC), n8n-Router nach display_target                                 | Roadmap  | —                                         | 2026-05-21 |
| PROJ-46 | 2.3   | Mail IMAP Integration — n8n IMAP-Connector, Metadaten in Weaviate, Mail-Query-Tools per Sprache/Text                                | Deployed  | [Spec](PROJ-46-mail-imap-integration.md)  | 2026-05-21 |
| PROJ-47 | 2.1   | JWT WebSocket Log Leak Fix — BUG-LIVE-2: uvicorn WebSocket protocol logger schreibt `?token=<JWT>` in Container-Logs                | Deployed  | [Spec](PROJ-47-jwt-websocket-log-leak-fix.md) | 2026-06-02 |
| PROJ-48 | 2.1   | TTS First-Token Latency Reduction — BUG-LIVE-3: Zeit bis erstes TTS-Audio ~10.8 s statt < 3 s; alice-chat-stream first-sentence streaming | Deployed  | [Spec](PROJ-48-tts-first-token-latency.md) | 2026-06-02 |

| PROJ-49 | 2.2   | ESPHome Device Feedback — LED-Zustandsmaschine + Wake Sound; Clockwise/Blink/Counter-clockwise per State; Wake Sound Konsistenz | Deployed  | [Spec](PROJ-49-esphome-device-feedback.md) | 2026-06-15 |

| PROJ-50 | 2.2   | ESPHome Wyoming Frame Split — LED zeigt "Thinking" während LLM-Wartezeit; Gateway sendet separaten AudioStart/AudioStop für "Warte bitte…" + neuer Device-Zustand LLM_WAITING | Roadmap  | —                                         | 2026-06-15 |
| PROJ-51 | 2.2   | Chat-Protokoll-Speicherung & Titelgenerierung — Erweitertes Nachrichtenmodell (STT/Thinking/HA), 30-Tage-Retention, Auto-Titel nach erstem LLM-Austausch, Sidebar-Titel-Fix | Deployed  | [Spec](PROJ-51-chat-storage-and-title-generation.md) | 2026-06-17 |
| PROJ-52 | 2.2   | Admin-Chatarchiv — Neuer Settings-Tab: Liste aller Chats aller Nutzer (30 Tage), Detail-Ansicht mit allen Nachrichtentypen, Löschen-Funktion, Admin-only | Deployed  | [Spec](PROJ-52-admin-chat-archive.md) | 2026-06-17 |

| PROJ-53 | 2.3   | Mail-Anhang DMS-Import — E-Mail-Anhänge automatisch oder nutzergesteuert in DMS-Pipeline einspeisung; Abhängigkeit von PROJ-46                                               | Roadmap  | —                                         | 2026-06-24 |
| PROJ-54 | 2.3   | Vision-Chat: Flip-Card Ergebnisansicht — Visuelle Darstellung von Suchergebnissen als Flip-Cards; Split-Screen Vision/Text; responsive Grid-Layout                           | Deployed  | [Spec](PROJ-54-vision-chat-flip-card-results.md) | 2026-06-27 |
| PROJ-55 | 2.3   | DMS Thumbnail-Generierung — Quadratische 1:1-Thumbnails nach DMS-Import (PDF/Office/Bilder), Ablage im Warm-Storage, API-Endpunkt, Backfill für Bestandsdokumente            | Deployed  | [Spec](PROJ-55-dms-thumbnail-generation.md)      | 2026-06-27 |

| PROJ-56 | 2.3   | DMS Bildanalyse — KI-Bildbeschreibung (Ollama Vision), EXIF-Extraktion, GPS-Reverse-Geocoding (lokales Nominatim), neue Weaviate-Collection "Image"                        | Deployed  | [Spec](PROJ-56-dms-image-analysis.md)            | 2026-06-29 |

| PROJ-57 | 2.2   | On-Device VAD Noise Robustness — wyoming_satellite Silence-Detector nutzt Fixed-RMS-Threshold (700) statt adaptivem Noise-Floor; Hintergrundgeräusche (Lüfter, Dunstabzugshaube, Kühlschrank, Staubsauger) verhindern sauberes Beenden der Utterance | Deployed | [Spec](PROJ-57-on-device-vad-noise-robustness.md) | 2026-07-03 |

| PROJ-58 | 2.2   | Sprache-vs-TV/Radio-Trennung — Streaming Speaker-ID im Gateway zur Unterscheidung von Nutzer-Stimme und sprachähnlichem Hintergrund (TV, Radio); Latenz-Machbarkeit ungeklärt, benötigt Machbarkeitsprüfung in /architecture | Roadmap  | —                                         | 2026-07-03 |

| PROJ-59 | 3.1   | Financial Research Workflow — Sektor-Analyse per Claude Skills (equity-research, financial-analysis, market-researcher) aus externem Docker-Container, Ergebnis als Dashboard-Link im Chat                            | Planned  | [Spec](PROJ-59-financial-research-workflow.md) | 2026-07-19 |
| PROJ-60 | 3.2   | Frontend Theming — Light/Dark-Mode-Switch (System/Hell/Dunkel), neue Farbpalette (Nova/Zinc/Cyan), Migration auf semantische shadcn-Tokens                                                                             | Deployed | [Spec](PROJ-60-frontend-theming-light-dark-mode.md) | 2026-07-19 |
| PROJ-61 | 3.2   | Vision Flip-Card Grid — Responsive Enlargement (volle Breite Mobile Portrait, größere Desktop-Karten); benötigt Thumbnail-Auflösungs-Update in PROJ-55                                                                 | Deployed | [Spec](PROJ-61-vision-flip-card-responsive-enlargement.md) | 2026-07-19 |
| PROJ-62 | 3.2   | Frontend i18n — DE/EN UI-Übersetzung, erweiterbar auf weitere Sprachen; `sprache`-Profilfeld steuert UI + Alice-Antwortsprache; FlipCard-Label-Maps datengetrieben                                                     | Deployed | [Spec](PROJ-62-frontend-i18n.md) | 2026-07-19 |
| PROJ-63 | 3.2   | Backend Sprachcode-Offenheit — alice-auth-Validierung + alice-chat-stream-LLM-Prompt-Logik auf konfigurierbare ISO-639-1-Codes umgestellt statt hartcodiert deutsch/englisch; neuer `GET /api/auth/languages`            | Deployed | [Spec](PROJ-63-backend-language-code-extensibility.md) | 2026-07-19 |
| PROJ-64 | 3.2   | Voice-Enrollment offene Sprachauswahl — Sprachabfrage im ESPHome-Enrollment-Flow erkennt beliebige konfigurierte Sprachen (Keyword-Matching) statt nur Deutsch/Englisch                                                | Deployed | [Spec](PROJ-64-voice-enrollment-language-recognition.md) | 2026-07-19 |
| PROJ-65 | 3.2   | Backend Effective-Permissions API — 3 neue system_permissions-Flags (DMS-Ordner/Chatarchiv/Mailbox-Verwaltung), neuer `GET /api/auth/permissions`-Endpunkt                                                              | Deployed | [Spec](PROJ-65-backend-effective-permissions-api.md) | 2026-07-19 |
| PROJ-66 | 3.2   | Frontend Granulares Rollen-Gating — SettingsPage-Tabs & MailboxSection auf permissions_system-Flags statt role===admin umgestellt; usePermissions-Hook                                                                  | Deployed | [Spec](PROJ-66-frontend-granular-ui-gating.md) | 2026-07-19 |
| PROJ-67 | 3.2   | Zentraler Auth-Fetch-Wrapper — konsolidiert authHeaders()/401-Handling aus 6 Service-Dateien in eine gemeinsame Implementierung                                                                                          | Deployed | [Spec](PROJ-67-central-auth-fetch-wrapper.md) | 2026-07-19 |
| PROJ-68 | 3.2   | SettingsPage Route-Splitting — eigene Subrouten je Tab (/settings/profil, /settings/dms, ...) mit Code-Splitting und Permission-Route-Guards                                                                            | Deployed | [Spec](PROJ-68-settingspage-route-splitting.md) | 2026-07-19 |
| PROJ-69 | 3.2   | Voice-Hooks Silence-Detection-Extraktion — gemeinsamer Hook für die duplizierte RMS-AnalyserNode-Logik aus useVoiceMode1/2, kein Verhaltensunterschied                                                                  | Deployed | [Spec](PROJ-69-voice-hook-silence-detection-extraction.md) | 2026-07-19 |
| PROJ-70 | 3.2   | Browser Adaptiver Noise-Floor — Kalibrierungsfenster pro Aufnahme statt Fixwert 700/0.01, analog zu PROJ-57 für die WebApp-Sprachmodi                                                                                    | Deployed | [Spec](PROJ-70-browser-adaptive-noise-floor.md) | 2026-07-19 |
| PROJ-71 | 3.2   | Chat State-Management-Layer — useChatSessions.ts auf zentralen Reducer/Dispatch statt 13+ verstreuter setMessagesBySession-Aufrufe umgestellt, kein Verhaltensunterschied                                               | Deployed | [Spec](PROJ-71-chat-state-management-layer.md) | 2026-07-19 |

<!-- Add features above this line -->

## Next Available ID: PROJ-72
