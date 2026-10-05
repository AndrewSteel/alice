# PROJ-87: Kalender-Agent

## Status: Planned
**Created:** 2026-10-05
**Last Updated:** 2026-10-05

## Dependencies
- Requires: PROJ-86 (Google-API-Infrastruktur) — OAuth-Flow, Connection-Verwaltung, Token-Abruf (`/token` kann ein transientes, retrybares 503 liefern; 409 `reauth_required` bei widerrufener Verbindung)
- Requires: bestehendes Rollen-/Permission-System (`alice.role_templates` / `alice.permissions_assistant`) — neue Kalender-Berechtigung pro Rolle
- Requires: Speaker-ID im `alice-speech-gateway` (Sprecher-Zuordnung zu einem User; Verbesserung → PROJ-103)
- Vorbild (UI-Muster): Postfach-Verwaltung (PROJ-46, `MailboxSection`)
- Wird nicht benötigt von PROJ-88/89, teilt aber den Konto-Verbinden-Baustein (Konten-Liste, Scope-Erweiterung, Trennen) konzeptionell mit ihnen

## Kontext

Der Kalender-Agent gibt Alice Zugriff auf die Google-Kalender eines Users: **Termine per Chat/Sprache anzeigen, anlegen, ändern und löschen** sowie ein Settings-Tab „Kalender", in dem der User Google-Konten verbindet und festlegt, welche seiner Google-Kalender Alice nutzen darf.

Es werden **keine Kalenderdaten lokal gespeichert** (PRD-Constraint „nur Live-Abfragen"). Gespeichert wird ausschließlich die Auswahl (welche Kalender aktiv, welcher Standard) — keine Termine.

Kalender sind **strikt pro User privat** (PROJ-86): kein Teilen, kein Admin-Zugriff auf fremde Kalender.

## User Stories

- Als berechtigter User möchte ich im Settings-Tab „Kalender" ein Google-Konto verbinden, damit Alice auf meine Kalender zugreifen kann.
- Als User möchte ich pro Google-Konto auswählen, welche meiner Google-Kalender Alice nutzen darf, und einen Standard-Kalender für neue Termine festlegen, damit z. B. Feiertags- oder Geburtstagskalender nicht stören.
- Als User möchte ich Alice per Sprache oder Chat fragen, welche Termine anstehen („Was steht morgen an?", „Wann ist mein nächster Termin?"), damit ich meinen Tag ohne Blick in die Google-App kenne.
- Als User möchte ich per Sprache oder Chat Termine anlegen (inkl. Ort, Beschreibung, ganztägig, Erinnerung und einfacher Wiederholung), damit ich nichts vergesse.
- Als User möchte ich Termine per Sprache oder Chat verschieben, umbenennen oder löschen, ohne dass ein Hörfehler versehentlich etwas Falsches entfernt.
- Als User möchte ich im Tab und im Chat klar erfahren, wenn meine Google-Verbindung nicht mehr funktioniert, und sie mit einem Klick erneuern können.
- Als Admin möchte ich pro Rolle steuern, wer den Kalender-Agenten nutzen darf.

## Acceptance Criteria

### Settings-Tab „Kalender"

- [ ] Der Tab „Kalender" erscheint in den Settings nur für Rollen mit Kalender-Berechtigung; ohne Berechtigung ist der Tab ausgeblendet.
- [ ] Der Tab listet **alle** Google-Konten des Users (Connections aus PROJ-86) mit Konto (E-Mail), Status und – bei Konten mit Kalender-Scope – deren Kalendern. Ein Button „Konto verbinden" startet den Google-Consent-Flow mit Kalender-Scope; nach Rückkehr (Erfolg oder Fehler) zeigt der Tab eine erkennbare Meldung und die aktualisierte Liste.
- [ ] Konten ohne Kalender-Scope (z. B. über einen späteren Aufgaben-/Kontakte-Tab verbunden) werden angezeigt mit dem Button „Kalender-Zugriff freigeben"; dieser löst einen gezielten Re-Consent aus und erweitert die bestehende Connection (kein Duplikat).
- [ ] Unter jedem Konto mit Kalender-Scope werden dessen Google-Kalender live von Google geladen (Name, ggf. Farbe, ob nur lesbar). Pro Kalender gibt es einen Schalter „Für Alice aktiv". Nur diese Auswahl wird in Alice gespeichert, keine Termine.
- [ ] Genau ein aktiver, beschreibbarer Kalender des Users kann als **Standard-Kalender** markiert werden (kontenübergreifend eindeutig). Wird der erste Kalender aktiviert, wird er automatisch Standard. Wird der Standard-Kalender deaktiviert, wird er entfernt; verbleibende Kalender werden nicht automatisch Standard (Alice fragt dann bei Bedarf nach).
- [ ] Schreibgeschützte Kalender (z. B. Feiertage, abonnierte Kalender) können aktiviert, aber nicht als Standard markiert werden; Alice nutzt sie nur zum Lesen.
- [ ] „Konto trennen" entfernt die gesamte Connection (alle Scopes, Revoke bei Google, PROJ-86-Verhalten). Der Bestätigungsdialog warnt, wenn das Konto auch Aufgaben-/Kontakte-Scopes hat, dass diese Features ebenfalls betroffen sind. Die Kalenderauswahl des Kontos wird mitgelöscht.
- [ ] Hat eine Connection Status `error` (Refresh-Token widerrufen), zeigt der Tab ein rotes Badge und den Button „Neu verbinden".
- [ ] Alle UI-Texte laufen über die i18n-Schicht (keine hartcodierten Strings).
- [ ] Leerzustand: Ohne verbundenes Konto zeigt der Tab eine kurze Erklärung und „Konto verbinden".

### Chat/Sprache — Anzeigen

- [ ] Alice versteht Abfragen für: heute, morgen, übermorgen, diese Woche, nächste Woche, ein konkretes Datum/Wochentag und „nächster Termin".
- [ ] Abfragen durchsuchen **alle aktiven Kalender** aller verbundenen Konten des identifizierten Users.
- [ ] Ausgabe chronologisch mit Uhrzeit (bzw. „ganztägig"), Titel, Ort (falls vorhanden); der Kalendername erscheint nur, wenn der User mehr als einen aktiven Kalender hat.
- [ ] Per Sprache liest Alice höchstens 5 Termine vor und nennt die Restanzahl („… und 3 weitere"); im Chat-Text werden alle Treffer angezeigt (max. 50, bei Überschreitung Hinweis auf Kürzung).
- [ ] Ohne Treffer sagt Alice klar, dass keine Termine vorliegen.
- [ ] Ausgabe in der konfigurierten Nutzersprache; Uhrzeiten in der Zeitzone des Users (Default Europe/Berlin).
- [ ] Serientermine werden als einzelne Vorkommen im Abfragezeitraum angezeigt.

### Chat/Sprache — Anlegen

- [ ] Alice legt einen Termin an aus: Titel + Datum/Uhrzeit; optional Dauer, Ort, Beschreibung, Kalender, Erinnerung, Wiederholung.
- [ ] Defaults: Dauer 60 Minuten; ohne Uhrzeit → ganztägiger Termin; ohne genannten Kalender → Standard-Kalender. Ist weder ein Kalender genannt noch ein Standard gesetzt, fragt Alice nach (mit Auswahl der aktiven beschreibbaren Kalender).
- [ ] Nennt der User einen Kalender („in den Familienkalender"), wird dieser genommen; ist der Name nicht eindeutig oder unbekannt, fragt Alice nach.
- [ ] Erinnerung: „erinnere mich 30 Minuten vorher" erzeugt eine Google-Erinnerung (Popup) mit entsprechendem Vorlauf.
- [ ] Wiederholung (einfach): täglich, wöchentlich (inkl. bestimmter Wochentage, z. B. „jeden Montag"), monatlich, jährlich; optional Ende („bis Ende Dezember", „10 Mal"). Komplexere Regeln („jeden zweiten Dienstag im Monat") lehnt Alice mit Hinweis auf Google ab.
- [ ] Nach dem Anlegen bestätigt Alice, was sie getan hat (Titel, Datum/Uhrzeit, Kalender), damit Hörfehler auffallen.
- [ ] Ein Termin in der Vergangenheit wird nicht stillschweigend angelegt, sondern Alice fragt zur Sicherheit nach.
- [ ] Anlegen in einem schreibgeschützten Kalender wird mit klarer Meldung abgelehnt.

### Chat/Sprache — Ändern

- [ ] Alice kann Titel, Datum/Uhrzeit, Dauer, Ort, Beschreibung, Erinnerung und Kalender eines bestehenden Termins ändern („Verschiebe den Zahnarzttermin auf 11 Uhr").
- [ ] Der Termin wird anhand von Titel/Zeitbezug identifiziert. Passen mehrere Termine, listet Alice sie kurz auf und fragt nach, statt zu raten. Passt keiner, sagt sie das.
- [ ] Änderungen laufen ohne Rückfrage, Alice bestätigt danach die neue Fassung.
- [ ] Gehört der Termin zu einer Serie, fragt Alice: „nur diesen Termin oder die ganze Serie?" und wendet die Änderung genau in diesem Umfang an („ab jetzt" ist nicht Teil des MVP).

### Chat/Sprache — Löschen

- [ ] Alice löscht Termine **nur nach Rückfrage**: Sie nennt den konkreten Termin (Titel, Datum/Uhrzeit, Kalender) und löscht erst nach einem „Ja" im folgenden Turn. Antwort „Nein"/anderes → nichts wird gelöscht.
- [ ] Bei mehreren passenden Terminen fragt Alice erst nach dem gemeinten, dann nach der Löschbestätigung.
- [ ] Gehört der Termin zu einer Serie, fragt Alice zusätzlich „nur diesen oder ganze Serie?"; die Löschbestätigung nennt den gewählten Umfang.

### Berechtigung, Zuordnung, Fehler

- [ ] Neue Kalender-Berechtigung pro Rolle im bestehenden Rollen-System (`role_templates`/`permissions_assistant`), im Admin-Bereich editierbar. Default: `admin` und `user` an, `guest` und `child` aus.
- [ ] Ohne Berechtigung lehnt Alice Kalenderanfragen höflich ab und erklärt, dass die Rolle keinen Kalenderzugriff hat; Endpoints des Tabs geben 403.
- [ ] Per Sprache nur bei **eindeutig identifiziertem User**: Bei nicht erkanntem Sprecher führt Alice keine Kalenderaktion aus und erklärt, dass sie nicht weiß, wessen Kalender gemeint ist. Kein Fallback auf Admin oder ein Geräte-Default.
- [ ] Ein User sieht und ändert ausschließlich eigene Kalender; Cross-User-Zugriffe (auch durch Admin) schlagen fehl.
- [ ] Verbindungsfehler `reauth_required` (409): Alice sagt im Chat sinngemäß, dass die Google-Verbindung erneuert werden muss (Hinweis auf Settings → Kalender); ohne weiteren Versuch.
- [ ] Transientes 503 des Token-Endpoints: einmal automatisch wiederholen; schlägt es erneut fehl, freundliche „Später nochmal versuchen"-Meldung.
- [ ] Google-API nicht erreichbar / Timeout / Rate-Limit: Alice meldet klar, dass der Kalender gerade nicht erreichbar ist; keine erfundenen Termine, keine Erfolgsmeldung ohne tatsächlich ausgeführte Aktion.
- [ ] Alice meldet einen Termin nur dann als angelegt/geändert/gelöscht, wenn die Google-API die Aktion bestätigt hat (kein Halluzinieren von Erfolg, vgl. PROJ-102).

## Edge Cases

- **Mehrere Konten, mehrere Kalender:** Abfragen mergen Termine über alle aktiven Kalender aller Konten; fällt ein Konto aus (Fehler), werden die Termine der übrigen angezeigt und Alice weist darauf hin, dass ein Konto nicht abrufbar war (keine stille Teilantwort).
- **Kalender wird in Google gelöscht/Zugriff entzogen:** Gespeicherte Auswahl verweist auf einen nicht mehr existierenden Kalender → wird beim nächsten Laden des Tabs bereinigt; ist er der Standard, entfällt der Standard. Chat-Anfragen überspringen ihn ohne Fehlerabbruch.
- **Kein aktiver Kalender ausgewählt:** Alice sagt, dass kein Kalender aktiviert ist und verweist auf Settings → Kalender.
- **Mehrdeutige Terminreferenz** („den Termin morgen" bei drei Terminen): Rückfrage statt Raten, auch bei Ändern.
- **Lösch-Rückfrage wird nicht beantwortet / Thema wechselt:** Es wird nichts gelöscht; die offene Löschabsicht verfällt nach dem nächsten, nicht bestätigenden Turn.
- **Ganztägige und mehrtägige Termine:** werden bei Abfragen für jeden betroffenen Tag korrekt berücksichtigt (z. B. Urlaub Mo–Fr erscheint bei „Was steht Mittwoch an?").
- **Zeitzonen / Sommerzeitwechsel:** Termine werden in der Zeitzone des Users gelesen und angelegt; ein Termin am Tag der Zeitumstellung liegt zur korrekten Ortszeit.
- **Whisper-Transkriptionsfehler** (z. B. falsche Uhrzeit): Die Anlege-Bestätigung nennt das Verstandene, damit der User korrigieren kann („Nein, 11 Uhr").
- **Zwei Alice-User verbinden dasselbe Google-Konto:** zwei unabhängige Connections und Kalenderauswahlen (PROJ-86); kein Konflikt.
- **Parallele Änderung in Google während eines Chat-Dialogs** (Termin zwischen Rückfrage und Löschung bereits entfernt/verändert): Alice meldet, dass der Termin nicht mehr gefunden wurde bzw. sich geändert hat, statt blind zu löschen.
- **Rolle verliert Berechtigung, während ein Konto verbunden ist:** Chat und Tab sperren sofort; Connection und Kalenderauswahl bleiben unverändert erhalten.
- **Connection ohne Kalender-Scope, aber Aktivierte Kalender in der Auswahl** (Scope später entzogen/Connection neu aufgebaut): Kalender werden ignoriert, bis der Scope erneut freigegeben ist.

## Technical Requirements

- **Datenhaltung:** Nur Auswahl-Metadaten (Connection, Kalender-ID, aktiv, Standard) in PostgreSQL; keine Termine, keine Beschreibungen, kein lokales Caching von Google-Daten.
- **Sicherheit:** Endpoints und Chat-Aktionen nur mit authentifiziertem, eindeutig identifiziertem User; alle Queries user-scoped; Token nur über den PROJ-86-Service.
- **Performance:** Terminabfrage über mehrere Kalender in der Regel < 3 s Ende-zu-Ende (Google-Roundtrip dominiert); kein HA_FAST-Ziel (< 200 ms gilt nicht).
- **Sprache:** Alice-Antworten in der Nutzersprache; UI-Strings über i18n; Code/Kommentare/Commit-Messages auf Englisch.
- **Zugang:** nur über VPN/Hausnetz (wie PROJ-86).

## Out of Scope (bewusst nicht in PROJ-87)

- Teilnehmer/Einladungen, Videokonferenz-Links, Raumbuchung
- Komplexe Wiederholungsregeln, „diesen und alle folgenden"-Änderungen an Serien
- Proaktive Benachrichtigungen/Push (→ PROJ-104)
- Zeitgesteuerte HA-Befehle (→ PROJ-105)
- Verbesserte Sprecher-Erkennung (→ PROJ-103)
- Andere Kalenderanbieter als Google
- Geteilte/familienweite Kalenderfreigabe zwischen Alice-Usern

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
