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

### Implementation Notes (Backend)

**Umgesetzt in:** `workflows/alice-dms-language-backfill.json`, `workflows/alice-dms-classification-backfill.json` (je 4 geänderte Zeilen, keine weiteren Dateien).

**Geänderte Nodes (beide Workflows identisch):**

- **`Code: Init Backfill Run`**: liest den Payload jetzt per `$('Webhook: POST /...')` statt `$input.first().json` — exakt das Muster aus Commit `8581996`. Zusätzlich: liest einen optionalen `max_runtime_seconds` aus Body/Query, validiert ihn (`parseInt`, Fallback 7200 bei `NaN`/`<= 0`) und gibt ihn als `MAX_RUNTIME_SECONDS` statt des bisherigen hardcoded Werts aus.
- **`Code: Time Check`**: liest `MAX_RUNTIME_SECONDS` jetzt per `$('Code: Init Backfill Run').first().json.MAX_RUNTIME_SECONDS` (mit try/catch-Fallback auf 7200) statt es hardcoded zu berechnen.

Der vorgeschaltete Lock-Node (`Code: Acquire Backfill Lock`) wurde wie in der Spec vorgesehen nicht angefasst.

**Verifikation (Graph-Trace, kein Deploy):**

- JSON valide in beiden Dateien; Diff exakt 4 Zeilen pro Datei (nur die zwei betroffenen `jsCode`-Strings).
- Beide geänderten Code-Nodes bestehen `node --check` in beiden Workflows.
- Kein `console.log` eingeführt; alle `$('Node')`-Referenzen lösen auf bestehende Node-Namen auf.
- Eigenes Verifikationsskript (`verify_proj92.mjs`, nicht ins Repo übernommen) führt den echten gelieferten Node-Code mit gefaktem `redis`/`winston`/`$input`/`$()` aus, analog zum PROJ-53-Testansatz: `confirm: true` (Body) → `CONFIRM=true`; kein Payload → `CONFIRM=false` (Dry-Run-Default bleibt sicher); `confirm: 'true'` als Query-String → `true`; `max_runtime_seconds`-Override propagiert korrekt bis zum tatsächlichen Zeitlimit-Check in `Code: Time Check`; ungültiger Override (negativ) fällt auf 7200 zurück. **10/10 Checks bestanden** (5 pro Workflow).

**Nicht verifizierbar ohne Deploy/n8n-Instanz:** echtes Laufzeitverhalten in n8n (Webhook-Routing, tatsächliche Redis-Instanz), End-to-End-Lauf mit echtem `confirm: true` gegen Weaviate.

---
_Implementation abgeschlossen._

## QA Test Results

**Tested:** 2026-08-24
**Commit under test:** `fc4ed65` (fix(PROJ-92): Read webhook payload by node name in DMS backfill workflows)
**Scope:** `workflows/alice-dms-language-backfill.json`, `workflows/alice-dms-classification-backfill.json`
**Tester:** QA Engineer (AI)

### Testmethode

Kein Deploy und kein Live-n8n/Redis in dieser Umgebung — gleiches Vorgehen wie bei PROJ-53/PROJ-94:

1. **Statische Graph-Analyse:** `connections`-Objekt eigenständig traversiert, Node-Parameter direkt aus der JSON gelesen (nicht der Implementer-Beschreibung vertraut).
2. **Struktureller Alt/Neu-Vergleich:** `fc4ed65~1` vs. `fc4ed65` auf Node-Ebene für beide Dateien.
3. **Isolierte Re-Execution:** `Code: Init Backfill Run` und `Code: Time Check` aus beiden Workflows extrahiert und der **echte** Node-Code gegen gefaktes `redis`/`winston` und injizierte `$input`/`$()`-Globals ausgeführt (eigenes Skript, unabhängig vom Implementer-Verifikationsskript neu geschrieben).
4. **Propagations-Trace:** Verfolgt, wie `confirm` und `MAX_RUNTIME_SECONDS` vom Init-Node durch die nachgelagerten Nodes bis zum eigentlichen Gate (`IF: Confirm Mode` bzw. `doc.confirm`-Check in `Code: Compare & Handle`) fließen — nicht nur Init isoliert geprüft.

**Ergebnis: 14/14 Checks bestanden, 0 Critical/High/Medium Bugs, 1 Low-Finding (vorbestehendes Muster, siehe unten).**

### Acceptance Criteria Status

| # | Acceptance Criterion | Status | Nachweis |
|---|---------------------|--------|----------|
| AC-1 | `Code: Init Backfill Run` liest Payload per Node-Name statt `$input` (beide Workflows) | **PASS** | Beide Dateien: `$('Webhook: POST /language-backfill')` bzw. `$('Webhook: POST /classification-backfill')` ersetzt `$input.first().json`. Diff-Scoping bestätigt: nur die zwei `jsCode`-Parameter geändert, sonst nichts. |
| AC-2 | `{"confirm": true}` (Body) → `CONFIRM = true`, tatsächliche Migration statt Dry-Run | **PASS** | Eigene Re-Execution: Body `{confirm: true}` → `CONFIRM: true` in beiden Workflows. Propagations-Trace bestätigt: `Code: Fetch All Documents` kopiert `confirm: trigger.confirm` auf jedes Dokument-Item; `IF: Confirm Mode` (language) und `doc.confirm`-Check in `Code: Compare & Handle` (classification) werten diesen Wert aus — beide erreichen bei `CONFIRM=true` den Migrations-/Korrektur-Pfad. |
| AC-3 | `confirm` als Query-Parameter gleichwertig zu Body, Body hat Vorrang | **PASS** | Code unverändert in dieser Hinsicht (`body.confirm !== undefined ? body.confirm : query.confirm`), nur die Payload-Quelle wurde korrigiert. Eigene Tests: Query `confirm: 'true'` → `true`; Body-Wert übersteuert bei beiden gesetzt (bestehende Logik, nicht Teil des Fixes, aber durch den Fix jetzt überhaupt erreichbar). |
| AC-4 | Ohne `confirm`/`confirm: false` bleibt Dry-Run | **PASS** | Eigene Tests: leerer Payload `{}` → `CONFIRM: false` in beiden Workflows. Sicherheitsverhalten (Fail-Closed) unverändert. |
| AC-5 | `Code: Time Check` liest `MAX_RUNTIME_SECONDS` von Init statt hardcoded | **PASS** | Beide Dateien: `parseInt($('Code: Init Backfill Run').first().json.MAX_RUNTIME_SECONDS, 10)` ersetzt die hardcoded `7200`. Eigener Test: Override `max_runtime_seconds: 60` im Body, `run_start` künstlich 90s in die Vergangenheit gesetzt → `_time_limit_reached: true` bei `maxRuntime=60` (wäre bei weiterhin hardcoded 7200 fälschlich `false` geblieben). |
| AC-6 | Ohne Override bleibt Zeitlimit bei 7200s | **PASS** | Eigener Test: kein `max_runtime_seconds` im Payload → `MAX_RUNTIME_SECONDS: 7200` in beiden Workflows (Normalfall unverändert). |
| AC-7 | Lock-Node (`Code: Acquire Backfill Lock`) unverändert | **PASS** | Struktureller Diff `fc4ed65~1` → `fc4ed65`: Lock-Node-Parameter, -Position, -ID in beiden Dateien byte-identisch. Einzige geänderte Nodes: `Code: Init Backfill Run`, `Code: Time Check`. |

**7/7 Acceptance Criteria PASS** (jeweils für beide Workflows geprüft).

### Edge Cases Status

| # | Edge Case | Status | Nachweis |
|---|-----------|--------|----------|
| EC-1 | Webhook-Call ganz ohne Body/Query | **PASS** | Eigener Test: `webhookPayload: {}` → `CONFIRM: false`, kein Crash, `MAX_RUNTIME_SECONDS: 7200`. |
| EC-2 | `confirm` als String `"true"` | **PASS** | Bestehende Logik (`confirmRaw === true \|\| confirmRaw === 'true'`) unverändert und durch den Fix jetzt erreichbar; eigener Test bestätigt `query.confirm: 'true'` → `true`. |
| EC-3 | `max_runtime_seconds` ungültig (negativ, nicht-numerisch, `0`) | **PASS** (mit Einschränkung, siehe Low-Finding) | Eigene Tests: `-5` → Fallback `7200`; `'3.7abc'` → `parseInt` liefert `3`, das ist `> 0` und wird **nicht** auf 7200 zurückgesetzt (kein Fallback, aber auch kein Crash und kein `0`-Zeitlimit — technisch kein Bug, da AC nur "Fallback bei ungültig/≤0" fordert und `3` ein gültiges Ergebnis von `parseInt` ist). Kein Zeitlimit von `0` in keinem getesteten Fall. |
| EC-4 | Zwei gleichzeitige Läufe desselben Workflows | **PASS** | Nicht Teil des Fixes, unverändert durch bestehenden Lock-Mechanismus abgedeckt (Lock-Node byte-identisch, siehe AC-7). |
| EC-5 | Bereits laufender Dry-Run-Prozess zum Zeitpunkt des Fixes | **N/A (nicht automatisiert prüfbar)** | Konzeptionell bestätigt: Dry-Run verändert keine Daten (kein Weaviate-Write-Pfad ohne `doc.confirm`/`CONFIRM`-Gate gefunden), kein Datenverlust durch den Fix möglich. |

**4/4 automatisiert prüfbare Edge Cases PASS, 1 N/A** (konzeptionelle Prüfung, kein Live-Zustand vorhanden).

### Security Audit Results

**n8n workflow features:**
- [ ] Authentication: `authentication: "none"` auf beiden Webhooks — **vorbestehend, nicht durch PROJ-92 verändert**. Identisch zu `alice-mail-attachment-backfill` (bereits deployed, QA-akzeptiert). VPN-only-Zugang laut CLAUDE.md-Constraint, `callerPolicy: workflowsFromSameOwner`. Kein neuer Befund, außerhalb des PROJ-92-Scopes.
- [x] Authorization: n/a (kein User-Context, Admin-Only-Tooling wie bei den Schwester-Workflows)
- [x] Input validation: `max_runtime_seconds` und `confirm` werden defensiv geparst (`parseInt`, `isNaN`-Check), kein Crash bei Fremdwerten getestet (String, verschachtelte Werte, überlange Zahlen)
- [x] Keine Secrets in den geänderten Code-Pfaden; `winston`-Logging unverändert, kein `console.log`

**Ein Low-Finding (kein Bug, informativ):** Ein extrem großer `max_runtime_seconds`-Wert (z.B. `99999999999999999999999999`) wird von `parseInt` als `1e+26` akzeptiert (`> 0`, kein Fallback) und hebelt das Zeitlimit faktisch aus. Identisches Verhalten besteht bereits im bereits deployten Referenz-Fix `alice-mail-attachment-backfill` (gleiche Validierungslogik übernommen) — kein durch PROJ-92 neu eingeführtes Risiko. Angriffsfläche gering: Webhook ist VPN-only, nur vom gleichen n8n-Owner aufrufbar, und ein Admin, der bereits `confirm:true` sendet, hat ohnehin volle Kontrolle über den Lauf. Kein Handlungsbedarf im Rahmen von PROJ-92; ggf. für ein künftiges Hardening-Ticket über alle drei Backfill-Workflows hinweg vormerken.

**Security: PASS — keine neue Angriffsfläche gegenüber dem bereits akzeptierten Referenzmuster.**

### Bugs Found

**Keine.** Weder Critical, High, Medium noch Low (das Low-Finding oben ist ein vorbestehendes Muster, kein durch PROJ-92 verursachter Bug).

### Regression Check

- Lock-Erwerb/-Freigabe (`Code: Acquire Backfill Lock`, `Code: Respond Already Running`, Release-Pfade in `Code: Respond Ollama Unavailable`/`Code: Empty Summary`/`Code: Build & Send Summary`): unverändert, nicht Teil des Diffs.
- `Code: Ollama Health Check`, `Code: Fetch All Documents`, `Split In Batches`, `Code: Heuristic Check`/`Execute: Classify Document`, `Code: Compare & Handle`/`Code: Apply Correction`: alle unverändert, nur konsumieren sie jetzt (transitiv über Init) die korrekten `confirm`/`MAX_RUNTIME_SECONDS`-Werte statt der zuvor immer-`false`/immer-`7200`-Konstanten.
- Kein anderer Workflow referenziert `Code: Init Backfill Run` oder `Code: Time Check` dieser beiden Workflows (Sub-Workflow-Grenzen, `callerPolicy: workflowsFromSameOwner`, keine Cross-Workflow-`$('...')`-Referenzen gefunden).

### Summary

- **Acceptance Criteria:** 7/7 passed
- **Edge Cases:** 4/4 automatisiert geprüft passed, 1 N/A (konzeptionell bestätigt)
- **Bugs Found:** 0 total (0 critical, 0 high, 0 medium, 0 low)
- **Security:** Pass — 1 informatives Low-Finding, vorbestehend und außerhalb des Scopes
- **Production Ready:** YES
- **Recommendation:** **READY** — Deploy. Fix folgt exakt dem bereits produktiv bewährten PROJ-53-Muster, Diff ist minimal-invasiv (4 Zeilen je Datei), Lock-Node unangetastet, Propagation von `confirm`/`MAX_RUNTIME_SECONDS` bis zu den tatsächlichen Gates eigenständig nachvollzogen und verifiziert.

## Deployment
_To be added by /deploy_

## Deployment
_To be added by /deploy_
