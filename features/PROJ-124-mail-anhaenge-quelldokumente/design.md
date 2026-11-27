# Architektur: PROJ-124 Mail-Anhänge als Quelldokumente (#19)

**Spec:** [spec.md](spec.md) · **Stand:** 2026-11-27

## A) Betroffene Bausteine
```
alice-mail-import (PROJ-123, Erweiterung, Port 8019, keine nginx-Route)
+-- NEU Schleife „Anhänge“: Mails mit erledigtem extract → Anhänge registrieren, Verweise in der Mail
|   nachtragen, Links bei Umbenennungen nachführen, nicht verarbeitete Endungen zählen
+-- Stufe extract (Mail-Markdown): baut bekannte Anhangs-ids und -Links gleich mit ein (Neuaufbau verliert nichts)
+-- Abgleich-Schnittstelle: neue Ebene 7 „Mail ↔ Anhangs-Quellen“ (prüfen + nachholen)
+-- GET /attachments/runs: gespeicherte Zusammenfassungen der nicht verarbeiteten Anhänge (für PROJ-122)

alice-file-detection (PROJ-116, Erweiterung)
+-- NEU GET /extensions: die wirksame Erkennungsliste (Endung → Art), einzige Stelle, an der sie gepflegt wird

alice-source-registry (PROJ-115, Erweiterung)
+-- `parents` zählt wie `locations` als Register-Feld: ein neuer Elternteil setzt keine Stufe zurück
+-- Dokument schreiben mit `keep_stages` (diese Stufen bleiben, wie sie sind) und eigenem Commit-Text `label`

alice-document-classify (PROJ-118, Änderung)
+-- Quelle mit `parents`: Betreff, Absender, Datum der ältesten Mail als Hinweis im Prompt

alice-etl-rebuild (PROJ-120, Erweiterung)
+-- Ebene 7 aus der Antwort des Mail-Imports übernehmen, Reparatur „Anhänge nachholen“ über den Mail-Import

PostgreSQL (Schema alice):
+-- NEU mail_attachment_mails   je Mail: Stand der Anhangs-Registrierung und der Verweise in der Mail
+-- NEU mail_attachments        je Anhang einer Mail: Endung, Größe, Hash, Ergebnis, Anhangs-Quelle, verlinkter Pfad
+-- NEU mail_attachment_runs    Zusammenfassungen „nicht verarbeitete Anhänge“ je Lauf (mind. 30 Tage)
```
Unverändert: `alice-mail-api`, `alice-mail-tools`, `alice-mail-reader`, Postfach-Verwaltung, Frontend (die ETL-Status-Ansicht zeigt Abgleich-Ebenen dynamisch an), `alice-text-extraction` (holt Anhangs-Dokumente wie jedes Dokument), nginx.

## B) Datenmodell

**Anhangs-Quelle** (Register, PROJ-115): eine ganz normale Quelle der Art aus der Erkennungsliste, Hash `sha256:…` wie bei PROJ-116, Fundort = absoluter Pfad der Archivdatei (`/mnt/nas/ai/mail/<Postfach>/<JJJJ>/<MM>/<Mail-id>.attachments/<Dateiname>`), `parents` = Mail-ids, Titel = Dateiname, Erfassungszeit = Mail-Datum der ersten Mail (daraus `documents/<JJJJ>/<MM>/…`). Keine neue Art, keine neue Markdown-Form.

**Stand je Mail** (`mail_attachment_mails`): wann die Anhänge zuletzt vollständig registriert wurden (verglichen mit dem Zeitpunkt, an dem `extract` der Mail fertig wurde: ist `extract` neuer, z. B. nach einem Neuaufbau, wird die Mail erneut bearbeitet), nächster Versuch nach einer Pause (Archiv nicht lesbar), Stand der Verweise in der Mail (erledigt / offen mit Fehler, Anzahl Versuche, nächster Versuch nach Backoff) und der Pfad der Mail-Markdown, gegen den die Links berechnet wurden.

**Je Anhang** (`mail_attachments`): Position in `attachments`, Dateiname, relativer Archivpfad, Endung, Größe und Änderungszeit der Datei, Hash (einmal berechnet, das Archiv ändert sich nie), Ergebnis (`registered` / `unsupported` / `empty`), id der Anhangs-Quelle und der Pfad der Anhangs-Markdown, auf den der Link in der Mail zeigt. Daraus entstehen ohne erneutes Hashen: Rückverweise, Nachführen der Links, Zählung, Abgleich.

**Zusammenfassung** (`mail_attachment_runs`): je Lauf (Takt mit bearbeiteten Mails, Abgleich) Art, Start, Ende und nicht verarbeitete Anhänge: gesamt, je Endung, je Postfach (je Endung), davon leer. Aufbewahrung `MAIL_ATTACHMENT_SUMMARY_RETENTION_DAYS` (Standard 90, mindestens 30).

**Mail-Markdown** (Änderung an PROJ-123): `attachments[].id` bei registrierten Anhängen; im Abschnitt „Anhänge“ hinter dem Archiv-Link zusätzlich `→ [Markdown](<relativer Pfad>)`. Nicht registrierte Anhänge bleiben ohne `id` und mit nur dem Archiv-Link.

Alle neuen Tabellen mit Row Level Security und offenen Policies wie die übrigen Dienst-Tabellen (nur der Dienst-Datenbanknutzer, kein Endnutzer-Zugriff). Sichtbarkeit der Quellen wie bisher nach PROJ-121.

## C) Abläufe

1. **Schleife „Anhänge“** (alle `MAIL_ATTACHMENT_POLL_SECONDS`, Standard 30 s, also deutlich unter den 5 Minuten aus AK-9):
   1. Nur eine Instanz arbeitet gleichzeitig (Advisory-Lock in PostgreSQL); eine zweite überspringt den Takt (AK-8). Die Hash-Eindeutigkeit des Registers verhindert Duplikate zusätzlich.
   2. Erkennungsliste von `alice-file-detection` holen (zwischengespeichert, alle paar Minuten neu). Nicht erreichbar und noch keine Liste bekannt, Register oder Archiv nicht erreichbar → Pause mit Warnung, nichts geändert (AK-39, AK-40).
   3. Fällige Mails wählen: `extract` = `done`, Archiv-Eintrag mit Anhängen, noch nicht bzw. vor dem letzten `extract` bearbeitet, keine Pause aktiv; die zuletzt fertig gewordenen zuerst. Neue Mails stehen damit immer vor dem Bestand (AK-36), der Bestand läuft in Paketen von `MAIL_ATTACHMENT_BATCH_SIZE` Mails (AK-35). `deleted`-Mails gehören dazu (AK-31).
   4. Je Mail zuerst alle Anhänge prüfen: Endung (klein geschrieben) in der Liste? Größe 0? Datei lesbar? Hash berechnen bzw. aus `mail_attachments` übernehmen. Ist eine Datei nicht lesbar, bleibt die ganze Mail unverändert und wird nach einer Pause erneut versucht (kein Fehlversuch, AK-39); die übrigen Mails laufen weiter.
   5. Je erkanntem, nicht leerem Anhang `POST /sources` mit Art, Hash, Titel, Fundort, Erfassungszeit der Mail, `parents` = Mail, `detect` erledigt. Neuer Hash → neue Quelle; bekannter Hash → zusätzlicher Fundort + Elternteil an der bestehenden Quelle, erledigte Stufen bleiben (AK-14–16). Gleicher Inhalt zweimal in einer Mail → beim zweiten Mal nur zweiter Fundort. Bei mehr als `MAIL_BATCH_THRESHOLD` Mails im Takt als Sammel-Commit (höchstens 500 Dateien, Grenze des Registers), am Ende des Pakets wird der Sammel-Commit abgeschlossen.
   6. Verweise in der Mail: Mail-Markdown lesen, `attachments[].id` setzen (Zuordnung über den Archivpfad), Abschnitt „Anhänge“ mit Links neu bauen, über das Register schreiben mit eigenem Commit (`attachments: <id> <Betreff>`, Autor Pipeline) und `keep_stages = classify`: `classify` der Mail bleibt `done` (AK-22). Steht der Inhaltsteil in `manual`, lässt das Register ihn stehen, nur das Frontmatter wird ergänzt (AK-21). Ist `attachments` selbst in `manual` oder die Markdown gesperrt/nicht schreibbar → Registrierung bleibt, Nachtragen mit Backoff (1 min … 12 h) erneut, Ereignis an der Mail im Register.
   7. Ohne Änderung (alles schon da) wird nichts geschrieben und nichts committet (AK-7).
   8. **Links nachführen** (jeder Takt): Hat sich der Pfad einer Anhangs-Markdown (Titeländerung, AK-20) oder der Mail-Markdown (z. B. nach `deleted/`) seit dem letzten Schreiben geändert, wird der Abschnitt „Anhänge“ neu geschrieben. Die `id` bleibt.
   9. Nicht verarbeitete Anhänge des Takts nach Endung/Postfach zählen und als Zusammenfassung speichern (nur wenn der Takt Mails bearbeitet hat), ältere über der Aufbewahrung löschen. Informativ: kein Fehler, keine Healthcheck-Warnung (AK-34).
2. **Stufe extract der Mail** (bestehend): baut die Markdown wie bisher und übernimmt zusätzlich die bekannten Anhangs-ids und Links aus `mail_attachments`. Ein Neuaufbau ab `extract` (PROJ-120) verliert die Verweise also nicht; danach bearbeitet die Schleife die Mail erneut (Hash-Dedup: keine Duplikate, gleiche ids, AK-37).
3. **classify mit Mail-Kontext** (alice-document-classify): Hat die Quelle `parents`, liest der Dienst über das Register die Mail-Markdowns, nimmt die mit dem ältesten Mail-Datum und gibt Betreff, Absender und Datum als markierten Hinweis an Klassifizierung und Feld-Extraktion (der Dokumenttext bleibt maßgeblich, kein Mailtext, AK-24/25). Nicht lesbar → ohne Hinweis, kein Fehler (AK-26). Ohne `parents` ist der Prompt unverändert (AK-27).
4. **Löschen:** PROJ-124 setzt nie `deleted` und entfernt keine Fundorte. Wird die Mail `deleted`, bleibt der Archivpfad Fundort der Anhangs-Quelle (AK-30). Der Nachtlauf von PROJ-116 entfernt nur Fundorte, die er selbst in überwachten Ordnern gefunden hat, nie Archivpfade (AK-33). Fehlt eine Archivdatei, meldet das der Abgleich (Ebenen 6 und 7) als Lücke (AK-32).
5. **Abgleich (PROJ-120), Ebene 7:** `alice-etl-rebuild` bekommt sie mit der bestehenden Abfrage `POST /reconcile/check` des Mail-Imports. Geprüft wird je Anhang mit erkannter Endung: Quelle vorhanden, `parents` enthält die Mail, Archivpfad ist Fundort, `id` in der Mail-Markdown (über `mail_attachments`). Lücken: `attachment_unregistered` (Reparatur `attachment_register`: die Mail sofort wie im Takt bearbeiten, zählt zur Reparaturgrenze), `attachment_file_missing` (nur gemeldet), `attachment_changed` (Datei hat andere Größe/Änderungszeit und anderen Hash als registriert, EC-4: nur gemeldet, nicht übernommen). Der Abgleich speichert ebenfalls eine Zusammenfassung der nicht verarbeiteten Anhänge (über alle Mails).

**Fehlerverhalten:** Register/Repo, Archiv oder Datei-Erkennung nicht erreichbar → Takt pausiert ohne Änderung, holt danach alles nach. Abbruch mitten in einer Mail → im Register ist jede Registrierung für sich vollständig (PROJ-115), die Mail gilt erst nach allen Schritten als bearbeitet und wird beim Neustart wiederholt; Hash-Dedup verhindert doppelte Quellen (AK-41). Logs nennen nur Mail-id, Quell-id, Dateiname-Endung und Zähler, nie Mailtexte oder Passwörter (AK-42).

## D) Technische Entscheidungen
- **Erweiterung von `alice-mail-import` statt neuer Dienst**, weil dort Archiv, Archiv-Einträge, Mail-Markdown und Abgleich-Ebenen 5/6 schon liegen; kein weiterer Container, kein zweiter Zugriff aufs Archiv.
- **Erkennungsliste über `GET /extensions` von `alice-file-detection`**, weil sie dort (Standard + `DETECT_EXT_*`) gepflegt wird; eine Kopie würde auseinanderlaufen (AK-4).
- **Auslöser per Abfrage in PostgreSQL** („`extract` fertig nach letzter Bearbeitung“), nicht per Aufruf aus der extract-Stufe: deckt neue Mails, Bestand, Neustart und Neuaufbau mit einer Regel ab und braucht keine Queue.
- **Hash je Anhang gespeichert**: Archivdateien ändern sich nie (PROJ-123); wiederholte Läufe, Links und Abgleich müssen große Anhänge nicht erneut lesen. Abweichungen erkennt der Abgleich an Größe/Änderungszeit.
- **`parents` setzt keine Stufen zurück** (Register): Ein neuer Elternteil ändert nichts am Inhalt; sonst liefen `database`/`rag`/`wiki` einer DMS-Quelle neu (AK-14 verlangt „erledigte Stufen bleiben done“).
- **`keep_stages` beim Schreiben der Mail-Markdown**: `classify` der Mail hängt am Inhaltsteil; die Links ändern ihn, die Bedeutung der Mail aber nicht (AK-22).
- **Links über gespeicherte Pfade nachführen** statt Register-Hook: Der Mail-Import erkennt Umbenennungen per Vergleich mit `alice.sources.path`; das Register bleibt frei von Mail-Wissen.
- **Mail-Kontext in Klassifizierung und Feld-Extraktion** (beide gehören zur Stufe `classify`), damit auch der Titel von `scan0001.pdf` profitiert.
- **Ebene 7 im bestehenden Prüf-Aufruf des Mail-Imports**: eine Abfrage, ein Dienst kennt Archiv und Anhänge; Ebenen 1–9 sind in den Ergebnistabellen erlaubt.

## E) Abhängigkeiten
- Pakete: keine neuen.
- Neue Umgebungsvariablen `alice-mail-import` (Platzhalter in `.env.example`, alle mit Standardwert): `DETECTION_URL` (Standard `http://alice-file-detection:8013`), `MAIL_ATTACHMENTS_DISABLED`, `MAIL_ATTACHMENT_POLL_SECONDS` (30), `MAIL_ATTACHMENT_BATCH_SIZE` (50), `MAIL_ATTACHMENT_SUMMARY_RETENTION_DAYS` (90).

## F) Test- und Deploy-Plan
| AK | Nachweis | Art |
|---|---|---|
| AK-1–3, AK-5, AK-6, AK-10–13, AK-29 | Testmails (PDFs, JPG/PNG, mp3/mp4, cid-Bilder, zip/ics/eml, 0 Byte) über Fake-IMAP importieren, extract, Schleife „Anhänge“; Register, Pfade, Stufen, Fundorte prüfen | Integration (Test-DB, Temp-Repo, Temp-Archiv) |
| AK-4 | Erkennungsliste der Attrappe um eine Endung erweitert → Anhang wird Quelle | Integration |
| AK-7, AK-8, AK-41 | zweiter Lauf ohne Änderung (Commits zählen), zwei Schleifen parallel, Abbruch zwischen Registrierung und Verweis | Integration |
| AK-9, AK-36 | neue Mail während Bestandslauf → nach einem Takt registriert | Integration |
| AK-14–17 | DMS-Quelle mit gleichem Hash (Register direkt), zwei Mails, zwei Dateinamen; Datei-Erkennung danach mit gleicher Datei | Integration |
| AK-18–22 | `attachments[].id`, Links (relativer Pfad existiert), Titeländerung → Link nachgeführt, `manual: [content]`, classify bleibt `done`, Commit-Autor | Integration |
| AK-23, AK-28 | bleibt bei PROJ-117 unverändert: Anhangs-Quelle `document` wird von `extract` geholt wie jede andere | Integration (Claim im Register) |
| AK-24–27 | Klassifizierung mit LLM-Attrappe: Prompt mit/ohne Mail-Kontext, älteste Mail, Mail-Markdown nicht lesbar | Unit + Integration |
| AK-30–33 | Mail `deleted` (Fundort entfernen) → Anhang aktiv; deleted-Mail → registriert; Archivdatei fehlt → Ebene 7 meldet; Datei-Erkennung nach Löschen der DMS-Kopie | Integration |
| AK-34 | Lauf mit 3 zip, 2 ics, 1 eml → Zusammenfassung, Health ohne Warnung | Integration |
| AK-35 | 60 Mails Bestand, Paketgröße 20, Abbruch nach erstem Paket → Fortsetzung, Sammel-Commits | Integration |
| AK-37, AK-38 | Neuaufbau-Freigabe `extract` für Mails → ids unverändert; Ebene 7 meldet und repariert, Ebene 7 in `alice-etl-rebuild` | Integration |
| AK-39, AK-40 | Archiv weg, Register nicht erreichbar → nichts geändert, danach weiter | Integration |
| AK-42–44 | Log-Prüfung, keine nginx-Route, Deploy-Schritte | Test + Prüfung |
| AK-45/46 | Live nach Deploy | Mensch |

Nicht ohne Produktivsysteme testbar: NAS-Archiv, echte Postfächer, LLM → Temp-Ordner, Fake-IMAP, Gateway-Attrappe. AK-45/46 prüft der Mensch.

Deploy-Schritte für den Menschen:
1. Migration `sql/migrations/2026-11-27_PROJ-124_mail_attachments.sql`.
2. `./scripts/sync-compose.sh`, `make rebuild s=automations/alice-source-registry`, `make rebuild s=automations/alice-file-detection`, `make rebuild s=automations/alice-mail-import`, `make rebuild s=automations/alice-document-classify`, `make rebuild s=automations/alice-etl-rebuild`.
3. Keine neuen Pflicht-Variablen; die `.env` von `alice-mail-import` bleibt gültig.

## Decision Log
| Entscheidung | Alternative | Abwägung |
|---|---|---|
| Erweiterung `alice-mail-import` | neuer Dienst `alice-mail-attachments` | Archiv-Wissen an einer Stelle, ein Container weniger |
| `GET /extensions` der Datei-Erkennung | Liste kopieren bzw. in die Datenbank | nur eine Pflegestelle (Spec); Datenbank-Liste hätte PROJ-116 stärker geändert |
| Abfrage „extract fertig nach letzter Bearbeitung“ | Aufruf direkt aus extract | gleiche Regel für Bestand, Neuaufbau, Neustart, Pausen |
| `parents` als Register-Feld ohne Stufen-Reset | wie bisher alles zurücksetzen | AK-14 verlangt unveränderte Stufen; Inhalt ändert sich nicht |
| `keep_stages` beim Schreiben | Mail-Markdown mit Stufenname `classify` schreiben | sauberer: Commit-Text und Stufe stimmen, keine Täuschung des Registers |
| Links per Pfadvergleich nachführen | Register benachrichtigt bei Umbenennung | Register bleibt generisch; Verzögerung höchstens ein Takt |
| Ebene 7 im bestehenden Prüf-Aufruf | eigener Endpunkt | weniger Aufrufe, gleiche Fehlerbehandlung wie 5/6 |

## Umsetzung (Bau, 2026-11-27)
- Gebaut wie oben. Neue Schleife `docker/compose/automations/alice-mail-import/app/attachments.py` (Anhänge registrieren, Verweise schreiben, Links nachführen, Zusammenfassungen, Ebene 7), Schema Abschnitt 21 in `sql/init-schema.sql` + Migration `sql/migrations/2026-11-27_PROJ-124_mail_attachments.sql`.
- `alice-mail-import`: neue Endpunkte `GET /attachments/runs`; `POST /reconcile/check` liefert zusätzlich `attachments` (Ebene 7), `POST /reconcile/repair` kennt den Typ `attachment_register`. Die Stufe extract übernimmt bekannte Anhangs-ids und Links in die neu gebaute Mail-Markdown. Health: Pause der Anhangs-Registrierung als Warnung, die Zählung nicht verarbeiteter Anhänge nie.
- Registrierung der Anhänge einer Mail als Sammel-Commit, wenn ein Takt mehr als `MAIL_BATCH_THRESHOLD` (20) Mails bearbeitet; danach wird der Sammel-Commit des Registers sofort abgeschlossen (`POST /maintenance/flush`). Einzelne neue Mails: ein Commit je neuer Quelle und ein Commit `attachments: <id> <Betreff>` für die Mail.
- Wird die Erkennungsliste um eine Endung erweitert, nimmt die Schleife auch bereits bearbeitete Mails mit Anhängen dieser Endung erneut auf (AK-4 gilt damit auch für den Bestand).
- Eine nicht lesbare Anhangsdatei pausiert die ganze Mail für `MAIL_ATTACHMENT_PAUSE_SECONDS` (900 s), damit nie nur ein Teil ihrer Anhänge registriert ist; fehlt die Datei dauerhaft, meldet der Abgleich die Lücke.
- Leere Anhänge werden in der Zusammenfassung unter ihrer Endung gezählt und zusätzlich als `empty` ausgewiesen.
- Die Links stehen hinter dem Archiv-Link als `→ [Markdown](<relativer Pfad>)`.
- `alice-source-registry`: `parents` gehört jetzt zu den Register-Feldern ohne Stufen-Reset (wie `locations`); `database` läuft für eine DMS-Quelle wegen des neuen Archiv-Fundorts trotzdem neu (die Fundorte stehen in der Datenbank, PROJ-119), alle übrigen Stufen bleiben `done`.
- Abweichung von der Spec (offen, Entscheidung des Menschen): AK-14 verlangt, dass die erledigten Stufen der DMS-Quelle `done` bleiben. Die Stufe `database` geht durch den neuen Archiv-Fundort aber nach der PROJ-119-Regel auf `pending` (die Fundorte stehen in der Dokument-Tabelle). Rückfrage im Issue gestellt.
- Nachbesserung nach Abnahme Runde 1 (EC-4/AK-37): Ist für eine Anhangsposition mit gleichem Archivpfad schon ein Hash gespeichert und liefert die Datei jetzt einen anderen Hash (Datei im Archiv ersetzt), wird nichts registriert. Die bisherige Quelle, ihre `id` in der Mail und der gespeicherte Dateistand bleiben; Ebene 7 meldet weiter `attachment_changed`. Vorher wurde die geänderte Datei bei einem Neuaufbau ab `extract` still als neue Quelle übernommen.
- Ebene 7: Ist `attachments` der Mail von Hand geschützt (`manual`), wird `attachment_reference_missing` nur gemeldet (keine Reparatur, die ohnehin scheitern würde).
