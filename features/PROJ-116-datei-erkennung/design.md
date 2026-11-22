# Architektur: PROJ-116 Datei-Erkennung (#5)

**Spec:** [spec.md](spec.md) · **Stand:** 2026-11-22

## A) Betroffene Bausteine
```
alice-file-detection (neuer Container, Python/FastAPI, Port 8013, nur Docker-Netz, keine nginx-Route)
+-- Zeitplaner: Tagesscan (Intervall), Nachtlauf (Uhrzeit), Nachholen nach Neustart
+-- Tagesscan: Ordner-Änderungszeiten, Stabilität über zwei Scans, Hash nur für neue Pfade
+-- Nachtlauf: voller Abgleich, verschwundene Fundorte, in-place-Änderungen, Sicherungen, Zusammenfassung
+-- interne Schnittstelle: Lauf auslösen, Zusammenfassungen, Erkennungsprobleme, Health
+-- liest die NAS-Freigaben nur (nas-volumes.yml wie die DMS-Container)
+-- schreibt ausschließlich über die Schnittstelle von alice-source-registry

alice-source-registry (PROJ-115, Änderungen)
+-- deleted-Quellen werden nicht mehr vergeben (claim)
+-- deleted → Markdown per Git-Umbenennung nach deleted/<art>/<JJJJ>/<MM>/, Frontmatter `deleted: <Zeitpunkt>`
+-- Reaktivierung → Markdown zurück an den regulären Platz, `deleted` entfällt
+-- Hand-Löschen in deleted/ wird akzeptiert (kein Wiederherstellen, kein Fehler);
|   taucht das Original wieder auf → letzter Stand aus Git, sonst neu angelegt + Stufen neu
+-- Registrierung kann die Stufe `detect` gleich als erledigt markieren
+-- in-place-Änderung (einziger Fundort): alle Stufen ab `extract` wieder `pending`
+-- Compose: eigene NAS-Freigabe der Quelle der Wahrheit als ganze Freigabe, ohne nas-volumes.yml

PostgreSQL (neu, nur vom Erkennungsdienst genutzt):
  alice.detect_files, alice.detect_dirs, alice.detect_pending, alice.detect_problems, alice.detect_runs
nginx, Frontend, n8n, Redis, Weaviate: keine Änderung
```

Ein neuer Dienst statt Erweiterung des Register-Dienstes: Die Erkennung braucht die (lesenden) NAS-Freigaben der Originale, der Register-Dienst nach dieser Spec genau eine andere (die Freigabe der Quelle der Wahrheit). Getrennte Container halten die Freigaben getrennt — so kann die Quelle der Wahrheit nie als Quelle erkannt werden.

## B) Datenmodell

Das Register (PROJ-115) bleibt die Wahrheit über Quellen, Fundorte und `deleted`. Der Erkennungsdienst führt nur seinen eigenen Arbeitsstand:

- **Bekannte Dateien** (`alice.detect_files`): je Pfad die Quelle, zu der er gehört, Größe und Änderungszeit, wie zuletzt gesehen, und der überwachte Ordner (Pfad), dem er zugeordnet ist. Grundlage für „Pfad schon bekannt → nicht hashen“ und für den Vergleich im Nachtlauf. Größe/Änderungszeit je Pfad (nicht je Quelle), weil Kopien andere Zeitstempel haben können.
- **Ordnerstand** (`alice.detect_dirs`): je Verzeichnis die zuletzt gesehene Änderungszeit, der übergeordnete Ordner und ob der Wert schon von zwei Scans bestätigt ist. Nur Gleichheit zählt, kein Zeitvergleich (EC-9).
- **Wartende neue Dateien** (`alice.detect_pending`): Pfad mit Größe und Änderungszeit aus dem letzten Scan, bis sie zweimal gleich gesehen wurden. In der Datenbank, damit ein Neustart nichts verliert.
- **Erkennungsprobleme** (`alice.detect_problems`): Pfad, Ursache, erstes und letztes Auftreten. Verschwindet von selbst, sobald die Datei gelesen werden kann oder nicht mehr existiert.
- **Läufe** (`alice.detect_runs`): Art (Tagesscan/Nachtlauf), Start, Ende, Zustand (läuft/fertig/pausiert/abgebrochen) und beim Nachtlauf die Zusammenfassung (Zahlen als JSON). Grundlage für Nachholen, parallele Läufe und PROJ-122. Aufbewahrung konfigurierbar (Standard 90 Tage, mindestens 30).

Alle Tabellen mit Row Level Security und offenen Policies wie die PROJ-115-Tabellen (nur Dienst-Datenbanknutzer, kein Endnutzerzugriff).

**Änderung Quell-Markdown:** Neues Register-Feld `deleted` (Zeitpunkt), nur vorhanden, solange die Quelle gelöscht ist. Stufen können es nicht schreiben.

**Freigabe** (für die 20-%-Grenze): erster Pfadteil unter dem NAS-Wurzelpfad (Standard `/mnt/nas`, also `/mnt/nas/<freigabe>`), wie im alten Reconcile. Liegt ein Ordner nicht darunter, gilt der überwachte Ordner selbst als Freigabe.

## C) Abläufe

1. **Zeitplaner** (alle paar Sekunden): Ist ein Nachtlauf fällig (letzte Nachtlauf-Zeit ohne fertigen Nachtlauf seitdem, höchstens Nachholfrist her) → Nachtlauf. Sonst, wenn das Intervall seit dem letzten Tagesscan um ist → Tagesscan. Es läuft immer höchstens ein Lauf (eine Sperre im Dienst). Läufe, die beim Start noch als „läuft“ markiert sind, werden als „abgebrochen“ vermerkt.
2. **Ordnerliste:** aus `alice.dms_watched_folders`. Aktive Ordner werden gescannt. Unterordner, die selbst überwachte Ordner sind (aktiv oder nicht), werden beim äußeren Ordner ausgelassen → jede Datei gehört zum längsten passenden Ordner. Ein aktiver Ordner, der nicht lesbar ist oder leer, obwohl Dateien darunter bekannt sind, wird übersprungen (Warnung in Log und Health).
3. **Tagesscan:**
   - Für jeden bekannten Ordner nur die Änderungszeit abfragen. Unverändert und bestätigt → nicht neu listen, nur in die bekannten Unterordner weitergehen. Geändert oder unbekannt → listen; neue Unterordner werden selbst gelistet. Ein geänderter Ordner wird im nächsten Scan noch einmal gelistet (bestätigt), damit eine Datei, die im selben Augenblick dazukam, nicht verloren geht.
   - Datei, deren Pfad nicht bekannt ist und die zu den Endungen passt → wartende Datei. Jeder Scan prüft alle wartenden Dateien erneut: gleiche Größe und Änderungszeit wie beim letzten Mal → stabil → hashen (sha256, in Blöcken, im Hintergrund-Thread) → beim Register anmelden (unbekannter Hash → neue Quelle mit Basis-Markdown, `detect` erledigt; bekannter Hash → zusätzlicher Fundort, gelöschte Quelle wird reaktiviert). Hat sich die Datei beim Hashen verändert, wartet sie weiter.
   - Entfernt nie etwas. Bekannte Pfade werden nicht gelesen.
4. **Nachtlauf:**
   - Alle Dateien aller aktiven, erreichbaren Ordner auflisten. Übersprunglisten gelten; nicht unterstützte Endungen werden je Ordner und gesamt gezählt.
   - Neue Pfade: Stabilität innerhalb des Laufs (Größe und Änderungszeit beim Auflisten gleich wie nach dem Hashen, bzw. eine passende wartende Datei), dann wie im Tagesscan. Anmeldung mit Sammel-Commit; am Ende werden offene Sammel-Commits geschrieben. Fortschritt alle 100 Dateien im Log. Weil jeder angemeldete Pfad sofort in `detect_files` steht, setzt ein abgebrochener oder nächster Lauf einfach fort.
   - Bekannte Pfade mit anderer Größe oder Änderungszeit → neu hashen. Gleicher Hash → nur Stand merken. Sonst: (a) einziger Fundort und neuer Hash unbekannt → Original der Quelle aktualisieren (gleiche `id`, Stufen ab `extract` `pending`, `manual` bleibt); (b) die Quelle hat weitere Fundorte, oder (c) der neue Hash gehört schon einer anderen Quelle → Pfad mit neuem Hash anmelden und danach bei der alten Quelle als verschwunden melden (die alte Quelle wird bei (c) `deleted`).
   - Danach **Entfernen**: bekannte Pfade in aktiven, gescannten Ordnern, die nicht gesehen wurden, werden je Freigabe gesammelt. Mehr als die Grenze (Standard 20 %) der bekannten Pfade dieser Freigabe → nichts entfernen, Freigabe als blockiert melden. Sonst je Pfad „Fundort verschwunden“ ans Register (letzter Fundort → `deleted`). Pfade von Ordnern, die nicht mehr in der Liste stehen, werden ohne Grenze entfernt. Deaktivierte und übersprungene Ordner werden nicht angefasst. Weil Neues vor dem Entfernen angemeldet wird, wird eine verschobene Datei oder ein umbenannter Ordner (EC-6) nie zwischendurch `deleted`.
   - **Zusammenfassung** als Log-Eintrag und in `detect_runs`; ältere als die Aufbewahrungsfrist werden gelöscht.
5. **Erkennungsprobleme:** Lesefehler beim Hashen (z. B. fehlende Rechte) → Eintrag mit Ursache. Verschwindet die Datei beim Hashen → kein Fehler, wird beim nächsten Scan neu bewertet (EC-1). Jeder Scan versucht wartende Dateien und Problem-Pfade erneut.
6. **Register nicht erreichbar** (Verbindung scheitert oder „repo_unavailable“): Lauf wird als „pausiert“ beendet, Ordnerstände dieses Laufs werden nicht gespeichert → nächster Lauf findet dieselben Änderungen wieder. Nichts wird entfernt.
7. **Interne Schnittstelle** (nur Docker-Netz): Tagesscan bzw. Nachtlauf sofort starten (Antwort „busy“, wenn ein Lauf aktiv ist), letzte Läufe/Zusammenfassungen, offene Erkennungsprobleme, Health.

**Register-Dienst (Änderungen):**
- Beim Schreiben einer Quell-Markdown bestimmt der Zustand `deleted` den Ort: gelöscht → `deleted/` + regulärer Pfad, sonst regulärer Pfad. Ein Wechsel ist eine Git-Umbenennung in einem Commit (`git log --follow` bleibt). Hand-Änderungen werden wie bisher vorher übernommen (EC-10).
- Hand-Korrektur-Prüfung beobachtet auch `deleted/`. Fehlt eine Datei einer gelöschten Quelle unter `deleted/`, wird das Löschen als Commit des Autors „Alice Hand-Korrektur“ übernommen, ohne Fehler-Ereignis. Außerhalb von `deleted/` bleibt es ein Fehler mit Wiederherstellung.
- Reaktivierung ohne Datei: Inhalt aus dem gespeicherten Git-Fingerabdruck (letzter Pipeline-Stand); fehlt er in Git, wird die Markdown neu angelegt und alle Stufen laufen neu.

## D) Technische Entscheidungen
- **Eigener Arbeitsstand in PostgreSQL** statt jedes Mal das Register zu fragen: Ein Tagesscan über 10.000 bekannte Dateien braucht dann keinen einzigen Aufruf beim Register. Die Tabellen sind nur ein Spiegel: geht ein Eintrag verloren, wird der Pfad neu gehasht und das Register ordnet ihn über den Hash derselben Quelle zu — es entstehen nie Duplikate (AK-27).
- **Ordner-Änderungszeit mit Bestätigung durch einen zweiten Scan**: NAS-Dateisysteme haben oft nur Sekunden-Auflösung; ohne zweites Listen könnte eine Datei, die im selben Augenblick dazukommt, bis zur Nacht übersehen werden.
- **Stabilität im Nachtlauf innerhalb des Laufs**: Der erste Lauf muss laut AK-28 den ganzen Bestand registrieren. Zwischen Auflisten und Hashen einer Datei vergeht Zeit; ist sie dabei unverändert, gilt sie als stabil. Im Tagesscan gilt die Regel „zwei Scans“ unverändert.
- **Erst anmelden, dann entfernen**: verhindert unnötiges `deleted` mit Hin- und Herschieben der Markdown bei Verschiebungen und umbenannten Ordnern.
- **Abbruch statt Teil-Entfernung**: Entfernt wird nur, wenn der Lauf alle Ordner fertig gescannt hat und das Register erreichbar ist.
- **Health „warning“ mit HTTP 200**: nicht erreichbare Ordner und ein pausiertes Register sind Warnungen (der Dienst arbeitet weiter und holt nach); nur Datenbank weg oder hängender Zeitplaner sind „unhealthy“. Der Healthcheck gibt die Antwort aus, so steht die Warnung mit dem Ordner in `docker inspect`.
- **Register-Freigabe als ganze Freigabe, Repo als Unterordner darin** (z. B. `/mnt/nas/sot/source-of-truth`): Fehlt der Mount, ist der Einhängepunkt leer, der Unterordner fehlt und der Register-Dienst legt kein neues Repo an (Schutz aus PROJ-115 bleibt).
- **Keine Authentifizierung an der Schnittstelle**, keine nginx-Route — wie PROJ-115.
- **Keine Redis-/Weaviate-Nutzung**: das alte System bleibt garantiert unberührt; Originale werden nur lesend geöffnet.

## E) Abhängigkeiten
- Pakete: `fastapi`, `uvicorn`, `asyncpg`, `httpx` (alle schon im Projekt).
- Neue Umgebungsvariablen (Platzhalter in `.env.example` von `alice-file-detection`): `POSTGRES_DSN`, `REGISTRY_URL`, `DETECT_SCAN_INTERVAL_SECONDS` (300), `DETECT_NIGHTLY_TIME` (02:00), `DETECT_TIMEZONE` (Europe/Berlin), `DETECT_CATCHUP_HOURS` (6), `DETECT_DELETE_LIMIT_PERCENT` (20), `DETECT_NAS_ROOT` (/mnt/nas), `DETECT_EXT_DOCUMENT`, `DETECT_EXT_IMAGE`, `DETECT_EXT_AUDIO`, `DETECT_EXT_VIDEO`, `DETECT_SKIP_DIRS`, `DETECT_SKIP_FILES`, `DETECT_EXCLUDE_PATHS`, `DETECT_SUMMARY_RETENTION_DAYS` (90).
- Register-Dienst: `SOT_SHARE` (Host-Pfad der eigenen Freigabe), `SOT_UID_GID` (NAS-Konto); `SOT_REPO_PATH` zeigt danach auf den Unterordner in dieser Freigabe.

## F) Test- und Deploy-Plan
| AK | Nachweis | Art |
|---|---|---|
| AK-1, AK-3, AK-5–7, AK-21 | Temp-Ordner als überwachte Ordner, echter Register-Dienst (in-process) mit Temp-Git-Repo | Integration (Test-DB) |
| AK-2 | Größe zwischen zwei Scans ändern | Integration |
| AK-4 | 10.000 Dateien, zweiter Tagesscan zählt Hash- und Listen-Aufrufe (= 0) | Integration (Attrappen-Register) |
| AK-8–11, AK-13–18 | Verschieben/Löschen/Ändern/Wiederauftauchen, Git-Log `--follow`, Frontmatter, Stufen | Integration |
| AK-12 | `deleted`-Quelle mit offenen Stufen, `claim` liefert sie nicht | Integration (Register-Tests) |
| AK-19, AK-20, AK-22, AK-23 | Ordner deaktivieren/löschen/umbenennen, Ordner leer bzw. nicht lesbar, 25 %/15 % fehlend | Integration |
| AK-24 | Datei ohne Leserechte (chmod 000; im Root-Job über Attrappe des Lesezugriffs) | Integration |
| AK-25 | Register-Attrappe antwortet 503 / nicht erreichbar, danach normal | Integration |
| AK-26, AK-30 | Lauf blockiert, zweiter Auslöser → „busy“; Schnittstelle; keine nginx-Route | Integration + Prüfung der nginx-Konfiguration + Container-Rauchtest |
| AK-27 | Nachtlauf mittendrin abbrechen, Neustart-Logik holt nach, keine Duplikate | Integration |
| AK-28 | 1.200 Dateien, Sammel-Commits ≤ 500, Fortschritt im Log | Integration |
| AK-29 | `a.zip` ×3, `b.exe` ×1 → Zusammenfassung je Ordner und gesamt | Integration |
| AK-31 | Dienst nutzt weder Redis noch Weaviate; Originale unverändert (Hash/mtime vor/nach) | Integration + Code-Prüfung |
| AK-32 | Live nach Deploy | nur durch den Menschen |

Nicht ohne Produktivsysteme testbar: echte NAS-Freigaben (NFS, Ausfall, Rechte des NAS-Kontos), Umzug des produktiven Repos → Attrappe: Temp-Verzeichnisse, die umbenannt/geleert werden.

Deploy-Schritte für den Menschen:
1. Migration `sql/migrations/2026-11-22_PROJ-116_file_detection.sql` anwenden.
2. Eigene NAS-Freigabe für die Quelle der Wahrheit anlegen (Rechte: Admin schreiben, Haushalt lesen, Gast nichts), auf dem Server einhängen (z. B. `/mnt/nas/sot`), das bestehende Repo samt `.git` dorthin umziehen (Register-Dienst vorher stoppen); `.env` des Register-Dienstes: `SOT_SHARE`, `SOT_UID_GID`, `SOT_REPO_PATH`.
3. `.env` für `alice-file-detection` aus `.env.example`.
4. Staging, Compose-Sync, beide Dienste bauen und starten; ersten Nachtlauf manuell auslösen (AK-32).

## Decision Log
| Entscheidung | Alternative | Abwägung |
|---|---|---|
| Neuer Dienst `alice-file-detection` | Erkennung im Register-Dienst | Freigaben getrennt (SoT nie als Quelle erkennbar), Register bleibt schlank |
| Eigener Arbeitsstand (`detect_*`) | Fundorte bei jedem Scan beim Register abfragen | Tagesscan ohne Register-Last; Register bleibt Wahrheit, Spiegel ist verlustfrei wiederherstellbar |
| Wartende Dateien in PostgreSQL | im Speicher | Neustart verliert keine halb erkannte Datei (Ordnerstand ist schon gespeichert) |
| Stabilität im Nachtlauf innerhalb des Laufs | auch nachts zwei Läufe | Bestand muss im ersten Lauf vollständig sein (AK-28) |
| Freigabe = erster Pfadteil unter `/mnt/nas` | Freigabe = überwachter Ordner | wie das alte Reconcile; Ausfall einer Freigabe trifft alle ihre Ordner |
| Zusammenfassung als JSON in `detect_runs` | eigene Tabellen je Kennzahl | Inhalt wächst mit PROJ-122, eine Zeile je Lauf genügt |

## Umsetzung (Bau, 2026-11-22)
- Neuer Dienst `docker/compose/automations/alice-file-detection/` (Port 8013, keine nginx-Route, Eintrag im `Makefile`), Schema in `sql/init-schema.sql` Abschnitt 17 + Migration `sql/migrations/2026-11-22_PROJ-116_file_detection.sql`.
- Register-Dienst: `deleted`-Feld und `deleted/`-Ablage beim Schreiben, `claim` ohne gelöschte Quellen, `complete` bei der Registrierung (Stufe `detect` erledigt), `update_original` setzt alle Stufen nach `detect` auf `pending`, Hand-Löschen unter `deleted/` wird als Commit „manual: remove …" übernommen. Quellen, die schon vor PROJ-116 gelöscht waren (z. B. die Testquelle aus dem PROJ-115-Live-Test), wandern beim nächsten Prüflauf nach `deleted/`.
- Register-Compose: eigene Freigabe `${SOT_SHARE}` als ganze Freigabe nach `/mnt/nas/sot`, Nutzer `${SOT_UID_GID}`, kein `nas-volumes.yml` mehr. Image: leerer Repo-Ordner `/mnt/nas/sot/source-of-truth` für den Container-Test (in Produktion vom Freigabe-Mount verdeckt; fehlt die Freigabe, fehlt der Ordner), beschreibbar für das NAS-Konto, `HOME=/tmp` für git.
- Ergänzungen zur Architektur:
  - **Tagesscans starten automatisch erst nach dem ersten fertigen Nachtlauf.** Sonst hätte der erste Tagesscan nach dem Deploy den ganzen Bestand Datei für Datei mit Einzel-Commits registriert, statt im ersten Nachtlauf mit Sammel-Commits (AK-28, AK-32). Manuell auslösen geht immer.
  - Findet ein Tagesscan mehr als 20 stabile neue Dateien (z. B. ein neu hinzugefügter Ordner), meldet er sie mit Sammel-Commit an.
  - Ein Unterordner, der nicht gelistet werden kann, wird als Erkennungsproblem geführt; unter ihm wird nichts entfernt.
  - Nach einer Änderung wird ein Ordner im nächsten Tagesscan noch einmal gelistet (Bestätigung). Im Dauerzustand ohne Änderung wird kein Ordner gelistet und keine Datei gelesen (AK-4).
- Abweichungen von der Spec: keine. Folge der Spec-Regel „plötzlich leerer Ordner = Mount fehlt" (AK-22): Wird ein überwachter Ordner vollständig geleert (z. B. ein Eingangsordner, aus dem alles wegsortiert wurde), bleiben seine Fundorte stehen, bis wieder eine Datei darin liegt.
