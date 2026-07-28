# PROJ-72: DMS Scanner/Processor Backlog-Locking

## Status: Planned
**Created:** 2026-07-28
**Last Updated:** 2026-07-28

## Dependencies
- Requires: PROJ-16 (DMS Scanner) — Sperrmechanismus erweitert `alice-dms-scanner`
- Requires: PROJ-19 (DMS Processor) — Sperrmechanismus erweitert `alice-dms-processor`
- Requires: PROJ-15 (DMS Ordnerverwaltung) — `alice.dms_watched_folders` ist die Quelle der zu sperrenden Pfade
- Bezug: PROJ-56 (DMS Bildanalyse) — Ursprung des gemeldeten Problems; **BUG-3** (systematische Duplizierung in `alice:dms:geocode_pending`, gefunden in der PROJ-56-QA vom 2026-07-28) ist ein direkt beobachtetes Symptom desselben Root-Cause und wird durch diesen Fix mit behoben

## Overview

Bei großen Erstaufnahme-Backlogs (z.B. 70.000+ Bilder in einer neu freigegebenen NAS-Freigabe) dauert die Abarbeitung durch `alice-dms-scanner` mehrere Tage — allein der 5-Sekunden-Stabilitätscheck pro Datei summiert sich entsprechend. Der Scanner läuft aber stündlich (07–22 Uhr) weiter und startet neue Ausführungen, während eine vorherige noch aktiv ist. Weil `Code: Scan All Folders` außerdem alle aktivierten Pfade aus `alice.dms_watched_folders` zu einer einzigen kombinierten Liste zusammenfasst, führt das zu zwei Problemen:

1. **Doppelverarbeitung:** Dieselbe Datei kann von zwei überlappenden Ausführungen erkannt und doppelt in die Verarbeitungs-Pipeline eingestellt werden (Race Condition, bevor der Datei-Hash in `alice:dms:queued_files` landet). Live-Produktionsdaten aus der PROJ-56-QA (2026-07-28) bestätigen dies konkret: In `alice:dms:geocode_pending` erschien während des aktiven Backlogs **jeder** `file_hash` exakt zweimal.
2. **Blockade anderer Pfade:** Ein sehr großer Backlog in einem Pfad verzögert faktisch auch neue Dateien in allen anderen, unabhängigen beobachteten Pfaden — diese kommen in der kombinierten Liste erst "an die Reihe", wenn der große Pfad durchgearbeitet ist.

Die Lösung: pro beobachtetem Pfad (`alice.dms_watched_folders`-Eintrag) wird ein Sperrstatus geführt. Ein Scanner-Lauf verarbeitet Pfade nacheinander, überspringt dabei aber Pfade, die bereits von einer anderen laufenden Ausführung gesperrt sind, und fährt stattdessen mit dem nächsten freien Pfad fort. Das löst Doppelverarbeitung (kein Pfad wird von zwei Läufen gleichzeitig bearbeitet) und Blockade (unabhängige Pfade werden nicht durch einen großen Backlog in einem anderen Pfad ausgehungert) im selben Konzept. Der Processor bekommt eine einfachere Variante desselben Prinzips — dort genügt ein einzelner Lauf-Lock, da er keine unabhängigen "Pfade" kennt, sondern eine einzelne nächtliche Batch-Verarbeitung ist.

Damit eine abgestürzte Ausführung eine Sperre nicht dauerhaft hält, erneuert eine aktive Ausführung ihre Sperre periodisch (Heartbeat); bleibt der Heartbeat aus, verfällt die Sperre automatisch.

Bestehende Datei-Level-Mechanismen (SHA-256-Dedup via `alice:dms:queued_files`/`processed_files`, 5s-Stabilitätscheck) bleiben unverändert bestehen — der Pfad-Lock ist eine zusätzliche Schicht, keine Ablösung.

## User Stories

- Als System möchte ich sicherstellen, dass zwei überlappende Scanner-Ausführungen niemals denselben beobachteten Pfad gleichzeitig verarbeiten, damit Dateien nicht mehrfach in die Verarbeitungs-Pipeline eingestellt werden (siehe PROJ-56 BUG-3: doppelte Geocoding-Anfragen genau durch dieses Problem).
- Als System möchte ich, dass ein großer Backlog in einem beobachteten Ordner die Verarbeitung neuer Dateien in anderen, unabhängigen Ordnern nicht blockiert, damit neue Dokumente/Bilder zeitnah erscheinen — unabhängig davon, wie voll andere Ordner gerade sind.
- Als System möchte ich sicherstellen, dass nie zwei nächtliche Processor-Läufe gleichzeitig aktiv sind, damit dieselbe Datei nicht doppelt klassifiziert/gespeichert wird, selbst wenn ein Lauf durch einen großen Image-/Geocode-Backlog länger als 24h dauert.
- Als Admin möchte ich, dass ein abgestürzter Scanner- oder Processor-Lauf einen Pfad bzw. den gesamten nächtlichen Lauf nicht dauerhaft blockiert, damit ich nach einem Absturz nicht manuell eingreifen muss.
- Als System möchte ich, dass nachweisbar ist, dass durch diesen Fix keine doppelten Einträge mehr in nachgelagerten Warteschlangen (z.B. `alice:dms:geocode_pending`) entstehen, damit BUG-3 aus PROJ-56 als behoben gilt.

## Acceptance Criteria

### Scanner: Pfad-Locking & Fairness

- [ ] Jeder aktivierte Eintrag in `alice.dms_watched_folders` hat einen zugehörigen Sperrstatus ("wird gerade verarbeitet" / frei)
- [ ] Bevor ein Scanner-Lauf einen Pfad bearbeitet, sperrt er ihn **atomar** — es darf kein Zeitfenster geben, in dem zwei Läufe denselben Pfad gleichzeitig als frei ansehen und beide sperren
- [ ] Ein Scanner-Lauf geht beim Start alle aktivierten Pfade der Reihe nach durch, überspringt dabei bereits gesperrte Pfade und fährt mit dem nächsten freien Pfad fort
- [ ] Während der Verarbeitung eines Pfades erneuert der Lauf dessen Sperre periodisch (Heartbeat), solange er aktiv daran arbeitet
- [ ] Bleibt der Heartbeat aus (Absturz, Container-Neustart), verfällt die Sperre automatisch nach kurzer Zeit — kein manuelles Eingreifen nötig
- [ ] Nach Abschluss der Verarbeitung eines Pfades (auch bei Fehler/Abbruch) wird dessen Sperre freigegeben
- [ ] Ein Pfad mit sehr großem Backlog (z.B. 70k+ Dateien) verzögert nicht die Verarbeitung anderer, unabhängiger Pfade — diese werden im selben oder einem der folgenden stündlichen Läufe bearbeitet, unabhängig vom Fortschritt des großen Pfades
- [ ] Bestehende Datei-Level-Mechanismen (SHA-256-Dedup, 5s-Stabilitätscheck) funktionieren unverändert zusätzlich zum neuen Pfad-Lock

### Processor: Lauf-Locking

- [ ] Vor Start der nächtlichen Verarbeitung prüft `alice-dms-processor`, ob bereits ein Lauf aktiv ist (z.B. vom Vortag, der wegen eines großen Image-/Geocode-Backlogs noch läuft)
- [ ] Ist bereits ein Lauf aktiv, startet der neue nächtliche Trigger keinen zweiten parallelen Lauf, sondern beendet sich sauber ohne einen zu starten (kein Fehler)
- [ ] Der aktive Lauf erneuert seine Sperre periodisch (Heartbeat), solange er läuft
- [ ] Bleibt der Heartbeat aus (Absturz), verfällt die Sperre automatisch — der nächste nächtliche Trigger kann normal starten
- [ ] Nach regulärem Abschluss (auch bei Erreichen des bestehenden Zeitlimits der Plaintext-Phase) wird die Sperre freigegeben

### Verifikation (BUG-3 aus PROJ-56)

- [ ] Über mehrere aufeinanderfolgende Scanner-Läufe während eines aktiven Backlogs treten keine doppelten `file_hash`-Einträge mehr in nachgelagerten Warteschlangen auf (`alice:dms:geocode_pending`, MQTT `alice/dms/image`/`alice/dms/new`)
- [ ] Überprüfbar durch Beobachtung mehrerer aufeinanderfolgender n8n-Executions (analog zur Methode aus der PROJ-56-QA vom 2026-07-28): Stichprobe aus den Fetch-Nodes zeigt keine unmittelbar aufeinanderfolgenden identischen `file_hash`-Paare mehr

## Edge Cases

- Zwei Scanner-Läufe starten praktisch zeitgleich (z.B. Neustart + Schedule-Kollision): Nur einer sperrt einen gegebenen Pfad erfolgreich; der andere überspringt ihn und verarbeitet ggf. andere freie Pfade
- Scanner-Lauf stürzt mitten in der Verarbeitung eines Pfades ab: Sperre verfällt nach Ausbleiben des Heartbeats automatisch; der Pfad wird im nächsten Lauf erneut aufgenommen; bereits gequeuete Dateien dieses Pfades bleiben zusätzlich über die bestehende Datei-Level-Dedup geschützt
- Ein Pfad wird während laufender Sperre in `alice.dms_watched_folders` deaktiviert: laufende Verarbeitung wird nicht hart abgebrochen; Sperre wird nach Abschluss regulär freigegeben; künftige Läufe überspringen den deaktivierten Pfad wie bisher
- Alle Pfade sind aktuell gesperrt (mehrere große Backlogs gleichzeitig aktiv): Ein neu getriggerter Scanner-Lauf findet keinen freien Pfad und beendet sich sofort ohne Dateien zu verarbeiten (kein Fehler, entspricht funktional dem bestehenden "keine Ordner aktiv"-Fall)
- Processor-Lauf läuft über Mitternacht/mehrere Tage (großer Image-Backlog): Der Lauf-Lock verhindert, dass der 02:00-Trigger einer Folgenacht einen zweiten Lauf startet, solange der erste noch aktiv ist
- Processor-Lauf hängt fest (z.B. Ollama/Weaviate antwortet nicht mehr, ohne dass der Prozess selbst abstürzt): Wird durch das Locking allein nicht gelöst — außerhalb des Scopes von PROJ-72; bestehendes Fehler-/Timeout-Verhalten der einzelnen Phasen bleibt maßgeblich
- Manuelles Zurücksetzen einer hängenden Sperre durch den Admin (z.B. direkter DB-/Redis-Zugriff) muss möglich sein, auch ohne UI dafür — reiner Notfall-Fallback neben dem automatischen Heartbeat-Verfall

## Technical Requirements (optional)

- Speicherort des Sperrstatus (zusätzliche Spalte an `alice.dms_watched_folders` vs. separater Redis-Key pro Pfad) ist eine Entscheidung für `/architecture` — beide Optionen wurden diskutiert
- Atomarität von "prüfen + sperren" ist eine harte Anforderung unabhängig vom gewählten Speicherort
- Heartbeat-Intervall und Verfallszeit sind Architektur-Entscheidungen; Richtwert: Intervall deutlich kürzer als Verfallszeit
- Keine Codeänderung an `dms-extractor-image` oder am Geocode-Sub-Flow (PROJ-56) nötig — die BUG-3-Symptomatik verschwindet als Nebeneffekt dieses Fixes

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
