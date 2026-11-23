# PROJ-118: Klassifizierung + Feldextraktion

**Erstellt:** 2026-11-23
**Phase:** 4.1

<!-- Der Status steht nur in features/INDEX.md. Diese Datei schreibt nur der Mensch (/write-spec, /refine). -->

## Abhängigkeiten
- Benötigt: PROJ-115 (Quelle-der-Wahrheit-Repo + Quellen-Register) — Stufe `classify`, Arbeit übernehmen/abschließen/zurückgeben, Quell-Markdown schreiben inkl. Titeländerung mit Umbenennung, `manual`-Schutz, Retry/Backoff, Commits
- Benötigt: PROJ-117 (Text-Extraktion → Quell-Markdown) — Inhaltsteil mit Seitenmarken, `language`, `extraction` (inkl. `extraction.empty`)
- Benötigt: PROJ-111 (LLM-Gateway mit Prioritäten, `features/old/`) — Hintergrund-Stufe für LLM-Aufrufe
- Ändert: PROJ-115 — Regeln, wann `classify` wieder auf `pending` geht (siehe „Erneute Klassifizierung“): zusätzlich zu `database`/`rag`/`wiki` auch `classify` bei neuer Extraktion, bei Hand-Korrektur des Inhaltsteils und bei Hand-Änderung von `type`
- Grundlage für: PROJ-119 (Strukturierte Dokumentdaten in PostgreSQL, inkl. Buchungen aus `BankStatement`), PROJ-120 (Neuaufbau), PROJ-122 (ETL-Status-Ansicht, unsichere Fälle), PROJ-127 (RAG), PROJ-129 (Wiki-Ingest)

## Überblick
PROJ-118 ist die Stufe `classify` des neuen ETL für Quellen der Art `document`. Sie nimmt fällige Arbeit aus dem Register (nachdem `extract` erledigt ist), lässt das lokale LLM aus dem Inhaltsteil der Quell-Markdown den **Dokumenttyp** bestimmen, die **fachlichen Felder** des Typs extrahieren und eine **deutsche Zusammenfassung** und einen **inhaltlichen Titel** erzeugen, und schreibt alles über die Schnittstelle von PROJ-115 ins Frontmatter. Bei Kontoauszügen werden alle **Buchungen** extrahiert, auch bei sehr langen Auszügen.

Die Stufe ersetzt fachlich `alice-dms-processor` (Dokumentteil), `alice-dms-classify-document`, `alice-dms-language-check` sowie die Backfills `alice-dms-classification-backfill` und `alice-dms-language-backfill`. Diese n8n-Workflows laufen unverändert für das alte System weiter, bis PROJ-142 sie abschaltet.

Das Feature hat keine Oberfläche. Getestet wird mit Wegwerf-Datenbank, PROJ-115 mit temporärem Git-Repo und einem gemockten LLM (OpenAI-kompatibler Fake-Server).

## User Stories
- Als Haushaltsmitglied möchte ich, dass jedes Dokument einen sprechenden Titel mit Zeitstempel bekommt, damit ich es im NAS-Ordner und in Alice wiedererkenne und chronologisch sortieren kann.
- Als Haushaltsmitglied möchte ich zu jedem Dokument eine deutsche Zusammenfassung lesen, auch wenn das Original englisch ist, damit ich schnell weiß, worum es geht.
- Als Haushaltsmitglied möchte ich, dass Rechnungen, Kontoauszüge, Verträge und Wertpapierabrechnungen als solche erkannt und ihre Kerndaten (Beträge, Daten, Partner, Buchungen) erfasst werden, damit Alice Fragen dazu richtig beantworten kann.
- Als Haushaltsmitglied möchte ich, dass bei einem langen Kontoauszug keine Buchung fehlt, damit Auswertungen stimmen.
- Als Haushaltsmitglied möchte ich falsche Typen oder Felder direkt in der Quell-Markdown korrigieren können, damit Alice danach mit dem korrigierten Wert arbeitet und ihn nie wieder überschreibt.
- Als Admin möchte ich unsichere Klassifizierungen, unsichere Sprache und nicht aufgehende Kontoauszüge im Frontmatter markiert sehen, damit ich sie gezielt prüfen kann.
- Als Admin möchte ich, dass die Klassifizierung Chat und Sprache nicht ausbremst, damit Alice im Alltag flüssig bleibt.

## Fachliches Modell

### Was verarbeitet wird
- Nur Quellen der Art `document`, deren Stufe `extract` auf `done` steht. Andere Arten (`image`, `email`, `audio`, `video`) übernimmt die Stufe nicht.
- **Immer LLM-Klassifizierung:** Feste Ordnertypen (`suggested_type` in den überwachten Ordnern) werden im neuen ETL nicht ausgewertet.
- Neue Dokumente werden laufend verarbeitet, sobald `classify` fällig ist — kein nächtliches Zeitfenster.

### Dokumenttypen
`Invoice`, `BankStatement`, `Contract`, `SecuritySettlement`, `Document` (Auffangtyp), wie in PROJ-115 festgelegt. Der Prompt enthält je Typ unterscheidende Merkmale (z. B. „Invoice: Rechnungsnummer, Bruttobetrag, Fälligkeitsdatum“).

### Unsichere Klassifizierung
- Erster Versuch deterministisch (Temperatur 0) mit einer Konfidenz (0–1) im Ergebnis.
- Liegt die Konfidenz unter einem konfigurierbaren Schwellwert, folgt ein zweiter Versuch mit erhöhter Temperatur. Übernommen wird das Ergebnis mit der höheren Konfidenz; bei Gleichstand der zweite Versuch.
- Bleibt die finale Konfidenz unter dem Schwellwert, wird die beste Schätzung trotzdem übernommen und `uncertain: true` gesetzt. Die Stufe endet mit `done`, nicht mit einem Fehler; Felder werden mit dem geschätzten Typ extrahiert.
- Im Frontmatter steht `classification` mit `confidence` und `uncertain`.

### Felder
Alle fachlichen Felder stehen gesammelt im Block `fields:` des Frontmatters (englische Namen, snake_case). Gemeinsame Angaben für alle Typen:

| Feld | Inhalt |
|---|---|
| `summary` | deutsche Zusammenfassung, 2–4 Sätze (Frontmatter-Feld außerhalb von `fields`) |
| `fields.document_date` | Datum des Dokuments |
| `fields.sender` | Absender/Aussteller |
| `fields.recipient` | Empfänger |
| `fields.tags` | 3–8 deutsche Schlagwörter |

Je Typ zusätzlich:

| Typ | Felder |
|---|---|
| `Invoice` | `invoice_number`, `invoice_date`, `due_date`, `amount_gross`, `amount_net`, `vat_rate`, `currency`, `line_items` (je Position: Bezeichnung, Menge, Betrag) |
| `BankStatement` | `bank_name`, `account_holder`, `iban`, `period_from`, `period_to`, `opening_balance`, `closing_balance`, `currency`, `transactions` (je Buchung: Buchungsdatum, Wertstellung, Gegenpartei, Verwendungszweck, Betrag mit Vorzeichen) |
| `SecuritySettlement` | `bank`, `depot_number`, `transaction_date`, `security_name`, `isin`, `transaction_type` (`buy`/`sell`/`dividend`/`distribution`), `quantity`, `price`, `settlement_amount`, `currency` |
| `Contract` | `contract_type`, `contract_partner`, `sign_date`, `start_date`, `end_date`, `notice_period`, `monthly_cost`, `annual_cost`, `currency` |
| `Document` | nur die gemeinsamen Felder |

- Daten im ISO-Format `YYYY-MM-DD`, Beträge und Mengen als Zahl, Währung als ISO-Code (z. B. `EUR`).
- Nicht gefundene Werte bleiben `null` — nichts wird geraten.
- Wechselt der Typ, werden Felder des alten Typs entfernt; Felder in `manual` bleiben erhalten.
- Ungültige Werte (Datum nicht parsebar, Betrag keine Zahl, `transaction_type` nicht aus der Liste) werden als `null` gespeichert.

### Titel
- Das LLM erzeugt einen kurzen deutschen Titel nach dem Muster „Was – Wer – Wann“ (z. B. „Stromrechnung Stadtwerke Oktober 2026“), höchstens etwa 80 Zeichen ohne Präfix.
- **Präfix:** Vor den Titel kommt die Änderungszeit des Originals (`modified`) im Format `YYYY-MM-DD hh.mm.ss`, z. B. `2026-10-14 09.32.11 Stromrechnung Stadtwerke Oktober 2026`. Ändert sich das Original (neue Änderungszeit, neue Extraktion), wird der Präfix neu gebildet.
- Die Titeländerung benennt die Quell-Markdown um (Mechanismus aus PROJ-115). Der Originalname bleibt über `locations` sichtbar.

### Deutsche Sprache für Titel und Zusammenfassung
- `title` und `summary` sind immer Deutsch, unabhängig von der Sprache der Quelle (`language` bleibt die Sprache des Inhalts).
- Nach der Erzeugung prüft eine Heuristik ohne LLM, ob Titel und Zusammenfassung überwiegend nicht-deutsch sind. Bei Verdacht folgt ein zweiter Versuch mit verschärfter Deutsch-Vorgabe.
- Bleibt der Verdacht, wird das Ergebnis trotzdem gespeichert und `summary_language_uncertain: true` gesetzt.
- Kurze oder sprachneutrale Texte (Eigennamen, Zahlen) gelten nicht als Verdacht; einzelne englische Fachbegriffe im deutschen Satz ebenfalls nicht.

### Lange Dokumente
- **Klassifizierung, Titel, Zusammenfassung und Felder** von `Invoice`, `Contract`, `SecuritySettlement`, `Document` sowie die Kopfdaten von `BankStatement` werden aus dem **Anfang** des Inhaltsteils bestimmt, begrenzt auf eine konfigurierbare Zeichenzahl (Standard 20.000).
- **Buchungen von Kontoauszügen** werden über den **gesamten** Inhaltsteil extrahiert: abschnittsweise entlang der Seitenmarken aus PROJ-117 (`## Seite <n>`), Abschnittsgröße konfigurierbar; die Buchungen aller Abschnitte werden in Dokumentreihenfolge zusammengeführt. Ohne Seitenmarken wird der Text in Abschnitte passender Größe geteilt.
- Buchungen, die an der Grenze zweier Abschnitte doppelt erkannt werden (gleiches Datum, gleicher Betrag, gleicher Verwendungszweck, direkt benachbart an der Grenze), werden zu einer zusammengeführt.

### Plausibilitätsprüfung
- **Saldo:** Bei `BankStatement` prüft eine Regel ohne LLM, ob `opening_balance` + Summe der Buchungen = `closing_balance` (Toleranz 0,01). Stimmt es nicht, wird trotzdem gespeichert und `balance_mismatch: true` mit der Differenz (`balance_difference`) gesetzt — kein Fehler, kein erneuter Versuch. Fehlt einer der Salden, entfällt die Prüfung (kein Flag).
- **Prüfziffern:** `iban` und `isin` werden auf gültige Prüfziffer geprüft; ein ungültiger Wert wird nicht gespeichert (`null`).

### Leeres Dokument
- Bei `extraction.empty: true` ruft die Stufe das LLM nicht auf: `type` = `Document`, `summary` leer, Felder `null`, `title` bleibt unverändert (Originalname). Stufe `done`.

### Erneute Klassifizierung
`classify` geht wieder auf `pending`, wenn
1. neu extrahiert wurde und sich der Inhaltsteil dadurch geändert hat (Original geändert → `extract` → neuer Inhalt),
2. der Inhaltsteil von Hand korrigiert wurde (z. B. OCR-Fehler im Betrag),
3. `type` von Hand geändert wurde — dann wird **nicht** neu klassifiziert, sondern die Felder werden mit dem Hand-Typ neu extrahiert,
4. „erneut versuchen“ oder ein Neuaufbau ausgelöst wird (PROJ-115/PROJ-120).

Hand-Änderungen nur an einzelnen Feldern (z. B. `fields.amount_gross`, `summary`, `title`) lösen keine erneute Klassifizierung aus; `database`/`rag`/`wiki` folgen wie in PROJ-115. In allen Fällen bleiben Felder in `manual` geschützt; ein von Hand gesetzter `type` hat immer Vorrang.

### LLM-Nutzung, Last und Fehler
- Alle LLM-Aufrufe laufen über `alice-llm-gateway` in der Hintergrund-Stufe; Chat und Sprache haben Vorrang. Höchstens eine Quelle gleichzeitig in Bearbeitung (konfigurierbar).
- Modell per Konfiguration (wie bisher das DMS-Modell); die Modellwahl ist nicht Teil dieser Spec.
- **LLM/Gateway nicht erreichbar oder Zeitüberschreitung:** Arbeit ohne Fehlversuch zurückgeben, pausieren, nach Rückkehr selbstständig weiter.
- **Ungültige Antwort** (kein gültiges JSON, Typ fehlt oder nicht aus der Liste): sofort ein zweiter Versuch; scheitert auch er, `failed` mit normalem Backoff aus PROJ-115 (nach 5 Fehlversuchen `failed_permanent`).
- Fällt bei einem Kontoauszug ein einzelner Abschnitt mit ungültiger Antwort aus (auch nach zweitem Versuch), gilt die ganze Quelle als fehlgeschlagen (`failed`) — keine Buchungsliste mit stiller Lücke.
- Nichts halb geschrieben: Frontmatter und Commit entstehen erst, wenn alle LLM-Schritte der Quelle abgeschlossen sind.

### Ablage
- PROJ-118 schreibt ausschließlich über die Schnittstelle von PROJ-115 in die Quell-Markdown (Frontmatter) und ins Register. Kein Schreiben nach Weaviate, keine Redis-Zustände des alten Systems, keine fachlichen Tabellen (PROJ-119).
- Commit im Normalbetrieb `classify: <id> <title>`, bei Massenläufen Sammel-Commits (PROJ-115).
- Der Inhaltsteil der Quell-Markdown wird von PROJ-118 nicht verändert (außer der Überschrift `# <title>`, die PROJ-115 aus `title` bildet).

## Außerhalb des Umfangs
- Fachliche Tabellen in PostgreSQL, Buchungen als eigene Datensätze (PROJ-119)
- Neuaufbau-Ablauf und Fortschritt (PROJ-120); eigene Backfill-Endpunkte für Klassifizierung oder Sprache gibt es nicht mehr
- Anzeige unsicherer Fälle, „erneut versuchen“ in der Oberfläche (PROJ-122)
- RAG-Index, Chunking für Weaviate (PROJ-127); Wiki (PROJ-129)
- Klassifizierung von Mails (Kategorie in PROJ-123), Bildbeschreibung und Geocoding (PROJ-125) — auch wenn der alte `alice-dms-processor` sie miterledigt hat
- Zusammenfassung über das ganze Dokument bei langen Dokumenten (nur der Anfang; später möglich)
- Felder `customer_number`, `contract_number` u. ä. (bewusst nicht im Feldsatz)
- Entfernen von `suggested_type` aus `alice.dms_watched_folders` und aus den Ordner-Einstellungen der WebApp (PROJ-139/PROJ-142); PROJ-118 ignoriert die Spalte nur
- Änderung, Abschaltung oder Datenübernahme der alten n8n-Workflows und ihrer Weaviate-/Redis-Bestände (PROJ-142)
- Übersetzung der Zusammenfassung in andere Nutzersprachen (PROJ-81, zurückgestellt)
- Auswahl oder Wechsel des LLM-Modells

## Akzeptanzkriterien

### Ablauf
- [ ] AK-1: Angenommen eine Quelle `kind: document` mit `extract` auf `done` und `classify` auf `pending`, wenn der Dienst läuft, dann übernimmt er die Arbeit (`running`), schreibt `type`, `classification`, `title`, `summary` und `fields` ins Frontmatter und setzt `classify` auf `done`.
- [ ] AK-2: Angenommen eine Quelle mit `extract` auf `pending`, `running` oder `failed`, wenn der Dienst läuft, dann übernimmt er `classify` für diese Quelle nicht.
- [ ] AK-3: Angenommen Quellen der Arten `image`, `email`, `audio`, `video`, wenn der Dienst läuft, dann übernimmt er sie nicht und verändert ihre Quell-Markdown nicht.
- [ ] AK-4: Angenommen eine erfolgreiche Klassifizierung im Normalbetrieb, wenn das Frontmatter geschrieben ist, dann gibt es genau einen Commit des Pipeline-Autors `classify: <id> <title>`; bei einem Massenlauf Sammel-Commits nach PROJ-115.
- [ ] AK-5: Angenommen eine Quelle, die in einem überwachten Ordner mit gesetztem `suggested_type` liegt, wenn klassifiziert wird, dann wird das LLM aufgerufen (Mock zählt den Aufruf) und dessen Typ übernommen, nicht der Ordnertyp.
- [ ] AK-6: Angenommen eine Quelle mit `classify` auf `pending`, wenn `extract` auf `done` wechselt, dann ist sie ohne Wartezeit auf ein Zeitfenster innerhalb einer konfigurierbaren Abfragefrist verarbeitet.

### Klassifizierung
- [ ] AK-7: Angenommen der LLM-Mock liefert für einen Rechnungstext Typ `Invoice` mit Konfidenz über dem Schwellwert, wenn klassifiziert wird, dann steht `type: Invoice`, `classification.confidence` mit dem Wert, `classification.uncertain: false`, und es gab genau einen Klassifizierungsaufruf mit Temperatur 0.
- [ ] AK-8: Angenommen der erste Versuch liefert eine Konfidenz unter dem Schwellwert, wenn klassifiziert wird, dann folgt ein zweiter Versuch mit erhöhter Temperatur, und übernommen wird das Ergebnis mit der höheren Konfidenz (bei Gleichstand der zweite).
- [ ] AK-9: Angenommen beide Versuche liefern Konfidenz unter dem Schwellwert, wenn klassifiziert wird, dann steht der Typ der besten Schätzung im Frontmatter, `classification.uncertain: true`, die Felder dieses Typs sind extrahiert, und `classify` steht auf `done`.
- [ ] AK-10: Angenommen der Prompt für die Klassifizierung, wenn er an das LLM geht, dann enthält er alle fünf Typen mit je unterscheidenden Merkmalen (prüfbar am Mock-Request).

### Felder
- [ ] AK-11: Angenommen ein Rechnungstext und ein LLM-Mock mit allen Rechnungsfeldern, wenn extrahiert wird, dann stehen unter `fields` die gemeinsamen Felder und alle `Invoice`-Felder inkl. `line_items`, Daten als `YYYY-MM-DD`, Beträge als Zahl.
- [ ] AK-12: Angenommen je ein Testtext für `Contract`, `SecuritySettlement` und `Document`, wenn extrahiert wird, dann enthält `fields` genau die gemeinsamen Felder und die Felder des jeweiligen Typs laut Tabelle — keine Felder anderer Typen.
- [ ] AK-13: Angenommen der LLM-Mock liefert für einige Felder keinen Wert bzw. `null`, wenn gespeichert wird, dann stehen diese Felder als `null` im Frontmatter.
- [ ] AK-14: Angenommen der LLM-Mock liefert ungültige Werte (Datum `31.13.2026`, Betrag `"ca. zwanzig"`, `transaction_type: "swap"`), wenn gespeichert wird, dann stehen diese Felder als `null`, die übrigen gültigen Felder sind gespeichert und `classify` steht auf `done`.
- [ ] AK-15: Angenommen eine Quelle mit `type: Invoice` und Rechnungsfeldern, wenn sie nach einer Inhaltsänderung als `Contract` klassifiziert wird, dann sind die `Invoice`-spezifischen Felder entfernt und die `Contract`-Felder gesetzt; ein Feld in `manual` bleibt erhalten.
- [ ] AK-16: Angenommen der LLM-Mock liefert eine IBAN bzw. ISIN mit falscher Prüfziffer, wenn gespeichert wird, dann ist `iban` bzw. `isin` `null`; eine gültige IBAN/ISIN wird unverändert (normalisiert, ohne Leerzeichen) gespeichert.

### Titel
- [ ] AK-17: Angenommen eine Quelle mit `modified` = 2026-10-14 09:32:11 und LLM-Titel „Stromrechnung Stadtwerke Oktober 2026“, wenn klassifiziert wird, dann ist `title` = `2026-10-14 09.32.11 Stromrechnung Stadtwerke Oktober 2026`, die Überschrift im Markdown entspricht dem Titel, und die Datei ist per Git-Umbenennung nach dem neuen Slug benannt (`<id>-…`, Ordner unverändert).
- [ ] AK-18: Angenommen der LLM-Mock liefert einen Titel mit mehr als 80 Zeichen, wenn gespeichert wird, dann ist der Titelteil nach dem Präfix auf höchstens 80 Zeichen gekürzt (an einer Wortgrenze).
- [ ] AK-19: Angenommen zwei Quellen erhalten vom LLM denselben Titel, wenn beide klassifiziert sind, dann unterscheiden sich ihre `title` durch den Präfix (verschiedene `modified`), und beide Dateien existieren nebeneinander.
- [ ] AK-20: Angenommen eine Quelle wird nach einer Änderung des Originals (neue `modified`) neu klassifiziert, wenn gespeichert wird, dann trägt `title` den Präfix der neuen Änderungszeit.

### Sprache
- [ ] AK-21: Angenommen eine englische Quelle (`language: en`), wenn klassifiziert wird, dann enthält der Prompt die Vorgabe, Titel und Zusammenfassung auf Deutsch zu schreiben, und `language` bleibt `en`.
- [ ] AK-22: Angenommen der LLM-Mock liefert im ersten Versuch eine englische Zusammenfassung und im zweiten eine deutsche, wenn klassifiziert wird, dann gab es einen zweiten Versuch mit verschärfter Deutsch-Vorgabe, gespeichert ist die deutsche Fassung, und `summary_language_uncertain` ist nicht `true`.
- [ ] AK-23: Angenommen der LLM-Mock liefert in beiden Versuchen eine englische Zusammenfassung, wenn klassifiziert wird, dann ist die Zusammenfassung des zweiten Versuchs gespeichert, `summary_language_uncertain: true`, und `classify` steht auf `done`.
- [ ] AK-24: Angenommen eine deutsche Zusammenfassung mit einzelnen englischen Fachbegriffen bzw. ein Titel nur aus Eigennamen und Zahlen, wenn die Heuristik prüft, dann löst sie keinen zweiten Versuch aus.

### Lange Dokumente und Kontoauszüge
- [ ] AK-25: Angenommen ein Dokument mit 100.000 Zeichen Inhalt, wenn klassifiziert wird, dann enthält der Klassifizierungs- und Feld-Prompt höchstens die konfigurierte Zeichenzahl vom Anfang (Standard 20.000; prüfbar am Mock-Request).
- [ ] AK-26: Angenommen ein Kontoauszug mit 12 Seiten (`## Seite 1` bis `## Seite 12`) und Buchungen auf allen Seiten, wenn extrahiert wird, dann werden die Buchungen abschnittsweise über alle Seiten extrahiert (Mock zählt mehrere Abschnitts-Aufrufe, zusammen decken sie alle Seiten ab), und `fields.transactions` enthält die Buchungen aller Abschnitte in Dokumentreihenfolge.
- [ ] AK-27: Angenommen der Mock liefert dieselbe Buchung (gleiches Datum, Betrag, Verwendungszweck) am Ende von Abschnitt 1 und am Anfang von Abschnitt 2, wenn zusammengeführt wird, dann steht sie nur einmal in `fields.transactions`; zwei gleiche Buchungen innerhalb eines Abschnitts bleiben beide erhalten.
- [ ] AK-28: Angenommen ein Kontoauszug mit `opening_balance` 1.000,00, Buchungen −200,00 und +50,00 und `closing_balance` 850,00, wenn geprüft wird, dann ist kein `balance_mismatch` gesetzt.
- [ ] AK-29: Angenommen derselbe Kontoauszug mit `closing_balance` 900,00, wenn geprüft wird, dann wird gespeichert mit `balance_mismatch: true` und `balance_difference` 50,00, und `classify` steht auf `done` ohne weiteren LLM-Versuch.
- [ ] AK-30: Angenommen ein Kontoauszug ohne erkannten Anfangs- oder Endsaldo, wenn geprüft wird, dann entfällt die Prüfung und `balance_mismatch` ist nicht gesetzt.
- [ ] AK-31: Angenommen ein Kontoauszug, bei dem ein Abschnitt auch im zweiten Versuch eine ungültige Antwort liefert, wenn die Stufe abschließt, dann steht `classify` auf `failed` mit verständlicher Fehlermeldung, und das Frontmatter ist unverändert (keine unvollständige Buchungsliste).

### Leeres Dokument
- [ ] AK-32: Angenommen eine Quelle mit `extraction.empty: true`, wenn `classify` läuft, dann wird das LLM nicht aufgerufen, `type` ist `Document`, `summary` leer, `fields` mit `null`-Werten, `title` unverändert, und `classify` steht auf `done`.

### Hand-Korrekturen und erneute Klassifizierung
- [ ] AK-33: Angenommen `type` steht in `manual` mit `Contract`, wenn `classify` läuft, dann wird keine Klassifizierung aufgerufen, `type` bleibt `Contract`, und die `Contract`-Felder werden extrahiert.
- [ ] AK-34: Angenommen ein Mensch ändert `type` von `Document` auf `Invoice`, wenn die Hand-Korrektur erkannt ist, dann steht `classify` auf `pending`, und nach dem Lauf sind die `Invoice`-Felder gesetzt, ohne dass ein Klassifizierungsaufruf stattfand.
- [ ] AK-35: Angenommen ein Mensch korrigiert den Inhaltsteil (z. B. einen Betrag), wenn die Hand-Korrektur erkannt ist, dann steht `classify` auf `pending` und läuft erneut auf dem korrigierten Text.
- [ ] AK-36: Angenommen ein Mensch ändert nur `fields.amount_gross`, `summary` oder `title`, wenn die Hand-Korrektur erkannt ist, dann bleibt `classify` auf `done`; `database`, `rag` und `wiki` gehen auf `pending` (PROJ-115).
- [ ] AK-37: Angenommen das Original wurde geändert und neu extrahiert, wenn sich der Inhaltsteil geändert hat, dann steht `classify` auf `pending`; liefert die Neuextraktion exakt denselben Inhalt, bleibt `classify` auf `done`.
- [ ] AK-38: Angenommen `title`, `summary` und `fields.iban` stehen in `manual`, wenn `classify` erneut läuft, dann bleiben diese drei Werte unverändert, und alle übrigen Felder werden aktualisiert.
- [ ] AK-39: Angenommen eine Stufe `classify` auf `failed_permanent`, wenn „erneut versuchen“ ausgelöst wird (PROJ-115), dann wird die Quelle erneut klassifiziert.

### LLM, Last und Betrieb
- [ ] AK-40: Angenommen der Dienst ruft das LLM auf, wenn man die Aufrufe prüft, dann gehen alle über das LLM-Gateway mit dem Schlüssel eines Hintergrund-Aufrufers, keiner direkt an den Inferenz-Server.
- [ ] AK-41: Angenommen 5 fällige Quellen und Parallelität 1, wenn der Dienst läuft, dann ist zu keinem Zeitpunkt mehr als eine Quelle durch den Dienst `running`; die Grenze ist konfigurierbar.
- [ ] AK-42: Angenommen das LLM-Gateway ist nicht erreichbar oder läuft in die Zeitüberschreitung, wenn eine Quelle übernommen ist, dann wird die Arbeit ohne Fehlversuch zurückgegeben (Versuchszähler unverändert), im Log steht eine Warnung, und nach Rückkehr des Gateways läuft die Verarbeitung ohne Eingriff weiter.
- [ ] AK-43: Angenommen der LLM-Mock liefert im ersten Aufruf kein gültiges JSON und im zweiten ein gültiges, wenn klassifiziert wird, dann ist das Ergebnis des zweiten gespeichert und `classify` steht auf `done`.
- [ ] AK-44: Angenommen der LLM-Mock liefert zweimal kein gültiges JSON (oder einen Typ außerhalb der Liste), wenn klassifiziert wird, dann steht `classify` auf `failed` mit Fehlermeldung und Backoff nach PROJ-115; nach dem 5. Fehlversuch `failed_permanent`.
- [ ] AK-45: Angenommen der Dienst wird mitten in einer Klassifizierung beendet, wenn er neu startet, dann ist die Quell-Markdown unverändert, es gibt keinen halben Commit, und die Stufe wird nach der Zeitüberschreitung aus PROJ-115 erneut übernommen.
- [ ] AK-46: Angenommen eine Quell-Markdown nach der Klassifizierung, wenn man das Frontmatter liest, dann enthält es keinen Verarbeitungszustand, keinen Retry-Zähler und keine Fehlermeldung; der Inhaltsteil (außer der Titel-Überschrift) ist unverändert.
- [ ] AK-47: Angenommen der Dienst, wenn man ihn von außerhalb des Docker-Netzes (über nginx) aufrufen will, dann ist er nicht erreichbar; es gibt keine nginx-Route.
- [ ] AK-48: Angenommen der neue Dienst läuft, wenn das alte System arbeitet, dann laufen `alice-dms-processor` und die übrigen alten Workflows unverändert; der Dienst schreibt nicht nach Weaviate und nicht in Redis-Schlüssel des alten Systems.

### Live-Tests nach Deploy
- [ ] AK-49 (Live-Test nach Deploy): Angenommen je eine echte Rechnung, ein echter mehrseitiger Kontoauszug, ein echter Vertrag, eine echte Wertpapierabrechnung und ein englisches Dokument auf dem NAS, wenn die Stufe läuft, dann stimmen Typ und Kernfelder bei Stichprobe, der Kontoauszug geht ohne `balance_mismatch` auf, alle Titel und Zusammenfassungen sind Deutsch, und die Dateien tragen den Titel mit Zeitstempel-Präfix.
- [ ] AK-50 (Live-Test nach Deploy): Angenommen die Stufe arbeitet eine Reihe von Dokumenten ab, wenn parallel im Chat und per Sprache gefragt wird, dann bleibt die Antwortzeit spürbar unverändert.

## Edge Cases
- EC-1: Dokument enthält mehrere Typen (z. B. Vertrag mit beiliegender Rechnung) → ein Typ (beste Schätzung), ggf. `uncertain: true`; keine Aufteilung in mehrere Quellen.
- EC-2: Kontoauszug mit mehreren Konten in einem PDF → eine Quelle, Kopfdaten aus dem Anfang, Buchungen aller Abschnitte; Saldenprüfung schlägt dann ggf. an (`balance_mismatch`) und macht den Fall sichtbar.
- EC-3: Kontoauszug ohne Seitenmarken (einseitig oder aus `txt`/`csv`) → Abschnitte nach Größe; ein kurzer Auszug wird in einem Abschnitt verarbeitet.
- EC-4: Kontoauszug ohne Buchungen (z. B. Saldenmitteilung) → `transactions` leere Liste, Saldenprüfung nur, wenn beide Salden vorhanden.
- EC-5: Beträge im deutschen Format (`1.234,56`, `-12,00 S`/`H`) → als Zahl mit korrektem Vorzeichen gespeichert; nicht eindeutig interpretierbare Beträge → `null`.
- EC-6: `modified` fehlt oder ist ungültig → Präfix aus dem Erfassungszeitpunkt (`captured`).
- EC-7: LLM liefert Titel mit Zeichen, die im Dateinamen stören (`/`, `:`, Emojis) → Titel bleibt im Frontmatter, Slug ist dateinamentauglich (PROJ-115).
- EC-8: LLM liefert einen Titel, der bereits einen Datums-Präfix enthält → kein doppelter Präfix.
- EC-9: Hand-Korrektur und Klassifizierung kurz nacheinander → Hand-Korrektur wird zuerst committet, Klassifizierung respektiert `manual` (PROJ-115).
- EC-10: Mensch entfernt `type` aus `manual` → nächster Lauf darf wieder klassifizieren.
- EC-11: Inhaltsteil enthält Anweisungen an ein LLM („Ignoriere alle vorherigen Anweisungen …“) → wird als Dokumenttext behandelt; Ergebnis muss trotzdem dem Antwortformat entsprechen, sonst ungültige Antwort (AK-44).
- EC-12: Sehr kurzes Dokument (wenige Wörter, `language` leer) → normal klassifiziert, meist `Document`, Sprachheuristik ohne falschen Alarm.
- EC-13: Redis-Neustart → keine Auswirkung, Arbeit kommt aus dem Register (PROJ-115).
- EC-14: Neuaufbau mit vielen Quellen → Sammel-Commits, Hintergrund-Stufe im Gateway; Chat bleibt bedienbar.
- EC-15: Quelle wird während der Klassifizierung gelöscht (`deleted`) → Ergebnis wird verworfen bzw. nicht mehr geschrieben, kein Fehler.

## Technische Anforderungen
- Testbar ohne GPU und ohne Produktivsysteme: LLM als OpenAI-kompatibler Fake-Server bzw. Gateway-Mock, Wegwerf-Postgres/Redis, PROJ-115 mit temporärem Git-Repo.
- Neuer Dienst bzw. Stufe im neuen ETL; die alten n8n-Workflows (`alice-dms-processor`, `-classify-document`, `-language-check`, `-classification-backfill`, `-language-backfill`) bleiben unverändert.
- LLM-Aufrufe nur über `alice-llm-gateway` als Hintergrund-Aufrufer (eigener Schlüssel); der neue Aufrufer wird in der Gateway-Konfiguration als Platzhalter/Beispiel ergänzt.
- Konfigurierbar: Modell, Konfidenz-Schwellwert, Zeichenzahl für den Dokumentanfang, Abschnittsgröße für Kontoauszüge, Parallelität, Zeitüberschreitung je LLM-Aufruf, Abfragefrist; neue Variablen nur als Platzhalter in `.env.example`.
- Schreiben der Quell-Markdowns ausschließlich über PROJ-115, nie direkt ins Repo.
- Schnittstelle nur intern im Docker-Netz, keine nginx-Route.
- Keine neue Queue-/Event-Infrastruktur.
- Keine echten Pfade, Hostnamen, Kontonummern, IBANs oder personenbezogenen Daten im Code oder in Testdaten (Test-IBANs/-ISINs nur aus öffentlichen Beispielen bzw. synthetisch mit gültiger Prüfziffer).

## Offene Fragen
- Keine

## Product Decisions
- Lange Dokumente: Klassifizierung, Titel, Zusammenfassung und Felder aus dem Anfang (Standard 20.000 Zeichen), Buchungen von Kontoauszügen abschnittsweise über das ganze Dokument: Buchungen dürfen nicht still fehlen, für Metadaten reicht der Anfang; Zusammenfassung über das ganze Dokument später möglich (2026-11-23)
- Immer LLM-Klassifizierung, keine festen Ordnertypen mehr: Ordner sind kein verlässliches Typ-Signal, Hand-Korrektur über `type` in `manual` ersetzt den Ordnertyp (2026-11-23)
- Unsichere Klassifizierung wie PROJ-78 (zwei Versuche, Konfidenz, Flag), Ergebnis im Frontmatter (`classification.confidence`, `uncertain`) und Stufe `done`: Pipeline blockiert nie, unsichere Fälle sind im Repo und später in PROJ-122 auffindbar (2026-11-23)
- Titel = Änderungszeit des Originals `YYYY-MM-DD hh.mm.ss` + deutscher Inhaltstitel: gleichlautende LLM-Titel bleiben für Menschen unterscheidbar und chronologisch sortierbar; `modified` ist immer vorhanden und braucht kein LLM; Dokumentdatum (oft ohne Uhrzeit, teils falsch erkannt) und Erfassungszeit (beim Neuaufbau fast gleich) verworfen (2026-11-23)
- Titel und Zusammenfassung immer Deutsch mit Sprachheuristik, zweitem Versuch und Flag wie PROJ-79; `language` bleibt Sprache des Inhalts (2026-11-23)
- Feldsatz aus dem alten Prozessor übernommen, englische snake_case-Namen, gemeinsame Felder (`document_date`, `sender`, `recipient`, `tags`) für alle Typen, alles unter `fields:`; fehlende/ungültige Werte `null`, nichts raten (2026-11-23)
- LLM über `alice-llm-gateway` als Hintergrund, Parallelität 1; LLM-Ausfall zählt nicht als Fehlversuch, ungültige Antworten mit Sofort-Retry, danach Backoff; laufende Verarbeitung statt Nachtlauf (Aktualitätsziel ≤ 15 min) (2026-11-23)
- Erneute Klassifizierung bei neuem Inhalt (Extraktion oder Hand-Korrektur) und bei Hand-Änderung von `type` (dann nur Felder neu); Hand-Änderungen einzelner Felder lösen sie nicht aus — Folge: Änderung der Regeln aus PROJ-115 (2026-11-23)
- PROJ-118 schreibt nur Frontmatter und Register; alte Workflows laufen bis PROJ-142 unverändert, keine eigenen Backfills mehr (Massenlauf über PROJ-120) (2026-11-23)
- Plausibilität bei Kontoauszügen per Saldenprüfung ohne LLM mit Flag `balance_mismatch` statt Fehler; Dubletten an Abschnittsgrenzen werden zusammengeführt; ungültige IBAN/ISIN werden nicht gespeichert (2026-11-23)
- Fällt ein Abschnitt eines Kontoauszugs aus, scheitert die ganze Quelle: lieber sichtbarer Fehler als eine Buchungsliste mit stiller Lücke (2026-11-23)
