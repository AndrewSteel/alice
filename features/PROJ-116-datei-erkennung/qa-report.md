# QA-Bericht: PROJ-116 Datei-Erkennung (#5)

**Spec:** [spec.md](spec.md) · **Design:** [design.md](design.md)
**Getestet am:** 2026-11-22 · **Commit:** `ae8736d` (Code-Stand; danach nur dieser Bericht und INDEX)

## Ergebnis
**Produktionsreif:** Ja (vorbehaltlich Live-Test AK-32 durch den Menschen)
- Akzeptanzkriterien: 31 von 31 in der Factory prüfbaren bestanden, AK-32 nur live
- Bugs: Critical 0 · High 0 offen (1 gefunden und behoben) · Medium 0 · Low 0

## Akzeptanzkriterien
Tests: `docker/compose/automations/alice-file-detection/tests/` (Erkennung + echter Register-Dienst in-process + Temp-Git-Repo + Wegwerf-Postgres) und `alice-source-registry/tests/test_deleted.py`.

| AK | Ergebnis | Nachweis |
|---|---|---|
| AK-1 neue Datei nach zwei Scans | ✅ | automatisiert (`test_new_file_registered_after_two_scans`), manuell gegen Test-Container |
| AK-2 wachsende Datei wartet | ✅ | automatisiert (`test_growing_file_waits`) |
| AK-3 Kopie mit alter Änderungszeit | ✅ | automatisiert (`test_copy_with_old_mtime_detected`) |
| AK-4 10.000 Dateien ohne Änderung | ✅ | automatisiert (`test_unchanged_tree_not_listed_or_hashed`: 0 Listen-, 0 Hash-Aufrufe, 201 Ordner nur per Änderungszeit geprüft) |
| AK-5 Arten nach Endung | ✅ | automatisiert (`test_kinds_by_extension`, `test_kind_of`) |
| AK-6 Übersprunglisten | ✅ | automatisiert (`test_skip_rules`: weder registriert noch als Endung gezählt) |
| AK-7 Kopie → zusätzlicher Fundort | ✅ | automatisiert (`test_copy_adds_location`) |
| AK-8 Verschieben tagsüber / nachts | ✅ | automatisiert (`test_move_keeps_id_old_location_until_night`), manuell gegen Test-Container |
| AK-9 Tagesscan entfernt nie | ✅ | automatisiert (`test_day_scan_never_removes`) |
| AK-10 einer von zwei Fundorten weg | ✅ | automatisiert (`test_night_removes_one_of_two_locations`) |
| AK-11 `deleted` + Markdown nach `deleted/` | ✅ | automatisiert (`test_night_deletes_source_and_moves_markdown`, Register `test_deleted_markdown_moves_to_deleted_dir`, `git log --follow`), manuell gegen Test-Container |
| AK-12 keine Vergabe an Worker | ✅ | automatisiert (Register `test_deleted_source_not_claimed`, mit und ohne Redis) |
| AK-13 Reaktivierung | ✅ | automatisiert (`test_reappearing_original_reactivates`, Register `test_reactivation_moves_back` inkl. `manual` und erledigter Stufen) |
| AK-14 Hand-Löschen in `deleted/` | ✅ | automatisiert (Register `test_hand_delete_in_deleted_dir_accepted`) |
| AK-15 Wiederherstellen aus Git-Historie | ✅ | automatisiert (Register `test_reappearing_after_hand_delete_restores_last_state`, `test_reappearing_without_history_recreates`) |
| AK-16 in-place, einziger Fundort | ✅ | automatisiert (`test_changed_in_place_single_location`, Register `test_update_original_resets_stages_after_detect`) |
| AK-17 in-place mit Kopie | ✅ | automatisiert (`test_changed_in_place_with_copy`) |
| AK-18 in-place auf bekannten Hash | ✅ | automatisiert (`test_changed_in_place_to_known_hash`) |
| AK-19 deaktivierter Ordner eingefroren | ✅ | automatisiert (`test_disabled_folder_frozen`) |
| AK-20 Ordner aus der Liste gelöscht | ✅ | automatisiert (`test_folder_deleted_from_list`: 80 % entfernt, Zusammenfassung nennt Ordner + Anzahl) |
| AK-21 verschachtelte Ordner | ✅ | automatisiert (`test_nested_folders_longest_match`, `test_nested_folder_added_later_reassigns`) |
| AK-22 Ordner nicht lesbar / leer | ✅ | automatisiert (`test_unreadable_or_empty_folder_skipped`, `test_unreadable_subfolder_protected`), manuell: Health `warning` mit Ordner |
| AK-23 20-%-Grenze | ✅ | automatisiert (`test_deletion_limit_per_share` 25 % blockiert / 15 % entfernt) |
| AK-24 Erkennungsprobleme | ✅ | automatisiert (`test_unreadable_file_is_problem_until_readable`, echte Datei mit `chmod 000`) |
| AK-25 Register nicht erreichbar | ✅ | automatisiert (`test_register_unavailable_pauses`), manuell: Register-Container gestoppt → `paused`, Health-Warnung, nach Start Datei registriert |
| AK-26 keine parallelen Läufe | ✅ | automatisiert (`test_no_parallel_runs`, `test_api_trigger_busy_and_runs` → 409 `busy`) |
| AK-27 Nachholen nach Neustart | ✅ | automatisiert (`test_nightly_due_and_catchup`, `test_interrupted_night_no_duplicates`) |
| AK-28 erster Lauf, Sammel-Commits | ✅ | automatisiert (`test_first_run_registers_inventory`: 1.200 Dateien, 3 Commits ≤ 500, Fortschritt im Log); manuell 31 Dateien → ein Commit `rebuild: detect 31 sources` |
| AK-29 Zusammenfassung mit Endungen | ✅ | automatisiert (`test_summary_counts_unsupported_extensions`: `zip: 3`, `exe: 1` je Ordner und gesamt, gespeichert in `alice.detect_runs`) |
| AK-30 manuell auslösen, keine nginx-Route | ✅ | automatisiert (`test_api_trigger_busy_and_runs`, `test_no_nginx_route`), Container-Rauchtest |
| AK-31 altes System unverändert | ✅ | automatisiert (`test_originals_untouched`: Hash/Größe/mtime vorher = nachher; `test_no_redis_or_weaviate`: kein Redis-/Weaviate-Code, Originale nur `rb`) |
| AK-32 Live-Test | ⏳ | nur nach Deploy durch den Menschen |

## Edge Cases
- ✅ EC-1: Datei verschwindet beim Hashen → kein Fehler, kein Problem-Eintrag (`test_file_vanishes_while_hashing`)
- ✅ EC-2: zwei identische Dateien im selben Scan → eine Quelle, zwei Fundorte (`test_copy_adds_location`)
- ✅ EC-3: umbenannt + geändert → neue Quelle, alte nachts `deleted` (`test_rename_and_change_at_once`)
- ✅ EC-4: Hash in Blöcken (`test_large_file_hashed_in_chunks`), läuft im Hintergrund-Thread
- ✅ EC-5: Umlaute, Leerzeichen, Sonderzeichen, lange Pfade (`test_originals_untouched`); Namen, die kein gültiges UTF-8 sind → Erkennungsproblem (`test_invalid_utf8_name_is_problem_not_failure`)
- ✅ EC-6: umbenannter überwachter Ordner → gleiche Quellen, nichts neu, nichts `deleted` (`test_renamed_folder_keeps_sources`)
- ✅ EC-7: kaputtes PDF wird registriert (`test_broken_pdf_is_registered`)
- ✅ EC-8: Links werden übersprungen, keine Schleifen (`test_skip_rules` mit Datei- und Ordner-Link)
- ✅ EC-9: nur Gleichheit der Ordnerzeit zählt (Design; AK-3-Test mit Zeitstempel aus dem Jahr 2000)
- ✅ EC-10: Hand-Änderung in `deleted/` wird vor dem Zurückschieben übernommen (Register `test_hand_edit_in_deleted_dir_taken_over_before_moving_back`)

## Bugs
- **B-1 (High, behoben):** Ein Dateiname, der kein gültiges UTF-8 ist (z. B. alte Windows-Kopie mit Latin-1-Umlaut), ließ jeden Nachtlauf mit `UnicodeEncodeError` scheitern — eine einzige Datei hätte die ganze Erkennung blockiert. · Schritte: 1. Datei `kaputt_\xe4.pdf` (Byte-Name) in einen überwachten Ordner legen 2. Nachtlauf auslösen · Erwartet: Lauf fertig, Datei als Problem · Tatsächlich: Lauf `failed`. · Fix: solche Namen werden als Erkennungsproblem („Dateiname/Ordnername ist kein gültiges UTF-8") geführt und übersprungen; der Eintrag verschwindet, wenn der Nachtlauf die Datei nicht mehr findet.

## Hinweise (keine Bugs)
- Folge der Spec-Regel AK-22: Wird ein überwachter Ordner **vollständig** geleert (z. B. Eingangsordner, aus dem alles wegsortiert wurde), gilt er als „Mount fehlt"; seine Fundorte bleiben stehen, bis wieder eine Datei darin liegt.
- Scheduled Tagesscans starten erst nach dem ersten fertigen Nachtlauf (damit der Bestand mit Sammel-Commits registriert wird). Nach dem Deploy daher den ersten Nachtlauf manuell auslösen (AK-32).
- Nach einer Ordneränderung wird der Ordner im nächsten Tagesscan einmal zur Bestätigung erneut gelistet (Schutz vor gleichzeitig angelegten Dateien bei groben NAS-Zeitstempeln).

## Sicherheit
- Keine Auffälligkeiten. Schnittstelle (Port 8013) ohne Authentifizierung wie PROJ-115, aber ohne nginx-Route und nur im Docker-Netz; kein Nutzerbezug. Eingaben: nur `kind` (day/night), Lauf-ID (int), `limit` (begrenzt). Alle SQL-Abfragen parametrisiert. Originale werden nur lesend geöffnet, der Dienst schreibt nur über den Register-Dienst. Keine Zugangsdaten im Code; `.env.example` nur mit Platzhaltern.
- Die Quelle der Wahrheit liegt nach dem Deploy auf einer eigenen Freigabe, die nur der Register-Dienst einbindet (nicht in `nas-volumes.yml`).

## Nicht live geprüft
- Echte NAS-Freigaben (NFS, Rechte des NAS-Kontos, Ausfall einer Freigabe), Umzug des produktiven Repos auf die eigene Freigabe → in der Factory mit Temp-Ordnern und umbenannten/leeren Ordnern nachgestellt. Prüfung im Staging (`scripts/stage.sh alice-file-detection <PR>`):
  - `docker run --rm --network backend curlimages/curl -s http://alice-file-detection-staging:8013/health` → `healthy` bzw. `warning` mit Ordnernamen
  - **Achtung:** Das Staging schreibt über den produktiven Register-Dienst ins Register. Einen Lauf dort nur auslösen, wenn das gewollt ist (z. B. als erster Nachtlauf).
- AK-32 Live-Test nach Deploy.

## Automatisierte Tests
- `scripts/test-services.sh alice-source-registry alice-file-detection`: 77 + 65 bestanden
- `scripts/test-containers.sh alice-source-registry alice-file-detection`: beide gesund, Rauchtests bestanden
- Migration gegen das Schema von `origin/dev` zweimal angewendet: fehlerfrei
