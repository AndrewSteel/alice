# PROJ-92: DMS-Backfill Confirm-Gate Fix

## Status: Planned
**Created:** 2026-08-24
**Last Updated:** 2026-08-24

## Dependencies
- Betrifft: `alice-dms-language-backfill` (PROJ-79, Deployed) und `alice-dms-classification-backfill` (PROJ-78, Deployed) — kein neuer Baustein, reiner Bugfix zweier bestehender Workflows.
- Identisches Bug-Muster wie der bereits behobene Fall in `alice-mail-attachment-backfill` (PROJ-53, Commit `8581996`) — dieses Ticket überträgt denselben Fix.

## Kontext

Bei der PROJ-53-QA-Nachprüfung wurde per Graph-Trace bestätigt, dass `alice-dms-language-backfill` und `alice-dms-classification-backfill` denselben Bug enthalten, der in `alice-mail-attachment-backfill` bereits gefunden und behoben wurde (Commit `8581996`, siehe dessen "Note (out of scope)"):

**Bug 1 — Confirm-Gate wirkungslos:** Der Graph beider Workflows ist `Webhook → Code: Acquire Backfill Lock → IF: Lock Acquired → Code: Init Backfill Run`. Der Lock-Node gibt ein neu gebautes Item (`{ _lock_acquired, _lock_error, lock_owner }`) zurück, ohne `body`/`query` durchzureichen. `Code: Init Backfill Run` liest den Payload aber über `$input.first().json.body` — also immer `undefined`. Damit ist `CONFIRM` unabhängig vom tatsächlich gesendeten `confirm`-Wert immer `false`; beide Workflows liefen über den Webhook vermutlich seit Einführung ausschließlich im Dry-Run.

**Bug 2 — Zeitlimit-Override wirkungslos (Nebenfund bei der Verifikation dieses Tickets):** Beide Workflows geben in `Code: Init Backfill Run` ein `MAX_RUNTIME_SECONDS`-Feld aus, aber `Code: Time Check` liest diesen Wert nicht — er hardcoded `elapsed >= 7200`. Ein Override des Zeitlimits über den Webhook-Payload hat damit in beiden Workflows keine Wirkung. Identisches Muster zum "dead config"-Nebenfund aus dem PROJ-53-Fix, dort betraf es nur `alice-mail-attachment-backfill`.

Beide Bugs wurden verifiziert (Code der betroffenen Nodes in beiden Workflow-JSONs gelesen, Graph-Struktur per `connections` bestätigt) und treten in beiden Workflows identisch auf.

## User Stories

- Als Admin möchte ich, dass ein Aufruf von `alice-dms-language-backfill` bzw. `alice-dms-classification-backfill` mit `{"confirm": true}` tatsächlich die Migration/Korrektur durchführt, statt stillschweigend im Dry-Run zu bleiben.
- Als Admin möchte ich, dass ein optional mitgegebener `max_runtime_seconds`-Override tatsächlich das Zeitlimit des Laufs verändert.

## Acceptance Criteria

- [ ] `Code: Init Backfill Run` liest den Webhook-Payload in beiden Workflows per Node-Name (`$('Webhook: POST /language-backfill')` bzw. `$('Webhook: POST /classification-backfill')`) statt über `$input.first().json`
- [ ] Ein Aufruf mit `{"confirm": true}` (Body) setzt in beiden Workflows `CONFIRM = true` und führt die tatsächliche Migration/Korrektur durch (kein Dry-Run)
- [ ] Ein Aufruf mit `{"confirm": true}` als Query-Parameter funktioniert weiterhin gleichwertig zum Body (bestehendes Verhalten, `body.confirm` hat Vorrang vor `query.confirm`)
- [ ] Ein Aufruf ohne `confirm` bzw. mit `confirm: false` bleibt im Dry-Run (bestehendes Sicherheitsverhalten, unverändert)
- [ ] `Code: Time Check` liest in beiden Workflows das von `Code: Init Backfill Run` ausgegebene `MAX_RUNTIME_SECONDS` statt es zu hardcoden; ein optionaler `max_runtime_seconds`-Override (Body oder Query) wirkt sich auf das tatsächliche Zeitlimit aus
- [ ] Ohne expliziten Override bleibt das Zeitlimit bei 7200s (2h) — keine Verhaltensänderung für den Normalfall
- [ ] Der vorgeschaltete Lock-Node (`Code: Acquire Backfill Lock`) bleibt unverändert (Konsistenz mit dem etablierten Muster, siehe PROJ-53-Fix-Begründung)

## Edge Cases

- **Webhook-Call ohne Body/Query überhaupt** (z.B. reiner GET ohne Parameter): `body`/`query` sind leere Objekte, `confirmRaw` ist `undefined`, `CONFIRM` bleibt `false` — Dry-Run, kein Crash.
- **`confirm` als String `"true"` statt Boolean `true`**: muss weiterhin als `true` gewertet werden (bestehende Logik `confirmRaw === true || confirmRaw === 'true'` bleibt erhalten).
- **`max_runtime_seconds` als ungültiger Wert** (z.B. negativ, nicht-numerisch, `0`): fällt zurück auf den Default 7200s, kein Crash und kein Zeitlimit von 0 (das den Lauf sofort abbrechen würde).
- **Zwei Backfill-Läufe desselben Workflows gleichzeitig gestartet**: unverändert durch den bestehenden Lock-Mechanismus abgedeckt (nicht Teil dieses Fixes).
- **Bereits laufender Dry-Run-Prozess in Produktion zum Zeitpunkt des Fixes**: kein Datenverlust — ein Dry-Run verändert per Definition keine Daten; nach dem Fix führt der nächste `confirm: true`-Aufruf die Migration erstmals tatsächlich aus.

## Technical Requirements (optional)

- Fix-Muster identisch zu Commit `8581996` (PROJ-53): `$('Webhook: ...')` statt `$input.first().json` für den Payload-Zugriff in `Code: Init Backfill Run`.
- Zusätzlich (Bug 2, in `8581996` nur für `alice-mail-attachment-backfill` behoben): `Code: Time Check` liest `MAX_RUNTIME_SECONDS` per Node-Name-Referenz auf `Code: Init Backfill Run` statt hardcoded `7200`.
- Der Lock-Node bleibt in beiden Workflows unverändert (etablierte Konvention, siehe Commit-Begründung `8581996`).

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### E) Workflow Architecture

PROJ-92 hat keine UI-Komponente. Es ändert zwei bestehende Workflows (`alice-dms-language-backfill`, `alice-dms-classification-backfill`) an derselben Stelle, mit demselben bereits produktiv bewährten Muster wie in `alice-mail-attachment-backfill` (PROJ-53, Commit `8581996`) — kein neuer Workflow, kein neuer Trigger, keine neuen Nodes.

**Einordnung in den bestehenden Ablauf (beide Workflows identisch):**

`Webhook → Code: Acquire Backfill Lock → IF: Lock Acquired → Code: Init Backfill Run → ... → Code: Time Check → ...`

**Änderung 1 — Payload-Zugriff in `Code: Init Backfill Run`:**

Statt des Payloads vom direkten Input (der vom dazwischenliegenden Lock-Node stammt und `body`/`query` nicht enthält) wird der ursprüngliche Webhook-Payload gezielt beim Webhook-Node selbst abgeholt, per Node-Namens-Referenz. `confirm` wird davon wie bisher aus Body oder Query gelesen (Body hat Vorrang), inkl. der bestehenden Boolean/String-Toleranz (`true` oder `"true"`).

**Änderung 2 — Zeitlimit-Override durchreichen:**

`Code: Init Backfill Run` liest zusätzlich einen optionalen `max_runtime_seconds`-Wert aus demselben Payload (Body oder Query) und gibt ihn validiert aus (Fallback auf 7200s bei fehlendem/ungültigem/nicht-positivem Wert). `Code: Time Check` liest diesen Wert anschließend per Node-Namens-Referenz auf `Code: Init Backfill Run` zurück, statt ihn wie bisher hardcoded zu berechnen.

**Data flow:** Webhook-Request (Body/Query mit optionalen `confirm`- und `max_runtime_seconds`-Feldern) → Lock-Erwerb (unverändert, gibt Payload nicht weiter) → Init liest Original-Payload direkt vom Webhook-Node → Rest des Laufs (Collections-Iteration, Klassifizierungs-/Sprachprüfung, Zeitlimit-Check) nutzt `CONFIRM` und `MAX_RUNTIME_SECONDS` aus Init.

**Integrationen:** Keine neuen. Weiterhin nur Redis (Lock, Lauf-Statistik) und Weaviate (Collections-Zugriff, bestehend).

**Fehlerverhalten:** Unverändert. Bleibt `confirm` unbestimmt oder falsy, bleibt der Lauf im bestehenden Dry-Run-Modus (Sicherheitsverhalten unverändert). Ein ungültiger `max_runtime_seconds`-Wert fällt auf den bisherigen Default 7200s zurück statt einen Fehler zu werfen oder ein Zeitlimit von 0 zu erzeugen.

### Tech-Entscheidungen (Begründung)

- **Exakt dasselbe Muster wie der PROJ-53-Fix (Commit `8581996`) übernehmen, keine eigene Lösung entwickeln:** Der Fix wurde dort bereits mit einem Graph-Trace-Test verifiziert und ist produktiv bewährt. Eine abweichende Implementierung in den beiden hier betroffenen Workflows würde unnötige Inkonsistenz zwischen drei strukturell identischen Backfill-Workflows schaffen.
- **Lock-Node bleibt unangetastet:** Wie in der Commit-Begründung von `8581996` festgehalten — der Lock-Node ist ein etabliertes, wiederverwendetes Muster über mehrere Backfill-Workflows hinweg. Ihn zu ändern, um den Payload durchzureichen, würde von dieser Konvention abweichen und mehr anfassen als nötig.
- **`max_runtime_seconds`-Fix wird mitgeliefert statt in einem separaten Ticket:** Gleiche Ursache (Init-Output wird von einem nachgelagerten Node ignoriert bzw. nicht korrekt berechnet), gleiche Dateien, gleicher Verifikationsaufwand — ein zweites Ticket für denselben Change-Set wäre unnötiger Overhead (Nutzerentscheidung während der Spec-Phase).

### Dependencies (Pakete)

Keine neuen Pakete — `redis` ist in beiden Workflows bereits im Einsatz.

---
_Implementation folgt in /backend._

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
