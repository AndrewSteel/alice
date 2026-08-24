# PROJ-94: DMS Path-Worker Zeitlimit

## Status: Approved
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

### E) Workflow Architecture

PROJ-94 hat keine UI-Komponente. Es erweitert den bestehenden `alice-dms-path-worker`-Workflow um einen Zeitlimit-Check innerhalb der bereits existierenden Datei-Verarbeitungsschleife — kein neuer Workflow, kein neuer Trigger.

**Einordnung in den bestehenden Ablauf:**

Der Path-Worker läuft aktuell pro Datei in `Loop: Files` durch: `Code: Renew Path Lock` (erneuert den Ordner-Lock) → `IF: Lock Still Held` (bricht bei Lock-Verlust über `Code: Self-Abort on Lock Loss` ab, sonst geht's weiter zur nächsten Datei). Genau an dieser Stelle — parallel zur bestehenden Lock-Prüfung — kommt die neue Zeitlimit-Prüfung hinzu.

**Ablauf:**

1. **Zeit-Check pro Datei-Durchlauf:** Zusätzlich zur bestehenden Lock-Erneuerung wird geprüft, wie viel Zeit seit `alice:dms:scanner:stats:folder:<folder_id>:run_start` (existierender Redis-Wert, wird bereits zu Lauf-Beginn gesetzt) vergangen ist.
2. **Unter 2 Stunden:** Verarbeitung läuft wie bisher unverändert weiter.
3. **2 Stunden oder mehr erreicht:** Die Schleife bricht kontrolliert ab — wie beim bestehenden Lock-Verlust-Fall, nur mit einem eigenen Abbruchgrund ("Zeitlimit erreicht" statt "Lock verloren"). Der Ordner-Lock wird sauber freigegeben, der bisherige Fortschritt (Anzahl verarbeiteter Dateien) wird geloggt, die Zusammenfassung am Ende des Laufs zeigt den Abbruchgrund.
4. **Nächster stündlicher Lauf:** Der Dispatcher (`alice-dms-scanner`) startet wie gewohnt zur nächsten vollen Stunde einen neuen Path-Worker-Lauf für denselben Ordner (sofern der Ordner-Lock zu dem Zeitpunkt frei ist — was er nach dem sauberen Abbruch ist). Noch nicht gescannte Dateien werden dabei automatisch erneut erfasst, da der Scanner unbekannte/neue Dateien bei jedem Durchlauf ohnehin neu bewertet.

**Integrationen:** Nur Redis (Lesen des bereits vorhandenen Zeitstempels) — keine neuen externen Abhängigkeiten.

**Fehlerverhalten:** Ist Redis beim Zeit-Check nicht erreichbar, läuft der Worker unverändert weiter (fail-open) — die bestehende Lock-Verlust-Prüfung bleibt die primäre Absicherung gegen hängende Läufe bei Redis-Ausfall, das Zeitlimit ist eine zusätzliche, aber nicht die einzige Schutzschicht.

### Datenmodell (fachlich)

Kein neues Datenbankschema, kein neuer Redis-Key. Der bereits existierende Wert `alice:dms:scanner:stats:folder:<folder_id>:run_start` (gesetzt beim Laufstart, ein Wert pro aktuell laufendem Ordner-Scan) wird zusätzlich für die Zeitlimit-Berechnung gelesen.

### Tech-Entscheidungen (Begründung)

- **Wiederverwendung des bestehenden `run_start`-Zeitstempels statt eines neuen Keys:** Der Wert existiert bereits pro Ordner-Lauf und wird bereits beim Laufstart gesetzt — ein zweiter, redundanter Zeitstempel wäre unnötiger State.
- **Zeitlimit-Check an derselben Stelle wie die bestehende Lock-Erneuerung (pro Datei in der Schleife) statt eines separaten globalen Checks:** Konsistent mit dem etablierten Muster aus `alice-dms-processor` (Zeit-Check zwischen Verarbeitungseinheiten, nicht mitten in einer einzelnen Dateiverarbeitung) und nutzt die bereits vorhandene Schleifenstruktur, statt eine parallele zu bauen.
- **Fail-open bei Redis-Ausfall:** Ein Redis-Problem soll nicht zusätzlich einen laufenden Scan abwürgen — das würde das Robustheitsproblem, das PROJ-94 lösen soll, durch ein neues ersetzen. Die bestehende Lock-Verlust-Prüfung deckt den Fall "Redis nicht erreichbar" bereits ab (der Lock kann dann ohnehin nicht erneuert werden).
- **2 Stunden als Grenzwert statt 4 Stunden (wie `alice-dms-processor`):** Der Path-Worker läuft stündlich, ein 4h-Limit würde also bis zu drei verpasste reguläre Trigger-Zeitpunkte bedeuten, bevor überhaupt abgebrochen wird — 2h hält die Verzögerung für betroffene Ordner kleiner und reduziert die Restwahrscheinlichkeit einer Überschneidung mit den nightly-Läufen um 02:00 Uhr bei sehr spät gestarteten Scans.

### Dependencies (Pakete)

Keine neuen Pakete — `redis` ist in n8n Code-Nodes bereits erlaubt und wird im Path-Worker bereits für die Lock-Verwaltung genutzt.

### Implementation Notes (Backend)

**Umgesetzt in:** `workflows/alice-dms-path-worker.json` (einziger geänderter Workflow, keine weiteren Dateien).

**Geänderte Nodes:**

- **`Code: Renew Path Lock`** (erweitert): Liest nach der bestehenden Lock-Erneuerung — auf derselben, bereits offenen Redis-Verbindung — `alice:dms:scanner:stats:folder:<folder_id>:run_start`, berechnet `elapsedSeconds` und setzt `_time_limit_reached = elapsedSeconds >= RUN_TIME_LIMIT_SECONDS` (7200). Der Zeit-Check liegt in einem eigenen inneren `try/catch`: jeder Fehler beim Lesen (und ein fehlender/0-Wert von `run_start`) lässt `_time_limit_reached = false` und loggt fail-open. Die bestehende Lock-Logik (`_lock_still_held`, fail-closed) ist unverändert. Neue Ausgabefelder: `_time_limit_reached`, `_elapsed_seconds`.
- **`IF: Time Limit Reached`** (neu, `n8n-nodes-base.if`, id `proj94-if-time-limit-reached-v1`): sitzt zwischen dem True-Zweig von `IF: Lock Still Held` und `Code: Hash + Size`. True → `Code: Abort on Time Limit`, False → `Code: Hash + Size` (bisheriger Pfad, unverändert).
- **`Code: Abort on Time Limit`** (neu, `n8n-nodes-base.code`, id `proj94-code-abort-on-time-limit-v1`): liest die bisherigen Fortschritts-Counter (`scanned_files`, `new_files`, `skipped_files`, `lifecycle_files`), loggt sie per winston als ein JSON-Event `alice-dms-path-worker-time-limit-abort` mit `reason: 'time_limit_reached'` und `elapsed_seconds`, und gibt `{_time_limit_reached: true, _elapsed_seconds}` aus. Verlässt die Schleife (keine Rückkante zu `Loop: Files`) und führt direkt zu `Code: Path Worker Summary`.
- **`Code: Path Worker Summary`** (erweitert): übernimmt `_time_limit_reached` aus dem Input und ergänzt die Ausgabe um `_time_limit_reached` (bool) und `abort_reason` (`'time_limit_reached'` oder `null`). Alle bisherigen Felder bleiben unverändert; im Normalfall ist `abort_reason: null`.
- **`Sticky: Overview`** (erweitert): neuer Abschnitt "Run Time Limit (PROJ-94)".

**Abweichungen vom Tech Design (explizit):**

1. **Kein separater `Code: Time Check`-Node.** Das Tech Design nennt `alice-dms-processor`s `Code: Time Check` als Muster; dort ist der Zeit-Check aber ohnehin mit der Lock-Erneuerung in *einem* Node kombiniert. Da der Path-Worker in `Code: Renew Path Lock` pro Datei bereits eine Redis-Verbindung öffnet, wurde der Zeit-Check dort eingehängt statt in einem zusätzlichen Node mit zweiter Verbindung — spart pro Datei einen Node und einen Redis-Connect, ohne die Semantik zu ändern. Die Routing-Entscheidung liegt weiterhin in einem eigenen IF-Node (`IF: Time Limit Reached`), analog zum Processor.
2. **Der Abbruch-Node gibt den Lock nicht selbst frei.** Er leitet stattdessen auf `Code: Path Worker Summary` → `Code: Release Path Lock` (bestehender, ownership-geprüfter Release-Pfad). Damit sind Lock-Freigabe, Statistik-Ermittlung und `MQTT: Publish Path Stats` bei Zeitlimit-Abbruch identisch zum regulären Lauf-Ende — AC "Lock sauber freigegeben" ist erfüllt, ohne die Release-Lua-Logik zu duplizieren. Der Processor nutzt hierfür einen separaten `Code: Final Log (Time)`-Node mit eigenem Release; das wurde bewusst *nicht* kopiert, weil der Path-Worker bereits einen gemeinsamen Abschlusspfad hat.
3. **Nicht analog zu `Code: Self-Abort on Lock Loss` per `throw` abgebrochen.** Der Lock-Loss-Node wirft absichtlich eine Exception und gibt den Lock *nicht* frei (die Ownership liegt bereits bei einem anderen Worker). Beim Zeitlimit ist der Lock noch in eigenem Besitz und muss freigegeben werden — deshalb ein sauberer Datenpfad statt `throw`. Die Execution endet damit als "success" (nicht als Fehler), was für einen geplanten Abbruch korrekt ist.
4. **Zusätzliches Feld `_elapsed_seconds`** im Loop-Item (im Tech Design nicht erwähnt) — nur damit der Abbruch-Log die tatsächliche Laufzeit ausweisen kann.

**Verifikation (strukturell + Verhaltenssimulation, kein Deploy):**

- JSON valide; Round-Trip-Formatierung identisch zum Original (Diff enthält ausschließlich die o.g. Änderungen).
- Alle `connections`-Ziele und alle `$('Node')`-Referenzen lösen auf; keine doppelten Node-Namen/-IDs; keine Canvas-Positions-Überlappungen; MQTT-Credentials unverändert vorhanden.
- Alle Code-Nodes bestehen `node --check`; kein `console.log` (winston überall, gemäß CLAUDE.md).
- 18 Verhaltenschecks gegen die geänderten Code-Nodes mit gefaktem Redis/winston: unter Limit → weiter (Item-Passthrough unverändert), exakt 7200s → Abbruch (`>=`), fehlender `run_start` → fail-open, Redis-`GET`-Fehler → fail-open bei erhaltenem Lock-Urteil, kompletter Redis-Ausfall → Lock-Loss-Pfad greift (kein Zeit-Abbruch), Abbruch-Log enthält den korrekten Fortschritt, Abbruch überlebt Redis-Ausfall, Summary setzt `abort_reason` nur im Abbruchfall.

**Nicht verifizierbar ohne Deploy/n8n-Instanz:** Validierung via n8n-MCP-Tools (als Subagent nicht verfügbar), echtes Laufzeitverhalten in n8n (Item-Pairing im `splitInBatches`-Loop, tatsächliche Redis-Werte) sowie ein realer >2h-Lauf. Empfehlung für `/qa`: Zeitlimit temporär niedrig setzen oder `run_start` manuell in die Vergangenheit schreiben, um den Abbruchpfad live zu prüfen.

## QA Test Results

**Tested:** 2026-08-24
**Commit under test:** `fd057bd` (feat(PROJ-94): Add 2h per-folder time limit to DMS path-worker)
**Scope:** `workflows/alice-dms-path-worker.json`
**Tester:** QA Engineer (AI)

### Testmethode

Kein Deploy und kein Live-n8n/Redis in dieser Umgebung — gleiches Vorgehen wie in den PROJ-53-QA-Runden:

1. **Statische Graph-Analyse:** `connections`-Objekt eigenständig traversiert (nicht der Implementer-Beschreibung vertraut), Node-Parameter direkt aus der JSON gelesen.
2. **Struktureller Alt/Neu-Vergleich:** `fd057bd~1` vs. `fd057bd` auf Node-Ebene (Parameter, Credentials, typeVersion, Position, Connections) statt nur Text-Diff.
3. **Isolierte Re-Execution:** Alle 16 Code-Nodes extrahiert und der **echte** Node-Code gegen ein gefaktes `redis`/`winston` und injizierte `$input`/`$()`-Globals ausgeführt (`harness.js`, 46 Checks).
4. **Loop-Traversal-Simulation:** Modell des `splitInBatches`-Loops inkl. aller Rückkanten, um Abbruch-Semantik und Flag-Leaks zu prüfen (`loopsim.js`, 18 Checks, davon 2000 randomisierte Läufe).

**Ergebnis: 64/64 Checks bestanden, 0 Bugs.**

### Acceptance Criteria Status

| # | Acceptance Criterion | Status | Nachweis |
|---|---------------------|--------|----------|
| AC-1 | Zeit-Check in `Loop: Files` gegen bestehenden `run_start`-Key, >2h | **PASS** | `Code: Renew Path Lock` liest `alice:dms:scanner:stats:folder:${trigger.id}:run_start`, rechnet `elapsedSeconds`, setzt `_time_limit_reached = elapsedSeconds >= 7200`. Läuft pro Datei (Loop-Batchgröße = 1). Kein neuer Redis-Key. |
| AC-2 | Bei Zeitlimit kontrollierter Abbruch, keine weiteren Dateien | **PASS** | `IF: Time Limit Reached` (true) → `Code: Abort on Time Limit` → `Code: Path Worker Summary`. Verifiziert: **keine** Rückkante zu `Loop: Files`. L2: 100 Dateien, Limit bei #20 → exakt 20 verarbeitet, 80 nicht begonnen. |
| AC-3 | Ordner-Lock wird beim Abbruch sauber freigegeben | **PASS** | Abbruchpfad führt über den bestehenden ownership-geprüften `Code: Release Path Lock` (Lua-CAS). T12: `_lock_released === true`. Inbound-Kanten von `Code: Release Path Lock` = `Set: No Files Stats` + `Code: Path Worker Summary` — der Abbruch erreicht ihn nachweislich. |
| AC-4 | Fortschritt wird beim Abbruch geloggt | **PASS** | `Code: Abort on Time Limit` liest `scanned_files`/`new_files`/`skipped_files`/`lifecycle_files` und loggt sie als winston-JSON-Event `alice-dms-path-worker-time-limit-abort` mit `reason` + `elapsed_seconds`. T8: alle Zähler korrekt im Log. T8b: Log erfolgt auch bei komplettem Redis-Ausfall (Zähler dann 0). |
| AC-5 | Kein Datenverlust — Restdateien beim nächsten Lauf | **PASS** | `Code: Scan Single Folder` ist ein zustandsloser Full-Rescan; Dedup läuft ausschließlich über `Code: Lifecycle Check` (Redis `path_to_hash`/`processed`/`queued_files`). Nicht begonnene Dateien hinterlassen keinerlei State → werden nächste Stunde neu erfasst. Lock ist nach AC-3 frei. |
| AC-6 | Lauf innerhalb des Limits verhält sich exakt wie bisher | **PASS** | Siehe „Regressionsanalyse Normalfall" unten. Item-Passthrough unverändert (T1), keine zusätzliche Redis-Verbindung, Renewal-Reihenfolge/TTL unverändert. |
| AC-7 | Zeitlimit gilt pro Ordner-Lauf, nicht global | **PASS** | Der gelesene Key ist auf `${trigger.id}` skopiert, `trigger` stammt aus `$('Execute Workflow Trigger')` — pro Sub-Workflow-Execution eigener Ordner. Kein globaler Key (im Gegensatz zu `alice-dms-processor`s `alice:dms:run:start_time`). Parallele Worker teilen keinen State. |

**7/7 Acceptance Criteria PASS.**

### Threshold-Prüfung (>= vs >)

Der Code implementiert `elapsedSeconds >= 7200` — einen **harten 2h-Deckel**.

- T2: exakt 7200s → Abbruch. T3: 7199s → kein Abbruch. L3/L4 bestätigen an der Loop-Grenze.
- Der Spec-Prosatext sagt „mehr als 2 Stunden", AC-Checkliste und Edge Cases behandeln es als Obergrenze („2 Stunden oder mehr erreicht" im Tech Design, Schritt 3).
- **Bewertung: konsistent mit der erklärten Absicht.** Das Tech Design formuliert explizit „2 Stunden oder mehr erreicht", und der referenzierte Präzedenzfall `alice-dms-processor` (`Code: Time Check`) nutzt ebenfalls `elapsed >= 7200`. Die Differenz zwischen `>` und `>=` beträgt hier ohnehin genau eine Sekunde bei einem Check-Intervall von einer Datei. Kein Bug.

### Edge Cases Status

| # | Edge Case | Status | Nachweis |
|---|-----------|--------|----------|
| EC-1 | Lauf endet regulär kurz vor dem Limit | **PASS** | L4: 7199s über alle Dateien → `normal_done`, `abort_reason: null`. |
| EC-2 | Limit mitten in einer Datei erreicht → aktuelle Datei fertig, nächste nicht mehr | **PASS** | Check sitzt in `Code: Renew Path Lock` **vor** `Code: Hash + Size`, also zwischen den Dateien. `Wait: 5s Stability` und die MQTT-Publishes der laufenden Datei liegen hinter dem Check und werden nicht unterbrochen. Batchgröße 1 → Granularität exakt eine Datei. |
| EC-3 | Sehr kleiner Ordner, nie 2h | **PASS** | L1: 50 Dateien bei 120s → identisches Verhalten, `abort_reason: null`. |
| EC-4 | Redis beim Zeit-Check nicht erreichbar → fail-open | **PASS** | Siehe „Fail-Open-Verifikation" unten. |
| EC-5 | Zwei parallele Ordner-Läufe unterschiedlicher Größe | **PASS** | Siehe AC-7: keine geteilten Keys, kein geteilter State zwischen Executions. |

### Fail-Open-Verifikation (Schwerpunkt)

Der Zeit-Check liegt in einem **inneren** `try/catch` innerhalb des bestehenden äußeren `try`. Getestet wurde gezielt der Fehlerfall *nur beim Zeit-Check*, nicht beim Lock-Renewal:

| Szenario | `_lock_still_held` | `_time_limit_reached` | `_elapsed_seconds` | Ergebnis |
|----------|-------------------|----------------------|--------------------|----------|
| Redis `GET run_start` wirft, Renewal OK (T4) | `true` (unverändert) | `false` | `0` | **PASS** — Lauf läuft weiter, Lock-Urteil unbeeinflusst, fail-open per winston geloggt |
| `run_start` fehlt komplett / `null` (T5) | `true` | `false` | `0` | **PASS** — kein Crash, kein riesiger Elapsed-Wert |
| `run_start` = `""`, `"abc"`, `"0"`, `"null"`, `"NaN"` (T5b) | `true` | `false` | `0` | **PASS** — `parseInt(x \|\| '0')` + `if (startMs > 0)` fängt alle Varianten ab (`NaN > 0` ist `false`) |
| `run_start` in der Zukunft / Clock-Skew (T5c) | `true` | `false` | negativ | **PASS** — kein Abbruch |
| Kompletter Redis-Ausfall, `connect()` wirft (T6) | `false` | `false` | `0` | **PASS** — greift der bestehende Lock-Loss-Pfad (fail-closed), **kein** falscher Zeit-Abbruch |

Der kritische Punkt „`_elapsed_seconds` wird bei fehlendem `run_start` nicht als riesige Zahl fehlberechnet" ist durch das `if (startMs > 0)`-Guard abgesichert: bei fehlendem Key bleibt `elapsedSeconds` auf dem Initialwert `0`, statt `Date.now() - 0` (≈ 56 Jahre) zu rechnen. Das war die gefährlichste denkbare Fehlerquelle und ist korrekt behandelt.

**Anmerkung (positiv):** Der Path-Worker ist hier robuster als der referenzierte `alice-dms-processor`, dessen `Code: Time Check` den `GET` **nicht** in ein try/catch kapselt.

### Abbruchpfad — Graph-Trace (selbst verifiziert)

```
Loop: Files (out1, batch=1)
  └─> Code: Renew Path Lock            [_lock_still_held, _time_limit_reached, _elapsed_seconds]
        └─> IF: Lock Still Held
              ├─ false ─> Code: Self-Abort on Lock Loss   (throw, KEIN Release — unverändert)
              └─ true  ─> IF: Time Limit Reached
                            ├─ true  ─> Code: Abort on Time Limit
                            │             └─> Code: Path Worker Summary
                            └─ false ─> Code: Hash + Size  (bisheriger Pfad, unverändert)

Code: Path Worker Summary ─> Code: Release Path Lock ─> MQTT: Publish Path Stats ─> End: Path Worker Done
Loop: Files (out0, done)  ─> Code: Path Worker Summary   (Normalfall)
```

- `Code: Abort on Time Limit` hat **genau eine** ausgehende Kante (→ Summary) und **keine** Rückkante zu `Loop: Files` → Schleife wird verlassen, weitere Dateien werden nicht verarbeitet.
- Lock-Freigabe erfolgt über den gemeinsamen, ownership-geprüften Release-Pfad. Abweichung 2 des Implementers ist damit sachlich korrekt und erfüllt AC-3, ohne die Release-Lua-Logik zu duplizieren.
- Reihenfolge Lock-Check → Zeit-Check ist richtig: bei Lock-Verlust darf **nicht** freigegeben werden (Ownership liegt woanders), bei Zeitlimit **muss** freigegeben werden. T7/L6 bestätigen die Priorisierung.

### Regression: Lock-Loss-Pfad

- `Code: Self-Abort on Lock Loss` ist **byte-identisch** zu `fd057bd~1` (struktureller Node-Vergleich: nicht in der Liste geänderter Parameter).
- `IF: Lock Still Held`s false-Kante ist unverändert (`→ Code: Self-Abort on Lock Loss`); nur die **true**-Kante wurde von `Code: Hash + Size` auf `IF: Time Limit Reached` umgehängt.
- T11: wirft weiterhin, Message unverändert, winston-`error`-Log unverändert, gibt den Lock weiterhin nicht frei.
- L7: Lock-Verlust bei Datei #5 unter Zeitlimit → Verhalten wie vor der Änderung.

### Regression: Normalfall (Lauf < 2h)

- **Keine zusätzliche Redis-Verbindung.** Der `GET` läuft auf dem bereits offenen Client aus dem Lock-Renewal — pro Datei weiterhin genau ein `createClient`/`connect`/`quit`.
- **Renewal-Timing/TTL unverändert.** Der `eval(RENEW_SCRIPT, ...)` läuft **vor** dem neuen `GET`; `LOCK_TTL_MS = 180000` und das Lua-Skript sind unverändert. Der zusätzliche `GET` verlängert also nicht das Fenster zwischen Renewals vor dem Renewal, sondern liegt danach.
- **Kosten:** ein `GET` pro Datei — im Vergleich zum bereits pro Datei laufenden `EVAL` + Datei-Hashing (`readFileSync` + SHA-256) + `Wait: 5s Stability` vernachlässigbar.
- **Item-Passthrough unverändert** (T1): `...$input.first().json` bleibt vollständig erhalten, es kommen nur die drei neuen Meta-Felder dazu. Downstream-Nodes lesen ausschließlich `file_path`/`file_size`/`file_hash`/`_lifecycle_action` etc. und werden davon nicht berührt.
- **Upstream unangetastet:** Scanning, Hashing, Lifecycle-Detection, Stability Check, OCR-Check und MQTT-Routing haben keine Parameteränderung (siehe Diff-Analyse).

### Stats/Logging-Korrektheit & Stale-State-Prüfung

`Code: Path Worker Summary` liest `($input.first().json || {})._time_limit_reached === true`. Da der Node **zwei** Inbound-Kanten hat (Loop-done und Abbruch), wurde gezielt auf Flag-Leak über Loop-Iterationen geprüft:

- **Abbruchpfad (T9):** `_time_limit_reached: true`, `abort_reason: 'time_limit_reached'`, Zähler und `runtime_seconds` korrekt aus Redis. Der Input ist dabei **ausschließlich** das eine Abort-Item (`summaryInput.length === 1`), nicht der akkumulierte Batch.
- **Normalfall (T10):** Loop-done-Items tragen `_time_limit_reached: false` (durch die `{...item}`-Spreads durchgereicht) → `abort_reason: null`. Korrekt.
- **Feld fehlt ganz (T10b):** `=== true` liefert `false` → `abort_reason: null`. Kein `undefined`-Leak.
- **Leak-Nachweis (L8):** Der **einzige** Produzent von `_time_limit_reached: true` ist `Code: Renew Path Lock`, und genau dieses Item wird von `IF: Time Limit Reached` sofort aus der Schleife geroutet — es kann daher nie in den akkumulierten Done-Batch gelangen. 2000 randomisierte Läufe (1–30 Dateien, zufällige Elapsed-Werte 0–15000s): **0 Leaks**, kein akkumuliertes Item mit `true`, kein falsches `abort_reason`.
- **Durchreichung ins MQTT-Payload (T12):** `Code: Release Path Lock` spreadet `...$input.first().json`, `MQTT: Publish Path Stats` sendet `JSON.stringify($json)` → `abort_reason` und `_time_limit_reached` landen korrekt auf `alice/dms/scanner/path_stats`.
- **Rückwärtskompatibilität:** Beide Felder sind rein additiv. Kein In-Repo-Konsument von `alice/dms/scanner/path_stats` gefunden (nur der Producer selbst) → kein Breaking Change.

### Statische Validierung

| Check | Ergebnis |
|-------|----------|
| JSON valide | PASS |
| Doppelte Node-Namen / IDs | PASS — keine |
| Alle `connections`-Quellen und -Ziele auflösbar | PASS — alle 38 Nodes |
| Alle `$('Node')`-Referenzen auflösbar | PASS — alle |
| Dangling Outputs (Output ohne Ziel, kein legitimer Terminaltyp) | PASS — keine (`End: Path Worker Done` = noOp, `Code: Self-Abort on Lock Loss` = terminal-by-throw, `Sticky: Overview` = Notiz) |
| Unerreichbare Nodes (kein Inbound, kein Trigger) | PASS — keine |
| Alle Code-Nodes `node --check` | PASS — 16/16 |
| `console.log` (CLAUDE.md: nur winston) | PASS — 0 Treffer, beide neuen Nodes nutzen winston |
| MQTT-Credentials vorhanden & unverändert | PASS — 7 Nodes, alle `mqtt-alice` (`Kqy6cn7hyDDXrBA0`), identisch zu `fd057bd~1` |
| Canvas-Positionsüberlappungen | PASS — keine |
| Top-Level-Felder (`active`, `settings`, `callerPolicy`) | PASS — unverändert |

### Diff-Scoping (`git diff fd057bd~1 fd057bd`)

Struktureller Node-Vergleich (nicht nur Text-Diff):

- **Hinzugefügt:** `IF: Time Limit Reached`, `Code: Abort on Time Limit` — sonst nichts.
- **Entfernt:** nichts.
- **Parameter geändert:** `Code: Renew Path Lock`, `Code: Path Worker Summary`, `Sticky: Overview` — sonst nichts.
- **Credentials / typeVersion / Position / IDs bestehender Nodes:** alle unverändert.
- **Connections geändert:** nur `IF: Lock Still Held` (true-Kante umgehängt) + die zwei neuen Nodes.
- **Nicht berührt:** `Code: Scan Single Folder`, `Code: Hash + Size`, `Code: Lifecycle Check`, `Code: Stability Check`, `Code: OCR Check`, `Code: Set Priority`, `Switch: Route by Type`, alle MQTT-Publish-Nodes, `Code: Mark Queued`, `Code: Release Path Lock`, `Set: No Files Stats`.

Diff ist exakt so eng geschnitten wie beschrieben.

### Security Audit Results

**Angriffsfläche: unverändert / trivial.** Bewertung explizit:

- [x] **Keine neue Exposition:** kein neuer Trigger, kein Webhook, kein HTTP-Endpunkt, kein neuer Port. Der Workflow bleibt ein Sub-Workflow mit `callerPolicy: workflowsFromSameOwner`, ausschließlich vom `alice-dms-scanner`-Dispatcher aufrufbar.
- [x] **Keine neuen Inputs:** der neue Code liest einen **bereits existierenden**, vom Workflow selbst geschriebenen Redis-Key. Keine benutzerkontrollierten Daten fließen in die Zeitlogik.
- [x] **Keine Injection-Fläche:** Der Redis-Key wird aus `trigger.id` interpoliert — dieselbe, bereits vorhandene Quelle wie in allen anderen Stats-Keys; `id` stammt aus `alice.dms_watched_folders` (DB-PK, kein Freitext). Kein neues Lua-Skript, keine Änderung an den bestehenden CAS-Skripten. Nur lesende `GET`-Operationen wurden ergänzt.
- [x] **Keine Secrets in Logs:** Das neue winston-Event enthält `folder_id`, `path`, Zähler und `elapsed_seconds` — keine Credentials, keine Tokens, kein `REDIS_PASSWORD`. `path` ist ein NAS-Pfad und wurde in diesem Workflow bereits vorher geloggt.
- [x] **Keine Rechte-/Auth-Änderung:** keine DB-Berechtigungen, keine RLS-Policies, keine JWT-Logik betroffen.
- [x] **Lock-Integrität gewahrt:** Die Freigabe läuft weiterhin über das ownership-geprüfte Lua-CAS. Ein Zeitlimit-Abbruch kann **nicht** den Lock eines fremden Workers löschen. Der Lock-Loss-Pfad gibt weiterhin bewusst **nicht** frei.
- [x] **DoS/Ressourcen:** Die Änderung *reduziert* das Risiko (begrenzt Lock-Haltedauer und Laufzeit). Ein `GET` pro Datei zusätzlich ist vernachlässigbar.

**Ein denkbarer Missbrauchsvektor** wäre, `run_start` in Redis zu manipulieren, um Läufe vorzeitig abzubrechen. Bewertung: **kein neues Risiko** — wer Schreibzugriff auf Redis hat, kann bereits direkt die Lock-Keys manipulieren (mächtiger). Redis ist nicht extern exponiert (VPN-only, passwortgeschützt). Worst Case ist ein sauberer Abbruch ohne Datenverlust.

**Security: PASS — keine neue Angriffsfläche.**

### Bugs Found

**Keine.** Weder Critical, High, Medium noch Low.

### Beobachtungen ohne Bug-Status (nicht behebungspflichtig)

1. **Asymmetrie im No-Files-Zweig (kosmetisch, vorbestehend):** `Set: No Files Stats` setzt weder `abort_reason` noch `_time_limit_reached` — das MQTT-Stats-Payload hat für diesen Zweig also eine leicht andere Feldmenge. Diese Asymmetrie besteht bereits vor PROJ-94 (dort fehlen auch schon `_no_files` und `lifecycle_files`) und ist hier folgenlos: ein Lauf ohne Dateien kann per Definition kein Zeitlimit erreichen. Kein Handlungsbedarf im Rahmen von PROJ-94.
2. **Nicht ohne Deploy prüfbar:** Item-Pairing-Verhalten von `splitInBatches` in echtem n8n, reale Redis-Werte und ein echter >2h-Lauf. Das Loop-Modell in `loopsim.js` bildet die dokumentierte Semantik ab und deckt den relevanten Leak-Fall ab, ersetzt aber keinen Live-Test.
3. **Empfehlung für `/deploy` (Smoke-Test):** `alice:dms:scanner:stats:folder:<id>:run_start` bei einem laufenden Worker manuell auf `Date.now() - 7300000` setzen und prüfen, dass (a) der Lauf bei der nächsten Datei abbricht, (b) `alice:dms:scanner:lock:folder:<id>` verschwindet, (c) auf `alice/dms/scanner/path_stats` ein Payload mit `abort_reason: "time_limit_reached"` erscheint, (d) der nächste stündliche Lauf denselben Ordner wieder aufgreift.

### Summary

- **Acceptance Criteria:** 7/7 passed
- **Edge Cases:** 5/5 passed
- **Automatisierte Checks:** 64/64 passed (46 Node-Re-Execution + 18 Loop-Traversal inkl. 2000 randomisierter Läufe)
- **Bugs Found:** 0 total (0 critical, 0 high, 0 medium, 0 low)
- **Security:** Pass — keine neue Angriffsfläche
- **Production Ready:** YES
- **Recommendation:** **READY** — Deploy. Die Implementierung entspricht Spec und Tech Design; alle vier dokumentierten Abweichungen sind sachlich begründet und korrekt umgesetzt (insbesondere die Lock-Freigabe über den gemeinsamen Release-Pfad statt eines duplizierten Release). Fail-open-Verhalten ist an allen geprüften Fehlerstellen korrekt, inklusive des kritischen Falls „fehlender `run_start`" (kein fehlberechneter Riesen-Elapsed-Wert). Lock-Loss-Pfad ist byte-identisch unverändert. Beim Deploy den obigen Smoke-Test fahren.

## Deployment
_To be added by /deploy_
