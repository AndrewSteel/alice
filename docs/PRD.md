# Product Requirements Document — Phase 2

> Phase 1 (PROJ-1–PROJ-39) ist abgeschlossen.
> Phase-1-Roadmap → `docs/PRD.Phase1.md`
> Entwicklungsstand Phase 1 → `docs/summaries/phase1-summary.md`

## Vision

Phase 2 transformiert Alice von einem text-basierten in einen vollständigen **Sprache-First-Assistenten**. Ein zentraler Speech-Gateway-Service verbindet HA-Voice-Geräte und WebApp mit derselben KI-Pipeline. Sprechererkennung ermöglicht automatische Nutzeridentifikation per Stimme und schafft die Grundlage für rollenbasierte Berechtigungen ohne manuelle Authentifizierung.

## Target Users

**Primär: Andreas** (Admin)
- Möchte Alice aus verschiedenen Räumen per Sprache nutzen — über HA-Voice-Geräte (Wakeword) und die WebApp (Mikrofon-Button)
- Sprechererkennung soll ihn automatisch identifizieren, ohne Login
- Display-Routing soll es ermöglichen, Ergebnisse gezielt auf Wallpanel, TV oder PC zu senden

**Sekundär: Partner und Gäste**
- Abgestufte Berechtigungen, erkannt per Stimme (Phase 2.2+)
- Einfache Sprach-Interaktion ohne Admin-Zugriff

**Schmerz Phase 2:** Alice ist nur per Texteingabe am Browser nutzbar. Keine Sprachsteuerung über HA-Voice-Geräte mit zentraler KI. Kein Hands-free-Betrieb im Haushalt.

## Core Features (Roadmap Phase 2)

| Priority | Feature                                          | Phase | Status  |
| -------- | ------------------------------------------------ | ----- | ------- |
| P0       | Speech Gateway Service (PROJ-40)                 | 2.1   | Planned |
| P0       | WebApp Voice Interface (PROJ-41)                 | 2.1   | Planned |
| P1       | Home Assistant Voice Integration (PROJ-42)       | 2.2   | Planned |
| P1       | Speaker Recognition / Speaker-ID (PROJ-43)       | 2.2   | Roadmap |
| P1       | DMS BankTransaction Lifecycle Cleanup (PROJ-44)  | 2.1   | Roadmap |
| P2       | Display Registry & Output Router (PROJ-45)       | 2.3   | Roadmap |
| P2       | Mail IMAP Integration (PROJ-46)                  | 2.3   | Roadmap |

## Success Metrics

| Metrik                                        | Zielwert                           |
| --------------------------------------------- | ---------------------------------- |
| Sprach-Latenz WebApp (STT + LLM + TTS)        | < 3s                               |
| HA-Voice End-to-End (Wakeword → TTS-Antwort)  | < 4s                               |
| Sprechererkennung Accuracy                    | > 95% bei eintrainierten Sprechern |
| DMS BankTransaction: verwaiste Objekte        | 0 nach Parent-Löschung             |
| System-Uptime                                 | > 99% (lokal, nur über VPN)        |

## Constraints

- **Lokal-First**: Keine Cloud-Abhängigkeiten für Kernfunktionen
- **Hardware**: Ryzen 9 + RTX 3090 (LLM + Whisper) + TITAN X (Embeddings + Speaker-ID)
- **Zugang**: Nur über VPN erreichbar (kein öffentliches Internet)
- **Sprache**: Primär Deutsch; Docs auf Deutsch, Code/Commits auf Englisch
- **Team**: Solo-Projekt (Andreas), Hobbyzeit (3–4h/Tag)
- **Stack**: Python-Services + n8n + React/Next.js + Whisper + Piper + Wyoming-Protocol
- **Phase 1 Basis**: PROJ-1–39 deployed — JWT-Auth, DMS-Pipeline, HA-Sync, Streaming Chat (SSE), BankTransaction-Indexierung
- **Verschoben auf Phase 3**: Memory Transfer PostgreSQL → Weaviate, WebAuthn/Passkeys, Multi-User Display-Routing (erweitert)

## Non-Goals Phase 2

- Keine Cloud-LLM-Pflicht (optional für spezifische Use-Cases)
- Kein Echtzeit-Transkriptions-Streaming (chunk-basierte Verarbeitung reicht)
- Kein Memory Transfer (→ Phase 3)
- Kein WebAuthn (→ Phase 3, Datenstruktur in Phase 1 vorbereitet)
- Keine Finance-Ingestion-Pipeline (durch DMS + PROJ-29 bereits abgedeckt)
- Keine Mobile App (PWA reicht)
- Keine öffentliche API / kein Multi-Tenant-Betrieb

---

Use `/write-spec` to create detailed feature specifications for each item in the roadmap above.
