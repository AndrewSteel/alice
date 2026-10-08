# PROJ-88: Aufgaben-Agent

## Status: Verworfen
**Created:** 2026-10-08
**Last Updated:** 2026-10-08

> **Verworfen am 2026-10-08 → ersetzt durch PROJ-106 (Aufgaben- & Listen-Verwaltung, lokal).**
> Grund: starke Überschneidung mit PROJ-100 (HA-Todo-Listen) → Zuordnungs-Rückfragen; die Google-Tasks-API speichert nur ein Datum (keine Uhrzeit, keine Frist); HA-Todo kennt weder Frist, Erinnerung, Wiederholung noch private Listen.
> Geprüfte Optionen: (1) PROJ-88 + PROJ-100 getrennt, (2) ein Agent über Google + HA (Listenregister), (3) eigene lokale Lösung in Alice, (4) nur über HA (Local To-do + HA-Integration Google Tasks). **Entscheidung: Option 3** — Aufwand kein Hindernis, Zugriff ohne VPN ohnehin nicht möglich, keine HA-Spiegelung nötig. PROJ-100 ist ebenfalls verworfen.
> Dieser Entwurf bleibt als Vorlage für das PROJ-106-Interview erhalten (insb. Abschnitt „Antwortverhalten" mit den PROJ-87-Lehren, Lösch-Rückfrage, Testsätze).

## Dependencies
- Requires: PROJ-86 (Google-API-Infrastruktur) — OAuth-Flow, Connection-Verwaltung, Token-Abruf (`/token` kann ein transientes, retrybares 503 liefern; 409 `reauth_required` bei widerrufener Verbindung)
- Requires: bestehendes Rollen-/Permission-System (`alice.role_templates` / `alice.permissions_assistant`) — neue Aufgaben-Berechtigung pro Rolle
- Requires: Speaker-ID im `alice-speech-gateway` (Sprecher-Zuordnung zu einem User; Verbesserung → PROJ-103)
- Vorbild: PROJ-87 (Kalender-Agent) — Settings-Tab-Muster (Konten-Liste, Scope-Erweiterung, Trennen, Standard-Auswahl), Chat-Verhalten und **die im PROJ-87-Live-Test gewonnenen Erkenntnisse** (siehe „Antwortverhalten")
- Abgrenzung: PROJ-100 (Todo-Listen-Agent, Home-Assistant-Listen wie Einkaufsliste) — **nicht** Teil dieses Features

## Kontext

Der Aufgaben-Agent gibt Alice Zugriff auf die **Google Tasks** eines Users: **Aufgaben per Chat/Sprache anzeigen, anlegen, ändern, erledigen/wieder öffnen und löschen** sowie ein Settings-Tab „Aufgaben", in dem der User Google-Konten verbindet und festlegt, welche seiner Google-Aufgabenlisten Alice nutzen darf.

**Begriffe:** Gegenstand dieses Features sind ausschließlich **Aufgaben** (Dinge, die man erledigt). Google-Aufgabenlisten sind hier nur die Ordner, in denen Aufgaben liegen; sie werden im Settings-Tab ausgewählt und im Chat höchstens als Ziel genannt („leg die Aufgabe in ‚Arbeit' an"). Listen mit Einträgen wie Einkaufslisten (Home-Assistant-Todo-Listen) behandelt PROJ-100.

**Datum statt Uhrzeit:** Die Google-Tasks-API kennt nur ein Fälligkeitsdatum (`due`, nur Datum — eine Uhrzeit wird verworfen). Die in der Google-App sichtbare Uhrzeit und die separate Frist sind über die API weder les- noch schreibbar. Alice arbeitet daher nur mit dem Fälligkeitsdatum.

Es werden **keine Aufgabendaten lokal gespeichert** (PRD-Constraint „nur Live-Abfragen"). Gespeichert wird ausschließlich die Auswahl (welche Aufgabenlisten aktiv, welche Standard).

Aufgaben sind **strikt pro User privat** (PROJ-86): kein Teilen, kein Admin-Zugriff auf fremde Aufgaben.

## User Stories

- Als berechtigter User möchte ich im Settings-Tab „Aufgaben" ein Google-Konto verbinden, damit Alice auf meine Google-Aufgaben zugreifen kann — und sofort loslegen können, ohne vorher etwas einstellen zu müssen.
- Als User möchte ich pro Google-Konto auswählen, welche meiner Aufgabenlisten Alice nutzen darf, und eine Standardliste für neue Aufgaben festlegen.
- Als User möchte ich Alice per Sprache oder Chat fragen, welche Aufgaben offen, heute/diese Woche fällig oder überfällig sind, damit ich meinen Tag planen kann.
- Als User möchte ich per Sprache oder Chat Aufgaben mit Fälligkeitsdatum und Notiz anlegen, damit ich nichts vergesse.
- Als User möchte ich Aufgaben per Sprache abhaken („Hake Müll rausbringen ab"), ändern oder verschieben, ohne die Google-App zu öffnen.
- Als User möchte ich Aufgaben löschen können, ohne dass ein Hörfehler versehentlich etwas Falsches entfernt.
- Als User möchte ich kurze, verlässliche Antworten bekommen — ohne Geschwätz, erfundene Rückfragen oder vorgetäuschte Erfolge.
- Als Admin möchte ich pro Rolle steuern, wer den Aufgaben-Agenten nutzen darf.

## Acceptance Criteria

### Settings-Tab „Aufgaben"

- [ ] Der Tab „Aufgaben" erscheint in den Settings nur für Rollen mit Aufgaben-Berechtigung; ohne Berechtigung ist er ausgeblendet.
- [ ] Der Tab listet **alle** Google-Konten des Users (Connections aus PROJ-86) mit Konto (E-Mail), Status und – bei Konten mit Aufgaben-Scope – deren Aufgabenlisten. „Konto verbinden" startet den Google-Consent-Flow mit Aufgaben-Scope; nach Rückkehr (Erfolg oder Fehler) zeigt der Tab eine erkennbare Meldung und die aktualisierte Liste.
- [ ] Konten ohne Aufgaben-Scope (z. B. über den Kalender-Tab verbunden) werden mit dem Button „Aufgaben-Zugriff freigeben" angezeigt; dieser erweitert die bestehende Connection per Re-Consent (kein Duplikat).
- [ ] Unter jedem Konto mit Aufgaben-Scope werden dessen Aufgabenlisten live von Google geladen (Name). Pro Liste gibt es einen Schalter „Für Alice aktiv". Nur diese Auswahl wird gespeichert, keine Aufgaben.
- [ ] Genau eine aktive Aufgabenliste des Users ist **Standardliste** (kontenübergreifend eindeutig) und kann im Tab gewechselt werden.
- [ ] **Auto-Setup:** Erhält der User erstmals Aufgaben-Zugriff (erstes Konto mit Aufgaben-Scope, noch keine aktive Liste), wird die Google-Default-Liste dieses Kontos („Meine Aufgaben") automatisch aktiviert und zur Standardliste. Weitere Listen aktiviert der User selbst.
- [ ] Wird die Standardliste deaktiviert, entfällt der Standard; verbleibende Listen werden nicht automatisch Standard (Alice fragt beim Anlegen nach).
- [ ] „Konto trennen" entfernt die gesamte Connection (alle Scopes, Revoke bei Google, PROJ-86-Verhalten). Der Bestätigungsdialog warnt, wenn das Konto auch Kalender-/Kontakte-Scopes hat, dass diese Features ebenfalls betroffen sind. Die Listenauswahl des Kontos wird mitgelöscht.
- [ ] Connection mit Status `error` (Refresh-Token widerrufen): rotes Badge und Button „Neu verbinden".
- [ ] Leerzustand: Ohne verbundenes Konto zeigt der Tab eine kurze Erklärung und „Konto verbinden".
- [ ] Alle UI-Texte laufen über die i18n-Schicht; Darstellung im hellen und dunklen Theme gut lesbar.

### Chat/Sprache — Zuordnung (Abgrenzung zu PROJ-100)

- [ ] Anfragen werden als Google-Aufgabe behandelt, wenn der User von einer **Aufgabe** spricht („Aufgabe", „erinnere mich, … zu erledigen", „bis Freitag muss ich …", „hake … ab"), eine Fälligkeit nennt oder eine aktive Google-Aufgabenliste beim Namen nennt.
- [ ] Anfragen mit Bezug auf eine benannte HA-Liste („Einkaufsliste", „auf die Liste setzen") werden **nicht** als Google-Aufgabe behandelt (→ PROJ-100).
- [ ] Bei Mehrdeutigkeit (z. B. „To-do-Liste" ohne weiteren Hinweis) fragt Alice einmal kurz nach („Als Google-Aufgabe oder auf die Liste ‚To-do'?") statt zu raten.
- [ ] Hat der User keine Aufgaben-Berechtigung oder kein verbundenes Konto, werden Aufgabenanfragen nicht stillschweigend auf eine HA-Liste umgeleitet; Alice sagt, dass Aufgaben nicht erlaubt bzw. nicht eingerichtet sind.
- [ ] Aufgabenanfragen und die direkte Antwort auf eine offene Aufgaben-Rückfrage werden **nicht** vom Smart-Home-Schnellpfad (HA_FAST) oder vom Kalender-Agenten abgefangen.

### Chat/Sprache — Anzeigen

- [ ] Alice versteht: alle offenen Aufgaben („Welche Aufgaben habe ich?"), fällig heute/morgen/diese Woche/an einem Datum, überfällige Aufgaben und die Fälligkeit einer bestimmten Aufgabe („Wann ist die Steuererklärung fällig?"); optional eingeschränkt auf eine genannte Aufgabenliste.
- [ ] Ohne Einschränkung werden **alle aktiven Aufgabenlisten** aller verbundenen Konten des identifizierten Users durchsucht.
- [ ] Reihenfolge: überfällige zuerst, dann datierte aufsteigend, dann Aufgaben ohne Datum. Pro Aufgabe: Titel, Fälligkeitsdatum (falls vorhanden), ggf. „überfällig". Der Listenname erscheint nur, wenn mehr als eine Liste aktiv ist. Notizen nur auf Nachfrage.
- [ ] In Google vorhandene Unteraufgaben werden eingerückt unter ihrer übergeordneten Aufgabe angezeigt.
- [ ] Per Sprache liest Alice höchstens 5 Aufgaben vor und nennt die Restanzahl („… und 3 weitere"); im Chat werden alle Treffer angezeigt (max. 50, bei Überschreitung Hinweis auf Kürzung).
- [ ] Erledigte Aufgaben erscheinen nur auf ausdrückliche Nachfrage („Was habe ich heute erledigt?"), maximal für die letzten 7 Tage.
- [ ] Ohne Treffer sagt Alice klar, dass keine (passenden) Aufgaben vorliegen.
- [ ] „Heute", „überfällig" usw. beziehen sich auf die Zeitzone des Users (Default Europe/Berlin).

### Chat/Sprache — Anlegen

- [ ] Pflicht ist nur der Titel; optional Fälligkeitsdatum, Notiz, Aufgabenliste.
- [ ] Ohne genannte Liste → Standardliste. Ist keine Standardliste gesetzt, fragt Alice nach (Auswahl der aktiven Listen). Ist die genannte Liste unbekannt oder mehrdeutig, fragt Alice nach.
- [ ] Nennt der User eine Uhrzeit („morgen um 14 Uhr"), legt Alice die Aufgabe mit dem Datum an und weist kurz darauf hin, dass Google Aufgaben nur mit Datum speichert.
- [ ] Ein Fälligkeitsdatum in der Vergangenheit wird nicht stillschweigend gesetzt; Alice fragt nach.
- [ ] Existiert in derselben Liste bereits eine **offene** Aufgabe mit gleichem Titel, weist Alice darauf hin und fragt, ob trotzdem angelegt werden soll.
- [ ] Nach dem Anlegen bestätigt Alice knapp Titel, Datum (falls gesetzt) und Liste (falls mehr als eine aktiv), damit Hörfehler auffallen.

### Chat/Sprache — Ändern

- [ ] Änderbar: Titel, Fälligkeitsdatum (setzen, ändern, entfernen), Notiz, Aufgabenliste (verschieben).
- [ ] Die Aufgabe wird über den (auch ungefähr genannten) Titel identifiziert. Mehrere Treffer → kurze Auflistung und Rückfrage; kein Treffer → klare Meldung.
- [ ] Änderungen laufen ohne Rückfrage; Alice bestätigt danach knapp die neue Fassung.

### Chat/Sprache — Erledigen / Wieder öffnen

- [ ] „Hake … ab" / „… ist erledigt" markiert die Aufgabe als erledigt, ohne Rückfrage; Alice bestätigt danach.
- [ ] „Öffne … wieder" / „… ist doch nicht erledigt" setzt eine erledigte Aufgabe wieder auf offen.
- [ ] Hat die Aufgabe offene Unteraufgaben, wird nur die genannte Aufgabe erledigt; Alice erwähnt, dass noch Unteraufgaben offen sind.
- [ ] Mehrere Aufgaben in einem Satz („Hake Müll und Steuer ab") werden in einem Durchgang erledigt, mit einer Sammelbestätigung; nicht eindeutig zuordenbare werden benannt und nicht erledigt.

### Chat/Sprache — Löschen

- [ ] Alice löscht **nur nach Rückfrage**: Sie nennt die konkrete Aufgabe (Titel, Datum, ggf. Liste) und löscht erst nach einem „Ja" im folgenden Turn. „Nein"/anderes → nichts wird gelöscht.
- [ ] Hat die Aufgabe Unteraufgaben, nennt die Rückfrage, dass diese mitgelöscht werden.
- [ ] Löschen erfolgt immer für genau eine Aufgabe pro Rückfrage; bei mehreren passenden fragt Alice zuerst nach der gemeinten.
- [ ] Ein „Ja" auf die Löschfrage führt verlässlich zum Löschen — per Chat **und** per Voice.

### Antwortverhalten (Erkenntnisse aus PROJ-87)

- [ ] Antworten sind knapp und gleichbleibend formuliert (in der Regel 1–2 Sätze): keine internen/technischen Begriffe, keine Wiederholung der Anfrage, keine doppelte Bestätigung („ich hake ab …" + „wurde abgehakt").
- [ ] Alice stellt nur Rückfragen, wenn etwas wirklich fehlt oder mehrdeutig ist (Zuordnung Aufgabe/HA-Liste, mehrdeutige Aufgabe, keine Standardliste, unbekannte Liste, Datum in der Vergangenheit, Duplikat, Löschbestätigung). Nicht genannte optionale Angaben (Notiz, Datum, Liste) werden **nie** erfragt.
- [ ] Alice meldet eine Aufgabe nur dann als angelegt/geändert/erledigt/gelöscht, wenn Google die Aktion bestätigt hat (kein Halluzinieren von Erfolg, vgl. PROJ-102); sie nennt keine Aufgaben, die Google nicht geliefert hat.
- [ ] Voice: Datumsangaben gesprochen („Freitag, den 10. Oktober"), keine Listen/Markdown/Emojis. Nach einer abgeschlossenen Aktion bzw. Abfrage endet die Voice-Sitzung (wie bei HA-Befehlen); bei einer Rückfrage bleibt sie offen, damit der User antworten kann.
- [ ] Antworten erfolgen in der konfigurierten Nutzersprache.
- [ ] Die folgenden Testsätze funktionieren im Live-Test über WebApp **und** Voice PE wie beschrieben:
  - „Setz Steuererklärung bis Freitag auf meine Aufgaben" → angelegt mit Datum, in Standardliste
  - „Erinnere mich, die Garage aufzuräumen" → angelegt ohne Datum, keine Rückfrage zum Datum
  - „Neue Aufgabe Reifen wechseln morgen um 14 Uhr" → angelegt mit Datum + Hinweis „nur Datum"
  - „Welche Aufgaben habe ich?" / „Was ist diese Woche fällig?" / „Was ist überfällig?" → Abfrage
  - „Verschiebe die Steuererklärung auf nächsten Montag" → Fälligkeit geändert
  - „Hake Müll rausbringen ab" → erledigt; „Öffne Müll rausbringen wieder" → offen
  - „Lösche die Aufgabe Garage aufräumen" → Rückfrage; „Ja" → gelöscht; „Nein" → nichts gelöscht
  - „Setz Butter auf die Einkaufsliste" → **nicht** Google Tasks (PROJ-100)
  - „Setz Steuer auf meine To-do-Liste" → Zuordnungsrückfrage

### Berechtigung, Zuordnung, Fehler

- [ ] Neue Aufgaben-Berechtigung pro Rolle im bestehenden Rollen-System, im Admin-Bereich editierbar. Default: `admin` und `user` an, `guest` und `child` aus.
- [ ] Ohne Berechtigung lehnt Alice Aufgabenanfragen höflich ab; Endpoints des Tabs geben 403.
- [ ] Per Sprache nur bei **eindeutig identifiziertem User**: Bei nicht erkanntem Sprecher führt Alice keine Aufgabenaktion aus und erklärt, dass sie nicht weiß, wessen Aufgaben gemeint sind. Kein Fallback auf Admin oder Geräte-Default.
- [ ] Ein User sieht und ändert ausschließlich eigene Aufgaben; Cross-User-Zugriffe (auch durch Admin) schlagen fehl.
- [ ] `reauth_required` (409): Alice sagt, dass die Google-Verbindung erneuert werden muss (Hinweis auf Settings → Aufgaben), ohne weiteren Versuch.
- [ ] Transientes 503 des Token-Endpoints: einmal automatisch wiederholen; danach freundliche „Später nochmal versuchen"-Meldung.
- [ ] Google-API nicht erreichbar / Timeout / Rate-Limit: klare Meldung, dass die Aufgaben gerade nicht erreichbar sind; keine erfundenen Aufgaben, keine Erfolgsmeldung.

## Edge Cases

- **Mehrere Konten:** Abfragen mergen Aufgaben über alle aktiven Listen aller Konten; fällt ein Konto aus, werden die übrigen Aufgaben angezeigt und Alice weist auf den Teilausfall hin (keine stille Teilantwort).
- **Aufgabenliste in Google gelöscht/umbenannt:** Gespeicherte Auswahl auf eine nicht mehr existierende Liste wird beim nächsten Laden des Tabs bereinigt; war sie Standard, entfällt der Standard. Chat-Anfragen überspringen sie ohne Abbruch. Umbenennungen werden live übernommen.
- **Keine aktive Liste:** Alice sagt, dass keine Aufgabenliste aktiviert ist, und verweist auf Settings → Aufgaben.
- **Gleichnamige Aufgaben in verschiedenen Listen:** Rückfrage mit Nennung der Liste statt Raten.
- **Lösch-Rückfrage wird nicht beantwortet / Thema wechselt:** Nichts wird gelöscht; die offene Löschabsicht verfällt nach dem nächsten, nicht bestätigenden Turn.
- **Parallele Änderung in Google** (Aufgabe zwischen Rückfrage und Löschung bereits gelöscht/erledigt/geändert): Alice meldet, dass die Aufgabe nicht mehr gefunden wurde bzw. sich geändert hat, statt blind zu handeln.
- **Abhaken einer bereits erledigten Aufgabe:** Alice sagt, dass sie schon erledigt ist (kein Fehler, keine Doppelaktion).
- **Unteraufgabe wird in eine andere Liste verschoben:** Nicht möglich, Alice meldet das (Google erlaubt Verschieben nur für Aufgaben ohne übergeordnete Aufgabe); alternativ Hinweis auf die Google-App.
- **Aus Google Docs/Chat zugewiesene Aufgaben** (keine Notizen möglich): werden angezeigt und können erledigt werden; Notizänderungen werden mit klarer Meldung abgelehnt.
- **Whisper-Transkriptionsfehler** (Titel/Datum falsch verstanden): Die Anlege-Bestätigung nennt das Verstandene, damit der User korrigieren kann.
- **Rolle verliert Berechtigung, während ein Konto verbunden ist:** Chat und Tab sperren sofort; Connection und Listenauswahl bleiben erhalten.
- **Scope entzogen, aber aktive Listen in der Auswahl:** Listen werden ignoriert, bis der Aufgaben-Scope erneut freigegeben ist.
- **Zwei Alice-User verbinden dasselbe Google-Konto:** zwei unabhängige Connections und Listenauswahlen (PROJ-86); kein Konflikt.

## Technical Requirements

- **Datenhaltung:** Nur Auswahl-Metadaten (Connection, Listen-ID, aktiv, Standard) in PostgreSQL; keine Aufgaben, keine Notizen, kein lokales Caching von Google-Daten.
- **Sicherheit:** Endpoints und Chat-Aktionen nur mit authentifiziertem, eindeutig identifiziertem User; alle Queries user-scoped; Token nur über den PROJ-86-Service.
- **Performance:** Abfrage über mehrere Listen in der Regel < 3 s Ende-zu-Ende; kein HA_FAST-Ziel.
- **Sprache:** Alice-Antworten in der Nutzersprache; UI-Strings über i18n; Code/Kommentare/Commit-Messages auf Englisch.
- **Zugang:** nur über VPN/Hausnetz (wie PROJ-86).
- **Hinweis für `/architecture`:** Die in PROJ-87 eingeführten Mechanismen (Vorlagen-Antworten statt LLM-Formulierung, erzwungenes Tool je Absicht, serverseitiges Lösch-Ticket aus früherem Turn, Umgehung des HA-Fast-Path, offene Rückfrage über Turns hinweg, `conversation_end` bei Voice) sollen geprüft und nach Möglichkeit wiederverwendet werden.

## Out of Scope (bewusst nicht in PROJ-88)

- Uhrzeit und Frist von Aufgaben (über die Google-Tasks-API nicht verfügbar)
- Unteraufgaben anlegen oder umhängen
- Wiederholende Aufgaben (über die API nicht verfügbar)
- Sortieren/Umordnen von Aufgaben
- Aufgabenlisten anlegen, umbenennen, löschen (erfolgt in Google)
- „Erledigte löschen" (Liste aufräumen)
- HA-Todo-Listen wie Einkaufsliste (→ PROJ-100)
- Proaktive Erinnerungen/Push zu fälligen Aufgaben (→ PROJ-104)
- Verbesserte Sprecher-Erkennung (→ PROJ-103)
- Andere Aufgabenanbieter als Google
- Geteilte/familienweite Aufgaben zwischen Alice-Usern

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
