# PROJ-24: DMS Operational Improvements (Stats, LLM-Retry, MQTT-Reliability, Error-Handler)

## Status: Planned
**Created:** 2026-03-15
**Last Updated:** 2026-03-15

## Dependencies
- Requires: PROJ-16 (DMS Scanner) — Workflow `alice-dms-scanner` muss deployed sein
- Requires: PROJ-18 (DMS Text-Extractor-Container) — alle 4 Extractor-Container müssen deployed sein
- Requires: PROJ-19 (DMS Processor) — Workflow `alice-dms-processor` muss deployed sein
- Requires: PROJ-22 (DMS Lifecycle Workflow) — Workflow `alice-dms-lifecycle` muss deployed sein

## Overview

Behebung von fünf Zuverlässigkeits- und Betriebsqualitäts-Findings aus den QA-Runden von PROJ-16, PROJ-18, PROJ-19, PROJ-21 und PROJ-22. Keine Sicherheitsrelevanz — alle Findings betreffen Monitoring, Retry-Mechanismen und Fehlerbehandlung.

| Bug | Komponente | Schweregrad | Beschreibung |
|-----|------------|-------------|--------------|
| PROJ-16 BUG-2 | `alice-dms-scanner` (n8n) | Medium | Keine finale Stats-Aggregation nach dem File-Loop |
| PROJ-19 BUG-6 | `alice-dms-processor` (n8n) | Medium | Kein LLM-Retry bei ungültigem JSON (Spec: 1× Retry) |
| PROJ-21/22 BUG-9 | `alice-dms-lifecycle` (n8n) | Medium | `errorWorkflow`-Setting fehlt → Error-Trigger-Chain nie aktiv |
| PROJ-18 BUG-5 | Alle 4 Extractor-Container | Low | MQTT `clean_session=true` → Nachrichtenverlust bei Container-Neustart |
| PROJ-18 BUG-4 | `dms-extractor-office` | Low | `shutil.copy2` statt `shutil.copy` → potenzielle Metadaten-Fehler auf NAS |

## User Stories

- Als Admin möchte ich nach jedem Scanner-Lauf eine aggregierte Zusammenfassung (`scanned_dirs`, `scanned_files`, `new_files`, `skipped_files`, `errors`) im Execution Log sehen, damit ich auf einen Blick erkennen kann, ob der Scan wie erwartet verlaufen ist.
- Als System möchte ich bei einem ungültigen LLM-JSON-Response die Anfrage einmalig wiederholen, bevor auf den Fallback-Dokumenttyp "Document" zurückgefallen wird, damit vorübergehende LLM-Ausreißer nicht zu Qualitätsverlust führen.
- Als System möchte ich, dass der `alice-dms-lifecycle` Error-Trigger-Handler bei Workflow-Fehlern tatsächlich feuert und Fehlermeldungen an `alice/dms/error` publiziert, damit Weaviate/Redis-Inkonsistenzen sichtbar werden.
- Als System möchte ich, dass die Extractor-Container bei einem Neustart keine MQTT-Nachrichten verlieren, die während der Downtime eintreffen, damit eine kurze Restart-Periode nicht zu übersprungenen Dateien führt.
- Als System möchte ich, dass der Office-Extractor Dateien vom NAS mit `shutil.copy` statt `shutil.copy2` kopiert, damit restriktive NAS-Metadaten keine Extraktionsfehler erzeugen.

## Acceptance Criteria

### Fix 1: Scanner Stats-Aggregation (PROJ-16 BUG-2)

- [ ] Workflow `alice-dms-scanner`: nach dem Ende des File-Loops (`Loop: Files` Output 0 = done) existiert ein neuer Summary-Code-Node
- [ ] Summary-Node liest die akkumulierten Zähler (`new_files`, `skipped_files`, `errors`) aus dem Loop und gibt sie als finales Execution-Log-Item aus
- [ ] Ausgabe-Format: `{ scanned_dirs, scanned_files, new_files, skipped_files, errors, runtime_seconds }`
- [ ] Bei leerem Scan (kein Ordner / keine Dateien): vorhandene `Set: Empty Stats` und `Set: No Files Stats` Nodes werden um `runtime_seconds` ergänzt
- [ ] Kein bestehendes Scan-Verhalten wird geändert

### Fix 2: LLM-Retry in Processor (PROJ-19 BUG-6)

- [ ] Workflow `alice-dms-processor`: `Code: Parse Classify Result` implementiert einen 1× Retry wenn JSON-Parse fehlschlägt
- [ ] Retry: erneuter HTTP-Call an Ollama mit identischem Prompt; Timeout 30s
- [ ] Bei erneutem Fehler: Fallback auf `document_type: "Document"`, leeres Feldobjekt, `_llm_retry_failed: true` ins Item
- [ ] Analog: `Code: Parse Extract Result` implementiert einen 1× Retry bei JSON-Parse-Fehler der Feldextraktion
- [ ] Stats-Zähler `llm_retries` und `llm_retry_failures` werden in `alice:dms:run:stats` ergänzt

### Fix 3: errorWorkflow-Konfiguration (PROJ-21/22 BUG-9)

- [ ] n8n Workflow `alice-dms-lifecycle` hat nach dem Deploy in n8n das Setting **Settings → Error Workflow → `alice-dms-lifecycle`** konfiguriert (Workflow zeigt auf sich selbst)
- [ ] Nach der Konfiguration: Ein manuell erzeugter Workflow-Fehler (Test-Execution mit falschem Weaviate-Host) führt dazu, dass der Error-Trigger feuert und eine Nachricht an `alice/dms/error` publiziert wird
- [ ] Deploy-Checklist in PROJ-22 Deployment-Sektion wird mit diesem Schritt ergänzt
- [ ] Kein Code-Änderung erforderlich — dies ist ein Post-Deploy-Konfigurationsschritt

### Fix 4: MQTT Persistent Sessions in Extractor-Containern (PROJ-18 BUG-5)

- [ ] Alle vier Node.js Extractor-Container (`dms-extractor-pdf`, `dms-extractor-txt`): `mqtt.connect()` mit `clean: false` (statt `true`) und stabiler `clientId` (z.B. `dms-extractor-pdf` ohne Timestamp-Suffix)
- [ ] Beide Python Extractor-Container (`dms-extractor-ocr`, `dms-extractor-office`): `mqtt.Client(client_id="dms-extractor-ocr", clean_session=False)`
- [ ] Alle 4 Container erhalten einen stabilen, eindeutigen `clientId` ohne zufälligen Suffix
- [ ] Bestehende MQTT-Subscription-Logik (QoS 1, Topic, Reconnect) bleibt unverändert
- [ ] Container-Rebuild und Re-Deploy nach Code-Änderung

### Fix 5: shutil.copy statt shutil.copy2 (PROJ-18 BUG-4)

- [ ] `dms-extractor-office/main.py`: `shutil.copy2(src, tmp_path)` → `shutil.copy(src, tmp_path)`
- [ ] Kein weiterer Änderungsaufwand — single-line fix

## Edge Cases

- **Fix 1 – Stats-Zähler gehen verloren bei Workflow-Abbruch**: Stats werden nur im finalen Node ausgegeben, nicht in Redis persistiert — bei Abbruch kein Execution-Log-Summary, akzeptables Verhalten
- **Fix 2 – LLM beim Retry vollständig nicht erreichbar**: Retry schlägt nach Timeout (30s) fehl → Fallback auf "Document" wie heute; `llm_retry_failures` wird hochgezählt
- **Fix 2 – Retry liefert wiederum ungültiges JSON**: Fallback, kein weiterer Retry (max. 1× Retry gemäß Spec)
- **Fix 3 – errorWorkflow auf sich selbst zeigen, Endlosschleife?**: n8n erkennt zirkuläre Error-Workflows und bricht nach einer Ebene ab — kein echtes Risiko
- **Fix 4 – Zwei Container-Instanzen mit gleicher clientId**: MQTT-Broker trennt die ältere Verbindung; da wir nur eine Instanz pro Container betreiben, kein Problem
- **Fix 4 – Nachrichten im Broker für offline Container**: QoS 1 + `clean: false` → Broker hält Nachrichten bis Container wieder verbunden ist (max. MQTT-Broker-Retention); lange Downtime kann zu Backlog führen — akzeptables Verhalten
- **Fix 5 – NAS-Datei ohne Leseberechtigung**: `shutil.copy` schlägt ebenfalls fehl; kein Unterschied in diesem Fall

## Technical Requirements

- **Betroffene n8n Workflows**: `alice-dms-scanner`, `alice-dms-processor`, `alice-dms-lifecycle`
- **Betroffene Container**: `dms-extractor-pdf`, `dms-extractor-ocr`, `dms-extractor-txt`, `dms-extractor-office`
- **n8n Workflow-Dateien**: `workflows/core/alice-dms-scanner.json`, `workflows/core/alice-dms-processor.json`
- **Container-Dateien**: `docker/compose/automations/dms-extractor-[pdf|ocr|txt|office]/main.[js|py]`
- **Keine DB-Migrationen** erforderlich
- **Keine nginx-Änderungen** erforderlich
- **Kein Frontend-Eingriff** erforderlich
- **Deploy-Reihenfolge**:
  1. n8n Workflows updaten (Scanner, Processor)
  2. Container neu bauen und starten (4× `make rebuild`)
  3. Post-Deploy: `alice-dms-lifecycle` errorWorkflow-Setting in n8n UI konfigurieren

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
