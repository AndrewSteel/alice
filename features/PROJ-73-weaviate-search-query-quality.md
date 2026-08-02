# PROJ-73: Weaviate-Suchkriterien-Qualität

## Status: Planned

**Created:** 2026-08-02
**Last Updated:** 2026-08-02

## Kontext & Motivation

Im Chat (Backend `alice-chat-stream`) ruft das LLM bei Fragen zu Dokumenten/Mails/Rechnungen die Tools `search_documents` bzw. `search_emails` auf und füllt dabei das `query`-Argument selbst aus (siehe `tools.py`, Tool-Schema). Dieses `query`-Argument geht als Hybrid-Suchtext (BM25 + Vektor, alpha 0.5) an Weaviate (`alice-tool-search`-Workflow, Node „Weaviate Search"). Ergebnisse mit Score < 0.01 werden verworfen.

Beobachtung aus der Praxis: Bei der Anfrage „Zeige mir die letzten Mails" generiert das LLM ein `query` wie `"neueste E-Mails"`. Das ist eine Paraphrase ohne echten inhaltlichen Anker — echte E-Mails enthalten diesen Text nicht, wodurch Hybrid-Scoring keine sinnvolle Trefferliste liefert.

Analyse ergab zwei unterschiedliche Ursachen, die beide in dieser Spec behandelt werden:

1. **Recency-Anfragen ohne Inhaltskriterium** („die letzten Mails", „die letzten Stromrechnungen"): Hier gibt es gar kein Inhalts-Suchkriterium — die Anfrage ist rein zeitlich. Eine Relevanz-gewichtete Hybrid-Suche ist für diesen Fall das falsche Werkzeug; benötigt wird eine Sortierung nach Datum absteigend.
2. **Inhaltliche Anfragen mit paraphrasierten Begriffen** (z.B. „Rechnung von Amazon" → LLM sucht nur nach „Rechnung" statt „Amazon"): Hier verwirft das LLM vom Nutzer genannte, konkrete Suchbegriffe (Firmennamen, Themen, Betreffe) und ersetzt sie durch generische Umschreibungen, wodurch Weaviate weniger präzise matchen kann.

## Dependencies

- Betrifft dieselbe Datei wie PROJ-37 (`streaming.py`, Tool-Status-Texte) und denselben n8n-Workflow wie PROJ-46 (`alice-tool-search.json`, Mail-Suche) — keine funktionale Abhängigkeit, aber Überschneidung im Code-Bereich.
- Requires: PROJ-30 (alice-chat-stream Backend), PROJ-46 (Mail IMAP Integration — `search_emails`)

## User Stories

- Als Nutzer möchte ich mit „Zeige mir die letzten Mails" die zuletzt eingegangenen/archivierten Mails sehen (nach Datum sortiert), ohne dass eine vage Texterfindung des LLM die Trefferliste verfälscht oder leer laufen lässt.
- Als Nutzer möchte ich mit „Zeige mir die letzten 10 Mails" genau 10 statt der Standardanzahl bekommen.
- Als Nutzer möchte ich mit „Zeige mir die letzten Rechnungen der Firma Enercity" nur Rechnungen von Enercity sehen, sortiert nach Datum (neueste zuerst) — nicht aufgefüllt mit Rechnungen anderer Firmen, falls es weniger als die Standardanzahl gibt.
- Als Nutzer möchte ich, dass bei inhaltlichen Suchanfragen die von mir genannten konkreten Begriffe (Firmennamen, Themen, Betreffzeilen-Stichworte) tatsächlich als Suchkriterium verwendet werden, statt vom LLM durch generische Umschreibungen ersetzt zu werden.
- Als Nutzer möchte ich, wenn ich nach „den neuesten Einträgen im Archiv" frage ohne einen Dokumenttyp zu nennen, zunächst gefragt werden, welchen Typ ich meine — bestehe ich aber ausdrücklich darauf, das ganze Archiv gemischt zu sehen, möchte ich die tatsächlich neuesten Einträge über alle Typen hinweg bekommen, statt eine Fehlermeldung oder eine Endlos-Rückfrage.

## Acceptance Criteria

### Recency-Erkennung & Datums-Sortierung

- [ ] Anfragen mit Recency-Signalwörtern („die letzten", „neueste", „aktuellste", „zuletzt", ...) und ohne weiteres Inhaltskriterium liefern die N zuletzt datierten Treffer des betreffenden Typs, sortiert nach Datum absteigend (neueste zuerst) — nicht nach Hybrid-Relevanz-Score.
- [ ] N ist standardmäßig 5, wenn der Nutzer keine Anzahl nennt.
- [ ] Nennt der Nutzer eine explizite Anzahl („die letzten 10 Mails"), wird genau diese Anzahl als N verwendet (kein zusätzliches Produkt-seitiges Deckeln unterhalb der ohnehin bestehenden technischen Obergrenze).
- [ ] Werden zusätzlich Filterkriterien genannt (Firma/Gegenpartei, Dokumenttyp, Richtung, Postfach), werden nur Treffer berücksichtigt, die diese Kriterien erfüllen; von diesen wird nach Datum sortiert und auf N begrenzt.
- [ ] Gibt es weniger als N passende Treffer (z.B. nur 3 Rechnungen von Enercity bei Standard-N=5), werden nur diese 3 zurückgegeben — es wird **nicht** mit Treffern anderer Firmen/Kriterien aufgefüllt.
- [ ] Recency-Anfrage ohne konkreten Dokumenttyp („die letzten Dokumente") bezieht sich ausschließlich auf `doc_type='Dokument'` (den generischen Dokumenttyp), nicht auf alle Archiv-Typen gemischt.
- [ ] Anfragen mit explizitem Datumsbereich (date_from/date_to, z.B. „Rechnungen aus Januar") behalten Vorrang vor der reinen Recency-Logik; innerhalb des Bereichs wird weiterhin nach Datum absteigend sortiert.
- [ ] Anfragen ganz ohne Recency-Signal und ohne Datumsbereich (rein inhaltliche Suche, z.B. „durchsuche meine Verträge nach einer Kündigungsfrist von 3 Monaten") verwenden weiterhin die bestehende Hybrid-Relevanz-Suche — unverändertes Verhalten.
- [ ] Recency-Anfrage ohne jede Typangabe, weder Dokumenttyp noch „alle" ausdrücklich genannt (z.B. „was ist neu in meinem Archiv?"): Alice fragt zunächst nach, welchen Dokumenttyp der Nutzer meint (Mails, Rechnungen, Kontoauszüge, Verträge, ...), statt zu raten.
- [ ] Besteht der Nutzer nach der Rückfrage (oder bereits in der ursprünglichen Anfrage) ausdrücklich auf einer typübergreifenden Sicht (z.B. „einfach alles", „egal welcher Typ", „das ganze Archiv"), werden die N zuletzt datierten Einträge über alle für ihn erlaubten Collections hinweg zurückgegeben, sortiert nach dem jeweiligen Datumsfeld des Treffers absteigend, gemischt in einer Ergebnisliste (jeder Treffer zeigt seinen eigenen Typ).

### Konkrete Suchbegriffe bei inhaltlichen Anfragen

- [ ] Nennt der Nutzer in seiner Anfrage einen konkreten Firmennamen/Gegenpartei (z.B. „Amazon", „Enercity", „Telekom", „Sparkasse"), erscheint dieser Begriff unverändert (nicht paraphrasiert) im an Weaviate gestellten Suchkriterium.
- [ ] Nennt der Nutzer ein konkretes Thema/Stichwort (z.B. „Mahnung", „Ökostrom-Tarif", „Kündigung"), erscheint dieses Stichwort unverändert im Suchkriterium.
- [ ] Generische Nutzeräußerungen ohne konkreten Inhalt (z.B. nur „Mails", „Rechnungen") führen nicht dazu, dass das LLM einen erfundenen Suchtext produziert, der wie ein Inhaltskriterium aussieht, aber keins ist — solche Fälle sollen als Recency-Fall (s.o.) statt als Inhalts-Suche behandelt werden.

## Edge Cases

- Recency-Anfrage mit Firmenfilter liefert 0 Treffer (z.B. keine Rechnung von einer nicht existierenden Firma) → bestehende „Keine Dokumente gefunden"/"Keine E-Mails gefunden"-Rückmeldung (PROJ-37) greift unverändert.
- Nutzer nennt eine sehr hohe Anzahl („die letzten 500 Mails") → wird nicht auf eine kleine Zahl gedeckelt; die bestehende technische Obergrenze in `alice-tool-search` (aktuell 100, siehe Input Normalizer) bleibt die einzige harte Grenze. **Offener Punkt für /architecture:** Das aktuelle Weaviate-Request-Timeout (10s) ist evtl. bei sehr hohen Limits nicht ausreichend — muss geprüft werden.
- Recency- **und** Inhaltssignal gemischt („die letzten Mahnungen von der Telekom") → zuerst nach Inhaltskriterium (Telekom, Mahnung) filtern, dann die Treffer nach Datum absteigend sortieren und auf N begrenzen.
- Nutzer nennt eine ungenaue Mengenangabe statt einer Zahl („zeig mir ein paar der letzten Mails") → Standard-N (5) wird verwendet.
- Nutzer antwortet auf die Rückfrage nach dem Dokumenttyp ausweichend oder bestätigend ohne Eingrenzung („ist mir egal", „einfach alles") → wird als expliziter Wunsch nach typübergreifender Ansicht gewertet (s. Acceptance Criteria), keine zweite Rückfrage.
- Typübergreifende Recency-Anfrage liefert Treffer aus mehreren Collections mit unterschiedlichen Datumsfeldern (z.B. `invoiceDate` vs. `date` bei Email) → Sortierung erfolgt über das jeweils passende Datumsfeld pro Treffer; die Ergebnisliste selbst ist unabhängig vom Feldnamen einheitlich (Treffer zeigen Typ + Datum).
- Vom Nutzer gesprochener Firmenname weicht von der exakten Schreibweise im Datensatz ab (z.B. „Enercity" vs. gespeichert „ENERCITY AG") → Erkennung/Matching-Genauigkeit ist technische Umsetzungsfrage für /architecture, keine neue Anforderung dieser Spec.

## Technical Requirements (optional)

- Betroffene Tools: `search_documents`, `search_emails` (beide in `alice-chat-stream`, dispatcht an `alice-tool-search`-Workflow bzw. `alice-mail-tools`-Workflow).
- Keine Änderung an bestehenden Permission-Checks (`Apply DMS Filter`-Node) — Recency-Sortierung greift erst nach der Permission-Filterung.

## Scope-Abgrenzung

**In Scope:**

- Erkennung von Recency-Absicht in Nutzeranfragen und entsprechende Datums-Sortierung (statt Relevanz-Score) für `search_documents` und `search_emails`.
- Übernahme konkreter, vom Nutzer genannter Suchbegriffe (Firmen, Themen) in das `query`-Argument, statt LLM-seitiger Paraphrasierung.
- Rückfrage nach dem Dokumenttyp bei typloser Recency-Anfrage; auf ausdrücklichen Wunsch typübergreifende, nach Datum gemischt sortierte Ergebnisliste über alle erlaubten Collections.

**Out of Scope:**

- Fuzzy-/Schreibweisen-Matching von Firmennamen (z.B. Abkürzungen, Groß-/Kleinschreibung) — bestehendes Hybrid-Matching-Verhalten bleibt unverändert.
- Neue UI-Elemente oder Frontend-Änderungen.
- Änderungen an `get_document_details`, `get_email_body`, `home_assistant`, `remember`, `recall`.

---

<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

_To be added by /architecture_

## QA Test Results

_To be added by /qa_

## Deployment

_To be added by /deploy_
