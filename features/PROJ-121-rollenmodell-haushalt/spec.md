# PROJ-121: Rollenmodell Haushalt

**Erstellt:** 2026-11-20
**Phase:** 4.1

<!-- Der Status steht nur in features/INDEX.md. Diese Datei schreibt nur der Mensch (/write-spec, /refine). -->

## Abhängigkeiten
- Keine (erstes Feature der Phase 4; PROJ-122, PROJ-128, PROJ-131, PROJ-132 bauen auf dem Rollenmodell auf)

## User Stories
- Als Haushaltsmitglied (Rolle `haushalt`) möchte ich alle Dokumente, Mails, Bilder und später das Wiki ohne Einzelfreigaben durchsuchen und ansehen können, damit ich Alice alles zum Haushalt fragen kann.
- Als Admin möchte ich zusätzlich Nutzer, Ordner, Postfächer, Logs und den ETL verwalten, damit ich das System betreiben kann.
- Als Admin möchte ich Nutzer nur noch einer von drei Rollen (`admin`, `haushalt`, `guest`) zuordnen, ohne Rechte je Dokumenttyp oder Postfach pflegen zu müssen, damit die Verwaltung einfach bleibt.
- Als Gast (Rolle `guest`) bekomme ich weiterhin nur die freigegebenen Home-Assistant-Funktionen, ohne Zugriff auf Dokumente, Mails oder Wiki.

## Rollen im Zielzustand

| Rolle | Dokumente, Bilder, Mails, Wiki | Home Assistant, Chat, Timer, Kalender, Listen | Verwaltung |
| ----- | ------------------------------ | --------------------------------------------- | ---------- |
| `admin` | alle lesen/suchen/herunterladen | voll (wie bisher `admin`) | Nutzer, Ordner, Postfächer, Logs, Workflows/ETL, Neuaufbau |
| `haushalt` | **alle** lesen/suchen/herunterladen, auch Kontoauszüge, Buchungen, Wertpapiere, alle Postfächer | unverändert wie bisherige Rolle `user` | keine |
| `guest` | kein Zugriff | unverändert wie bisher `guest` | keine |

Beide Haushaltsmitglieder haben identische Rechte; es gibt keine Unterscheidung untereinander.

## Außerhalb des Umfangs
- Rechte je Dokumenttyp und je Postfach (entfallen ersatzlos)
- Rolle `child` (entfällt, inkl. Zeit- und Raumbeschränkungen der Vorlage)
- Neue Rechte für das Wiki selbst und die Wiki-Ansicht (PROJ-131, PROJ-132); hier wird nur festgelegt, dass `haushalt` und `admin` Zugriff haben und `guest` nicht
- Änderungen an HA-Rechten, Timer-/Kalender-/Listen-Funktionen oder Sprechererkennung
- Freigabe der Cloud-Recherche für `haushalt` (PROJ-137)
- Schreibende Dokumentfunktionen in Alice: Originale liegen außerhalb von Alice, Korrekturen der Quell-Markdown erfolgen direkt im Quelle-der-Wahrheit-Ordner (PROJ-115); Alice kennt für Dokumente nur Lesen, Suchen, Herunterladen
- Neue Oberfläche für Rollenverwaltung über das hinaus, was zur Umstellung auf drei Rollen nötig ist

## Akzeptanzkriterien
- [ ] AK-1: Angenommen eine frisch aufgebaute Datenbank, wenn der Schema-Aufbau läuft, dann sind als Rollen nur `admin`, `haushalt` und `guest` zulässig; ein Nutzer mit `user` oder `child` kann nicht mehr angelegt werden (Datenbank lehnt ab).
- [ ] AK-2: Angenommen eine Bestandsdatenbank mit Nutzern der Rollen `admin`, `user`, `guest` und `child`, wenn die Migration läuft, dann haben `user`-Nutzer danach `haushalt`, `child`-Nutzer `guest`, `admin` und `guest` bleiben unverändert.
- [ ] AK-3: Angenommen die Bestandsdatenbank enthält Rollen-Einstellungen für Kalender, Listen und Timer je Rolle, wenn die Migration läuft, dann sind die Werte der Rolle `user` unter `haushalt` übernommen, die Zeilen der Rolle `child` entfernt und bestehende Timer, Kalender- und Listen-Daten behalten ihre Zuordnung (Eigentümerrolle `user` → `haushalt`, `child` → `guest`).
- [ ] AK-4: Angenommen die Migration wurde bereits ausgeführt, wenn sie erneut läuft, dann ändert sie nichts und bricht nicht ab (idempotent).
- [ ] AK-5: Angenommen ein Nutzer der Rolle `haushalt`, wenn er per Chat oder API Dokumente, Mails oder Bilder aller Typen abfragt (inkl. Kontoauszüge, Buchungen, Wertpapierabrechnungen, E-Mails aus allen Postfächern, auch fremden), dann werden die Treffer ausgeliefert, ohne dass eine Freigabe je Dokumenttyp oder Postfach nötig ist.
- [ ] AK-6: Angenommen ein Nutzer der Rolle `admin`, wenn er dieselben Abfragen stellt, dann gilt dasselbe wie für `haushalt`.
- [ ] AK-7: Angenommen ein Nutzer der Rolle `guest` oder ein nicht erkannter Sprecher, wenn er Dokumente, Mails oder Bilder abfragt, dann erhält er keine Treffer und eine verständliche Ablehnung in seiner Sprache; Home-Assistant-Funktionen laufen wie bisher.
- [ ] AK-8: Angenommen ein Nutzer der Rolle `haushalt`, wenn er Verwaltungsfunktionen aufruft (Nutzer, Ordner, Postfächer verwalten, Logs, ETL-Status), dann werden diese mit 403 abgelehnt; für `admin` sind sie erlaubt.
- [ ] AK-9: Angenommen ein Nutzer der Rolle `haushalt`, wenn er Chat, Sprache, Timer, Kalender, Listen und Home Assistant nutzt, dann verhalten sich Rechte, Grenzen (z. B. maximale Timer) und erlaubte HA-Domänen exakt wie bisher bei `user`.
- [ ] AK-10: Angenommen ein Nutzer der Rolle `haushalt` mit erlaubten Chat-Werkzeugen, wenn der Agent Werkzeuge wählt, dann stehen ihm alle Dokument-, Bild- und Mail-Suchwerkzeuge zur Verfügung; `guest` weiterhin nur Home Assistant.
- [ ] AK-11: Angenommen die WebApp, wenn ein Admin einen Nutzer anlegt oder die Rolle ändert, dann stehen nur `admin`, `haushalt` und `guest` zur Auswahl (Anzeigenamen über i18n); die Rollen-Einstellungen für Kalender, Listen und Timer zeigen nur diese drei Rollen.
- [ ] AK-12: Angenommen die WebApp, wenn ein Admin die Postfach-Verwaltung öffnet, dann gibt es keinen Dialog und keine Auswahl mehr für Zugriff je Nutzer; jedes Postfach ist für alle `haushalt`- und `admin`-Nutzer sichtbar, Anlegen/Ändern/Löschen nur für `admin`.
- [ ] AK-13: Angenommen die API für Nutzer-, Rollen- und Rollenvorlagen-Verwaltung (Auth, Chat-Stream, Kalender, Listen), wenn ein Request die Rolle `user` oder `child` enthält, dann wird er mit einer Validierungsfehlermeldung abgelehnt; `haushalt` wird akzeptiert.
- [ ] AK-14: Angenommen die Datenbank nach der Migration, wenn man nach Tabellen und Funktionen für Rechte je Dokumenttyp (`permissions_dms`, `check_dms_permission`) und je Postfach-Nutzer (`imap_mailbox_access`) sucht, dann existieren sie nicht mehr, und keine Komponente (Workflow, Service, WebApp) referenziert sie.
- [ ] AK-15: Angenommen die Rollenvorlagen, wenn ein neuer Nutzer angelegt wird, dann erhält er die Rechte der gewählten Rolle (`admin`, `haushalt`, `guest`); die Vorlage `child` existiert nicht mehr.
- [ ] AK-16 (Live-Test nach Deploy): Angenommen die produktive Instanz nach der Migration, wenn sich beide Haushaltsmitglieder und der Admin anmelden und je eine Frage zu einem Kontoauszug und einer Mail stellen, dann bekommen sie Antworten; ein Gast-Login bekommt sie nicht.

## Edge Cases
- EC-1: Was passiert, wenn der Admin die eigene Rolle auf `haushalt` ändert und kein weiterer Admin existiert? → bestehendes Verhalten bleibt (Schutz vor Entfernen des letzten Admins, sofern vorhanden); keine Änderung durch dieses Feature.
- EC-2: Was passiert, wenn ein Nutzer während der Migration eingeloggt ist? → Sein bestehendes Token mit Rolle `user` wird nach der Migration weiter akzeptiert und als `haushalt` behandelt oder verlangt einen neuen Login; in keinem Fall bekommt er mehr Rechte als `haushalt`.
- EC-3: Was passiert, wenn ein alter Client oder ein gespeicherter Rollenwert `user` sendet? → Abgelehnt mit Validierungsfehler (AK-13), kein stilles Mapping.
- EC-4: Was passiert, wenn individuell angepasste Einzelrechte (z. B. HA) an einem Bestandsnutzer existieren? → Sie bleiben bei der Rollenumbenennung erhalten; nur DMS- und Postfach-Einzelrechte entfallen.
- EC-5: Was passiert bei Sprachanfrage eines nicht erkannten Sprechers? → Wie bisher `guest`-Kontext (AK-7); kein Zugriff auf Dokumente, Mails, Wiki.
- EC-6: Was passiert, wenn ein Postfach heute nur für einen Nutzer freigegeben war? → Es ist künftig für alle `haushalt`/`admin` sichtbar (bewusste Entscheidung, siehe Product Decisions).

## Technische Anforderungen
- Migration der Bestandsdatenbank als wiederholbares Skript; der konsolidierte Schema-Aufbau (`sql/init-schema.sql`) enthält den Zielzustand.
- Kein neuer Container.
- Zugriffsprüfung für Dokumente/Mails/Wiki nur noch über die Rolle (`admin`/`haushalt` ja, `guest` nein), nicht mehr über Tabellen je Nutzer.

## Offene Fragen
- Keine

## Product Decisions
- Rolle `user` wird zu `haushalt` umbenannt (DB, Services, WebApp): ein durchgängiger Begriff statt zwei; PRD-Sprache gilt überall (2026-11-20)
- Bestehende `child`-Nutzer werden `guest`: restriktivste verbleibende Rolle, kein stiller Rechtezuwachs; Kinder sind im Haushalt nicht vorgesehen (2026-11-20)
- `haushalt` bekommt nur Lesen, Suchen und Herunterladen auf alle Dokumente, Mails, Bilder und das Wiki; Ändern/Löschen/Anlegen gibt es in Alice für Dokumente nicht, weil Originale außerhalb von Alice liegen und Markdown-Korrekturen direkt im Quelle-der-Wahrheit-Ordner erfolgen (2026-11-20)
- Alle Postfächer sind für alle Haushaltsmitglieder sichtbar; Verwalten bleibt `admin` (PRD: Rechte je Postfach entfallen) (2026-11-20)
- Alle übrigen Rechte von `haushalt` (HA, Chat, Timer, Kalender, Listen) bleiben wie bei der bisherigen Rolle `user`, damit keine Regression entsteht (2026-11-20)
