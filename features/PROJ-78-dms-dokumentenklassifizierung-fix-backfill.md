# PROJ-78: DMS-Dokumentenklassifizierung — Fix + Backfill Bestand

## Status: Architected
**Created:** 2026-08-18
**Last Updated:** 2026-08-18

## Dependencies
- None (voraussetzungsfrei)
- **Wird benötigt von:** PROJ-80 (DMS-Vollständigkeits-Dashboard) — konsumiert das neue `classification_uncertain`-Flag zur Anzeige unsicherer Fälle

## Kontext

Die nächtliche `alice-dms-processor`-Pipeline klassifiziert neue Dokumente per LLM (`OLLAMA_MODEL_DMS`, produktiv aktuell `qwen3.5:27b-q4_K_M`, temperature 0) in genau einen von sechs Typen: `Invoice`, `BankStatement`, `Document`, `Email`, `SecuritySettlement`, `Contract`. Bei Parse-Fehlern gibt es einen Retry mit identischem Prompt; bei inhaltlich falscher Klassifizierung (z. B. eine Rechnung wird als generisches `Document` erkannt) gibt es aktuell keine Korrekturmöglichkeit — das Ergebnis wird unverändert übernommen. Dadurch landen im laufenden Betrieb wiederkehrend Dokumente in der falschen Weaviate-Collection, was die Vertrauenswürdigkeit der DMS-Wissensbasis untergräbt (siehe PRD Phase 3, Erfolgsmetrik: 0 falsch klassifizierte Rechnungen im `Document`-Schema).

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

- Kein neues LLM-Modell — weiterhin `OLLAMA_MODEL_DMS` (produktiv aktuell `qwen3.5:27b-q4_K_M`) für beide Klassifizierungsversuche.
- Backfill ist reine Weaviate-Operation; NAS-Originaldateien werden nicht verschoben oder verändert.
- Backfill-Zeitfenster darf sich nicht mit dem nächtlichen `alice-dms-processor`-Lauf überschneiden (Ressourcen-Konflikt auf der TITAN X / Ollama).

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Betroffene Workflows

- **`alice-dms-processor`** (bestehend) — wird für den Fix erweitert (Klassifizierungs-Abschnitt).
- **`alice-dms-classification-backfill`** (neu) — analog zu `alice-dms-thumbnailer-backfill` aufgebaut (Webhook, Dry-Run/Confirm-Schalter, Batch- und Zeitlimit-Pattern).

Beides sind reine n8n-Automatisierungen ohne UI-Anteil — kein Frontend-Task nötig.

### E) Workflow-Architektur

#### Teil 1 — Fix in `alice-dms-processor`

- **Trigger:** unverändert (nächtlicher Zeitplan, 02:00 Uhr).
- **Ablauf (nur der Klassifizierungs-Abschnitt ändert sich):**
  1. „Auto-Klassifizieren?"-Weiche bleibt wie heute — Ordner mit fest hinterlegtem Typ überspringen die LLM-Klassifizierung weiterhin komplett.
  2. **1. Versuch** (Ollama, temperature 0): Prompt wird um unterscheidende Merkmale/Keywords je Dokumenttyp ergänzt und fragt zusätzlich eine Konfidenz (0–1) im selben JSON-Ergebnis ab.
  3. Der bestehende Parse-Fehler-Retry (gleicher Prompt, bei ungültigem JSON) bleibt als Sicherheitsnetz unverändert erhalten.
  4. **Neue Weiche:** Liegt die Konfidenz unter dem Schwellwert → **2. Versuch** (gleicher erweiterter Prompt, temperature 0.3).
  5. **Ergebnis-Auswahl:** Es gewinnt der Versuch mit der höheren Konfidenz; bei Gleichstand der 2. (informierte) Versuch.
  6. Bleibt die finale Konfidenz unter dem Schwellwert, wird trotzdem die beste Schätzung übernommen — zusätzlich wird das Dokument als „unsicher" markiert. Die Pipeline blockiert dadurch nie.
  7. Ab hier läuft die Pipeline unverändert weiter (Extraktion, Weaviate-Insert), schreibt aber zusätzlich die Konfidenz und das Unsicherheits-Flag ins Zielobjekt.
- **Datenmodell-Änderung:** Jede der sechs klassifizierbaren Collections (Document, Invoice, Contract, Email, BankStatement, SecuritySettlement) erhält zwei neue, optionale Felder:
  - „Klassifizierungs-Konfidenz" (Zahl 0–1)
  - „Klassifizierung unsicher" (Ja/Nein-Flag) — genau das Flag, das PROJ-80 später für das Vollständigkeits-Dashboard konsumiert.
  Bestehende Dokumente sind davon nicht betroffen (Felder bleiben dort leer/false), bis sie neu klassifiziert werden.
- **Betriebs-Statistiken:** Die bestehenden Lauf-Statistiken (in Redis, sichtbar z. B. im Log) werden um Zähler für „Konfidenz zu niedrig, 2. Versuch nötig" und „nach 2. Versuch weiterhin unsicher" ergänzt — analog zu den bereits vorhandenen Retry-Zählern.

#### Teil 2 — Neuer Backfill-Workflow `alice-dms-classification-backfill`

- **Trigger:** manueller Webhook-Aufruf (POST), von Andreas ausgelöst — kein automatischer Zeitplan.
- **Modus-Schalter:** ohne `confirm`-Parameter → Dry-Run (nur Bericht, keine Änderung); mit `confirm=true` → verbindliche Korrektur.
- **Ablauf:**
  1. Alle sechs klassifizierbaren Collections werden nacheinander in Batches durchlaufen (gleiches Batch-/Zeitlimit-Pattern wie im nächtlichen Processor), sodass ein Lauf bei Bedarf über mehrere Nächte fortgesetzt werden kann, ohne einen einzelnen Request zu blockieren.
  2. Jedes bestehende Dokument wird mit derselben Zwei-Versuche-Klassifizierungslogik wie im Fix (Teil 1) anhand seines bereits gespeicherten Volltexts neu bewertet.
  3. Ergebnis wird mit dem aktuellen Typ verglichen.
  4. **Dry-Run:** Abweichungen werden gesammelt und als JSON-Bericht zurückgegeben (Dateiname, aktuelle Collection, vorgeschlagene Collection, Konfidenz) — keine Schreibaktion.
  5. **Confirm-Lauf:** Für jede Abweichung wird das Dokument mit dem Extraktions-Prompt des Zieltyps neu aufbereitet, in die Zielcollection eingefügt, das alte Objekt gelöscht und die Thumbnail-Neuerzeugung angestoßen (bestehender Thumbnailer-Mechanismus wird wiederverwendet, nicht neu gebaut).
     - Sonderfall BankStatement: Beim Wechsel in oder aus dieser Collection werden zusätzlich die zugehörigen Transaktions-Einträge neu erzeugt bzw. verwaiste alte Einträge gelöscht.
  6. Fehler bei einzelnen Dokumenten (z. B. Neuextraktion schlägt fehl) werden übersprungen, geloggt und in den Lauf-Statistiken gezählt — der Gesamtlauf läuft weiter.
  7. **Sperre gegen Überschneidung:** Der Backfill nutzt denselben Sperrmechanismus wie der nächtliche Processor, damit beide nicht gleichzeitig um die Ollama-Ressource (TITAN X) konkurrieren.
  8. Antwort auf den Webhook-Aufruf: Dry-Run liefert die Abweichungsliste, Confirm-Lauf liefert eine Zusammenfassung (migriert / übersprungen / fehlgeschlagen).
- **Konvergenz:** Da der Backfill den Typ jedes Mal frisch aus dem gespeicherten Volltext ableitet und nur echte Abweichungen migriert, liefert ein erneuter `confirm=true`-Aufruf nach einem abgeschlossenen Lauf automatisch keine weiteren Abweichungen mehr — ein zusätzlicher Duplikat-Schutz ist nicht nötig, da die bestehende Dedup-Logik (Löschen des alten Objekts vor Insert) bereits greift.

### Tech-Entscheidungen (Begründung)

- **Konfidenz-Selbstauskunft statt zweitem Prüfmodell:** Das LLM gibt seine Konfidenz im selben Aufruf mit aus — kein zusätzlicher Modellaufruf, kein zusätzliches Modell nötig, minimaler Mehraufwand gegenüber heute.
- **Maximal zwei Versuche statt Endlos-Retry:** Hält die nächtliche Laufzeit planbar und verhindert, dass echte Grenzfälle (Dokument mit Vertrags- und Rechnungscharakter) die Pipeline aufhalten — passt zum in der Spec beschriebenen Edge Case „genuin mehrdeutige Dokumente".
- **Backfill als separater, manuell ausgelöster Workflow statt Teil des nächtlichen Laufs:** Hält den nächtlichen Lauf schnell und vorhersehbar (Spec-Vorgabe: kein Ressourcenkonflikt mit dem nächtlichen Lauf) und gibt Andreas genau die Dry-Run-/Confirm-Sicherheitsstufe, die er sich in den User Stories wünscht.
- **Gemeinsame Klassifizierungslogik für Fix und Backfill:** Beide Workflows sollen exakt dasselbe Klassifizierungsverhalten zeigen. Der Backend-Dev sollte die Prompt-/Auswertungslogik so bauen, dass sie an einer Stelle gepflegt wird (z. B. als wiederverwendbarer Baustein), statt sie zweimal unabhängig zu implementieren — sonst laufen Fix und Backfill mit der Zeit auseinander.
- **Neue Felder direkt in den Weaviate-Collections statt separater Postgres-Tabelle:** Das Unsicherheits-Flag hängt direkt am Dokument, das es beschreibt. PROJ-80 (Dashboard) kann es dadurch mit einer einzigen Abfrage je Collection auslesen, statt zwei Datenbanken zu verknüpfen.
- **Konfidenz-Schwellwert als Umgebungsvariable statt fest im Prompt-Code verdrahtet:** Der genaue Schwellwert (Annahme: Startwert 0.7) ist eine Abwägung zwischen „zu viele unnötige Zweitversuche" und „zu viele falsch-sichere Klassifizierungen". Als Konfigurationswert lässt er sich im Betrieb nachjustieren, ohne den Workflow neu zu deployen.

### Datenmodell (einfache Sprache)

```
Jedes klassifizierbare Dokument bekommt zusätzlich:
- Klassifizierungs-Konfidenz (Zahl zwischen 0 und 1)
- Unsicherheits-Flag (Ja/Nein)

Betrifft: Document, Invoice, Contract, Email, BankStatement, SecuritySettlement
Speicherort: Weaviate (gleiche Collection wie das Dokument selbst, keine neue Datenbank)
```

### Abhängigkeiten (zu installierende Pakete)

Keine neuen Pakete/Node-Typen nötig. Beide Workflows nutzen ausschließlich bereits vorhandene Bausteine (HTTP-Aufruf an Ollama, Weaviate-REST-API, Redis-/Winston-Logging-Pattern), die im Container bereits verfügbar sind.

### Bestätigte Annahme

- Konfidenz-Schwellwert: Startwert **0.7**, als Umgebungsvariable konfigurierbar (mit Andreas im Review bestätigt).

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
