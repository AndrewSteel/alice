# QA-Bericht: PROJ-115 Quelle-der-Wahrheit-Repo + Quellen-Register (#3)

**Datum:** 2026-11-21 · **Ergebnis:** bestanden (keine kritischen/hohen Fehler)

## Testumgebung
- `scripts/test-services.sh alice-source-registry`: 66 pytest-Tests, davon Integrationstests gegen Wegwerf-PostgreSQL (mit `sql/init-schema.sql`) und Wegwerf-Redis, Repo als temporäres Git-Repo im Job-Ordner.
- `scripts/test-containers.sh alice-source-registry`: Image gebaut, Healthcheck `healthy`, Rauchtest (leeres `/data/sot` → Repo angelegt, Quelle registriert, Commit „Alice ETL“, Stufe übernommen).
- Migration gegen das Schema von `dev` zweimal hintereinander angewendet: beide Läufe fehlerfrei.
- Nicht live geprüft: echter NAS-Ordner (CIFS) und echter Ausfall der Freigabe — nachgebildet durch Umbenennen des Temp-Ordners. AK-34 prüft der Mensch nach dem Deploy.

## Akzeptanzkriterien
| AK | Ergebnis | Nachweis (Test) |
|---|---|---|
| AK-1 | ✅ | `test_init_empty_folder`, `test_startup_initializes_repo` |
| AK-2 | ✅ | `test_existing_repo_is_reused_unchanged` |
| AK-3 | ✅ | `test_foreign_folder_is_rejected_and_untouched`, `test_foreign_folder_aborts_start` |
| AK-4 | ✅ | `test_register_writes_markdown`, `test_rel_path_by_kind_year_month` |
| AK-5 | ✅ | `test_title_change_renames_file` (`git log --follow`) |
| AK-6 | ✅ | `test_location_change_only_touches_locations` |
| AK-7 | ✅ | `test_register_writes_markdown`, `test_title_change_renames_file` |
| AK-8 | ✅ | `test_batch_commits_max_500` (1.200 → 500/500/200), `test_batch_closes_after_time_limit` |
| AK-9 | ✅ | `test_register_writes_markdown`, `test_render_parse_roundtrip_has_heading_and_no_state` |
| AK-10 | ✅ | `test_audio_video_skipped[audio/video]` |
| AK-11 | ✅ | `test_register_writes_markdown` |
| AK-12 | ✅ | `test_same_hash_second_location` |
| AK-13 | ✅ | `test_attachment_parents` |
| AK-14 | ✅ | `test_deleted_only_without_locations` |
| AK-15 | ✅ | `test_exclusive_claim`, `test_exclusive_claim_without_redis` |
| AK-16 | ✅ | `test_fail_backoff_and_permanent` (1 min/5 min/30 min/2 h) |
| AK-17 | ✅ | `test_fail_backoff_and_permanent` (5. Fehler → `failed_permanent`) |
| AK-18 | ✅ | `test_fail_backoff_and_permanent`, `test_http_flow` |
| AK-19 | ✅ | `test_stale_running_back_to_pending` |
| AK-20 | ✅ | `test_content_change_resets_dependents`, `test_location_change_does_not_reset` |
| AK-21 | ✅ | `test_new_stage_for_existing_sources` |
| AK-22 | ✅ | `test_queue_rebuilt_after_redis_flush`, `test_queue_with_real_redis` |
| AK-23 | ✅ | `test_uncommitted_hand_edit` (Prüfintervall Standard 60 s ≤ 5 min) |
| AK-24 | ✅ | `test_human_commit_is_hand_correction` |
| AK-25 | ✅ | `test_manual_fields_protected`, `test_manual_content_protected` |
| AK-26 | ✅ | `test_manual_fields_protected` |
| AK-27 | ✅ | `test_write_commits_pending_hand_edit_first` |
| AK-28 | ✅ | `test_invalid_hand_edit_locks_until_repaired` (YAML, Pflichtfeld, `id`) |
| AK-29 | ✅ | `test_invalid_hand_edit_locks_until_repaired`, `test_invalid_then_reverted_unlocks` |
| AK-30 | ✅ | `test_repo_unavailable_pauses`, `test_unhealthy_without_repo` (nachgebildet) |
| AK-31 | ✅ | `test_repo_unavailable_pauses` (Hand-Korrektur während Ausfall erkannt; nachgebildet) |
| AK-32 | ✅ | `test_orphaned_lock_removed_after_wait_time`, `test_young_lock_means_busy_and_is_kept`, `test_orphaned_lock_on_startup` |
| AK-33 | ✅ | `test_no_nginx_route` (keine Route in `docker/compose/infra/nginx/`) |
| AK-34 | – | Live-Test nach Deploy durch den Menschen |

## Edge Cases
EC-1 `test_same_slug_different_ids_gives_unique_names` ✅ · EC-2 `test_slug_umlauts_special_chars_and_length` ✅ · EC-3 `test_manual_fields_protected` ✅ · EC-4 `test_moved_file_is_put_back` ✅ · EC-5 `test_deleted_file_restored` ✅ · EC-6 `test_stray_markdown_left_alone` ✅ · EC-7 `test_restart_commits_leftover_pipeline_files` ✅ · EC-8 `test_update_original_hash` ✅ · EC-9 `test_parallel_writes_serialized` ✅ · EC-10 `test_old_schema_file_extended` ✅

## Sicherheit
- Keine nginx-Route, keine veröffentlichten Ports; Schnittstelle nur im Docker-Netz (bewusst ohne Auth, kein Nutzerbezug).
- Dateipfade im Repo entstehen nur aus Art, Datum, zufälliger `id` und Slug (`a-z0-9-`): kein Path-Traversal über Titel. Feldnamen von Stufen werden geprüft, Register-Felder sind nicht beschreibbar.
- YAML nur mit `safe_load`, SQL nur parametrisiert, Git ohne Hooks (`core.hooksPath=/dev/null`).
- Keine Zugangsdaten im Repo; `.env.example` nur mit Platzhaltern.

## Gefundene und behobene Fehler
- Eine vom Menschen committete Änderung vor dem ersten Prüflauf (noch keine Prüfmarke) wurde nicht erkannt → erster Prüflauf vergleicht jetzt alle versionierten Dateien einmal.
- Titel mit Zeilenumbruch hätten die Überschrift in den Inhaltsteil verschoben → Überschrift wird einzeilig geschrieben.
