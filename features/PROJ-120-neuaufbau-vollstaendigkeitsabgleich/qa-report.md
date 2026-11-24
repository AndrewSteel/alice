# QA-Bericht: PROJ-120 Neuaufbau + Vollständigkeitsabgleich (#12)

**Spec:** [spec.md](spec.md) · **Design:** [design.md](design.md)
**Getestet am:** 2026-11-24 · **Branch:** `factory/12`

## Ergebnis
**Produktionsreif:** Ja (mit Live-Tests AK-47–49 nach dem Deploy)
- Akzeptanzkriterien: 46 von 46 testbaren bestanden (AK-12 über den bestehenden PROJ-118-Mechanismus), AK-47–49 sind Live-Tests nach Deploy
- Bugs: Critical 0 · High 0 · Medium 0 · Low 0 (zwei während der QA gefundene Kleinigkeiten behoben, siehe unten)

## Akzeptanzkriterien
| AK | Ergebnis | Nachweis |
|---|---|---|
| AK-1 Neuaufbau ab `classify` | ✅ | `alice-etl-rebuild/tests/test_rebuild.py::test_rebuild_from_classify`; manuell im Container-Verbund (12 Quellen, `abgeschlossen`) |
| AK-2 Art-Filter | ✅ | `test_kind_filter` |
| AK-3 neue Stufe gehört dazu (sobald bedient) | ✅ | `test_new_served_stage_joins_scope` (Option A der Rückfrage) |
| AK-4 `failed_permanent` → `pending`, Zähler 0 | ✅ | `test_failed_permanent_restarts_at_zero`, Register `test_release_flags_and_resets_attempts` |
| AK-5 Ausnahmen mit Grund | ✅ | `test_exclusions_counted` (gelöscht, gesperrt, audio = `skipped`, image = `not_served`) |
| AK-6 Momentaufnahme | ✅ | `test_snapshot_new_source_not_in_run` |
| AK-7 nur ein Lauf | ✅ | `test_only_one_run`, `test_api.py::test_http_flow` (409 mit bestehendem Lauf); manuell |
| AK-8 `manual` bleibt (Markdown + DB) | ✅ | `test_manual_value_survives` (DB-Stufe simuliert, übernimmt das Frontmatter wie PROJ-119) |
| AK-9 Sammel-Commits ≤ 500 | ✅ | `test_batch_commits` (1.200 Quellen ab `extract`: nur `rebuild: …`-Commits, max. 500 Dateien); manuell: `rebuild: classify 12 sources` |
| AK-10 Drosselung N | ✅ | `test_throttle` (N = 20, 500 Quellen, nach jeder Runde geprüft); manuell N = 4: max. 4 je Stufe |
| AK-11 Normalbetrieb vor Neuaufbau | ✅ | Register `test_normal_work_before_rebuild_work`, `test_redis_claim_fills_with_rebuild_work` |
| AK-12 LLM als Hintergrundlast | ✅ | statisch: `alice-document-classify` ruft das Gateway mit eigenem Hintergrund-Schlüssel (PROJ-118, AK-40 dort getestet); der Neuaufbau ändert daran nichts |
| AK-13 Pausieren | ✅ | `test_pause_resume`; manuell (freigegeben 8 vor/nach der Pause) |
| AK-14 Fortsetzen ohne Doppelverarbeitung | ✅ | `test_pause_resume` |
| AK-15 Abbrechen ohne Zurückrollen | ✅ | `test_cancel` (10 von 50 freigegeben, 40 unverändert, kein Abgleich); manuell |
| AK-16 Neustart (laufend/pausiert) | ✅ | `test_restart[False/True]` |
| AK-17 Abgleich „nach Neuaufbau“ | ✅ | `test_reconcile.py::test_after_rebuild`; manuell (Ergebnis 1 `after_rebuild` an Lauf 1) |
| AK-18 Fortschrittsfelder | ✅ | `test_progress_fields_and_errors` (100 Quellen, 3 ausgenommen, Summe je Stufe = 97) |
| AK-19 Fehlerliste | ✅ | `test_progress_fields_and_errors` |
| AK-20 < 200 ms bei 50.000 Quellen, 20 Abrufe/s | ✅ | `test_api.py::test_progress_50000_sources` (max. Antwortzeit und Alter gemessen; keine Aufrufe an Register/Erkennung außer dem Health-Check der Lauf-Schleife); manuell max. 3 ms |
| AK-21 Log-Zeilen | ✅ | `test_log_lines` (Intervall 60 s, Zeit vorgestellt); manuell mit 10 s |
| AK-22 Liste der Läufe | ✅ | `test_list_of_runs` |
| AK-23 nicht registrierte Datei | ✅ | `test_reconcile.py::test_level1_register_and_missing`, Erkennung `test_check_finds_unregistered_and_missing` |
| AK-24 Datei fehlt → nur melden | ✅ | dieselben Tests |
| AK-25 gleiche Größe/Zeit, anderer Inhalt | ✅ | `test_rehash_changed_content`, Erkennung `test_same_size_and_mtime_changed_content` |
| AK-26 Markdown fehlt (Historie / neu anlegen) | ✅ | Register `test_missing_markdown_restored_from_history`, `test_missing_markdown_without_history_recreated`; E2E `test_level2_and_events` |
| AK-27 Markdown ohne Registereintrag / falsches `kind` | ✅ | Register `test_orphan_and_kind_mismatch_reported`, E2E `test_level2_orphan_reported` |
| AK-28 falscher Ort, Git-Umbenennung | ✅ | Register `test_wrong_place_moved_with_history` (`git log --follow`) |
| AK-29 Ebene 3 ohne Quellen eines aktiven Laufs | ✅ | `test_level3_pending_too_long` |
| AK-30 `database` done ohne Zeile → `pending` | ✅ | `test_level4` |
| AK-31 verwaiste Zeilen samt Buchungen | ✅ | `test_level4` |
| AK-32 konsistenter Bestand | ✅ | `test_consistent_inventory`, Register `test_repo_check_consistent` |
| AK-33 Sicherung 5 % | ✅ | `test_mass_repair_guard` (100 Quellen, 6 fehlende Markdowns); manuell gegriffen (3 Reparaturen bei 13 Quellen) |
| AK-34 Ereignis je Reparatur | ✅ | `test_level1_register_and_missing`, `test_level2_and_events`, `test_level4`, `test_rehash_changed_content` |
| AK-35 nie gleichzeitig mit dem Nachtlauf | ✅ | `test_waits_for_nightly_run`, Erkennung `test_lease_blocks_nightly_and_vice_versa` |
| AK-36 rollierendes Neu-Hashen | ✅ | `test_nightly_rolling_hash`, Erkennung `test_rolling_rehash_thirds` |
| AK-37 Fortsetzen nach Unterbrechung | ✅ | Erkennung `test_rehash_continues_after_interruption` |
| AK-38 auf Abruf | ✅ | `test_on_demand_and_second_rejected`, `test_rehash_changed_content` (vollständiges Neu-Hashen), `test_http_flow` |
| AK-39 Ergebnisse ≥ 30 Tage, Log | ✅ | `test_results_kept_and_logged` |
| AK-40 Register weg → `wartet` | ✅ | `test_waits_while_register_unavailable`; manuell: Register-Container gestoppt → `wartet` mit Grund, Health `warning`; gestartet → `läuft` |
| AK-41 Abgleich bricht ab, repariert nichts | ✅ | `test_register_unavailable_aborts` |
| AK-42 Ordner leer/nicht lesbar | ✅ | `test_skipped_folder_named`, Erkennung `test_skipped_and_disabled_folders` |
| AK-43 Datei nicht lesbar beim Neu-Hashen | ✅ | `test_unreadable_on_rehash`, Erkennung `test_unreadable_file_reported_and_retried` |
| AK-44 keine nginx-Route | ✅ | statisch: kein Eintrag in `docker/compose/infra/nginx/`, kein `ports:` in `compose.yml`; Container-Test ruft nur intern auf |
| AK-45 Altsystem unberührt | ✅ | statisch: kein Redis/Weaviate/MQTT im neuen Dienst, keine n8n-Änderung; Originale nur lesend (`open(…, "rb")`, Mount `:ro` im manuellen Test) |
| AK-46 Schema-Skript | ✅ | `init-schema.sql` auf frischer DB fehlerfrei; Migration zweimal auf dem `dev`-Stand fehlerfrei |
| AK-47–49 | ⏳ | Live-Tests nach Deploy (Mensch) |

## Edge Cases
- ✅ EC-1 Quelle wird gelöscht → ausgenommen: `test_deleted_during_run_and_empty_run`
- ✅ EC-2 Hand-Korrektur während des Laufs → Kennzeichen entfällt, normaler Vorrang: Register `test_normal_reset_clears_flag`; `manual` geschützt (`test_manual_value_survives`)
- ✅ EC-3 zusätzlich durch Normalbetrieb fällig → einmal verarbeitet: gleicher Stufenzustand, Zählung je Quelle
- ✅ EC-4 Lauf mit 0 Quellen: `test_deleted_during_run_and_empty_run`
- ✅ EC-5 `failed` mit Backoff → Lauf bleibt `läuft`: `test_progress_fields_and_errors`
- ✅ EC-6 Abgleich während Lauf: `test_level3_pending_too_long`
- ✅ EC-7 Markdown fehlt während Lauf → Reparatur über das Register, unabhängig vom Lauf (statisch, gleiche Reparatur wie AK-26)
- ✅ EC-8 deaktivierter Ordner: Erkennung `test_skipped_and_disabled_folders`
- ✅ EC-9 neuer Hash gehört anderer Quelle: Erkennung `test_rehash_hash_of_other_source`
- ✅ EC-10 sehr große Datei: Erkennung `test_large_file_hashed_whole`
- ✅ EC-11 Redis-Neustart: Lauf- und Freigabezustand nur in PostgreSQL; Neuaufbau-Arbeit nie in der Redis-Queue (`test_redis_claim_fills_with_rebuild_work`)
- ✅ EC-12 zweiter Abgleich → 409: `test_on_demand_and_second_rejected`, `test_http_flow`
- ✅ EC-13 Stufen-Dienst gestoppt: `test_stage_service_down` (Durchsatz 0, Restzeit unbekannt)

## Bugs
Während der QA gefunden und behoben:
- (Low) Startversuch mit ungültiger Startstufe lieferte während eines aktiven Laufs 409 statt 422 → Eingabe wird jetzt zuerst geprüft.
- (Low) Das Log enthielt alle 2 s eine httpx-Zeile für den Register-Health-Check → httpx-Logger auf WARNING.

Offen: keine.

## Sicherheit
- Schnittstelle ohne Authentifizierung wie PROJ-115/116/119: nur im Docker-Netz `backend`, kein veröffentlichter Port, keine nginx-Route. Kein Nutzerbezug.
- Alle Eingaben über Pydantic geprüft (Stufenname per Muster, Art aus fester Liste, `started_by` 1–200 Zeichen, Seitengrößen begrenzt); alle SQL-Abfragen parametrisiert.
- Keine Secrets in Code, Logs oder Antworten; `.env.example` nur mit Platzhaltern.
- Register-Erweiterungen: Freigabe setzt nur Stufen nicht gelöschter, nicht gesperrter Quellen; Reparaturen schreiben ausschließlich über die bestehende Git-Logik (kein freier Pfad aus der Anfrage, `found_at` wird nur gelesen, wenn er im Repo existiert und dieselbe `id` trägt – sonst greift die Prüfung von PROJ-115).

## Nicht live geprüft
- Echter Bestand (rund 55.000 Quellen, NFS-NAS), echte Stufen-Dienste mit LLM, Chat-Last → Attrappen: Temp-Ordner als NAS, temporäres Git-Repo, simulierte Stufen-Worker, Container-Verbund aus Register, Erkennung und neuem Dienst mit Wegwerf-Postgres/Redis.
- Live prüfen nach dem Deploy (AK-47–49):
  1. Nächsten Morgen: `docker run --rm --network backend curlimages/curl -s http://alice-etl-rebuild:8017/reconcile/results?limit=1` → `state: complete`, Lücken je Ebene erklärbar (Ebene 3 zeigt zunächst den Rückstau der Klassifizierung als „länger als 24 h pending“).
  2. Neuaufbau ab `database`: `curl -s -XPOST http://alice-etl-rebuild:8017/rebuilds -H 'content-type: application/json' -d '{"start_stage":"database","kind":"document","started_by":"admin"}'`, Fortschritt mit `GET /rebuilds/current`; währenddessen eine neue Datei ablegen, nach ≤ 15 min in `alice.doc_documents`.
  3. Neuaufbau ab `classify` mit kleiner Stichprobe (z. B. Art `document` und danach Abbruch): Chat bedienbar, `pause`/`resume`/`cancel` wie beschrieben.

## Automatisierte Tests
- `scripts/test-services.sh alice-source-registry alice-file-detection alice-etl-rebuild alice-document-database alice-document-classify alice-text-extraction`: 111 / 76 / 41 / 44 / 93 / 73 bestanden
- `scripts/test-containers.sh alice-source-registry alice-file-detection alice-etl-rebuild`: alle gesund, Rauchtests bestanden
- Schema: frische DB und Migration (2×) auf dem `dev`-Stand fehlerfrei
