# Architektur: PROJ-123 Mail-Import in den ETL (#17)

**Spec:** [spec.md](spec.md) · **Stand:** 2026-11-26

## A) Betroffene Bausteine
```
alice-mail-import (Container, NEU, Python/FastAPI, Port 8019, nur Docker-Netz, keine nginx-Route)
+-- Takt je Postfach (Sync-Intervall): IMAP nur lesend, INBOX + Gesendet, neue Mails zuerst,
|   danach Historie in Paketen; Archivieren (.eml + ausgelagerte Anhänge), Registrieren (Stufe detect)
+-- Stufe extract für kind email: Mail-Markdown aus der archivierten .eml (ohne LLM, ohne IMAP)
+-- Stufe classify für kind email: category + deutsche summary über alice-llm-gateway (Hintergrund)
+-- Nachtlauf je Postfach: verschwundene Fundorte entfernen (20-%-Grenze), gelöschte Postfächer,
|   fehlende Mails nachholen, UIDVALIDITY-Wechsel neu zuordnen
+-- Abgleich-Schnittstelle für PROJ-120: Ebene 5 „IMAP ↔ Register“, Ebene 6 „Register ↔ Mail-Archiv“
+-- pflegt die Statusfelder in alice.imap_mailboxes (Settings-Tab ohne Frontend-Änderung)
+-- GET /health, GET /status

alice-source-registry (PROJ-115, Erweiterung)
+-- Mail-Fundort = Postfach + Ordner + UID + Message-ID (bisher Postfach + Message-ID)
|   Ordner gehört zum Schlüssel, die UID ist veränderlich (UIDVALIDITY-Wechsel, EC-4)

alice-etl-rebuild (PROJ-120, Erweiterung)
+-- Abgleich ruft alice-mail-import für die Ebenen 5 und 6 (prüfen, dann reparieren über den Mail-Import)

PostgreSQL (Schema alice):
+-- NEU mail_import_mailboxes   je Postfach: stabiler Archiv-Schlüssel, Nachtlauf-Ergebnis
+-- NEU mail_import_folders     je Postfach + Ordner: UIDVALIDITY, Startmarke ohne Startdatum
+-- NEU mail_archive            je Mail-Quelle: Pfad der .eml, Anhänge, „nicht zerlegbar“-Ursache
+-- NEU mail_import_runs        Nachtläufe mit Zusammenfassung (u. a. „blockiert“)
+-- source_locations: neue Spalten folder, uid; Eindeutigkeit inkl. Ordner
+-- pipeline_stages: database überspringt kind email
Mail-Archiv: NAS-Ordner /mnt/nas/ai/mail/ (konfigurierbar), außerhalb Repo und DMS-Ordnern
docker/compose/scripts/Makefile: neuer Stack automations/alice-mail-import
n8n: alice-mail-sync, -attachment-processor, -attachment-backfill, -reconcile werden beim Deploy deaktiviert
```
Unverändert: `alice-mail-reader`, `alice-mail-api` (n8n), `alice-mail-tools` (n8n), Settings-Frontend, `alice-text-extraction` und `alice-document-classify` (beide holen nur `kind: document`).

## B) Datenmodell

**Quelle einer Mail** (Register, PROJ-115): `kind: email`, Hash = `mid:` + SHA-256 der Message-ID (ohne spitze Klammern, Kleinschreibung). Mails ohne Message-ID bekommen `mfp:` + SHA-256 aus Absender, Datum, Betreff und Mail-Inhalt (Fingerabdruck). Weil das Register Quellen über den Hash eindeutig hält, ist jede Mail genau eine Quelle, egal in wie vielen Postfächern/Ordnern sie liegt. Titel = Betreff bzw. „(ohne Betreff)“, Erfassungszeit = Mail-Datum (fehlt es oder liegt es in der Zukunft: Empfangszeitpunkt auf dem Server).

**Fundort** (Register): Postfach-Schlüssel + Ordner + UID + Message-ID (bei Mails ohne Message-ID steht dort der Fingerabdruck). Ordner gehört zur Identität des Fundorts, die UID nicht: Wechselt UIDVALIDITY, wird nur die UID aktualisiert. Im Frontmatter steht `locations` als Liste aus `mailbox`, `folder`, `uid`, `message_id`.

**Postfach-Schlüssel** (`mail_import_mailboxes`): beim ersten Import einmal aus Anzeigename (Slug) und den ersten 8 Zeichen der Postfach-UUID gebildet, z. B. `privat-3f2a9c1d`. Er bleibt, auch wenn der Anzeigename geändert wird (EC-10), und dient als Ordnername im Archiv und als `mailbox` im Fundort. Die Zeile bleibt stehen, wenn das Postfach in den Settings gelöscht wird; daran erkennt der Nachtlauf das gelöschte Postfach. Dazu: letzter Nachtlauf und dessen Ergebnis.

**Ordnerzustand** (`mail_import_folders`): je Postfach + Ordner (`INBOX` bzw. der erkannte Gesendet-Ordner) die zuletzt gesehene UIDVALIDITY und die Startmarke (UIDNEXT beim ersten Import) für Postfächer ohne Startdatum. Der Fortschritt selbst ergibt sich aus den Fundorten im Register (welche UIDs schon bekannt sind); ein Neustart macht deshalb genau dort weiter (EC-12: nichts in Redis).

**Mail-Archiv-Eintrag** (`mail_archive`): je Mail-Quelle der relative Pfad der `.eml`, Postfach-Schlüssel, Liste der Anhänge (Dateiname, MIME-Typ, Größe, relativer Pfad) und bei nicht zerlegbaren Mails die Ursache. Grundlage für `extract` (ohne IMAP), Neuaufbau und Ebene 6.

**Nachtläufe** (`mail_import_runs`): Start, Ende, Zusammenfassung je Postfach (entfernte Fundorte, `deleted`, nachgeholt, blockiert mit Zahlen, nicht erreichbar).

**Postfach-Status** (`imap_mailboxes`, bestehend): PROJ-123 setzt `status` (`active`/`syncing`/`error`), `last_synced_at`, `last_error` (verständliche Ursache, nie Passwort), `mails_indexed` (Anzahl Mail-Quellen mit vorhandenem Fundort in diesem Postfach) und `next_sync_at` (nächster Takt).

**Archiv-Dateien:** `<Schlüssel>/<JJJJ>/<MM>/<id>.eml` und `<Schlüssel>/<JJJJ>/<MM>/<id>.attachments/<Dateiname>`. In der `.eml` ist jeder echte Anhang durch einen Teil `message/external-body` (Zugriffsart `local-file`, Name = Archivpfad der Datei) ersetzt; Mailprogramme zeigen ihn als Verweis an. Eingebettete `cid:`-Bilder bleiben unverändert drin.

**Mail-Markdown** (Frontmatter über das Register): Basisfelder + `from`, `to`, `cc`, (`bcc`), `date`, `message_id`, `in_reply_to`, `references`, `archive`, `attachments`, `category`, `summary`, `language`. Adressen als `{name, address}`. Pfade (`archive`, Anhänge) absolut wie bei den Dokument-Fundorten (`/mnt/nas/ai/mail/...`).

Alle neuen Tabellen mit Row Level Security und offenen Policies wie die übrigen Dienst-Tabellen (Zugriff nur über den Dienst-Datenbanknutzer, kein Endnutzer-Zugriff).

## C) Abläufe

1. **Takt** (Schleife alle paar Sekunden, je fälligem Postfach; Postfächer parallel, je Postfach höchstens eine Verbindung):
   1. Sperre je Postfach in PostgreSQL (Advisory-Lock): Läuft eine zweite Instanz, überspringt sie das Postfach (AK-9, AK-48).
   2. Archiv nicht erreichbar/beschreibbar oder Register nicht erreichbar → Pause mit Warnung im Log, nichts geändert, Postfach bleibt fällig (AK-44).
   3. Status `syncing`, Passwort entschlüsseln (nur im Speicher), anmelden. Fehler (Anmeldung abgelehnt, Host nicht erreichbar, Zeitüberschreitung) → Status `error` mit Ursache, nächster Versuch im nächsten Takt (AK-41).
   4. Ordner bestimmen: `INBOX` und der Ordner mit der IMAP-Kennzeichnung `\Sent`; ohne Kennzeichnung der konfigurierte Name (Standard `Sent`), falls vorhanden.
   5. Je Ordner nur lesend öffnen (`EXAMINE`), UIDVALIDITY prüfen (Wechsel → UIDs über die Message-ID neu zuordnen, EC-4), UIDs im Zeitraum suchen (`SINCE` Startdatum bzw. ab Startmarke) und mit den bekannten Fundorten vergleichen. Unbekannte UIDs: zuerst alle über der höchsten bekannten UID (neu eingegangen), dann höchstens eine Paketgröße Historie (neueste zuerst).
   6. Je Mail: Rohmail mit `BODY.PEEK[]` holen (setzt kein „gelesen“), Hash bilden. Hash bekannt → nur Fundort ergänzen (reaktiviert eine `deleted`-Quelle mit derselben `id`, AK-35). Neu → Anhänge in einen temporären Ordner im Archiv schreiben, im Register anlegen (`detect` = done), dann Anhangsordner auf `<id>.attachments` umbenennen und die `.eml` als temporäre Datei schreiben, auf die Platte bringen und umbenennen. So entsteht nie eine halbe Datei (AK-43, AK-45); vorhandene Dateien werden nie überschrieben (AK-16). Abbruch einer einzelnen Mail → diese im nächsten Takt erneut, die übrigen laufen weiter.
   7. Historie-Pakete registrieren mit Sammel-Commits (PROJ-115, höchstens 500 Dateien); neue Mails einzeln. Bleibt Historie übrig, ist das Postfach nach einer kurzen Pause wieder fällig, sonst nach dem Sync-Intervall.
   8. Status `active`, letzte Synchronisierung, Anzahl Mails.
2. **Stufe extract** (eigene Schleife): fällige Arbeit `extract` für `kind: email` übernehmen, `.eml` aus dem Archiv lesen, Frontmatter-Felder + Inhaltsteil bauen, über das Register schreiben, `done`. Nicht zerlegbare Mail → `failed_permanent` mit Ursache (AK-42). `.eml` fehlt → zurückgeben mit Verzögerung (kein Fehlversuch), Ebene 6 legt sie neu ab. Arbeit aus einem Neuaufbau (PROJ-120) läuft genauso, mit Sammel-Commits (AK-50).
3. **Stufe classify** (eigene Schleife, eine Mail gleichzeitig): `classify` für `kind: email` nach `extract`, Absender/Empfänger/Betreff + Anfang des Mailtexts (konfigurierbare Länge) an das Gateway mit eigenem Hintergrund-Schlüssel und ausdrücklich ohne Thinking; Antwort JSON `category` + `summary` (deutsch angefordert). Erlaubt sind `important`/`promotion`/`social`/`spam` (auch die deutschen Bezeichnungen werden angenommen). Ungültige Antwort oder Gateway nicht erreichbar → `fail` mit Backoff (AK-31); `manual` schützt `category` (AK-32). Commit „classify: <id> <title>“ macht das Register.
4. **Nachtlauf** (Standard 02:30, nachgeholt, wenn verpasst): je Postfach zuerst ein normaler Takt (nachholen, neu zuordnen), dann alle UIDs je Ordner mit den Fundorten vergleichen. Verschwundene Fundorte → über das Register entfernen; die letzte Fundstelle weg → `deleted`, Markdown nach `deleted/emails/…` (PROJ-115/116). Mehr als 20 % der bekannten Fundorte eines Postfachs weg → nichts entfernt, „blockiert“ (AK-36). Postfach nicht erreichbar oder leere Ordnerliste → nichts entfernt (AK-37). Postfach in den Settings gelöscht → alle seine Fundorte entfernt, ohne Grenze (AK-38). Das Archiv wird nie angefasst.
5. **Abgleich (PROJ-120):** `alice-etl-rebuild` ruft nach den Ebenen 1–4 `POST /reconcile/check` des Mail-Imports. Ebene 5: Mails im Zeitraum ohne Fundort (`mail_unregistered`, Reparatur `mail_import`); nicht erreichbare Postfächer erscheinen als Hinweis. Ebene 6: Quelle ohne `.eml` bzw. fehlende Anhangsdatei (`eml_missing`/`attachment_missing`, Reparatur `mail_rearchive`, wenn ein Fundort noch vorhanden ist, sonst nur gemeldet). Die Reparaturen zählen zur Sicherung gegen Massenreparatur und laufen über `POST /reconcile/repair`. Ist der Mail-Import nicht erreichbar, ist das Ergebnis „unvollständig“ mit Grund.

**Fehlerverhalten:** Register nicht erreichbar → Takt pausiert ohne Änderung. Archiv weg zwischen Registrierung und Ablage (sehr kurzes Fenster) → Quelle ohne `.eml`, `extract` wartet, Ebene 6 legt nach. Nie Passwörter oder Mailtexte in Logs und Fehlermeldungen; geloggt werden nur Postfach-Schlüssel, Ordner, UID und Quell-`id`.

## D) Technische Entscheidungen
- **Ein neuer Dienst für Import, extract, classify und Nachtlauf**, weil alle drei Stufen das Mail-Archiv bzw. Mail-Wissen brauchen und es kein vorhandenes Gegenstück gibt. `alice-mail-reader` bleibt unverändert (Settings bis PROJ-140).
- **IMAP mit der Standardbibliothek (`imaplib`) in Hilfs-Threads**, nur `EXAMINE` und `BODY.PEEK[]`: keine neue Abhängigkeit, und schreibende Befehle kommen im Code gar nicht vor (AK-4).
- **Fortschritt = bekannte Fundorte**, nicht ein UID-Zähler: Diff „UIDs auf dem Server im Zeitraum“ gegen „bekannte UIDs“ deckt Erstimport, Neustart, Lücken nach Abbruch, früheres Startdatum (AK-40) und Nachholen (AK-39) mit einer Regel ab.
- **Advisory-Lock in PostgreSQL je Postfach**, weil zwei Instanzen sich sonst nur über Redis abstimmen könnten (EC-12: Redis nicht nötig).
- **Passwort-Entschlüsselung im Dienst** (AES-256-CBC, Schlüssel = SHA-256 von `MAIL_ENC_KEY`, gleiches Format wie `alice-mail-reader`), weil es keine zweite Passwortablage geben soll und der Mail-Reader nicht geändert werden darf. Gleicher Wert von `MAIL_ENC_KEY` in der `.env`.
- **HTML → Markdown mit `markdownify` (BeautifulSoup)**, vorher Bilder, Skripte, Styles entfernt; Links und Tabellen bleiben.
- **Sprache ohne LLM** über Anteil deutscher bzw. englischer Funktionswörter (wie PROJ-118), unter 20 Wörtern leer.
- **Neue Abgleich-Ebenen als Nummern 5 und 6**: Die Ergebnistabellen erlauben Ebene 1–9, die ETL-Status-Ansicht zeigt Ebenen dynamisch an — keine Frontend-Änderung.
- **Mail-Archiv-Pfad absolut im Frontmatter**, wie die Dokument-Fundorte (`/mnt/nas/...`), damit Links ohne Umrechnung funktionieren.

## E) Abhängigkeiten
- Pakete: `fastapi`, `uvicorn`, `asyncpg`, `httpx`, `pycryptodome`, `markdownify`, `beautifulsoup4` (Python 3.12).
- Neue Umgebungsvariablen (Platzhalter in `.env.example`): `POSTGRES_DSN`, `REGISTRY_URL`, `MAIL_ENC_KEY`, `LLM_GATEWAY_URL`, `LLM_GATEWAY_KEY`, `CLASSIFY_MODEL`, `MAIL_ARCHIVE_PATH` (Standard `/mnt/nas/ai/mail`), `MAIL_SENT_FOLDER_FALLBACK` (`Sent`), `MAIL_BATCH_SIZE` (200), `MAIL_DELETE_LIMIT_PERCENT` (20), `MAIL_CLASSIFY_CHARS` (4000), `MAIL_NIGHTLY_TIME` (02:30), weitere optionale mit Standardwerten.
- `alice-etl-rebuild`: `MAIL_IMPORT_URL` (Standard `http://alice-mail-import:8019`, leer = Ebenen 5/6 aus).
- Gateway: neuer Eintrag `mail-import background <key>` in der `clients`-Datei.

## F) Test- und Deploy-Plan
| AK | Nachweis | Art |
|---|---|---|
| AK-1–4, AK-6–8, AK-40 | Fake-IMAP-Server (echtes IMAP-Protokoll über TCP, Ordner mit `\Sent`, Spam usw., Flags) + echtes Register-Code + Test-DB + Temp-Repo + Temp-Archiv | Integration |
| AK-5, AK-47 | neue Mail während Historie → nach einem Takt vorhanden | Integration |
| AK-9, AK-48 | zwei Importer parallel, Verbindungszähler des Fake-Servers | Integration |
| AK-10–16 | MIME-Beispiele (PDFs, cid-Bilder, rfc822, gleiche Namen, RFC-2231-Umlaut, 101-MB-Anhang), Parser-Prüfung der `.eml` | Unit + Integration |
| AK-17–27 | Markdown-Erzeugung (Frontmatter, Text/HTML, 50.000 Zeichen, Kodierungen, YAML-Sonderzeichen, Sprache, `manual`), Stufenzustände im Register | Unit + Integration |
| AK-28–32 | Gateway-Attrappe (Priorität = eigener Schlüssel, `enable_thinking: false`, Länge, deutsch, Fehler) | Unit + Integration |
| AK-33–39 | Nachtlauf gegen Fake-Server (löschen, ein Ordner, wiederherstellen, > 20 %, nicht erreichbar, Postfach gelöscht, nachholen), UIDVALIDITY-Wechsel | Integration |
| AK-41–45 | Anmeldefehler, kaputte MIME, Verbindungsabbruch, Archiv weg, Abbruch mitten im Import | Integration |
| AK-46 | 2.000 Mails, Commit-Zählung ≤ 500 Dateien | Integration |
| AK-49 | Statusfelder in `imap_mailboxes` nach Erfolg/Fehler | Integration |
| AK-50–53 | Neuaufbau-Freigabe ohne IMAP; Abgleich-Ebenen 5/6 im Mail-Import und im Ergebnis von `alice-etl-rebuild` | Integration |
| AK-54–56 | keine nginx-Route, Log-Prüfung, Deploy-Schritte im PR | Prüfung + Test |
| AK-57/58 | Live nach Deploy | Mensch |

Nicht ohne Produktivsysteme testbar: echter IMAP-Server (Gmail-Ordnernamen, Anbieter-Eigenheiten), NAS, LLM → Attrappen: Fake-IMAP-Server im Test, Temp-Ordner, Gateway-Mock. AK-57/58 prüft der Mensch.

Deploy-Schritte für den Menschen:
1. Migration `sql/migrations/2026-11-26_PROJ-123_mail_import.sql`.
2. Ordner `/mnt/nas/ai/mail` auf der beschreibbaren Freigabe anlegen (NAS-Konto).
3. Gateway-Schlüssel `mail-import background <key>` ergänzen, Gateway neu starten.
4. `.env` für `alice-mail-import` aus `.env.example` (gleicher `MAIL_ENC_KEY` wie `alice-mail-reader`).
5. n8n: `alice-mail-sync`, `alice-mail-attachment-processor`, `alice-mail-attachment-backfill`, `alice-mail-reconcile` deaktivieren.
6. `sync-compose.sh`, `make rebuild s=automations/alice-mail-import`, `make rebuild s=automations/alice-source-registry`, `make rebuild s=automations/alice-etl-rebuild`.

## Decision Log
| Entscheidung | Alternative | Abwägung |
|---|---|---|
| Ein Dienst für Import + extract + classify | drei Dienste bzw. Erweiterung von `alice-text-extraction`/`alice-document-classify` | Mail-Wissen (Archiv, MIME) an einer Stelle; die Dokument-Dienste bleiben unverändert und holen weiter nur `document` |
| Fundort-Schlüssel Postfach + Ordner + Message-ID, UID als Attribut | UID im Schlüssel | UIDVALIDITY-Wechsel würde sonst Massen-Fundorte erzeugen/entfernen (EC-4) |
| Fortschritt aus den Fundorten | `last_uid` je Ordner | Ein Zähler kann Lücken nach Abbrüchen nicht erkennen; Diff ist idempotent |
| Advisory-Lock je Postfach | Redis-Lock | Zustand nur in PostgreSQL (EC-12) |
| Anhänge zuerst temporär, Registrierung, dann Umbenennen | Registrierung zuerst | Archiv-Ausfall vor der Registrierung ändert das Register nicht (AK-44) |
| `message/external-body` als Verweis in der `.eml` | Text-Platzhalter | Standard-MIME, Mailprogramme zeigen den Verweis als Anhang-Eintrag |
| Ebenen 5/6 über Schnittstelle des Mail-Imports | IMAP-Zugriff in `alice-etl-rebuild` | Nur ein Dienst kennt Passwörter und IMAP |

## Umsetzung (Bau, 2026-11-26)
- Gebaut wie oben: neuer Dienst `docker/compose/automations/alice-mail-import/` (Port 8019, keine nginx-Route, `nas-base` für `/mnt/nas/ai`), Schema Abschnitt 20 in `sql/init-schema.sql` + Migration `sql/migrations/2026-11-26_PROJ-123_mail_import.sql`, Makefile-Eintrag.
- `alice-source-registry`: Mail-Fundort nimmt `folder` und `uid` an; Eindeutigkeit jetzt inkl. Ordner (Index `idx_source_locations_key_folder` ersetzt `idx_source_locations_key`), eine neue UID im selben Ordner aktualisiert den Fundort statt einen neuen anzulegen. Ältere Mail-Fundorte ohne Ordner bleiben gültig.
- `alice-etl-rebuild`: neue Variable `MAIL_IMPORT_URL`; Ebene 5 (`mail_unregistered`, Reparatur „nachholen“) und Ebene 6 (`eml_missing`/`attachment_missing`, Reparatur „neu ablegen“ nur, wenn ein Fundort noch vorhanden ist). Ebenen 5/6 erscheinen nur, wenn der Mail-Import konfiguriert ist; ist er bzw. ein Postfach nicht erreichbar, ist das Ergebnis „unvollständig“ mit Grund.
- Sammel-Commits: Ein Paket mit mehr als `MAIL_BATCH_THRESHOLD` (20) Mails wird als Sammel-Commit registriert, kleinere Takte (z. B. eine neue Mail) einzeln. `extract` schreibt als Sammel-Commit, wenn es mehrere Mails auf einmal übernimmt.
- Zeitraum „ab Startdatum“ richtet sich nach dem Empfangsdatum auf dem Server (IMAP `SINCE`), nicht nach dem `Date`-Header.
- Ordnernamen werden so gespeichert, wie der Server sie meldet (bei Nicht-ASCII-Namen in modifiziertem UTF-7).
- Bei Mails ohne Message-ID steht im Fundort `message_id: fp:<Fingerabdruck>`, das Feld `message_id` im Frontmatter bleibt leer.
- Abweichungen von der Spec: keine.
