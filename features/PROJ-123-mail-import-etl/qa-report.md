# QA-Bericht: PROJ-123 Mail-Import in den ETL (#17)

**Spec:** [spec.md](spec.md) · **Design:** [design.md](design.md)
**Getestet am:** 2026-11-26 (Runde 2 nach Abnahme-Rückgabe) · **Branch:** `factory/17`

## Ergebnis
**Produktionsreif:** Ja (mit Live-Tests AK-57/58 nach dem Deploy)
- Akzeptanzkriterien: 56 von 56 testbaren bestanden, AK-57/58 sind Live-Tests nach dem Deploy
- Bugs: Critical 0 · High 0 · Medium 0 · Low 0 (ein während der Entwicklung gefundener Fehler behoben: Abruf von UIDs im zuletzt geöffneten statt im richtigen Ordner)

## Automatische Prüfungen
- `alice-mail-import`: 63 Tests (Unit + Integration). Echter Register-Code in-process, Wegwerf-Postgres, temporäres Git-Repo, temporärer Ordner als Mail-Archiv, Fake-IMAP-Server (echtes IMAP-Protokoll über TCP, `tests/fakeimap.py`) und Gateway-Attrappe
- `alice-source-registry`: 113 Tests (neu: Mail-Fundort mit Ordner + UID)
- `alice-etl-rebuild`: 47 Tests (neu: `tests/test_reconcile_mail.py`, Ebenen 5/6)
- Container-Tests `alice-mail-import`, `alice-source-registry`, `alice-etl-rebuild`: gesund, Rauchtests bestanden
- Migration gegen den alten Schema-Stand (`origin/dev`) zweimal fehlerfrei angewendet; vorhandene Mail-Quelle bekommt `database = skipped`
- Manuell im Container-Verbund (Test-Postgres + Register + Mail-Import + Fake-IMAP + Fake-Gateway): 6 Mails im Server, 5 importiert (Spam nicht), Archiv mit `.eml` und ausgelagerten Anhängen, Markdown mit allen Feldern, `classify` mit `Bearer`-Schlüssel und `enable_thinking: false`, Flags unverändert, keine schreibenden IMAP-Befehle, höchstens 1 Verbindung, kaputte Mail `extract = failed_permanent`, Nachtlauf über `/maintenance/nightly` ohne Entfernungen, Health `healthy`

## Akzeptanzkriterien
| AK | Ergebnis | Nachweis |
|---|---|---|
| AK-1 nur INBOX + Gesendet | ✅ | `test_import.py::test_inbox_and_sent_only_read_only` (Spam, Papierkorb, Entwürfe, Archiv nicht importiert); manuell |
| AK-2 Startdatum / ohne Startdatum | ✅ | `test_start_date_and_mailbox_without_start_date` |
| AK-3 Gesendet über `\Sent`, sonst Ordnername | ✅ | `test_inbox_and_sent_only_read_only` („Gesendet“ mit `\Sent`), `test_sent_folder_fallback_name` |
| AK-4 nur lesend | ✅ | Flags vorher/nachher gleich, Befehlsliste nur CAPABILITY/LOGIN/LIST/EXAMINE/UID SEARCH/UID FETCH/LOGOUT, keine Verstöße; manuell |
| AK-5 neue Mail im nächsten Takt | ✅ | `test_new_mail_in_next_tick_and_idempotent` (nächster Takt nach Sync-Intervall) |
| AK-6 Wiederholung ohne Änderungen | ✅ | gleicher Test: keine Quelle, kein Commit, keine Archivdatei; `test_same_message_id_twice_in_one_folder` (zwei Kopien mit gleicher Message-ID in INBOX: 3 weitere Takte ohne Abruf und ohne Commit, Nachtlauf mit gelöschter Kopie ohne `deleted`) |
| AK-7 eine Quelle, mehrere Fundorte | ✅ | `test_same_mail_in_two_folders_and_two_mailboxes` (INBOX + Gesendet + zweites Postfach, eine `.eml`) |
| AK-8 Mails ohne Message-ID | ✅ | `test_mails_without_message_id`, `test_mime.py::test_identity_without_message_id` |
| AK-9 zwei Instanzen | ✅ | `test_two_instances_one_connection`, `test_two_instances_ticking` (Advisory-Lock je Postfach) |
| AK-10 Archivstruktur, byte-gleich | ✅ | `test_archive_markdown.py::test_archive_layout_and_markdown`, `test_mime.py::test_pdfs_are_moved_out_byte_identical` |
| AK-11 `.eml` mit Parser lesbar, Verweise statt PDFs | ✅ | gleiche Tests (`message/external-body`, Name = `<id>.attachments/<datei>`) |
| AK-12 `cid:`-Bilder bleiben | ✅ | `test_cid_images_stay_embedded`, `test_cid_and_forward_through_import` |
| AK-13 weitergeleitete Mail als `.eml` | ✅ | `test_forwarded_mail_is_an_attachment` (byte-gleich inkl. CRLF), `test_cid_and_forward_through_import` |
| AK-14 gleiche Namen, Umlaut-Name | ✅ | `test_same_names_and_encoded_umlaut`, `test_markdown_special_cases` |
| AK-15 Anhang > 100 MB | ✅ | `test_big_attachment` (101 MB über IMAP, byte-gleich) |
| AK-16 nie überschrieben | ✅ | `test_archive_is_never_overwritten` (erneuter Import + neues extract) |
| AK-17 Frontmatter | ✅ | `test_archive_layout_and_markdown` (alle Felder, kein Zustand), `test_no_attachment_section_without_attachments` (`bcc` nur wenn vorhanden) |
| AK-18 Text-Teil vollständig | ✅ | `test_markdown_text_and_frontmatter` |
| AK-19 HTML → Markdown | ✅ | `test_html_only_to_markdown` (Links, Tabelle; ohne Bilder, Pixel, CSS, Skript) |
| AK-20 > 50.000 Zeichen, Zitate | ✅ | `test_long_text_with_quotes_is_complete` |
| AK-21 Abschnitt „Anhänge“ | ✅ | `test_markdown_text_and_frontmatter`, `test_no_attachment_section_without_attachments` |
| AK-22 Kodierungen | ✅ | `test_encodings` (RFC 2047, ISO-8859-1, falsch deklariert, unbekannter Zeichensatz), `test_markdown_special_cases` |
| AK-23 ohne Betreff | ✅ | `test_no_subject`, `test_markdown_special_cases` (Dateiname `…-ohne-betreff.md`) |
| AK-24 YAML-Sonderzeichen | ✅ | `test_yaml_breaking_subject_stays_valid`, `test_markdown_special_cases` |
| AK-25 Sprache ohne LLM | ✅ | `test_language`, `test_markdown_special_cases` |
| AK-26 `manual` geschützt | ✅ | `test_manual_fields_survive` (`title` + `content` von Hand, extract erneut) |
| AK-27 Stufenzustände | ✅ | `test_inbox_and_sent_only_read_only`; manuell (detect/extract done, classify pending → done, database skipped) |
| AK-28 classify setzt Kategorie + Zusammenfassung | ✅ | `test_classify` („Werbung“ → `promotion`, Commit `classify: <id> <title>`) |
| AK-29 Hintergrund, ohne Thinking, Länge | ✅ | `test_classify` (eigener Hintergrund-Schlüssel, `enable_thinking: false`, 300 Zeichen); manuell |
| AK-30 Zusammenfassung deutsch angefordert | ✅ | `test_classify` (englischer Text, Systemprompt verlangt Deutsch) |
| AK-31 ungültige Kategorie / Gateway weg | ✅ | `test_classify_errors` (`failed` mit Backoff, Markdown unverändert) |
| AK-32 `category` in `manual` | ✅ | `test_category_in_manual` |
| AK-33 gelöscht → `deleted`, Archiv bleibt | ✅ | `test_nightly_errors.py::test_deleted_on_server` |
| AK-34 nur ein Fundort entfernt | ✅ | `test_removed_from_one_folder_only` |
| AK-35 Reaktivierung | ✅ | `test_restored_mail_is_reactivated` (gleiche `id`, Stufen bleiben `done`) |
| AK-36 20-%-Grenze | ✅ | `test_mass_loss_is_blocked` |
| AK-37 Postfach nicht erreichbar / leere Ordnerliste | ✅ | `test_unreachable_mailbox_removes_nothing`, `test_empty_folder_list_removes_nothing` |
| AK-38 Postfach gelöscht | ✅ | `test_deleted_mailbox` (ohne Grenze, Archiv unverändert) |
| AK-39 fehlende Mails nachholen | ✅ | `test_missing_mails_are_fetched` |
| AK-40 Startdatum früher/später | ✅ | `test_earlier_and_later_start_date` |
| AK-41 Anmeldung abgelehnt / Server weg | ✅ | `test_login_rejected`, `test_server_unreachable`, `test_status_fields` |
| AK-42 kaputter MIME-Aufbau | ✅ | `test_broken_mime` (Rohmail byte-gleich, `failed_permanent`, übrige laufen); manuell |
| AK-43 Verbindungsabbruch | ✅ | `test_connection_drop` (keine Duplikate, keine halben Dateien) |
| AK-44 Archiv nicht erreichbar | ✅ | `test_archive_unavailable` (Pause mit Warnung, kein Register-Eintrag, setzt fort), `test_archive_not_writable_during_import` |
| AK-45 Neustart mitten im Import | ✅ | `test_hard_stop_between_register_and_archive` (harter Abbruch nach der Registrierung, Neustart legt die fehlende `.eml` im nächsten Takt selbst ab, `extract` danach done), `test_restart_leftovers` (temporäre Reste aufgeräumt, Ebene 6 als Absicherung); Schreiben nur über temporären Namen + Umbenennen |
| AK-46 2.000 Mails in Paketen | ✅ | `test_mass_import_batch_commits` (4 Pakete à 500, Commits ≤ 500 Dateien) |
| AK-47 neue Mail während Erstimport | ✅ | `test_history_in_packages_new_mail_first` |
| AK-48 eine Verbindung je Postfach | ✅ | `test_two_instances_one_connection` (`max_active == 1`); manuell |
| AK-49 Statusfelder | ✅ | `test_status_fields`; manuell (`active`, `mails_indexed`, `last_synced_at`). Der Settings-Tab liest diese Felder unverändert (nicht im Browser geprüft, keine Frontend-Änderung) |
| AK-50 Neuaufbau ohne IMAP | ✅ | `test_rebuild_from_archive_without_imap` (Server weg, `manual`-Titel bleibt, classify folgt) |
| AK-51 Ebene IMAP ↔ Register | ✅ | `test_reconcile_levels`, `test_reconcile_repair_imports`; `alice-etl-rebuild/tests/test_reconcile_mail.py::test_levels_5_and_6` |
| AK-52 Ebene Register ↔ Mail-Archiv | ✅ | `test_reconcile_levels` (neu abgelegt bzw. „nicht mehr auf dem Server“), `test_level6_gap_only_reported_when_gone_from_server` |
| AK-53 beide Ebenen in der Zusammenfassung | ✅ | `test_levels_5_and_6` (Ebenen „5“ und „6“ mit Zahlen und Lücken-Liste über die PROJ-120-Schnittstelle) |
| AK-54 keine nginx-Route | ✅ | statisch: keine Route in `docker/compose/infra/nginx/`, Dienst nur im Docker-Netz |
| AK-55 keine Passwörter/Mailtexte in Logs | ✅ | `test_no_passwords_or_mail_texts_in_logs`; manuell (Log des Containers ohne Passwort/Mailtext) |
| AK-56 Deploy-Schritte | ✅ | im PR: vier Workflows deaktivieren, `alice-mail-api`, `alice-mail-tools`, `alice-mail-reader` unverändert (keine Datei dieser Bausteine geändert) |
| AK-57 Live-Test Erstimport | ⏳ | nach dem Deploy durch den Menschen |
| AK-58 Live-Test Testmail mit PDF | ⏳ | nach dem Deploy durch den Menschen |

## Edge Cases
| EC | Ergebnis | Nachweis |
|---|---|---|
| EC-1 Mail an sich selbst | ✅ | `test_same_mail_in_two_folders_and_two_mailboxes` |
| EC-2 Gmail archiviert (verlässt INBOX) | ✅ | wie AK-33 (Fundort weg → `deleted`, Archiv bleibt) |
| EC-3 gleiche Message-ID, anderer Inhalt | ✅ | `test_identity_by_message_id`; erste Fassung bleibt, Hinweis im Log |
| EC-4 UIDVALIDITY-Wechsel | ✅ | `test_uidvalidity_change` (keine Entfernung, keine Duplikate, neue UIDs) |
| EC-5 Datum in der Zukunft / fehlt | ✅ | Ablage nach Empfangszeitpunkt (Code), `date` aus dem Empfangszeitpunkt |
| EC-6 sehr große Mail | ✅ | wie AK-15; Postfächer laufen parallel (je Postfach eine Aufgabe) |
| EC-7 Anhang ohne Namen | ✅ | `test_unnamed_and_calendar_attachments` (`anhang-1.bin`) |
| EC-8 verschlüsselt | ✅ | `test_encrypted_mail_is_marked` |
| EC-9 Kalendereinladung | ✅ | `test_unnamed_and_calendar_attachments` |
| EC-10 Anzeigename geändert | ✅ | Archiv-Schlüssel wird beim ersten Import festgelegt (`mail_import_mailboxes`) |
| EC-11 Kategorie von Hand | ✅ | `test_category_in_manual` |
| EC-12 Redis-Neustart | ✅ | Dienst nutzt kein Redis |
| EC-13 zwei Postfächer, gleiches Konto | ✅ | wie AK-7 |

## Sicherheit
- Keine nginx-Route, keine Endnutzer-Daten über die Schnittstelle; Endpunkte ohne Token wie bei den übrigen ETL-Diensten (nur Docker-Netz).
- Passwörter nur im Speicher; Fehlermeldungen ohne Passwort/Host-Details; Test prüft Logs und `last_error`.
- Dateinamen aus Mails werden bereinigt (kein `/`, `..`, Steuerzeichen) → kein Schreiben außerhalb des Archivs (`test_bad_characters_in_file_names`).
- Prompt-Injection über Mailtext: Die LLM-Antwort darf nur eine von vier Kategorien und einen Text setzen, beides wird geprüft und als YAML-Wert geschrieben.
- SQL nur parametrisiert.

## Nicht live geprüft
- Echter IMAP-Server (Gmail-Ordnernamen, TLS, Anbieter-Eigenheiten), NAS-Freigabe mit NAS-Konto, echtes LLM → AK-57/58 nach dem Deploy: Status im Settings-Tab, `docker logs alice-mail-import`, `GET http://alice-mail-import:8019/status`, Archivordner `/mnt/nas/ai/mail/`.

## Hinweise
- Sammel-Commits des Registers heißen wie bisher `rebuild: <stufe> <n> sources` (PROJ-115), auch beim Erstimport.
- Runde 2: Abnahme-Befunde behoben. B-1 (gleiche Message-ID zweimal im Ordner → Abruf und Commit je Takt, High), B-2 (Quelle ohne `.eml` nach hartem Abbruch, Medium), B-3 (weitergeleitete Mail mit LF statt CRLF, Low). Je ein neuer Test bzw. eine verschärfte Prüfung.
