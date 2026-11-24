# Architektur: PROJ-119 Strukturierte Dokumentdaten in PostgreSQL (#11)

**Spec:** [spec.md](spec.md) · **Stand:** 2026-11-24

## A) Betroffene Bausteine
```
alice-document-database (Container, NEU, Port 8016, nur intern)
+-- Arbeitsschleife: Stufe `database` aus dem Register übernehmen
+-- Prüfung + Umwandlung des Frontmatters (Datum, exakte Dezimalzahl, Listen)
+-- Je Dokument: DB-Stand in einer Transaktion vollständig ersetzen
+-- Dubletten-Markierung je Konto (IBAN) neu bestimmen
+-- GET /health, GET /status

alice-source-registry (PROJ-115, kleine Erweiterung)
+-- Stufen können auch bei Änderung von `locations` und `deleted` auf pending gehen
+-- Übernahme (claim) kann gelöschte Quellen mitliefern (Option, nur für `database`)

PostgreSQL, Schema alice (NEU):
+-- doc_documents            eine Zeile je Dokument
+-- doc_invoices             Detail Rechnung
+-- doc_invoice_line_items   Rechnungspositionen
+-- doc_bank_statements      Detail Kontoauszug
+-- doc_bank_transactions    Buchungen (+ Dubletten-Merker)
+-- doc_security_settlements Detail Wertpapierabrechnung
+-- doc_contracts            Detail Vertrag
+-- pipeline_stages['database']: resets_on_fields = {locations, deleted}

docker/compose/scripts/Makefile: neuer Stack automations/alice-document-database
```
Keine nginx-Route, kein Frontend, keine n8n-Änderung, kein Weaviate, kein Redis.

## B) Datenmodell
Alle Tabellen im Schema `alice`, Präfix `doc_`, damit sie sich klar von den Register-Tabellen (`sources`, `source_*`) und den alten Weaviate-Collections unterscheiden.

- **doc_documents** (Schlüssel: `id` der Quelle): Typ, Titel, Zusammenfassung, Tags (Textliste), Dokumentdatum, Absender, Empfänger, Sprache, Klassifikations-Sicherheit (`confidence`, `uncertain`), `summary_language_uncertain`, `modified`, `captured` (Zeitpunkte mit Zeitzone), Pfad der Quell-Markdown im Repo, Fundorte (`locations`, als JSON-Liste genau wie im Frontmatter), Zeitpunkt der letzten Übernahme.
- **Detail-Tabellen** je Typ (Schlüssel = Dokument-`id`, Fremdschlüssel auf `doc_documents` mit `ON DELETE CASCADE`), Spalten genau wie in der Spec-Tabelle. Beträge, Mengen, Kurse, Steuersatz als `NUMERIC` (exakt, ohne feste Stellenzahl), Daten als `DATE`. `Document` hat keine Detail-Zeile.
- **doc_invoice_line_items**: Rechnung, Position (1…n), Bezeichnung, Menge, Betrag.
- **doc_bank_transactions**: Auszug, Position (1…n, Dokumentreihenfolge), Buchungsdatum, Wertstellung, Gegenpartei, Verwendungszweck, Betrag mit Vorzeichen, Währung (vom Auszug), Verweis `duplicate_of` auf die Original-Buchung (leer = keine Dublette). Der Verweis wird beim Löschen des Originals automatisch geleert (`ON DELETE SET NULL`) und danach ohnehin neu bestimmt.
- Indizes auf allen Filter-/Join-Spalten: Typ, Dokumentdatum, Absender, IBAN, Buchungsdatum, Betrag, Fremdschlüssel.
- **RLS** auf allen neuen Tabellen mit Policies wie bei den Register-Tabellen (der Dienst-Nutzer schreibt, Rollenprüfung erfolgt in den Lese-Tools von PROJ-128).
- **Aufbewahrung:** solange die Quelle existiert; gelöschte Quellen werden entfernt. Die DB ist jederzeit aus den Quell-Markdowns neu aufbaubar.
- Es gibt keine Berechnungen: Werte stehen 1:1 wie im Frontmatter, `null` bleibt `null`. Die einzige abgeleitete Information ist die Dubletten-Markierung (von der Spec verlangt).

## C) Abläufe

**Normaler Lauf (AK-1, AK-4, AK-5)**
1. Der Dienst fragt alle `DATABASE_POLL_SECONDS` (Standard 10 s) beim Register nach fälliger Arbeit der Stufe `database`: nur Art `document`, nur wenn `classify` erledigt ist, gelöschte Quellen mit. Höchstens `DATABASE_CONCURRENCY` Quellen gleichzeitig.
2. Bei einer nicht gelöschten Quelle liest er die Quell-Markdown über das Register (nie direkt im Repo).
3. Er prüft und wandelt alle Werte um. Ein ungültiger Wert bricht ab, bevor die DB angefasst wird.
4. In **einer Transaktion**: Sperre für das Dokument und für die betroffenen Konten (alte und neue IBAN), alle bisherigen Zeilen des Dokuments löschen (Detail, Buchungen, Positionen hängen per Kaskade daran), neue Zeilen schreiben, Dubletten-Markierungen der betroffenen Konten neu bestimmen. Erst danach wird die Transaktion bestätigt.
5. Stufe `database` → `done`.

Beim ersten Start steht `database` für alle bestehenden Quellen schon auf `pending` (Stufe ist seit PROJ-115 angelegt). Der Dienst arbeitet sie ohne Anstoß ab (AK-5).

**Wann `database` wieder fällig wird** (alles im Register, PROJ-115/118):
- jede Inhalts- oder Feldänderung der Markdown (Klassifizierung, Hand-Korrektur) – war schon so (`resets_on_content_change`),
- **neu:** Änderung der Fundorte (`locations`) und Löschen/Wiederkehr (`deleted`); dafür bekommt die Stufe `database` diese beiden Felder in `resets_on_fields`. Bisher lösten sie keine Stufe aus.

**Gelöschte Quelle (AK-20, AK-21, AK-24, EC-5)**
1. Das Register setzt `database` beim Löschen auf `pending`.
2. Der Dienst bekommt die Quelle bei der Übernahme mit dem Kennzeichen „gelöscht“, liest keine Markdown, entfernt in einer Transaktion alle Zeilen des Dokuments und bestimmt die Dubletten seines Kontos neu. Stufe → `done`.
3. Kehrt die Quelle zurück, ändert sich `deleted` wieder → `database` `pending` → normal eingetragen.

**Dubletten (AK-22–26, EC-1–4, EC-8)**
- Nach jedem Ersetzen oder Entfernen werden die Markierungen aller Buchungen der betroffenen Konten neu berechnet (ein SQL-Durchgang je IBAN, keine Schleife je Buchung).
- Vergleich: gleiche IBAN, anderer Auszug, gleiches Buchungsdatum, gleicher Betrag, gleicher Verwendungszweck (beide leer gilt als gleich). Ohne Buchungsdatum oder Betrag kein Abgleich.
- Original ist die Buchung aus dem Auszug mit dem frühesten `captured`, bei Gleichstand der kleineren `id`; innerhalb dieses Auszugs die erste passende Position. Buchungen des Original-Auszugs werden nie markiert; gleiche Buchungen im selben Auszug nie.
- Eine Sperre je IBAN in der Transaktion sorgt dafür, dass zwei Auszüge desselben Kontos nacheinander berechnet werden (EC-4). Ergebnis hängt nicht von der Reihenfolge ab (AK-23).

**Fehler**
- Ungültiger Wert (AK-27): Stufe `failed` mit Meldung „Feld `fields.amount_gross`: 'zwölf' ist keine Zahl“; die DB bleibt unverändert; Backoff und `failed_permanent` nach 5 Versuchen macht das Register. Korrektur in der Markdown setzt `database` wieder auf `pending` (AK-28).
- Markdown gesperrt (AK-29): das Register gibt gesperrte Quellen nicht aus; sollte das Lesen trotzdem auf die Sperre treffen, wird die Arbeit ohne Fehlversuch zurückgegeben.
- PostgreSQL der fachlichen Tabellen nicht erreichbar (AK-30): Arbeit ohne Fehlversuch zurückgeben, Warnung ins Log, `/health` meldet `warning`, neue Arbeit pausiert kurz und läuft danach von selbst weiter.
- Register nicht erreichbar: warten, nach einer Schonfrist `unhealthy` (wie PROJ-118).
- Abbruch mitten im Eintragen (AK-19): die Transaktion wird nicht bestätigt, die DB behält den alten Stand; das Register gibt die Stufe nach seiner Zeitüberschreitung erneut aus.
- Die Stufe schreibt nie in die Markdown und erzeugt keine Commits (AK-6).

## D) Technische Entscheidungen
- **Neuer Dienst statt Erweiterung von alice-document-classify**, weil die Stufen unabhängig voneinander laufen, die DB-Stufe kein LLM braucht und auch bei LLM-Ausfall weiterarbeiten soll; Aufbau (Register-Client, Arbeitsschleife, Heartbeat, Health) wie bei PROJ-117/118.
- **Gelöschte Quellen über das Register statt eigener Abfrage der Register-Tabellen**, weil die Spec das Lesen der Zustände ausschließlich über PROJ-115 verlangt. Zwei kleine, abwärtskompatible Erweiterungen im Register (Felder `locations`/`deleted` als Auslöser, Claim-Option für gelöschte Quellen) nutzen die vorhandenen Mechanismen (Backoff, Zeitüberschreitung, Queue) und halten die Abfragefrist ein.
- **Komplett ersetzen statt Abgleich einzelner Zeilen**, weil es einfach und robust ist und die Spec genau das verlangt (keine Altlasten bei Typwechsel, entfernten Buchungen, direkten DB-Änderungen).
- **Werte strikt prüfen, nichts raten:** Zahlen müssen YAML-Zahlen oder Texte mit Punkt als Dezimaltrenner sein, Daten ISO-Datum (`JJJJ-MM-TT`). Alles andere ist ein Fehler mit Feld und Wert – eine Hand-Korrektur geht nie still verloren.
- **Exakte Dezimalzahlen:** die Register-Antwort wird mit Dezimal-Parser gelesen, Werte gehen als `NUMERIC` in die DB. YAML liefert Zahlen mit bis zu 15 signifikanten Stellen exakt; mehr Stellen kommen in Belegen nicht vor.
- **Unbekannte Dokument-Typen** (nicht aus der Liste) → `failed` mit Typ in der Meldung.
- **Eine Sperre pro Dokument im Dienst** (gleiche Quelle nie zweimal gleichzeitig) plus Datenbank-Sperren je Dokument und IBAN, damit auch bei Parallelität keine Halbzustände oder gegenseitigen Markierungen entstehen.

## E) Abhängigkeiten
- Pakete: `fastapi`, `uvicorn`, `httpx`, `asyncpg` (wie die übrigen Dienste), `PyYAML` nur für Tests (Register in-process).
- Neue Umgebungsvariablen (Platzhalter in `.env.example`): `REGISTRY_URL`, `POSTGRES_DSN`, optional `DATABASE_CONCURRENCY`, `DATABASE_POLL_SECONDS`, `DATABASE_HEARTBEAT_SECONDS`, `DATABASE_DB_RETRY_SECONDS`, `DATABASE_REGISTRY_GRACE_SECONDS`.

## F) Test- und Deploy-Plan
| AK | Nachweis | Art |
|---|---|---|
| AK-1, AK-5 | Quellen registrieren, extract/classify done → Worker trägt alle ein, Stufe `done` | Integration (echtes Register in-process, Test-DB, temporäres Git-Repo) |
| AK-2, AK-3 | classify pending/failed bzw. Art image/email → keine Übernahme, keine Zeile | Integration |
| AK-4 | Hand-Korrektur → `database` pending → nächster Durchgang aktualisiert | Integration |
| AK-6 | Git-Log und Markdown vor/nach unverändert | Integration |
| AK-7–13 | je Typ vollständiges Frontmatter, 3 Positionen, 250 Buchungen (Summe exakt), `null`, Merker, leere Liste | Integration + Unit (Umwandlung) |
| AK-14–18 | Hand-Korrektur, 10→9 Buchungen, Typwechsel, `manual` + Stufen-Rücksetzung (simulierter Neuaufbau), direkte DB-Änderung | Integration |
| AK-19 | Fehler mitten im Schreiben (Attrappe wirft) → alter Stand vollständig; Zeitüberschreitung übernimmt erneut | Integration |
| AK-20, AK-21, EC-5 | Fundort weg → Zeilen weg; Fundort zurück → wieder da | Integration |
| AK-22–26, EC-1–4, EC-8 | Dubletten-Konstellationen inkl. Reihenfolge, Löschen, Änderung, parallele Verarbeitung | Integration |
| AK-27, AK-28 | „zwölf“, `31.13.2026`, `transactions` als Text → failed mit Feld/Wert, DB unverändert, 5× → failed_permanent; Korrektur → done | Integration |
| AK-29 | gesperrte Markdown → keine Übernahme, DB unverändert | Integration |
| AK-30 | DB-Pool auf nicht erreichbare Adresse → release, Versuche unverändert, Warnung im Log | Unit/Integration |
| AK-31 | kein nginx-Eintrag, kein Port in compose.yml | Durchsicht + Container-Test |
| AK-32 | Dienst hat keine Weaviate-/Redis-Anbindung | Durchsicht |
| AK-33 | Schema auf frischer Test-DB und Migration zweimal auf altem Stand | Integration (psql) |
| Register-Erweiterung | bestehende Register-Tests + neue Tests für Auslöser `locations`/`deleted` und Claim mit gelöschten Quellen | Integration |
| AK-34, AK-35 | Live nach Deploy | Mensch |

Nicht ohne Produktivsysteme testbar: echte klassifizierte Dokumente (AK-34) und die 15-Minuten-Frist live (AK-35) → im Test mit synthetischen Dokumenten (synthetische IBAN/ISIN mit gültiger Prüfziffer) und kurzer Abfragefrist.

Deploy-Schritte für den Menschen:
1. Migration `sql/migrations/2026-11-24_PROJ-119_document_data.sql` anwenden.
2. `.env` für `alice-document-database` aus `.env.example` anlegen (`POSTGRES_DSN` mit dem Dienst-DB-Nutzer, `REGISTRY_URL`).
3. `./scripts/sync-compose.sh`, `make rebuild s=automations/alice-source-registry` (Register-Erweiterung), `make rebuild s=automations/alice-document-database`.
4. Live-Tests AK-34/35.

## Decision Log
| Entscheidung | Alternative | Abwägung |
|---|---|---|
| Neuer Dienst `alice-document-database` | Stufe in `alice-document-classify` | Unabhängig vom LLM, klare Verantwortung; ein Container mehr |
| Löschen über Register-Auslöser `deleted` + Claim gelöschter Quellen | Dienst liest `alice.sources.deleted` direkt; eigener Abgleich aller Zeilen | Spec verlangt Zustände nur über PROJ-115; nutzt Backoff/Queue/Zeitüberschreitung des Registers |
| `locations` als Auslöser | Fundorte nicht synchron halten | Spec verlangt Fundorte abfragbar; sonst veralten sie |
| Präfix `doc_` für Tabellen | `alice.documents`, `alice.invoices` | Keine Verwechslung mit Register und alten Collections |
| Fundorte als JSON-Liste | eigene Tabelle | Fundorte sind Teil der Quelle (Register hat die Tabelle schon); 1:1 wie Frontmatter |
| Strikte Prüfung (Punkt-Dezimal, ISO-Datum) | deutsche Zahlformate akzeptieren | Eindeutig, keine stillen Fehlinterpretationen; Fehlermeldung nennt Feld und Wert |
| Dubletten-Neuberechnung je IBAN in derselben Transaktion | nachgelagerter Hintergrundlauf | Immer korrekt sofort nach dem Lauf, kein halber Zustand |

## Umsetzung (2026-11-24)

**Gebaut**
- Neuer Dienst `docker/compose/automations/alice-document-database` (Port 8016, nur intern, keine nginx-Route): `convert.py` (strikte Umwandlung Frontmatter → Zeilen, Meldung mit Feld und Wert), `store.py` (Ersetzen/Entfernen je Dokument in einer Transaktion, Sperren je Dokument und IBAN, Dubletten-Neuberechnung je IBAN in einem SQL-Durchgang), `worker.py` (Arbeitsschleife wie PROJ-118: Claim, Heartbeat, Release/Fail, Pause bei DB-Ausfall), `main.py` (`/health`, `/status`). Eintrag im Makefile.
- Schema-Abschnitt 18 in `sql/init-schema.sql` + Migration `sql/migrations/2026-11-24_PROJ-119_document_data.sql`: sieben Tabellen `alice.doc_*` mit RLS, Policies, Indizes; Stufe `database` bekommt `resets_on_fields = {locations,deleted}`.
- Register (`alice-source-registry`): Felder `locations`/`deleted` lösen nur Stufen aus, die sie in `resets_on_fields` nennen (nicht alle `resets_on_content_change`-Stufen – `rag`/`wiki` bleiben unberührt); Claim-Option `include_deleted` liefert gelöschte Quellen mit (`deleted: true`, ohne `requires`-Prüfung, auch gesperrte, da die Markdown nicht gelesen wird); bei gesperrter Markdown setzen Löschen/Wiederkehr die Stufe direkt zurück. Rückgabe des Claims enthält jetzt immer `deleted`.

**Abweichungen / Präzisierungen**
- Zahlen in der Markdown: YAML-Zahl oder Text mit Punkt als Dezimaltrenner (`"12.50"`). `"12,50"` gilt als ungültig (Fehlermeldung nennt Feld und Wert), damit nichts still falsch gelesen wird. Daten nur `JJJJ-MM-TT`.
- IBAN-Abgleich für Dubletten ohne Leerzeichen und ohne Groß-/Kleinschreibung; gespeichert wird die IBAN 1:1 wie im Frontmatter.
- Der PROJ-115-Test „Fundort-Änderung setzt nichts zurück“ wurde angepasst: `rag` bleibt `done`, `database` geht (gewollt) auf `pending`.
- Doppelte Übernahme derselben Quelle (Claim vom Register zurückgenommen, z. B. beim Löschen während der Verarbeitung) wird im Dienst nacheinander abgearbeitet; das Ergebnis des zweiten Laufs zählt (EC-5).

## Deployment (2026-11-24)

**Schritte**
1. Migration `sql/migrations/2026-11-24_PROJ-119_document_data.sql` (durch den Nutzer) und `.env` für `alice-document-database` (lokal angelegt, mitsynchronisiert).
2. `sync-compose.sh`: rsync meldete Code 23, nur wegen der nicht setzbaren Änderungszeit von `automations/mqtt/config` (Operation not permitted); keine Löschungen, alle Dateien übertragen.
3. Rebuild `alice-source-registry` (Erweiterung), danach Start `alice-document-database`; beide `healthy`. Die `jq`-Meldungen des Health-Skripts sind kosmetisch, `docker inspect` und `/health` bestätigen den Zustand.
4. Kein Staging (Entscheidung 2026-11-24): Live-Prüfung in Produktion.

**Live-Test AK-34 (Stichprobe per SQL, nur lesen)**
- Der Dienst zog den klassifizierten Bestand ohne Anstoß nach: 361 Quellen `database` = `done`, `failed` = 0, `released` = 0, keine Warnungen/Fehler im Log.
- Eingetragen: 356+ Dokumente (157 `Document`, 134 `SecuritySettlement`, 66 `BankStatement`, 2 `Contract`), 2819+ Buchungen; keine Rechnung, weil PROJ-118 bisher keine `Invoice` klassifiziert hat (klassifiziert: 359 von rund 52.700 Quellen, `classify` ist der Engpass, nicht `database`).
- Salden: 63 Auszüge gehen auf (Anfangssaldo + Summe der Buchungen = Endsaldo, Toleranz 0,01), die 2 Abweichungen sind genau die 2 von PROJ-118 mit `balance_mismatch` markierten, 1 Auszug ohne Saldo (Prüfung entfällt).
- Dubletten: 0 markiert; unabhängige Abfrage (gleiche IBAN, Datum, Betrag, Zweck in mehreren Auszügen) findet ebenfalls 0 Gruppen.
- Zwei gelöschte Quellen (`deleted`, darunter die PROJ-116-Testquelle) stehen auf `database` = `done` ohne Eintrag in der DB (Aufräumen nach AK-20).
- Der Feldvergleich DB ↔ Frontmatter je Typ (zweiter Teil von AK-34) wurde noch nicht gemacht; geprüft sind nur Zähler, Salden und Dubletten. `doc_invoices` ist leer, bis PROJ-118 Rechnungen klassifiziert hat.

**Offen**
- AK-35 (Betrag in einer Quell-Markdown von Hand ändern, nach ≤ 15 min in der DB prüfen): vom Nutzer auszuführen.
- Feldvergleich DB ↔ Frontmatter je Typ (AK-34, Rest): vom Nutzer auszuführen.
- Dubletten- und Rechnungspfad live erst prüfbar, wenn überlappende Auszüge bzw. Rechnungen klassifiziert sind.
