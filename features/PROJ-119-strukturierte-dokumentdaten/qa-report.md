# QA-Bericht: PROJ-119 Strukturierte Dokumentdaten in PostgreSQL (#11)

**Spec:** [spec.md](spec.md) · **Design:** [design.md](design.md)
**Getestet am:** 2026-11-24 · **Commit:** `3cf2efa` (Code-Stand; dieser Bericht kommt als eigener Commit dazu)

## Ergebnis
**Produktionsreif:** Ja
- Akzeptanzkriterien: 33 von 33 testbaren bestanden (AK-34/35 sind Live-Tests nach Deploy)
- Bugs: Critical 0 · High 0 · Medium 0 · Low 0

Getestet mit dem echten Register-Code (in-process bzw. als Container), Wegwerf-PostgreSQL mit `sql/init-schema.sql` und temporärem Git-Repo; kein LLM (das Klassifizierungsergebnis wird wie von PROJ-118 über das Register geschrieben). Test-IBANs/-ISINs synthetisch mit gültiger Prüfziffer.

## Akzeptanzkriterien
| AK | Ergebnis | Nachweis |
|---|---|---|
| AK-1 Übernahme → DB → done | ✅ | automatisiert (`test_e2e.py::test_document_flow_and_no_repo_change`), manuell im Container-Systemtest |
| AK-2 classify pending/running/failed/failed_permanent → nichts | ✅ | automatisiert (`test_only_classified_documents`) |
| AK-3 andere Arten → nichts | ✅ | automatisiert (`test_only_classified_documents`, Art image) |
| AK-4 Aktualisierung innerhalb der Abfragefrist | ✅ | automatisiert (`test_hand_correction_lands_in_db`); Systemtest: 3 Dokumente nach 2,2 s bei Abfragefrist 2 s |
| AK-5 Bestand beim ersten Start | ✅ | automatisiert (`test_backlog_on_first_start`) |
| AK-6 keine Markdown-Änderung, kein Commit | ✅ | automatisiert (HEAD, `git status` und Dateiinhalt vor/nach gleich) |
| AK-7 Document mit allen gemeinsamen Feldern, keine Detail-Zeile | ✅ | automatisiert |
| AK-8 alle Typen mit allen Feldern, Datum/Dezimal | ✅ | automatisiert (`test_all_types_with_all_fields`) |
| AK-9 3 Rechnungspositionen 1–3 | ✅ | automatisiert |
| AK-10 250 Buchungen, Summe exakt | ✅ | automatisiert (`test_250_bookings_sum_exact`) |
| AK-11 null bleibt null | ✅ | automatisiert (Contract ohne Empfänger/Tags/Ende, Position ohne Menge) |
| AK-12 Merker abfragbar | ✅ | automatisiert (`test_flags_and_empty_statement`, `test_document_flow…`) |
| AK-13 leere Buchungsliste | ✅ | automatisiert |
| AK-14 Hand-Korrektur Betrag | ✅ | automatisiert (`test_hand_correction_lands_in_db`) |
| AK-15 10 → 9 Buchungen | ✅ | automatisiert (`test_new_version_replaces_bookings`) |
| AK-16 Typwechsel Invoice → Contract | ✅ | automatisiert (`test_type_change`) |
| AK-17 `manual` übersteht Neuaufbau | ✅ | automatisiert; Neuaufbau simuliert durch Zurücksetzen aller Stufen im Register (PROJ-120 noch nicht gebaut) |
| AK-18 direkte DB-Änderung überschrieben | ✅ | automatisiert |
| AK-19 Abbruch mitten im Eintragen | ✅ | automatisiert: Abbruch nach allen Schreibvorgängen vor dem Commit → alter Stand vollständig; Register-Zeitüberschreitung → erneut übernommen und fertig |
| AK-20 gelöschte Quelle entfernt (Kontoauszug, Rechnung) | ✅ | automatisiert + Systemtest |
| AK-21 Rückkehr wird wieder eingetragen | ✅ | automatisiert + Systemtest |
| AK-22 Dublette in B markiert, Summe einmal | ✅ | automatisiert + Systemtest |
| AK-23 unabhängig von der Reihenfolge | ✅ | automatisiert |
| AK-24 A gelöscht → B nicht mehr markiert | ✅ | automatisiert + Systemtest |
| AK-25 gleicher Auszug / andere IBAN / ohne IBAN | ✅ | automatisiert |
| AK-26 Original geändert → Markierung weg | ✅ | automatisiert |
| AK-27 „zwölf“, `31.13.2026`, `transactions` als Text | ✅ | automatisiert: `failed` mit Feld und Wert, DB unverändert, 5. Versuch `failed_permanent` |
| AK-28 Korrektur → done | ✅ | automatisiert (`test_invalid_hand_correction`) |
| AK-29 gesperrte Markdown | ✅ | automatisiert (`test_locked_markdown_keeps_db`) |
| AK-30 PostgreSQL nicht erreichbar | ✅ | automatisiert: Release ohne Fehlversuch (attempts 0), Warnung im Log, `/health` warning, danach selbstständig fertig |
| AK-31 keine nginx-Route | ✅ | statisch: kein Eintrag in `docker/compose/infra/nginx/`, kein veröffentlichter Port in `compose.yml` |
| AK-32 altes System unberührt | ✅ | statisch: Dienst hat keine Weaviate-/Redis-/n8n-Anbindung; keine Workflow-Änderung |
| AK-33 Schema-Skript wiederholbar | ✅ | manuell: frische Test-DB mit `init-schema.sql` ohne Fehler, Migration darauf zweimal; DB im alten Stand (`origin/dev`) Migration zweimal ohne Fehler, 7 Tabellen `alice.doc_*` vorhanden |
| AK-34, AK-35 | ⏳ | Live-Test nach Deploy (Mensch) |

## Edge Cases
- ✅ EC-1 drei Auszüge: beide späteren verweisen auf den frühesten (`test_three_statements_and_original_deleted`)
- ✅ EC-2 Original gelöscht: nächstfrühester wird Original, letzter verweist darauf
- ✅ EC-3 IBAN von Hand geändert: Markierungen beider Konten neu (`test_iban_changed_by_hand`)
- ✅ EC-4 vier Auszüge desselben Kontos parallel (Parallelität 4): eindeutig, keine gegenseitige Markierung
- ✅ EC-5 während der Verarbeitung gelöscht: kein Eintrag bleibt, Rückmeldung des alten Laufs nur geloggt
- ✅ EC-6 3000 Buchungen in einer Transaktion (eine Anweisung für alle Buchungen)
- ✅ EC-7 0,000123 und 1.250.000,01 exakt (Unit-Test, E2E, Container-Selbsttest)
- ✅ EC-8 fehlender Verwendungszweck gilt als gleich; ohne Datum oder Betrag kein Abgleich
- ✅ EC-9 ältere Fassung ohne Felder → null (Unit-Test)
- ✅ EC-10 classify wieder pending → DB-Stand bleibt (`test_classify_pending_again_keeps_db`)
- ✅ EC-11 Redis-Neustart: Dienst nutzt kein Redis; Arbeit kommt nur aus dem Register (Claim mit `kinds` läuft immer über PostgreSQL)
- ✅ EC-12 Neuaufbau: kein LLM, Abarbeitung ohne Eingriff (AK-5-Test)

## Bugs
Keine offenen. Während der Entwicklung behoben: keine fachlichen Fehler, nur Testkorrekturen.

## Regression
- Register: bestehender PROJ-115-Test „Fundort-Änderung setzt nichts zurück“ angepasst – `rag` bleibt `done`, `database` geht gewollt auf `pending` (Fundorte stehen in der DB). Alle übrigen Register-Tests unverändert grün.
- Abhängige Dienste (`alice-document-classify`, `alice-file-detection`, `alice-text-extraction`) gegen das geänderte Register grün.

## Sicherheit
- Der Dienst hat keine Endpunkte mit Eingaben (nur `/health`, `/status`), keine nginx-Route, keine Nutzerdaten-Zugriffe.
- Alle Abfragen parametrisiert; Spalten- und Tabellennamen kommen nur aus Konstanten im Code, nie aus dem Frontmatter.
- Frontmatter-Werte werden streng typgeprüft; Fehlermeldungen enthalten den Wert gekürzt (max. 200 Zeichen) und landen nur im Register (`last_error`), nicht in Logs außerhalb des Dienstes.
- RLS + Policies auf allen neuen Tabellen; Rollenprüfung für Leser folgt in PROJ-128.
- Keine Zugangsdaten im Code; `.env.example` nur mit Platzhaltern.

## Nicht live geprüft
- Echte klassifizierte Dokumente (AK-34) und die 15-Minuten-Frist mit echter Hand-Korrektur (AK-35): nur mit synthetischen Dokumenten geprüft. Nach Deploy: Stichprobe je Typ (`SELECT … FROM alice.doc_*`) mit dem Frontmatter vergleichen, für einen echten Kontoauszug `SELECT sum(amount) FROM alice.doc_bank_transactions WHERE document_id = '<id>'` gegen Endsaldo − Anfangssaldo; einen Betrag in einer Quell-Markdown ändern und nach ≤ 15 min in `alice.doc_invoices` prüfen.

## Automatisierte Tests
- `scripts/test-services.sh alice-document-database`: 44 bestanden
- `scripts/test-services.sh alice-source-registry alice-document-classify alice-file-detection alice-text-extraction`: 95 / 93 / 66 / 73 bestanden
- `scripts/test-containers.sh alice-document-database alice-source-registry`: beide gesund, Rauchtests bestanden
- Systemtest mit Containern (Register + Dienst + Test-PostgreSQL, echtes HTTP): Eintragen, Dublette, Löschen, Rückkehr bestanden
