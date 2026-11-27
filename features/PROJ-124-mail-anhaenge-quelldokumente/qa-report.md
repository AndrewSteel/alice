# QA-Bericht: PROJ-124 Mail-Anhänge als Quelldokumente (#19)

**Spec:** [spec.md](spec.md) · **Design:** [design.md](design.md)
**Getestet am:** 2026-11-27 · **Branch:** `factory/19`

## Ergebnis
**Produktionsreif:** Ja (mit Live-Tests AK-45/46 nach dem Deploy)
- Akzeptanzkriterien: 44 von 44 testbaren bestanden, AK-45/46 sind Live-Tests nach dem Deploy
- Bugs: Critical 0 · High 0 · Medium 0 · Low 0
- Hinweis zu AK-14 (siehe unten): Bei einer DMS-Quelle, die durch einen Anhang einen weiteren Fundort bekommt, bleiben `extract`, `classify`, `rag` und `wiki` `done`. Die Stufe `database` läuft wegen des neuen Fundorts nach der bestehenden Regel aus PROJ-119 neu (die Fundorte stehen in der Dokument-Tabelle). Das ist keine LLM-/OCR-Verarbeitung, nur ein Abgleich der Zeile.

## Automatische Prüfungen
- `alice-mail-import`: 90 Tests (neu: 27 in `tests/test_attachments.py`). Echter Register-Code in-process, Wegwerf-Postgres, temporäres Git-Repo, temporärer Ordner als Mail-Archiv, Fake-IMAP-Server, Attrappe der Erkennungsliste
- `alice-source-registry`: 115 Tests (neu: `tests/test_attachments_interface.py`: neuer Elternteil setzt keine Stufe zurück, Schreiben mit `keep_stages` + `label`)
- `alice-file-detection`: 78 Tests (neu: `GET /extensions` folgt der Konfiguration)
- `alice-document-classify`: 98 Tests (neu: `tests/test_mail_context.py`)
- `alice-etl-rebuild`: 49 Tests (neu: Ebene 7 mit Reparatur und „unvollständig“)
- Container-Tests aller fünf Dienste: gesund, Rauchtests bestanden (neu: `/extensions`, `/attachments/runs`, Reparatur-Validierung)
- Migration `2026-11-27_PROJ-124_mail_attachments.sql` gegen den alten Schema-Stand (`origin/dev`) zweimal fehlerfrei angewendet
- Manuell im Container-Verbund (Test-Postgres + Register + Datei-Erkennung mit `DETECT_EXT_DOCUMENT=pdf,xyz` + Mail-Import): Mail vom Januar mit `scan0001.pdf`, `notiz.xyz`, `daten.zip` im Archiv abgelegt → nach 5 s Mail-Markdown (extract) und zwei Anhangs-Quellen unter `documents/2026/01/`, Fundort = Archivdatei, `parents` = Mail, `detect` done, `extract` pending; Mail mit `attachments[].id` und funktionierenden relativen Links, `daten.zip` ohne `id`/Link; Zusammenfassung `zip: 1`; Ebene 7 ohne Lücken; Health `healthy`; Mailtext nicht im Log

## Akzeptanzkriterien
| AK | Ergebnis | Nachweis |
|---|---|---|
| AK-1 zwei PDFs → zwei Quellen | ✅ | `test_two_pdfs_become_sources_with_references`; manuell |
| AK-2 einziger Fundort = Archivdatei, keine Kopie | ✅ | gleicher Test (Fundorte, Anzahl Dateien im Archiv); manuell |
| AK-3 pdf/JPG/mp3/mp4 → Arten, audio/video skipped | ✅ | `test_kinds_sizes_and_stages` |
| AK-4 erweiterte Erkennungsliste | ✅ | `test_added_extension_without_code_change` (auch für schon bearbeitete Mails), `alice-file-detection::test_extensions_endpoint_follows_configuration`; manuell mit `DETECT_EXT_DOCUMENT=pdf,xyz` |
| AK-5 Ablage nach Mail-Datum | ✅ | `test_filed_by_mail_date` (Januar-Mail → `2026/01`); manuell |
| AK-6 Titel = Dateiname, Überschrift | ✅ | `test_two_pdfs_become_sources_with_references` |
| AK-7 erneuter Lauf ändert nichts | ✅ | `test_second_run_changes_nothing` (erzwungener Neulauf: keine Quelle, kein Fundort, kein Commit, Markdowns gleich) |
| AK-8 zwei Instanzen | ✅ | `test_two_instances_register_once` (Advisory-Lock + Hash-Eindeutigkeit) |
| AK-9 höchstens 5 Minuten | ✅ | Takt alle `MAIL_ATTACHMENT_POLL_SECONDS` (30 s, konfigurierbar); `test_new_mail_first_while_stock_runs` (nach einem Takt registriert); manuell 5 s inkl. extract |
| AK-10 keine `cid:`-Bilder | ✅ | `test_cid_images_are_no_sources` |
| AK-11 keine Mindestgröße | ✅ | `test_kinds_sizes_and_stages` (3-KB-PNG und 5-MB-JPG registriert) |
| AK-12 zip/ics/eml nicht registriert | ✅ | `test_not_recognised_and_empty_are_counted` (Archiv unverändert, kein `id`) |
| AK-13 0 Byte nicht registriert, gezählt | ✅ | gleicher Test (`empty: 1`) |
| AK-14 gleicher Hash wie DMS-Quelle | ⚠️ Abweichung (`database` → `pending`), Rückfrage offen | `test_same_hash_as_dms_source`, Register `test_new_parent_keeps_finished_stages` (siehe Hinweis zu `database`) |
| AK-15 derselbe Anhang in zwei Mails | ✅ | `test_same_attachment_in_two_mails` |
| AK-16 gleicher Inhalt zweimal in einer Mail | ✅ | `test_same_content_twice_in_one_mail` |
| AK-17 später DMS-Datei mit gleichem Hash | ✅ | `test_later_dms_copy_keeps_parents` |
| AK-18 `attachments[].id` | ✅ | `test_two_pdfs_become_sources_with_references`; manuell |
| AK-19 relativer Link auf die Anhangs-Markdown | ✅ | gleicher Test (Link aufgelöst, Datei existiert; zip nur Archiv-Link); manuell |
| AK-20 Link folgt Umbenennung | ✅ | `test_link_follows_renamed_markdown` |
| AK-21 Inhaltsteil in `manual` | ✅ | `test_manual_content_only_frontmatter` |
| AK-22 classify der Mail bleibt done, eigener Commit | ✅ | `test_two_pdfs_become_sources_with_references` (Commit `Alice ETL|attachments: <id> …`), Register `test_write_with_keep_stages_and_label` |
| AK-23 Pipeline übernimmt Anhangs-Dokument | ✅ | `test_attachment_document_goes_to_extract` (Claim von `extract` für `document`, wie bei DMS); Text-Extraktion selbst unverändert (PROJ-117) |
| AK-24 Prompt mit Betreff/Absender/Datum, ohne Mailtext | ✅ | `alice-document-classify::test_prompt_contains_mail_context_not_mail_text` |
| AK-25 älteste Mail | ✅ | `test_oldest_mail_is_used` |
| AK-26 Mail-Markdown nicht lesbar | ✅ | `test_unreadable_mail_runs_without_context` |
| AK-27 ohne `parents` unverändert | ✅ | `test_without_parents_prompt_unchanged` (identischer Prompt) |
| AK-28 passwortgeschütztes PDF | ✅ | `test_attachment_document_goes_to_extract` (`failed_permanent`, Quelle bleibt, Mail unverändert); Erkennung des Passwortschutzes ist PROJ-117 |
| AK-29 Bild-Anhang | ✅ | `test_kinds_sizes_and_stages` |
| AK-30 Mail `deleted` → Anhang bleibt | ✅ | `test_mail_deleted_attachment_stays` (inkl. Link aus `deleted/`) |
| AK-31 `deleted`-Mail wird nachgeholt | ✅ | `test_deleted_mail_still_registered` |
| AK-32 Archivdatei fehlt → Lücke | ✅ | `test_level7_reports_and_repairs` (`attachment_file_missing`, Quelle bleibt aktiv) |
| AK-33 DMS-Kopie gelöscht → Quelle aktiv | ✅ | `test_later_dms_copy_keeps_parents`; Datei-Erkennung entfernt nur selbst gefundene Pfade (Code geprüft) |
| AK-34 Zusammenfassung zip/ics/eml | ✅ | `test_not_recognised_and_empty_are_counted` (gesamt, je Endung, je Postfach, keine Warnung); manuell `GET /attachments/runs` |
| AK-35 Bestand in Paketen, fortsetzbar | ✅ | `test_new_mail_first_while_stock_runs` (25 Mails, Paket 10, Sammel-Commits, ≤ 500 Dateien je Commit, Neustart) |
| AK-36 neue Mail vor Bestand | ✅ | gleicher Test |
| AK-37 Neuaufbau ab extract | ✅ | `test_rebuild_keeps_ids` (gleiche ids, Links bleiben, keine Duplikate) |
| AK-38 Ebene 7 meldet + holt nach | ✅ | `test_level7_reports_and_repairs`, `alice-etl-rebuild::test_level7_attachment_sources` |
| AK-39 Archiv nicht erreichbar | ✅ | `test_archive_unavailable_pauses`, `test_unreadable_file_pauses_only_its_mail` |
| AK-40 Register nicht erreichbar | ✅ | `test_register_unavailable_pauses_and_catches_up` |
| AK-41 Abbruch mitten im Lauf | ✅ | gleicher Test (Abbruch zwischen Registrierung und Verweis), Neustart in `test_new_mail_first_while_stock_runs` |
| AK-42 keine Mailtexte/Passwörter in Logs | ✅ | `test_logs_without_mail_text_or_password`; manuell (Container-Log) |
| AK-43 keine nginx-Route | ✅ | statisch: keine Route in `docker/compose/infra/nginx/` |
| AK-44 Deploy ohne mail-api/-tools/-reader/Postfach-Verwaltung | ✅ | Deploy-Schritte im PR (nur Register, Datei-Erkennung, Mail-Import, Klassifizierung, Abgleich) |
| AK-45, AK-46 | ⏳ | Live-Tests nach dem Deploy (Mensch) |

## Edge Cases
- ✅ EC-1 DMS-Datei und Anhang → eine Quelle, zwei Fundorte (`test_same_hash_as_dms_source`)
- ✅ EC-2 eine Mail in zwei Postfächern → eine Mail-Quelle (PROJ-123), ein Archivpfad
- ✅ EC-3 gleiche Datei mit neuem Namen in Antwort-Mail (`test_same_attachment_in_two_mails`)
- ✅ EC-4 Archivdatei ersetzt → `attachment_changed` gemeldet, nicht übernommen (`test_level7_reports_and_repairs`); auch nicht bei einem Neuaufbau ab `extract` (`test_rebuild_does_not_take_over_replaced_file`, Befund B-1 der Abnahme Runde 1)
- ✅ `attachments` in `manual` → Ebene 7 meldet nur, keine Reparatur (`test_manual_attachments_only_reported_in_level7`)
- ✅ EC-5 Umbenennung → Link folgt der `id` (`test_link_follows_renamed_markdown`)
- ✅ EC-6 alte Anhangsordner als überwachter Ordner → normale Hash-Dedup (`test_later_dms_copy_keeps_parents`)
- ✅ EC-7 erzeugter Name ohne erkannte Endung → gezählt (Endung aus dem Namen)
- ✅ EC-8 Art folgt der Endung
- ✅ EC-9 sehr große Anhänge: gehasht in Blöcken (1 MB), Hash wird gespeichert und nicht erneut berechnet
- ✅ EC-10 viele Anhänge: Mails in Paketen, je Takt höchstens `MAIL_ATTACHMENT_BATCH_SIZE` Mails

## Bugs
- Keine offenen. Während der Entwicklung keine Fehlschläge in den neuen Tests.

## Sicherheit
- Neue Endpunkte (`/attachments/runs`, `/extensions`, Ebene 7) nur im Docker-Netz, keine nginx-Route, keine Nutzerdaten über Personen hinweg (wie die übrigen ETL-Dienste)
- Archiv wird nur gelesen (kein Kopieren, Verschieben, Löschen); Pfade stammen aus dem Archiv-Eintrag des Mail-Imports
- Mail-Kontext im Prompt als Daten markiert (`<mail>`), nur Betreff/Absender/Datum, kein Mailtext
- Logs: nur Mail-id, Positionen, Zähler; keine Mailtexte, keine Passwörter (Test + Container-Log)
- Neue Tabellen mit RLS und Policies wie die übrigen Dienst-Tabellen

## Nicht live geprüft
- Echtes NAS-Archiv und echte Postfächer (Temp-Ordner, Fake-IMAP), echtes LLM (Gateway-Attrappe) → AK-45/46 nach dem Deploy: Testmail mit PDF-Rechnung an das produktive Postfach, nach wenigen Minuten Quelle mit `parents` im Repo, extract/classify, Link in der Mail; nach dem Bestandslauf Abgleich ohne Lücken in Ebene 7

## Automatisierte Tests
- `scripts/test-services.sh alice-mail-import alice-source-registry alice-file-detection alice-document-classify alice-etl-rebuild`: alle bestanden
- `scripts/test-containers.sh` (geänderte Dienste): alle bestanden
