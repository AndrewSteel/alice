# PROJ-78: DMS-Dokumentenklassifizierung — Fix + Backfill Bestand

## Status: Planned
**Created:** 2026-08-18
**Last Updated:** 2026-08-18

## Dependencies
- None (voraussetzungsfrei)
- **Wird benötigt von:** PROJ-80 (DMS-Vollständigkeits-Dashboard) — konsumiert das neue `classification_uncertain`-Flag zur Anzeige unsicherer Fälle

## Kontext

Die nächtliche `alice-dms-processor`-Pipeline klassifiziert neue Dokumente per LLM (`qwen3:14b`, temperature 0) in genau einen von sechs Typen: `Invoice`, `BankStatement`, `Document`, `Email`, `SecuritySettlement`, `Contract`. Bei Parse-Fehlern gibt es einen Retry mit identischem Prompt; bei inhaltlich falscher Klassifizierung (z. B. eine Rechnung wird als generisches `Document` erkannt) gibt es aktuell keine Korrekturmöglichkeit — das Ergebnis wird unverändert übernommen. Dadurch landen im laufenden Betrieb wiederkehrend Dokumente in der falschen Weaviate-Collection, was die Vertrauenswürdigkeit der DMS-Wissensbasis untergräbt (siehe PRD Phase 3, Erfolgsmetrik: 0 falsch klassifizierte Rechnungen im `Document`-Schema).

Das Feature hat zwei Teile:
1. **Fix**: Die Klassifizierungslogik für neu eingehende Dokumente wird robuster (Retry bei niedriger Konfidenz statt nur bei Parse-Fehlern).
2. **Backfill**: Der bestehende Dokumentenbestand (~500–2.000 Dokumente über alle Collections) wird einmalig mit der neuen Logik nachkorrigiert.

## User Stories

- Als Andreas (Admin) möchte ich, dass neu eingehende Dokumente zuverlässig in die richtige Collection einsortiert werden, damit ich mich beim Suchen und Nachfragen auf die DMS-Wissensbasis verlassen kann.
- Als Andreas möchte ich, dass die Klassifizierung bei Unsicherheit einen zweiten, anders gearteten Versuch unternimmt, damit nicht jede Unsicherheit automatisch im generischen `Document`-Schema landet.
- Als Andreas möchte ich vor einer Massenänderung am Bestand einen Vorschau-Report sehen (welches Dokument wechselt von welcher in welche Collection), damit ich die Korrektur prüfen kann, bevor sie verbindlich wird.
- Als Andreas möchte ich den geprüften Backfill mit einem zweiten Aufruf bestätigen können, damit mein gesamter bestehender DMS-Bestand korrigiert wird, ohne die Originaldateien auf dem NAS anzufassen.
- Als Andreas möchte ich, dass Dokumente, die auch nach zwei Versuchen unsicher bleiben, sichtbar markiert werden (statt sie stillschweigend falsch einzusortieren), damit ich sie später über das Vollständigkeits-Dashboard (PROJ-80) auffinden kann.

## Acceptance Criteria

### Fix (laufender Betrieb, `alice-dms-processor`)
- [ ] Der Klassifizierungs-Prompt enthält je Dokumenttyp unterscheidende Merkmale/Keywords (z. B. „Invoice: enthält Rechnungsnummer, Bruttobetrag, Fälligkeitsdatum") statt nur der Typnamen.
- [ ] Der erste Klassifizierungsversuch bleibt deterministisch (temperature 0), wie heute.
- [ ] Das System ermittelt eine Konfidenz für das Klassifizierungsergebnis (z. B. Selbstauskunft des LLM im JSON-Response).
- [ ] Liegt die Konfidenz unter einem definierten Schwellwert, läuft automatisch ein zweiter Versuch mit erhöhter Temperature (z. B. 0.3) und dem erweiterten Keyword-Prompt.
- [ ] Von beiden Versuchen wird das Ergebnis mit der höheren Konfidenz übernommen; bei Gleichstand gewinnt der zweite (informierte) Versuch.
- [ ] Bleibt die finale Konfidenz unter dem Schwellwert, wird das Dokument trotzdem mit der besten Schätzung gespeichert, zusätzlich aber mit einem Flag markiert, das eine Unsicherheit kennzeichnet (konsumierbar durch PROJ-80).
- [ ] Der bestehende Parse-Fehler-Retry-Mechanismus bleibt erhalten (unabhängig von der neuen Konfidenz-Logik).
- [ ] Ordner mit fest hinterlegtem `suggested_type` (kein `auto`) sind von der Änderung nicht betroffen — sie überspringen die LLM-Klassifizierung weiterhin komplett.

### Backfill (einmaliger Bestands-Lauf)
- [ ] Ein manuell auslösbarer Webhook-Endpoint (analog `alice-dms-thumbnailer-backfill`) klassifiziert im Dry-Run-Modus (kein Confirm-Flag) jedes existierende Weaviate-Objekt über alle sechs klassifizierbaren Collections neu, ohne Daten zu verändern.
- [ ] Die Dry-Run-Response ist ein JSON-Report mit jedem Dokument, dessen neu ermittelter Typ vom aktuellen abweicht (Dateiname, aktuelle Collection, vorgeschlagene Collection, Konfidenz).
- [ ] Derselbe Endpoint mit einem Confirm-Parameter (z. B. `confirm=true`) führt für alle abweichenden Dokumente die Korrektur aus: Neuextraktion mit dem Extraktions-Prompt des Zieltyps, Insert in die Zielcollection, Löschen des alten Objekts, Anstoß der Thumbnail-Neuerzeugung.
- [ ] Der Backfill läuft gebatcht/zeitlich begrenzt (wiederverwendet das Time-Limit-Pattern von `alice-dms-processor`), sodass er bei ~500–2.000 Dokumenten über mehrere Läufe/Nächte abgeschlossen werden kann, statt in einem einzigen langen Request zu blockieren.
- [ ] Ein erneuter Aufruf mit `confirm=true` nach einem bereits abgeschlossenen Backfill liefert keine weiteren Abweichungen mehr (Konvergenz, keine Duplikate).
- [ ] Dokumente, bei denen Neuextraktion fehlschlägt, werden übersprungen und geloggt (Redis-Stats analog bestehendem Fehler-Handling), der Gesamtlauf bricht dadurch nicht ab.
- [ ] Nach einem bestätigten Backfill-Lauf befinden sich 0 tatsächliche Rechnungen (oder andere Fremdtypen) mehr in der `Document`-Collection (Stichprobenprüfung gegen PRD-Erfolgsmetrik).

## Edge Cases

- **Duplikat nach Collection-Wechsel**: Existiert im Zielschema bereits ein Objekt mit demselben `fileHash` (z. B. durch einen früheren Teil-Lauf) → bestehende Dedup-Logik (Löschen des alten, Insert des neuen) greift, kein Duplikat.
- **BankStatement-Rekategorisierung**: Wechselt ein Dokument in oder aus `BankStatement`, müssen die zugehörigen `BankTransaction`-Chunks neu erzeugt bzw. verwaist alte Chunks gelöscht werden — nicht nur das Elternobjekt.
- **Alte UUID-Referenzen**: Frühere Chat-Antworten/Vision-Results, die auf die alte Weaviate-UUID verweisen, zeigen nach dem Wechsel ins Leere. Wird als akzeptables, seltenes Backfill-Nebenprodukt hingenommen — kein Rewrite der Chat-Historie.
- **Ollama nicht erreichbar während Backfill**: Lauf bricht sauber ab (kein Teil-Update einzelner Dokumente), ist beim nächsten Trigger fortsetzbar und überspringt bereits korrigierte Dokumente.
- **Genuin mehrdeutige Dokumente** (z. B. ein Dokument, das sowohl Vertrags- als auch Rechnungscharakter hat): wird mit Best-Guess-Typ + Unsicherheits-Flag gespeichert, keine Blockade der Pipeline, spätere manuelle Prüfung über PROJ-80.
- **Berechtigungswechsel durch Collection-Wechsel**: `alice.permissions_dms` filtert pro `doc_type` — ein Dokument, das die Collection wechselt, unterliegt danach anderen Zugriffsregeln. Da Andreas aktuell einziger aktiver Nutzer mit Admin-Rechten ist, ist das Risiko für MVP vernachlässigbar, sollte bei künftigen Nutzern aber beachtet werden.
- **Leerer Bestand / keine Abweichungen im Dry-Run**: Report liefert eine leere Liste, Confirm-Aufruf ist dann ein No-Op.

## Technical Requirements (optional)

- Kein neues LLM-Modell — weiterhin `OLLAMA_MODEL_DMS` (Standard `qwen3:14b`) für beide Klassifizierungsversuche.
- Backfill ist reine Weaviate-Operation; NAS-Originaldateien werden nicht verschoben oder verändert.
- Backfill-Zeitfenster darf sich nicht mit dem nächtlichen `alice-dms-processor`-Lauf überschneiden (Ressourcen-Konflikt auf der TITAN X / Ollama).

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
