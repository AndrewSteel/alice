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

| ID      | Phase | Feature                                                                                                                                   | Status  | Spec | Created    |
| ------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------ | ------- | ---- | ---------- |
| PROJ-53 | 3.2   | Mail-Anhang DMS-Import — E-Mail-Anhänge automatisch in DMS-Pipeline einspeisen + Mail-Thumbnails; Abhängigkeit von PROJ-46; verschoben aus Phase 4 | In Review | [Spec](PROJ-53-mail-anhang-dms-import.md) | 2026-06-24 |
| PROJ-78 | 3.1   | DMS-Dokumentenklassifizierung — Fix + Backfill Bestand (falsch klassifizierte Rechnungen im Document-Schema)                              | Deployed | [Spec](PROJ-78-dms-dokumentenklassifizierung-fix-backfill.md) | 2026-08-17 |
| PROJ-79 | 3.1   | DMS-Zusammenfassung Sprachkorrektur — nur Deutsch, Fix + Backfill Bestand                                                                  | Deployed | [Spec](PROJ-79-dms-zusammenfassung-sprachkorrektur.md) | 2026-08-17 |
| PROJ-80 | 3.2   | DMS-Vollständigkeits-Dashboard — Coverage-Übersicht (Pfad-Scan vs. Weaviate/Thumbnail/Geo je Dokument); Abhängigkeit von PROJ-77           | Deployed | [Spec](PROJ-80-dms-vollstaendigkeits-dashboard.md) | 2026-08-17 |
| PROJ-81 | 3.2   | Frontend-Übersetzung on-the-fly — deutsche Zusammenfassung → Nutzersprache; Abhängigkeit von PROJ-79                                       | Roadmap | —    | 2026-08-17 |
| PROJ-82 | 3.3   | HA-MCP-Server-Evaluierung — Spike, Go/No-Go-Vergleichsdokument (aktuelle n8n-Intent-Steuerung vs. MCP-Server)                              | Roadmap | —    | 2026-08-17 |
| PROJ-83 | 3.3   | HA-Agent variable Intents — Prozent-Werte, Mengen, Listen-Einträge; Abhängigkeit von PROJ-82                                               | Roadmap | —    | 2026-08-17 |
| PROJ-84 | 3.3   | HA-Agent Area-Context-Weitergabe — Device-Area an HA übergeben; Abhängigkeit von PROJ-82                                                   | Roadmap | —    | 2026-08-17 |
| PROJ-85 | 3.3   | Timer-Agent — Timer/Wecker setzen, ändern, abfragen, löschen                                                                               | Roadmap | —    | 2026-08-17 |
| PROJ-86 | 3.3   | Google-API-Infrastruktur — OAuth-Flow, Token-Storage/Refresh/Verschlüsselung, wiederverwendbarer Connection-Mechanismus                    | Roadmap | —    | 2026-08-17 |
| PROJ-87 | 3.4   | Kalender-Agent — Settings-Tab „Kalender" (mehrere Google-Kalender pro User, analog Postfach-Verwaltung) + Chat-CRUD; Abhängigkeit von PROJ-86 | Roadmap | —    | 2026-08-17 |
| PROJ-88 | 3.4   | Aufgaben-Agent — Settings-Tab „Aufgaben" (mehrere Google-Aufgabenlisten pro User) + Chat-CRUD; Abhängigkeit von PROJ-86                    | Roadmap | —    | 2026-08-17 |
| PROJ-89 | 3.4   | Kontakte-Agent — Settings-Tab „Kontakte" (mehrere Google-Kontaktbücher pro User) + Chat-CRUD; Abhängigkeit von PROJ-86                     | Roadmap | —    | 2026-08-17 |
| PROJ-90 | 3.4   | Websearch-Agent — Plan → begrenzter Such-Loop → qualifiziertes Ergebnis, hartes Loop-Limit                                                  | Roadmap | —    | 2026-08-17 |
| PROJ-91 | 3.2   | Synchroner Office-Textextraktor — HTTP-Wrapper (z.B. markitdown) für DOCX/XLSX/ODT/ODS als Ersatz/Ergänzung zu `dms-extractor-office`; schließt Volltext-Klassifizierungslücke aus PROJ-53 | Roadmap | —    | 2026-08-23 |

<!-- Add features above this line -->

## Next Available ID: PROJ-92