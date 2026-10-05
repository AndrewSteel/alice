# PROJ-87: Kalender-Agent

## Status: Architected
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

**Entworfen:** 2026-10-05

### Überblick

PROJ-87 besteht aus vier Bausteinen:

1. **Neuer Service `alice-calendar`** — spricht mit der Google-Calendar-API, löst Zeiträume/Zeitzonen/Wiederholungen auf und bietet sowohl dem Chat als auch dem Settings-Tab eine saubere Schnittstelle. Entscheidung des Users: eigener Container (nicht im Chat-Service, nicht in n8n).
2. **Chat-Anbindung in `alice-chat-stream`** — neue Kalender-Tools für das LLM (anzeigen/anlegen/ändern/löschen), die den neuen Service aufrufen.
3. **Settings-Tab „Kalender"** im Frontend, plus ein kleiner Rollen-Schalter im Admin-Bereich.
4. **Kleine Ergänzungen** an bestehenden Teilen: Rollen-Berechtigung in der Datenbank und eine Rücksprung-Anpassung im PROJ-86-Service (siehe „Offene Punkte").

Kein n8n-Workflow nötig. Kein lokales Cachen von Terminen.

### A) Komponentenstruktur (Settings-Tab)

```
Settings → Tab „Kalender"  (nur sichtbar mit Kalender-Berechtigung)
+-- Meldungsleiste (Ergebnis nach Google-Rückkehr: verbunden / Fehler)
+-- Kopfzeile mit Button „Konto verbinden"
+-- Leerzustand (kein Konto: kurze Erklärung + „Konto verbinden")
+-- Konten-Liste (je Google-Konto eine Karte)
|   +-- Konto-Kopf: E-Mail, Status-Badge (aktiv / Fehler)
|   |   +-- Button „Neu verbinden"   (nur bei Status Fehler)
|   |   +-- Button „Kalender-Zugriff freigeben"   (nur wenn Kalender-Scope fehlt)
|   |   +-- Button „Konto trennen"   → Bestätigungsdialog (mit Warnhinweis bei Aufgaben/Kontakte-Scope)
|   +-- Kalender-Liste (live von Google geladen)
|       +-- Kalender-Zeile: Name, Farbpunkt, „nur lesbar"-Hinweis
|           +-- Schalter „Für Alice aktiv"
|           +-- Auswahl „Standard-Kalender" (nur bei aktiven, beschreibbaren Kalendern)
+-- Ladezustand (Skeleton) / Fehlerzustand je Konto (Google nicht erreichbar)

Settings → Nutzer-Verwaltung (bestehend, admin)
+-- Rollen-Abschnitt (neben dem Timer-Rollen-Abschnitt): Schalter „Kalender nutzen" je Rolle
```

Wiederverwendet: Tabellen-/Dialog-/Badge-/Skeleton-Bausteine und das Layout-Muster der Postfach-Verwaltung; Settings-Shell mit Tab-Guard; i18n-Schicht; das Rollen-Abschnitt-Muster von `TimerRolesSection`.

### B) Datenmodell (einfach beschrieben)

**Neue Tabelle „Kalenderauswahl"** — eine Zeile pro (Google-Verbindung, Google-Kalender), den der User in Alice aktiviert hat:
- Eindeutige ID
- Verbindung (Fremdschlüssel auf die PROJ-86-Tabelle; beim Trennen der Verbindung wird die Auswahl automatisch mit gelöscht)
- Alice-User (Besitzer, denormalisiert, damit „ein Standard-Kalender pro User" per Datenbank erzwungen werden kann)
- Google-Kalender-Kennung
- Aktiv-Flag
- Standard-Flag — höchstens ein Standard pro User, kontenübergreifend
- Zeitstempel

Es werden **keine** Kalendernamen, Termine oder Beschreibungen gespeichert — Namen/Farben/Schreibrechte werden bei jedem Öffnen des Tabs live bei Google geholt. Zeilen für Kalender, die es bei Google nicht mehr gibt, werden beim nächsten Laden des Tabs bereinigt.

**Berechtigung:** ein neues Flag „Kalender nutzen" bei den Rollen-Vorlagen und den Assistenten-Berechtigungen (wie das Timer-Flag aus PROJ-85). Default: admin + user an, guest + child aus; die Funktion, die neuen Usern Rechte aus der Vorlage zuweist, übernimmt das Flag.

**Löschbestätigung (flüchtig):** Löschwünsche werden kurzzeitig (wenige Minuten) im vorhandenen Redis abgelegt — kein neuer Dauer-Speicher.

Alle neuen Tabellen: Row Level Security aktiv, Indizes auf User/Verbindung.

### C) Ablauf-Architektur

**Kalenderliste im Tab laden**
- Tab ruft `alice-calendar` mit dem User-JWT auf → Service holt die Konten (PROJ-86) → holt für jedes Konto mit Kalender-Scope über einen frischen Access-Token die Kalenderliste von Google → mischt die gespeicherte Auswahl (aktiv/Standard) darüber → liefert pro Konto: Status + Kalender. Fällt ein Konto aus, kommen die anderen trotzdem mit Fehlermarkierung zurück.

**Auswahl speichern** (Schalter, Standard setzen): Service schreibt die Auswahl, prüft User-Ownership und die Regeln (erster aktivierter Kalender wird automatisch Standard; Standard nur bei beschreibbaren, aktiven Kalendern; Deaktivieren des Standards entfernt ihn).

**Konto verbinden / Zugriff freigeben / Neu verbinden**: Frontend ruft den bestehenden PROJ-86-Consent-Start mit dem Kalender-Scope auf und leitet zu Google. Nach dem Consent kehrt der Browser zurück zum Tab „Kalender" (siehe Offene Punkte).

**Chat/Sprache — Termine anzeigen**
1. Chat-Service erkennt Absicht, LLM ruft das Tool „Termine abfragen" mit Zeitraum auf.
2. Vorprüfung im Chat-Service: Rolle hat Kalender-Berechtigung? User ist eindeutig identifiziert (Nil-UUID = unbekannter Sprecher → Ablehnung mit Erklärung)?
3. `alice-calendar` holt alle aktiven Kalender des Users, fragt Google pro Kalender parallel ab, löst Serien in einzelne Vorkommen auf, sortiert chronologisch, kürzt nach Regeln (Sprache max. 5, Chat max. 50), liefert strukturiertes Ergebnis inkl. Hinweis, falls ein Konto/Kalender nicht abrufbar war.
4. LLM formuliert die Antwort in der Nutzersprache.

**Anlegen / Ändern**
- Tool-Aufruf mit strukturierten Feldern (Titel, Start/Ende oder Dauer, ganztägig, Ort, Beschreibung, Kalender, Erinnerung, Wiederholung). Service wählt den Kalender (genannt → Standard → sonst Rückfrage-Ergebnis „Kalender nötig" mit Auswahl), validiert (vergangene Zeit → Rückfrage-Ergebnis, schreibgeschützter Kalender → klare Ablehnung, zu komplexe Wiederholung → Ablehnung) und ruft Google.
- Das Ergebnis enthält den von Google bestätigten Termin; nur darauf darf das LLM seine Bestätigung stützen.
- Termin-Identifikation beim Ändern: Service sucht Kandidaten über Titel + Zeitbezug; bei 0 Treffern „nicht gefunden", bei mehreren eine Kandidatenliste für die Rückfrage.
- Serien: Ergebnis „Serie – Umfang nötig"; das LLM fragt den User, dann zweiter Aufruf mit Umfang „nur dieser / ganze Serie".

**Löschen — zweistufig, serverseitig abgesichert**
- Stufe 1 „Löschen vorbereiten": Service identifiziert den Termin eindeutig (sonst Kandidatenliste/Serienumfang-Rückfrage), liefert Titel/Zeit/Kalender zurück plus ein **einmaliges Bestätigungs-Ticket** (kurze Gültigkeit, an User, Termin und Umfang gebunden).
- Alice nennt dem User den Termin und fragt.
- Stufe 2 „Löschen bestätigen": nur mit gültigem Ticket **aus einer früheren Chat-Anfrage** (Ticket, das in derselben Anfrage ausgestellt wurde, wird abgelehnt). Dadurch kann das LLM nicht in einem Zug rückfragen und löschen — das Löschen setzt immer ein „Ja" des Users im nächsten Turn voraus, unabhängig vom Modellverhalten. Vor dem Löschen prüft der Service, ob der Termin noch unverändert existiert (Parallel-Änderung in Google).

**Fehlerbehandlung (alle Pfade)**
- `reauth_required` (409 von PROJ-86): Ergebnis „Verbindung erneuern" → Alice verweist auf Settings → Kalender; Tab zeigt „Neu verbinden".
- Transientes 503: ein automatischer Wiederholungsversuch, dann „Später nochmal versuchen".
- Google nicht erreichbar/Timeout/Rate-Limit: klares Fehlerergebnis; das Tool-Ergebnis enthält nie einen Erfolg ohne Google-Bestätigung.
- Teilausfall (ein Konto von mehreren): Ergebnis der übrigen Konten plus Hinweis.

### D) Tech-Entscheidungen (Begründung)

- **Eigener Service `alice-calendar`** (Entscheidung des Users): saubere Trennung von der Chat-Orchestrierung und von der reinen OAuth-Infrastruktur (PROJ-86). Aufwand: ein Container mehr (Dockerfile, Compose, Makefile-Eintrag, nginx-Route `/api/calendar/`). Die Zeit-/Zeitzonen-/Serienlogik liegt in testbarem Python statt in n8n-Code-Nodes.
- **Kein n8n:** Datums- und Zeitzonenlogik inkl. Wiederholungen ist fehleranfällig und braucht automatisierte Tests; n8n-Code-Nodes sind dafür ungeeignet und zusätzlich langsamer.
- **Token-Abruf über PROJ-86 mit durchgereichtem User-JWT:** Der PROJ-86-Token-Endpoint ist bewusst user-scoped (kein bloßes Connection-ID-Credential). `alice-calendar` reicht daher das JWT des anfragenden Users durch und holt Tokens nur, wenn nötig (kurzlebig im Speicher, nie persistiert).
- **Google Calendar REST direkt (kein SDK):** PROJ-86 nutzt ebenfalls schlanke HTTP-Aufrufe; es werden nur wenige Endpunkte gebraucht (Kalenderliste, Termine lesen/anlegen/ändern/löschen).
- **Serverseitige Lösch-Absicherung statt Prompt-Anweisung:** Ein Prompt allein garantiert nicht, dass das Modell rückfragt; das einmalige Ticket aus früherer Anfrage erzwingt es. Dies deckt die Anforderung „nur nach Rückfrage" verlässlich ab (Hörfehler bei Spracheingabe).
- **Auswahl getrennt von den Verbindungen:** Eigene Tabelle statt Erweiterung der PROJ-86-Tabelle — PROJ-86 bleibt dienstneutral; PROJ-88/89 bekommen später analoge Auswahl-Tabellen. Fremdschlüssel mit Cascade-Löschung erfüllt „Auswahl wird mit der Verbindung gelöscht".
- **Unbekannter Sprecher = kein Zugriff:** Der Chat-Service erkennt den Nil-UUID-Fall bereits für Timer; für Kalender wird er hart abgelehnt (anders als bei Timern kein Rollen-Fallback).
- **Rollen-Flag im bestehenden Permission-System:** gleiches Muster wie `can_use_timers`; kein neues Berechtigungskonzept.
- **Chat-Tools werden nur angeboten, wenn berechtigt:** Das Tool-Schema für das LLM enthält Kalender-Tools nur für Rollen/User mit Berechtigung — spart Tokens und verhindert Fehlaufrufe.
- **Keine Latenz-Optimierung über HA_FAST:** Kalenderanfragen laufen über den normalen LLM-Tool-Pfad (Ziel < 3 s Ende-zu-Ende laut Spec).

### E) Offene Punkte / Änderungen an bestehenden Teilen

1. **Rücksprung nach dem Google-Consent (PROJ-86):** Der Callback leitet heute auf **eine** feste Frontend-URL zurück. Damit der User nach „Konto verbinden" wieder im Tab „Kalender" landet (und später PROJ-88/89 im jeweils eigenen Tab), muss PROJ-86 beim Consent-Start ein Rücksprungziel aus einer festen Liste erlaubter Ziele entgegennehmen und im signierten State mitführen. Kleine, rückwärtskompatible Ergänzung am PROJ-86-Service.
2. **JWT-Herkunft bei Sprache:** Bei Sprachbefehlen kommt der Aufruf über das Speech-Gateway. Zu klären in der Umsetzung: akzeptiert der PROJ-86-Token-Endpoint das vom Gateway für den identifizierten User durchgereichte/ausgestellte JWT, oder braucht es einen eng begrenzten Service-zu-Service-Pfad (nur für die vom Gateway bestätigte User-ID)? Sicherheitsvorgabe bleibt: Kein Zugriff auf fremde Connections.
3. **Berechtigungs-Flag im Frontend:** Der Settings-Guard braucht das neue Flag im bestehenden Berechtigungs-Abruf, damit der Tab nur bei Berechtigung erscheint.
4. **Google-Cloud-Konfiguration (kein Code):** Calendar-API im bestehenden Google-Cloud-Projekt aktivieren; Calendar-Scope (Lesen+Schreiben) im Consent-Screen ergänzen. Da der Scope „sensibel" ist, kann Google eine erneute Verifizierung der Consent-Screen-Einstellungen verlangen.
5. **System-Prompt/Tool-Beschreibungen:** Anweisung an das LLM, Erfolg nur nach bestätigtem Tool-Ergebnis zu melden und bei Rückfrage-Ergebnissen (Kalender nötig, Kandidatenliste, Serienumfang, Löschticket) den User zu fragen.

### F) Neue/geänderte Infrastruktur

- Neuer Service-Ordner `docker/compose/automations/alice-calendar/` (Dockerfile, compose.yml, `.env.example`, Tests), Eintrag in `docker/compose/scripts/Makefile` (STACKS)
- Neue nginx-Location `/api/calendar/` → `alice-calendar` (SSE nicht nötig; normale Timeouts; Rate-Limit-Zone analog Timer)
- Neue Migration (Kalenderauswahl-Tabelle mit RLS + Rollen-Flag in Vorlagen/Berechtigungen + Anpassung der Rechte-Zuweisungsfunktion)
- `alice-chat-stream`: neue Tool-Definitionen + Dispatch + Berechtigungs-/Sprecher-Vorprüfung + Anpassung System-Prompt
- Frontend: neuer Settings-Tab-Eintrag + Route `kalender`, Service-Client, Hook, Komponenten, Rollen-Abschnitt, i18n-Keys (de/en)
- `alice-google-connect`: Rücksprungziel (siehe E.1)

### G) Dependencies (Pakete)

- Backend `alice-calendar`: `fastapi`, `uvicorn` (Service), `httpx` (Google-/PROJ-86-Aufrufe), `asyncpg` oder `psycopg` (je nach Alice-Konvention, PostgreSQL), `redis` (Lösch-Tickets), `pyjwt` + `cryptography` (JWT-Verifikation, RS256), `python-dateutil` bzw. `tzdata` (Zeitzonen/Wiederholungen), `pytest` (Tests)
- Frontend: keine neuen Pakete erwartet (vorhandene shadcn/ui-Bausteine, Tabelle/Switch/Dialog/Badge, i18n)


## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
