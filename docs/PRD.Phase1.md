# Product Requirements Document — Phase 1

> Phase 1 (PROJ-1–PROJ-39) ist abgeschlossen.
> Aktueller Entwicklungsstand → `docs/summaries/phase1-summary.md`
> Phase-2-Roadmap → `docs/PRD.md`

## Vision

Alice ist ein lokaler, KI-first und Sprache-first Personal Assistant und Smart Home Controller. Das System vereint Haussteuerung, Dokumentenmanagement, Finanzen und persönliche Assistenz unter einer einzigen intelligenten Schnittstelle – ohne dass der Nutzer zwischen verschiedenen Systemen unterscheiden muss. Alle KI-Inferenz läuft lokal, der Zugang nur über VPN.

## Target Users

**Primär: Andreas** (Admin)
- Technikaffiner Hausbesitzer mit Interesse an KI, Smart Home, Garten und Finanzen
- Nutzt das System täglich für Haussteuerung, Dokumentensuche und Informationen
- Bevorzugt deutschen, technisch detaillierten Dialog

**Sekundär: Partner und Gäste**
- Abgestufte Berechtigungen (User/Guest)
- Einfachere Sprache, weniger Systemzugriff

**Schmerz:** Zu viele Systeme (HA, NAS, Finanzen, Dokumente) erfordern manuelle Navigation. Sprachsteuerung über HA ist unflexibel. Kein systemübergreifendes Gedächtnis.

## Core Features (Roadmap Phase 1)

| Priority | Feature                                                              | Phase | Status   |
| -------- | -------------------------------------------------------------------- | ----- | -------- |
| P0 (MVP) | Infrastruktur: DB-Schema & Weaviate HAIntent Collection              | 1.1   | Deployed |
| P0 (MVP) | React Chat Frontend (Text-basiert)                                   | 1.1   | Deployed |
| P0 (MVP) | n8n Chat-Handler Grundgerüst mit Memory                              | 1.1   | Deployed |
| P0 (MVP) | FastAPI Container + Python Helper (hassil)                           | 1.2   | Deployed |
| P0 (MVP) | HA-First Chat-Handler mit Intent-Routing                             | 1.2   | Deployed |
| P0 (MVP) | HA Auto-Sync via MQTT                                                | 1.2   | Deployed |
| P0 (MVP) | Hassil Native Library Integration (Expansion Engine Upgrade)         | 1.2   | Deployed |
| P0 (MVP) | Hassil expansion_rules Compatibility Fix                             | 1.2   | Deployed |
| P0 (MVP) | HA Sync Python Worker (Ersatz n8n alice-ha-intent-sync)              | 1.2   | Deployed |
| P1       | JWT Auth / Login Screen                                              | 1.5   | Deployed |
| P1       | DMS NAS-Ordner-Verwaltung (PROJ-15)                                  | 1.4   | Deployed |
| P1       | DMS Scanner & NAS-Infrastruktur (PROJ-16)                            | 1.4   | Deployed |
| P1       | DMS Scanner Multi-Queue-Routing (PROJ-17)                            | 1.4   | Deployed |
| P1       | DMS Text-Extractor-Container (PROJ-18)                               | 1.4   | Deployed |
| P1       | DMS Processor Workflow (PROJ-19)                                     | 1.4   | Deployed |
| P1       | DMS Document Search Tool (PROJ-20)                                   | 1.4   | Deployed |
| P1       | DMS Lifecycle Management (PROJ-21/22)                                | 1.4   | Deployed |
| P1       | DMS Security Hardening (PROJ-23/24/25)                               | 1.4   | Deployed |
| P1       | Admin Nutzerverwaltung (PROJ-26)                                     | 1.5   | Deployed |
| P1       | BankStatement Transaction Indexing (PROJ-29)                         | 1.6   | Deployed |
| P1       | Streaming Chat Backend — alice-chat-stream (PROJ-30)                 | 1.6   | Deployed |
| P1       | Frontend Streaming-UI (PROJ-31)                                      | 1.6   | Deployed |
| P1       | RS256-Migration alice-auth + n8n (PROJ-34/36)                        | 1.6   | Deployed |
| P1       | Chat Frontend Redesign (PROJ-35)                                     | 1.6   | Deployed |
| P1       | Streaming Verbosity — Thinking + angereicherte Tool-Events (PROJ-37) | 1.6   | Deployed |
| P1       | alice-ha-sync Overhaul — Conversation Filter, Area Registry (PROJ-39)| 1.6   | Deployed |

## Success Metrics

| Metrik                            | Zielwert                    |
| --------------------------------- | --------------------------- |
| Einfacher HA-Befehl Latenz        | < 200ms End-to-End          |
| Multi-Intent Latenz (2-3 Befehle) | < 400ms                     |
| LLM-Antwort (Chat)                | < 3s                        |
| Intent-Erkennung Accuracy         | > 90% bei Standard-Befehlen |
| Auto-Sync nach Entity-Änderung    | < 60s                       |
| System-Uptime                     | > 99% (lokal, nur über VPN) |

## Constraints

- **Lokal-First**: Keine Cloud-Abhängigkeiten für Kernfunktionen
- **Hardware**: Ryzen 9 + RTX 3090 (LLM) + TITAN X (Embeddings/Weaviate)
- **Zugang**: Nur über VPN erreichbar (kein öffentliches Internet)
- **Sprache**: Primär Deutsch; Docs auf Deutsch, Code/Commits auf Englisch
- **Team**: Solo-Projekt (Andreas), Hobbyzeit (3-4h/Tag)
- **Stack**: n8n + Ollama (qwen3:14b) + Weaviate + PostgreSQL + React/Next.js

## Non-Goals Phase 1

- Keine Cloud-LLM-Pflicht (optional für spezifische Use-Cases)
- Keine öffentliche API / kein Multi-Tenant-Betrieb
- Keine Mobile App (PWA reicht)
- Kein Echtzeit-Video/Bild-Verarbeitung im DMS
- Keine Spracherkennung (→ Phase 2)
