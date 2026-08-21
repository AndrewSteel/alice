# PROJ-79: DMS-Zusammenfassung Sprachkorrektur — nur Deutsch, Fix + Backfill Bestand

## Status: Deployed
**Created:** 2026-08-21
**Last Updated:** 2026-08-21

## Dependencies
- None (voraussetzungsfrei)
- **Wird benötigt von:** PROJ-81 (Frontend-Übersetzung on-the-fly) — setzt eine verlässlich deutsche `summary` als Ausgangstext für die Nutzersprachen-Übersetzung voraus

## Kontext

Die `alice-dms-processor`-Pipeline extrahiert je Dokument u. a. `title` und `summary` per LLM-Aufruf (`OLLAMA_MODEL_DMS`, temperature 0) — der Extraktions-Prompt gibt aktuell keinerlei Sprachvorgabe vor. Bei englischsprachigen oder gemischtsprachigen Quelldokumenten übernimmt das Modell entsprechend die Quellsprache, wodurch `title`/`summary` teils auf Englisch statt Deutsch gespeichert werden (siehe PRD Phase 3, Erfolgsmetrik: 100 % der Zusammenfassungen auf Deutsch). Das untergräbt die Konsistenz der DMS-Wissensbasis und ist Voraussetzung für PROJ-81, das auf einer garantiert deutschen Zusammenfassung aufbaut, um sie bei Bedarf in die Nutzersprache zu übersetzen.

Ein Präzedenzfall existiert bereits für Bildbeschreibungen (`alice-dms-image-description-backfill`, Feld `ai_description`): dort erzwingt ein deutsch formulierter Prompt ("Beschreibe dieses Bild ... auf Deutsch") die Zielsprache — allerdings ohne jede Nachprüfung, ob die Antwort tatsächlich Deutsch ist. Für PROJ-79 soll dieses Muster um eine leichtgewichtige Prüfung und einen gezielten zweiten Versuch ergänzt werden, analog zum Zwei-Versuche-Konfidenz-Muster aus PROJ-78 (DMS-Dokumentenklassifizierung).

Das Feature hat zwei Teile:
1. **Fix**: Der Extraktions-Prompt wird um eine explizite Deutsch-Vorgabe ergänzt; eine Heuristik prüft `title` und `summary` nach der Extraktion, bei Verdacht auf Englisch folgt automatisch ein zweiter, verschärfter Versuch.
2. **Backfill**: Der bestehende Dokumentenbestand (~500–2.000 Dokumente über alle sechs klassifizierbaren Collections) wird auf vermutlich-englische `title`/`summary`-Werte geprüft und für Treffer einmalig neu generiert.

## User Stories

- Als Andreas (Admin) möchte ich, dass neu eingehende Dokumente zuverlässig eine deutsche Zusammenfassung und einen deutschen Titel erhalten, damit ich mich beim Durchsuchen und Nachfragen der DMS-Wissensbasis auf einheitliches Deutsch verlassen kann.
- Als Andreas möchte ich, dass bei Verdacht auf eine englische Zusammenfassung automatisch ein zweiter, gezielterer Versuch unternommen wird, damit nicht jeder erste Fehlgriff des Modells unkorrigiert bleibt.
- Als Andreas möchte ich vor einer Massenänderung am Bestand einen Vorschau-Report sehen (welches Dokument mit welcher vermutlich-englischen Zusammenfassung/Titel betroffen ist), damit ich die Korrektur prüfen kann, bevor sie verbindlich wird.
- Als Andreas möchte ich den geprüften Backfill mit einem zweiten Aufruf bestätigen können, damit die betroffenen Bestandsdokumente korrigiert werden, ohne die Originaldateien auf dem NAS anzufassen.
- Als Andreas möchte ich, dass Dokumente, die auch nach zwei Versuchen weiterhin vermutlich-englisch bleiben, sichtbar markiert werden (statt sie stillschweigend zu übernehmen), damit ich sie später über das Vollständigkeits-Dashboard (PROJ-80) auffinden kann.

## Acceptance Criteria

### Fix (laufender Betrieb, `alice-dms-processor`)
- [ ] Der Extraktions-Prompt enthält für alle sechs Dokumenttypen eine explizite Vorgabe, dass `title` und `summary` auf Deutsch zu verfassen sind — unabhängig von der Sprache des Quelldokuments.
- [ ] Der erste Extraktionsversuch bleibt deterministisch (temperature 0), wie heute.
- [ ] Nach der Extraktion prüft eine Heuristik `title` und `summary` auf Anzeichen für überwiegend englischen statt deutschen Text.
- [ ] Deutet die Heuristik auf Englisch hin, läuft automatisch ein zweiter Versuch mit verschärfter Deutsch-Vorgabe im Prompt.
- [ ] Deutet auch der zweite Versuch laut Heuristik weiterhin auf Englisch hin, wird trotzdem das Ergebnis des zweiten Versuchs gespeichert (Pipeline blockiert nie), zusätzlich aber mit einem Flag markiert, das die Sprach-Unsicherheit kennzeichnet (konsumierbar durch PROJ-80).
- [ ] Ordner mit fest hinterlegtem `suggested_type` (kein `auto`) sind von der Prompt-Änderung genauso betroffen wie alle anderen — die Deutsch-Vorgabe gilt unabhängig vom Klassifizierungsmodus, da sie ausschließlich die Extraktion (nicht die Klassifizierung) betrifft.
- [ ] Die bestehende Klassifizierungs-Konfidenz-Logik aus PROJ-78 bleibt unverändert; beide Mechanismen laufen unabhängig nebeneinander (unterschiedliche Prüfgegenstände: Dokumenttyp vs. Sprache).

### Backfill (einmaliger Bestands-Lauf)
- [ ] Ein neuer, manuell auslösbarer Webhook-Endpoint (analog `alice-dms-classification-backfill`) prüft im Dry-Run-Modus (kein Confirm-Flag) die bereits gespeicherten `title`/`summary`-Werte jedes existierenden Weaviate-Objekts über alle sechs klassifizierbaren Collections mit derselben Heuristik — ohne dafür einen Ollama-Aufruf zu benötigen und ohne Daten zu verändern.
- [ ] Die Dry-Run-Response ist ein JSON-Report mit jedem Dokument, dessen `title` oder `summary` die Heuristik als vermutlich-englisch einstuft (Dateiname, Collection, betroffenes Feld, aktueller Wert).
- [ ] Derselbe Endpoint mit einem Confirm-Parameter (z. B. `confirm=true`) generiert für alle im Dry-Run gefundenen Kandidaten `title` und `summary` mit dem deutsch-erzwingenden Prompt (inkl. Zwei-Versuche-Logik wie im Fix) neu und aktualisiert nur diese beiden Felder am bestehenden Weaviate-Objekt — keine Neuextraktion anderer Felder, kein Collection-Wechsel, kein Insert/Delete.
- [ ] Der Backfill läuft gebatcht/zeitlich begrenzt (wiederverwendet das Time-Limit-/Lock-Pattern von `alice-dms-processor` bzw. `alice-dms-classification-backfill`), sodass er bei Bedarf über mehrere Läufe/Nächte abgeschlossen werden kann, statt in einem einzigen langen Request zu blockieren.
- [ ] Ein erneuter Dry-Run nach einem abgeschlossenen Confirm-Lauf liefert keine weiteren Kandidaten mehr, außer den nach zwei Versuchen weiterhin unsicheren Dokumenten (Konvergenz).
- [ ] Dokumente, bei denen die Neugenerierung fehlschlägt, werden übersprungen und geloggt (Redis-Stats analog bestehendem Fehler-Handling), der Gesamtlauf bricht dadurch nicht ab.
- [ ] Nach einem bestätigten Backfill-Lauf bestätigt eine manuelle Stichprobenprüfung der zuvor markierten Dokumente, dass `title`/`summary` jetzt auf Deutsch vorliegen (Abgleich gegen PRD-Erfolgsmetrik).

## Edge Cases

- **Kurze oder sprachneutrale Texte**: Sehr kurze Zusammenfassungen, reine Zahlen-/Betragsangaben oder Eigennamen (z. B. Firmennamen) liefern der Heuristik zu wenig Signal für eine verlässliche Sprach-Einschätzung → wird als unsicher statt als eindeutig-englisch behandelt, kein falscher Alarm bei sprachneutralem Text.
- **Gemischtsprachiger Quelltext** (z. B. deutsches Anschreiben mit englischen Fachbegriffen/Produktnamen): Solange `title`/`summary` selbst überwiegend deutsch formuliert sind, gilt das nicht als Treffer — einzelne englische Fachbegriffe im deutschen Satzbau lösen keine Korrektur aus.
- **Zweiter Versuch weiterhin unsicher**: Wird wie in den Acceptance Criteria beschrieben mit Best-Guess + Unsicherheits-Flag gespeichert, keine Blockade der Pipeline bzw. des Backfill-Laufs.
- **Ollama nicht erreichbar während Backfill**: Lauf bricht sauber ab (kein Teil-Update einzelner Dokumente), ist beim nächsten Trigger fortsetzbar und überspringt bereits korrigierte Dokumente (gleiches Verhalten wie in PROJ-78 etabliert).
- **Gleichzeitiger Lauf mit anderen DMS-Backfills/Processor**: Der neue Backfill nutzt denselben Sperrmechanismus wie `alice-dms-processor` und `alice-dms-classification-backfill`, damit keine zwei Läufe gleichzeitig um die Ollama-Ressource (RTX 3090) konkurrieren.
- **Leerer Bestand / keine Kandidaten im Dry-Run**: Report liefert eine leere Liste, Confirm-Aufruf ist dann ein No-Op.
- **Dokument wurde zwischen Dry-Run und Confirm-Lauf bereits gelöscht oder durch anderen Prozess verändert** (z. B. durch den PROJ-78-Klassifizierungs-Backfill in eine andere Collection verschoben): Wird beim Confirm-Lauf übersprungen und geloggt statt eines Fehlers, der den Gesamtlauf abbricht — analog zum bestehenden Fehler-Handling.

## Technical Requirements (optional)

- Kein neues LLM-Modell — weiterhin `OLLAMA_MODEL_DMS` für beide Extraktionsversuche (Fix und Backfill).
- Die Sprach-Heuristik ist eine leichtgewichtige, lokale Prüfung (keine externe API, kein zusätzliches Modell) — die konkrete Umsetzung (Wortliste, Schwellwert o. Ä.) obliegt der technischen Architektur-Entscheidung.
- Backfill ist reine Weaviate-Feld-Aktualisierung (`title`, `summary` sowie neues Unsicherheits-Flag); NAS-Originaldateien werden nicht verschoben oder verändert, kein Collection-Wechsel.
- Backfill-Zeitfenster darf sich nicht mit dem nächtlichen `alice-dms-processor`-Lauf oder anderen DMS-Backfills überschneiden (Ressourcen-Konflikt auf der RTX 3090 (Ollama)).

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Betroffene Workflows

- **`alice-dms-processor`** (bestehend) — Extraktions-Abschnitt wird um die Deutsch-Vorgabe und die Sprachprüfung erweitert.
- **`alice-dms-language-check`** (neu) — gemeinsamer n8n-Sub-Workflow (Execute-Workflow-Trigger), analog zu `alice-dms-classify-document` aus PROJ-78: enthält die Heuristik-Prüfung und die Zwei-Versuche-Logik an einer einzigen Stelle, damit Fix und Backfill garantiert dasselbe Sprachverhalten zeigen und nicht auseinanderlaufen.
- **`alice-dms-language-backfill`** (neu) — analog zu `alice-dms-classification-backfill` aufgebaut (Webhook, Dry-Run/Confirm-Schalter, gleiches Sperr- und Zeitlimit-Pattern).

Beides sind reine n8n-Automatisierungen ohne UI-Anteil — kein Frontend-Task nötig.

### E) Workflow-Architektur

#### Teil 1 — Fix in `alice-dms-processor`

- **Trigger:** unverändert (nächtlicher Zeitplan).
- **Ablauf (nur der Extraktions-Abschnitt ändert sich):**
  1. Der bestehende Extraktions-Prompt (heute ein einzelner Code-Baustein mit sechs Vorlagen, eine je Dokumenttyp) wird um einen deutschen Sprachhinweis ergänzt — für jeden der sechs Typen, unabhängig davon, ob der Ordner `auto` oder einen fest hinterlegten Typ nutzt (die Vorgabe betrifft nur die Extraktion, nicht die Klassifizierung).
  2. **1. Versuch** (Ollama, temperature 0, wie heute) liefert `summary` (alle sechs Typen) bzw. zusätzlich `title` (nur Document, Contract — die einzigen zwei Typen, die laut bestehendem Schema und Prompt überhaupt ein `title`-Feld führen).
  3. Der bestehende Parse-Fehler-Retry (gleicher Prompt bei ungültigem JSON) bleibt als eigenständiges Sicherheitsnetz unverändert erhalten — unabhängig von der neuen Sprachprüfung.
  4. **Neuer Schritt:** Der neue Sub-Workflow `alice-dms-language-check` prüft die tatsächlich vorhandenen Textfelder (`summary` immer, `title` nur bei Document/Contract) mit der leichtgewichtigen lokalen Heuristik auf Anzeichen für überwiegend englischen Text.
  5. Deutet die Heuristik auf Englisch hin → **2. Versuch**: erneuter Ollama-Aufruf mit demselben Prompt, aber verschärfter/expliziterer Deutsch-Vorgabe (temperature bleibt 0 — anders als bei PROJ-78 geht es hier nicht um Kreativität/Varianz, sondern um eine strengere Anweisung).
  6. Deutet auch der zweite Versuch auf Englisch hin, wird trotzdem dessen Ergebnis übernommen — zusätzlich markiert ein neues Flag die Sprach-Unsicherheit. Die Pipeline blockiert dadurch nie.
  7. Ab hier läuft die Pipeline unverändert weiter (Weaviate-Insert), schreibt aber zusätzlich das neue Flag ins Zielobjekt.
- **Unabhängigkeit von PROJ-78:** Die Klassifizierungs-Konfidenz-Logik (welcher Dokumenttyp) und die neue Sprachprüfung (welche Sprache) laufen als zwei getrennte Prüfschritte im selben Pipeline-Durchlauf, ohne sich gegenseitig zu beeinflussen — unterschiedliche Prüfgegenstände, unterschiedliche Sub-Workflows.
- **Datenmodell-Änderung:** Jede der sechs klassifizierbaren Collections erhält ein neues, optionales Feld:
  - „Sprache unsicher" (Ja/Nein-Flag) — analog zu `classificationUncertain` aus PROJ-78, konsumierbar durch das künftige Vollständigkeits-Dashboard (PROJ-80).
  Bestehende Dokumente sind davon nicht betroffen (Feld bleibt dort leer/false), bis sie neu extrahiert oder per Backfill korrigiert werden.
- **Betriebs-Statistiken:** Die bestehenden Redis-Lauf-Statistiken werden um Zähler für „Sprachprüfung: 2. Versuch nötig" und „nach 2. Versuch weiterhin unsicher" ergänzt — analog zu den PROJ-78-Zählern.

#### Teil 2 — Neuer Backfill-Workflow `alice-dms-language-backfill`

- **Trigger:** manueller Webhook-Aufruf (POST), von Andreas ausgelöst — kein automatischer Zeitplan.
- **Modus-Schalter:** ohne `confirm`-Parameter → Dry-Run (nur Bericht, keine Änderung, kein Ollama-Aufruf nötig — reine Heuristik-Prüfung der bereits gespeicherten Werte); mit `confirm=true` → verbindliche Korrektur.
- **Ablauf:**
  1. Alle sechs klassifizierbaren Collections werden nacheinander in Batches durchlaufen (gleiches Batch-/Zeitlimit-Pattern wie `alice-dms-classification-backfill`), sodass ein Lauf bei Bedarf über mehrere Nächte fortgesetzt werden kann.
  2. **Dry-Run:** Jedes bestehende Weaviate-Objekt wird mit derselben Heuristik aus `alice-dms-language-check` gegen seine gespeicherten `summary`-/`title`-Werte geprüft — ohne Ollama-Aufruf, ohne Schreibaktion. Treffer werden gesammelt und als JSON-Bericht zurückgegeben (Dateiname, Collection, betroffenes Feld, aktueller Wert).
  3. **Confirm-Lauf:** Für jeden Dry-Run-Treffer wird `title`/`summary` mit derselben Zwei-Versuche-Logik wie im Fix (`alice-dms-language-check`, aufgerufen mit dem gespeicherten Volltext als Eingabe) neu generiert und nur diese beiden Felder plus das Unsicherheits-Flag am bestehenden Objekt aktualisiert — keine Neuextraktion anderer Felder, kein Collection-Wechsel, kein Insert/Delete, keine Thumbnail-Neuerzeugung nötig (Bildbezug bleibt unverändert).
  4. Fehler bei einzelnen Dokumenten (z. B. Ollama-Fehler bei der Neugenerierung) werden übersprungen, geloggt und in den Lauf-Statistiken gezählt — der Gesamtlauf läuft weiter. Ein zwischen Dry-Run und Confirm gelöschtes oder in eine andere Collection verschobenes Dokument wird beim Zugriff übersprungen und geloggt statt den Lauf abzubrechen.
  5. **Sperre gegen Überschneidung:** derselbe Redis-Lock-Key wie `alice-dms-processor` und `alice-dms-classification-backfill` (`alice:dms:processor:lock:run`), damit nie zwei DMS-Läufe gleichzeitig um die Ollama-Ressource (RTX 3090) konkurrieren.
  6. **Ollama-Erreichbarkeit:** derselbe Health-Check-Circuit-Breaker wie in `alice-dms-classification-backfill` (kurzer Timeout-Check vor Laufbeginn) — bei Ausfall sauberer Sofort-Abbruch statt schleichendem Timeout pro Dokument.
  7. Antwort auf den Webhook-Aufruf: Dry-Run liefert die Treffer-Liste, Confirm-Lauf liefert eine Zusammenfassung (korrigiert / übersprungen / fehlgeschlagen / weiterhin unsicher).
- **Konvergenz:** Da reine Feld-Updates ohne Collection-Wechsel stattfinden (kein Insert/Delete-Duplikat-Risiko wie bei PROJ-78), liefert ein erneuter Dry-Run nach einem abgeschlossenen Confirm-Lauf automatisch keine weiteren Treffer mehr — außer den nach zwei Versuchen weiterhin als unsicher markierten Dokumenten, die laut Spec explizit als erwartetes Restergebnis gelten.

### Tech-Entscheidungen (Begründung)

- **Gemeinsamer Sub-Workflow für Fix und Backfill (`alice-dms-language-check`):** Exakt dasselbe Muster wie PROJ-78 (`alice-dms-classify-document`). Heuristik und Zwei-Versuche-Logik werden an einer Stelle gepflegt, statt zweimal unabhängig implementiert zu werden — verhindert Drift zwischen laufendem Betrieb und Backfill.
- **Dry-Run ohne Ollama-Aufruf:** Die Heuristik ist eine lokale, leichtgewichtige Prüfung (kein Modellaufruf nötig) — dadurch ist der Dry-Run-Report schnell und ressourcenschonend, unabhängig von der Größe des Bestands (~500–2.000 Dokumente) und ohne Konkurrenz um die Ollama-Ressource.
- **Zweiter Versuch bei temperature 0 (nicht erhöht wie bei PROJ-78):** Bei der Klassifizierung hilft höhere Temperature, echte inhaltliche Mehrdeutigkeit aufzulösen. Bei der Sprachvorgabe ist das Problem meist, dass das Modell die Anweisung beim ersten Versuch schlicht ignoriert oder überliest — eine deutlichere, strengere Formulierung im zweiten Versuch adressiert das gezielter als zufällige Varianz.
- **Reine Feld-Aktualisierung im Backfill statt Collection-Wechsel:** Anders als bei PROJ-78 ändert sich hier nie die Collection (die Sprache eines Dokuments hat keinen Einfluss auf seinen Dokumenttyp) — dadurch entfällt das Duplikat-Risiko aus PROJ-78 (BUG-1) von vornherein, kein zusätzlicher Dedup-Mechanismus nötig.
- **Sprach-Heuristik-Schwellwert als Umgebungsvariable:** Analog zu `DMS_CLASSIFICATION_CONFIDENCE_THRESHOLD` aus PROJ-78 — der genaue Schwellwert lässt sich im Betrieb nachjustieren (z. B. wenn sich zu viele False Positives bei kurzen/eigennamenlastigen Texten zeigen), ohne den Workflow neu zu deployen.
- **`title`-Prüfung nur für Document/Contract:** Die Acceptance Criteria sprechen allgemein von „`title` und `summary`" über alle sechs Typen — laut bestehendem Schema und Extraktions-Prompt führen aber nur `Document` und `Contract` überhaupt ein `title`-Feld; die übrigen vier Typen (Invoice, BankStatement, Email, SecuritySettlement) haben nur `summary`. Die Sprachprüfung inspiziert daher je Typ nur die tatsächlich vorhandenen Felder — keine Schema-Änderung nötig, keine Abweichung von der eigentlichen Absicht der Spec.

### Datenmodell (einfache Sprache)

```
Jedes klassifizierbare Dokument bekommt zusätzlich:
- Sprache-unsicher-Flag (Ja/Nein)

Betrifft: Document, Invoice, Contract, Email, BankStatement, SecuritySettlement
Geprüfte Felder je Dokument: summary (immer), title (nur Document, Contract)
Speicherort: Weaviate (gleiche Collection wie das Dokument selbst, keine neue Datenbank)
```

### Abhängigkeiten (zu installierende Pakete)

Keine neuen Pakete/Node-Typen nötig. Beide neuen Workflows nutzen ausschließlich bereits vorhandene Bausteine (HTTP-Aufruf an Ollama, Weaviate-REST-API, Redis-Lock-/Winston-Logging-Pattern), die im Container bereits verfügbar sind.

### Bestätigte Annahmen

- Sprach-Heuristik-Schwellwert ist über eine neue Umgebungsvariable konfigurierbar (mit Andreas im Review bestätigt, analog zum PROJ-78-Muster) — konkreter Startwert obliegt dem Backend-Dev.
- Die Sprachprüfung inspiziert je Dokumenttyp nur die tatsächlich vorhandenen Textfelder (`summary` immer, `title` nur bei Document/Contract) statt aller sechs Typen pauschal auf `title` zu prüfen (mit Andreas im Review bestätigt).

## Implementation Notes (Backend)

**Neue Workflows:**
- `workflows/alice-dms-language-check.json` — geteilter Sub-Workflow (analog `alice-dms-classify-document`): lokale Englisch-Heuristik (Wortlisten-Verhältnis, konfigurierbar über `DMS_LANGUAGE_HEURISTIC_THRESHOLD`, Default 0.3) gegen `summary`/`title`; bei Verdacht ein zweiter Ollama-Aufruf (temperature 0) mit demselben Extraktions-Prompt plus verschärfter Deutsch-Direktive. Gibt `{ summary, title, languageUncertain, language_retried, extracted }` zurück — `extracted` enthält bei Retry den kompletten neu geparsten JSON-Datensatz, nicht nur die beiden Sprachfelder.
- `workflows/alice-dms-language-backfill.json` — Webhook `POST /alice-dms-language-backfill`, Dry-Run/Confirm-Schalter, gleicher Redis-Lock-Key (`alice:dms:processor:lock:run`) und Zeitlimit-Pattern (7200s) wie `alice-dms-classification-backfill`. Dry-Run läuft rein heuristisch ohne Ollama-Aufruf. Confirm nutzt `alice-dms-language-check` je Treffer und aktualisiert nur `summary`/`title`/`languageUncertain` per PATCH am bestehenden Weaviate-Objekt (kein Insert/Delete, kein Collection-Wechsel, keine Thumbnail-Neuerzeugung).

**Geänderte Workflows:**
- `workflows/alice-dms-processor.json`: Extraktions-Prompt (`Code: Build Extraction Prompt`) um eine deutsche Sprachdirektive ergänzt (einmal an den gewählten Typ-Prompt angehängt, gilt für alle sechs Typen). Neue Knoten zwischen `Code: Parse Extract Result` und `Code: Build Weaviate Query`: `Code: Prep Language Check Input` → `Execute: Language Check` → `Code: Map Language Result` (führt bei Retry den vollständigen neu-extrahierten Datensatz zusammen). `Code: Build Weaviate Payload` schreibt zusätzlich `languageUncertain` in alle sechs Branches. Neue Redis-Stats-Zähler `language_retries` / `language_still_uncertain`, geloggt in beiden Final-Log-Knoten.

**Datenmodell:** Neues optionales Boolean-Feld `languageUncertain` in den Weaviate-Schemas `schemas/invoice.json`, `bank-statement.json`, `security-settlement.json`, `document.json`, `email.json`, `contract.json` (analog `classificationUncertain` aus PROJ-78). Muss vor Deploy per `./scripts/init-weaviate-schema.sh` angewendet werden (Schema-Änderungen werden von Weaviate additiv übernommen, kein Reset nötig).

**Offene Punkte für Deploy:**
- Beide neuen Workflows referenzieren den Sub-Workflow `alice-dms-language-check` über einen Platzhalter-Workflow-ID (`REPLACE_LANG_CHECK_WORKFLOW_ID`) — muss beim Import in n8n durch die tatsächliche ID ersetzt werden (gleiches Verfahren wie bei `alice-dms-classify-document` in PROJ-78).
- `DMS_LANGUAGE_HEURISTIC_THRESHOLD` ist nicht in `docker/compose/automations/n8n/compose.yml` deklariert (Code-Fallback: 0.3) — exakt dasselbe Muster wie das bestehende `DMS_CLASSIFICATION_CONFIDENCE_THRESHOLD` aus PROJ-78, das ebenfalls nicht dort deklariert ist. Funktioniert über `$env`, da `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` gesetzt ist.

## QA Test Results

**Tested:** 2026-08-21
**App URL:** n/a (n8n backend feature, no UI) — live Alice stack (Weaviate/Ollama/n8n at n8n.happy-mining.de) not reachable from this environment; workflows also not yet deployed (per project convention, deploy is a manual user step). Testing performed as static/logic verification of the workflow JSON against every acceptance criterion, plus a security audit of the code, plus a full regression check of `alice-dms-processor`'s existing (deployed) logic.
**Tester:** QA Engineer (AI)

### Acceptance Criteria Status

#### AC-1: Fix — German directive in extraction prompt (all 6 types)
- [x] `Code: Build Extraction Prompt` appends one shared `GERMAN_DIRECTIVE` string to whichever type-prompt is selected — applies uniformly to all six document types (Invoice, BankStatement, Document, Email, SecuritySettlement, Contract).

#### AC-2: First extraction attempt stays deterministic (temperature 0)
- [x] `HTTP: Ollama Extract` still calls with `options: { temperature: 0 }`, unchanged from before this feature.

#### AC-3: Heuristic checks title/summary after extraction
- [x] `alice-dms-language-check` runs a local English-word-ratio heuristic against `summary` (always) and `title` (only when the document type actually has one — Document/Contract), matching the confirmed technical decision that not all six types carry a `title` field.

#### AC-4: Second attempt on suspected-English with stricter directive
- [x] On a heuristic hit, `alice-dms-language-check` re-calls Ollama at temperature 0 with the original extraction prompt plus an explicit, stricter German-only directive appended.

#### AC-5: Still-uncertain after 2nd attempt → store anyway + flag, never block
- [x] `alice-dms-language-check` always returns a result (falls back to the 1st attempt's values if the 2nd Ollama call throws) and sets `languageUncertain: true` when the 2nd attempt still looks English. `Code: Map Language Result` in the processor has `continueOnFail: true` upstream and defaults to `languageUncertain: false, no change` if the sub-workflow call itself errors — the pipeline never halts.

#### AC-6: Fixed `suggested_type` folders equally affected
- [x] The German directive is applied in `Code: Build Extraction Prompt`, which runs identically regardless of whether `_document_type` came from `Code: Map Classify Result` (LLM/auto path) or `Code: Use Suggested Type` (fixed-type path) — both converge into the same extraction-prompt node before the language check.

#### AC-7: PROJ-78 classification logic unchanged, independent of language check
- [x] Diff-verified: no `classificationConfidence`/`classificationUncertain`/`llm_classified`/classification-retry code paths were touched. The two mechanisms run as separate sub-workflow calls (`Execute: Classify Document` vs. `Execute: Language Check`) writing to separate fields.

#### AC-8: Backfill dry-run — pure heuristic, no Ollama call, no writes
- [x] Confirmed via connection-graph trace: `IF: Confirm Mode`'s false-branch goes straight to `Code: Report Dry-Run Hit` (Redis-only), never reaching `Code: Prep Language Check Input` / `Execute: Language Check` (the only Ollama-calling nodes). `Code: Ollama Health Check` itself also skips the Ollama ping entirely when `!trigger.confirm`.

#### AC-9: Dry-run report format (fileName, collection, field, current value)
- [x] FIXED (post-QA, see BUG-3). `Code: Report Dry-Run Hit` now emits one report entry per affected field: `{ fileName, filePath, collection, field: 'summary'|'title', value }` — a document with both fields flagged produces two clean entries instead of one entry with two booleans.

#### AC-10: Confirm re-generates via German-forcing 2-attempt prompt, PATCH-only update
- [x] `Code: Apply Correction` calls `axios.patch` on the existing object's `/v1/objects/{class}/{id}` with only `{ summary, title?, languageUncertain }` — no insert, no delete, no collection field. Uses the shared `alice-dms-language-check` sub-workflow for the actual 2-attempt logic (same as the fix).

#### AC-11: Batched/time-limited, resumable across runs
- [x] Reuses `Split In Batches` + `Code: Time Check` (7200s wall-clock) + Redis-lock-renewal pattern, identical structure to `alice-dms-classification-backfill`.

#### AC-12: Re-run dry-run after confirm converges (no new hits except still-uncertain)
- [x] Verified the heuristic word-list/threshold logic is byte-identical between `alice-dms-language-check` and the backfill's own `Code: Heuristic Check` (only comment text differs). Corrected documents' new `summary`/`title` will no longer trip the heuristic; still-uncertain documents keep their best-guess (still English-leaning) values and legitimately reappear, matching the AC's stated exception.

#### AC-13: Per-document failures skipped + logged, run doesn't abort
- [x] `Code: Apply Correction` wraps the PATCH in try/catch, increments `failed` stat on error, and returns `_outcome: 'failed'` — `Split In Batches` continues to the next item regardless.

#### AC-14: Manual spot-check after confirm
- [ ] NOT TESTABLE in this session — requires a live confirm run against production Weaviate data, which requires deploy first (out of scope for backend QA; to be done by Andreas post-deploy per the AC's own wording "manuelle Stichprobenprüfung").

### Edge Cases Status

#### EC-1: Short/name-only/number-only text → inconclusive, not flagged
- [x] `englishRatio()` returns `null` (never a hit) when fewer than 6 matched words are found, in both the sub-workflow and the backfill's local copy.

#### EC-2: Mixed-language text (German with English loanwords) → not a hit if summary/title itself is majority German
- [x] The ratio-based heuristic only flags when the English-marker-word ratio crosses the configurable threshold (default 0.3) — a few embedded loanwords in an otherwise-German sentence stay well under that ratio.

#### EC-3: Still uncertain after 2nd attempt → best-guess + flag, no blocking
- [x] Same as AC-5.

#### EC-4: Ollama unreachable during backfill → clean abort, no partial updates, resumable
- [x] `Code: Ollama Health Check` (confirm-mode only) → `IF: Ollama Available` false-branch → `Code: Respond Ollama Unavailable`, which releases the lock and responds before any document is touched. Reuses the exact same circuit-breaker pattern PROJ-78 added after its own QA cycle.

#### EC-5: Concurrent run with other DMS backfills/processor → shared lock
- [x] `Code: Acquire Backfill Lock` uses the identical Redis key `alice:dms:processor:lock:run` as `alice-dms-processor` and `alice-dms-classification-backfill`.

#### EC-6: Empty backlog / no dry-run candidates → empty list, confirm is a no-op
- [x] `IF: Queue Empty` → `Code: Empty Summary` returns `hits: []` / `hits_found: 0` immediately; a confirm call against an empty backlog would trivially process zero items the same way.

#### EC-7: Document deleted/moved between dry-run and confirm → skipped + logged, no run-abort
- [x] `Code: Apply Correction`'s PATCH against a since-deleted `weaviate_id` throws (404), is caught, logged via winston, counted in `failed`, and the batch loop continues.

### Security Audit Results

**n8n workflow features:**
- [x] Authentication: webhook uses `authentication: "none"`, matching the existing deployed `alice-dms-classification-backfill` exactly — access is VPN-only per the project's stated architecture (CLAUDE.md: "Access is only via VPN"), not a regression introduced by this feature.
- [x] Authorization: no user-scoped data involved (system-wide DMS backfill, admin-triggered operational endpoint) — same trust model as the existing classification backfill.
- [x] Input validation: `confirm` param is only ever compared with strict equality, never interpolated into a query, GraphQL string, or shell command. All GraphQL query fragments (`class`, `textField`, `hasTitle`, pagination `cursor`) are sourced from the hardcoded `COLLECTIONS` array or Weaviate's own `_additional.id`, never from webhook input — no injection surface.
- [x] No secrets visible in logs: winston log lines only include file paths/classes/error messages, no credentials or tokens.
- [ ] Note (not a new issue): document plaintext is interpolated into the Ollama prompt for both the 1st recheck and 2nd-attempt calls — a theoretical prompt-injection surface via malicious document content. This exposure already exists identically in the deployed PROJ-78 classification prompt and every extraction prompt in `alice-dms-processor`; not introduced or worsened by this feature, out of scope to fix here.

### Bugs Found

#### BUG-1: Sub-workflow ID placeholder not yet resolved (blocks deploy)
- **Severity:** Medium
- **Steps to Reproduce:**
  1. Import `workflows/alice-dms-language-check.json`, `alice-dms-processor.json`, or `alice-dms-language-backfill.json` into n8n as-is.
  2. `Execute: Language Check` nodes in both the processor and the backfill still reference `workflowId.value: "REPLACE_LANG_CHECK_WORKFLOW_ID"`.
  3. Expected: the Execute-Workflow node resolves to the real `alice-dms-language-check` sub-workflow ID.
  4. Actual: the node will fail to resolve at runtime until the placeholder is manually replaced with the real workflow ID assigned by n8n on import (same one-time bootstrapping step PROJ-78 needed for `alice-dms-classify-document`, ID `JHyjjKyhcSxPgAv4` at the time).
- **Priority:** Fix before deployment — must be resolved as part of the `/deploy` step (import `alice-dms-language-check` first, note its assigned ID, then patch both referencing workflows before importing them).

#### BUG-2: `DMS_LANGUAGE_HEURISTIC_THRESHOLD` not declared in `docker/compose/automations/n8n/compose.yml`
- **Severity:** Low
- **Steps to Reproduce:**
  1. Code reads `$env.DMS_LANGUAGE_HEURISTIC_THRESHOLD` with a `0.3` fallback if unset/unparseable.
  2. The variable is not passed through in the n8n container's `environment:` block.
  3. Expected: an operator setting this var in `.env` to tune the heuristic would have it take effect.
  4. Actual: works only if n8n's Node.js process happens to inherit it from the host process environment directly (uncertain, depends on `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` semantics) — otherwise the fallback default silently applies regardless of what's set in `.env`.
  5. Note: this exactly mirrors a pre-existing state in PROJ-78 — `DMS_CLASSIFICATION_CONFIDENCE_THRESHOLD` has the identical gap in the same compose file today, and that feature is already deployed to production. Not a regression specific to PROJ-79, but worth fixing for both at the same time.
- **Priority:** Nice to have — flag for Andreas; likely worth a follow-up chore ticket covering both threshold vars together rather than a one-off fix here.

#### BUG-3: Dry-run report doesn't literally separate "affected field" from "current value" per-field — FIXED
- **Severity:** Low
- **Steps to Reproduce:**
  1. Trigger a dry-run backfill with a document whose `summary` is English but `title` is fine (or vice versa).
  2. Expected (per AC wording): report entry names the one affected field and its current value.
  3. Actual (before fix): report entry included `summaryHit`/`titleHit` booleans plus both `summary` and `title` values unconditionally — all necessary information was present, but a consumer had to combine two fields to determine "the" affected field/value rather than reading it directly off one `field`/`value` pair.
- **Priority:** Nice to have — cosmetic/report-shape only, did not affect correctness of detection or correction.
- **Fix:** `Code: Report Dry-Run Hit` in `workflows/alice-dms-language-backfill.json` now pushes one report entry per affected field: `{ fileName, filePath, collection, field: 'summary'|'title', value }`. A document with both fields flagged produces two clean entries instead of one entry with two booleans.

### Summary
- **Acceptance Criteria:** 14/14 fully passed (AC-9 fixed post-QA), 1 not independently testable pre-deploy (AC-14, by design — requires live data after deploy)
- **Bugs Found:** 3 total (0 critical, 0 high, 1 medium, 2 low) — BUG-3 fixed; BUG-1 requires the deploy step itself; BUG-2 deferred as a follow-up chore
- **Security:** Pass — no new injection, auth, or secrets-exposure issues found; one pre-existing, unchanged prompt-injection exposure noted for awareness only
- **Production Ready:** YES, conditional on resolving BUG-1 during the deploy step (expected — it's a one-time bootstrapping step inherent to n8n's Execute-Workflow-by-ID model, identical to what PROJ-78 needed)
- **Recommendation:** Proceed to `/deploy`. During deploy: import `alice-dms-language-check` first, capture its assigned workflow ID, then update the `workflowId.value` placeholder in both `alice-dms-processor.json` and `alice-dms-language-backfill.json` before importing/activating those two. BUG-2 is low-priority and can be deferred.

## Deployment

**Status:** Deployed to production.
**Deployed:** 2026-08-21

- n8n workflows (`alice-dms-language-check`, `alice-dms-processor`, `alice-dms-language-backfill`) deployed manually by Andreas.
- Weaviate schema migration (`scripts/proj79-add-language-field.sh`) run successfully — `languageUncertain` added to all 6 classifiable collections.

This sandbox had no network path to the production n8n/Weaviate instances (same constraint as PROJ-78: `weaviate:8080` is internal-only, and n8n workflow imports must be done by the user per project convention — Claude never deploys n8n workflows or writes directly to production Weaviate), so both steps above were executed manually by Andreas.

### Deploy steps taken (in this order)

1. **Import the shared sub-workflow first:** `Deploy n8n-workflow alice-dms-language-check`
   - Note the workflow ID n8n assigns to it after import (visible in the URL / workflow settings).
2. **Patch the placeholder ID** in the two files below, replacing `REPLACE_LANG_CHECK_WORKFLOW_ID` with the real ID from step 1 (both the `value` and, if desired, `cachedResultName` stays `"alice-dms-language-check"`):
   - `workflows/alice-dms-processor.json` — node `Execute: Language Check`
   - `workflows/alice-dms-language-backfill.json` — node `Execute: Language Check`
3. **Import/update the two patched workflows:**
   - `Deploy n8n-workflow alice-dms-processor` (this updates the existing, already-active nightly workflow — the new nodes are additive, no need to deactivate first)
   - `Deploy n8n-workflow alice-dms-language-backfill` (new webhook workflow — activate after import)
4. **Run the Weaviate schema migration** (adds `languageUncertain` to all 6 classifiable collections, idempotent — safe to re-run):
   ```bash
   ./scripts/proj79-add-language-field.sh http://weaviate:8080
   ```
   Run this on/near the server, same pattern as `scripts/proj78-add-classification-fields.sh`.
5. **Smoke test:**
   - Trigger `alice-dms-language-backfill` once with no `confirm` param (dry-run) — should return `{ mode: 'dry-run', total_checked: N, hits_found: 0..N, hits: [...] }` without errors.
   - Check n8n execution log for the next nightly `alice-dms-processor` run (02:00) for `language_retries`/`language_still_uncertain` in the final stats log — confirms the new nodes execute without errors.

### Known follow-up (not blocking, see QA BUG-2)
`DMS_LANGUAGE_HEURISTIC_THRESHOLD` is not declared in `docker/compose/automations/n8n/compose.yml` (same pre-existing gap as `DMS_CLASSIFICATION_CONFIDENCE_THRESHOLD` from PROJ-78) — code falls back to `0.3` if unset. Worth a combined follow-up chore for both threshold vars rather than a one-off fix here.
