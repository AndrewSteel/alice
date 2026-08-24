# PROJ-94: DMS Path-Worker Zeitlimit

## Status: Planned
**Created:** 2026-08-24
**Last Updated:** 2026-08-24

## Dependencies
- Betrifft: `alice-dms-path-worker` (Kern der DMS-Scan-Pipeline aus PROJ-16, Deployed) — kein neuer Baustein, reine Robustheits-Ergänzung eines bestehenden Workflows.
- Kein Zusammenhang mit PROJ-53 selbst, wurde aber während dessen Abschlussprüfung entdeckt.

## Kontext

`alice-dms-path-worker` scannt pro Aufruf einen überwachten NAS-Ordner (getriggert vom `alice-dms-scanner`-Dispatcher, stündlich zwischen 07:00 und 22:00 Uhr) und verteilt neue/geänderte Dateien per MQTT an die `dms-extractor-*`-Container zur Textextraktion. Anders als `alice-dms-processor` (nightly, 02:00 Uhr) hat der Path-Worker **kein** Zeitlimit — es gibt zwar einen Ordner-Lock mit Verlust-Erkennung (`IF: Lock Still Held`), aber keinen `Time Check`/`IF: Time Limit Reached`-Schutz.

In der Praxis wurden bereits Läufe von >10 Stunden beobachtet (z.B. bei sehr großen Ordnern oder vielen neuen Dateien). Das ist unabhängig vom Thema GPU-Kollision (der Path-Worker selbst nutzt kein LLM; von den Extraktoren nutzt nur `dms-extractor-image` Ollama/GPU, alle anderen sind CPU-only) ein Robustheitsproblem: Ein sehr langer Lauf blockiert den Ordner-Lock über den nächsten stündlichen Trigger-Zeitpunkt hinaus und kann sich zeitlich mit den nightly-Workflows (`alice-dms-processor`, `alice-mail-attachment-processor`, beide 02:00 Uhr) überschneiden, falls ein spät gestarteter Lauf (z.B. 22:00 Uhr) entsprechend lange braucht.

## User Stories

- Als Admin möchte ich, dass ein einzelner Path-Worker-Lauf nach einer angemessenen Zeit kontrolliert abbricht, damit er nicht unbegrenzt den Ordner-Lock blockiert oder mit anderen zeitkritischen Workflows kollidiert.
- Als Admin möchte ich, dass beim Abbruch keine Dateien verloren gehen — nur die Verarbeitung verschiebt sich auf den nächsten regulären Lauf.

## Acceptance Criteria

- [ ] Der Path-Worker prüft während der Datei-Verarbeitungsschleife (`Loop: Files`) periodisch, ob seit Lauf-Start (bestehender Redis-Key `alice:dms:scanner:stats:folder:<folder_id>:run_start`, gesetzt in `Code: Init Worker Run`) mehr als **2 Stunden** vergangen sind
- [ ] Wird das Zeitlimit erreicht, bricht der Lauf kontrolliert ab: keine weiteren Dateien werden in der aktuellen Ausführung gescannt/verarbeitet
- [ ] Beim Abbruch wird der Ordner-Lock (`alice:dms:scanner:lock:folder:<folder_id>`) sauber freigegeben (analog zum bestehenden Verhalten bei `IF: Lock Still Held` → Verlust)
- [ ] Beim Abbruch wird der bisherige Fortschritt geloggt (Anzahl gescannter/verarbeiteter Dateien bis zum Abbruch), analog zum bestehenden Statistik-Logging
- [ ] Noch nicht gescannte Dateien im Ordner werden beim nächsten regulären stündlichen Lauf erneut aufgegriffen — kein Datenverlust, keine Sonderbehandlung nötig (der Scanner erkennt neue/ungesehene Dateien beim nächsten Durchlauf ohnehin)
- [ ] Ein Lauf, der innerhalb des Zeitlimits fertig wird, verhält sich exakt wie bisher (keine Verhaltensänderung für den Normalfall)
- [ ] Das Zeitlimit gilt **pro Ordner-Lauf** (nicht global über alle vom Dispatcher parallel gestarteten Ordner-Läufe hinweg) — konsistent mit der bestehenden Pro-Ordner-Lock-Architektur

## Edge Cases

- **Lauf beendet sich regulär kurz vor Erreichen des Zeitlimits**: Kein Sonderfall, normales Ende wie bisher.
- **Zeitlimit wird mitten in der Verarbeitung einer einzelnen Datei erreicht** (z.B. während `Wait: 5s Stability` oder unmittelbar vor einem MQTT-Publish): Die aktuell begonnene Datei wird nicht abgebrochen, sondern der Check greift zwischen den Dateien der Batch-Schleife — die gerade angefangene Datei wird also noch fertig verarbeitet, erst die nächste Datei wird nicht mehr begonnen (konsistent mit dem "sauber abbrechen zwischen Einheiten"-Verhalten aus `alice-dms-processor`).
- **Sehr kleiner Ordner, der ohnehin nie 2 Stunden braucht**: Zeitlimit greift nie, kein Verhaltensunterschied zu heute.
- **Redis nicht erreichbar beim Zeitlimit-Check**: Fail-open (Lauf läuft weiter, wie bei einem fehlenden `run_start`-Wert) — ein Redis-Ausfall soll nicht zusätzlich einen laufenden Scan abbrechen; das bestehende Lock-Verlust-Verhalten (`IF: Lock Still Held`) bleibt die primäre Absicherung gegen hängende Läufe bei Redis-Problemen.
- **Zwei Ordner-Läufe unterschiedlicher Größe laufen parallel** (Dispatcher startet mehrere Path-Worker-Instanzen gleichzeitig für unterschiedliche Ordner): Jeder Lauf hat seinen eigenen `run_start`-Zeitstempel und Lock — Zeitlimit-Abbruch eines Laufs hat keine Auswirkung auf parallele Läufe anderer Ordner.

## Technical Requirements (optional)

- Kein neuer Redis-Key nötig — `alice:dms:scanner:stats:folder:<folder_id>:run_start` existiert bereits (`Code: Init Worker Run`).
- Muster orientiert sich an `alice-dms-processor`s `Code: Time Check`/`IF: Time Limit Reached`, angepasst an den Pro-Ordner-Kontext des Path-Workers (kein globaler `run:start_time`-Key wie beim Processor).

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
