# QA-Bericht: PROJ-122 ETL-Status-Ansicht (Admin, WebApp) (#14)

**Spec:** [spec.md](spec.md) · **Design:** [design.md](design.md)
**Getestet am:** 2026-11-25 · **Commit:** `1983333`

## Ergebnis
**Produktionsreif:** Ja
- Akzeptanzkriterien: 47 von 47 vor Deploy prüfbaren bestanden (AK-48–50 sind Live-Tests nach Deploy)
- Bugs: Critical 0 · High 0 · Medium 0 · Low 0 (zwei kleine Textfehler während des Tests behoben, siehe unten)

## Testaufbau
- **Dienst:** `scripts/test-services.sh alice-etl-status` (39 Tests: Zugriff, Ansichten, Retry über das echte Register in-process, Neuaufbau/Abgleich gegen eine PROJ-120-Attrappe mit festen Daten, Ampel, Last mit 60.000 Quellen) und `scripts/test-containers.sh alice-etl-status` (Image gebaut, Healthcheck, Rauchtest mit/ohne Token, Rolle `haushalt`).
- **Browser:** gebauter statischer Export, Playwright/Chromium. Echte Dienste im Job: `alice-etl-status` und `alice-source-registry` (Wegwerf-Postgres, temporäres Git-Repo), PROJ-120 als Attrappe mit einstellbaren Daten, `/api/auth/validate` und `/api/auth/profile` als Attrappe. 82 Prüfungen, alle bestanden.
- Testdaten: Dokumente mit `failed_permanent` in `classify`, `failed` in `extract`, eine gesperrte und eine gelöschte Quelle, Bild/Audio, Titel mit HTML, lange Fehlermeldung (Stacktrace), 120 E-Mails mit `pending`.

## Akzeptanzkriterien
| AK | Ergebnis | Nachweis |
|---|---|---|
| AK-1 Kachel → Seite | ✅ | Browser: Klick auf Kachel öffnet `/etl` |
| AK-2 UserCard „ETL-Status“ | ✅ | Browser: Menüeintrag öffnet `/etl` |
| AK-3 haushalt/guest weggeleitet | ✅ | Browser: beide Rollen landen im Chat, keine Anfrage an `/api/etl/`, kein Menüeintrag, Kachel nur im Admin-Dashboard |
| AK-4 401/403, nichts geändert | ✅ | `test_access.py` (alle Lese- und Aktionsrouten ohne/ungültiges/abgelaufenes Token 401, haushalt/guest 403, Register und Attrappe unverändert) + Container-Rauchtest |
| AK-5 Matrix = Register ohne Gelöschte | ✅ | `test_views.py::test_matrix_counts_kind_and_deleted` + Browser |
| AK-6 Art-Filter, Gelöschte einblenden | ✅ | wie AK-5 |
| AK-7 neue Stufe erscheint | ✅ | `test_new_stage_appears_in_position` |
| AK-8 Liste einer Zelle | ✅ | `test_list_of_a_cell` + Browser (3 Zeilen, alle Spalten) |
| AK-9 120 Quellen seitenweise | ✅ | `test_list_paging_120` + Browser (alle 121 der Zelle über die Seiten) |
| AK-10 Suche Titel/ID | ✅ | `test_search_title_and_id` + Browser |
| AK-11 Fehlerbereich | ✅ | `test_errors_area` + Browser (Sortierung, Filter) |
| AK-12 Quellen-Detail | ✅ | `test_detail` + Browser (Fundorte vorhanden/verschwunden, Ereignisse neueste zuerst, Pfad) |
| AK-13 Retry failed_permanent | ✅ | `test_retry.py::test_single_failed_permanent` (echtes Register) + Browser (DB: `pending,0`, Ereignis „… von anna-admin“) |
| AK-14 Retry failed | ✅ | `test_single_failed` |
| AK-15 kein Retry für done/pending/running/skipped/gesperrt/gelöscht | ✅ | `test_not_offered_states_rejected`, `test_detail_locked_and_deleted_not_retryable` + Browser (Ursache + Hinweis zur Hand-Reparatur) |
| AK-16 Sammel-Retry 30 von 40 | ✅ | `test_bulk_30_of_40` + Browser (Dialog nennt Anzahl) |
| AK-17 Abbruch ändert nichts | ✅ | Browser + `dry_run` ändert nichts (Test) |
| AK-18 Grenze 1.000 | ✅ | `test_bulk_limit` (1.001 Quellen, auch direkter Aufruf → 409 `limit_exceeded`); Oberfläche zeigt Hinweis + „Zum Neuaufbau“ |
| AK-19 zweiter Tab | ✅ | `test_second_tab` (409 mit aktuellem Zustand, kein zweites Ereignis) |
| AK-20 Start-Dialog + Vorschau | ✅ | `test_rebuild.py::test_preview` + Browser (`detect` nicht wählbar, Anzahl, Stufen ab `classify`) |
| AK-21 Start mit Admin-Namen | ✅ | `test_start_uses_admin_name` (Name aus der DB, nie aus dem Request) + Browser |
| AK-22 Start deaktiviert bei aktivem Lauf | ✅ | Browser (Button deaktiviert, Grund „Lauf 3 (läuft) ist aktiv …“) |
| AK-23 Fortschritt wie geliefert | ✅ | Browser mit festen Daten der Attrappe |
| AK-24 Restzeit „unbekannt“ | ✅ | Browser (Durchsatz 0) |
| AK-25 Pausieren/Fortsetzen | ✅ | `test_control_and_lists` + Browser |
| AK-26 Abbrechen mit Rückfrage | ✅ | Browser (Abbruch der Rückfrage lässt Lauf laufen; Bestätigung bricht ab) |
| AK-27 Fehlerliste des Laufs | ✅ | Browser (2 Fehler, Sprung ins Detail per ID) |
| AK-28 Verlauf | ✅ | Browser (abgeschlossen/abgebrochen, Link „Abgleich 5“) |
| AK-29 `wartet` mit Grund | ✅ | Browser |
| AK-30 Zusammenfassung + Hervorhebung | ✅ | `test_light.py::test_attention` + Browser (2 h ohne, 39 h und `unvollständig` mit Hervorhebung) |
| AK-31 Ergebnisliste seitenweise | ✅ | Browser + Durchreichen mit `limit/offset` (PROJ-120 hält ≥ 30 Tage) |
| AK-32 Ergebnis-Detail | ✅ | Browser (je Ebene repariert/nur gemeldet, Sicherung, übersprungener Ordner, Hash-Zyklus 40 %, Lücke → Quellen-Detail) |
| AK-33 Abgleich jetzt / Neu-Hashen mit Rückfrage | ✅ | `test_control_and_lists` + Browser |
| AK-34 Buttons bei laufendem Abgleich deaktiviert | ✅ | Browser (Grund „Abgleich 99 läuft gerade“) |
| AK-35 keine Aktion auf Lücken | ✅ | Browser (im Detail nur Quellen-Links und Schließen) |
| AK-36 Kachel-Zahlen | ✅ | `test_counts_for_tile` (4 + 1 = 5, 7 failed) + Browser („läuft 63 %“, Abgleich mit Status/Zeit) |
| AK-37 Ampel | ✅ | `test_light.py` (grün/gelb/rot inkl. nur gemeldete Lücken) + Browser |
| AK-38 alte Kacheln unverändert | ✅ | Durchsicht `tileRegistry.tsx` (nur ein Eintrag ergänzt) + Browser |
| AK-39 Refresh 5 s / aus | ✅ | Browser (Änderung in der DB nach ≤ 6,5 s sichtbar; „aus“: 7 s keine Anfrage) |
| AK-40 Wahl gemerkt | ✅ | Browser (60 s nach Neuladen) |
| AK-41 Dienstausfall | ✅ | Browser (Banner, „veraltet“, letzte Daten bleiben, Aktionen deaktiviert, kein Toast je Refresh, Banner verschwindet nach Rückkehr) |
| AK-42 abgelehnte Aktion → Toast + Neuladen | ✅ | `test_rejection_passed_on` + Browser (Grund aus PROJ-120 im Toast) |
| AK-43 Leerzustände | ✅ | Browser (leeres Register, keine Fehler, kein Lauf, kein Abgleich) |
| AK-44 Deutsch/Englisch | ✅ | Browser (Profilsprache `en` → Seite und Kachel englisch); alle Texte in `de.ts`/`en.ts` |
| AK-45 375 px | ✅ | Browser (`scrollWidth` ≤ 375 auf Seite und mit offener Liste; Matrix/Tabellen scrollen im Container) |
| AK-46 < 1 s bei 60.000 Quellen | ✅ | `test_load.py`: Zustand 0,21 s, mit Filter 0,17 s, Liste 0,07–0,12 s, Fehler 0,11–0,28 s; Dienst hat keinen Repo-/NAS-Mount |
| AK-47 Altsystem unberührt | ✅ | Durchsicht: keine n8n-, Redis- oder Weaviate-Anbindung im neuen Dienst |
| AK-48–50 | ⏳ | Live-Test nach Deploy (Mensch) |

## Edge Cases
- ✅ EC-1: nächster Refresh zeigt neuen Stand; nicht mehr gültige Aktion → 409 mit Grund (Toast)
- ✅ EC-2: Auswahl wird bei der Ausführung neu bestimmt, Antwort nennt die tatsächliche Zahl (`test_bulk_selection_changed_meanwhile`)
- ✅ EC-3: Detail zeigt gelöscht/gesperrt, kein Retry-Button; Server lehnt ab
- ✅ EC-4: Liste kürzt auf 300 Zeichen mit „…“, Detail zeigt vollständig und umbrechend
- ✅ EC-5: Titel mit HTML wird als Text angezeigt; leerer Titel → `id`
- ✅ EC-6: PROJ-120 entscheidet, Ablehnung kommt mit Grund
- ✅ EC-7: 401 → Anmeldung über den zentralen `fetchWithAuth` (kein Fehler-Loop)
- ✅ EC-8: Rolle wird je Anfrage aus der DB gelesen (`test_role_from_database_not_token`); 403 → Weiterleitung
- ✅ EC-9: PROJ-120 weg → nur Neuaufbau/Abgleich zeigen das Banner, Matrix/Listen/Retry gehen weiter (`test_rebuild_service_down` + Browser)
- ✅ EC-10: Art ohne Quellen → Nullen bzw. Leerzustand
- ✅ EC-11: statisch geprüft: ein sofort abgeschlossener Lauf erscheint im Verlauf mit seinen Endzahlen („0 von 0 durch“); nicht eigens im Browser gestellt

## Bugs
Keine offenen. Während des Tests behoben (Low): englische Zähler „1 errors“/„1 sources“ (jetzt „Errors: 1“), Satzbau „Lauf 3 ist läuft“.

## Sicherheit
- Jede Route außer `/health` prüft JWT (RS256) und Rolle `admin` aus `alice.users` (aktiv). `started_by` und der Name im Ereignis kommen aus der DB, nie aus dem Request.
- Alle Eingaben über Pydantic-Muster (Stufe, Art, Zustand, ID, Aktion), SQL nur parametrisiert; Suchbegriff mit maskierten `%`/`_`.
- Interne Schnittstellen von Register und PROJ-120 bleiben ohne nginx-Route; die neue Route hat ein eigenes Ratenlimit.
- React rendert alle Texte escaped; kein `dangerouslySetInnerHTML`.
- Keine Secrets im Code, Testschlüssel werden je Lauf erzeugt.

## Nicht live geprüft
- Echter Bestand, echter PROJ-120-Dienst mit laufendem Neuaufbau/Abgleich, nginx-Route → Live-Tests AK-48–50 nach Deploy. Prüfen: `/etl` öffnen, Zahlen gegen `SELECT stage, state, count(*) FROM alice.source_stages GROUP BY 1,2` vergleichen; eine Testquelle mit `failed_permanent` erneut versuchen; kleinen Neuaufbau starten/pausieren/fortsetzen.

## Automatisierte Tests
- `scripts/test-services.sh alice-etl-status`: 39 bestanden
- `scripts/test-containers.sh alice-etl-status`: bestanden
- Frontend: `npx tsc --noEmit`, `npm run build` bestanden
- Browser (Playwright, außerhalb des Repos): 82/82
