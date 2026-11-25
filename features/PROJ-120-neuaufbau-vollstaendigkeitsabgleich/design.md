# Architektur: PROJ-120 Neuaufbau + Vollständigkeitsabgleich (#12)

**Spec:** [spec.md](spec.md) · **Stand:** 2026-11-24

## A) Betroffene Bausteine
```
alice-etl-rebuild (Container, NEU, Python/FastAPI, Port 8017, nur Docker-Netz, keine nginx-Route)
+-- Neuaufbau-Läufe: Start (Momentaufnahme), Freigabe in Portionen, Pause/Fortsetzen/Abbruch,
|   Neustart-fest, Fortschritt (Zwischenspeicher, alle 2 s neu), Log-Zeilen, Fehlerliste
+-- Vollständigkeitsabgleich: Zeitplan (nachts, Nachholen), auf Abruf, nach Neuaufbau;
|   Ebenen 1–4, Sicherung gegen Massenreparatur, Ergebnisse + Lücken, Aufbewahrung
+-- liest Register- und Dokument-Tabellen nur lesend; ändert Stufen und Markdowns
|   ausschließlich über alice-source-registry; kein NAS-, Repo-, Redis- oder Weaviate-Zugriff
+-- GET /health

alice-source-registry (PROJ-115, Erweiterung)
+-- Neuaufbau-Kennzeichen je Stufenzustand: Freigabe durch den Lauf, Vorrang Normalbetrieb
|   bei der Übernahme, Schreibvorgänge solcher Stufen automatisch als Sammel-Commit
+-- „bediente Stufen“: merkt sich je Stufe und Art, dass ein Stufen-Dienst dort Arbeit übernommen hat
+-- Ebene 2 (Register ↔ Repo): Prüfung und Reparatur (Wiederherstellen, Neu anlegen, Verschieben)
+-- Ereignis an einer Quelle eintragen (für Reparaturen anderer Ebenen)

alice-file-detection (PROJ-116, Erweiterung)
+-- Ebene 1 (NAS ↔ Register): Prüfung, Registrieren fehlender Dateien, rollierendes Neu-Hashen,
|   Anwenden abweichender Hashes (Regeln wie im Nachtlauf)
+-- „Abgleich-Sperre“ (Lease): während eines Abgleichs startet kein Nachtlauf und umgekehrt

PostgreSQL (Schema alice):
+-- NEU rebuild_runs, rebuild_items, reconcile_results, reconcile_gaps          (alice-etl-rebuild)
+-- NEU pipeline_stage_served; source_stages.rebuild_run (neue Spalte)          (Register)
+-- NEU detect_hash_cycle; detect_files.rehashed_at (neue Spalte)              (Erkennung)
docker/compose/scripts/Makefile: neuer Stack automations/alice-etl-rebuild
```
Kein Frontend (kommt mit PROJ-122), keine n8n-Änderung, kein Redis/Weaviate im neuen Dienst. Die Stufen-Dienste `alice-text-extraction`, `alice-document-classify`, `alice-document-database` bleiben unverändert.

## B) Datenmodell

**Neuaufbau-Lauf** (`rebuild_runs`): Startstufe, optionale Art, Umfang je Art (geltende Stufen und „nicht bediente“ Stufen, beim Start festgehalten), Status (`running`/`paused`/`waiting`/`done`/`cancelled` = läuft/pausiert/wartet/abgeschlossen/abgebrochen) mit Grund, „gestartet von“, Start, Ende, Gesamtzahl, Ausnahmen je Grund, Endzahlen, zugehöriges Abgleich-Ergebnis. Läufe bleiben dauerhaft.

**Quellen eines Laufs** (`rebuild_items`): Momentaufnahme beim Start, eine Zeile je Quelle: Art, Reihenfolge, Ausnahme-Grund (leer = gehört zum Lauf), Freigabezeitpunkt (leer = noch nicht freigegeben), Zeitpunkt „alle Stufen durch“ (für den Durchsatz). Ausnahme-Gründe: `deleted` (gelöscht), `locked` (gesperrt), `skipped` (alle Stufen im Umfang sind für die Art `skipped`, z. B. audio), `not_served` (keine Stufe im Umfang wird für die Art schon bedient, z. B. image heute). Eine Quelle, die während des Laufs gelöscht oder gesperrt wird, wird nicht mehr freigegeben und wechselt zu „ausgenommen“ (EC-1).

**Neuaufbau-Kennzeichen** (`source_stages.rebuild_run`): Nummer des Laufs, der die Stufe dieser Quelle auf `pending` gesetzt hat. Normalbetrieb (Inhaltsänderung, Hand-Korrektur, „erneut versuchen“, in-place geändertes Original) löscht das Kennzeichen wieder, die Arbeit gilt dann als Normalbetrieb.

**Bediente Stufen** (`pipeline_stage_served`): Paare (Stufe, Art) mit Zeitpunkt der ersten Übernahme. Eingetragen, sobald die Übernahme (claim) einer Stufe erstmals eine Quelle dieser Art ausgibt oder eine Registrierung die Stufe gleich als erledigt meldet (`detect`). Die Migration füllt sie aus dem Bestand (jede Stufe/Art, die schon einmal `done`, `running` oder fehlgeschlagen war) – heute: `detect` für alle Arten, `extract`/`classify`/`database` für `document`.

**Abgleich-Ergebnis** (`reconcile_results`): Art (`nightly`/`on_demand`/`after_rebuild`), Umfang (`levels` = Ebenen 1–4 bzw. nachts zusätzlich eine Hash-Portion, `full_rehash` = vollständiges Neu-Hashen), zugehöriger Lauf, Start, Ende, Dauer, Status (`running`/`complete`/`incomplete` = läuft/vollständig/unvollständig) mit Grund, Sicherung gegriffen ja/nein, Zusammenfassung (je Ebene Anzahl Lücken, Reparaturen, Meldungen; übersprungene Ordner; Fortschritt des Hash-Zyklus).
**Lücken** (`reconcile_gaps`): je Lücke Ebene, Art der Lücke, Quelle (falls bekannt), Pfad, Beschreibung, Reaktion (`repaired`/`reported`/`repair_failed`). Aufbewahrung der Ergebnisse samt Lücken einstellbar (Standard 90 Tage, mindestens 30).

**Hash-Zyklus** (Erkennung): `detect_files.rehashed_at` je Pfad und `detect_hash_cycle` (Beginn des laufenden Zyklus). Ein Pfad ist im Zyklus erledigt, sobald er nach Zyklusbeginn neu gehasht wurde; der Fortschritt wird nach jeder Datei gespeichert (Neustart setzt fort).

Alle neuen Tabellen mit RLS und offenen Policies wie die übrigen Dienst-Tabellen (nur Dienst-Datenbanknutzer, kein Endnutzerzugriff).

## C) Abläufe

### Neuaufbau starten (AK-1–7)
1. Aufruf mit Startstufe, optional Art, „gestartet von“. Abgelehnt (409 mit Nummer und Status des bestehenden Laufs), wenn ein Lauf läuft, pausiert ist oder wartet. Startstufe muss existieren und hinter `detect` liegen.
2. Umfang je Art: Startstufe und alle folgenden Stufen (Reihenfolge aus dem Register), soweit sie für die Art nicht `skipped` und schon **bedient** sind (Entscheidung zur Rückfrage vom 2026-11-24, Option A). Nicht bediente Stufen stehen im Fortschritt als „nicht bedient“. Eine später hinzukommende Stufe gehört dazu, sobald ihr Dienst einmal Arbeit übernommen hat (AK-3).
3. Momentaufnahme: alle Quellen (ggf. der Art) als `rebuild_items` in einem Schritt; Ausnahmen mit Grund. Neue Quellen danach gehören nicht dazu (AK-6). Lauf mit 0 Quellen endet sofort als abgeschlossen, Abgleich läuft trotzdem (EC-4).

### Freigabe in Portionen (AK-4, AK-10, AK-13–16, AK-40)
Eine Schleife (alle 2 s) je aktivem Lauf:
1. Register erreichbar und Repo verfügbar (Health)? Nein → Status `wartet` mit Grund, keine Freigabe; danach selbstständig `läuft` (AK-40). PostgreSQL weg → ebenso.
2. Freigegebene Quellen, die inzwischen gelöscht oder gesperrt sind → ausgenommen.
3. Je Stufe zählen, wie viele Quellen des Laufs gerade `pending`/`running` sind. Die nächsten Quellen (feste Reihenfolge) werden freigegeben, solange **jede** ihrer Stufen im Umfang noch Platz unter N hat (AK-10). N je Stufe einstellbar, Standard 50.
4. Freigabe über das Register in einem Aufruf je Portion: die Stufen im Umfang → `pending`, Versuchszähler 0, Fehler leer, Kennzeichen = Lauf (AK-4). Stufen, die gerade `running` sind, bleiben unberührt (sie laufen ohnehin mit dem aktuellen Stand). Wiederholte Freigabe derselben Quelle für denselben Lauf ändert nichts (keine Doppelfreigabe nach Absturz, AK-16). Danach Freigabezeitpunkt speichern.
5. Ende: alle Quellen des Laufs freigegeben und jede Stufe im Umfang `done`, `skipped` oder `failed_permanent` → `abgeschlossen`, Log-Zeile, automatischer Abgleich der Art „nach Neuaufbau“, dessen Ergebnis am Lauf hängt (AK-1, AK-17). `failed` (Backoff) zählt noch nicht als Ende (EC-5).
- **Pausieren:** keine Freigaben mehr, freigegebene laufen zu Ende; **Fortsetzen** macht mit den noch nicht freigegebenen weiter (AK-13/14).
- **Abbrechen:** Status sofort `abgebrochen`, keine Freigaben mehr; nicht freigegebene Quellen bleiben unverändert (AK-15). Ende-Zeitpunkt, sobald die freigegebenen durch sind. Kein Abgleich danach.
- **Neustart:** Status steht in PostgreSQL; `läuft`/`wartet` setzt fort, `pausiert` bleibt (AK-16, EC-11).

### Vorrang und Sammel-Commits im Register (AK-9, AK-11, EC-2, EC-3)
- Die Übernahme (claim) ordnet Arbeit ohne Kennzeichen vor Arbeit mit Kennzeichen, danach wie bisher nach Fälligkeit. Neuaufbau-Arbeit kommt nicht in die Redis-Queue; Übernahmen über die Queue füllen fehlende Plätze aus dem Register auf.
- Schreibt eine Stufe die Quell-Markdown, während ihr Stufenzustand das Kennzeichen trägt, schreibt das Register automatisch als Massenlauf mit Sammel-Commit (`rebuild: <stufe> <n> sources`, ≤ 500 Dateien). Die Stufen-Dienste ändern sich nicht.
- Hand-Korrekturen, „erneut versuchen“ und Inhaltsänderungen löschen das Kennzeichen → normaler Vorrang; `manual` bleibt durch PROJ-115 geschützt (AK-8). Die Quelle zählt im Lauf trotzdem genau einmal.
- LLM-Aufrufe der Klassifizierung laufen schon heute mit dem Hintergrund-Schlüssel des Gateways (PROJ-118), auch im Neuaufbau (AK-12).

### Fortschritt (AK-18–22, EC-13)
- Ein Hintergrund-Task rechnet alle 2 s je aktivem Lauf (und einmal für beendete) die Zahlen mit einer gebündelten Abfrage aus und hält sie im Speicher. Der Abruf liefert nur diesen Stand (+ „Stand von“), ohne Datenbank-, NAS- oder Repo-Zugriff → < 200 ms auch bei 50.000 Quellen und vielen Abrufen, Zahlen ≤ 5 s alt (AK-20).
- Je Stufe: erledigt (`done`/`skipped`), fehlgeschlagen (`failed`/`failed_permanent`), in Arbeit (`running`), offen (`pending` oder noch nicht freigegeben); Summe je Stufe = Quellen im Lauf mit dieser Stufe im Umfang.
- Durchsatz = Quellen, deren Stufen in der letzten Stunde fertig wurden; Restzeit = offene Quellen / Durchsatz, unbekannt bei Durchsatz 0 (EC-13).
- Fehlerliste (seitenweise): freigegebene Quellen mit fehlgeschlagener Stufe im Umfang: `id`, Titel, Stufe, Meldung.
- Log: Fortschrittszeile alle 15 min (einstellbar) sowie bei Start, Pause, Fortsetzen, Abbruch, Warten/Weiter und Ende.

### Vollständigkeitsabgleich (AK-23–43)
Höchstens ein Abgleich gleichzeitig (weitere Anforderung → 409, EC-12). Ablauf:
1. **Abgleich-Sperre bei der Erkennung holen** (wird während des Abgleichs regelmäßig verlängert, verfällt nach einigen Minuten von selbst). Läuft gerade ein Nachtlauf, wartet der Abgleich; solange die Sperre besteht, startet kein Nachtlauf (AK-35). Tagesscans laufen weiter (Aktualität).
2. **Prüfen (ohne etwas zu ändern):**
   - Ebene 1 (Erkennung): alle aktiven, erreichbaren überwachten Ordner vollständig auflisten (Endungs-/Übersprunglisten, verschachtelte Ordner, „nicht lesbar/leer“-Schutz genau wie im Nachtlauf). Datei ohne vorhandenen Fundort im Register → Lücke „nicht registriert“. Vorhandener Fundort in einem gelisteten Ordner ohne Datei → Lücke „Datei fehlt“ (nur melden). Übersprungene Ordner werden genannt, ihre Fundorte gelten nicht als fehlend (AK-42); deaktivierte Ordner werden nicht geprüft (EC-8).
   - Neu-Hashen (nachts eine Portion, auf Abruf vollständig): Pfade des laufenden Zyklus nacheinander hashen; abweichender Hash → Lücke „Inhalt geändert“; nicht lesbar oder verschwunden → melden, ohne Fortschritt, nächster Durchlauf versucht es erneut (AK-43). Portion je Nacht: Datenmenge = Bestand / Zyklustage (Standard 30), höchstens die Zeitgrenze; eine Datei wird immer ganz gehasht (EC-10). Ist der Zyklus durch und älter als die Zyklusdauer, beginnt ein neuer.
   - Ebene 2 (Register): Quellen ohne Markdown (wiederherstellbar aus Git oder nicht), Markdown am falschen Ort (gelöscht ↔ `deleted/`), Markdown ohne Registereintrag, `id`/`kind` passen nicht. Dateien, deren Git-Fingerabdruck dem Register entspricht, werden nicht gelesen.
   - Ebene 3 (eigene Abfrage): nicht gelöschte Quelle, bediente Stufe länger als die Grenze (Standard 24 h) `pending` → melden; ausgenommen Quellen offen in einem aktiven Lauf (AK-29, EC-6) und Stufen, vor denen schon eine Stufe derselben Quelle sichtbar fehlgeschlagen ist (Folge eines sichtbaren Fehlers, keine stille Lücke).
   - Ebene 4 (eigene Abfrage): `document` nicht gelöscht, `database` = `done`, keine Dokument-Zeile → Lücke; Dokument-Zeile zu gelöschter oder unbekannter Quelle → Lücke.
3. **Sicherung:** Anzahl geplanter Reparaturen / Anzahl Quellen im Register > Schwelle (Standard 5 %) → nichts reparieren, alles melden, „Sicherung gegriffen“ im Ergebnis (AK-33).
4. **Reparieren** (sonst): nicht registrierte Datei → registrieren wie eine neue Datei (Erkennung, Stabilität und Hash wie im Nachtlauf); abweichender Hash → wie ein in-place geändertes Original (Erkennung, inkl. EC-9); Markdown fehlt → letzter Stand aus Git, sonst Basis-Markdown + Stufen ab `extract` `pending` (Register); falscher Ort → Git-Umbenennung (Register); `database` fehlt → `database` erneut (Register); verwaiste Dokument-Zeile → löschen samt abhängigen Zeilen (Kaskade). Jede Reparatur erzeugt ein Ereignis an der Quelle (AK-34) und wird im Ergebnis gezählt.
5. **Ergebnis** speichern + Log-Zeile; Sperre zurückgeben; Ergebnisse älter als die Aufbewahrung löschen.
- **Störungen:** Register/Repo nicht erreichbar oder PostgreSQL weg → Abbruch, Ergebnis `unvollständig` mit Grund, keine weiteren Reparaturen (AK-41). Erkennung nicht erreichbar → Ebene 1 als unvollständig mit Grund, übrige Ebenen laufen. Neustart mitten im Abgleich → beim Start als `unvollständig` (Grund: Neustart) markiert; das Neu-Hashen setzt beim nächsten Mal an derselben Stelle fort (AK-37).
- **Zeitplan:** nachts zur eingestellten Uhrzeit (Standard 03:00, nach dem Nachtlauf um 02:00), mit Nachholen nach Neustart (wie PROJ-116). Auf Abruf sofort (AK-38).

### Schnittstelle (für PROJ-122)
`POST /rebuilds` (Startstufe, Art, gestartet von) · `GET /rebuilds` (seitenweise) · `GET /rebuilds/current` · `GET /rebuilds/{id}` (Fortschritt) · `POST /rebuilds/{id}/pause|resume|cancel` · `GET /rebuilds/{id}/errors` (seitenweise) · `POST /reconcile` · `POST /reconcile/full-rehash` · `GET /reconcile/results` (seitenweise) · `GET /reconcile/results/{id}` · `GET /reconcile/results/{id}/gaps?level=` (seitenweise) · `GET /health`. Keine Authentifizierung (wie PROJ-115/116, nur Docker-Netz), Eingaben werden geprüft.

## D) Technische Entscheidungen
- **Neuer Dienst für Lauf und Abgleich**, weil weder Register noch Erkennung Zeitplan, Lauf-Zustand und Ergebnisse tragen sollen; der neue Dienst braucht weder NAS noch Repo und kann den Fortschritt dadurch garantiert ohne NAS-/Repo-Last liefern (AK-20).
- **Ebene 1 in der Erkennung, Ebene 2 im Register**, weil nur diese Dienste die NAS-Freigaben bzw. das Repo eingebunden haben und dort die Regeln von PROJ-115/116 schon stehen (Endungen, Stabilität, in-place-Änderung, Git-Wiederherstellung). Keine doppelte Logik.
- **Erst prüfen, dann reparieren:** Die 5-%-Sicherung braucht die Gesamtzahl vor der ersten Reparatur; ein Ausfall während der Prüfung führt deshalb nie zu Teil-Reparaturen.
- **Kennzeichen am Stufenzustand** statt eigener Queue: Vorrang und Sammel-Commits entstehen im Register an einer Stelle, ohne dass sich die Stufen-Dienste ändern; das Kennzeichen übersteht Neustarts (PostgreSQL) und Redis-Ausfälle (EC-11).
- **Bediente Stufen automatisch** (Rückfrage 2026-11-24, Option A): keine Pflege-Liste, Folge-Features (PROJ-125/126/127/129) werden ohne Anpassung Teil von Neuaufbau und Ebene 3.
- **Drosselung über alle Stufen einer Quelle:** Eine Quelle wird erst freigegeben, wenn jede ihrer Stufen Platz hat; so gilt „nie mehr als N je Stufe“ auch für spätere Stufen, deren Arbeit erst nach der vorigen fällig wird.
- **Fortschritt aus dem Speicher**, alle 2 s neu berechnet: konstante Antwortzeit unabhängig von der Zahl der Abrufer.
- **Lesender Zugriff auf Register-/Dokument-Tabellen** für Momentaufnahme, Zählungen und Ebenen 3/4 (schnell, eine Abfrage statt tausender HTTP-Aufrufe). Alle Änderungen an Stufen und Markdowns laufen über die Register-Schnittstelle (Spec); nur verwaiste Dokument-Zeilen löscht der Dienst selbst (Ebene 4, so verlangt).
- **Abgleich-Sperre mit Ablaufzeit** statt gemeinsamer Datenbank-Sperre: ein abgestürzter Abgleich blockiert den Nachtlauf höchstens wenige Minuten.
- **Ebene 3 ignoriert Folgestufen eines sichtbaren Fehlers**, sonst würde jede `failed_permanent`-Extraktion zusätzlich als stille Lücke in Klassifizierung und DB gemeldet.

## E) Abhängigkeiten
- Pakete: `fastapi`, `uvicorn`, `httpx`, `asyncpg` (wie die übrigen Dienste).
- Neue Umgebungsvariablen `alice-etl-rebuild` (Platzhalter in `.env.example`): `POSTGRES_DSN`, `REGISTRY_URL`, `DETECTION_URL`, `REBUILD_STAGE_LIMIT` (50), `REBUILD_STAGE_LIMITS` (je Stufe, z. B. `classify=10`), `REBUILD_LOG_INTERVAL_SECONDS` (900), `RECONCILE_NIGHTLY_TIME` (03:00), `RECONCILE_TIMEZONE`, `RECONCILE_CATCHUP_HOURS` (6), `RECONCILE_PENDING_LIMIT_HOURS` (24), `RECONCILE_REPAIR_LIMIT_PERCENT` (5), `RECONCILE_HASH_CYCLE_DAYS` (30), `RECONCILE_HASH_PORTION_SECONDS` (3600), `RECONCILE_HASH_PORTION_BYTES` (leer = Bestand / Zyklustage), `RECONCILE_RETENTION_DAYS` (90).
- Register und Erkennung: keine neuen Variablen.

## F) Test- und Deploy-Plan
| AK | Nachweis | Art |
|---|---|---|
| AK-1–7, EC-1, EC-4 | Register in-process (Test-DB, temporäres Git-Repo), simulierte Stufen-Worker über die Register-Schnittstelle | Integration |
| AK-8 | `manual`-Feld, Neuaufbau ab `extract`, simulierte Stufen schreiben andere Werte → Markdown unverändert; DB-Stufe von PROJ-119 übernimmt das Frontmatter (dort getestet) | Integration |
| AK-9 | 1.200 Quellen, Neuaufbau ab `extract`, Commits zählen (Sammel-Commits, kein Einzel-Commit) | Integration |
| AK-10 | N = 20, 500 Quellen, nach jeder Runde Zustände zählen | Integration |
| AK-11 | Normal- und Neuaufbau-Arbeit fällig → Übernahme liefert zuerst Normalarbeit | Integration (Register) |
| AK-12 | Klassifizierung nutzt den Hintergrund-Schlüssel (PROJ-118-Tests) | Durchsicht + bestehender Test |
| AK-13–16 | Pause/Fortsetzen/Abbruch/Neustart (neue Dienst-Instanz auf derselben DB) | Integration |
| AK-17, AK-22 | Ergebnis „nach Neuaufbau“ am Lauf; Liste der Läufe | Integration |
| AK-18, AK-19, AK-21 | Fortschrittsfelder, Fehlerliste, Log-Zeilen (kurzes Intervall, Zeit vorgestellt) | Integration |
| AK-20 | 50.000 Quellen per SQL, 20 Abrufe/s über die HTTP-Schnittstelle, Zeit je Abruf, keine Register-/NAS-Aufrufe | Integration |
| AK-23–25, AK-36, AK-37, AK-42, AK-43, EC-9, EC-10 | Erkennung in-process mit Temp-Ordnern als NAS | Integration (Erkennung) |
| AK-26–28 | Register in-process: Markdown löschen (mit/ohne Git-Stand), falscher Ort, verwaiste/falsche Markdown | Integration (Register) |
| AK-29–34, AK-38, AK-39, AK-41, EC-12 | Abgleich über alle drei Dienste in-process | Integration |
| AK-35 | Nachtlauf aktiv → Sperre verweigert, Abgleich wartet; Sperre aktiv → kein Nachtlauf | Integration |
| AK-40 | Register-Attrappe 503 → `wartet`, danach `läuft` | Integration |
| AK-44, AK-45 | keine nginx-Route, kein Port in compose, keine Redis-/Weaviate-Anbindung, Originale nur lesend | Durchsicht + Container-Test |
| AK-46 | Schema auf frischer DB, Migration zweimal auf altem Stand | psql |
| AK-47–49 | Live nach Deploy | Mensch |

Nicht ohne Produktivsysteme testbar: echter Bestand, echte Stufen-Dienste mit LLM, Chat-Last → Attrappen: simulierte Stufen-Worker, Temp-Ordner als NAS, temporäres Git-Repo.

Deploy-Schritte für den Menschen:
1. Migration `sql/migrations/2026-11-24_PROJ-120_rebuild_reconcile.sql` anwenden.
2. `.env` für `alice-etl-rebuild` aus `.env.example`.
3. `./scripts/sync-compose.sh`, Rebuild `alice-source-registry` und `alice-file-detection`, Start `alice-etl-rebuild`.
4. Live-Tests AK-47–49.

## Decision Log
| Entscheidung | Alternative | Abwägung |
|---|---|---|
| Neuer Dienst `alice-etl-rebuild` + Prüf-/Reparatur-Endpunkte in Register und Erkennung | alles in der Erkennung | Erkennung bleibt bei Dateien; der neue Dienst braucht keine Freigaben, Fortschritt ohne NAS-Last |
| Kennzeichen `rebuild_run` am Stufenzustand | eigene Queue / Stufen-Dienste ändern | keine neue Infrastruktur, Stufen-Dienste unverändert, Vorrang an einer Stelle |
| Bediente Stufen automatisch (Option A) | feste Liste; Stufen aus dem Register entfernen | Antwort des Menschen 2026-11-24 |
| Prüfen vor Reparieren | sofort reparieren | 5-%-Sicherung und „nichts reparieren nach Ausfall“ sind nur so sicher |
| Lease bei der Erkennung | Abgleich-Zeit fest nach dem Nachtlauf | garantiert „nie gleichzeitig“ auch bei langen oder nachgeholten Nachtläufen |
| Fortschritt im Speicher, 2 s Takt | Abfrage je Abruf | < 200 ms bei 50.000 Quellen und vielen Abrufern |
| Hash-Zyklus je Pfad in `detect_files` | eigener Cursor | Fortschritt je Datei gespeichert, Neustart-fest, keine Doppel-Hashes im Zyklus |

## Umsetzung (Bau, 2026-11-24)

**Gebaut**
- Neuer Dienst `docker/compose/automations/alice-etl-rebuild` (Port 8017, nur Docker-Netz `backend`, keine nginx-Route, Eintrag im Makefile): `rebuild.py` (Läufe, Freigabe, Fortschritt im Speicher), `reconcile.py` (Abgleich, Sicherung, Reparaturen, Ergebnisse), `clients.py` (Register, Erkennung), `main.py` (Schnittstelle, Hintergrund-Schleife alle 2 s, `/health`).
- Register (`alice-source-registry`): `POST /rebuild/release`, `POST /sources/{id}/events`, `GET /maintenance/repo-check`, `POST /maintenance/repo-repair`; Kennzeichen `rebuild_run` (Vorrang bei der Übernahme, automatischer Sammel-Commit beim Schreiben, gelöscht bei Inhaltsänderung/Hand-Korrektur/„erneut versuchen“/in-place-Änderung, nie in der Redis-Queue); `pipeline_stage_served` wird bei Übernahme und Registrierung mit `complete` gepflegt. Antwort der Übernahme enthält zusätzlich `rebuild` (abwärtskompatibel).
- Erkennung (`alice-file-detection`): `app/reconcile.py` mit `POST /reconcile/lease|check|register|rehash|apply` und `DELETE /reconcile/lease/{token}`; der Zeitplaner startet keinen Nachtlauf, solange die Sperre besteht.
- Schema-Abschnitt 19 in `sql/init-schema.sql` + Migration `sql/migrations/2026-11-24_PROJ-120_rebuild_reconcile.sql` (füllt `pipeline_stage_served` aus dem Bestand).

**Präzisierungen**
- Stufen, die wegen eines endgültigen Fehlers (`failed_permanent`) einer früheren Stufe derselben Quelle nie laufen können (z. B. `classify`, wenn `extract` endgültig fehlschlug), zählen im Fortschritt als „fehlgeschlagen“, belegen keinen Drosselungsplatz und gelten für das Ende des Laufs als durch. Das gilt auch, wenn die fehlgeschlagene Stufe **vor der Startstufe** liegt (Neuaufbau ab `database`, `extract` endgültig fehlgeschlagen). Sonst würde ein solcher Lauf nie fertig. In der Fehlerliste steht die Stufe mit dem eigentlichen Fehler, auch wenn sie vor der Startstufe liegt.
- Ebene 3 meldet keine Stufen gesperrter Quellen (die Sperre ist ein sichtbarer Fehler) und keine Folgestufen eines sichtbaren Fehlers. Ein echter Rückstau (z. B. noch nicht klassifizierte Dokumente) erscheint nach 24 h dagegen als Lücke auf Ebene 3; das ist so gewollt (nichts bleibt still) und im Ergebnis je Lücke erklärt.
- Je Ergebnis und Ebene werden höchstens 10.000 Lücken einzeln gespeichert; die Zahlen im Ergebnis sind immer vollständig (`gap_list_truncated` nennt den Rest). Schutz gegen Millionen Zeilen bei einem großen Rückstau.
- Eine Quelle, deren Stufe bei der Freigabe gerade `running` ist (Normalbetrieb), wird nicht zurückgesetzt; sie läuft ohnehin mit dem aktuellen Stand und zählt im Lauf, sobald sie durch ist.
- Ist die Datei-Erkennung nicht erreichbar, läuft der Abgleich ohne Ebene 1 weiter und endet `unvollständig` mit Grund. Nur ein Ausfall von Register/Repo (oder PostgreSQL) bricht ab (AK-41).
- Die Prüfung von Ebene 2 liest nur Markdowns, deren Git-Fingerabdruck nicht dem Pipeline-Stand entspricht, und erkennt verschobene Markdowns (gleiche `id` an anderem Ort): Reparatur = zurücklegen.
- Entfernt der Abgleich eine verwaiste Kontoauszugs-Zeile, werden die Dubletten-Merker anderer Auszüge desselben Kontos erst bei deren nächster Übernahme neu bestimmt (der Verweis auf die entfernte Buchung wird von der DB sofort geleert).
- Die Abfragen über alle Quellen eines Laufs (Fortschritt, Ende, Fehlerliste) und Ebene 3 laufen mit erzwungenen Hash-Joins und einem Zeitlimit von 60 s. Bei veralteter Tabellenstatistik (z. B. direkt nach einer großen Momentaufnahme) hatte PostgreSQL in einem Testlauf einen Plan mit verschachtelten Schleifen gewählt, der bei 50.000 Quellen nicht mehr endete; mit Hash-Joins dauert die Abfrage ~0,25 s unabhängig von der Statistik. Nach der Momentaufnahme wird zusätzlich `ANALYZE alice.rebuild_items` ausgeführt.
- Abweichungen von der Spec: keine.

## Nacharbeit nach Abnahme Runde 1 (2026-11-24)
- **B-1:** Fortschritt, Ende und Fehlerliste eines Laufs berücksichtigen `failed_permanent` in **allen** früheren Stufen der Quelle, nicht nur in Stufen des Umfangs. Vorher blieb ein Neuaufbau ab `classify`/`database` mit endgültig fehlgeschlagener Extraktion für immer `läuft`, und ab N solcher Quellen wurde nichts mehr freigegeben; ein abgebrochener Lauf bekam nie ein Ende.
- **B-2:** Das rollierende Neu-Hashen beginnt einen neuen Zyklus, sobald der alte seine Dauer erreicht hat, auch wenn einzelne Dateien darin nicht gehasht werden konnten (unlesbar, verschwunden). Diese Dateien haben den ältesten Stand und kommen im neuen Zyklus zuerst dran; sie werden weiter gemeldet und erneut versucht (AK-43).
- **B-3:** Ebene 2 liest auch die Markdown gesperrter Quellen und meldet eine `id`/`kind`-Abweichung als `frontmatter_mismatch` (AK-27), auch nachdem PROJ-115 die Quelle beim Scan gesperrt hat. Unlesbares YAML einer gesperrten Quelle ist deren sichtbarer Sperrgrund und wird nicht zusätzlich als Abweichung gemeldet.
- Hinweis aus der Abnahme (zwei Ereignisse beim Verschieben: `file_moved` vom Register und `reconcile_moved`) unverändert gelassen: `file_moved` entsteht in der bestehenden Git-Logik von PROJ-115, `reconcile_moved` nennt den Abgleich als Auslöser; kein Verlust, kein Widerspruch zu AK-34.


## Deployment

**Datum:** 2026-11-25, von `dev` (Phase 4). Kein Staging.

**Schritte:**
1. Migration `sql/migrations/2026-11-24_PROJ-120_rebuild_reconcile.sql` (durch den Nutzer).
2. `.env` für `alice-etl-rebuild` (durch den Nutzer).
3. `./scripts/sync-compose.sh` (rsync-Code 23 nur wegen der Zeitstempel von `mqtt/config`, harmlos), Rebuild `alice-source-registry`, `alice-file-detection`, `alice-etl-rebuild` (durch den Nutzer). Alle drei `healthy`, Logs ohne Fehler.

**Mechanik-Test (statt AK-48/AK-49, Entscheidung des Nutzers):** Neuaufbau-Lauf 1 ab `database`, Art `document`.
- 850 Quellen, 2 ausgenommen (gelöscht), 848 im Lauf; nie mehr als 50 gleichzeitig freigegeben (Drosselung).
- Pausieren: keine neuen Freigaben, freigegebene liefen zu Ende (aktiv → 0); Fortsetzen: nahtlos weiter.
- Ende nach ~14 min: `abgeschlossen`, 848/848 erledigt, 0 fehlgeschlagen; automatischer Abgleich `after_rebuild` (Ergebnis 1): `vollständig`, 55.417 Quellen, 0 Lücken auf allen vier Ebenen, Sicherung nicht ausgelöst, Dauer 9,2 s.
- AK-48 (neue Datei ≤ 15 min während des Laufs) und AK-49 (Chat parallel zu einem `classify`-Lauf) nicht eigens geprüft: Neuaufbau-Läufe laufen in der Praxis ohne parallele Ablage; der Chat-Vorrang nutzt den Hintergrund-Schlüssel aus PROJ-118 (dort live geprüft). Bekannte Einschränkung aus PROJ-118: lange Buchungs-Extraktionen (56–133 s) können einen Chat-Aufruf im Gateway warten lassen; bei einem großen `classify`-Lauf beobachten.

**Nebenbefund (PROJ-119):** `alice-document-database` schreibt Kontoauszüge im Takt von ~5 s je Stück, andere Typen in Millisekunden. Für Läufe über den ganzen Bestand beobachten.

**Offen:** AK-47 — Ergebnis des ersten nächtlichen Abgleichs (03:00, 2026-11-26) prüfen.
