# QA-Bericht: PROJ-125 Bilder in der Quelle der Wahrheit (#21)

**Spec:** [spec.md](spec.md) · **Design:** [design.md](design.md)
**Getestet am:** 2026-11-27 · **Branch:** `factory/21`

## Ergebnis
**Produktionsreif:** Ja
- Akzeptanzkriterien: 40 von 40 testbaren bestanden. AK-41–43 sind Live-Tests nach dem Deploy.
- Bugs: Critical 0 · High 0 · Medium 0 · Low 1 (behoben)

Nachweise:
- automatisierte Tests (`alice-image-processing/tests/`): EXIF-Leser, Vision-Client und Ort mit Attrappen; End-to-End mit dem echten Register-Code, Wegwerf-Postgres inkl. Migration und temporärem Git-Repo
- manueller Test mit echten Containern (eigenes Compose-Projekt): Register, Bilddienst, test-postgres, test-redis, test-weaviate mit der Collection `Image` aus `schemas/image.json` sowie ein Fake-Server für Gateway und Geoapify

## Akzeptanzkriterien
| AK | Ergebnis | Nachweis |
|---|---|---|
| AK-1 neues JPEG vollständig | ✅ | `test_e2e::test_new_jpeg_complete` (alle Felder, Register erledigt, Commits „Alice ETL“); manuell im Container geprüft |
| AK-2 alle Formate | ✅ | `test_imaging::test_exif_in_every_format`, `test_e2e::test_all_formats` (jpg/jpeg/png/webp/heic/tif/tiff); Container-Selbsttest (HEIC/TIFF/WebP im Image) |
| AK-3 Mail-Anhang | ✅ | `test_e2e::test_mail_attachment` |
| AK-4 andere Arten unberührt | ✅ | `test_e2e::test_other_kinds_untouched`; Register-Test `test_claim_never_hands_out_deleted_or_other_kinds`; manuell (Dokument blieb `pending`) |
| AK-5 classify/database skipped | ✅ | `test_registry/test_images_interface::test_image_stages`, Migration in init-schema (Test-DB) |
| AK-6 gelöschte nicht vergeben | ✅ | `test_e2e::test_deleted_image_not_handed_out` |
| AK-7 ohne EXIF | ✅ | `test_e2e::test_without_exif`, `test_imaging::test_no_exif_is_no_error`; manuell (PNG, Ort `skipped`) |
| AK-8 S/W-Koordinaten | ✅ | `test_imaging::test_gps_south_west_signed`; manuell (−33.8568/−151.2153) |
| AK-9 EXIF aus dem Original | ✅ | `test_e2e::test_exif_from_original_not_from_weaviate`; manuell (Altobjekt mit Nikon → Canon im Frontmatter) |
| AK-10 Übernahme ohne Geoapify | ✅ | `test_e2e::test_takeover_without_geoapify`, `test_weaviate_live` gegen echtes Weaviate 1.33; manuell: 0 Geoapify-Aufrufe |
| AK-11 Geoapify deutsch | ✅ | `test_geo::test_geoapify_german`; manuell (`lang=de`) |
| AK-12 Weaviate weg | ✅ | `test_e2e::test_weaviate_down_waits_then_takes_over`; manuell: fehlende Collection → Ort wartete 5 min ohne Fehlversuch, danach übernommen |
| AK-13 Übernahme aus | ✅ | `test_e2e::test_takeover_switched_off` |
| AK-14 Tageslimit 3 von 5 | ✅ | `test_e2e::test_daily_limit_three_of_five` (inkl. Folgetag) |
| AK-15 ≤ 5/s | ✅ | `test_geo::test_rate_limit_five_per_second`, `…_under_concurrency` |
| AK-16 Geoapify-Fehler | ✅ | `test_e2e::test_geoapify_error_leaves_description_alone` |
| AK-17 Ort trotz gescheiterter Beschreibung | ✅ | `test_e2e::test_place_written_although_description_fails` |
| AK-18 ein Aufruf, Priorität, kein Thinking, Prompt | ✅ | `test_vision::test_one_call_with_background_key_and_no_thinking`; manuell: Schlüssel und `enable_thinking: false` am Fake |
| AK-19 Ort als Hinweis | ✅ | `test_vision::test_place_as_hint`, `test_e2e::test_new_jpeg_complete` |
| AK-20 Text im Bild | ✅ | `test_document::test_content_with_and_without_text`, `test_e2e::test_text_in_image_section`; manuell |
| AK-21 description_model | ✅ | `test_e2e::test_new_jpeg_complete` (`qwen3.8-27b` aus der Gateway-Antwort) |
| AK-22 bis 2:1 ein Aufruf ≤ 1024 px | ✅ | `test_imaging::test_one_image_up_to_two_to_one` |
| AK-23 Panorama 8 + 1 | ✅ | `test_imaging::test_panorama_in_eight_tiles`, `test_vision::test_panorama_tiles_and_merge`, `test_e2e::test_panorama_end_to_end`; manuell (22704×1760: 9 Aufrufe) |
| AK-24 Teilbild scheitert | ✅ | `test_vision::test_failed_tile_fails_everything`, `test_e2e::test_panorama_tile_fails_nothing_written` |
| AK-25 > 250 MP / kaputt | ✅ | `test_imaging::test_over_pixel_limit_without_decoding`, `test_broken_file`, `test_e2e::test_too_large_and_broken_fail_permanently` (kein Vision-Aufruf) |
| AK-26 leer/Timeout/Gateway weg | ✅ | `test_e2e::test_vision_errors_retry_by_backoff` (Markdown unverändert) |
| AK-27 Titelformat | ✅ | `test_document::test_title_format`, `test_e2e::test_new_jpeg_complete` (Datei umbenannt) |
| AK-28 ohne taken/Ort | ✅ | `test_document::test_title_from_modified_without_place`, `test_e2e::test_without_exif` |
| AK-29 Ort später | ✅ | `test_e2e::test_place_after_description_completes_title`; manuell (Titel und Dateiname um „Rimini (alt)“ ergänzt) |
| AK-30 title manual | ✅ | `test_e2e::test_manual_title_and_content_protected` |
| AK-31 Bestand gesperrt | ✅ | `test_e2e::test_backlog_locked_only_new_described_place_for_both`; manuell: Bestand blieb offen, Ort lief |
| AK-32 neu vor Bestand | ✅ | `test_e2e::test_new_before_backlog_when_released`, `test_worker::test_claim_order_and_lock` |
| AK-33 Einzelbild anstoßen | ✅ | `test_e2e::test_trigger_one_backlog_image`; manuell `POST /describe/<id>` (200, 404, 400) |
| AK-34 Parallelität 1 | ✅ | `test_e2e::test_concurrency_one` (höchstens ein Vision-Aufruf gleichzeitig) |
| AK-35 Inhalt manual | ✅ | `test_e2e::test_manual_title_and_content_protected` |
| AK-36 in-place geändert | ✅ | `test_e2e::test_changed_original_runs_again` (auch `skipped`-Ort läuft neu), Register-Test `test_done_skipped_and_reset_on_new_original` |
| AK-37 Register weg | ✅ | `test_worker::test_register_unreachable_pauses_and_reports`, `test_register_back_continues`; Container-Rauchtest; manuell Register gestoppt/gestartet |
| AK-38 NAS weg | ✅ | `test_e2e::test_nas_down_releases_without_attempt` |
| AK-39 keine nginx-Route | ✅ | statisch: keine Route in `docker/compose/infra/nginx/`, Port nur im Docker-Netz |
| AK-40 altes System unberührt | ✅ | statisch: `dms-extractor-image` und Workflows unverändert (git diff), kein Redis/MQTT im Dienst; Weaviate nur `POST /v1/graphql` (Lesezugriff, `test_geo`) |
| AK-41 Stichprobe | ⏳ | Live-Test nach Deploy |
| AK-42 Chat-Latenz, 15 min | ⏳ | Live-Test nach Deploy |
| AK-43 Geoapify-Verbrauch erster Tag | ⏳ | Live-Test nach Deploy (`GET /status` zeigt `calls_today`) |

## Edge Cases
- ✅ EC-1 HEIC-EXIF (Unit-Tests + Container)
- ✅ EC-2 Aufnahmezeit wird übernommen wie gelesen
- ✅ EC-3 GPS 0/0 → kein GPS
- ✅ EC-4 Geoapify ohne Stadt → teilweise leer, erledigt
- ✅ EC-5 nur `country` gilt als gefüllt
- ✅ EC-6 erstes gefülltes Altobjekt
- ✅ EC-7 ohne Titel / kein JSON → Fehlversuch
- ✅ EC-8 `---`/Backticks in der Abschrift: Frontmatter bleibt gültig
- ✅ EC-9 mehrseitiges TIFF → erste Seite
- ✅ EC-10 gedrehtes Bild → richtig ausgerichtet, angezeigte Maße
- ✅ EC-11 gleicher Hash an mehreren Fundorten: eine Quelle (Register PROJ-115)
- ✅ EC-12 Modellwechsel: Modellname je Antwort
- ✅ EC-13 Handkorrektur zuerst: Register mit Claim-Token
- ✅ EC-14 Neustart: Zustand nur im Register/Postgres. Manuell zweimal neu gestartet, Bestandsgrenze und Arbeit blieben erhalten.
- ✅ EC-15 Mitternacht: Wartezeit bis 00:00 Europe/Berlin, am Folgetag weiter (`test_daily_limit_three_of_five`)

## Bugs
- **B-1 (Low, behoben):** Die Bestandsgrenze wurde beim Start zweimal geladen und geloggt (beide Schleifen gleichzeitig). Jetzt mit Lock nur einmal.

## Sicherheit
- Die Schnittstelle (`/health`, `/status`, `POST /describe/{id}`) ist ohne Token und nur im Docker-Netz erreichbar, wie bei den anderen ETL-Diensten. Es gibt keine nginx-Route.
- `POST /describe` prüft die ID per Regex. Es nimmt nur Bilder an (keine anderen Arten, keine gelöschten Quellen) und ändert nichts außer der Wiederholung der Beschreibung.
- Weaviate-Abfrage: Der Hash wird nur als 64-stelliges Hex eingesetzt. Kein GraphQL-Injection möglich.
- Der Geoapify-Schlüssel steht nur in der Anfrage. httpx-Logs stehen auf WARNING, Fehlermeldungen nennen nur den Statuscode.
- Text aus dem Bild landet nur im Inhaltsteil (Code-Block) und wird nie als Anweisung ausgeführt.
- Keine Zugangsdaten im Repo (`factory-secret-scan` grün). Eine zwischenzeitlich angelegte `tests/container.env` mit Testwerten ist aus der Branch-Historie entfernt; der Container startet mit den Platzhaltern aus `.env.example`.

## Nicht live geprüft
- **Echtes Vision-Modell:** Qualität und Länge der Beschreibung, keine erfundenen Ortsnamen, Abschrift. Geprüft mit Fake-Gateway. Live: AK-41 (Stichprobe über `POST /describe/<id>`).
- **Echtes Geoapify:** Feldnamen der Antwort wie im alten Prozess (`country`, `country_code`, `city`, `suburb`/`district`/`quarter`). Live: Ort eines Bildes ohne Altobjekt ansehen.
- **Produktiv-Weaviate:** Abfrage gegen test-weaviate mit dem echten Schema geprüft. Live: AK-43.
- **NAS, Mail-Archiv, GPU-Last, Chat-Latenz:** AK-42.

## Automatisierte Tests
- `scripts/test-services.sh`:
  - alice-image-processing: 91 bestanden, 1 übersprungen (Live-Weaviate-Test; separat gegen test-weaviate bestanden)
  - alice-source-registry: 120 bestanden
  - alice-etl-status: 39 bestanden
  - alice-etl-rebuild: 49 bestanden
  - alice-file-detection: 78 bestanden
  - alice-text-extraction: 73 bestanden
  - alice-document-classify: 98 bestanden
  - alice-document-database: 44 bestanden
  - alice-mail-import: 92 bestanden
- `scripts/test-containers.sh alice-image-processing alice-source-registry`: bestanden (Healthcheck, Rauchtest, Selbsttest mit HEIC/TIFF/WebP und Panorama im Image)
