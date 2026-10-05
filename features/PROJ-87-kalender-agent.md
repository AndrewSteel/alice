# PROJ-87: Kalender-Agent

## Status: Deployed
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
4. **Google-Cloud-Konfiguration (kein Code):** Calendar-API im bestehenden Google-Cloud-Projekt aktivieren; Calendar-Scopes im Consent-Screen ergänzen. **Entschieden (2026-10-05):**
   - Scopes: `https://www.googleapis.com/auth/calendar.calendarlist.readonly` (Kalenderliste für den Settings-Tab) und `https://www.googleapis.com/auth/calendar.events` (Termine lesen/anlegen/ändern/löschen). Beide „sensitive", nicht „restricted".
   - Verifizierung: **keine** Einreichung bei Google (kein Demo-Video). Die App bleibt „In Production" (Refresh-Tokens laufen nicht ab), beim Consent erscheint die Warnung „App nicht überprüft" (bestätigen über „Erweitert → Weiter zu …"); Obergrenze 100 Nutzer. Verifizierung kann später nachgeholt werden, wenn die Warnung stört.
   - Google-Cloud-Projekt bleibt bestehen (nur umbenannt); OAuth-Client, Redirect-URI und `.env` von `alice-google-connect` unverändert.
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


## Implementation Notes (Backend + Frontend, 2026-10-05)

### Gebaut
- **Migration `sql/migrations/071-proj87-calendar-agent.sql`:** Tabelle `alice.calendar_selections` (RLS, Indizes, Trigger). Zusammengesetzter FK `(connection_id, user_id)` → `alice.google_connections(id, user_id)` mit `ON DELETE CASCADE` (dafür neuer Unique-Constraint `google_connections_id_user_uniq`). Damit ist der Auswahl-Besitzer garantiert der Connection-Besitzer. Partieller Unique-Index „ein Standard pro User“; CHECK „Standard nur wenn aktiv“. Flag `can_use_calendar` in `permissions_assistant` + `role_templates` (admin/user an, guest/child aus) inkl. Backfill und angepasster `init_user_permissions()`. Gegen frischen Postgres (init-schema + alle Migrationen) verifiziert, idempotent.
- **Neuer Service `docker/compose/automations/alice-calendar/`** (FastAPI, Port 8009, asyncpg, httpx, Redis):
  - `timeutil.py` — Zeitraum-Auflösung (heute/morgen/übermorgen/diese Woche = heute bis So/nächste Woche/Datum/nächster), Google-Zeitparsing, Start/Ende inkl. ganztägig/mehrtägig/über Mitternacht, DST-sicher (lokale Uhrzeit + `timeZone`), einfache Wiederholung → RRULE (daily/weekly+Wochentage/monthly/yearly, until/count; alles andere → Ablehnung), Ausrichtung des ersten Vorkommens auf den ersten genannten Wochentag.
  - `google.py` — PROJ-86-Client (User-JWT durchgereicht, 503 genau einmal wiederholt, 409 → reauth) + Calendar-REST (calendarList, events list/get/insert/patch/move/delete) mit Fehlerabbildung (reauth / nicht erreichbar inkl. Rate-Limit / nicht gefunden / abgelehnt).
  - `agent.py` — Tool-Logik (Abfragen über alle aktiven Kalender aller Konten, Teilausfall mit Hinweis, Sprache max. 5 + Rest, Chat max. 50; Anlegen mit Kalenderwahl genannt → Standard → Rückfrage, Vergangenheits-Rückfrage, schreibgeschützt → Ablehnung; Ändern mit Kandidatensuche/Rückfrage, Serien „nur dieser/ganze Serie“, Kalenderwechsel; zweistufiges Löschen) + Settings-Tab-Übersicht (Live-Kalenderliste, Bereinigung verschwundener Kalender, Standard bei schreibgeschützt entfernt).
  - `tickets.py` — Lösch-Tickets in Redis (5 min), gebunden an User + Session + Turn; einlösbar **nur im unmittelbar folgenden Turn** (gleicher Turn → abgelehnt ohne Verbrauch; späterer Turn → verfallen). Etag-Vergleich vor dem Löschen erkennt Parallel-Änderungen.
  - Endpoints: `GET /calendar/accounts`, `PUT /calendar/selection` (403 ohne Berechtigung), `GET/PUT /calendar/admin/roles` (Admin-Rolle frisch aus DB, nicht aus JWT), `POST /internal/turn`, `POST /internal/tools/{tool}` (nur Docker-Netz, nicht über nginx).
- **`alice-chat-stream`:** neues Modul `app/calendar_tools.py` (5 Tools `calendar_list_events/create_event/update_event/delete_event/confirm_delete`), Einbindung in `streaming.py` (Tools nur bei Berechtigung angeboten, Dispatch an alice-calendar) und `main.py` (nur im LLM-Pfad, HA_FAST unberührt). `memory.count_user_messages()` liefert die Turn-Nummer. Neue Env `CALENDAR_URL` (leer = Feature aus).
- **`alice-google-connect` (E.1):** `POST /google/connect/start` akzeptiert optional `return_to` aus fester Allowlist (`kalender`); wird im signierten State mitgeführt, der Callback leitet nach `/settings/kalender` (gleiche Origin wie `FRONTEND_REDIRECT_URL`). Ohne `return_to` bzw. bei ungültigem State unverändertes Verhalten. Fremde Ziele → 422 (kein Open Redirect).
- **`alice-auth`:** `GET /auth/permissions` liefert zusätzlich `can_use_calendar` (aus `permissions_assistant`) für den Settings-Guard (E.3).
- **Infra:** Makefile-STACKS, nginx `location ^~ /api/calendar/` (eigene Zone `calendar_limit` 60r/m), `.gitignore` (`alice-calendar/.env`), `.rsyncignore` (`**/.venv/`, `**/.pytest_cache/` — sonst würden lokale Test-venvs auf den Server synchronisiert).
- **Frontend:** Route `/settings/kalender` (Tab-Guard `can_use_calendar`), `CalendarSection` (Konto-Karten, Status-Badge, Neu verbinden / Kalender-Zugriff freigeben / Konto trennen, Schalter „Für Alice aktiv“, „Als Standard“, „nur lesbar“, Leerzustand, Rückmeldung nach Google-Rückkehr), `DisconnectGoogleDialog` (Warnung bei weiteren Scopes), `CalendarRolesSection` in der Nutzerverwaltung, Service `services/calendar.ts`, Hook `useCalendarAccounts`, i18n de/en.

### Entscheidungen / Abweichungen
- **E.2 geklärt:** Das Speech-Gateway stellt ein reguläres RS256-JWT mit der `user_id` des erkannten Sprechers aus (Nil-UUID bei unbekanntem Sprecher). Dieses JWT wird unverändert bis zum PROJ-86-Token-Endpoint durchgereicht — kein Service-zu-Service-Pfad nötig. Da das Gateway-JWT immer `role=user` behauptet, wird die Kalender-Berechtigung **immer frisch aus der DB** gelesen.
- **Offene Rückfragen über Turns hinweg:** `alice-chat-stream` gibt Tool-Ergebnisse nicht in die History des nächsten Turns. Damit Lösch-Ticket und `event_ref`s einer Rückfrage nicht verloren gehen, speichert alice-calendar die letzte offene Rückfrage (confirm_delete, ambiguous, needs_scope, needs_calendar, confirm_past) pro User+Session in Redis; `POST /internal/turn` liefert sie für genau den Folgeturn, chat-stream hängt sie an den System-Prompt.
- **Ohne Berechtigung / unbekannter Sprecher:** Es werden keine Kalender-Tools angeboten; stattdessen erklärt ein System-Prompt-Hinweis dem LLM, warum es ablehnen soll (die Tool-Endpoints lehnen zusätzlich serverseitig ab).
- **Serien ändern (ganze Serie):** nur Uhrzeit/Dauer/Titel/Ort/Beschreibung/Erinnerung/Kalender (gleiches Konto). Datumsverschiebung der ganzen Serie wird abgelehnt (würde das BYDAY-Muster zerstören) — Hinweis auf „nur diesen Termin“ bzw. Google.
- **Kalenderwechsel über Kontogrenzen:** Einzeltermine per Kopie + Löschen; Serien nicht.
- **„Diese Woche“** = heute bis Sonntag (vergangene Tage der Woche nicht relevant).
- **Inline-Style:** nur für den Farbpunkt des Kalenders (Farbe kommt zur Laufzeit von Google, nicht als Tailwind-Klasse ausdrückbar).

### Tests
- alice-calendar: 103 Tests (90 Unit mit Fake-Google/DB/Redis + 13 Integration gegen echten Postgres mit RS256-JWTs).
- alice-chat-stream: 221 Tests grün (13 neue für `calendar_tools`), bestehende unverändert grün.
- alice-google-connect: Rücksprungziel per Skript gegen die echte App verifiziert (422 bei fremdem Ziel, Redirect nach `/settings/kalender`, Legacy unverändert, manipulierter State → Default-URL).
- Frontend: `tsc --noEmit` und `next build` sauber.

### Deployment-Hinweise (für /deploy)
- Reihenfolge: Migration 071 → `alice-calendar` (`.env` aus `.env.example`, Werte wie chat-stream: `POSTGRES_DSN`, Redis) bauen/starten → `alice-google-connect`, `alice-auth`, `alice-chat-stream` (`CALENDAR_URL=http://alice-calendar:8009` in `.env`) neu bauen → **danach** nginx reload (nginx löst `alice-calendar` beim Laden auf) → Frontend deployen.
- Google Cloud: Calendar API aktivieren, Scopes `calendar.calendarlist.readonly` + `calendar.events` im Consent-Screen ergänzen (siehe E.4).

## QA Test Results

**Tested:** 2026-10-05
**Umgebung:** lokal — alice-calendar als gebautes Docker-Image (`alice-calendar:qa`) in eigenem Netz mit Postgres 16 (init-schema + Migrationen bis 071), Redis 7 und Stub für alice-google-connect; Calendar-Aufrufe gegen das **echte** googleapis.com (ungültiges Token → reale 401-Pfade). Frontend: statischer `next build`-Export hinter zustandsbehaftetem Mock-Backend, Chrome (hell + dunkel, 1440 / 768 / 375 px). Kein echtes LLM und kein echtes Google-Konto lokal verfügbar → LLM-Tool-Nutzung und Live-Google-CRUD nur über Unit-/Integrationstests mit Fakes abgedeckt (Live-Test beim Deploy).
**Tester:** QA Engineer (AI)

### Automatisierte Tests
- alice-calendar: **103/103** grün (90 Unit + 13 Integration gegen echten Postgres, RS256-JWTs)
- alice-chat-stream: **221/221** grün (inkl. 13 neue `calendar_tools`-Tests; Baseline vor der Änderung 208/208)
- Container-Red-Team-Skript gegen das laufende Image: **31/31** Checks bestanden
- Frontend: `tsc --noEmit` + `next build` sauber (kein Vitest/Playwright im Projekt eingerichtet)

### Acceptance Criteria Status

#### Settings-Tab „Kalender“
- [x] Tab nur mit Kalender-Berechtigung sichtbar; ohne Flag ausgeblendet, Direktaufruf `/settings/kalender` → Redirect auf `/settings/profil` (Browser verifiziert)
- [x] Alle Konten mit E-Mail, Status und Kalendern; „Konto verbinden“ startet Consent mit beiden Kalender-Scopes + `return_to=kalender`; nach Rückkehr Meldung + aktualisierte Liste, URL-Parameter entfernt
- [x] Konto ohne Kalender-Scope: Hinweis + „Kalender-Zugriff freigeben“ (Re-Consent; PROJ-86 vereinigt Scopes auf derselben Connection)
- [x] Kalender live geladen (Name, Farbpunkt, „nur lesbar“), Schalter „Für Alice aktiv“; nur Auswahl gespeichert
- [ ] BUG-1: Standard-Kalender — Eindeutigkeit, Wechsel und „Deaktivieren entfernt Standard ohne Nachfolger“ korrekt; **aber** wird zuerst ein schreibgeschützter Kalender aktiviert, wird der danach aktivierte erste beschreibbare Kalender nicht automatisch Standard
- [x] Schreibgeschützte Kalender aktivierbar, kein „Als Standard“-Button, Server lehnt Standard ab (400)
- [x] „Konto trennen“: Dialog mit Warnung bei weiteren Scopes, DELETE an PROJ-86, Auswahl per Cascade gelöscht (DB verifiziert)
- [x] Status `error` / Google-401: rotes Badge + „Neu verbinden“
- [x] Alle UI-Texte über i18n (de/en)
- [x] Leerzustand mit Erklärung + „Konto verbinden“
- [ ] BUG-4: Erfolgsmeldung (grün) im hellen Theme kaum lesbar; Status-Badges im hellen Theme kontrastschwach

#### Chat/Sprache — Anzeigen
- [x] heute / morgen / übermorgen / diese Woche / nächste Woche / Datum(-bereich) / nächster Termin (Unit-Tests `resolve_range`, `list_events`)
- [x] Alle aktiven Kalender aller Konten gemergt
- [x] Chronologisch, ganztägig zuerst, Ort; Kalendername nur bei > 1 aktivem Kalender
- [x] Sprache max. 5 + Restanzahl; Chat max. 50 + Kürzungshinweis (Kanal aus `source` — alle Gateway-Pfade senden `esphome*`)
- [x] Ohne Treffer klare Aussage; bei Totalausfall nie „keine Termine“
- [x] Zeitzone des Users (Default Europe/Berlin), DST-Tag korrekt
- [x] Serien als Einzelvorkommen (`singleEvents=true`)

#### Chat/Sprache — Anlegen
- [x] Titel + Datum/Uhrzeit, optional Dauer/Ort/Beschreibung/Kalender/Erinnerung/Wiederholung
- [x] Defaults 60 min, ohne Uhrzeit ganztägig, Standard-Kalender; ohne Standard Rückfrage mit beschreibbaren Kalendern
- [x] Genannter Kalender („Familienkalender“ → „Familie“), unbekannt/mehrdeutig → Rückfrage
- [x] Erinnerung als Popup-Override
- [x] Einfache Wiederholung inkl. Wochentage/Ende; komplexe Regeln abgelehnt
- [ ] BUG-3: Ablehnung komplexer Wiederholungen enthält keinen Hinweis auf Google (Spec: „mit Hinweis auf Google“)
- [x] Bestätigung nur aus Google-Antwort (Titel, Datum/Uhrzeit, Kalender)
- [x] Vergangenheit → Rückfrage `confirm_past`
- [x] Schreibgeschützter Kalender → klare Ablehnung
- [ ] BUG-2: nicht-numerische Zahlwerte (`duration_minutes`, `new_duration_minutes`) führen zu `internal_error` („später nochmal versuchen“) statt `invalid_input`

#### Chat/Sprache — Ändern
- [x] Titel/Datum/Uhrzeit/Dauer/Ort/Beschreibung/Erinnerung/Kalender änderbar (Dauer bleibt bei Zeitverschiebung erhalten)
- [x] Identifikation über Titel/Zeitbezug; mehrere → Kandidatenliste mit `event_ref`; keiner → „nicht gefunden“
- [x] Ohne Rückfrage, Bestätigung der neuen Fassung
- [x] Serie → „nur dieser / ganze Serie“, Umfang korrekt (Instanz- vs. Master-Patch)

#### Chat/Sprache — Löschen
- [x] Nur nach Rückfrage; Ticket nur im **folgenden** Turn derselben Session einlösbar (gleicher Turn abgelehnt ohne Verbrauch, späterer Turn verfallen, andere Session/User abgelehnt, Doppel-Einlösung abgelehnt)
- [x] Mehrere Treffer → erst Auswahl, dann Bestätigung
- [x] Serie → Umfangsfrage, Bestätigung nennt Umfang

#### Berechtigung, Zuordnung, Fehler
- [x] Rollen-Flag (admin/user an, guest/child aus), im Admin-Bereich editierbar (Browser + API), per-User-Flag synchron
- [x] Ohne Berechtigung: Tab-Endpoints 403, Tools `forbidden`, System-Prompt-Hinweis zur Ablehnung
- [x] Unbekannter Sprecher (Nil-UUID): keine Aktion, Tab 403, Prompt-Hinweis; Gateway-`role=user` wird ignoriert (child via Gateway-Token → forbidden)
- [x] Nur eigene Kalender (event_ref fremder Kalender → not_found; Cross-User-Auswahl → kein Datensatz; Admin-Rolle aus DB statt JWT)
- [x] `reauth_required` → Hinweis auf Settings → Kalender, kein weiterer Versuch
- [x] Transientes 503 genau einmal wiederholt, danach „später nochmal“
- [x] Google nicht erreichbar/Timeout/Rate-Limit → klare Fehlermeldung, keine erfundenen Termine
- [x] Erfolg nur bei Google-Bestätigung (alle Fehlerpfade ohne `status: created/updated/deleted`)

### Edge Cases Status
- [x] Mehrere Konten, eines fällt aus → Teilergebnis + `warnings`
- [x] Kalender in Google gelöscht → Tab bereinigt Auswahl (Standard entfällt), Chat überspringt ohne Fehler
- [x] Kein aktiver Kalender → Verweis auf Settings
- [x] Mehrdeutige Referenz → Rückfrage (auch beim Ändern)
- [x] Lösch-Rückfrage unbeantwortet → verfällt nach dem nächsten nicht bestätigenden Turn
- [x] Ganztägig/mehrtägig → erscheint am Mitteltag
- [x] Zeitzone/Sommerzeit → lokale Uhrzeit bleibt erhalten
- [x] Whisper-Fehler → Bestätigung nennt Verstandenes
- [x] Zwei Alice-User, gleiches Google-Konto → unabhängige Connections/Auswahl (Composite-FK)
- [x] Parallele Änderung/Löschung in Google → `event_changed` / `event_gone`, nichts gelöscht
- [x] Rolle verliert Berechtigung → sofort gesperrt, Daten bleiben
- [x] Connection ohne Kalender-Scope mit alter Auswahl → ignoriert, kein Token-Abruf
- [x] Zusätzlich: offene Rückfrage geht nicht verloren, obwohl Tool-Ergebnisse nicht in der History landen; vorzeitiger Same-Turn-Confirm löscht sie nicht

### Security Audit Results
- [x] Authentifizierung: ohne Token / Basic / abgelaufen / HS256-gefälscht / `alg=none` → 401 (Tab, `/internal/turn`, `/internal/tools`)
- [x] Autorisierung: User-ID ausschließlich aus JWT; Berechtigung + Admin-Rolle frisch aus DB (gefälschter `role=admin`-Claim → 403); Auswahl kann per Composite-FK nur auf eigene Connections zeigen
- [x] Token-Weitergabe: Google-Tokens nur über PROJ-86 mit dem User-JWT; nie persistiert oder ausgegeben
- [x] Lösch-Tickets: zufällig (128 bit), an User+Session+Turn gebunden, atomar verbraucht
- [x] Open Redirect: `return_to` nur aus Allowlist (fremde URL → 422); Ziel nur aus verifiziertem State
- [x] Interne Tool-Routen nicht über nginx erreichbar (Rewrite erzeugt immer `/calendar/...`)
- [x] Input-Validierung: ungültige UUID/fehlende Flags → 422, SQLi-artige IDs ohne 5xx (parametrisierte Queries), Längenlimits, XSS-Strings nur als React-Text gerendert
- [x] Rate-Limit: nginx-Zone `calendar_limit` 60r/m für `/api/calendar/`
- [x] Keine Secrets in Logs/Responses (Container-Logs geprüft)

### Bugs Found

#### BUG-1: Erster beschreibbarer Kalender wird nicht automatisch Standard, wenn vorher ein schreibgeschützter aktiviert wurde
- **Severity:** Medium
- **Steps to Reproduce:** 1. Tab „Kalender“, nichts aktiv. 2. „Feiertage“ (nur lesbar) aktivieren. 3. „Privat“ aktivieren. Expected: „Privat“ wird Standard (erster aktivierter Kalender, der Standard sein kann). Actual: kein Standard → Alice fragt bei jedem Anlegen nach dem Kalender. Ursache: `db.set_selection` prüft „gibt es schon irgendeinen aktiven Kalender“ statt „gibt es schon einen Standard“. Reproduziert gegen echten Postgres.
- **Priority:** Fix before deployment

#### BUG-2: Nicht-numerische Zahlwerte führen zu `internal_error`
- **Severity:** Low
- **Steps to Reproduce:** `create_event` mit `duration_minutes: "abc"` (bzw. `update_event` mit `new_duration_minutes: "lang"`). Expected: `invalid_input` mit Feldhinweis. Actual: `internal_error` + Traceback im Log; Alice würde „später nochmal versuchen“ sagen. Ursache: ungeschütztes `int()` in `agent.create_event` / `_time_patch`.
- **Priority:** Fix before deployment

#### BUG-3: Ablehnung komplexer Wiederholungen ohne Hinweis auf Google
- **Severity:** Low
- **Steps to Reproduce:** `create_event` mit `recurrence: {freq: "monthly", interval: 2}`. Expected: Fehler mit Verweis auf Google (Spec). Actual: generisches `invalid_input` „Nur einfache Wiederholungen … — korrigiere den Aufruf oder frage den Nutzer nach“.
- **Priority:** Fix before deployment

#### BUG-4: Erfolgsmeldung im hellen Theme kaum lesbar
- **Severity:** Medium
- **Steps to Reproduce:** Helles Theme, Konto verbinden → Rückkehr. Expected: gut lesbare grüne Meldung. Actual: `text-green-200` auf `bg-green-900/30` → hellgrün auf hellgrün. Status-Badges („Aktiv“/„Fehler“) ebenfalls kontrastschwach (gleiches Muster wie bestehende Postfach-Badges).
- **Priority:** Fix before deployment

### Summary
- **Acceptance Criteria:** 41/45 Prüfpunkte bestanden (4 mit Bug)
- **Bugs Found:** 4 total (0 critical, 0 high, 2 medium, 2 low)
- **Security:** Pass
- **Production Ready:** YES nach Definition (keine Critical/High) — Empfehlung: die 4 kleinen Bugs vor dem Deploy fixen und nachtesten
- **Nicht lokal testbar:** echtes LLM-Verhalten mit den Tools und Live-CRUD gegen ein echtes Google-Konto → beim Deploy als Live-Test durchführen

### Re-QA nach Bugfix (2026-10-05)

Alle 4 Bugs behoben und unabhängig nachgetestet (neu gebautes Image, frischer Frontend-Build):

| Bug | Fix | Verifikation |
|-----|-----|--------------|
| BUG-1 (Medium) | `db.set_selection`: Aktivieren eines beschreibbaren Kalenders macht ihn zum Standard, solange der User **keinen Standard** hat (statt „noch kein aktiver Kalender“). „Standard deaktivieren → kein automatischer Nachfolger unter den verbleibenden“ bleibt erhalten. | Neuer Integrationstest gegen echten Postgres (nur-lesbar zuerst → „Privat“ wird Standard, weiterer Kalender nicht); bestehende Standard-Tests weiter grün |
| BUG-2 (Low) | `_int_arg()` für `duration_minutes` / `new_duration_minutes` → `InputError` | Container: `invalid_input` „duration_minutes muss eine ganze Zahl sein“, kein Traceback im Log; Unit-Test |
| BUG-3 (Low) | Eigener Fehlercode `unsupported_recurrence` mit Anweisung, auf Google Kalender zu verweisen und nichts anzulegen | Container + Integrationstest: Meldung enthält „Google“ |
| BUG-4 (Medium) | Theme-abhängige Klassen (`bg-green-50 text-green-800` / `dark:…`) für Meldungen und Status-/Standard-Badges | Browser hell + dunkel: gut lesbar |

- alice-calendar: **106/106** grün (+3 Regressionstests); alice-chat-stream **221/221**; Container-Red-Team **31/31**; `tsc` + `next build` sauber.
- Keine neuen Bugs, keine Regressionen.
- **Acceptance Criteria:** 45/45 Prüfpunkte bestanden
- **Bugs offen:** 0
- **Production Ready:** **YES** — Status **Approved**. Offen für /deploy: Live-Test mit echtem Google-Konto und echtem LLM (Anlegen/Ändern/Löschen per Chat und per Voice PE, Rückfrage-Flows, unbekannter Sprecher).

## Deployment

**Deployed:** 2026-10-05 (durch den User, manuell)

- Migration `071-proj87-calendar-agent.sql` eingespielt (nur die erwarteten `NOTICE`s der idempotenten `DROP … IF EXISTS` beim Erstlauf).
- Container neu gebaut/gestartet: `alice-calendar` (neu), `alice-chat-stream`, `alice-auth`, `alice-google-connect`; nginx neu gestartet; Frontend deployed.
- Konfiguration: `alice-calendar/.env` (inkl. `REDIS_PASSWORD` wie chat-stream), `CALENDAR_URL=http://alice-calendar:8009` in `alice-chat-stream/.env`; Google Cloud: Calendar API + Scopes `calendar.calendarlist.readonly` und `calendar.events`.
- **Live-Test bestanden (2026-10-05):** Settings-Tab (Konto verbinden, OAuth-Rücksprung, Kalenderauswahl, hell/dunkel), Termine anlegen, abfragen (einzelner Tag und ganze Woche) und löschen (zweistufig mit Rückfrage) — jeweils über WebApp **und** Voice PE.
- Während des Live-Tests gefundene und behobene Punkte: siehe „Nachlauf Live-Test 1–5“ (HA-Fast-Path-Abgrenzung, erzwungene Tool-Nutzung je Absicht, keine Tools nach Rückfrage, Token-Limit + Wiederholungsbremse, Vorlagen-Antworten statt LLM-Formulierung, Text in erzwungener Runde verworfen, erweiterte Absichtserkennung, `TT.MM.JJJJ`-Datumsformat).
- Offen / nicht live geprüft: Ändern von Terminen und Serien-Abläufe (nur diesen / ganze Serie) per Sprache, Kalenderwechsel über Kontogrenzen, Mehr-Konten-Teilausfall — durch Unit-/Integrationstests abgedeckt.

### Nachlauf Live-Test 2026-10-05 (nach Deploy durch den User)

Settings-Tab, OAuth-Rücksprung, Kalenderauswahl und Darstellung (hell/dunkel) live bestätigt. Im Chat drei Probleme gefunden (Analyse über `alice.messages` + Container-Logs):

1. **HA_FAST fängt Kalenderanfragen ab:** „Welche Termine habe ich morgen?“ wurde von Weaviate dem Timer-Intent zugeordnet („Auf wie viele Minuten soll ich den Timer stellen?“), ein nachfolgendes „Nein“ einem Schalter-Intent. **Fix (alice-chat-stream):** Nachrichten mit Kalenderbezug (Termin/Kalender/„was steht … an“/„was habe ich … vor“) und die direkte Antwort auf eine offene Kalender-Rückfrage umgehen den HA-Fast-Path.
2. **LLM ruft kein Tool auf und erfindet den Erfolg:** „Termin … erstellt“ ohne einen einzigen Aufruf bei alice-calendar (Modell `qwen3-vl-30b`; laut DB generell selten Tool-Aufrufe). **Fix:** Bei Kalenderanfragen bekommt das LLM in der ersten Runde nur die Kalender-Tools mit `tool_choice: "required"` (gegen den produktiven llama.cpp verifiziert, auch mit Thinking). Antwort auf eine offene Rückfrage erzwingt ebenfalls einen Kalender-Aufruf — außer bei Verneinung; auf die Lösch-Rückfrage nur bei klarem „Ja“. Zusätzlich akzeptiert alice-calendar Datumsangaben auch als `TT.MM.JJJJ` (Modell lieferte dieses Format trotz Schema).
3. **Redis:** `REDIS_PASSWORD` in `alice-calendar/.env` leer → „Authentication required“; Lösch-Tickets/offene Rückfragen funktionierten nicht. **Fix: Konfiguration** (Wert wie in `alice-chat-stream/.env`).

Tests: alice-chat-stream 245/245 (+24), alice-calendar Unit 98/98 (+5 Datumsformat). Neu zu deployen: `alice-chat-stream`, `alice-calendar`.

### Nachlauf Live-Test 2 (2026-10-05, Voice PE + WebApp)

Anlegen per Voice und WebApp funktioniert, Löschen per WebApp (Ticket → „Ja“ → gelöscht) ebenfalls. Gefunden (Analyse `alice.messages.tool_calls`):

1. **Falsches erzwungenes Tool:** Voice „Lösche den Termin …“ → Modell wählte im erzwungenen Kalender-Schritt `calendar_list_events` statt `calendar_delete_event` und stellte die Ja/Nein-Frage selbst (ohne Ticket); das folgende „Ja, löschen“ wurde ohne Tool-Aufruf mit „gelöscht“ beantwortet (Termin blieb bestehen). **Fix:** Die erste Runde erzwingt jetzt genau **ein** Tool nach erkannter Absicht (löschen/absagen → delete, verschieben/ändern/umbenennen → update, anlegen/eintragen/erstellen → create, sonst list). Antwort auf eine offene Rückfrage erzwingt das Tool dieser Rückfrage, nach Lösch-Rückfrage + „Ja“ ausschließlich `calendar_confirm_delete`.
2. **Bestätigung im selben Request + Endlosschleife:** WebApp „Lösche den morgigen Termin …“ → `delete_event` (Ticket) und direkt danach `confirm_delete` im selben Request → korrekt abgelehnt (`ticket_same_turn`), Modell behauptete dennoch „gelöscht“ und wiederholte Text + Tool-Aufruf bis zum Abbruch. **Fix:** Sobald ein Kalender-Tool eine Rückfrage liefert, bekommen die restlichen Runden dieses Requests keine Tools mehr (Modell muss antworten); parallele Aufrufe in derselben Runde werden mit `await_user_answer` abgewiesen, ohne alice-calendar zu erreichen.
3. **Zu textlastig (Voice + WebApp), „single/series“-Fachbegriffe, unnötige Rückfragen zu Erinnerung/Kalender:** Prompt-Regeln „ein bis zwei Sätze, keine internen Begriffe, keine Rückfragen zu nicht genannten optionalen Angaben“, für Voice zusätzlich „keine Listen/Markdown/Emojis, Uhrzeiten gesprochen“; Tool-Anweisungen in alice-calendar gekürzt und nutzerneutral formuliert; Serien-Frage nur bei `needs_scope`.

Tests: alice-chat-stream 255/255, alice-calendar Unit 98/98. Neu zu deployen: `alice-chat-stream`, `alice-calendar`.

### Nachlauf Live-Test 3 (2026-10-05, Voice PE Dauerschleife)

- Test lief noch gegen den **alten** alice-chat-stream-Container (neu erstellt erst 18:06:48 UTC, Test 18:02–18:05) — die Fixes aus Live-Test 2 waren noch nicht aktiv. Stufe 1 (`delete_event` → Ticket) funktionierte; beim „Ja.“ kein Tool-Aufruf.
- **Dauerschleife:** Das Modell wiederholte einen Satz 14 799 Tokens / 93 s lang; das Gateway las jeden Satz vor, bis der Voice PE vom Strom getrennt wurde. Ursache unabhängig vom Kalender: alice-chat-stream setzte **kein Token-Limit**. **Fix:** `max_tokens` pro LLM-Runde (`LLM_MAX_TOKENS`, Default 4096 inkl. Reasoning) + Wiederholungsbremse (derselbe vollständige Satz ≥ 15 Zeichen dreimal in Folge → Stream sofort beendet, keine Tool-Ausführung, Warnung im Log).
- Gegen den produktiven llama.cpp verifiziert: `tool_choice: "required"` mit nur `calendar_confirm_delete` wird auch **im Streaming** eingehalten (Tool-Aufruf mit korrektem Ticket aus der offenen Rückfrage, kein Text).

Tests: alice-chat-stream 258/258. Neu zu deployen: `alice-chat-stream`.

### Nachlauf Live-Test 4 (2026-10-05, Antworttexte)

Löschen per Voice PE funktioniert (Rückfrage → „Ja“ → in Google gelöscht). Weiterhin zu textlastig: Das Modell ignorierte die Kürze-Regeln, fragte bei einem Einzeltermin nach „einzelnen Termin oder ganze Serie“, las die Anfrage vor und bestätigte die Löschung doppelt („ich lösche …“ + „wurde erfolgreich gelöscht“).

**Entscheidung:** Kalender-Ergebnisse formuliert nicht mehr das LLM, sondern `alice-chat-stream/app/calendar_replies.py` per Vorlage aus dem strukturierten alice-calendar-Ergebnis (de/en gemäß Nutzersprache `sprache`, unbekannt → de wie die LLM-Sprachanweisung). Nach einem Kalender-Ergebnis endet der Request ohne weitere LLM-Runde; nur korrigierbare Eingabefehler (`invalid_input`) gehen zurück ans LLM. Voice: gesprochene Uhrzeiten („um 9 Uhr 20“), keine Listen, Auswahl auf 3 Kandidaten begrenzt; Chat: ab 4 Terminen Liste mit Ort/Kalender. Nach abgeschlossenen Aktionen `conversation_end` (Voice-Session endet wie bei HA-Befehlen), bei Rückfragen bleibt sie offen.

Beispiele: „Soll ich „Test“ morgen um 10 Uhr löschen?“ → „Ich habe den Termin „Test“ gelöscht.“; „Morgen hast du 2 Termine: um 9 Uhr 20 Fußpflege und um 10 Uhr Test.“

Damit ist auch AC „Erfolg nur bei Google-Bestätigung“ strukturell abgesichert: Die Erfolgsmeldung entsteht ausschließlich aus `status created/updated/deleted`.

Tests: alice-chat-stream 286/286 (+ `test_calendar_replies.py`, End-to-End `test_streaming_calendar.py` mit Fake-LLM). Neu zu deployen: `alice-chat-stream`.

### Nachlauf Live-Test 5 (2026-10-05, „Setze einen Termin …“)

„Setze einen Termin für Mittwoch um 11 Uhr … Zahnarzt“ wurde nicht als Anlegen erkannt („setzen“ fehlte) → erzwungen wurde `calendar_list_events`; das Modell schrieb im erzwungenen Schritt zusätzlich eine erfundene Erinnerungs-Rückfrage, die vorgelesen wurde; danach Terminliste per Vorlage + `conversation_end` (korrekt für eine Abfrage) → keine Antwortmöglichkeit, nichts angelegt.

**Fix (alice-chat-stream):** Text, den das Modell in einer erzwungenen Tool-Runde schreibt, wird verworfen (die Antwort kommt aus der Vorlage); liefert die Runde wider Erwarten keinen Tool-Aufruf, antwortet eine freie Folgerunde. Absichtserkennung erweitert (setzen, notieren, vormerken, merken, buchen, „Titel“, „Dauer“); ohne erkennbares Verb wählt das Modell zwischen Anlegen und Anzeigen, nur echte Fragen erzwingen reines Anzeigen.

Tests: alice-chat-stream 296/296. Neu zu deployen: `alice-chat-stream`.
