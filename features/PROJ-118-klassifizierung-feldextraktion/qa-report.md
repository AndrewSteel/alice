# QA-Bericht: PROJ-118 Klassifizierung + Feldextraktion (#9)

**Spec:** [spec.md](spec.md) · **Design:** [design.md](design.md)
**Getestet am:** 2026-11-23 · **Commit:** `fd90477`

## Ergebnis
**Produktionsreif:** Ja
- Akzeptanzkriterien: 47 von 48 prüfbaren bestanden, AK-37 zweiter Halbsatz entfällt (Entscheidung A im Issue); AK-49/50 sind Live-Tests nach Deploy
- Bugs: Critical 0 · High 0 · Medium 0 · Low 0 (im Feature); ein bestehender Befund außerhalb des Features unter „Sicherheit“

## Akzeptanzkriterien
Dateien relativ zu `docker/compose/automations/`. „E2E“ = echter Register-Code mit Wegwerf-Postgres und temporärem Git-Repo, LLM als Gateway-Attrappe.

| AK | Ergebnis | Nachweis |
|---|---|---|
| AK-1 | ✅ | E2E `alice-document-classify/tests/test_e2e.py::test_invoice_end_to_end`; manuell im Docker-Aufbau (Register + Gateway-Attrappe + Dienst) |
| AK-2 | ✅ | `alice-source-registry/tests/test_classify_interface.py::test_claim_requires_done_stage` (pending/running/failed); E2E `test_only_documents_after_extract`; manuell (Quelle mit `extract` pending blieb `pending`) |
| AK-3 | ✅ | E2E `test_only_documents_after_extract` (Bild unverändert, nicht übernommen); manuell |
| AK-4 | ✅ | E2E `test_invoice_end_to_end` (genau ein Commit „Alice ETL\|classify: <id> <title>“), `test_batch_commit` („rebuild: classify 3 sources“) |
| AK-5 | ✅ | E2E `test_only_documents_after_extract`: Ordner mit `suggested_type = Invoice`, Attrappe zählt den Aufruf, LLM-Typ `Contract` übernommen |
| AK-6 | ✅ | E2E: nach `extract = done` in der nächsten Abfragerunde verarbeitet; Frist `CLASSIFY_POLL_SECONDS` (Standard 10 s); manuell mit 2 s |
| AK-7 | ✅ | `test_classifier.py::test_invoice` (ein Aufruf, Temperatur 0) |
| AK-8 | ✅ | `test_low_confidence_second_try`, `test_low_confidence_tie_takes_second`, `test_first_try_better_stays` |
| AK-9 | ✅ | `test_uncertain_still_extracts` (Typ der besten Schätzung, `uncertain: true`, Felder des Typs) |
| AK-10 | ✅ | `test_classify_prompt_lists_types` |
| AK-11 | ✅ | `test_invoice`, E2E `test_invoice_end_to_end` |
| AK-12 | ✅ | `test_fields_of_type_only` (Contract, SecuritySettlement, Document), `test_normalize.py::test_normalize_fields_exact_set` |
| AK-13 | ✅ | `test_fields_of_type_only` (alle `null`) |
| AK-14 | ✅ | `test_invalid_values_become_null` (`31.13.2026`, `"ca. zwanzig"`, `swap`), `test_normalize.py` |
| AK-15 | ✅ | E2E `test_original_changed_new_prefix_and_type_change` (Invoice → Contract, Feld in `manual` bleibt); Register `test_manual_inner_field_survives_rewrite` |
| AK-16 | ✅ | `test_normalize.py::test_iban_isin`, `test_invalid_values_become_null`; manuell (IBAN mit Leerzeichen → normalisiert) |
| AK-17 | ✅ | E2E `test_invoice_end_to_end`: Titel `2026-10-14 09.32.11 …`, Überschrift, Datei `<id>-2026-10-14-09-32-11-stromrechnung-….md` im selben Ordner, `git log --follow` reicht bis `detect` |
| AK-18 | ✅ | `test_normalize.py::test_title` |
| AK-19 | ✅ | E2E `test_same_title_two_files` |
| AK-20 | ✅ | E2E `test_original_changed_new_prefix_and_type_change` (neues `modified` → neuer Präfix) |
| AK-21 | ✅ | `test_english_source_prompt_and_language_retry` (Deutsch-Vorgabe im Prompt, `language` wird nicht geschrieben) |
| AK-22 | ✅ | `test_english_source_prompt_and_language_retry` |
| AK-23 | ✅ | `test_language_stays_english` |
| AK-24 | ✅ | `test_german_with_terms_no_retry`, `test_language.py` |
| AK-25 | ✅ | `test_long_document_head_only` (108.000 Zeichen, Prompt enthält genau 20.000 vom Anfang) |
| AK-26 | ✅ | `test_bank_statement_sections` (12 Seiten, mehrere Abschnitts-Aufrufe, jede Seite genau einmal, Reihenfolge) |
| AK-27 | ✅ | `test_normalize.py::test_merge_transactions` |
| AK-28 | ✅ | `test_normalize.py::test_balance`, `test_bank_statement_sections` |
| AK-29 | ✅ | `test_bank_statement_mismatch_and_missing_balance` (Differenz 50,00, kein weiterer Aufruf); manuell im Docker-Aufbau |
| AK-30 | ✅ | `test_bank_statement_mismatch_and_missing_balance`, `test_balance` |
| AK-31 | ✅ | `test_bank_statement_bad_section_fails`; E2E `test_bank_statement_section_fails_unchanged` (`failed`, Meldung nennt Seite/Abschnitt, Datei unverändert) |
| AK-32 | ✅ | `test_empty_document_no_llm`, E2E `test_empty_document` |
| AK-33 | ✅ | `test_manual_type` |
| AK-34 | ✅ | E2E `test_hand_type_change`; Register `test_hand_edit_of_type_and_content_resets_classify` |
| AK-35 | ✅ | E2E `test_hand_content_correction` (zweiter Lauf sieht den korrigierten Text) |
| AK-36 | ✅ | Register `test_hand_edit_of_single_fields_keeps_classify` (`manual` = `fields.amount_gross`, `summary`, `title`; classify `done`; database/rag/wiki `pending`) |
| AK-37 | ✅ / entfällt | Inhalt geändert → `pending`: E2E `test_original_changed_…`, Register `test_new_content_from_extract_resets_classify` (Neuextraktion mit gleichem Inhalt lässt classify `done`). Geändertes Original setzt classify laut Entscheidung A immer zurück; der zweite Halbsatz entfällt dafür. |
| AK-38 | ✅ | E2E `test_manual_title_summary_iban` |
| AK-39 | ✅ | E2E `test_invalid_answers_backoff_permanent_and_retry` |
| AK-40 | ✅ | `test_invoice` (nur Gateway-URL, Schlüssel des Hintergrund-Aufrufers); manuell: alle Aufrufe der Gateway-Attrappe mit `Bearer <key>` an `/v1/chat/completions` |
| AK-41 | ✅ | `test_worker.py::test_concurrency_one`, `test_concurrency_configurable` |
| AK-42 | ✅ | `test_gateway_down_releases_and_continues`, E2E `test_gateway_down_no_attempt`; manuell: Gateway gestoppt → Warnung im Log, `attempts` 0, `/health` warning; Gateway gestartet → nach der Pause von selbst `done` |
| AK-43 | ✅ | `test_invalid_json_retry` |
| AK-44 | ✅ | `test_invalid_twice` (kein JSON, Typ außerhalb der Liste, Typ fehlt), E2E `test_invalid_answers_backoff_permanent_and_retry` (5 Fehlversuche → `failed_permanent`) |
| AK-45 | ✅ | `test_worker.py::test_cancel_writes_nothing`; ein Schreibaufruf erst nach allen LLM-Schritten; Rücknahme nach Zeitüberschreitung ist PROJ-115-Verhalten (bestehende Register-Tests) |
| AK-46 | ✅ | E2E `test_invoice_end_to_end` |
| AK-47 | ✅ | statisch: keine nginx-Route (`docker/compose/infra/nginx/` ohne Eintrag), Port 8015 nur im Netz `backend`, kein `ports:` in `compose.yml` |
| AK-48 | ✅ | statisch: keine Redis-/Weaviate-/MQTT-Abhängigkeit (`requirements.txt`), `workflows/` unverändert (`git diff`) |
| AK-49 | ⏳ | Live-Test nach Deploy (echte Dokumente, echtes LLM) |
| AK-50 | ⏳ | Live-Test nach Deploy (Chat/Sprache parallel) |

## Edge Cases
- ✅ EC-1: Antwortformat erlaubt genau einen Typ; Unsicherheit über Konfidenz (`test_uncertain_still_extracts`)
- ✅ EC-2: Saldenprüfung schlägt an (`balance_mismatch`), Buchungen aller Abschnitte
- ✅ EC-3: `test_sections_without_marks`
- ✅ EC-4: leere Buchungsliste, Prüfung nur mit beiden Salden
- ✅ EC-5: `test_amounts` (`1.234,56`, `-12,00`, `S`/`H`, mehrdeutig `1.234` → `null`)
- ✅ EC-6: `test_title` (`modified` ungültig → `captured`)
- ✅ EC-7: Titel mit `/`, `:`, Emoji bleibt im Frontmatter, Slug aus PROJ-115 (`test_title`, Register-Slug-Tests)
- ✅ EC-8: `test_title` (kein doppelter Präfix)
- ✅ EC-9: Register `test_write_with_stale_token_is_discarded` (Hand-Korrektur zuerst committet, Ergebnis verworfen, classify erneut `pending`)
- ✅ EC-10: Ohne `type` in `manual` wird wieder klassifiziert (Logik in `classifier.run`, `test_invoice`)
- ✅ EC-11: Ungültige Antwort → AK-44 (`test_invalid_twice` mit Anweisungstext im Dokument); Dokument steht abgegrenzt als Daten im Prompt
- ✅ EC-12: `test_names_and_numbers_are_not`
- ✅ EC-13: Übernahme mit `requires` läuft über das Register, nicht über Redis
- ✅ EC-14: `test_batch_commit`
- ✅ EC-15: E2E `test_deleted_during_classification` (verworfen, kein Fehlversuch)

## Bugs
- Keine im Feature.

## Sicherheit
- Dienst ohne Endpunkte mit Wirkung (nur `/health`, `/status`), keine nginx-Route; `/status` zeigt wie bei `alice-text-extraction` Quell-IDs und Titel nur im Docker-Netz.
- Prompt-Injection: Dokumenttext ist abgegrenzt und als Daten markiert; jede Antwort wird streng gelesen (Typ aus fester Liste, Werte normalisiert, Ungültiges → `null`). Schlimmster Fall ist eine falsche Klassifizierung, die im Frontmatter sichtbar und korrigierbar ist.
- Gateway-Schlüssel nur aus der Umgebung, wird nicht geloggt; `.env.example` nur mit Platzhaltern.
- Register: neue Parameter validiert (`requires` nach Stufennamen-Muster, `token` als UUID, `resets_on_fields` begrenzt); alle Abfragen parametrisiert.
- **Bestehender Befund außerhalb dieses Features:** In `docker/compose/automations/alice-llm-gateway/clients` sind seit PROJ-111 Schlüssel eingecheckt, die nicht wie Platzhalter aussehen. Nicht geändert (nicht Teil des Features). Empfehlung: prüfen, ob es echte Schlüssel sind; falls ja, rotieren und die Datei aus dem Repo nehmen.

## Nicht live geprüft
- Echtes LLM (Qualität von Typ, Feldern, Buchungen, deutschen Titeln) → Gateway-Attrappe. Staging: `scripts/stage.sh alice-document-classify <PR>`, je eine echte Rechnung, einen mehrseitigen Kontoauszug, einen Vertrag, eine Wertpapierabrechnung und ein englisches Dokument klassifizieren lassen (AK-49), dabei `docker logs alice-llm-gateway` auf `caller: document-classify`, `tier: background` prüfen.
- Last neben Chat/Sprache (AK-50) → nur live.
- Echtes NAS-Repo (Umbenennung auf der Freigabe) → temporäres Git-Repo.

## Automatisierte Tests
- `scripts/test-services.sh alice-document-classify`: 91 bestanden (Unit + E2E)
- `scripts/test-services.sh alice-source-registry`: 92 bestanden (davon 10 neu für PROJ-118)
- `scripts/test-services.sh alice-text-extraction alice-file-detection alice-llm-gateway`: 73 / 66 / 33 bestanden (Regression, laden den Register-Code)
- `scripts/test-containers.sh alice-document-classify alice-source-registry alice-llm-gateway`: bestanden (Rauchtest mit Selbsttest im Image)
- Migration gegen das Schema von `dev` zweimal fehlerfrei angewendet; neues `init-schema.sql` startet fehlerfrei
- Manuell: Docker-Aufbau aus Wegwerf-Postgres/Redis, Register, Gateway-Attrappe und Dienst (Rechnung, Kontoauszug mit Saldenabweichung, Bild, Quelle vor der Extraktion, Gateway-Ausfall)
