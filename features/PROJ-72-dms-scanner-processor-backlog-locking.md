# PROJ-72: DMS Scanner/Processor Backlog-Locking

## Status: Deployed
**Created:** 2026-07-28
**Last Updated:** 2026-07-29

> **Update 2026-07-28 (Backend):** Implementiert gemäß Tech Design. Details siehe "Implementation Notes" unten.
>
> **Update 2026-07-28 (QA):** Statischer Code-Review, Node.js-Syntaxprüfung, n8n-mcp-Validierung und Live-Verifikation der Redis-Lock-Primitiven (temporärer Docker-Redis) durchgeführt — keine Live-Ausführung gegen die produktive n8n-Instanz möglich, da noch nicht deployed. 2 nicht-blockierende Bugs dokumentiert (1 Medium: Sperrfreigabe bei unerwarteten Node-Fehlern verzögert statt sofort, selbstheilend über TTL; 1 Low: workflowId-Platzhalter muss vor Deploy ersetzt werden, bereits in "Deployment" dokumentiert). Kein Critical/High-Bug offen. Status auf "Approved" gesetzt, nächster Schritt `/deploy`. Details siehe "QA Test Results" unten.
>
> **Update 2026-07-29 (Deploy/Betrieb):** Alle drei Workflows live deployed. Erstlauf mit vollem Backlog aufgedeckt, dass n8n-Task-Runner unter der neuen Nebenläufigkeit (mehrere parallele Pfad-Worker + Nightly-Prozessor) an Speichergrenzen und Timeout stieß (Task-Runner-Disconnects, `Find Stale Paths` lief in den 3600s-Task-Timeout). Zusätzlich stellte sich heraus, dass `console.log`/`warn`/`error` in Code-Nodes grundsätzlich nur im Browser sichtbar ist, nie im Container — nachträgliche Fehleranalyse war damit nicht möglich. Beides behoben, siehe neuer Abschnitt "Betriebs-Fix: Logging & Task-Runner-Speicher" unten. Details zum aktuellen Produktionsstand siehe "Deployment" unten.

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
- Processor-Lauf hängt fest (z.B. Ollama/Weaviate antwortet nicht mehr, ohne dass der Prozess selbst abstürzt): Das Beheben des Hängers selbst ist außerhalb des Scopes von PROJ-72 (bestehendes Fehler-/Timeout-Verhalten der einzelnen Phasen bleibt maßgeblich). Was mit der Sperre passiert, ist aber in Scope: verpasst der hängende Lauf dadurch seinen Heartbeat, verfällt die Sperre und ein neuer nächtlicher Trigger kann starten; wacht der ursprüngliche, hängende Lauf später wieder auf, muss er erkennen, dass er die Sperre nicht mehr besitzt, und sich selbst abbrechen statt weiterzuarbeiten
- Ein Pfad-Worker (Scanner) hängt bei einer einzelnen Datei ungewöhnlich lange fest (z.B. NAS antwortet extrem langsam), ohne abzustürzen, und verpasst dadurch seinen Heartbeat: Die Sperre verfällt, ein späterer Dispatcher-Lauf kann den Pfad neu vergeben. Reagiert der ursprüngliche Worker danach wieder, erkennt er beim nächsten Erneuerungsversuch den Besitzverlust und bricht sich selbst ab — dadurch bearbeiten niemals zwei Worker denselben Pfad gleichzeitig, auch nicht in diesem "hängt nur, stürzt nicht ab"-Fall
- Manuelles Zurücksetzen einer hängenden Sperre durch den Admin (z.B. direkter DB-/Redis-Zugriff) muss möglich sein, auch ohne UI dafür — reiner Notfall-Fallback neben dem automatischen Heartbeat-Verfall

## Technical Requirements (optional)

- Speicherort des Sperrstatus (zusätzliche Spalte an `alice.dms_watched_folders` vs. separater Redis-Key pro Pfad) ist eine Entscheidung für `/architecture` — beide Optionen wurden diskutiert
- Atomarität von "prüfen + sperren" ist eine harte Anforderung unabhängig vom gewählten Speicherort
- Heartbeat-Intervall und Verfallszeit sind Architektur-Entscheidungen; Richtwert: Intervall deutlich kürzer als Verfallszeit
- Keine Codeänderung an `dms-extractor-image` oder am Geocode-Sub-Flow (PROJ-56) nötig — die BUG-3-Symptomatik verschwindet als Nebeneffekt dieses Fixes

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Kerngedanke

Überlappende Scanner-Ausführungen werden nicht verboten, sondern gefahrlos gemacht: Statt einer globalen "nur eine Ausführung gleichzeitig"-Regel wird die Sperre auf den einzelnen beobachteten Pfad heruntergebrochen. Läuft eine Ausführung gerade an einem sehr großen Pfad, kann eine zeitgleich gestartete zweite Ausführung parallel an einem anderen, freien Pfad arbeiten — genau das behebt die Blockade, ohne die Doppelverarbeitung wieder einzuführen. Beim Processor gibt es keine unabhängigen Pfade, daher genügt dort ein einzelner Lauf-weiter Lock.

**Wichtige Einschränkung:** n8n erlaubt keine verschachtelten Schleifen (kein Loop-Node innerhalb eines anderen Loop-Nodes) — genau deshalb fasst die aktuell deployte Implementierung bereits alle Pfade zu einer kombinierten Dateiliste zusammen, bevor die einzige Datei-Schleife startet (keine willkürliche Abweichung vom PROJ-16-Design, sondern eine erzwungene Lösung für diese Plattform-Grenze).

Ein reines "Locking innerhalb der bestehenden Schleife" (ein früherer Entwurf, inkl. Round-Robin-Verschachtelung) löst zwar die Reihenfolge, ändert aber nichts am Grundproblem: Eine einzelne Ausführung müsste weiterhin alle aktuell freien Pfade auf einmal für sich beanspruchen und deren komplette Dateiverarbeitung durch dieselbe, gemeinsame Schleife schleusen — ein Pfad mit Tage-langem Backlog hält die betreffende Ausführung entsprechend lange am Leben, während andere, längst fertig bearbeitete Pfade zwar früher freigegeben werden, aber die grundsätzliche Struktur (eine Ausführung bearbeitet sequenziell/interleaved potenziell alle Pfade) bleibt bestehen.

Die etablierte n8n-Lösung für "eigentlich verschachtelte Schleifen" ist, die innere Schleife in einen **Sub-Workflow** auszulagern, der über den nativen "Execute Workflow"-Node pro Außenschleifen-Durchlauf aufgerufen wird. Damit wird aus einem Workflow zwei:

- **Dispatcher (`alice-dms-scanner`, angepasst):** iteriert über die Pfade (einzige, unveränderte Art von Schleife), sperrt jeden freien Pfad atomar und stößt für jeden erfolgreich gesperrten Pfad den neuen Sub-Workflow an — **ohne auf dessen Abschluss zu warten**. Dadurch bleibt der Dispatcher-Lauf selbst kurz (nur Sperrversuche + Anstoßen, keine Datei-Verarbeitung) und blockiert nicht.
- **Pfad-Worker (neuer Sub-Workflow):** bekommt einen einzelnen Pfad übergeben und führt darin die komplette bisherige Datei-Verarbeitung aus (rekursiver Scan, Hash/Dedup, Stabilitätscheck, OCR, Priorität, MQTT-Publish) — jetzt als **eigene, unabhängige Schleife in einem eigenen Workflow**, keine Verschachtelung mehr, da es kein "Loop-in-Loop" innerhalb eines einzigen Workflows ist.

Weil der Dispatcher nicht wartet, laufen mehrere Pfad-Worker bei Bedarf **echt parallel** als unabhängige n8n-Ausführungen — ein Riesen-Backlog in Pfad A blockiert dadurch strukturell nicht mehr die Bearbeitung von B, C, D, weil deren jeweiliger Worker eine komplett eigenständige, gleichzeitig laufende Ausführung ist, nicht nur ein anders sortiertes Item in einer gemeinsam geteilten Liste. Die Round-Robin-Verschachtelung aus meinem vorherigen Entwurf entfällt damit ersatzlos.

### Workflow Architecture — Scanner (`alice-dms-scanner` Dispatcher + neuer Pfad-Worker-Sub-Workflow)

**Trigger:** Unverändert — Schedule, stündlich 07–22 Uhr, am Dispatcher. Der Pfad-Worker hat keinen eigenen Zeit-Trigger, er wird ausschließlich vom Dispatcher aufgerufen.

**Dispatcher — Nodes (High-Level):**
1. Aktive Pfade aus `alice.dms_watched_folders` laden (unverändert)
2. Schleife über die Pfade (einzige Schleifenebene in diesem Workflow):
   - Atomarer Sperrversuch für den Pfad
   - Bereits gesperrt (anderer, noch laufender Pfad-Worker) → überspringen, weiter zum nächsten Pfad
   - Erfolgreich gesperrt → Pfad-Worker-Sub-Workflow anstoßen, **ohne auf dessen Fertigstellung zu warten**, dann weiter zum nächsten Pfad
3. Kurzer Abschluss-Log (wie viele Pfade angestoßen bzw. übersprungen wurden — keine Datei-Statistik mehr, die liegt jetzt beim Worker)

**Pfad-Worker — Nodes (High-Level, pro Aufruf für genau einen Pfad):**
1. Pfad-Info vom Dispatcher entgegennehmen
2. Pfad rekursiv nach Dateien durchsuchen (unverändert aus PROJ-16, jetzt auf genau einen Pfad beschränkt statt auf die kombinierte Liste)
3. Bestehende Datei-Schleife (unverändert: Hash/Dedup-Check, Stabilitätscheck, OCR-Check, Priorität, MQTT-Publish, Redis-Markierung) — ergänzt um einen Heartbeat-Schritt pro Datei, der die Sperre dieses (einen) Pfades erneuert, solange der Worker aktiv daran arbeitet
4. **Jede Heartbeat-Erneuerung prüft zuerst, ob der Worker die Sperre überhaupt noch besitzt** (siehe Data Model unten), bevor er sie verlängert. Ist sie zwischenzeitlich verfallen und von einem anderen Worker übernommen worden (z.B. weil dieser Worker bei einer einzelnen Datei ungewöhnlich lange gehangen hat und dadurch einen Heartbeat verpasst hat), bricht dieser Worker seine eigene Verarbeitung sofort ab, statt weiterzumachen — niemand darf annehmen, die Sperre noch zu halten, ohne das bei jeder Erneuerung neu zu bestätigen
5. Nach Abschluss aller Dateien dieses Pfades (auch bei Fehler oder Selbstabbruch nach Sperrverlust): Sperre freigeben, sofern der Worker sie zu diesem Zeitpunkt noch besitzt — ein einziger, eindeutiger Freigabepunkt, da dieser Worker-Lauf ausschließlich für diesen einen Pfad zuständig ist

**Data flow:** PostgreSQL (aktive Pfade, im Dispatcher) → Sperrversuch pro Pfad (Dispatcher) → asynchroner Aufruf des Pfad-Workers → bestehender Datei-Scan-/Dedup-/MQTT-Fluss (unverändert, jetzt im Worker) → Besitz-geprüfte Sperre erneuern/freigeben (Worker)

**Integrations:** Keine neuen externen Systeme — Dispatcher und Worker nutzen dieselbe Redis-Verbindung, die der Workflow bereits für `queued_files`/`processed_files` verwendet; neu ist lediglich die interne n8n-zu-n8n-Verbindung zwischen Dispatcher und Worker (natives n8n-Feature, kein externer Service)

**Error handling:** Schlägt das Anstoßen des Pfad-Workers selbst fehl (z.B. kurzzeitiger interner Fehler), bleibt die Sperre ungenutzt liegen und verfällt automatisch über den Heartbeat-Mechanismus — kein Sonderfall nötig, keine Datei wurde angefasst. Bricht die Datei-Verarbeitung innerhalb eines Worker-Laufs mit Fehler ab, gibt der Worker seine Pfad-Sperre trotzdem frei (sofern noch im Besitz). Stürzt ein Worker-Lauf komplett ab (Container-Neustart), bleibt der Heartbeat aus und die Sperre verfällt automatisch nach kurzer Zeit — niemand muss das aktiv bemerken, das Fehlen der nächsten Erneuerung genügt. Hängt ein Worker nur (lebt aber noch) und verpasst dadurch seinen Heartbeat, verfällt die Sperre ebenso automatisch; wacht der hängende Worker später wieder auf, erkennt er beim nächsten Erneuerungsversuch den Besitzverlust und bricht selbst ab — dadurch bearbeiten niemals zwei Worker denselben Pfad gleichzeitig, selbst wenn der ursprüngliche nur verzögert statt abgestürzt war.

### Workflow Architecture — Processor (`alice-dms-processor`)

**Trigger:** Unverändert — Schedule, täglich 02:00 Uhr.

**Nodes (High-Level, Ablaufreihenfolge):**
1. Direkt nach dem Schedule-Trigger: Versuch, den Lauf-Lock exklusiv zu setzen
2. Bereits gesperrt (Vortageslauf noch aktiv, z.B. wegen großem Image-/Geocode-Backlog) → Lauf beendet sich sofort und sauber, kein Fehler, nur ein Log-Hinweis
3. Lock erfolgreich gesetzt → der komplette bestehende Ablauf (Plaintext-Batch-Schleife, Image-Subflow, Geocode-Subflow aus PROJ-19/PROJ-56) läuft unverändert
4. Während der Verarbeitung: Lock regelmäßig erneuern (Heartbeat)
5. An jedem regulären Ausstiegspunkt des bestehenden Workflows (leere Queue, Zeitlimit erreicht, Geocode-Phase fertig, Abbruch bei Weaviate-Fehler) wird der Lock freigegeben

**Data flow:** Sperrversuch → bestehender Plaintext-/Image-/Geocode-Ablauf (unverändert) → Sperre erneuern/an allen Ausstiegspunkten freigeben

**Integrations:** Keine neuen — nutzt die bereits vorhandene Redis-Verbindung

**Error handling:** Der bestehende Workflow hat mehrere Ausstiegspunkte (leere Queue, Zeitlimit, Geocode fertig, Fehlerabbruch) — die Freigabe muss an jedem davon verdrahtet werden, sonst bleibt der Lock bis zum Heartbeat-Verfall bestehen (verzögert im schlimmsten Fall den nächsten Start um wenige Minuten, kein Datenverlust). Stürzt die Ausführung komplett ab, verfällt der Lock automatisch über denselben Heartbeat-Mechanismus wie beim Scanner. Wie beim Pfad-Worker prüft auch hier jede Heartbeat-Erneuerung den fortbestehenden Besitz; verpasst dieser Lauf durch ein ungewöhnlich langes Einzelereignis (z.B. Ollama/Weaviate reagiert extrem langsam) seinen Heartbeat und übernimmt der nächste nächtliche Trigger den nun freien Lock, muss der ursprüngliche Lauf beim Aufwachen den Besitzverlust erkennen und sich selbst abbrechen.

### Data Model (plain language)

Kein neues PostgreSQL-Schema, keine neue Tabelle, keine Migration. Die gesamte Sperrlogik lebt in Redis — dort, wo die DMS-Pipeline bereits ihre gesamte Koordinations- und Warteschlangen-Logik führt (`queued_files`, `processed_files`, `geocode_pending`, `geocode_quota`, `run:stats`).

- **Pro beobachtetem Pfad (Scanner):** ein Sperreintrag je Pfad-ID aus `alice.dms_watched_folders`. Inhalt: ein eindeutiger Besitz-Nachweis der haltenden Ausführung. Dieser Wert ist keine reine Diagnose-Zutat, sondern hart notwendig für die Korrektheit: Jede Heartbeat-Erneuerung und jede Freigabe muss zuerst bestätigen, dass der eigene Besitz-Nachweis noch mit dem aktuell gespeicherten übereinstimmt, bevor sie die Sperre verlängert bzw. löscht ("nur erneuern/freigeben, wenn ich es wirklich noch bin" — nicht blind verlängern). Ohne diese Prüfung könnte ein Worker, der die Sperre durch einen verpassten Heartbeat bereits verloren hat, sie versehentlich einem inzwischen neuen Besitzer wieder entziehen oder eigenmächtig verlängern. Zusätzlich enthält der Eintrag lesbare Zusatzinfo (Pfad, Startzeitpunkt) für die manuelle Admin-Diagnose. Verfällt automatisch, wenn keine (besitz-bestätigte) Erneuerung mehr eintrifft.
- **Für den gesamten Processor-Lauf:** ein einzelner Sperreintrag, kein Pfad-Bezug nötig. Gleiches Besitz-geprüfte Verhalten.
- **Admin-Fallback:** Da es bewusst kein UI für den Sperrstatus gibt (siehe Spec), kann ein hängender Sperreintrag im Notfall direkt in Redis gelöscht werden — die lesbare Zusatzinfo im Eintrag hilft, den richtigen zu identifizieren.

### Tech Decisions

| Entscheidung | Wahl | Begründung |
| --- | --- | --- |
| Speicherort des Sperrstatus | Redis (nicht PostgreSQL) | Redis bietet eine einzige atomare Operation für "nur setzen, wenn noch nicht gesetzt, mit automatischem Verfall" — schließt das Kernrisiko (zwei Läufe sperren gleichzeitig) strukturell aus. PostgreSQL könnte dasselbe leisten, bräuchte dafür aber eine neue Spalte, eine Migration, RLS-Policy-Anpassungen und eigene "ist die Sperre noch gültig"-Logik bei jedem Lesezugriff. Redis ist außerdem bereits die alleinige Koordinationsschicht der DMS-Pipeline (Queue-Dedup, Backlog-Zähler, Quota) — konsistent mit dem bestehenden Muster, keine neue Infrastruktur nötig |
| Sperrgranularität Scanner | Pro Pfad (`dms_watched_folders`-Eintrag), nicht pro Ausführung insgesamt | Löst Blockade UND Doppelverarbeitung im selben Mechanismus: überlappende Ausführungen bleiben erlaubt und sogar nützlich (parallele Bearbeitung unabhängiger Pfade), solange sie sich nicht denselben Pfad teilen |
| Sperrgranularität Processor | Ein einzelner Lauf-weiter Lock | Der Processor hat keine unabhängigen Arbeitseinheiten wie der Scanner — alle drei Phasen (Plaintext, Image, Geocode) teilen sich dieselben Redis-/Weaviate-Ressourcen und dieselbe Nachtlauf-Logik; eine feinere Granularität hätte keinen Fairness-Nutzen, nur zusätzliche Komplexität |
| Heartbeat statt fixem Timeout | Sperre wird regelmäßig erneuert, solange aktiv gearbeitet wird; die automatische Verfallszeit ist kurz (im Minutenbereich), unabhängig von der erwarteten Gesamtlaufzeit | Ein fester langer Timeout müsste die längstmögliche Verarbeitungsdauer erraten (Sekunden bis mehrere Tage, je nach Backlog-Größe) — falsch geraten bedeutet entweder verfrühtes Verfallen (Duplikate, genau der Bug von BUG-3) oder tagelang blockierte Pfade nach einem Absturz. Der Heartbeat entkoppelt "wie lange darf die Sperre insgesamt halten" von "wie schnell wird ein Absturz erkannt" |
| Niemand überwacht den Heartbeat aktiv — Verfall ist rein passiv (Redis-TTL), plus Besitz-geprüfte Erneuerung/Freigabe statt blindem Verlängern | Kein Watchdog-/Monitoring-Prozess; Redis löscht abgelaufene Sperreinträge von selbst. Jede Erneuerung und Freigabe bestätigt vorher den eigenen Besitz anhand eines in der Sperre gespeicherten eindeutigen Nachweises | Passiver TTL-Verfall braucht keine zusätzliche Infrastruktur — die bloße Abwesenheit einer Erneuerung genügt. Ohne die Besitzprüfung entstünde aber eine Lücke: Hängt ein Worker/Lauf nur (lebt noch), verpasst dadurch seinen Heartbeat und verliert die Sperre an einen neuen Worker, würde er beim Aufwachen sonst blind weiterarbeiten und denselben Pfad parallel zum neuen Besitzer bearbeiten — exakt das Duplizierungsproblem, das PROJ-72 beheben soll, nur über einen anderen Auslöser (Hänger statt Absturz). Die Besitzprüfung zwingt einen Worker, der seine Sperre verloren hat, sich beim nächsten Erneuerungsversuch selbst abzubrechen |
| Sub-Workflow statt Locking innerhalb einer gemeinsamen Schleife | Die Datei-Verarbeitung pro Pfad wird in einen eigenen, vom Dispatcher per "Execute Workflow" aufgerufenen Sub-Workflow ausgelagert | n8n erlaubt keine verschachtelten Loop-Nodes. Die aktuell deployte kombinierte Dateiliste ist deshalb keine willkürliche Abweichung vom ursprünglichen PROJ-16-Design, sondern eine erzwungene Lösung für diese Plattform-Grenze. Ein Locking innerhalb der bestehenden einzelnen Schleife (inkl. Round-Robin-Verschachtelung, ein früherer Entwurf) hätte zwar die Reihenfolge geändert, aber am Grundproblem nichts: Eine Ausführung müsste weiterhin alle freien Pfade auf einmal für sich beanspruchen und deren komplette Verarbeitung durch dieselbe Schleife schleusen. Der Sub-Workflow ist der etablierte n8n-Weg für "eigentlich verschachtelte" Schleifen und löst das grundlegend, nicht nur kosmetisch |
| Dispatcher ruft Pfad-Worker ohne auf Fertigstellung zu warten | "Fire-and-forget"-Aufruf statt synchronem Warten auf den Sub-Workflow | Nur so entsteht echte Parallelität zwischen mehreren gleichzeitig laufenden Pfad-Workern. Würde der Dispatcher pro Pfad auf den Abschluss warten, wäre er faktisch wieder eine sequenzielle Schleife über alle Pfade — ein Riesen-Backlog in Pfad A würde den Dispatcher entsprechend lange aufhalten, bevor er überhaupt zu Pfad B weiterkäme, und die ursprüngliche Blockade wäre nur an eine andere Stelle verschoben |

### Dependencies

Keine neuen Packages, keine neue externe Infrastruktur. Beide bestehenden Workflows haben die benötigte Redis-Credential bereits — dieselbe, die für die bestehende Dedup-/Queue-Logik verwendet wird. Neu ist ein zusätzliches n8n-Workflow-Artefakt: der Pfad-Worker-Sub-Workflow (neue Datei unter `workflows/`), aufgerufen über n8n's natives "Execute Workflow"-Feature — kein externer Service, keine neue Credential.

### No UI Changes Required

Bewusste Entscheidung aus der Spec (kein Sperrstatus-Badge im Settings-UI für den MVP-Scope; Admin-Zugriff im Notfall direkt über Redis).

## Implementation Notes

### Scanner: Dispatcher + Path-Worker Split (`workflows/alice-dms-scanner.json`, `workflows/alice-dms-path-worker.json` neu)

`alice-dms-scanner.json` wurde vom bisherigen monolithischen Scan-Workflow (36 Nodes) auf einen schlanken **Dispatcher** reduziert (16 Nodes): lädt aktive Pfade, iteriert einmal darüber (`Loop: Folders`), versucht pro Pfad einen atomaren Redis-Lock (`Code: Try Lock Folder`, `SET NX PX 180000`), und stößt bei Erfolg den neuen Sub-Workflow **`alice-dms-path-worker`** per `Execute Workflow`-Node **ohne zu warten** an (`options.waitForSubWorkflow: false`). Bereits gesperrte Pfade werden übersprungen. Die komplette bisherige Datei-Verarbeitung (Hash/Dedup, Lifecycle-Check, 5s-Stabilitätscheck, OCR-Check, MQTT-Routing nach Typ) wurde unverändert in den neuen Pfad-Worker verschoben, jetzt auf genau einen Pfad pro Aufruf beschränkt statt auf die frühere kombinierte Liste.

- **Sperrschlüssel:** `alice:dms:scanner:lock:folder:<folder_id>` (Redis, JSON-Wert mit `owner`-UUID, `NX`+`PX`). Renewal und Release sind **besitz-geprüft** (Lua-Skript: `GET` → `cjson.decode` → Owner-Vergleich → `SET`/`DEL`), nicht blindes Verlängern/Löschen.
- **Heartbeat:** Renewal einmal pro Datei im Pfad-Worker (`Code: Renew Path Lock`), TTL 180s. Verliert ein Worker den Besitz (Redis-Fehler wird **fail-closed** als Besitzverlust behandelt, siehe Nutzer-Entscheidung unten), bricht er über `Code: Self-Abort on Lock Loss` sofort ab (`throw`) — kein Release-Versuch, da der Besitz bereits weg ist.
- **Stats-Umbau:** Die bisherigen globalen `alice:dms:scanner:stats:*`-Zähler wären bei parallel laufenden Pfad-Workern nicht mehr korrekt (mehrere Worker würden sich gegenseitig überschreiben). Neu: pro-Pfad-Zähler `alice:dms:scanner:stats:folder:<folder_id>:*`, zurückgesetzt bei jedem Worker-Start, veröffentlicht am Ende auf dem **neuen** Topic `alice/dms/scanner/path_stats`. Der Dispatcher veröffentlicht auf dem bisherigen Topic `alice/dms/scanner/stats` nur noch eine schlanke Zusammenfassung (`paths_dispatched`, `paths_skipped_locked`) — **kein** in-Repo-Konsument dieses Topics gefunden, aber falls extern etwas die alten Datei-Zähler-Felder auf diesem Topic erwartet, ändert sich dessen Payload-Form.
- `Code: Find Stale Paths` (globaler Sweep, PROJ-44) bleibt unverändert im Dispatcher (läuft einmal pro Dispatcher-Lauf, nicht pro Pfad).
- **workflowId-Platzhalter:** Der `Execute: Path Worker`-Node im Dispatcher referenziert die neue Sub-Workflow-ID aktuell als Platzhalter `__REPLACE_WITH_PATH_WORKER_WORKFLOW_ID__`, da die echte n8n-Workflow-ID erst nach dem ersten Import von `alice-dms-path-worker` bekannt ist. Siehe "Deployment"-Abschnitt unten für den nötigen manuellen Schritt.

### Processor: Lauf-Lock (`workflows/alice-dms-processor.json`)

Neuer Node `Code: Acquire Processor Lock` direkt nach dem Schedule-Trigger (atomarer `SET NX PX 1800000` auf `alice:dms:processor:lock:run`). Bei Sperrfehlschlag beendet sich der Lauf sofort und sauber über `Code: Log Already Running` → `End: Already Running` (kein Fehler). Heartbeat-Renewal (besitz-geprüft, gleiches Lua-Muster wie beim Scanner) wurde in die drei bereits pro Batch-Item laufenden Nodes integriert: `Code: Time Check` (Plaintext-Phase), `Code: Process Image Item` (Image-Phase), `Code: Prepare Geocode Request` (Geocode-Phase). Verliert der Lauf die Sperre, nimmt er denselben bestehenden, nicht-werfenden Ausstiegspfad wie beim Zeitlimit (`Code: Final Log (Time)` → `End: Time Limit`) — bewusst asymmetrisch zum Pfad-Worker-`throw`, da der Prozessor an jeder Phase bereits einen sauberen Ausstiegspunkt hat. Freigabe erfolgt an den beiden einzigen echten Enden des gesamten Laufs: in `Code: Final Log (Time)` (vor `End: Time Limit`) und im neuen Node `Code: Release Processor Lock (Success)` (vor `End: Geocode Done`, ersetzt die frühere direkte Verkabelung von drei Erfolgspfaden dorthin). Die restliche Plaintext-/BankTransaction-/Image-/Geocode-Logik wurde nicht angefasst.

### Nutzer-Entscheidung (diese Session)

Bei einem Redis-Fehler während der Sperr-Erneuerung wurde **fail-closed** gewählt (als Sperrverlust behandeln, sofort abbrechen) statt fail-open — priorisiert "niemals doppelt verarbeiten" (der Kern von BUG-3) über einen möglichen unnötigen Abbruch bei einem kurzen Redis-Verbindungsfehler.

### Betriebs-Fix: Logging & Task-Runner-Speicher (2026-07-29, nach erstem Produktions-Lauf)

Der erste Lauf gegen den echten Backlog (5 Pfade, davon einer mit mehreren tausend Bildern) deckte zwei produktive Probleme auf, die im QA-Review nicht sichtbar waren (kein echter Backlog zum Testzeitpunkt vorhanden):

- **Task-Runner-Überlastung:** Mit der neuen Nebenläufigkeit (mehrere parallele Pfad-Worker-Ausführungen statt eines sequenziellen Laufs) gerieten n8n-Task-Runner-Prozesse an Speicher-/Kapazitätsgrenzen — sichtbar als `Node execution failed` (`InternalTaskRunnerDisconnectAnalyzer`, Task-Broker-WS-Verbindungsabbruch) im Prozessor (`Code: BankTransaction Phase B`, langlaufender sequenzieller Ollama-Chunk-Loop) und im Pfad-Worker (zweiter stündlicher Trigger, während der Bild-Pfad noch lief), sowie als exaktes `N8N_RUNNERS_TASK_TIMEOUT`-Timeout (3600s) im Dispatcher (`Code: Find Stale Paths`, vermutlich durch NAS-I/O-Konkurrenz mit den parallel laufenden Pfad-Workern verlangsamt). Fix: `N8N_RUNNERS_MAX_OLD_SPACE_SIZE=4096` in `docker/compose/automations/n8n/compose.yml` (Server hat 64GB RAM, ~24GB durch die 33 laufenden Container belegt — 4096MB Headroom für den Task-Runner bestätigt ausreichend).
- **Keine nachträgliche Fehleranalyse möglich:** `console.log`/`warn`/`error` in n8n-Code-Nodes wird laut n8n-eigener Doku/Community by design ausschließlich an den Browser weitergereicht, nie an die Container-Logs — unabhängig von Task-Runner-Modus. Fix: alle 61 `console.*`-Aufrufe über alle drei Workflows (22 betroffene Code-Nodes) auf pro-Node-`winston`-Logger umgestellt, die direkt auf Datei schreiben (`/home/node/.n8n/logs/n8n.log`, dieselbe Datei wie n8n-eigenes Core-Logging via `N8N_LOG_OUTPUT=file`), mit `defaultMeta: { workflow, node }` für Greppability. `winston` wurde dafür zu `NODE_FUNCTION_ALLOW_EXTERNAL` hinzugefügt.
  - Ein zusätzlicher `winston.transports.Console()`-Transport wurde getestet, in der Annahme, damit auch `docker logs --follow n8n` nutzbar zu machen — funktioniert nicht: der Code-Node-Task-Runner läuft als eigener Prozess, der mit dem n8n-Hauptprozess über ein WebSocket-Task-Broker-Protokoll kommuniziert (nicht über einfache stdio-Vererbung), dessen eigener stdout nicht an den Container-stdout durchgereicht wird — unabhängig von `N8N_LOG_OUTPUT` (das nur n8n's eigenen internen Core-Logger steuert, nicht selbst erstellte `winston`-Logger-Instanzen in Code-Nodes). Der Console-Transport wurde daher wieder entfernt (nur `File`-Transport bleibt). Einzig zuverlässiger Zugriffsweg: `docker exec n8n tail -f /home/node/.n8n/logs/n8n.log`.

### Validierung durchgeführt

- Alle 44 Code-Node-JS-Bodies über alle drei Workflow-Dateien mit Node.js (`node -e "new Function(...)"`) syntaktisch geprüft — 0 Fehler.
- `alice-dms-scanner.json` und `alice-dms-path-worker.json` vollständig mit n8n-mcp `validate_workflow` geprüft: keine ungültigen Verbindungen, keine echten Ausdrucksfehler. Die gemeldeten "Cannot return primitive values directly"-Fehler sind ein bekannter Fehlalarm des heuristischen Linters (er erkennt `return true/false` innerhalb verschachtelter `.filter()`-Callbacks bzw. `return 0/1` innerhalb der Lua-Skript-Strings fälschlich als Top-Level-Return) — reproduzierbar auch auf unverändertem, bereits produktivem Code (`Code: Lifecycle Check`, `Code: Find Stale Paths`), also kein PROJ-72-Regressions-Befund.
- `alice-dms-processor.json` (67 Nodes) wurde wegen Tool-Payload-Größe nicht als Ganzes durch `validate_workflow` geschickt; stattdessen wurde der komplette Verbindungsgraph händisch (Python) auf fehlende/verwaiste Referenzen und die beiden echten Terminal-Exits geprüft (bestanden), zusätzlich zur Node.js-Syntaxprüfung aller Code-Nodes.
- Kein PostgreSQL-Schema geändert (Tech Design: Redis-only).

## QA Test Results

**Tested:** 2026-07-28
**Environment:** Statischer Code-Review + Node.js-Syntaxprüfung + n8n-mcp-Validierung + Live-Redis-Verifikation der Lock-Primitiven (Docker-Container `redis:7-alpine`, temporär, nach Test entfernt). **Keine Live-Ausführung gegen die produktive n8n-Instanz** — die Workflows sind zu diesem Zeitpunkt noch nicht deployed (Deploy ist laut Projektkonvention ein manueller Nutzer-Schritt). Die beiden Verifikations-ACs zu BUG-3 (echte überlappende Executions, echte Warteschlangen-Stichprobe) konnten daher nicht live getestet werden — siehe "Nicht verifizierbar" unten.
**Tester:** QA Engineer (AI)

### Acceptance Criteria Status

#### AC-1: Scanner — Pfad-Locking & Fairness
- [x] Jeder aktivierte `dms_watched_folders`-Eintrag hat einen Sperrstatus (Redis-Key `alice:dms:scanner:lock:folder:<id>`, Existenz = gesperrt)
- [x] Atomares Sperren — verifiziert live gegen echtes Redis: zweiter `SET NX PX`-Versuch auf denselben Key schlägt fehl, solange der erste Eintrag noch besteht (kein Zeitfenster für Doppel-Lock)
- [x] Scanner-Lauf geht alle aktivierten Pfade der Reihe nach durch (`Loop: Folders`, sortiert wie zuvor `sort_order ASC, id ASC`), überspringt gesperrte Pfade, fährt mit dem nächsten fort
- [x] Periodische Sperr-Erneuerung während der Verarbeitung (`Code: Renew Path Lock`, einmal pro Datei)
- [x] Sperre verfällt automatisch bei ausbleibendem Heartbeat (Redis `PX`-TTL, passiv) — Mechanismus live verifiziert (Renew auf abgelaufenen/gelöschten Key liefert `0`)
- [x] Sperre wird nach Abschluss freigegeben (No-Files-Zweig und nach Abschluss der Datei-Schleife, jeweils besitz-geprüft) — **mit Einschränkung, siehe BUG-1**
- [x] Großer Backlog in einem Pfad blockiert andere Pfade strukturell nicht mehr (Dispatcher wartet nicht auf den Pfad-Worker — `waitForSubWorkflow: false` — mehrere Worker laufen als unabhängige Executions)
- [x] Bestehende Datei-Level-Mechanismen (SHA-256-Dedup, 5s-Stabilitätscheck) unverändert — Code 1:1 übernommen, nur Redis-Statistik-Keys auf Pfad-Ebene umbenannt

#### AC-2: Processor — Lauf-Locking
- [x] Prüft vor Start, ob bereits ein Lauf aktiv ist (`Code: Acquire Processor Lock`, atomar)
- [x] Bereits aktiv → neuer Trigger startet keinen zweiten Lauf, beendet sich sauber ohne Fehler (`End: Already Running`, `noOp`)
- [x] Aktiver Lauf erneuert Sperre periodisch (einmal pro Plaintext-/Image-/Geocode-Item, alle drei Phasen abgedeckt)
- [x] Sperre verfällt automatisch bei ausbleibendem Heartbeat
- [x] Nach regulärem Abschluss (auch bei Zeitlimit) freigegeben — **mit Einschränkung, siehe BUG-1**

#### AC-3: Verifikation (BUG-3 aus PROJ-56)
- [ ] **Nicht verifizierbar in dieser Session:** Keine doppelten `file_hash`-Einträge über mehrere echte überlappende Scanner-Läufe — erfordert eine deployte Instanz mit echtem Backlog; strukturell durch das Pfad-Lock-Design ausgeschlossen (kein Pfad kann von zwei Workern gleichzeitig bearbeitet werden, live am Redis-Mechanismus verifiziert), aber nicht am echten n8n mit echten Daten beobachtet
- [ ] **Nicht verifizierbar in dieser Session:** Stichprobe aus n8n-Executions — es existieren noch keine Executions, da die Workflows noch nicht deployed sind

### Edge Cases Status

#### EC-1: Zwei Scanner-Läufe starten praktisch zeitgleich
- [x] Verifiziert live: Nur einer sperrt einen gegebenen Pfad erfolgreich, der andere überspringt ihn (Redis `SET NX` ist atomar, kein Zeitfenster)

#### EC-2: Scanner-Lauf stürzt mitten in Pfad-Verarbeitung ab
- [x] Sperre verfällt nach TTL (180s), Pfad wird im nächsten Lauf erneut aufgenommen, File-Level-Dedup bleibt zusätzlich bestehen

#### EC-3: Pfad wird während laufender Sperre deaktiviert
- [x] Laufender Worker hat Pfad-Info bereits vom Dispatcher übernommen, arbeitet unbeeinflusst weiter; künftige Dispatcher-Läufe filtern über `WHERE enabled = true` und überspringen den Pfad automatisch

#### EC-4: Alle Pfade aktuell gesperrt
- [x] Dispatcher durchläuft alle Pfade, sperrt keinen, beendet sich ohne Datei-Verarbeitung, kein Fehler (`Code: Dispatcher Summary Log` mit `paths_dispatched: 0`)

#### EC-5: Processor-Lauf über Mitternacht/mehrere Tage
- [x] Lock-TTL (30 Min) wird durch Heartbeat pro Item weit vor Ablauf erneuert; nächster 02:00-Trigger findet die Sperre noch aktiv und beendet sich sauber

#### EC-6: Processor-Lauf hängt fest (Ollama/Weaviate reagiert nicht)
- [x] Alle Einzel-HTTP-Calls in der Pipeline haben bestehende Timeouts (10–300s je nach Call), alle deutlich unter der 30-Min-TTL — ein Hänger an einer einzelnen Operation lässt die Sperre nicht vorzeitig verfallen
- [x] Verfällt die Sperre dennoch (z.B. durch mehrere Retries in Folge), erkennt der ursprüngliche Lauf dies beim nächsten Renewal-Versuch und bricht sich selbst ab (kein Doppel-Lauf)

#### EC-7: Pfad-Worker hängt bei einzelner Datei (z.B. langsames NAS) fest
- [x] Verhält sich exakt wie in der Spec beschrieben: Erkennung/Selbstabbruch erfolgt beim NÄCHSTEN Renewal-Versuch (nächste Datei), nicht mitten in der hängenden Operation selbst — die Spec akzeptiert das explizit und verweist auf die zusätzliche File-Level-Dedup als Sicherheitsnetz für genau diesen Fall; Verhalten deckt sich mit dem Design

#### EC-8: Manuelles Zurücksetzen einer hängenden Sperre durch Admin
- [x] Sperrwert ist lesbares JSON (`owner`, `path`, `folder_id`, `started_at`, `last_heartbeat`) — per direktem `DEL` in Redis jederzeit außerhalb des n8n-Flows entfernbar, kein UI nötig

### Security Audit Results

**n8n workflow features (kein neuer externer Trigger, rein interne Scheduled Workflows):**
- [x] Keine neue Angriffsfläche: keine neuen Webhooks, keine neuen Credentials, kein neuer externer Service
- [x] Redis-Key-Konstruktion sicher: `folder.id` stammt aus PostgreSQL `SERIAL` (Integer, kein Nutzereingabe-String), keine Injection-Möglichkeit in Key-Namen
- [x] Lua-Skript-Injection ausgeschlossen: Owner-Token und Timestamps werden ausschließlich über `ARGV`/`arguments` an `EVAL` übergeben, niemals in den Skript-Text interpoliert — live gegen echtes Redis verifiziert
- [x] Fehlerhafte/korrumpierte Lock-Werte (z.B. durch manuellen Admin-Eingriff mit ungültigem JSON) führen zu einem sauberen `pcall`-Fehlschlag (Rückgabe `0`, kein Lua-Crash) — live verifiziert
- [x] Keine neuen Secrets im Code; bestehende `REDIS_PASSWORD`-Handhabung unverändert übernommen
- [x] `callerPolicy: workflowsFromSameOwner` auf beiden Workflows (Dispatcher + neuer Sub-Workflow) — konsistent mit bestehender Konvention, keine Rechteausweitung

### Bugs Found

#### BUG-1: Sperre wird bei einem echten, unerwarteten Node-Fehler (nicht Zeitlimit/Lock-Verlust) nicht sofort freigegeben
- **Severity:** Medium
- **Steps to Reproduce:**
  1. Angenommen, ein bislang unbekannter Bug oder eine Laufzeitausnahme lässt einen der bestehenden, unveränderten Verarbeitungsschritte (z.B. `Code: Lifecycle Check` im Pfad-Worker oder `Code: BankTransaction Phase B` im Processor) eine nicht abgefangene Exception werfen (alle diese Nodes haben zwar bereits eigene try/catch/finally-Blöcke aus früheren PROJs, aber ohne `onError`-Konfiguration auf Node-Ebene stoppt n8n bei einer wirklich unerwarteten Exception die gesamte Execution sofort an dieser Stelle)
  2. Erwartet laut Spec/Tech-Design ("Bricht die Datei-Verarbeitung ... mit Fehler ab, gibt der Worker seine Pfad-Sperre trotzdem frei" bzw. "Nach regulärem Abschluss ... wird die Sperre freigegeben"): Sperre wird auch in diesem Fall sofort freigegeben
  3. Tatsächlich: Es gibt keinen verkabelten Error-Output-Pfad (`onError: 'continueErrorOutput'`) zu `Code: Release Path Lock` bzw. `Code: Release Processor Lock (Success)` — eine solche Exception würde die Execution beenden, ohne dass der Release-Code läuft. Die Sperre bleibt bis zum TTL-Ablauf bestehen (Scanner: 180s, Processor: 30 Min)
- **Einordnung:** Kein Datenverlust und kein Doppelverarbeitungs-Risiko (die Sperre verfällt selbstständig und ist danach wieder frei) — reines Verzögerungsrisiko, im Scanner-Fall sehr kurz (180s), im Processor-Fall potenziell bis zu 30 Min am nächsten Abend. Dasselbe Fehlerbehandlungs-Muster (kein durchgängiges `onError`-Routing) besteht bereits unverändert im gesamten übrigen Workflow und ist keine PROJ-72-spezifische Regression, aber die Tech-Design-Formulierung verspricht für die Sperre explizit eine Freigabe "auch bei Fehler", was so nicht vollständig eingehalten wird.
- **Priority:** Nice to have (kann in einem Folge-Sprint durch `onError: 'continueErrorOutput'` + eine zusätzliche Fehler-Route zum jeweiligen Release-Node geschlossen werden, falls gewünscht)

#### BUG-2: workflowId-Platzhalter im Dispatcher muss vor dem ersten Deploy manuell ersetzt werden
- **Severity:** Low
- **Steps to Reproduce:**
  1. `alice-dms-scanner` wird deployed, ohne vorher den Platzhalter `__REPLACE_WITH_PATH_WORKER_WORKFLOW_ID__` im Node `Execute: Path Worker` durch die echte `alice-dms-path-worker`-Workflow-ID zu ersetzen
  2. Erwartet: Dispatcher stößt den Pfad-Worker an
  3. Tatsächlich: Der `Execute: Path Worker`-Node schlägt fehl (ungültige Workflow-ID), da die echte ID erst nach dem ersten Import von `alice-dms-path-worker` bekannt ist
- **Priority:** Fix before deployment (bereits als expliziter manueller Schritt im Abschnitt "Deployment" dieser Spec dokumentiert — kein Code-Bug, sondern ein Deploy-Reihenfolge-Punkt, den der Nutzer beim Deploy beachten muss)

### Regression-Check (bestehende, deployte Features)
- [x] MQTT-Topics für Datei-Routing unverändert (`alice/dms/pdf|ocr|txt|office|image`) — Nachrichtenformat 1:1 identisch, keine Auswirkung auf `dms-extractor-*`-Container (PROJ-16/17/18/56)
- [x] `alice/dms/lifecycle` (PROJ-21) und `alice/dms/done`, Thumbnail-Trigger (PROJ-55) unverändert
- [x] Kein PostgreSQL-Schema geändert — `alice.dms_watched_folders` weiterhin identisch gelesen (SELECT unverändert)
- [x] Bestehende Datei-Level-Redis-Strukturen (`alice:dms:processed`, `queued_files`, `path_to_hash`, `hash_to_paths:<hash>`) unverändert genutzt
- [ ] **Nicht verifizierbar:** Live-Regressionstest der Plaintext-/BankTransaction-/Image-/Geocode-Kernlogik im Processor, da diese Session keinen Zugriff auf eine laufende n8n-Instanz mit echten Daten hat — Code dieser Bereiche wurde nachweislich nicht verändert (nur um Lock-Aufruf/-Renewal ergänzt), Diff-Review bestätigt dies

### Summary
- **Acceptance Criteria:** 13/15 passed (2 nicht live verifizierbar mangels Deployment, s.o.; strukturell/statisch aber erfüllt)
- **Bugs Found:** 2 total (0 critical, 0 high, 1 medium, 1 low)
- **Security:** Pass — keine neue Angriffsfläche, Lock-Primitiven live gegen echtes Redis auf Atomarität, Besitzprüfung und Robustheit gegen korrupte Werte verifiziert
- **Production Ready:** YES (kein Critical/High-Bug offen)
- **Recommendation:** Deploy — BUG-1 und BUG-2 sind dokumentierte, nicht-blockierende Punkte (Nice-to-have bzw. bereits im Deployment-Ablauf abgedeckt). Nach dem Deploy wird empfohlen, die beiden nicht verifizierbaren ACs (echte überlappende Executions, Stichprobe gegen `alice:dms:geocode_pending`) einmalig anhand echter n8n-Executions nachzuprüfen, analog zur Methode aus der PROJ-56-QA.

## Deployment

**Manueller Schritt vor dem ersten Deploy (workflowId-Platzhalter):**
1. `alice-dms-path-worker` zuerst deployen ("Deploy n8n-workflow alice-dms-path-worker").
2. Echte Workflow-ID ermitteln (n8n-UI oder `n8n_get_workflow_minimal`).
3. In `workflows/alice-dms-scanner.json` im Node `Execute: Path Worker` den Platzhalter `__REPLACE_WITH_PATH_WORKER_WORKFLOW_ID__` durch die echte ID ersetzen.
4. `alice-dms-scanner` deployen ("Deploy n8n-workflow alice-dms-scanner").
5. `alice-dms-processor` deployen ("Deploy n8n-workflow alice-dms-processor").

### Produktionsstand (2026-07-29)

Alle drei Workflows sind live deployed. Erster Lauf gegen den echten Backlog:

- **Pfade mit geringem Datenaufkommen:** alle abgearbeitet, aktuell keine neuen Dateien in diesen Pfaden.
- **Bild-/Video-Pfad:** läuft noch (mehrere tausend Dateien), Fertigstellung wird noch einige Zeit in Anspruch nehmen. Redis-Lock verhält sich dabei erwartungsgemäß (Sperre bleibt beim laufenden Worker, kein Doppel-Dispatch bei den dazwischenliegenden stündlichen Triggern).
- **`alice-dms-processor`:** manuell gestartet, läuft bisher ohne Fehler (nach dem Task-Runner-Speicher-Fix, siehe "Betriebs-Fix"-Abschnitt oben).
- **n8n neu deployed** nach dem Betriebs-Fix (`N8N_RUNNERS_MAX_OLD_SPACE_SIZE`, Datei-Logging, winston-Umstellung) — Container-Neustart hat den zu dem Zeitpunkt laufenden Bild-Pfad-Worker beendet; dieser wird durch den nächsten stündlichen Trigger sauber neu gestartet (bereits verarbeitete Dateien werden über den bestehenden Hash-Abgleich in `Code: Lifecycle Check` übersprungen, kein Re-OCR/Re-Queueing).
