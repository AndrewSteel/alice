# Product Requirements Document — Phase 3

> Phase 1 (PROJ-1–PROJ-39) und Phase 2 (PROJ-40–PROJ-77) sind abgeschlossen.
> Phase-1-Roadmap → `docs/PRD.Phase1.md`
> Phase-2-Roadmap → `docs/PRD.Phase2.md`

## Vision

Phase 3 macht die DMS-Datenbasis vertrauenswürdig (korrekte Klassifizierung, durchgängig deutsche Zusammenfassungen, volle Sichtbarkeit über den Verarbeitungsstand) und erweitert Alice um eigenständige Agenten (Timer, Google Kalender/Aufgaben/Kontakte, Websuche) sowie eine leistungsfähigere Smart-Home-Steuerung mit variablen Intents und Raumkontext.

## Target Users

**Primär: Andreas** (Admin)
- Primärer und aktuell einziger aktiver Nutzer
- Verlässt sich zunehmend auf die DMS-Wissensbasis (Rechnungen, Dokumente) und erwartet korrekte Klassifizierung und Sprache
- Möchte Alice als vollwertigen Assistenten nutzen — Timer, Kalender, Aufgaben, Kontakte, aktuelle Web-Informationen, präzisere Smart-Home-Steuerung

**Schmerz Phase 3:** Falsch klassifizierte bzw. englische DMS-Daten untergraben das Vertrauen in die Wissensbasis; kein Überblick über die Verarbeitungs-Vollständigkeit der DMS-Pipeline; der Assistent kann keine Timer, Kalender, Aufgaben oder Kontakte verwalten und keine aktuellen Web-Informationen abrufen; Smart-Home-Befehle mit Werten (%, Mengen) oder Raumbezug scheitern.

## Core Features (Roadmap Phase 3)

| Priority | Feature                                                                                                          | Sub-Phase | Status  |
| -------- | ----------------------------------------------------------------------------------------------------------------- | --------- | ------- |
| P0       | DMS-Dokumentenklassifizierung — Fix + Backfill Bestand (PROJ-78)                                                   | 3.1       | Planned |
| P0       | DMS-Zusammenfassung Sprachkorrektur (Deutsch) — Fix + Backfill Bestand (PROJ-79)                                   | 3.1       | Deployed |
| P1       | DMS-Vollständigkeits-Dashboard (PROJ-80)                                                                           | 3.2       | Deployed |
| P1       | Frontend-Übersetzung on-the-fly (PROJ-81)                                                                          | 3.2       | Roadmap |
| P2       | Mail-Anhang DMS-Import (PROJ-53, verschoben aus Phase 4)                                                           | 3.2       | Roadmap |
| P1       | HA-MCP-Server-Evaluierung — Spike (PROJ-82)                                                                        | 3.3       | Roadmap |
| P1       | HA-Agent variable Intents — Prozent, Mengen, Listen-Einträge (PROJ-83)                                             | 3.3       | Roadmap |
| P1       | HA-Agent Area-Context-Weitergabe (PROJ-84)                                                                         | 3.3       | Roadmap |
| P1       | Timer-Agent (PROJ-85)                                                                                              | 3.3       | Roadmap |
| P1       | Google-API-Infrastruktur (PROJ-86)                                                                                 | 3.3       | Roadmap |
| P2       | Kalender-Agent — inkl. Settings-Tab „Kalender", mehrere Google-Kalender pro User (PROJ-87)                         | 3.4       | Roadmap |
| P2       | Aufgaben-Agent — inkl. Settings-Tab „Aufgaben", mehrere Google-Aufgabenlisten pro User (PROJ-88)                   | 3.4       | Roadmap |
| P2       | Kontakte-Agent — inkl. Settings-Tab „Kontakte", mehrere Google-Kontaktbücher pro User (PROJ-89)                    | 3.4       | Roadmap |
| P2       | Websearch-Agent — Plan → begrenzter Such-Loop → Antwort (PROJ-90)                                                  | 3.4       | Roadmap |

## Success Metrics

| Metrik                                                                    | Zielwert                                     |
| -------------------------------------------------------------------------- | --------------------------------------------- |
| Fälschlich klassifizierte Rechnungen im `Document`-Schema nach Backfill    | 0                                             |
| Zusammenfassungen (Bestand + neu) auf Deutsch                              | 100 %                                         |
| DMS-Vollständigkeits-Dashboard zeigt Coverage-% je Schritt und Pfad        | Weaviate/Thumbnail/Geo je Dokumenttyp sichtbar |
| Variable HA-Intents (%-Werte, Mengen) funktionsfähig                       | Rolladen, Licht, Einkaufsliste                |
| Timer/Wecker per Sprache setz-, änder-, abfrag-, löschbar                  | ja                                            |
| Google-Agenten ohne lokale Datenspeicherung                                | nur Live-Abfragen                             |
| Mehrere Google-Kalender/-Aufgabenlisten/-Kontaktbücher pro User verwaltbar | im Settings-Tab, analog Postfach-Verwaltung   |
| Websearch-Agent Such-Loop begrenzt                                         | hartes Maximum, keine Endlosschleife          |

## Constraints

- **Lokal-First** bleibt Grundprinzip. **Ausnahme**: Google- und Websearch-Agenten benötigen zwingend Cloud-Zugriff (keine lokale Alternative) — nur Live-Abfragen, kein lokales Caching der Google-Daten
- **Hardware**: Ryzen 9 + RTX 3090 (LLM + Whisper) + TITAN X (Embeddings + Speaker-ID)
- **Zugang**: Nur über VPN erreichbar (kein öffentliches Internet)
- **Sprache**: Primär Deutsch; Docs auf Deutsch, Code/Commits auf Englisch
- **Team**: Solo-Projekt (Andreas), Hobbyzeit (3–4h/Tag)
- **Stack**: n8n + PostgreSQL + Weaviate + Ollama, wie bisher
- **Phase 1+2 Basis**: PROJ-1–77 deployed — JWT-Auth, DMS-Pipeline, HA-Sync, Speech-Gateway, Chat-Storage, Admin-Dashboard

## Non-Goals Phase 3

- Kein PROJ-45 Display Registry / Multi-Display-Routing (→ Phase 4)
- Keine vertiefte Finanzanalyse / PROJ-59 (→ Phase 4)
- Kein Sprache-vs-TV/Radio-Trennung / PROJ-58 (→ Phase 5)
- Kein Multi-Provider-Kalender/-Aufgaben/-Kontakte (nur Google; mehrere Konten/Kalender innerhalb Google sind vorgesehen)
- Keine lokale Synchronisation/Spiegelung der Google-Daten in PostgreSQL/Weaviate

---

Use `/write-spec` to create detailed feature specifications for each item in the roadmap above.
