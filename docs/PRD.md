# Product Requirements Document

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

## Core Features (Roadmap)

| Priority | Feature | Phase | Status |
|----------|---------|-------|--------|
| P0 (MVP) | Infrastruktur: DB-Schema & Weaviate HAIntent Collection | 1.1 | Deployed |
| P0 (MVP) | React Chat Frontend (Text-basiert) | 1.1 | Deployed |
| P0 (MVP) | n8n Chat-Handler Grundgerüst mit Memory | 1.1 | Deployed |
| P0 (MVP) | FastAPI Container + Python Helper (hassil) | 1.2 | Deployed |
| P0 (MVP) | HA-First Chat-Handler mit Intent-Routing | 1.2 | Deployed |
| P0 (MVP) | HA Auto-Sync via MQTT | 1.2 | Deployed |
| P0 (MVP) | Hassil Native Library Integration (Expansion Engine Upgrade) | 1.2 | Planned |
| P1 | JWT Auth / Login Screen | 1.5 | Planned |
| P1 | DMS-Pipeline (NAS → Weaviate) | 1.4 | Planned |
| P1 | Memory-Transfer PostgreSQL → Weaviate | 1.5 | Planned |
| P2 | Speech Gateway (Whisper STT + Piper TTS) | 2 | Planned |
| P2 | Speaker-ID / Sprechererkennung | 2 | Planned |
| P3 | Multi-User-Handling & Display-Routing | 3 | Planned |
| P3 | WebAuthn / Passkeys | 3 | Planned |

## Success Metrics

| Metrik | Zielwert |
|--------|----------|
| Einfacher HA-Befehl Latenz | < 200ms End-to-End |
| Multi-Intent Latenz (2-3 Befehle) | < 400ms |
| LLM-Antwort (Chat) | < 3s |
| Intent-Erkennung Accuracy | > 90% bei Standard-Befehlen |
| Auto-Sync nach Entity-Änderung | < 60s |
| System-Uptime | > 99% (lokal, nur über VPN) |

## Constraints

- **Lokal-First**: Keine Cloud-Abhängigkeiten für Kernfunktionen
- **Hardware**: Ryzen 9 + RTX 3090 (LLM) + TITAN X (Embeddings/Weaviate)
- **Zugang**: Nur über VPN erreichbar (kein öffentliches Internet)
- **Sprache**: Primär Deutsch; Docs auf Deutsch, Code/Commits auf Englisch
- **Team**: Solo-Projekt (Andreas), Hobbyzeit (3-4h/Tag)
- **Stack**: n8n + Ollama (qwen2.5:14b) + Weaviate + PostgreSQL + React/Vite

## Non-Goals

- Keine Cloud-LLM-Pflicht (optional für spezifische Use-Cases)
- Keine öffentliche API / kein Multi-Tenant-Betrieb
- Keine Mobile App (PWA reicht)
- Kein Echtzeit-Video/Bild-Verarbeitung im DMS (Phase 1)
- Keine Spracherkennung vor Phase 2

---

Use `/requirements` to create detailed feature specifications for each item in the roadmap above.
