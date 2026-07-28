# PROJ-72: DMS Scanner/Processor Backlog-Locking

## Status: Architected
**Created:** 2026-07-28
**Last Updated:** 2026-07-28

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

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
