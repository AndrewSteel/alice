# QA-Bericht: PROJ-121 Rollenmodell Haushalt (#1)

**Spec:** [spec.md](spec.md) · **Design:** [design.md](design.md)
**Getestet am:** 2026-11-20 · **Commit:** `e7d44e3` (Stand vor diesem Bericht)

## Ergebnis
**Produktionsreif:** Ja (mit Live-Test nach Deploy für LLM-Antworten und n8n-Workflows)
- Akzeptanzkriterien: 15 von 15 prüfbaren bestanden (AK-16 ist Live-Test des Menschen); AK-5/6/7/10/12/14 in den n8n-Teilen statisch bzw. mit Attrappen geprüft
- Bugs: Critical 0 · High 0 · Medium 0 · Low 1 (behoben)

## Akzeptanzkriterien
| AK | Ergebnis | Nachweis |
|---|---|---|
| AK-1 Nur `admin`/`haushalt`/`guest` im frischen Schema | ✅ | Test-DB aus `init-schema.sql`: `INSERT … role 'user'`/`'child'` → Check-Verletzung `users_role_check`, ohne Rolle → `haushalt`; Container-Rauchtest alice-chat-stream (Rolle per UPDATE auf `user`/`child` scheitert) |
| AK-2 `user` → `haushalt`, `child` → `guest` | ✅ | DB im alten Stand (Schema von `dev`) mit Nutzern aller vier Rollen, Migration angewendet: admin/guest unverändert, user → haushalt, child → guest, voice-guest bleibt guest |
| AK-3 Rollen-Einstellungen + Daten migriert | ✅ | gleicher Lauf: geänderte Werte der Vorlage `user` (timer_max_active 7, Kalender aus) stehen unter `haushalt`; Vorlage `child` weg; Timer `user` → `haushalt`, `child` → `guest`, admin unverändert; `timer_default_role` → `"haushalt"`; individuelles HA-Recht (`lock`) des Bestandsnutzers erhalten |
| AK-4 Idempotent | ✅ | Migration zweimal mit `ON_ERROR_STOP=1`: zweiter Lauf ohne Fehler, ändert nichts; danach `pg_dump --schema-only` identisch mit frischem Aufbau |
| AK-5 `haushalt` sieht alle Dokumente, Mails (alle Postfächer), Bilder | ✅ ⚠️ | Unit: Archiv-Werkzeuge angeboten und ausgeführt (`tests/test_archive_access.py`); Container-Rauchtest: `archive_access` = True für haushalt aus echter DB; SQL der n8n-Knoten gegen Test-DB: haushalt bekommt Rolle (alle Collections), alle Postfächer inkl. fremdem, Zugangsdaten fremder Postfächer; Code-Knoten `Apply DMS Filter` mit Node: alle 7 Dokument-Collections + Image. Live-Suche: nach Deploy |
| AK-6 `admin` wie `haushalt` | ✅ ⚠️ | wie AK-5 |
| AK-7 `guest`/unerkannter Sprecher: kein Zugriff, Ablehnung | ✅ ⚠️ | Unit: keine Archiv-Werkzeuge, Aufruf → `access_denied` ohne n8n-Aufruf, Systemprompt mit Ablehnungsanweisung + Sprachanweisung der Nutzereinstellung; Rauchtest: voice-guest/guest/inaktiv → False; n8n: guest/voice-guest bekommen keine Rolle, keine Postfächer, keine Zugangsdaten; Filter mit leerem/fehlerhaftem Ergebnis → leere Collections. Text der Ablehnung kommt vom LLM → nicht live geprüft |
| AK-8 Verwaltung nur `admin` (403) | ✅ | `alice-auth/tests/test_roles.py` + Rauchtest (haushalt/guest/user-Token → 403 auf Nutzerverwaltung); Kalender/Listen-Tests (haushalt → 403 auf Rollen-API); n8n mail-api Code-Knoten: POST/PUT/DELETE für haushalt/guest → 403, auch als Eigentümer; WebApp: haushalt wird von `/settings/nutzer` umgeleitet |
| AK-9 HA, Chat, Timer, Kalender, Listen wie bisher `user` | ✅ | Vorlage `haushalt` = Vorlage `user` (Werte 1:1, nur Werkzeugliste ergänzt); Listen- und Kalender-Testsuiten laufen mit `haushalt` statt `user` unverändert grün (102 + 113 Tests); Timer-Tests mit `haushalt` |
| AK-10 Such-Werkzeuge für `haushalt`, `guest` nur HA | ✅ | `test_household_gets_all_archive_tools`, `test_guest_gets_no_archive_tools_but_home_assistant`, `test_stream_chat_uses_archive_access` |
| AK-11 WebApp: nur drei Rollen, i18n | ✅ | Playwright: Rollenauswahl „Neuer Nutzer" = Administrator/Haushalt/Gast; Kalender-, Listen-, Timer-Rollen je genau drei; kein „Kind" mehr; Badges übersetzt. Hinweis: eine Oberfläche zum Ändern der Rolle bestehender Nutzer gibt es nicht (gab es vorher nicht, siehe design.md) |
| AK-12 Kein Zugriffsdialog, Verwaltung nur `admin` | ✅ ⚠️ | Playwright: Admin ohne Spalte „Zugriff" und ohne Zugriffsknopf, mit Bearbeiten/Löschen; haushalt sieht alle Postfächer (auch fremde) ohne Hinzufügen/Bearbeiten/Löschen (1440 und 375px); Workflow-Endpunkte `mailboxes/access` entfernt. n8n live: nach Deploy |
| AK-13 APIs lehnen `user`/`child` ab | ✅ | Auth (422, Test + Rauchtest), Kalender und Listen (422, Integrationstests), Chat-Stream Timer-Konfiguration (Pydantic im Container-Rauchtest: `default_role`/`roles` mit `user`/`child` abgelehnt, `haushalt` ok) |
| AK-14 Tabellen/Funktion weg, nirgends referenziert | ✅ | nach Migration `to_regclass` NULL, keine Funktion `check_dms_permission`; `git grep` findet sie nur noch in der Migration, `docs/` (Historie) und `features/old/` – in keinem Workflow, Dienst oder WebApp |
| AK-15 Vorlagen nur drei Rollen | ✅ | Test-DB: `role_templates` = admin, guest, haushalt; Auth-Integrationstest legt je Rolle einen Nutzer an und prüft die Rechte aus der Vorlage |
| AK-16 Live-Test | – | Mensch nach Deploy |

## Edge Cases
- ✅ EC-1: Schutz des letzten Admins unverändert (kein Code daran geändert).
- ✅ EC-2: Alt-Token mit `user`: Archivzugriff, Postfachliste, Kalender, Listen und Timer lesen die Rolle aus der DB (→ `haushalt`); Admin-Prüfungen verlangen `admin` (Test: `user`-Token → 403). Nie mehr als `haushalt`.
- ✅ EC-3: `user` wird überall mit Validierungsfehler abgelehnt, kein Mapping.
- ✅ EC-4: individuelle HA-Rechte eines `user`-Bestandsnutzers bleiben erhalten (Migrationstest, Domäne `lock`).
- ✅ EC-5: voice-guest (`0000…`) → kein Archivzugriff (Rauchtest, SQL der Workflows).
- ✅ EC-6: Postfach eines anderen Nutzers ist für haushalt sichtbar und durchsuchbar (SQL-Test mit fremdem Postfach).
- Hinweis: ehemalige `child`-Nutzer bekommen die Gast-Rechte neu gesetzt (Kinder-Sonderrechte entfallen, siehe design.md).

## Bugs
- **B-1 (Low, behoben in `e7d44e3`):** Hinweistext der Listen-Rollen erwähnte noch „Kinder". Jetzt „Gäste mit Listenrecht …" (de/en).

## Sicherheit
- Rechte werden serverseitig geprüft: Chat-Stream (Werkzeugangebot + Ausführung), n8n-Workflows (Rolle aus DB), Auth/Kalender/Listen (Admin aus Token bzw. DB). Fehler bei der Rollenabfrage verweigern den Zugriff.
- `user_id` stammt in Chat-Stream aus dem geprüften JWT; die n8n-Webhooks der Postfach-Verwaltung verwenden JWT-Authentifizierung von n8n.
- Bekannt, nicht durch dieses Feature eingeführt: Die internen Such-Webhooks (`alice-tool-search`, `alice-mail-tools`) vertrauen der mitgeschickten `user_id`. Wer im VPN die ID eines Haushaltsmitglieds kennt, kann sie direkt aufrufen (vorher genauso mit der ID eines Nutzers mit Rechten). Abhilfe kommt mit PROJ-128 (Such-Tools als Dienst).
- Keine Zugangsdaten in Code, Tests oder Workflows (nur Wegwerf-Werte in Tests).

## Nicht live geprüft
- **n8n-Workflows** (`alice-tool-search`, `alice-mail-tools`, `alice-mail-api`, `alice-mail-sync`): statisch geprüft (`scripts/check-workflows.sh`), Code-Knoten isoliert mit Node, SQL der Postgres-Knoten gegen die migrierte Test-DB. Nach Import prüfen: als haushalt im Chat „Zeig mir den letzten Kontoauszug" und „Habe ich Mails von <Absender aus fremdem Postfach>?" → Treffer; als Gast → Ablehnung; E-Mail-Tab als haushalt zeigt alle Postfächer.
- **Ablehnungstext des LLM** (AK-7): nur Prompt und Werkzeugangebot geprüft. Staging: `scripts/stage.sh alice-chat-stream <PR>` und mit einem Gast-Token `POST /stream/chat` „Zeig mir meine Rechnungen" → freundliche Ablehnung in der Sprache des Gasts, kein `tool_start` für Suchwerkzeuge.
- **alice-speech-gateway**: Änderung zweizeilig (Einroll-Rolle, Token-Rolle); Testsuite und Containertest laufen in der Factory nicht (`SKIP`, schwere Abhängigkeiten). Neuer Test `tests/test_enrollment_role.py`, Funktion isoliert ausgeführt. Nach Deploy: neuen Nutzer per Sprache einrollen → Rolle `haushalt`.
- **Migration auf Produktiv-DB**: nur gegen nachgebauten Altbestand getestet. Vorher Sicherung.

## Automatisierte Tests
- `SKIP=alice-speech-gateway scripts/test-services.sh`: alice-auth 10, alice-calendar 113, alice-chat-stream 424, alice-lists 102, alice-llm-gateway 33 – alle bestanden
- `scripts/test-containers.sh alice-auth alice-calendar alice-lists alice-chat-stream`: alle gesund, Rauchtests (auth, chat-stream) bestanden
- `scripts/check-workflows.sh`: 24 Workflows OK
- Frontend: `npx tsc --noEmit` und `npm run build` grün; Playwright (Chromium, APIs gemockt): Admin/Haushalt/Gast, 1440 und 375px, keine Konsolenfehler, kein horizontaler Überlauf
- Migration: Altbestand → zweimal angewendet → Schema identisch mit frischem Aufbau
