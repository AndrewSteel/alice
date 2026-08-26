# PROJ-78: DMS-Dokumentenklassifizierung — Fix + Backfill Bestand

## Status: Deployed
**Created:** 2026-08-18
**Last Updated:** 2026-08-26 (axios/Node-24-Crash in `alice-dms-classification-backfill` gefixt und deployed, siehe "Fix-Forward" unten)

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
- Backfill-Zeitfenster darf sich nicht mit dem nächtlichen `alice-dms-processor`-Lauf überschneiden (Ressourcen-Konflikt auf der RTX 3090 (Ollama)).

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
  7. **Sperre gegen Überschneidung:** Der Backfill nutzt denselben Sperrmechanismus wie der nächtliche Processor, damit beide nicht gleichzeitig um die Ollama-Ressource (RTX 3090) konkurrieren.
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

## Implementation Notes (Backend)

**Neue/geänderte Workflow-Dateien:**
- `workflows/alice-dms-classify-document.json` (neu) — gemeinsamer n8n-Sub-Workflow (Execute-Workflow-Trigger) mit der Zwei-Versuche-Klassifizierungslogik (Prompt mit Unterscheidungsmerkmalen je Typ, Konfidenz-Selbstauskunft, 2. Versuch bei Temperature 0.3 unterhalb des Schwellwerts, bestehender Parse-Fehler-Retry bleibt als separates Sicherheitsnetz erhalten). Wird sowohl vom Fix als auch vom Backfill aufgerufen (`Execute Workflow`-Node), damit beide nicht auseinanderlaufen — wie im Tech Design gefordert. Live in n8n angelegt (inaktiv) unter der ID `JHyjjKyhcSxPgAv4`, damit die aufrufenden Workflows per ID referenzieren können (analog zum bestehenden Muster `alice-dms-scanner` → `alice-dms-path-worker`).
- `workflows/alice-dms-processor.json` (geändert) — Klassifizierungs-Abschnitt ruft jetzt den neuen Sub-Workflow auf (`Execute: Classify Document` ersetzt den bisherigen direkten Ollama-Call; `Code: Map Classify Result` ersetzt `Code: Parse Classify Result`). Neue Redis-Lauf-Statistiken `confidence_low_second_attempt` und `still_uncertain_after_second` ergänzt (Init + beide Final-Log-Varianten). `Code: Build Weaviate Payload` schreibt zusätzlich `classificationConfidence` und `classificationUncertain` in alle sechs klassifizierbaren Collections.
- `workflows/alice-dms-classification-backfill.json` (neu) — manueller Webhook (`POST /webhook/alice-dms-classification-backfill`), Dry-Run (Standard) vs. `confirm=true`. Teilt sich den Sperrmechanismus (identischer Redis-Lock-Key `alice:dms:processor:lock:run`) mit dem nächtlichen Processor, damit beide nie gleichzeitig um die Ollama-Ressource (RTX 3090, Hostname ollama-3090) konkurrieren. Batch-/Zeitlimit-Pattern (7200s, Split-In-Batches + Lock-Renewal) 1:1 vom Processor übernommen. Sonderfall BankStatement (Wechsel in/aus der Collection) regeneriert bzw. löscht verwaiste `BankTransaction`-Kindobjekte. Nutzt den bestehenden Thumbnailer-Endpoint (`alice-dms-thumbnailer:8004/generate`) für die Thumbnail-Neuerzeugung, statt diese neu zu bauen.
- `schemas/invoice.json`, `bank-statement.json`, `security-settlement.json`, `document.json`, `email.json`, `contract.json` — je zwei neue Properties `classificationConfidence` (number) und `classificationUncertain` (boolean) ergänzt.

**Neue Umgebungsvariable:** `DMS_CLASSIFICATION_CONFIDENCE_THRESHOLD` (Default `0.7`, siehe bestätigte Annahme oben) — wird vom neuen Sub-Workflow `alice-dms-classify-document` gelesen.

**Abweichungen vom Tech Design (bewusste Vereinfachungen):**
- Die Extraktions-Prompts je Zieltyp (Invoice/BankStatement/…) sind im Backfill-Workflow dupliziert statt über einen weiteren Sub-Workflow geteilt — es handelt sich um statische Prompt-Vorlagen mit geringem Drift-Risiko, anders als die eigentliche Klassifizierungslogik (die *ist* geteilt). Ebenso ist die BankTransaction-Chunk-Extraktion (Phase B) im Backfill als eigenständige, vereinfachte Kopie der Processor-Logik implementiert (ohne die Spezialfälle für „gleicher Parent, erneuter Lauf", da beim Backfill jeder Collection-Wechsel zwangsläufig ein neues Objekt erzeugt).
- Weaviate-Schema-Änderungen sind nur als Datei im Repo vorbereitet (`schemas/*.json`). Da `scripts/init-weaviate-schema.sh` bestehende Collections überspringt, greifen die zwei neuen Properties bei bereits existierenden Collections erst, wenn entweder Weaviate Auto-Schema aktiv ist (Property wird beim ersten Insert automatisch angelegt) oder vor dem Deploy ein `POST /v1/schema/{Class}/properties`-Aufruf je Collection erfolgt. Für `/deploy` vormerken.
- Die live in n8n angelegte Sub-Workflow-Instanz (`alice-dms-classify-document`, ID `JHyjjKyhcSxPgAv4`) ist inaktiv angelegt (nur damit `alice-dms-processor` und `alice-dms-classification-backfill` sie per ID referenzieren können) — der eigentliche Deploy/Aktivierung aller drei Workflows erfolgt weiterhin manuell durch Andreas.

## QA Test Results

**Tested:** 2026-08-18
**Tester:** QA Engineer (AI)
**Methode:** Statisches Code-Review + Logik-Trace gegen alle Acceptance Criteria und Edge Cases. Kein Live-Ausführungstest möglich, da `alice-dms-processor` (Produktion) und `alice-dms-classification-backfill` (neu) laut Projektkonvention nicht eigenständig deployt werden dürfen ("Deploy n8n-workflow …" bleibt manueller Schritt von Andreas) und ein Confirm-Lauf gegen die echte Produktions-Weaviate-Instanz irreversible Seiteneffekte hätte. `npm test` / `npm run test:e2e` entfallen — dieses Feature hat keinen Frontend- oder API-Route-Anteil (reine n8n-Workflows + Weaviate-Schema).

### Acceptance Criteria Status

#### AC-1: Fix — laufender Betrieb (`alice-dms-processor`)
- [x] Prompt enthält unterscheidende Merkmale/Keywords je Dokumenttyp
- [x] 1. Versuch bleibt deterministisch (temperature 0)
- [x] Konfidenz wird im selben JSON-Response ermittelt
- [x] 2. Versuch bei Temperature 0.3 automatisch bei Konfidenz < Schwellwert
- [x] Höhere Konfidenz gewinnt; bei Gleichstand 2. Versuch
- [x] Beste Schätzung wird immer gespeichert + Unsicherheits-Flag bei weiterhin niedriger Konfidenz
- [x] Bestehender Parse-Fehler-Retry bleibt unverändert als separates Sicherheitsnetz erhalten
- [x] Ordner mit fest hinterlegtem `suggested_type` überspringen die LLM-Klassifizierung weiterhin komplett (Zweig unverändert)

#### AC-2: Backfill — einmaliger Bestands-Lauf
- [x] Dry-Run (kein `confirm`) klassifiziert alle sechs Collections neu, ohne zu schreiben
- [x] Dry-Run-Report enthält Dateiname, aktuelle/vorgeschlagene Collection, Konfidenz je Abweichung
- [x] `confirm=true` migriert: Neuextraktion, Insert Zielcollection, Löschen Altobjekt, Thumbnail-Trigger
- [x] Batch-/Zeitlimit-Pattern (7200s, Lock-Renewal) vom Processor übernommen
- [ ] BUG-1: Konvergenz/keine-Duplikate bei erneutem `confirm=true`-Aufruf nicht in jedem Fall garantiert (siehe unten)
- [x] Fehlgeschlagene Neuextraktionen werden übersprungen, geloggt, gezählt — Gesamtlauf läuft weiter
- [ ] Nicht unabhängig verifizierbar vor Deployment: „0 tatsächliche Rechnungen mehr in Document-Collection" ist eine Stichprobenprüfung gegen echte Produktionsdaten nach einem realen Confirm-Lauf — kann erst nach Deploy + echtem Lauf geprüft werden.

### Edge Cases Status

#### EC-1: Duplikat nach Collection-Wechsel
- [ ] BUG-1: Nicht vollständig abgedeckt — siehe Bugs

#### EC-2: BankStatement-Rekategorisierung
- [x] Cascade-Delete alter `BankTransaction`-Kinder beim Verlassen von BankStatement; Neuextraktion beim Eintritt — korrekt gegenseitig exklusiv (da `proposedType !== doc.class` garantiert)

#### EC-3: Alte UUID-Referenzen
- [x] Bewusst akzeptiert wie spezifiziert, kein Code nötig

#### EC-4: Ollama nicht erreichbar während Backfill
- [ ] BUG-2: Kein sauberer Sofort-Abbruch bei komplettem Ollama-Ausfall (siehe unten)

#### EC-5: Genuin mehrdeutige Dokumente
- [x] Best-Guess + Unsicherheits-Flag, keine Pipeline-Blockade

#### EC-6: Berechtigungswechsel durch Collection-Wechsel
- [x] Bewusst akzeptiert für MVP wie spezifiziert, kein Code nötig

#### EC-7: Leerer Bestand / keine Abweichungen im Dry-Run
- [x] Leere Liste im Dry-Run-Report; Confirm-Aufruf ist No-Op

### Security Audit Results

**n8n workflow features:**
- [x] Keine GraphQL-Injection: alle dynamischen `class`/`textField`-Werte sind statisch/allowlisted, Cursor-IDs stammen von Weaviate selbst; `parentStatementId`-Sanitizing für `BankTransaction`-Cascade-Delete identisch zum bestehenden Muster im Processor
- [x] `document_type` aus dem Klassifizierungs-Ergebnis ist durch `alice-dms-classify-document` bereits allowlist-validiert, bevor er als Weaviate-Klassenname verwendet wird; `Code: Compare & Handle` validiert zusätzlich selbst gegen `validTypes`
- [x] Keine Secrets in Logs (Redis-Passwort wird nirgends geloggt, nur interne Hostnamen)
- [~] Kein Auth-Mechanismus auf dem neuen Webhook (`authentication: none`) — entspricht exakt dem bestehenden Muster von `alice-dms-thumbnailer-backfill` und dem VPN-only-Zugriffsmodell des Projekts; kein neues, durch PROJ-78 eingeführtes Risiko, aber erwähnenswert falls sich das Zugriffsmodell künftig ändert
- [x] Der neue Sub-Workflow `alice-dms-classify-document` nutzt einen `executeWorkflowTrigger` (kein Webhook) — keine neue externe Angriffsfläche

### Bugs Found

#### BUG-1: Backfill-Confirm garantiert Konvergenz/Duplikatfreiheit nicht bei fehlgeschlagenem Delete
- **Severity:** High
- **Datei:** `workflows/alice-dms-classification-backfill.json`, Node `Code: Compare & Handle`
- **Root Cause:** Die Migration fügt zuerst das neue Objekt in die Zielcollection ein und löscht danach das alte Objekt in der Quellcollection — der Löschaufruf ist per `.catch()` fehlertolerant und bricht die Migration bei Fehlschlag NICHT ab (`_outcome: 'migrated'` wird trotzdem gesetzt). Zusätzlich prüft der Code vor dem Insert nicht, ob in der Zielcollection bereits ein Objekt mit demselben `fileHash` existiert (im Gegensatz zum bestehenden Muster im Processor: `Code: Build Weaviate Query` → `HTTP: Weaviate Search` → `Code: Check Existing Entry` → bedingtes Delete-vor-Insert).
- **Steps to Reproduce (Failure Scenario):**
  1. `confirm=true`-Lauf migriert Dokument X von `Document` nach `Invoice`.
  2. Insert des neuen `Invoice`-Objekts gelingt; der anschließende `DELETE` des alten `Document`-Objekts schlägt fehl (z. B. kurzer Netzwerk-Hänger zu Weaviate).
  3. Der Fehler wird nur geloggt, `migrated`-Zähler wird trotzdem erhöht.
  4. Beim nächsten Dry-Run erscheint das alte `Document`-Objekt erneut als Abweichung (es existiert ja weiterhin und wird erneut als `Invoice` klassifiziert).
  5. Ein erneuter `confirm=true`-Aufruf migriert es ein zweites Mal → zwei `Invoice`-Objekte mit identischem `fileHash` in der Zielcollection.
  - **Erwartet:** Laut AC „Ein erneuter Aufruf mit `confirm=true` … liefert keine weiteren Abweichungen mehr (Konvergenz, keine Duplikate)" und laut Edge-Case-Vorgabe „bestehende Dedup-Logik (Löschen des alten, Insert des neuen) greift, kein Duplikat".
  - **Tatsächlich:** Unter dem beschriebenen (realistischen, wenn auch seltenen) Fehlerfall entsteht ein Duplikat, und der Alt-Datensatz bleibt dauerhaft in der falschen Collection liegen.
- **Priority:** Fix before deployment

#### BUG-2: Kein sauberer Sofort-Abbruch bei komplettem Ollama-Ausfall während des Backfills
- **Severity:** Medium
- **Datei:** `workflows/alice-dms-classification-backfill.json` (Code: Time Check / Code: Compare & Handle) und `workflows/alice-dms-classify-document.json`
- **Root Cause:** Es gibt keinen Health-Check/Circuit-Breaker für Ollama. Bei komplettem Ausfall durchläuft jedes einzelne Dokument weiterhin bis zu vier Timeout-Wartezeiten (2× 120s im Klassifizierungs-Sub-Workflow, bis zu 300s in der Neuextraktion) statt den Lauf sofort zu erkennen und sauber abzubrechen.
- **Steps to Reproduce:** Ollama-Container stoppen, Backfill mit `confirm=true` und >10 Dokumenten auslösen.
  - **Erwartet:** Laut Edge Case „Lauf bricht sauber ab (kein Teil-Update einzelner Dokumente), ist beim nächsten Trigger fortsetzbar".
  - **Tatsächlich:** Der Lauf arbeitet sich langsam (mehrere Minuten pro Dokument) durch die Warteschlange, bis irgendwann das 7200s-Zeitlimit greift — kein sauberer Sofort-Abbruch, unnötig lange Laufzeit und viele „failed"-Einträge statt eines einzigen klaren Abbruchgrunds.
- **Priority:** Fix before deployment (empfohlen, da einfache Ergänzung: erste Ollama-Anfrage im Time-Check mit kurzem Timeout prüfen und bei Fehlschlag sofort mit `reason: 'ollama_unavailable'` abbrechen)

### Summary
- **Acceptance Criteria:** 15/17 passed (2 partially — see BUG-1 EC-1/AC-2 convergence criterion; 1 not independently verifiable pre-deployment)
- **Bugs Found:** 2 total (0 critical, 1 high, 1 medium, 0 low)
- **Security:** Pass (no new vulnerabilities introduced; webhook auth model matches existing project convention)
- **Production Ready:** NO (siehe Re-Test unten)
- **Recommendation:** Fix BUG-1 (target-collection dedup check before insert, or treat delete-failure as `failed` instead of `migrated`) before deployment. BUG-2 recommended but not strictly blocking if Ollama uptime is otherwise reliable in this single-user deployment.

---

### Re-Test (2026-08-18, nach Backend-Fixes)

**BUG-1 (High) — behoben.** `Code: Compare & Handle` sucht jetzt vor jedem Insert per `deleteExistingByHash(proposedType, doc.fileHash)` in der Zielcollection nach einem bestehenden Objekt mit demselben `fileHash` und löscht es zuerst (identisches Escaping-Muster wie beim bestehenden `filePath`-Escaping im Processor). Damit ist die Ziel-Collection vor jedem Insert garantiert frei von Duplikaten für diesen `fileHash` — unabhängig davon, ob ein früherer Lauf das alte Quellobjekt erfolgreich gelöscht hat oder nicht. Ein fehlgeschlagenes Löschen des Altobjekts wird weiterhin nicht als „failed" gewertet (das neue Objekt ist ja korrekt migriert), aber neu unter `old_object_delete_failed` separat gezählt und in der Confirm-Zusammenfassung ausgewiesen, damit verwaiste Altobjekte sichtbar bleiben. Konvergenz-AC (erneuter `confirm=true`-Aufruf liefert keine Duplikate) ist damit erfüllt — Code-Trace bestätigt: EC-1 (Duplikat nach Collection-Wechsel) jetzt korrekt abgedeckt.

**BUG-2 (Medium) — behoben.** Neuer Node `Code: Ollama Health Check` (GET `/api/tags`, 5s Timeout) direkt nach `Code: Init Backfill Run`, gefolgt von `IF: Ollama Available`. Bei nicht erreichbarem Ollama bricht der Lauf sofort sauber ab (`Code: Respond Ollama Unavailable`, Lock wird freigegeben, keine Dokumente werden angefasst) statt sich durch Timeout-Ketten pro Dokument zu arbeiten. Deckt EC-4 jetzt wie spezifiziert ab.

Beide Fixes wurden per Code-Review verifiziert: JSON-Struktur validiert (`node -e "JSON.parse(...)"`), alle Node-Namen/Connections lösen auf (kein hängender Verweis), alle 11 Code-Node-Bodies syntaktisch korrekt geparst (`AsyncFunction`-Konstruktor-Check). Kein Live-Ausführungstest möglich (siehe Testmethode oben — weiterhin unverändert).

### Updated Summary
- **Acceptance Criteria:** 17/17 passed (1 weiterhin nicht unabhängig vor Deployment verifizierbar: Stichprobenprüfung „0 Rechnungen in Document-Collection" erfordert einen echten Confirm-Lauf gegen Produktionsdaten)
- **Bugs Found:** 2 total, 2 fixed (0 open)
- **Security:** Pass
- **Production Ready:** YES
- **Recommendation:** Deploy. Nach dem ersten echten Confirm-Lauf die Stichprobenprüfung gegen die `Document`-Collection manuell durchführen (PRD-Erfolgsmetrik).

## Deployment

**2026-08-21** — n8n-Workflows von Andreas manuell deployed: `alice-dms-classify-document`, `alice-dms-processor`, `alice-dms-classification-backfill`.

**Weaviate-Schema-Migration:** Claude Code hat aus dieser Sandbox keinen Netzwerkzugriff auf die Produktions-Weaviate-Instanz (`weaviate:8080` ist nur intern im Docker-Netzwerk erreichbar, kein Port-Mapping nach außen). Das Skript `scripts/proj78-add-classification-fields.sh` ist vorbereitet (analog zu `scripts/proj55-add-thumbnail-path.sh`) und ergänzt `classificationConfidence` (number) + `classificationUncertain` (boolean) an den sechs bestehenden Collections `Invoice`, `BankStatement`, `Document`, `Email`, `SecuritySettlement`, `Contract`. Idempotent — bereits vorhandene Properties werden übersprungen.

Ausführen (auf dem Server bzw. mit Netzwerkzugriff auf Weaviate):
```bash
./scripts/proj78-add-classification-fields.sh
# oder mit expliziter URL, falls weaviate:8080 nicht auflösbar ist:
./scripts/proj78-add-classification-fields.sh http://<weaviate-host>:8080
```

Status: **Abgeschlossen** — von Andreas ausgeführt, Properties erfolgreich an allen sechs Collections ergänzt.

### Fix-Forward — axios/Node-24-Crash bei Nicht-2xx-Antworten (2026-08-26)

Fix-Forward auf einem bereits freigegebenen Workflow — **kein neuer Review-Zyklus**, Status bleibt **Deployed**.

**Symptom:** Ein Backfill-Lauf gegen 150 Datensätze verarbeitete nur 149 und brach dann komplett ab. n8n-Log zeigte einen rohen Node.js-Crash in `Code: Compare & Handle` statt eines sauberen `winston.warn`-Eintrags: `TypeError: Cannot assign to read only property 'name' of object 'Error: Request failed with status code 422'` in `axios@1.18.0`. Derselbe Crash-Typ wie der zuerst in **PROJ-53** (Mail-Attachment-Backfill) diagnostizierte und dort gefixte Bug (siehe dort für die vollständige Ursachenanalyse).

**Ursache:** Bekannte Inkompatibilität zwischen `axios@1.18.0` und `Node.js ≥ 22` (Task-Runner läuft `Node.js v24.18.1`): Beim Bau eines `AxiosError`-Objekts für jede Nicht-2xx-Antwort wirft axios eine `TypeError`, weil `this.name = 'AxiosError'` auf einer read-only Property des `Error`-Prototyps unter neueren V8-Versionen fehlschlägt. Wichtiger Unterschied zu PROJ-53: Hier lag um den gesamten fehleranfälligen Code bereits ein äußerer `try { ... } catch(e) { logger.warn(...); await incr('failed', 1); ... }`-Block (Zeilen 147–219 vor dem Fix) — der Crash passiert aber **innerhalb** der Task-Runner-Infrastruktur selbst (`InternalTaskRunnerDisconnectAnalyzer` im Log), nicht als normale JavaScript-Exception innerhalb des Sandboxes. Kein noch so umfassender `try/catch` im Node-Code kann einen Absturz des Runner-Prozesses selbst abfangen — deshalb beendete der Fehler die gesamte Batch-Verarbeitung (`Split In Batches`-Schleife) statt nur den einen Datensatz als `failed` zu zählen.

`Code: Compare & Handle` enthielt **10** axios-Aufrufe (GraphQL-Queries, Objekt-Insert/-Delete/-Batch-Insert bei Weaviate, zwei Ollama-Extraktionsaufrufe, ein Thumbnailer-Trigger) — jeder davon war exponiert, nicht nur der eine, der den 422 auslöste. Zusätzlich waren zwei weitere Nodes desselben Workflows betroffen: `Code: Ollama Health Check` (1 Aufruf) und `Code: Fetch All Documents` (1 Aufruf).

**Fix:** In allen 12 axios-Aufrufen (3 Nodes) wurde `validateStatus: () => true` ergänzt, sodass axios für 4xx/5xx keinen `AxiosError` mehr konstruiert, sondern eine normale Response mit gesetztem `.status` zurückgibt. Statusprüfung erfolgt danach explizit im Code:

- `Code: Ollama Health Check` — `ollamaOk` wird jetzt aus `r.status` abgeleitet statt aus "kein Fehler geworfen"
- `Code: Fetch All Documents` — Nicht-2xx bricht die Pagination-Schleife für die betroffene Collection sauber ab (gleiches Muster wie der GraphQL-Fix in PROJ-53)
- `Code: Compare & Handle` — alle 10 Aufrufe (`cascadeDeleteBankTransactions`, `deleteExistingByHash`, `extractChunk`/Ollama, BankTransaction-Batch-Insert, Klassifizierungs-Extraktion, Weaviate-Insert des neuen Objekts, Alt-Objekt-Löschung, Thumbnail-Trigger) prüfen jetzt `r.status` statt sich auf axios' Wurfverhalten zu verlassen. Der Weaviate-Insert (Zeile mit dem ursprünglich gemeldeten 422) wirft jetzt `weaviate_insert_failed: HTTP 422 <Fehlerdetail>` — landet im äußeren `catch`, wird als `failed` gezählt und geloggt, der Lauf geht mit dem nächsten Batch-Item weiter, statt abzubrechen

**Zusätzlich gefixt (gleiches Muster, auf Nutzerwunsch mitgenommen):** `alice-dms-language-backfill` (PROJ-79) teilt laut PROJ-92 dieselbe Code-Basis für `Code: Ollama Health Check` und `Code: Fetch All Documents`, plus einen eigenen `axios.patch()`-Aufruf in `Code: Apply Correction` — alle drei ebenfalls auf `validateStatus` umgestellt. Siehe PROJ-79-Spec.

**Verifikation:**

- Beide geänderten Workflow-JSONs bleiben strukturell gültiges JSON, Node-Anzahl unverändert (19 bzw. 25), keine hängenden Connection-Referenzen (eigene Prüfung: alle `connections`-Einträge lösen auf existierende Node-Namen auf).
- Der geänderte `jsCode` aus allen betroffenen Nodes wurde extrahiert und mit `node --check` syntaktisch validiert (keine Parse-Fehler).
- Diff bewusst minimal gehalten (nur die betroffenen `jsCode`-Strings geändert, byte-identische Unicode-Kodierung beibehalten) — `git diff --stat`: 3 Zeilen je Datei.
- **Nicht verifiziert:** kein Lauf gegen echtes n8n in dieser Session (`mcp__n8n-mcp__*`-Tools nicht aufgerufen).

**Deployment:** Vom Nutzer manuell in n8n neu importiert und aktiviert (2026-08-26), zusammen mit `alice-dms-language-backfill`. Nutzer bestätigt: Verarbeitung läuft seither fehlerfrei.
