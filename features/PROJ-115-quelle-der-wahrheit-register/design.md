# Architektur: PROJ-115 Quelle-der-Wahrheit-Repo + Quellen-Register (#3)

**Spec:** [spec.md](spec.md) · **Stand:** 2026-11-20

## A) Betroffene Bausteine
```
alice-source-registry (neuer Container, Python/FastAPI, Port 8012, nur Docker-Netz)
+-- Repo-Verwaltung: Init, Lesen/Schreiben der Quell-Markdowns, Git-Commits (git im Container)
+-- Register: Quellen, Fundorte, Eltern (Mail → Anhang), Stufenzustände, Ereignisse
+-- Arbeits-Queue in Redis (aus dem Register wiederherstellbar)
+-- Hintergrund-Überwachung: Hand-Korrekturen, hängende Stufen, Sammel-Commits,
|   Erreichbarkeit des Repo-Ordners, Queue-Abgleich
+-- interne HTTP-Schnittstelle für die Folge-Stufen (PROJ-116 ff.)
PostgreSQL: alice.sources, alice.source_locations, alice.source_parents,
            alice.pipeline_stages, alice.source_stages, alice.source_events (alle neu)
Redis: sot:queue:<stufe> (Arbeits-Queue je Stufe), sot:queue:ready (Merker)
nginx: keine Änderung (bewusst keine Route)
Frontend, n8n: keine Änderung
```

Ein neuer Dienst statt Erweiterung eines bestehenden: Kein vorhandener Dienst hat Zugriff auf einen beschreibbaren NAS-Ordner mit Git, und PROJ-116–120 brauchen genau eine Stelle, die Register und Repo zusammen ändert (sonst laufen Datei und Datenbank auseinander).

## B) Datenmodell

**Quelle** (`alice.sources`): eine Zeile je eindeutigem Inhalt.
- `id`: kurze, zufällige, unveränderliche Kennung (12 Zeichen, Kleinbuchstaben/Ziffern), wird nie aus Pfad oder Name abgeleitet.
- Art (`kind`), Hash (eindeutig, nachträglich änderbar für EC-8), Größe, Änderungszeit des Originals, Erfassungszeitpunkt, Titel.
- Pfad der Quell-Markdown im Repo und der Git-Fingerabdruck (Blob-Hash) des zuletzt von der Pipeline geschriebenen bzw. übernommenen Inhalts. Daran erkennt der Dienst jede fremde Änderung.
- `deleted` + Zeitpunkt: gesetzt, sobald kein Fundort mehr vorhanden ist. Gelöschte Quellen bleiben stehen.
- `repo_error`: verständliche Ursache, wenn die Datei gesperrt ist (ungültiges Frontmatter). Solange gesetzt, fasst die Pipeline die Datei nicht an.

**Fundorte** (`alice.source_locations`): je Quelle beliebig viele, entweder Datei (`path`) oder Mail (`mailbox` + `message_id`), mit „vorhanden"-Kennzeichen, zuerst/zuletzt gesehen, verschwunden seit. Verschwundene Fundorte bleiben als Historie.

**Eltern** (`alice.source_parents`): Paare Quelle → Mail-Quelle. Daraus entstehen `parents` im Frontmatter und die Liste der Anhänge einer Mail.

**Stufen** (`alice.pipeline_stages`): erweiterbare Liste mit Name, Reihenfolge, Arten, für die die Stufe nicht gilt (`skip_kinds`), und Kennzeichen „bei Inhaltsänderung zurücksetzen". Vorbelegt: `detect`, `extract`, `classify`, `database`, `rag`, `wiki`, `thumbnail`; `database`/`rag`/`wiki` werden bei Inhaltsänderung zurückgesetzt; für `audio`/`video` gelten alle außer `detect` als `skipped`.

**Stufenzustand** (`alice.source_stages`): je Quelle und Stufe Zustand (`pending`/`running`/`done`/`failed`/`failed_permanent`/`skipped`), Versuche, letzte Fehlermeldung, letzter Versuch, nächster Retry, Übernahmezeitpunkt und ein Übernahme-Token (nur wer die Stufe übernommen hat, kann sie abschließen).

**Ereignisse** (`alice.source_events`): Protokoll je Quelle (Hand-Korrektur übernommen, Datei gelöscht und wiederhergestellt, Datei zurückverschoben, ungültig/repariert). Grundlage für PROJ-122.

**Repo-Zustand** liegt ausschließlich in Git: Quell-Markdowns, README, eine interne Git-Referenz `refs/alice/scanned` (bis wohin fremde Commits schon geprüft sind).

Alle neuen Tabellen mit Row Level Security und offenen Policies wie die übrigen Dienst-Tabellen (Zugriff nur über den Dienst-Datenbanknutzer; kein Endnutzer greift direkt zu). Keine personenbezogenen Rechte nötig: PROJ-115 hat keinen Nutzerzugriff.

**Quell-Markdown:** YAML-Frontmatter mit den Basisfeldern der Spec (`id`, `schema` = 1, `kind`, `title`, `locations`, `parents`, `hash`, `size`, `modified`, `captured`, `language`, `type`, `manual`), danach `# <title>` und der Inhaltsteil. Stufen können weitere Felder ergänzen (erweiterbar). Kein Zustand, kein Fehler, kein Zähler im Frontmatter. Bei `audio`/`video` (und bis zur Extraktion bei allen anderen) enthält der Inhaltsteil einen Link auf das Original. Der Inhaltsteil heißt in `manual` `content`.

## C) Abläufe

1. **Start:** Repo-Ordner prüfen. Leer → `git init`, Ordner + README, erster Commit unter „Alice ETL". Git-Repo → unverändert weiterverwenden (nur verwaiste Sperren aufräumen, liegengebliebene Pipeline-Dateien committen). Nicht leer und kein Git → Fehler im Log, Dienst beendet sich, Ordner bleibt unberührt. Ordner fehlt/nicht lesbar → Dienst läuft, meldet „unhealthy" und prüft weiter (NAS-Ausfall).
2. **Quelle registrieren** (PROJ-116, PROJ-123): Art, Hash, Größe, Änderungszeit, Titel (Originalname/Betreff), Fundort, optional Eltern und Erfassungszeit (Mail-Datum). Hash bekannt → Fundort/Eltern an die bestehende Quelle hängen, Stufen bleiben, wie sie sind. Hash neu → `id` erzeugen, Stufen `pending`/`skipped`, Quell-Markdown unter `<art>/<JJJJ>/<MM>/<id>-<slug>.md` schreiben, Commit.
3. **Fundorte pflegen:** hinzufügen, als verschwunden melden, Hash aktualisieren. Ändert im Frontmatter nur `locations` (bzw. `hash`/`size`/`modified`), nie Ort oder Name der Datei. Letzter Fundort weg → `deleted`.
4. **Stufe übernehmen:** Ein Worker fragt „gib mir fällige Arbeit für Stufe X". Der Dienst nimmt Kandidaten aus der Redis-Queue und setzt jeden in **einer** bedingten Datenbank-Änderung auf `running` (nur wenn noch `pending` bzw. `failed` und fällig) — so kann nur einer gewinnen. Ist Redis weg, wird direkt aus dem Register gewählt. Gesperrte Quellen werden übersprungen. Ist das Repo nicht erreichbar, gibt es keine Arbeit (Pause, Grund in der Antwort).
5. **Stufe abschließen:** `done`, `fail` (Fehler → Versuch +1, Backoff 1 min/5 min/30 min/2 h; der 5. Fehlversuch → `failed_permanent`), `release` (Arbeit ohne Fehlversuch zurückgeben, z. B. bei NAS-Ausfall). Nur mit gültigem Übernahme-Token.
6. **Markdown schreiben** (Stufe liefert Felder und/oder Inhaltsteil): Sperre holen → zuerst eine eventuelle Hand-Änderung an der Datei als Hand-Korrektur committen → Felder aus `manual` und den Inhaltsteil (falls `content` in `manual`) beibehalten, übrige übernehmen, Basisfelder aus dem Register → bei geändertem Titel Git-Umbenennung → Commit „`<stufe>: <id> <title>`" unter „Alice ETL". Hat sich mehr als `locations` geändert, gehen `database`/`rag`/`wiki` (außer der schreibenden Stufe) auf `pending`.
7. **Massenlauf:** Schreiben mit Kennzeichen „Sammel-Commit": Datei wird geschrieben, aber erst gesammelt. Commit „`rebuild: <stufe> <n> sources`", sobald 500 Dateien erreicht sind oder die älteste 5 Minuten wartet.
8. **Hand-Korrekturen** (alle 60 s, einstellbar): Kandidaten sind uncommittete Dateien (`git status`) und Dateien aus Commits seit `refs/alice/scanned`. Weicht der Inhalt vom gespeicherten Fingerabdruck der Pipeline ab, ist es eine Hand-Korrektur: Frontmatter prüfen; ungültig → Sperre mit Ursache, nichts übernehmen; gültig → geänderte Felder und ggf. `content` zu `manual` hinzufügen (die vom Menschen gepflegte Liste ist die Basis, entfernte Einträge bleiben entfernt), Datei bei Titeländerung umbenennen, Commit „`manual: <id> <title>`" unter dem Autor „Alice Hand-Korrektur", abhängige Stufen `pending`, Sperre aufheben. Verschobene Datei → zurück an ihren Ort. Gelöschte Datei → aus Git wiederherstellen, Fehler-Ereignis. Datei ohne bekannte `id` → Warnung im Log, bleibt liegen.
9. **Überwachung** (alle paar Sekunden): Repo erreichbar? (Wechsel wird geloggt, Healthcheck folgt), `running` länger als Zeitüberschreitung → `pending` ohne Fehlversuch, fällige Sammel-Commits, Queue-Abgleich (sofort, wenn der Merker in Redis fehlt, sonst alle 10 min).

**Fehlerverhalten:** Repo nicht erreichbar → Schreibaufrufe antworten 503 „repo_unavailable", nichts wird als Fehlversuch gezählt. Gesperrte Datei → 409. Datenbank weg → 503, Healthcheck „unhealthy".

## D) Technische Entscheidungen
- **Ein Prozess, alle Git-Operationen hintereinander** (eine Sperre im Dienst), weil damit kein Commit Änderungen einer fremden Stufe enthält (EC-9) und nur dieser Dienst schreibt. Jeder Commit nennt seine Dateien ausdrücklich.
- **Fingerabdruck statt Autorenvergleich je Commit:** Der Dienst merkt sich je Quelle den Blob-Hash, den er selbst geschrieben hat. Alles, was davon abweicht (fremder Commit oder uncommittete Änderung), ist eine Hand-Korrektur. Das ist die Spec-Regel „nicht vom Pipeline-Autor" — zuverlässig auch bei Commits, die der Mensch zwischen Pipeline-Commits macht, und ohne Zusatzdatei. Liegengebliebene Pipeline-Dateien nach einem Neustart (EC-7) stimmen mit dem Fingerabdruck überein und werden als Pipeline committet.
- **Zwei feste Git-Autoren:** „Alice ETL" für die Pipeline, „Alice Hand-Korrektur" für übernommene Hand-Änderungen, die der Mensch nicht selbst committet hat (Nachricht `manual: …`). Committet der Mensch selbst, bleibt sein Commit; der Dienst ergänzt `manual` in einem Folge-Commit.
- **Repo wird nie selbst angelegt:** Der konfigurierte Ordner muss existieren. Fällt die NAS-Freigabe weg, ist der Unterordner nicht mehr da — so entsteht nie versehentlich ein neues Repo im leeren Einhängepunkt.
- **Verwaiste Git-Sperren** (`*.lock` in `.git`) werden erst entfernt, wenn sie älter als die Wartezeit (Standard 120 s) und in dieser Zeit unverändert sind; sonst gilt das Repo als beschäftigt und es wird später erneut versucht.
- **Redis nur als Queue** (sortierte Menge je Stufe, Wert = fällig ab), mit TTL und Merker; das Register bleibt die Wahrheit. Die exklusive Übernahme macht PostgreSQL.
- **Keine Authentifizierung an der Schnittstelle, keine nginx-Route:** Aufrufer sind nur Dienste im Docker-Netz, es gibt keinen Nutzerbezug. Schutz über Netz und fehlende Route (AK-33).
- **Slug:** Umlaute → ae/oe/ue/ss, sonst nur `a-z0-9-`, höchstens 60 Zeichen; leer → `untitled`.
- **`kind` und `id` sind von Hand nicht änderbar** (Änderung = ungültig), weil Ordner und Verweise daran hängen.
- **Backoff-Tabelle** 1 min/5 min/30 min/2 h/12 h; der fünfte Fehlversuch macht `failed_permanent` (AK-17), daher wird die 12-h-Stufe bei der Grenze 5 nicht erreicht. Sie bleibt in der Tabelle, falls die Grenze angehoben wird.

## E) Abhängigkeiten
- Pakete: `fastapi`, `uvicorn`, `pydantic`, `asyncpg`, `redis`, `PyYAML`; im Container `git`.
- Neue Umgebungsvariablen (Platzhalter in `.env.example`): `POSTGRES_DSN`, `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `SOT_REPO_PATH`, `SOT_STALE_RUNNING_SECONDS` (Standard 1800), `SOT_SCAN_INTERVAL_SECONDS` (Standard 60), `SOT_GIT_LOCK_STALE_SECONDS` (Standard 120), `SOT_BATCH_MAX_FILES` (500), `SOT_BATCH_MAX_SECONDS` (300).
- NAS: ein **beschreibbarer** Unterordner auf der beschreibbaren Freigabe (z. B. unter `/mnt/nas/ai/...`), in den Container unter `/data/sot` eingebunden.

## F) Test- und Deploy-Plan
| AK | Nachweis | Art |
|---|---|---|
| AK-1–3 | Start gegen leeren / initialisierten / fremden Ordner im Temp-Verzeichnis | Unit (echtes git) |
| AK-4–7, AK-9, AK-10 | Registrieren + Schreiben, Pfad, Frontmatter, `git log --follow`, Commit-Anzahl/-Nachricht | Integration (Test-DB + Temp-Repo) |
| AK-8 | 1.200 Sammel-Schreibvorgänge → 3 Commits ≤ 500; Zeitgrenze mit kurzer Konfiguration | Integration |
| AK-11–14 | Register-Abfragen nach Registrierung, Duplikat-Hash, Anhang, Fundorte verschwinden | Integration |
| AK-15–19, AK-21 | Parallele Übernahme, Fehler/Backoff, permanent, Retry, hängend, neue Stufe | Integration |
| AK-20, AK-23–29 | Inhalt ändern, Hand-Änderung mit/ohne Commit, `manual`-Schutz, ungültiges/repariertes Frontmatter | Integration |
| AK-22 | Redis leeren → Queue wieder vollständig | Integration (Test-Redis) |
| AK-30–32 | Repo-Ordner wegnehmen/zurückgeben, Healthcheck, verwaiste `index.lock` | Integration |
| AK-33 | keine nginx-Route im Repo; Container-Test ruft nur intern auf | Prüfung der nginx-Konfiguration + Container-Test |
| AK-34 | Live auf dem NAS | nur nach Deploy durch den Menschen |

Nicht ohne Produktivsysteme testbar: echter NAS-Ordner (CIFS, Ausfall der Freigabe) → Attrappe: Temp-Verzeichnis, das umbenannt/entfernt wird. AK-34 prüft der Mensch.

Deploy-Schritte für den Menschen:
1. Migration `sql/migrations/2026-11-20_PROJ-115_source_registry.sql` anwenden.
2. Leeren Ordner für die Quelle der Wahrheit auf der beschreibbaren NAS-Freigabe anlegen; `.env` für `alice-source-registry` aus `.env.example` anlegen.
3. Staging mit `scripts/stage.sh alice-source-registry <PR>`, nach dem Merge `sync-compose.sh` und `make rebuild s=automations/alice-source-registry`.

## Decision Log
| Entscheidung | Alternative | Abwägung |
|---|---|---|
| Neuer Dienst `alice-source-registry` | Erweiterung `alice-dms-thumbnailer`/Extraktoren | Klare Zuständigkeit für Repo + Register; die Altdienste entfallen ohnehin mit Phase 4 |
| HTTP-Schnittstelle im Docker-Netz | Python-Bibliothek, die jede Stufe einbindet | Nur ein Prozess schreibt Git → Serialisierung ohne verteilte Sperren; Stufen können in beliebiger Sprache folgen |
| Blob-Fingerabdruck in der DB | Journal-Datei / Autorenvergleich je Commit | Erkennt Hand-Änderungen gleich, egal ob committet oder nicht; robust bei Neustart |
| Stufen als Tabellenzeilen | Spalten je Stufe | Neue Stufe = neue Zeile, kein Umbau (AK-21) |
| Exklusive Übernahme in PostgreSQL | Redis-Lock | Register ist die Wahrheit; Redis darf verloren gehen (AK-22) |
| Keine Auth an der Schnittstelle | Dienst-JWT | Kein Nutzerbezug, keine nginx-Route; Dienst-Token kann bei Bedarf in einem Folge-Feature ergänzt werden |

## Umsetzungsnotizen (Bau, 2026-11-21)
- Gebaut wie oben beschrieben: Dienst `docker/compose/automations/alice-source-registry/` (Port 8012, keine nginx-Route), Schema in `sql/init-schema.sql` Abschnitt 16 + Migration `sql/migrations/2026-11-20_PROJ-115_source_registry.sql`, Eintrag in `docker/compose/scripts/Makefile`.
- Der Host-Ordner kommt aus `SOT_NAS_DIR` (in der `.env` des Dienstes, von Compose für den Bind-Mount nach `/data/sot` gelesen). Das Image legt `/data/sot` leer an; ohne Mount (Container-Test) entsteht dort ein frisches Repo.
- Ergänzung zu C.8: Gibt es noch keine Prüfmarke `refs/alice/scanned` (erster Prüflauf oder verlorene Referenz), vergleicht der erste Prüflauf einmal alle versionierten Quell-Markdowns mit ihrem Fingerabdruck. Sonst würde ein Commit des Menschen vor dem ersten Prüflauf übersehen.
- Der Container läuft als root (wie die übrigen Dienste ohne `nas-base`); Schreibrechte auf der NAS-Freigabe regeln deren Mount-Optionen.
- Abweichungen von der Spec: keine.
