# PROJ-119: Strukturierte Dokumentdaten in PostgreSQL

**Erstellt:** 2026-11-24
**Phase:** 4.1

<!-- Der Status steht nur in features/INDEX.md. Diese Datei schreibt nur der Mensch (/write-spec, /refine). -->

## Abhängigkeiten
- Benötigt: PROJ-115 (Quelle-der-Wahrheit-Repo + Quellen-Register) — Stufe `database`, Arbeit übernehmen/abschließen/zurückgeben, Quell-Markdown lesen, Retry/Backoff, Rücksetzen von `database` bei Inhaltsänderung und Hand-Korrektur
- Benötigt: PROJ-116 (Datei-Erkennung) — `deleted`-Quellen, Fundorte
- Benötigt: PROJ-118 (Klassifizierung + Feldextraktion) — `type`, `classification`, `title`, `summary`, `fields` inkl. `transactions` und `line_items`, Merker `balance_mismatch`/`balance_difference`, `summary_language_uncertain`
- Grundlage für: PROJ-120 (Neuaufbau), PROJ-122 (ETL-Status-Ansicht), PROJ-128 (Such-Tools, Auswertungen), PROJ-134 (Agent)

## Überblick
PROJ-119 ist die Stufe `database` des neuen ETL für Quellen der Art `document`. Sie liest das Frontmatter der Quell-Markdown und bildet es in fachlichen PostgreSQL-Tabellen ab: eine gemeinsame Zeile je Dokument, eine Detail-Zeile je Typ (Rechnung, Kontoauszug, Wertpapierabrechnung, Vertrag), Buchungen und Rechnungspositionen als eigene Datensätze. Die DB ist rein abgeleitet: Quelle der Wahrheit ist die Quell-Markdown, die DB ist jederzeit daraus neu aufbaubar. Hand-Korrekturen in der Markdown (geschützt über `manual`, PROJ-115) landen so automatisch in der DB und werden beim Neuaufbau nicht überschrieben.

PROJ-119 befüllt die Tabellen und hält sie synchron; Lese-Schnittstellen (Suche, Auswertungen, Agent-Tools) baut PROJ-128. Das Feature hat keine Oberfläche. Getestet wird mit Wegwerf-Postgres und PROJ-115 mit temporärem Git-Repo; kein LLM.

## User Stories
- Als Haushaltsmitglied möchte ich, dass die Kerndaten meiner Rechnungen, Kontoauszüge, Verträge und Wertpapierabrechnungen strukturiert gespeichert sind, damit Alice Fragen wie „Was habe ich 2026 an die Stadtwerke gezahlt?“ exakt beantworten kann.
- Als Haushaltsmitglied möchte ich, dass jede Buchung eines Kontoauszugs ein eigener Datensatz ist, damit sie gefiltert und summiert werden kann.
- Als Admin möchte ich einen Wert in der Quell-Markdown korrigieren und kurz danach den korrigierten Wert in der DB sehen, ohne dass ein Neuaufbau ihn wieder überschreibt.
- Als Haushaltsmitglied möchte ich, dass gelöschte Dokumente nicht mehr in Auswertungen auftauchen.
- Als Haushaltsmitglied möchte ich, dass Buchungen, die in zwei überlappenden Kontoauszügen stehen, in Auswertungen nicht doppelt zählen.
- Als Admin möchte ich sehen, wenn eine Hand-Korrektur ungültig ist und deshalb nicht in die DB übernommen wurde.

## Fachliches Modell

### Was verarbeitet wird
- Nur Quellen der Art `document`, deren Stufe `classify` auf `done` steht und deren Stufe `database` fällig ist. Andere Arten (`image`, `email`, `audio`, `video`) fasst die Stufe nicht an; ob und wie sie in die DB kommen, legen PROJ-123/PROJ-125 fest.
- Dokumente mit `classify` auf `pending`, `running`, `failed` oder `failed_permanent` erhalten keine DB-Zeile (bzw. behalten ihren letzten gültigen Stand).
- Laufende Verarbeitung innerhalb einer konfigurierbaren Abfragefrist, kein Nachtlauf (Aktualitätsziel ≤ 15 min bis DB).
- `database` wird fällig durch die Regeln aus PROJ-115/PROJ-118: neue Klassifizierung, Inhaltsänderung, Hand-Korrektur, „erneut versuchen“, Neuaufbau.

### Abfragbare Daten
Wie die Tabellen gebaut sind, entscheidet die Factory. Abfragbar sein muss:

**Je Dokument (alle Typen, eine Zeile):** `id` der Quelle, `type`, `title`, `summary`, `tags`, `document_date`, `sender`, `recipient`, `language`, `classification.confidence`, `classification.uncertain`, `summary_language_uncertain`, `modified`, `captured`, Pfad der Quell-Markdown im Repo, Fundorte der Originale (`locations`).

**Je Typ (eine Detail-Zeile, verknüpft mit dem Dokument):**

| Typ | Daten |
|---|---|
| `Invoice` | `invoice_number`, `invoice_date`, `due_date`, `amount_gross`, `amount_net`, `vat_rate`, `currency` |
| `BankStatement` | `bank_name`, `account_holder`, `iban`, `period_from`, `period_to`, `opening_balance`, `closing_balance`, `currency`, `balance_mismatch`, `balance_difference` |
| `SecuritySettlement` | `bank`, `depot_number`, `transaction_date`, `security_name`, `isin`, `transaction_type`, `quantity`, `price`, `settlement_amount`, `currency` |
| `Contract` | `contract_type`, `contract_partner`, `sign_date`, `start_date`, `end_date`, `notice_period`, `monthly_cost`, `annual_cost`, `currency` |
| `Document` | keine Detail-Zeile |

**Eigene Datensätze:**
- **Buchung** (aus `fields.transactions` eines `BankStatement`): Buchungsdatum, Wertstellung, Gegenpartei, Verwendungszweck, Betrag mit Vorzeichen, Währung des Auszugs, Position im Auszug (Dokumentreihenfolge), Verweis auf den Auszug, Dubletten-Merker (siehe unten).
- **Rechnungsposition** (aus `fields.line_items` einer `Invoice`): Bezeichnung, Menge, Betrag, Position in der Rechnung, Verweis auf die Rechnung.

- Typen in der DB: Daten als Datum, Beträge/Mengen als exakte Dezimalzahl (keine Fließkommazahl), Zeitpunkte mit Zeitzone. `null` im Frontmatter bleibt `null` in der DB.
- Die DB bildet das Frontmatter 1:1 ab: keine eigenen Berechnungen, keine Anreicherung, kein Volltext (Volltext/Suche: PROJ-127).

### Synchronisation
- Je Dokument wird der DB-Stand vollständig aus dem aktuellen Frontmatter ersetzt, in einer Transaktion: Dokument-Zeile, Detail-Zeile, Buchungen bzw. Positionen. Es gibt nie einen halb aktualisierten Stand.
- **Typwechsel** (z. B. `Invoice` → `Contract`): die Detail-Zeile und abhängigen Datensätze des alten Typs werden entfernt, die des neuen angelegt.
- **Gelöschte Quelle** (`deleted`, PROJ-116): alle Daten des Dokuments (Dokument-, Detail-Zeile, Buchungen, Positionen) werden aus der DB entfernt, innerhalb der Abfragefrist. Die Quell-Markdown bleibt in `deleted/` und in der Git-Historie. Kehrt die Quelle zurück (Fundort taucht wieder auf), wird sie wieder normal eingetragen.
- Die DB wird nie direkt bearbeitet; Korrekturen erfolgen nur in der Quell-Markdown. Direkte Änderungen in der DB werden beim nächsten Lauf überschrieben.

### Dubletten über Kontoauszüge hinweg
- Buchungen werden **nicht** über Auszüge hinweg zusammengeführt oder gelöscht; jede Buchung gehört zu genau einem Auszug.
- Eine Buchung wird als **mögliche Dublette** markiert, wenn ein *anderer* Auszug mit derselben `iban` eine Buchung mit gleichem Buchungsdatum, gleichem Betrag und gleichem Verwendungszweck enthält. Die Markierung verweist auf die Buchung, die als Original gilt.
- **Original** ist die Buchung aus dem Auszug mit dem frühesten `captured` (bei Gleichstand: kleinere `id`). Nur die übrigen werden markiert, sodass eine Auswertung ohne markierte Buchungen jede Buchung genau einmal zählt.
- Ohne `iban` am Auszug findet kein Abgleich statt. Gleiche Buchungen innerhalb desselben Auszugs werden nicht markiert.
- Die Markierung wird bei jeder Änderung neu bestimmt: kommt ein Auszug hinzu, ändert sich einer oder wird einer gelöscht, sind die Markierungen aller betroffenen Buchungen desselben Kontos danach wieder korrekt.

### Fehler
- **Ungültige Werte im Frontmatter** (typischerweise aus einer Hand-Korrektur: Datum nicht parsebar, Betrag keine Zahl, `transactions`/`line_items` keine Liste, `type` nicht aus der Liste): Stufe `database` geht auf `failed` mit verständlicher Meldung, die Feld und Wert nennt; normaler Backoff aus PROJ-115, nach 5 Fehlversuchen `failed_permanent`. Die DB behält für dieses Dokument den letzten gültigen Stand. Korrigiert der Mensch die Markdown, setzt die Hand-Korrektur `database` wieder auf `pending`.
- **Quell-Markdown von PROJ-115 gesperrt** (ungültiges YAML, AK-28 in PROJ-115): keine Änderung an der DB, letzter gültiger Stand bleibt.
- **PostgreSQL nicht erreichbar:** Arbeit ohne Fehlversuch zurückgeben, Warnung ins Log, nach Rückkehr selbstständig weiter.
- Die Stufe schreibt nichts in die Quell-Markdown und erzeugt keine Commits.

### Last
- Keine LLM-Aufrufe. Parallelität konfigurierbar.
- Beim ersten Deploy werden alle bereits klassifizierten Dokumente, deren `database` fällig ist, ohne manuellen Anstoß nachgezogen.

## Außerhalb des Umfangs
- Lese-Schnittstellen: Suche, Filter, Summen, Auswertungen, Agent-Tools (PROJ-128, PROJ-134)
- Mails, Mail-Anhänge als eigene Art, Bilder in der DB (PROJ-123, PROJ-124, PROJ-125)
- Neuaufbau-Ablauf und Fortschritt (PROJ-120); Anzeige von Fehlern und „erneut versuchen“ (PROJ-122)
- Volltext, Chunks, Vektoren (PROJ-127); Wiki (PROJ-129)
- Bearbeiten von Daten direkt in der DB oder über eine Oberfläche
- Zusammenführen von Buchungen über Auszüge hinweg; Abgleich ohne IBAN; unscharfer Dubletten-Abgleich (z. B. leicht abweichender Verwendungszweck)
- Kategorisierung von Buchungen, Finanzanalyse (PROJ-59, Non-Goal Phase 4)
- Änderung, Abschaltung oder Datenübernahme der alten Weaviate-Collections (`Invoice`, `BankStatement`, `BankTransaction`, `Contract`, `SecuritySettlement`, `Document`) und n8n-Workflows (PROJ-142)
- Zugriffsrechte auf die Tabellen für Nutzer (Rollenprüfung erfolgt in den Lese-Tools, PROJ-128; PROJ-121)

## Akzeptanzkriterien

### Ablauf
- [ ] AK-1: Angenommen eine Quelle `kind: document` mit `classify` auf `done` und `database` auf `pending`, wenn der Dienst läuft, dann übernimmt er die Arbeit (`running`), trägt das Dokument in die DB ein und setzt `database` auf `done`.
- [ ] AK-2: Angenommen eine Quelle mit `classify` auf `pending`, `running`, `failed` oder `failed_permanent`, wenn der Dienst läuft, dann übernimmt er `database` nicht, und es entsteht keine DB-Zeile.
- [ ] AK-3: Angenommen Quellen der Arten `image`, `email`, `audio`, `video`, wenn der Dienst läuft, dann übernimmt er sie nicht und schreibt nichts in die fachlichen Tabellen.
- [ ] AK-4: Angenommen `database` wechselt auf `pending`, wenn der Dienst läuft, dann ist die DB innerhalb einer konfigurierbaren Abfragefrist aktualisiert.
- [ ] AK-5: Angenommen bereits klassifizierte Dokumente mit `database` auf `pending` beim ersten Start, wenn der Dienst startet, dann werden alle ohne manuellen Anstoß eingetragen.
- [ ] AK-6: Angenommen der Dienst verarbeitet ein Dokument, wenn man Repo und Register prüft, dann hat er weder die Quell-Markdown verändert noch einen Commit erzeugt.

### Abbildung
- [ ] AK-7: Angenommen ein `Document` mit allen gemeinsamen Feldern, wenn es eingetragen ist, dann sind alle unter „Je Dokument“ genannten Daten per SQL abfragbar (inkl. `tags`, Pfad der Quell-Markdown und Fundorte), und es gibt keine Detail-Zeile.
- [ ] AK-8: Angenommen je ein Testdokument für `Invoice`, `BankStatement`, `SecuritySettlement` und `Contract` mit allen Feldern, wenn eingetragen, dann gibt es je eine Dokument-Zeile und eine Detail-Zeile mit allen Daten des Typs laut Tabelle; Daten als Datum, Beträge als exakte Dezimalzahl.
- [ ] AK-9: Angenommen eine `Invoice` mit 3 `line_items`, wenn eingetragen, dann gibt es 3 Rechnungspositionen mit Bezeichnung, Menge, Betrag und Position 1–3, verknüpft mit der Rechnung.
- [ ] AK-10: Angenommen ein `BankStatement` mit 250 Buchungen, wenn eingetragen, dann gibt es 250 Buchungs-Datensätze mit Buchungsdatum, Wertstellung, Gegenpartei, Verwendungszweck, Betrag mit Vorzeichen, Währung und Position in Dokumentreihenfolge; die Summe der Beträge per SQL entspricht der Summe im Frontmatter exakt.
- [ ] AK-11: Angenommen Felder mit `null` im Frontmatter, wenn eingetragen, dann sind sie in der DB `null`.
- [ ] AK-12: Angenommen ein `BankStatement` mit `balance_mismatch: true` und `balance_difference` 50,00 bzw. ein Dokument mit `classification.uncertain: true` und `summary_language_uncertain: true`, wenn eingetragen, dann sind diese Merker per SQL abfragbar.
- [ ] AK-13: Angenommen ein `BankStatement` mit leerer Buchungsliste, wenn eingetragen, dann gibt es Dokument- und Detail-Zeile und keine Buchungen.

### Änderungen und Hand-Korrekturen
- [ ] AK-14: Angenommen ein eingetragenes Dokument, wenn ein Mensch in der Quell-Markdown `fields.amount_gross` ändert und die Hand-Korrektur erkannt ist (PROJ-115), dann steht nach dem nächsten Lauf der neue Wert in der DB.
- [ ] AK-15: Angenommen ein Kontoauszug mit 10 Buchungen in der DB, wenn eine neue Fassung des Frontmatters 9 Buchungen (eine entfernt, eine geändert) enthält, dann stehen danach genau diese 9 Buchungen in der DB, keine alte bleibt übrig.
- [ ] AK-16: Angenommen ein Dokument mit `type: Invoice` und Positionen in der DB, wenn es als `Contract` neu klassifiziert und eingetragen wird, dann gibt es keine Rechnungs-Detail-Zeile und keine Positionen mehr, sondern eine Vertrags-Detail-Zeile.
- [ ] AK-17: Angenommen ein Feld steht in `manual` mit einem von Hand gesetzten Wert, wenn ein Neuaufbau (PROJ-115: alle Stufen erneut) durchläuft, dann steht danach weiterhin der Hand-Wert in der DB.
- [ ] AK-18: Angenommen ein Wert wurde direkt in der DB geändert, wenn `database` für dieses Dokument erneut läuft, dann steht danach wieder der Wert aus der Quell-Markdown in der DB.
- [ ] AK-19: Angenommen der Dienst wird mitten im Eintragen eines Kontoauszugs beendet, wenn man die DB prüft, dann steht dort entweder der vollständige alte oder der vollständige neue Stand (keine halbe Buchungsliste), und nach dem Neustart wird die Stufe nach der Zeitüberschreitung aus PROJ-115 erneut übernommen.

### Löschen
- [ ] AK-20: Angenommen ein eingetragener Kontoauszug mit Buchungen, wenn die Quelle `deleted` wird, dann sind Dokument-, Detail-Zeile und alle Buchungen innerhalb der Abfragefrist aus der DB entfernt; ebenso Rechnungen mit Positionen.
- [ ] AK-21: Angenommen eine gelöschte Quelle, wenn ihr Fundort wieder auftaucht und sie nicht mehr `deleted` ist, dann wird sie nach dem nächsten Lauf wieder vollständig eingetragen.

### Dubletten
- [ ] AK-22: Angenommen zwei Kontoauszüge A (früher erfasst) und B mit derselben `iban`, die beide eine Buchung mit gleichem Buchungsdatum, Betrag und Verwendungszweck enthalten, wenn beide eingetragen sind, dann ist die Buchung in B als mögliche Dublette markiert mit Verweis auf die Buchung in A, die Buchung in A ist nicht markiert, und eine Summe über alle nicht markierten Buchungen zählt sie einmal.
- [ ] AK-23: Angenommen dieselbe Konstellation, aber B wird vor A verarbeitet, wenn beide eingetragen sind, dann ist das Ergebnis dasselbe wie in AK-22 (Original = früheste `captured`, unabhängig von der Verarbeitungsreihenfolge).
- [ ] AK-24: Angenommen AK-22, wenn A gelöscht wird (`deleted`), dann ist die Buchung in B danach nicht mehr als Dublette markiert.
- [ ] AK-25: Angenommen zwei gleiche Buchungen in demselben Auszug, bzw. gleiche Buchungen in zwei Auszügen mit verschiedener `iban`, bzw. in Auszügen ohne `iban`, wenn eingetragen, dann ist keine davon als Dublette markiert.
- [ ] AK-26: Angenommen AK-22, wenn die Buchung in A von Hand im Betrag geändert wird, dann ist die Buchung in B nach dem nächsten Lauf nicht mehr markiert.

### Fehler und Betrieb
- [ ] AK-27: Angenommen eine Hand-Korrektur setzt `fields.amount_gross: "zwölf"` (bzw. `invoice_date: 31.13.2026` oder `transactions` als Text), wenn `database` läuft, dann steht die Stufe auf `failed` mit einer Meldung, die Feld und Wert nennt, die DB enthält für dieses Dokument unverändert den letzten gültigen Stand, und nach dem 5. Fehlversuch steht `failed_permanent`.
- [ ] AK-28: Angenommen AK-27, wenn der Mensch den Wert in der Markdown korrigiert und die Hand-Korrektur erkannt ist, dann läuft `database` erneut und steht auf `done` mit dem korrigierten Wert in der DB.
- [ ] AK-29: Angenommen eine Quell-Markdown ist durch PROJ-115 wegen ungültigen Frontmatters gesperrt, wenn der Dienst läuft, dann ändert er die DB für dieses Dokument nicht.
- [ ] AK-30: Angenommen PostgreSQL (fachliche Tabellen) ist nicht erreichbar, wenn eine Quelle übernommen ist, dann wird die Arbeit ohne Fehlversuch zurückgegeben (Versuchszähler unverändert), im Log steht eine Warnung, und nach Rückkehr läuft die Verarbeitung ohne Eingriff weiter.
- [ ] AK-31: Angenommen der Dienst, wenn man ihn von außerhalb des Docker-Netzes (über nginx) aufrufen will, dann ist er nicht erreichbar; es gibt keine nginx-Route.
- [ ] AK-32: Angenommen der neue Dienst läuft, wenn das alte System arbeitet, dann laufen die alten Workflows unverändert, und der Dienst schreibt nicht nach Weaviate und nicht in Redis-Schlüssel des alten Systems.
- [ ] AK-33: Angenommen das Schema-Skript, wenn es auf einer frischen Wegwerf-DB und auf einer DB mit bestehendem Phase-4-Schema angewendet wird, dann laufen beide ohne Fehler und die fachlichen Tabellen existieren im Schema `alice`.

### Live-Tests nach Deploy
- [ ] AK-34 (Live-Test nach Deploy): Angenommen die in PROJ-118 klassifizierten echten Dokumente, wenn die Stufe durchgelaufen ist, dann stimmen bei Stichprobe je Typ die DB-Werte mit dem Frontmatter überein, und die Summe der Buchungen eines echten Kontoauszugs ergibt Endsaldo minus Anfangssaldo.
- [ ] AK-35 (Live-Test nach Deploy): Angenommen ein Betrag wird in einer echten Quell-Markdown von Hand korrigiert, wenn höchstens 15 Minuten vergangen sind, dann steht der korrigierte Wert in der DB.

## Edge Cases
- EC-1: Gleiche Buchung in drei Auszügen desselben Kontos → eine gilt als Original (früheste `captured`), die beiden anderen verweisen auf sie.
- EC-2: Original-Auszug wird gelöscht, zwei weitere enthalten die Buchung → der nächstfrüheste wird Original, der letzte bleibt markiert und verweist auf den neuen Original.
- EC-3: Hand-Korrektur ändert die `iban` eines Auszugs → Dubletten-Markierungen beider Konten werden neu bestimmt.
- EC-4: Zwei Auszüge desselben Kontos werden gleichzeitig verarbeitet (Parallelität > 1) → Markierungen sind danach trotzdem korrekt und eindeutig (keine gegenseitige Markierung).
- EC-5: Dokument wird während der Verarbeitung `deleted` → kein Eintrag bleibt übrig, kein Fehler.
- EC-6: Sehr langer Kontoauszug (mehrere tausend Buchungen) → wird vollständig in einer Transaktion eingetragen.
- EC-7: Betrag mit vielen Nachkommastellen oder sehr groß (z. B. Wertpapier-Menge 0,000123, Betrag 1.250.000,00) → exakt gespeichert, keine Rundung durch Fließkomma.
- EC-8: Buchung ohne Verwendungszweck oder ohne Wertstellung → mit `null` eingetragen; Dubletten-Abgleich nur bei vorhandenem Buchungsdatum und Betrag, fehlender Verwendungszweck gilt als gleich, wenn bei beiden fehlend.
- EC-9: Quell-Markdown mit älterer `schema`-Version ohne einzelne Felder → fehlende Felder `null`, kein Fehler.
- EC-10: `classify` wird nach `done` erneut `pending` (z. B. Inhaltsänderung) → bis zur neuen Klassifizierung bleibt der letzte DB-Stand stehen; danach wird `database` wieder fällig.
- EC-11: Redis-Neustart → keine Auswirkung, Arbeit kommt aus dem Register (PROJ-115).
- EC-12: Neuaufbau mit vielen Dokumenten (PROJ-120) → Stufe arbeitet die Menge ohne Eingriff ab; Chat und Sprache sind nicht betroffen (kein LLM).

## Technische Anforderungen
- Testbar ohne GPU und ohne Produktivsysteme: Wegwerf-Postgres/Redis, PROJ-115 mit temporärem Git-Repo; kein LLM.
- Neuer Dienst bzw. Stufe im neuen ETL; Schema-Erweiterung in `sql/init-schema.sql` (Schema `alice`), auf bestehender DB wiederholbar anwendbar.
- Lesen der Quell-Markdowns und Stufenzustände ausschließlich über PROJ-115, nie direkt im Repo schreiben.
- Konfigurierbar: Abfragefrist, Parallelität; neue Variablen nur als Platzhalter in `.env.example`.
- Schnittstelle nur intern im Docker-Netz, keine nginx-Route.
- Keine neue Queue-/Event-Infrastruktur.
- Keine echten Pfade, Hostnamen, Kontonummern, IBANs oder personenbezogenen Daten im Code oder in Testdaten (Test-IBANs/-ISINs synthetisch mit gültiger Prüfziffer).

## Offene Fragen
- Keine

## Product Decisions
- Gelöschte Quellen werden aus der DB entfernt statt markiert: die DB ist abgeleitet und neu aufbaubar, gelöschte Dokumente dürfen nie in Summen auftauchen, ein Filter in jeder Abfrage wäre fehleranfällig; die Markdown bleibt in `deleted/` und in Git (2026-11-24)
- PROJ-119 befüllt nur die Tabellen, keine Lese-API: Lese-Tools, Suche und Auswertungen gehören zu PROJ-128; kleine Spec, eine Stufe (2026-11-24)
- Aufteilung: gemeinsame Zeile je Dokument + Detail-Zeile je Typ + Buchungen und Rechnungspositionen als eigene Datensätze: Fragen über alle Dokumente und gezielt je Typ möglich, Buchungen filter- und summierbar (2026-11-24)
- Keine Dubletten-Bereinigung über Auszüge hinweg, sondern Markierung als mögliche Dublette (gleiche IBAN, Buchungsdatum, Betrag, Verwendungszweck) mit Verweis aufs Original (früheste Erfassung): DB bleibt 1:1 zu den Quellen, Auswertungen zählen trotzdem nicht doppelt (2026-11-24)
- Nur `kind: document` und erst nach `classify` = `done`; laufende Verarbeitung; Mails/Bilder entscheiden ihre Features selbst; fehlgeschlagene Klassifizierungen sind über PROJ-122 sichtbar, nicht über die DB (2026-11-24)
- Ungültige Werte aus Hand-Korrekturen lassen `database` sichtbar scheitern (Feld und Wert in der Meldung), die DB behält den letzten gültigen Stand: eine Korrektur darf nie still als `null` verloren gehen (2026-11-24)
- Korrekturen nur in der Quell-Markdown; die DB wird bei jedem Lauf je Dokument vollständig aus dem Frontmatter ersetzt — so übersteht eine Hand-Korrektur jeden Neuaufbau über `manual` (PROJ-115) (2026-11-24)
