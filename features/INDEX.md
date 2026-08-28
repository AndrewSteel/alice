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
| PROJ-53 | 3.2   | Mail-Anhang DMS-Import — E-Mail-Anhänge automatisch in DMS-Pipeline einspeisen + Mail-Thumbnails; Abhängigkeit von PROJ-46; verschoben aus Phase 4 | Deployed | [Spec](PROJ-53-mail-anhang-dms-import.md) | 2026-08-26 |
| PROJ-55 | 2     | DMS Thumbnail-Generierung — quadratisches Vorschaubild je Dokument (Laufzeit + Backfill); Refine 2026-08-28: 3 Bugs gefunden und behoben (Merge-Node verwarf failed/skipped aus Response, UUID-Logging kaputt, unbehandelte 500er bei Konvertierungsfehlern) — Deploy + Verifikationslauf ausstehend | In Progress | [Spec](phase-2/PROJ-55-dms-thumbnail-generation.md) | 2026-06-27 |
| PROJ-78 | 3.1   | DMS-Dokumentenklassifizierung — Fix + Backfill Bestand (falsch klassifizierte Rechnungen im Document-Schema)                              | Deployed | [Spec](PROJ-78-dms-dokumentenklassifizierung-fix-backfill.md) | 2026-08-26 |
| PROJ-79 | 3.1   | DMS-Zusammenfassung Sprachkorrektur — nur Deutsch, Fix + Backfill Bestand                                                                  | Deployed | [Spec](PROJ-79-dms-zusammenfassung-sprachkorrektur.md) | 2026-08-26 |
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
| PROJ-91 | 3.2   | Synchroner Office-Textextraktor — erweitert `alice-mail-reader`s `/attachment-text` um DOCX/XLSX/ODT/ODS (python-docx/openpyxl/odfpy statt markitdown, Alpine/musl-Kompatibilität); schließt Volltext-Klassifizierungslücke aus PROJ-53; `dms-extractor-office` bleibt unverändert. QA: 1 Medium-Bug (unbegrenzter Speicher-/Zeitverbrauch bei komprimierbaren Anhängen vor Truncation, gleiches Muster wie im bereits produktiven PDF-Pfad, kein Blocker) | Deployed | [Spec](PROJ-91-synchroner-office-textextraktor.md) | 2026-08-23 |
| PROJ-92 | 3.1   | Bug: `confirm`-Parameter wirkungslos in `alice-dms-language-backfill` **und** `alice-dms-classification-backfill` (bestätigt per Code-Lesung; identisches Muster wie der behobene Bug in `alice-mail-attachment-backfill`, siehe PROJ-53) — Ursache: vorgeschalteter Lock-Node gibt ein neues Item ohne `body`/`query` zurück, `Code: Init Backfill Run` liest aber `$input.first().json.body` statt per Node-Name auf den Webhook zuzugreifen. Confirm-Gate war seit Einführung nie über den Webhook erreichbar, Workflows liefen immer im Dry-Run. Zusätzlicher Nebenfund: `MAX_RUNTIME_SECONDS`-Override ebenfalls wirkungslos (hardcoded 7200 in `Code: Time Check`, beide Workflows). Fix analog zum PROJ-53-Fix (Commit `8581996`). | Deployed | [Spec](PROJ-92-dms-backfill-confirm-gate-fix.md) | 2026-08-23 |
| PROJ-93 | 3.2   | Bug: Mail-Objekte bekommen nie ein Thumbnail (BUG-15, bei PROJ-53-Iteration-4-QA gefunden, vorbestehend seit Iteration 1) — `alice-dms-thumbnailer`s `Code: Parse & Filter` verwirft Nachrichten ohne `file_path`, `alice-mail-sync`s `MQTT: Publish Email Done` sendet keinen. Fix: kein Platzhalter-Pfad, stattdessen liest der Thumbnailer-Workflow Betreff+Body-Preview per Weaviate REST-GET direkt (neuer Mail-spezifischer Text-Rendering-Modus im Thumbnailer-Service, kein Datei-Zugriff nötig). QA: 7/7 AC, 0 Bugs | Deployed | [Spec](PROJ-93-mail-thumbnail-fix.md) | 2026-08-24 |
| PROJ-94 | 3.1   | DMS Path-Worker Zeitlimit — kontrollierter Abbruch nach 2h statt unbegrenzter Laufzeit (bei PROJ-53-Abschlussprüfung entdeckt, Robustheitsfix, kein GPU-Bezug) | Deployed | [Spec](PROJ-94-dms-path-worker-time-limit.md) | 2026-08-24 |

<!-- Add features above this line -->

## Next Available ID: PROJ-95