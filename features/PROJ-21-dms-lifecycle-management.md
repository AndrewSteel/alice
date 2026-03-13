# PROJ-21: DMS Lifecycle Management (Duplikate, Verschiebungen, Dateiänderungen)

## Status: Planned
**Created:** 2026-03-12
**Last Updated:** 2026-03-12

## Dependencies
- Requires: PROJ-17 (DMS Scanner Multi-Queue) — Workflow `alice-dms-scanner` muss deployed sein
- Requires: PROJ-19 (DMS Processor) — Redis-Mappings `alice:dms:path_to_hash` und `alice:dms:hash_to_paths:<hash>` müssen vom Processor befüllt werden
- Weaviate Collections müssen existieren (PROJ-19)

## Overview

Erweiterung des `alice-dms-scanner` Workflows und des `alice-dms-processor` Workflows um die Erkennung und Behandlung von drei Datei-Lifecycle-Ereignissen, die über den Normalfall (neue Datei) hinausgehen:

| Fall | Beschreibung | Erkennung | Behandlung |
|---|---|---|---|
| **Fall 1 – Duplikat** | Gleicher Inhalt (Hash), anderer Pfad, Originalpfad noch vorhanden | Scanner | Weaviate-Eintrag um neuen Pfad erweitern (kein LLM-Aufruf) |
| **Fall 2 – Verschiebung** | Gleicher Inhalt (Hash), anderer Pfad, Originalpfad verschwunden | Scanner | Weaviate-Eintrag: `original_path` auf neuen Pfad aktualisieren (kein LLM-Aufruf) |
| **Fall 3 – Dateiänderung** | Gleicher Pfad, anderer Hash | Scanner erkennt, Processor behandelt | Weaviate: ALTER Eintrag löschen, NEUEN Eintrag vollständig verarbeiten (LLM-Aufruf) |

**Fall 4 (Dateilöschung)** ist explizit nicht Teil dieses Projekts. Da gelöschte Dateien keinen Scan-Event erzeugen, kann dieser Fall nicht im Scanner erkannt werden. Er erfordert einen eigenständigen Reconciliation-Sprint.

Die Grundlage für alle drei Fälle sind die Redis-Mappings, die PROJ-19 nach jedem erfolgreichen Weaviate-Insert befüllt:
- `alice:dms:path_to_hash` (Redis Hash) — Pfad → Hash
- `alice:dms:hash_to_paths:<hash>` (Redis Set) — Hash → alle bekannten Pfade

## User Stories

- Als System möchte ich erkennen, wenn eine bereits verarbeitete Datei an einen anderen Ort kopiert wurde (Duplikat), damit der neue Pfad in Weaviate als zusätzlicher Zugriffspfad hinterlegt wird.
- Als System möchte ich erkennen, wenn eine bereits verarbeitete Datei verschoben wurde, damit der veraltete Pfad in Weaviate aktualisiert wird und Suchergebnisse nicht auf nicht-existente Pfade zeigen.
- Als System möchte ich erkennen, wenn eine bereits verarbeitete Datei inhaltlich geändert wurde (gleicher Pfad, neuer Inhalt), damit der veraltete Weaviate-Eintrag ersetzt und die neuen Inhalte vollständig klassifiziert und indiziert werden.
- Als Admin möchte ich, dass Duplikat- und Verschiebungs-Erkennungen ohne LLM-Aufruf ablaufen, damit die GPU nicht unnötig belastet wird.

## Acceptance Criteria

### Scanner-Erweiterung (alice-dms-scanner)

- [ ] Für jede gescannte Datei: nach Hash-Berechnung Lookup in `alice:dms:path_to_hash` (HGET mit `file_path`)
  - [ ] Ergebnis: bekannter Hash für diesen Pfad (→ Fall 3 prüfen) oder kein Eintrag (→ Normalpfad)
- [ ] **Fall 3 (Dateiänderung)**: `path_to_hash[file_path]` vorhanden UND gespeicherter Hash ≠ aktueller Hash
  - [ ] Datei wird mit `action: "replace"` und `old_hash` in die typenspezifische MQTT-Queue gestellt
  - [ ] Alter Hash wird aus `alice:dms:processed` entfernt (`SREM`) → erzwingt Neuverarbeitung
  - [ ] Alter Hash wird in `alice:dms:queued_files` nicht nochmals eingetragen (new hash wird gequeuet)
- [ ] Für Dateien mit bereits bekanntem Hash (bisher: skip): `alice:dms:hash_to_paths:<hash>` prüfen
  - [ ] **Fall 1 (Duplikat)**: Hash bekannt, bekannte Pfade in `hash_to_paths` existieren noch alle auf NAS → `action: "add_path"` direkt an Processor-Queue (ohne Textextraktion)
  - [ ] **Fall 2 (Verschiebung)**: Hash bekannt, alle bekannten Pfade in `hash_to_paths` existieren NICHT mehr auf NAS → `action: "update_path"` direkt an Processor-Queue (ohne Textextraktion)
- [ ] Für Fälle 1 und 2: Nachrichten gehen direkt in eine neue Queue `alice/dms/lifecycle` (kein Extractor-Umweg, da kein Plaintext benötigt)

### Weaviate-Schema-Erweiterung

- [ ] Alle 6 Collections erhalten ein zusätzliches Feld `additional_paths` (Array of String) für Duplikat-Pfade
- [ ] `original_path` bleibt als primäres Feld erhalten

## Edge Cases

- **Weder Fall 1 noch Fall 2 eindeutig** (einige bekannte Pfade existieren noch, andere nicht): Behandlung als Fall 1 (konservativ, kein Datenverlust). Nicht mehr existente Pfade werden aus `hash_to_paths` entfernt, neue Pfade hinzugefügt.
- **`hash_to_paths` leer obwohl Hash in `processed`** (Inkonsistenz, z.B. aus Altdaten vor PROJ-21): Behandlung wie neue Datei — Skip des Lifecycle-Checks, normaler Prozessfluss.
- **Fall 3: Dateiänderung + gleichzeitiger LLM-Timeout**: Normales Fehlerverhalten des Processors — alter Hash wurde bereits aus `processed` entfernt; beim nächsten Nacht-Lauf wird die Datei erneut verarbeitet.
- **Pfad-Check auf NAS schlägt fehl** (NAS nicht erreichbar): Lifecycle-Checks für Fall 1/2 werden übersprungen; Scanner loggt Warnung. Nächster Scan-Run versucht es erneut.
- **Mehrere Verschiebungen in Folge**: Jede Verschiebung wird als eigenes Lifecycle-Event erkannt; `hash_to_paths` und `path_to_hash` werden bei jeder Operation konsistent aktualisiert.

## Technical Requirements

- **Geänderte Workflows**: `alice-dms-scanner` (Lifecycle-Erkennung + Routing) + `alice-dms-processor` (Fall-3-Handling bereits via PROJ-19 Dedup-before-insert abgedeckt)
- **Neue MQTT-Queue**: `alice/dms/lifecycle` — für Fälle 1 und 2; wird von `alice-dms-lifecycle` (PROJ-22) konsumiert
- **NAS-Pfad-Check im Scanner**: Datei-Existenz-Prüfung — Scanner muss NAS-Zugriff haben (bereits vorhanden via NAS-Mount in n8n)
- **Keine neuen n8n Credentials** — gleiche wie PROJ-19
- **Workflow-Datei**: `workflows/core/alice-dms-scanner.json`
- **Verarbeitung der lifecycle Queue**: eigenständiger Workflow `alice-dms-lifecycle` (PROJ-22)

## Lifecycle-Nachrichtenformat (alice/dms/lifecycle Queue)

```json
{
  "action": "add_path",
  "file_hash": "sha256:abc123...",
  "file_path": "/mnt/nas/projekte/kopie/rechnung.pdf",
  "detected_at": "2026-03-12T03:00:00Z"
}
```

```json
{
  "action": "update_path",
  "file_hash": "sha256:abc123...",
  "file_path": "/mnt/nas/projekte/neu/rechnung.pdf",
  "old_paths": ["/mnt/nas/projekte/alt/rechnung.pdf"],
  "detected_at": "2026-03-12T03:00:00Z"
}
```

---
<!-- Sections below are added by subsequent skills -->

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
