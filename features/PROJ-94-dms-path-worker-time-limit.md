# PROJ-94: DMS Path-Worker Zeitlimit

## Status: In Progress
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
_To be added by /qa_

## Deployment
_To be added by /deploy_
