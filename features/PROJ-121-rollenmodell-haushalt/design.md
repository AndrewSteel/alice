# Architektur: PROJ-121 Rollenmodell Haushalt (#1)

**Spec:** [spec.md](spec.md) · **Stand:** 2026-11-20

## A) Betroffene Bausteine
```
PostgreSQL (Schema alice)
+-- alice.users.role            nur noch admin | haushalt | guest (Standard: haushalt)
+-- alice.timers.owner_role     nur noch admin | haushalt | guest
+-- alice.role_templates        Vorlagen admin, haushalt, guest; Spalte dms_permissions entfällt
+-- alice.system_settings       timer_default_role: "user" → "haushalt"
+-- alice.init_user_permissions ohne DMS-Teil
+-- entfernt: alice.permissions_dms, alice.check_dms_permission(), alice.imap_mailbox_access,
|             Sicht alice.v_dms_permissions (Sicht v_user_permissions_summary ohne DMS-Spalte)
+-- sql/init-schema.sql (Zielzustand) + sql/migrations/2026-11-20_PROJ-121_rollenmodell-haushalt.sql

alice-auth           Nutzer anlegen: nur admin | haushalt | guest (sonst 422)
alice-chat-stream    Timer-Rollen-API: nur die drei Rollen; Such-/Mail-/Bildwerkzeuge nur für admin/haushalt,
                     sonst ausgeblendet + Ablehnungshinweis an das LLM (Nutzersprache)
alice-calendar       Rollen-API: nur die drei Rollen
alice-lists          Rollen-API und Listenregeln: "user" → "haushalt"
alice-speech-gateway Einrollen per Sprache legt "haushalt" statt "user" an; Dienst-Token-Rolle "haushalt"

n8n: alice-tool-search   Zugriff je Rolle statt je Dokumenttyp
n8n: alice-mail-tools    alle Postfächer für admin/haushalt, keine für guest
n8n: alice-mail-api      Liste für admin/haushalt komplett; Anlegen/Ändern/Löschen nur admin;
                         Endpunkte für Zugriff je Postfach entfernt
n8n: alice-mail-sync     Benachrichtigung „wichtige Mail" an alle aktiven admin/haushalt

Frontend: Einstellungen › Nutzer (Anlegen-Dialog, Rollen-Badges, Kalender-/Listen-/Timer-Rollen)
Frontend: Einstellungen › E-Mail (ohne Zugriffsdialog/-spalte, Verwalten nur admin)
Frontend: i18n de/en (Rollenname „Haushalt"/„Household", „Kind" entfällt)
```

## B) Datenmodell
- **Rolle des Nutzers** bleibt eine Spalte an `alice.users`. Erlaubt sind nur noch `admin`, `haushalt`, `guest`; die Datenbank lehnt andere Werte ab. Neue Nutzer ohne Angabe bekommen `haushalt`.
- **Zugriff auf Dokumente, Bilder, Mails (später Wiki)** wird nicht mehr gespeichert, sondern aus der Rolle abgeleitet: `admin` und `haushalt` ja, `guest` nein. Die Tabellen für Rechte je Dokumenttyp und je Postfach-Nutzer entfallen samt Prüffunktion.
- **Rollenvorlagen** gibt es nur noch für die drei Rollen. Die Vorlage `haushalt` übernimmt alle bisherigen Werte der Vorlage `user` (HA-Domänen, Timer-Grenzen, Kalender, Listen, Systemrechte), ergänzt in der Werkzeugliste um die Mail-/Detailwerkzeuge. Die Vorlage `child` wird gelöscht.
- **Timer** gehören weiter einer Rolle: bestehende Timer der Rolle `user` gehören danach `haushalt`, die von `child` gehören `guest`.
- **Postfächer** behalten ihren Eigentümer (wer sie angelegt hat), er steuert aber keine Sichtbarkeit mehr.
- Wer was sieht: Datenbank-Inhalte unverändert; nur die Prüfung verlagert sich auf die Rolle.

## C) Abläufe
1. **Migration (einmalig, wiederholbar):** in einer Transaktion: alte Sichten/Funktion/Tabellen entfernen → Rollen-Prüfregeln an Nutzern und Timern ersetzen, dabei `user` → `haushalt`, `child` → `guest` → Vorlage `haushalt` aus `user` erzeugen (nur wenn noch nicht vorhanden), `user`/`child` löschen → Timer-Voreinstellung umstellen → Hilfsfunktion und Übersichtssicht neu anlegen. Ein zweiter Lauf findet nichts mehr zu ändern.
   Ehemalige `child`-Nutzer bekommen die Rechte der Vorlage `guest` neu gesetzt (ihre Kinder-Sonderrechte entfallen), damit kein stiller Rechtezuwachs oder Mischzustand entsteht.
2. **Chat-Anfrage (WebApp oder Sprache):** alice-chat-stream liest pro Anfrage die aktuelle Rolle des Nutzers aus der Datenbank (nicht aus dem Token).
   - `admin`/`haushalt`: alle Werkzeuge wie bisher; Such-Workflows liefern Treffer aller Dokumenttypen und aller Postfächer.
   - `guest` bzw. nicht erkannter Sprecher (Gast-Nutzer `voice-guest`): Dokument-, Bild- und Mailwerkzeuge werden dem LLM nicht angeboten, und der Systemprompt weist es an, solche Anfragen freundlich abzulehnen. Die Antwort folgt der eingestellten Sprache des Nutzers (bestehende Sprachanweisung). Ruft das LLM ein solches Werkzeug trotzdem auf, liefert der Dienst „kein Zugriff" statt einer Suche. HA bleibt unverändert.
   - Zusätzlich prüfen die n8n-Such-Workflows selbst die Rolle (zweite Verteidigungslinie).
3. **Postfach-Verwaltung (WebApp):** Liste zeigt `admin` und `haushalt` alle Postfächer; `guest` eine leere Liste. Anlegen, Ändern, Löschen lehnt der Workflow für Nicht-Admins mit 403 ab; in der WebApp sind die Knöpfe nur für Admins sichtbar.
4. **Verwaltung (Nutzer, Ordner, Logs, Workflows/ETL, Chat-Archiv):** unverändert nur `admin` (Prüfung `role == admin` bzw. Systemrechte der Vorlage); `haushalt` bekommt 403 wie bisher `user`.
5. **Alte Tokens (EC-2):** Ein vor der Migration ausgestelltes Token mit `user` bleibt bis zum Ablauf gültig. Alle rechte-relevanten Prüfungen lesen die Rolle frisch aus der Datenbank (→ `haushalt`), Admin-Prüfungen verlangen weiterhin `admin`. Das Token bekommt also nie mehr als `haushalt`.

## D) Technische Entscheidungen
- **Zugriff aus der Rolle in der Datenbank, nicht aus dem Token**, weil Tokens der Sprachsteuerung immer eine feste Rolle tragen und alte Tokens nach der Migration noch `user` enthalten (EC-2). Kalender, Listen und Timer machen das schon so.
- **Werkzeuge für Gäste ausblenden + Prompt-Hinweis + Sperre im Dienst**, weil heute die Werkzeuge allen angeboten werden und der Gast nur leere Treffer bekommt („nichts gefunden" statt Ablehnung). So lehnt das LLM in der Nutzersprache ab, und ein dennoch versuchter Aufruf liefert keine Daten.
- **n8n-Workflows prüfen zusätzlich die Rolle**, weil sie per Webhook direkt erreichbar sind. Knotennamen bleiben gleich, damit Verbindungen und Referenzen stabil bleiben.
- **Spalte `dms_permissions` der Vorlagen entfällt**, weil sie ohne Zieltabelle nur noch toter Inhalt wäre (AK-14).
- **Rolle `user` wird hart abgelehnt (422)**, kein stilles Mapping (EC-3).
- **Benachrichtigung wichtiger Mails an alle `admin`/`haushalt`**, weil jedes Postfach jetzt für alle sichtbar ist und die bisherige Empfängerliste (Eigentümer + Freigaben) entfällt.
- **Die Listenregeln für „sonstige Rollen"** (früher für `child`) bleiben bestehen; sie greifen jetzt für `guest`, falls ein Admin Gästen Listen erlaubt.

## E) Abhängigkeiten
- Pakete: keine neuen
- Neue Umgebungsvariablen: keine

## F) Test- und Deploy-Plan
| AK | Nachweis | Art |
|---|---|---|
| AK-1 | frische Test-DB aus `init-schema.sql`: Einfügen `user`/`child` scheitert, `haushalt` klappt | Integration (Test-DB) |
| AK-2, AK-3, AK-4, AK-14, AK-15 | Test-DB im alten Stand (Schema von `dev`) mit Nutzern aller Rollen, Timern, Vorlagen; Migration zweimal; Prüfabfragen | Integration (Test-DB, Skript) |
| AK-5, AK-6, AK-7, AK-10 | Chat-Stream: Werkzeugliste/Prompt/Sperre je Rolle (Unit + Test-DB); Code der n8n-Knoten isoliert mit Node gegen Beispiel-Items; Such-SQL gegen Test-DB | Unit / Integration / statisch |
| AK-8 | bestehende Admin-Prüfungen in Auth/Chat-Stream/Kalender/Listen mit `haushalt`-Token → 403 | Unit / Integration |
| AK-9 | Listen-, Kalender-, Timer-Tests mit `haushalt` statt `user` (gleiche Grenzen) | Integration (Test-DB) |
| AK-11, AK-12 | WebApp mit gemockten APIs im Browser: Rollen-Auswahl, Rollen-Einstellungen, E-Mail-Tab ohne Zugriffsdialog | Browser |
| AK-13 | Auth/Chat-Stream/Kalender/Listen: Requests mit `user`/`child` → 422, `haushalt` ok | Unit / Integration |
| AK-16 | Live-Test nach Deploy | Mensch |

Nicht ohne Produktivsysteme testbar: echtes LLM (Ablehnungstext), n8n-Ausführung, Weaviate-Inhalte, IMAP → Attrappen: gefälschter LLM-Stream, Node-Ausführung der Code-Knoten, SQL der Postgres-Knoten gegen die Test-DB.

Deploy-Schritte für den Menschen:
1. Datenbank sichern, dann Migration `sql/migrations/2026-11-20_PROJ-121_rollenmodell-haushalt.sql` anwenden.
2. n8n-Workflows importieren: `alice-tool-search`, `alice-mail-tools`, `alice-mail-api`, `alice-mail-sync`.
3. Container neu bauen: alice-auth, alice-chat-stream, alice-calendar, alice-lists, alice-speech-gateway.
4. Frontend bauen und deployen.
5. Alle Nutzer einmal neu anmelden lassen (optional; alte Tokens funktionieren als `haushalt`).

## Decision Log
| Entscheidung | Alternative | Abwägung |
|---|---|---|
| Rolle frisch aus DB für Dokumentzugriff | Rolle aus dem Token | Token der Sprachsteuerung und Alt-Tokens tragen falsche Rolle; DB-Abfrage ist billig (1 Zeile, Primärschlüssel) |
| Werkzeuge für Gast ausblenden + Prompt-Ablehnung | Werkzeuge anbieten, leere Treffer | Leere Treffer erzeugen „nichts gefunden" statt Ablehnung (AK-7) |
| Feste Ablehnungsvorlage je Sprache ohne LLM | LLM formuliert Ablehnung | Vorlage wäre deterministisch, bräuchte aber eine eigene Erkennung „Dokument-Frage?" vor dem LLM; Sprache folgt ohnehin der Nutzereinstellung |
| `child` → Vorlage `guest` neu anwenden | nur Rolle umbenennen | Nur Umbenennen ließe Kinder-Rechte (z. B. Listen, Timer) an einem „Gast" hängen; Kinder sind nicht vorgesehen |
| Mail-Benachrichtigung an alle admin/haushalt | nur Eigentümer | Sichtbarkeit aller Postfächer für alle ist Product Decision; Eigentümer allein wäre ein Rückschritt für bisher Freigegebene |
| Zugriffs-Endpunkte im Workflow entfernen | stehen lassen | Sie schreiben in die entfernte Tabelle und würden fehlschlagen (AK-14) |

## Umsetzung

**Gebaut (2026-11-20):**
- **Schema:** `sql/init-schema.sql` enthält den Zielzustand (Rollen-Prüfregel an `users`/`timers`, Standardrolle `haushalt`, Vorlagen `admin`/`haushalt`/`guest` ohne Spalte `dms_permissions`, `init_user_permissions` ohne DMS-Teil, Timer-Voreinstellung `haushalt`). Entfernt: `permissions_dms`, `check_dms_permission`, `v_dms_permissions`, `imap_mailbox_access`. Migration `sql/migrations/2026-11-20_PROJ-121_rollenmodell-haushalt.sql`; gegen eine Datenbank im alten Stand zweimal angewendet, danach ist das Schema identisch mit einem frischen Aufbau.
- **alice-auth:** Nutzer anlegen nur mit `admin`/`haushalt`/`guest` (sonst 422). Neue Tests (`tests/`) inkl. Anlegen gegen die Test-Datenbank und Rauchtest im Container.
- **alice-calendar, alice-lists:** Rollen-API nur noch drei Rollen (`user`/`child` → 422); Listenregeln `user` → `haushalt`. Die bisherigen Regeln für `child` gelten weiter für alle übrigen Rollen, d. h. für Gäste, falls ein Admin ihnen Listen freigibt.
- **alice-chat-stream:** `tools.archive_access()` liest die Rolle frisch aus `alice.users` (aktiv + `admin`/`haushalt`), bei Fehlern kein Zugriff. Ohne Zugriff: Archiv-Werkzeuge nicht im Werkzeugangebot, Systemprompt mit Ablehnungsanweisung (Sprache folgt der Nutzereinstellung), Aufruf trotzdem → `access_denied`. Timer-Rollen-API nur drei Rollen; Rückfall-Rolle `haushalt`.
- **alice-speech-gateway:** Einrollen per Sprache legt `haushalt` an; Dienst-Token tragen `haushalt` (informativ, die Dienste lesen die Rolle aus der DB).
- **n8n:** `alice-tool-search` prüft die Rolle statt Dokumenttyp-Rechten (Postgres-Knoten liefert jetzt auch bei leerem Ergebnis ein Item, damit Gäste eine leere Antwort statt keiner bekommen); `alice-mail-tools` alle Postfächer für `admin`/`haushalt`; `alice-mail-api` Liste für `admin`/`haushalt` (Rolle aus der DB, max. 200), Anlegen/Ändern/Löschen nur `admin` (403), Zugriffs-Endpunkte entfernt; `alice-mail-sync` benachrichtigt alle aktiven `admin`/`haushalt`.
- **WebApp:** Rollenauswahl und Rollen-Einstellungen (Kalender, Listen, Timer) mit drei Rollen, Anzeigenamen über i18n (auch Rollen-Badges, Profil, Stimmprofile, Seitenleiste); E-Mail-Tab ohne Zugriffsspalte und -dialog, Hinzufügen/Bearbeiten/Löschen nur mit `can_manage_mailboxes` (Admin).
- **Doku:** `CLAUDE.md` (Code-Referenz) angepasst.

**Abweichungen / Hinweise:**
- Eine Oberfläche zum Ändern der Rolle eines bestehenden Nutzers gibt es nicht (gab es vorher auch nicht); AK-11 ist für das Anlegen umgesetzt, Rollenwechsel bleibt außerhalb des Umfangs.
- Der Workflow-Endpunkt `GET alice/users` (Nutzerliste, im Frontend ungenutzt) bleibt unverändert; er referenziert keine entfernte Tabelle.
- `docs/` (Briefing, Planungsnotizen, `dms-pipeline-map.html`) erwähnt die alten Tabellen noch als Historie; nicht geändert.
- Der E-Mail-Tab bleibt für Gäste sichtbar, zeigt ihnen aber eine leere Liste.
