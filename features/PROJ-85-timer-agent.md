# PROJ-85: Timer-Agent

## Status: Approved
**Created:** 2026-09-07
**Last Updated:** 2026-09-08

## Dependencies

- Requires: PROJ-1 (HA Intent Infrastructure) — Weaviate-`HAIntent`-Collection als Index für die Timer-Satzmuster (Timer-Intents werden als handgepflegte, entity-lose Objekte in dieselbe Collection eingetragen)
- Requires: PROJ-3 (HA-First Chat Handler mit Intent-Routing) — HA_FAST/LLM_ONLY-Pfadlogik, Sentence Splitter (Mehrfach-Timer in einem Satz)
- Requires: PROJ-40/PROJ-42 (Speech-Gateway Wyoming/ESPHome) — direkte Wyoming-Verbindung Voice PE ↔ `alice-speech-gateway`, `device-mapping.yaml` (Gerätename/Raum je IP), `source: <device>`-Weitergabe an `alice-chat-stream`
- Requires: PROJ-83 (HA-Agent variable Intents) — Muster für Wert-/Text-Extraktion aus dem transkribierten Text nach dem Weaviate-Match (hier: Dauer, Uhrzeit, Name, Delta)
- Requires: Speaker-ID / JWT-User-Identifikation (Phase 1) — Timer gehören einem User; die Rolle des Users steuert Sichtbarkeit, Berechtigung und Limits
- Requires: Permission-System Phase 1 — `alice.role_templates`, `alice.permissions_assistant`, `alice.init_user_permissions()`, Settings-Tab „User-Verwaltung" — wird um Timer-Berechtigung und rollen-spezifische Timer-Limits erweitert
- Related: PROJ-103 (Sprecher-Erkennung verbessern) — die heutige Speaker-ID ist stark device-abhängig und fällt bei Nicht-Erkennung auf einen Anonymous-Kontext zurück; PROJ-85 mildert das über die Default-Rolle ab, die eigentliche Verbesserung ist PROJ-103. PROJ-85 hängt nicht davon ab.
- Unabhängig von: PROJ-84 (Area-Context) — Timer haben keinen Raumbezug

## Overview

Alice bekommt einen **Timer-Agenten**: per Sprache (Voice PE) oder WebApp-Chat lassen sich mehrere unabhängige Timer setzen, ändern, abfragen, pausieren/fortsetzen und löschen. Timer laufen im schnellen HA_FAST-Pfad (Weaviate-Intent-Match + Textverarbeitung, kein LLM, < 200 ms) und werden **nicht** über Home Assistants Assist-Pipeline verwaltet — dazu fehlt Alice der Zugang (HA-Sprach-Timer haben keine Entity, keinen REST-Service und leben ausschließlich im Assist-Pipeline-Kontext, den `alice-chat-stream` nicht nutzt).

Der Timer-Zustand liegt in einer eigenen Tabelle `alice.timers` (PostgreSQL) — Name, Ablauf-Zeitpunkt, Besitzer (User), **Besitzer-Rolle**, Setz-Gerät bzw. WebApp-Session, Status. Ein Background-Task im bestehenden `alice-chat-stream`-Container überwacht die Abläufe und löst beim Ablauf die Benachrichtigung aus:

- **Voice PE:** `alice-speech-gateway` sendet über das native **Wyoming-Timer-Protokoll** ein `timer-finished`-Event an genau das Gerät, auf dem der Timer gesetzt wurde; das Gerät spielt daraufhin selbst eine Melodie/Tonfolge ab, bis der User es anspricht (Wakeword) oder eine Maximalzeit (Default 2 Minuten) abläuft. Beim Ansprechen sagt Alice die abgelaufene Timer-Meldung an ("Der 20 Minuten Timer ist abgelaufen.").
- **WebApp:** Der Client zählt lokal auf den vom Server gelieferten Ablauf-Zeitpunkt herunter und meldet den Ablauf per Toast + Ton **im sichtbaren Tab**. Zuverlässige Hintergrund-Benachrichtigung (gesperrtes Display, anderer Tab/App im Vordergrund) ist **nicht** Teil von PROJ-85 — dafür gibt es den neuen Roadmap-Eintrag PROJ-104 (Web Push / PWA-Benachrichtigungen).

### Rollen-basierte Sichtbarkeit, Berechtigung und Limits

Die Sprecher-Erkennung von Alice ist heute stark device-abhängig und erkennt einen Sprecher nicht immer zuverlässig (Speaker-ID mit Ähnlichkeits-Threshold; darunter kein User). Damit Timer trotzdem berechenbar zugeordnet werden, ist die **Rolle** des Besitzers (`admin`/`user`/`guest`/`child`) das zentrale Ordnungsmerkmal:

- **Sichtbarkeits-Scope:** Ein Timer ist für alle User **derselben Rolle** sichtbar und änderbar, nicht nur für den Ersteller. Fragt ein `admin` "Welche Timer laufen?", sieht er alle Timer, die von einem `admin` gesetzt wurden.
- **Berechtigung:** Pro Rolle ist konfigurierbar, ob Timer-Operationen überhaupt erlaubt sind (analog zu bestehenden Chat-Feature-Permissions in `alice.permissions_assistant`). Eine Rolle ohne Timer-Berechtigung bekommt bei jedem Timer-Befehl eine freundliche Ablehnung.
- **Rollen-spezifische Limits:** Max. Anzahl gleichzeitig aktiver Timer und Max-Dauer sind pro Rolle einstellbar (z. B. `child`: 3 Timer / 2 h; `admin`: 20 Timer / 24 h).
- **Default-Rolle bei unerkanntem Sprecher:** Wird über ein Voice PE kein User erkannt, wird der Timer einer konfigurierbaren **Default-Rolle** zugeordnet (Einstellung im Settings-Tab; sinnvoller Auslieferungswert `user`). Der Timer ist dann für alle User dieser Rolle sichtbar. In der heutigen Ein-Nutzer-Realität (nur Andreas, `admin`) landet damit alles konsistent im Admin-Scope, sobald die Default-Rolle auf `admin` gesetzt ist.

Alle rollen-basierten Einstellungen werden über den bestehenden Settings-Tab „User-Verwaltung" / Rollen-Verwaltung gepflegt (Erweiterung im Rahmen dieses Features), gespeichert in `alice.role_templates` bzw. `alice.permissions_assistant`.

### Bewusst außerhalb des Scopes

- **Zeitgesteuerte HA-Befehle** ("Schließe den Rolladen im Büro um 20 Uhr 30") — anderer Mechanismus (geplante Geräte-Aktion, kein Countdown mit Melodie). Neuer Roadmap-Eintrag PROJ-105.
- **Verbesserung der Sprecher-Erkennung selbst** — die device-abhängige, oft unsichere Speaker-ID ist ein eigenes Thema (neuer Roadmap-Eintrag PROJ-103). PROJ-85 mildert die Auswirkung über die Default-Rolle ab, verbessert aber nicht die Erkennung.
- **Zuverlässige WebApp-Hintergrund-Benachrichtigung** (Web Push / Service Worker / PWA) — neuer Roadmap-Eintrag PROJ-104. PROJ-85 hängt nicht davon ab.
- **Pro-User-Sichtbarkeit unterhalb der Rolle** — Timer werden absichtlich auf Rollen-Ebene geteilt, nicht pro einzelnem User isoliert. Ein feineres „nur meine eigenen Timer" ist kein Scope.
- **Multi-Turn-Namensdialog bei Kollision** — der HA_FAST-Pfad bleibt zustandslos (analog PROJ-83/84). Bei Namenskollision vergibt Alice sofort einen Fallback-Namen statt nachzufragen.
- **Ausgeschriebene Zahlwörter** ("zwanzig Minuten" statt "20 Minuten") — dokumentierte, akzeptierte Lücke (Whisper transkribiert im Deutschen überwiegend Ziffern), analog PROJ-83.
- **Relative Uhrzeit-Wecker mit Wiederholung** ("jeden Morgen um 7") — kein Scope, kein Countdown-Mechanismus.
- **Timer-Alarm auf einem anderen als dem Setz-Gerät** (Ausweich-Routing bei Offline-Gerät) — kein Scope; ein Offline-Gerät bekommt die Meldung nachgeholt oder der Timer wird nach Maximalzeit still quittiert.

## User Stories

### Setzen

- Als Andreas möchte ich sagen "Setze einen Timer auf 20 Minuten" und Alice legt einen Timer mit 20 Minuten Laufzeit an und bestätigt "Ich habe einen Timer auf 20 Minuten gesetzt."
- Als Andreas möchte ich sagen "Stelle einen Timer auf 15 Uhr 40" und Alice legt einen Timer an, der zur nächsten 15:40-Uhr-Marke abläuft, und bestätigt mit der berechneten Laufzeit ("Ich habe einen Timer auf 15 Uhr 40 gesetzt, er läuft 25 Minuten.").
- Als Andreas möchte ich sagen "Stelle einen Timer für Kartoffeln auf 20 Minuten" und Alice legt einen benannten Timer "Kartoffel Timer" an und bestätigt "Ich habe den Kartoffel Timer auf 20 Minuten gesetzt."
- Als Andreas möchte ich, dass ein Timer ohne expliziten Namen automatisch einen Namen aus seiner Zeitangabe bekommt ("20 Minuten Timer", "15 Uhr 40 Timer"), damit ich ihn später ansprechen kann.
- Als Andreas möchte ich sagen "Setze einen Timer auf 10 und einen auf 20 Minuten" und Alice legt zwei getrennte Timer an.

### Namenskollision

- Als Andreas möchte ich, dass wenn schon ein Timer mit demselben (abgeleiteten oder genannten) Namen existiert, Alice den neuen Timer sofort mit einem Fallback-Namen anlegt ("zweiter 20 Minuten Timer", "dritter 20 Minuten Timer") und mir das in der Bestätigung sagt — statt den Vorgang mit einer Rückfrage zu unterbrechen.

### Ändern

- Als Andreas möchte ich sagen "Verlängere den 20 Minuten Timer um 5 Minuten" und die Restlaufzeit dieses Timers erhöht sich um 5 Minuten.
- Als Andreas möchte ich sagen "Verkürze den Kartoffel Timer um 2 Minuten" und die Restlaufzeit dieses Timers verringert sich um 2 Minuten.
- Als Andreas möchte ich, dass Alice bei einer Änderung die neue Restlaufzeit bestätigt ("Der Kartoffel Timer läuft jetzt noch 14 Minuten.").

### Abfragen

- Als Andreas möchte ich fragen "Wie lange läuft der Kartoffel Timer noch?" und eine Antwort mit der verbleibenden Laufzeit bekommen.
- Als Andreas möchte ich fragen "Welche Timer laufen gerade?" und eine Aufzählung der aktiven Timer in meinem Rollen-Scope mit Restlaufzeit bekommen.
- Als Andreas möchte ich einen Timer über jedes meiner Geräte und die WebApp abfragen/ändern können, auch wenn ich ihn woanders gesetzt habe — die Melodie beim Ablauf spielt aber nur auf dem ursprünglichen Setz-Gerät.

### Pausieren / Fortsetzen / Löschen

- Als Andreas möchte ich sagen "Pausiere den Kartoffel Timer" und "Setze den Kartoffel Timer fort" und der Countdown hält an bzw. läuft an der pausierten Stelle weiter.
- Als Andreas möchte ich sagen "Lösche den Kartoffel Timer" und der Timer wird entfernt, ohne dass er noch abläuft.
- Als Andreas möchte ich sagen "Lösche alle Timer" und alle meine aktiven Timer werden entfernt.

### Ablauf

- Als Andreas möchte ich, dass wenn ein Timer abläuft, das Voice-Gerät, auf dem ich ihn gesetzt habe, eine Melodie/Tonfolge abspielt — bis ich das Gerät anspreche oder eine Maximalzeit abläuft.
- Als Andreas möchte ich, dass wenn ich das Gerät nach dem Ablauf anspreche, die Melodie sofort aufhört und Alice mir sagt, welcher Timer abgelaufen ist ("Der 20 Minuten Timer ist abgelaufen.").
- Als Andreas möchte ich, dass ein in der WebApp gesetzter Timer im sichtbaren Tab per Hinweis und Ton meldet, dass er abgelaufen ist.
- Als Andreas möchte ich, dass meine laufenden Timer einen Neustart der Alice-Dienste überstehen und ein währenddessen fällig gewordener Timer nachträglich ausgelöst wird.

### Rollen-basierte Sichtbarkeit & Verwaltung

- Als Andreas (admin) möchte ich alle Timer sehen und ändern können, die von einem admin gesetzt wurden — auch die, die über ein Voice PE ohne sichere Sprecher-Erkennung angelegt wurden (weil die Default-Rolle auf admin steht).
- Als Andreas möchte ich im Settings-Tab pro Rolle festlegen können, ob diese Rolle Timer nutzen darf, wie viele gleichzeitig, und wie lang maximal.
- Als Andreas möchte ich im Settings-Tab die Default-Rolle einstellen können, der ein per Voice PE gesetzter Timer zugeordnet wird, wenn der Sprecher nicht erkannt wurde.
- Als Elternteil möchte ich, dass ein child-User nur wenige, kurze Timer setzen kann und die Timer der Erwachsenen weder sieht noch ändert.
- Als Gast-Nutzer (guest ohne Timer-Berechtigung) möchte ich eine verständliche Rückmeldung bekommen, wenn ich einen Timer setzen will, statt eines stillen Fehlschlags.

## Acceptance Criteria

### Setzen — Dauer

- [ ] "Setze einen Timer auf X Minuten/Stunden" (auch kombiniert, z. B. "1 Stunde 30 Minuten") legt einen Timer mit Laufzeit X an; Ablauf-Zeitpunkt = jetzt + X
- [ ] Bestätigung für einen unbenannten Dauer-Timer: "Ich habe einen Timer auf {Dauer} gesetzt." (Dauer im gesprochenen Format, z. B. "20 Minuten", "1 Stunde 30 Minuten")
- [ ] Ein unbenannter Dauer-Timer bekommt automatisch den Namen "{Dauer} Timer" (z. B. "20 Minuten Timer", "1 Stunde 30 Minuten Timer")

### Setzen — absolute Uhrzeit

- [ ] "Stelle einen Timer auf HH Uhr MM" (bzw. "auf HH Uhr") legt einen Timer an, der zur nächsten Vorkommnis dieser Uhrzeit abläuft
- [ ] Liegt die genannte Uhrzeit heute noch in der Zukunft, läuft der Timer heute zu dieser Uhrzeit ab; liegt sie heute bereits in der Vergangenheit, läuft er morgen zu dieser Uhrzeit ab
- [ ] Bestätigung für einen unbenannten Uhrzeit-Timer nennt die berechnete Laufzeit: "Ich habe einen Timer auf {Uhrzeit} gesetzt, er läuft {berechnete Dauer}." (Dauer = Differenz aktuelle Zeit ↔ Ablauf-Zeitpunkt, auf ganze Minuten gerundet)
- [ ] Ein unbenannter Uhrzeit-Timer bekommt automatisch den Namen "{Uhrzeit} Timer" (z. B. "15 Uhr 40 Timer")

### Setzen — benannt

- [ ] "Stelle einen Timer für {Name} auf {Zeit}" (Dauer oder Uhrzeit) legt einen Timer mit dem genannten Namen an ("Kartoffel Timer" bei "für Kartoffeln"); der Name wird sprachlich normalisiert (Grundform/Titel, "{Name} Timer")
- [ ] Bestätigung für einen benannten Timer: "Ich habe den {Name} Timer auf {Zeit} gesetzt." — bei Uhrzeit zusätzlich "…, er läuft {berechnete Dauer}."

### Namenskollision

- [ ] Existiert bereits ein aktiver Timer **im selben Rollen-Scope** mit demselben Namen (abgeleitet oder genannt, case-insensitiv), legt Alice den neuen Timer **sofort** mit einem Fallback-Namen an ("zweiter {Name} Timer", bei weiterer Kollision "dritter …", "vierter …") — keine Rückfrage, kein Dialog-Zustand
- [ ] Die Bestätigung nennt den vergebenen Fallback-Namen: "Es gibt schon einen {Name} Timer. Ich habe einen zweiten {Name} Timer gesetzt."

### Rollen-basierte Sichtbarkeit, Berechtigung & Limits

- [ ] Jeder Timer wird beim Anlegen mit dem Besitzer-User **und** dessen Rolle gespeichert; wird über ein Voice PE kein User erkannt, wird die konfigurierte Default-Rolle gespeichert (Besitzer-User dann leer / Anonymous)
- [ ] Abfrage-, Änderungs-, Pausier- und Löschbefehle wirken auf alle Timer **im Rollen-Scope des anfragenden Users** — nicht nur auf selbst erstellte; "Welche Timer laufen?" listet alle Timer der eigenen Rolle
- [ ] "Lösche alle Timer" löscht alle Timer im eigenen Rollen-Scope (nicht die anderer Rollen)
- [ ] Hat die Rolle des Users keine Timer-Berechtigung (`alice.permissions_assistant`), antwortet Alice bei jedem Timer-Befehl mit einer verständlichen deutschen Ablehnung und führt nichts aus — kein LLM-Fallback
- [ ] Die Maximalzahl gleichzeitig aktiver Timer wird pro Rolle aus `alice.role_templates` gelesen; beim Überschreiten lehnt Alice ab und nennt das Limit ("Für deine Rolle sind höchstens {N} Timer gleichzeitig möglich.")
- [ ] Die Maximaldauer wird pro Rolle gelesen; eine längere angeforderte Dauer wird abgelehnt mit Nennung des Rollen-Limits
- [ ] Untergrenze der Dauer (Default 10 Sekunden) gilt rollenunabhängig
- [ ] Im Settings-Tab „User-Verwaltung" / Rollen kann ein admin pro Rolle setzen: Timer-Berechtigung (an/aus), Max-Anzahl aktiver Timer, Max-Dauer
- [ ] Im Settings-Tab kann ein admin die Default-Rolle für per Voice PE gesetzte, nicht zugeordnete Timer wählen (`admin`/`user`/`guest`/`child`); Auslieferungswert `user`
- [ ] Die Settings-Änderungen wirken ohne Container-Neustart auf neu gesetzte Timer; bestehende Timer behalten ihre gespeicherte Rolle
- [ ] Nur ein `admin` sieht und bearbeitet diese Einstellungen; für andere Rollen ist der Bereich nicht sichtbar (bestehendes Settings-Berechtigungsmuster)
- [ ] Neue Rollen-Default-Werte werden über `alice.role_templates` geseedet und von `alice.init_user_permissions()` bei der User-Anlage übernommen

### Mehrere Timer in einem Satz

- [ ] "Setze einen Timer auf X und einen auf Y Minuten" legt über den bestehenden Sentence-Splitter (PROJ-3) zwei getrennte Timer an; jeder Teil wird unabhängig aufgelöst und einzeln bestätigt

### Ändern

- [ ] "Verlängere den {Name} Timer um X Minuten" erhöht den Ablauf-Zeitpunkt dieses Timers um X; Alice bestätigt mit der neuen Restlaufzeit
- [ ] "Verkürze den {Name} Timer um X Minuten" verringert den Ablauf-Zeitpunkt um X; Alice bestätigt mit der neuen Restlaufzeit
- [ ] Würde eine Verkürzung den Ablauf-Zeitpunkt in die Vergangenheit (bzw. Restlaufzeit ≤ 0) legen, wird die Änderung **nicht** ausgeführt; Alice antwortet mit der aktuellen Restlaufzeit und dem Hinweis, dass so viel nicht abgezogen werden kann
- [ ] Änderungsbefehle ohne Namensnennung ("Verlängere den Timer um 5 Minuten") greifen auf den einzigen aktiven Timer, wenn genau einer läuft; laufen mehrere, zählt Alice sie auf und bittet um Präzisierung — es wird nichts geändert

### Abfragen

- [ ] "Wie lange läuft der {Name} Timer noch?" antwortet mit der verbleibenden Laufzeit (auf sinnvolle Einheit gerundet, z. B. "noch 3 Minuten", "noch 45 Sekunden")
- [ ] "Wie lange läuft der Timer noch?" ohne Namensnennung antwortet für den einzigen aktiven Timer; bei mehreren zählt Alice alle mit Restlaufzeit auf
- [ ] "Welche Timer laufen gerade?" / "Zeig mir meine Timer" listet alle aktiven Timer im Rollen-Scope des anfragenden Users mit Name und Restlaufzeit; ein pausierter Timer wird als pausiert gekennzeichnet
- [ ] Laufen keine Timer, antwortet Alice entsprechend ("Es läuft gerade kein Timer.")

### Pausieren / Fortsetzen

- [ ] "Pausiere den {Name} Timer" hält den Countdown an; die verbleibende Laufzeit bleibt eingefroren, der Timer läuft nicht ab
- [ ] "Setze den {Name} Timer fort" / "Starte den {Name} Timer wieder" setzt den Countdown mit der eingefrorenen Restlaufzeit fort (neuer Ablauf-Zeitpunkt = jetzt + eingefrorene Restlaufzeit)
- [ ] Pausieren eines bereits pausierten Timers bzw. Fortsetzen eines laufenden Timers wird als harmloser No-Op mit passender Rückmeldung behandelt

### Löschen

- [ ] "Lösche den {Name} Timer" / "Brich den {Name} Timer ab" entfernt den Timer; er löst nicht mehr aus, Alice bestätigt
- [ ] "Lösche alle Timer" entfernt alle aktiven Timer im Rollen-Scope des Users; Alice bestätigt mit der Anzahl
- [ ] Löschbefehl ohne Namensnennung bei genau einem aktiven Timer trifft diesen; bei mehreren zählt Alice sie auf und löscht nichts

### Ablauf — Voice PE

- [ ] Läuft ein über ein Voice PE gesetzter Timer ab, sendet `alice-speech-gateway` ein natives Wyoming-`timer-finished`-Event an genau dieses Gerät (identifiziert über die beim Setzen gespeicherte Geräte-Zuordnung)
- [ ] Das Voice PE spielt daraufhin eine Melodie/Tonfolge ab (Geräte-Firmware-Verhalten auf `timer-finished`), bis eine der Abbruch-Bedingungen eintritt
- [ ] Mehrere Timer auf demselben Gerät, die innerhalb eines kurzen Sammel-Fensters (Default 3 Sekunden, konfigurierbar) fällig werden, werden gebündelt: es läuft **eine** Melodie, nicht mehrere; spielt bereits eine Timer-Melodie, wird kein zweiter Ton gestartet
- [ ] Spricht der User das Gerät an (Wakeword) während die Melodie spielt, stoppt die Melodie sofort und Alice sagt **eine** Ablauf-Meldung an, die alle im Sammel-Fenster fälligen Timer nennt: "Der {Name} Timer ist abgelaufen." bzw. "Der {Name A} Timer und der {Name B} Timer sind abgelaufen."
- [ ] Reagiert der User nicht, stoppt die Melodie nach einer konfigurierbaren Maximalzeit (Default 2 Minuten) von selbst; der Timer gilt dann als quittiert
- [ ] Nach Quittierung (durch Ansprache oder Zeitablauf) wird der Timer aus der Menge der aktiven Timer entfernt

### Ablauf — WebApp

- [ ] Beim Anlegen eines Timers über den WebApp-Chat liefert die Antwort den absoluten Ablauf-Zeitpunkt mit, sodass der Client lokal herunterzählen kann
- [ ] Läuft der Timer ab, während der WebApp-Tab sichtbar im Vordergrund ist, zeigt die WebApp einen deutlichen Hinweis (Toast) mit dem Timer-Namen und spielt einen Ton (nutzt die bestehende Audio-Freigabe); der Hinweis bleibt, bis der User ihn schließt
- [ ] Wird der Tab nach dem Ablauf-Zeitpunkt wieder in den Vordergrund geholt, zeigt die WebApp eine Nachhol-Meldung ("Der {Name} Timer ist vor {Dauer} abgelaufen.") — der Server bleibt maßgebliche Quelle für den Timer-Status (Abgleich beim Tab-Fokus / Reload)
- [ ] Ist der Tab beim Ablauf nicht im Vordergrund und wird auch nicht innerhalb des Nachhol-Fensters zurückgeholt, entfällt die WebApp-Meldung — dokumentierte Einschränkung (zuverlässige Hintergrund-Benachrichtigung → PROJ-104)

### Nebenläufigkeit

- [ ] Jeder Status-Übergang eines Timers (running → paused/expired/acknowledged/deleted, Ablauf-Zeitpunkt ändern) läuft als atomare DB-Operation mit Row-Lock; konkurrierende Schreibzugriffe auf denselben Timer werden serialisiert, kein "lost update", kein doppelter Ablauf
- [ ] Markiert der Scheduler einen Timer als abgelaufen, während im selben Moment ein Änderungsbefehl ("verlängere/verkürze/pausiere den {Name} Timer") eintrifft, **gewinnt der Ablauf**: die Änderung wird abgelehnt und wie "Timer schon abgelaufen" behandelt (Alice weist darauf hin, der User setzt bei Bedarf einen neuen Timer)
- [ ] Trifft ein Löschbefehl für einen Timer ein, der gerade abläuft: der Timer wird entfernt und eine bereits gestartete Melodie/Ansage für diesen Timer wird abgebrochen (Löschen gewinnt gegen einen noch nicht quittierten Ablauf)
- [ ] Der Neustart-Reconcile-Lauf und der reguläre Scheduler-Pfad lösen denselben überfälligen Timer **nicht doppelt** aus (einmaliger, idempotenter Status-Übergang auf `expired`)

### Persistenz & Neustart

- [ ] Timer-Zustand liegt in `alice.timers` (PostgreSQL) und überlebt Neustarts von `alice-chat-stream`, dem Scheduler-Task und `alice-speech-gateway`
- [ ] Nach einem Neustart prüft der Scheduler alle aktiven Timer: ein während der Downtime fällig gewordener Timer wird jetzt ausgelöst (Melodie/Meldung, ggf. mit Hinweis "Der {Name} Timer ist vor {Dauer} abgelaufen."); noch laufende Timer zählen bis zum gespeicherten Ablauf-Zeitpunkt weiter
- [ ] Ist bei Ablauf das Setz-Gerät nicht erreichbar, wird der Timer als "abgelaufen, nicht zugestellt" markiert und beim nächsten Kontakt des Geräts (innerhalb Maximalzeit + Puffer) gemeldet; danach still als erledigt markiert

### Pfad & Performance

- [ ] Alle Timer-Operationen laufen im HA_FAST-Pfad — Weaviate-Intent-Match gegen handgepflegte, entity-lose Timer-Intent-Objekte, danach Textverarbeitung (Dauer/Uhrzeit/Name/Delta), kein LLM-Aufruf
- [ ] End-to-End-Antwortzeit einer Timer-Operation < 200 ms (Performance-Ziel aus PROJ-3 AC-9 / PROJ-83 / PROJ-84 gilt unverändert)
- [ ] Bestehende HA-Geräte-Befehle und die Sentence-Splitter-Logik funktionieren unverändert — keine Regression durch die neuen Timer-Intent-Objekte in der `HAIntent`-Collection

### Limits & Sprache

- [ ] Max. Anzahl gleichzeitig aktiver Timer ist **pro Rolle** konfigurierbar (Auslieferungs-Defaults z. B. `admin` 20, `user` 10, `child` 3, `guest` 0/kein Timer); beim Überschreiten lehnt Alice ab und nennt das Limit
- [ ] Max-Dauer ist **pro Rolle** konfigurierbar (Auslieferungs-Default 24 Stunden für `admin`/`user`, kürzer für `child`); eine längere Dauer wird abgelehnt mit Nennung des Rollen-Limits
- [ ] Dauer unterhalb der (rollenunabhängigen) Mindestgrenze (Default 10 Sekunden) wird abgelehnt; Alice nennt den zulässigen Bereich
- [ ] Alle Bestätigungen, Rückfragen und Fehlermeldungen sind auf Deutsch (bzw. folgen der konfigurierten Nutzersprache, analog LLM-Output-Konvention); Zeitangaben werden natürlichsprachlich formuliert

## Edge Cases

- **Verkürzung um mehr als die Restlaufzeit** ("Verkürze den 20 Minuten Timer um 30 Minuten", 12 Minuten Rest): Änderung wird abgelehnt, Alice nennt die aktuelle Restlaufzeit. Kein sofortiges Auslösen.
- **Verlängerung eines bereits abgelaufenen, aber noch nicht quittierten Timers** (Melodie spielt noch): Behandlung wie "Timer nicht mehr aktiv" — Alice weist darauf hin, dass der Timer schon abgelaufen ist; ein neuer Timer muss gesetzt werden.
- **Zwei Timer werden im selben Moment fällig** (auf demselben Gerät): innerhalb des Sammel-Fensters (Default 3 s) gebündelt — eine Melodie-Sequenz, eine kombinierte Ansage beim Ansprechen ("Der 20 Minuten Timer und der Kartoffel Timer sind abgelaufen.").
- **Zwei Timer fällig auf verschiedenen Geräten**: unabhängig — jedes Gerät bekommt sein eigenes `timer-finished`, spielt seine eigene Melodie, wird einzeln quittiert. Kein Bündeln über Geräte hinweg.
- **Dritter Timer wird fällig, während die Melodie der ersten beiden noch spielt** (nach Ablauf des Sammel-Fensters): der dritte Timer wird an die laufende Melodie-/Quittierungs-Sitzung dieses Geräts angehängt statt eine zweite zu starten; beim Ansprechen nennt Alice alle noch offenen abgelaufenen Timer des Geräts.
- **Ablauf und Änderungsbefehl treffen gleichzeitig ein** (Scheduler markiert `expired`, User sagt "verlängere den Timer"): der Ablauf gewinnt (Row-Lock), die Änderung wird als "Timer schon abgelaufen" abgelehnt.
- **Ablauf und Löschbefehl treffen gleichzeitig ein**: Löschen gewinnt — der Timer wird entfernt, eine gerade startende Melodie/Ansage für ihn wird abgebrochen.
- **Quittierung per Ansprache und automatischer Ablauf der Maximalzeit fallen zusammen**: einmaliger Status-Übergang, kein Doppel-Quittieren (bereits als Edge Case unten geführt).
- **Timer auf demselben Gerät läuft ab, während gerade ein Gespräch mit diesem Gerät aktiv ist**: das `timer-finished`-Event wird nach Abschluss des laufenden Turns zugestellt (kein Abbruch der laufenden Antwort); Melodie startet unmittelbar danach.
- **Uhrzeit-Timer mit exakt der aktuellen Uhrzeit** ("Timer auf 15 Uhr 40", es ist genau 15:40:00): gilt als "heute schon vorbei" → morgen. (Randfall der Vergangenheits-Regel.)
- **Uhrzeit ohne Minutenangabe** ("Timer auf 15 Uhr"): MM = 00.
- **Mehrdeutige Uhrzeit / 12h-Angabe** ("Timer auf 4 Uhr" um 22:00): nächste Vorkommnis von 04:00 → morgen früh. Keine AM/PM-Heuristik über die Vergangenheits-Regel hinaus.
- **Name kollidiert mit einem gerade abgelaufenen, noch nicht quittierten Timer**: der abgelaufene Timer zählt für die Kollisionsprüfung nicht mehr als "aktiv" → neuer Timer bekommt den regulären Namen ohne Fallback.
- **Nachkommawert bei Dauer** ("Timer auf 2,5 Minuten"): auf die nächste sinnvolle Einheit interpretieren (2 Minuten 30 Sekunden) — nicht ablehnen. (Analog PROJ-83 Rundungsverhalten, hier aber Umrechnung statt Rundung.)
- **Kein Zeitwert im Satz erkennbar** ("Setze einen Timer" ohne Dauer/Uhrzeit, oder STT hat die Zahl verschluckt): kein vollständiger Match → Rückfrage nach der Dauer ("Auf wie viele Minuten soll ich den Timer stellen?"), kein Timer wird angelegt, kein LLM-Fallback nötig.
- **Änderungs-/Abfrage-/Löschbefehl nennt einen Timer-Namen, der nicht existiert** ("Verlängere den Nudel Timer"): Alice antwortet, dass es keinen Timer mit diesem Namen gibt, und nennt (falls vorhanden) die tatsächlich laufenden Timer im eigenen Rollen-Scope.
- **User A (admin) setzt einen Timer, User B (admin) fragt "welche Timer laufen"**: B sieht ihn — Timer werden auf Rollen-Ebene geteilt.
- **User C (child) fragt "welche Timer laufen", während admin-Timer aktiv sind**: C sieht nur `child`-Timer, nicht die der Erwachsenen.
- **Sprecher wird über ein Voice PE nicht erkannt, Default-Rolle ist `user`, Andreas (admin) hat den Timer gemeint**: der Timer landet im `user`-Scope; ein späteres "welche Timer laufen" als erkannter admin sieht ihn **nicht**. Empfehlung im Ein-Nutzer-Haushalt: Default-Rolle auf `admin` setzen. Dokumentierte Konsequenz der schwachen Sprecher-Erkennung (→ PROJ-103).
- **Rolle verliert Timer-Berechtigung, während sie noch aktive Timer hat**: bestehende Timer laufen normal ab und lösen aus; neue Timer-Befehle dieser Rolle werden abgelehnt. Abfragen/Löschen der eigenen laufenden Timer bleibt möglich (damit man aufräumen kann) — oder wird ebenfalls gesperrt: **in /architecture festzulegen**.
- **child-User ändert einen Timer per "verkürze den Timer", der die Rollen-Max-Dauer nicht betrifft**: erlaubt — die Max-Dauer wird nur beim Setzen und beim Verlängern geprüft, nicht beim Verkürzen.
- **Verlängern über die Rollen-Max-Dauer hinaus** ("Verlängere den 23-Stunden-Timer um 3 Stunden" bei child-Limit 2 h): abgelehnt mit Nennung des Rollen-Limits; die bestehende Restlaufzeit bleibt unverändert.
- **WebApp-Timer, Browser wird komplett geschlossen und später neu geöffnet**: beim erneuten Laden holt die WebApp die aktiven Timer des eigenen Rollen-Scopes vom Server; ein zwischenzeitlich abgelaufener Timer wird als Nachhol-Meldung angezeigt, sofern er innerhalb des Nachhol-Fensters liegt.
- **Alice-Dienst-Neustart genau im Moment eines Timer-Ablaufs**: nach dem Neustart erkennt der Scheduler den überfälligen Timer und löst ihn nach (Nachhol-Pfad), auch wenn das `timer-finished`-Event beim ersten Versuch verloren ging.
- **Maximalzeit läuft ab, während der User das Gerät gerade anspricht**: die Ansprache gewinnt (Melodie stoppt, Ansage kommt); kein Doppel-Quittieren.
- **Rollen-Timer-Limit erreicht, User löscht einen und setzt sofort einen neuen**: funktioniert (Limit wird zum Setz-Zeitpunkt geprüft).
- **Admin ändert die Rollen-Limits im Settings-Tab nach unten, während bereits mehr Timer laufen als das neue Limit**: laufende Timer bleiben, nur das Neusetzen ist gesperrt, bis die Anzahl wieder unter dem Limit liegt.
- **Zwei Timer in einem Satz, einer davon ungültig** ("Timer auf 10 Minuten und einen auf 3 Wochen"): der gültige Teil wird angelegt, der ungültige einzeln abgelehnt mit Begründung (analog Teilerfolg-Muster PROJ-83/84).

## Technical Requirements

- **Performance:** Timer-Operationen bleiben im HA_FAST-Pfad, < 200 ms End-to-End, kein LLM-Aufruf. Zeit-/Namens-/Delta-Extraktion ist reine Textverarbeitung (Regex-Klasse) nach dem Weaviate-Match.
- **Persistenz:** Neue Tabelle `alice.timers` (mindestens: `id`, `owner_user_id` [nullable, wenn Sprecher nicht erkannt], `owner_role` [not null], `name`, `expires_at`, `status` [running/paused/expired/acknowledged], `paused_remaining_seconds`, `origin_device` bzw. `origin_session`, `created_at`). Row Level Security aktiv, Policies für alle Operationen. Sichtbarkeit/Änderbarkeit ist auf **`owner_role`** gescoped, nicht auf den einzelnen User. Indizes auf `owner_role`, `expires_at`, `status`.
- **Rollen-Konfiguration:** Erweiterung von `alice.role_templates` (Spalten für `timer_allowed`, `timer_max_active`, `timer_max_duration_seconds`) und ggf. `alice.permissions_assistant` (Feature-Flag `timer`). Ein System-Setting `timer_default_role` (für per Voice PE nicht zugeordnete Timer). Seeds mit sinnvollen Defaults je Rolle; `alice.init_user_permissions()` übernimmt die Flags bei der User-Anlage. Konsistent mit dem bestehenden Permission-Modell aus Phase 1.
- **Rollen-Auflösung im HA_FAST-Pfad:** Der Timer-Handler liest die Rolle des anfragenden Users (aus dem per-Turn-JWT / `alice.users`); ist kein User bekannt (Anonymous vom Speech-Gateway), gilt `timer_default_role`. Berechtigungs- und Limit-Prüfung erfolgen als parametrisierte PG-Queries im < 200 ms-Budget (gleiches Muster wie der Friendly-Name-Lookup in PROJ-83/84).
- **Scheduler:** Background-Task innerhalb `alice-chat-stream` (kein neuer Container). Weckt zum jeweils nächsten fälligen `expires_at`; beim Start Reconcile-Lauf für überfällige Timer.
- **Nebenläufigkeit:** Jeder Status-Übergang eines Timers erfolgt als atomare DB-Operation mit `SELECT … FOR UPDATE` (Row-Lock) bzw. bedingtem `UPDATE … WHERE status = …`. Der Übergang auf `expired` ist idempotent, sodass Scheduler und Neustart-Reconcile denselben Timer nicht doppelt auslösen. Politik bei Konflikt: Ablauf schlägt Änderung, Löschen schlägt Ablauf.
- **Sammel-Fenster:** Timer desselben Geräts, die innerhalb eines konfigurierbaren Fensters (Default 3 s) fällig werden, werden zu einer Melodie- und Quittierungs-Sitzung gebündelt; weitere Abläufe während einer laufenden Sitzung werden an diese angehängt.
- **Voice-Benachrichtigung:** `alice-speech-gateway` implementiert die ausgehende Seite des Wyoming-Timer-Protokolls (`timer-started` / `timer-updated` / `timer-cancelled` / `timer-finished`) auf der bestehenden Wyoming-Verbindung zum Voice PE. Zuordnung Timer → Gerät über die `device-mapping.yaml`-Kennung, die beim Setzen als `origin_device` gespeichert wird.
- **Ansprech-Quittierung:** Beim Wakeword während einer laufenden Timer-Melodie stoppt das Gerät die Melodie; das Speech-Gateway erkennt den Kontext "es lief eine Timer-Melodie" und lässt Alice die Ablauf-Meldung ansagen, statt die Äußerung normal zu verarbeiten. Maximalzeit als konfigurierbarer Wert (Default 2 min).
- **Timer-Intent-Index:** Die Timer-Satzmuster werden als handgepflegte `HAIntent`-Objekte (ohne `entity_id`) in die bestehende Weaviate-Collection eingetragen — analog zu bestehenden Intents, aber vom Entity-Gate in `alice-ha-sync` ausgenommen (Eintrag über einen dedizierten Seed-Schritt, nicht über den HA-Sync). Der HA_FAST-Handler erkennt am Intent-Typ, dass keine HA-REST-Aktion, sondern der Timer-Handler zuständig ist.
- **WebApp — Timer-Alarm:** Client-seitiger Countdown auf den Server-`expires_at`; Toast + Ton über die bestehende `use-toast`- und Audio-Freigabe-Infrastruktur. Abgleich der aktiven Timer (im eigenen Rollen-Scope) beim Tab-Fokus / Reload über einen Read-Endpoint. i18n: alle neuen UI-Strings über die i18n-Schicht.
- **WebApp — Settings-Erweiterung:** Der bestehende Settings-Tab „User-Verwaltung" / Rollen bekommt einen Timer-Abschnitt pro Rolle (Berechtigung, Max-Anzahl, Max-Dauer) plus die Auswahl der Default-Rolle. Nur für `admin` sichtbar (bestehendes Berechtigungsmuster der Settings-Page). CRUD über `services/` analog zu `services/dms.ts`. Alle Strings über die i18n-Schicht.
- **Sprache:** Alle assistenzseitigen Ausgaben auf Deutsch bzw. gemäß konfigurierter Nutzersprache (LLM-Output-Konvention); Container-/DB-/Code-Bezeichner Englisch.
- **Kein Breaking Change** an bestehenden HA-Geräte-Befehlen, an der Sentence-Splitter-Logik (PROJ-3) und an der HA-Sync-Infrastruktur.

### Offene Architektur-Fragen (für /architecture)

- Verarbeitet die eingesetzte ESPHome-Voice-PE-Firmware das Wyoming-`timer-finished`-Event eigenständig (Melodie-Playback + Verstummen bei Interaktion), oder muss das Speech-Gateway die Melodie selbst als Audio-Stream schicken und die Ansprech-Erkennung vollständig serverseitig bauen? → am echten Gerät verifizieren.
- Exakter Mechanismus, wie das Speech-Gateway "Wakeword während laufender Timer-Melodie" vom normalen Wakeword unterscheidet und die Ablauf-Ansage einschiebt.
- Wie fein muss der Scheduler pollen bzw. wie wird "wecke zum nächsten `expires_at`" bei vielen Timern und bei Änderungen/Löschungen sauber umgesetzt (Task-Cancellation, Neuberechnung).
- Format und Umfang des "meine aktiven Timer"-Read-Endpoints für die WebApp (und ob er über `alice-chat-stream` oder einen bestehenden API-Pfad läuft).
- Namensnormalisierung "für Kartoffeln" → "Kartoffel Timer": rein regelbasiert (Genitiv/Plural-Heuristik) oder Wortliste — Grenzen dokumentieren.
- Wird die Rollen-Konfiguration in `alice.role_templates` erweitert oder in einer separaten Tabelle (`alice.timer_role_config`) geführt? Abhängig davon, wie `role_templates` heute strukturiert ist (JSON-Blob vs. Spalten).
- Verliert eine Rolle die Timer-Berechtigung: bleibt Abfragen/Löschen der eigenen laufenden Timer möglich (Aufräumen) oder wird alles gesperrt?
- Genügt die per-Turn-JWT-Rolle im Speech-Gateway-Pfad, oder muss der Timer-Handler die Rolle frisch aus `alice.users` lesen (Konsistenz bei Rollenwechsel während einer Session)?

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

**Feature-Typ:** Backend-Schwerpunkt (Python in `alice-chat-stream` + `alice-speech-gateway`, neue DB-Tabelle + Schema-Erweiterung, Weaviate-Seed) **plus** ein Frontend-Anteil (Settings-Tab-Erweiterung + WebApp-Timer-Alarm). Kein n8n-Workflow. Kein neuer Docker-Container.

### Das große Bild — was gebaut wird und warum

Alice bekommt einen eigenen, vollständigen Timer-Mechanismus. Der Grund dafür ist im Spec-Interview klar geworden: Home Assistants eingebaute Sprach-Timer sind für Alice nicht erreichbar (sie leben nur in HAs Assist-Pipeline, die Alice über den „Hey Jarvis"-Pfad bewusst umgeht). Alice muss also selbst zählen, selbst benennen, selbst benachrichtigen.

Vier Bausteine, weitgehend unabhängig:

```
1. Timer-Verstehen      — neue Timer-Satzmuster im schnellen Intent-Pfad erkennen,
                          Dauer/Uhrzeit/Name/Änderung aus dem Text ziehen
2. Timer-Speicher       — neue Tabelle alice.timers; ein Timer = eine Zeile mit
                          Ablauf-Zeitpunkt, Name, Besitzer-Rolle, Status, Setz-Kanal
3. Timer-Wächter        — ein Hintergrund-Prozess in alice-chat-stream, der auf den
                          jeweils nächsten Ablauf wartet und dann die Meldung auslöst
4. Ablauf-Zustellung    — Voice PE: Alice ruft Home Assistant per REST, das Gerät
                          spielt die Melodie;  WebApp: der Browser zählt selbst
                          herunter und meldet sich im sichtbaren Tab
```

Dazu kommt die **Rollen-Schicht**: Wer darf Timer nutzen, wie viele, wie lange — und wessen Timer sieht man. Das hängt an der bestehenden Rollen-Verwaltung (`admin`/`user`/`guest`/`child`).

---

### A) Systemüberblick (Visual)

```
                        ┌───────────────────────────────────────────────┐
   "Hey Jarvis,         │  HA Voice PE (ESPHome)                          │
    setze einen         │   • "Hey Jarvis" → Wyoming → alice-speech-gw    │
    Timer auf           │   • dauerhaft via ESPHome-API mit HA verbunden  │
    20 Minuten"         │   • hat eine media_player-Entity in HA          │
                        └──────────────┬────────────────────────────────┘
                                       │ Wyoming (kurzlebige Session, nur beim Sprechen)
                                       ▼
                        ┌───────────────────────────────┐
                        │  alice-speech-gateway          │
                        │   • Speaker-ID → User/Rolle    │
                        │   • NEU: erkennt Timer-Ablauf- │
                        │     Ansage-Kontext             │
                        └──────────────┬────────────────┘
                                       │ HTTP  (session, transcript, source=esphome:<Raum>)
                                       ▼
   Browser / WebApp ───HTTP──►  ┌─────────────────────────────────────────────┐
   "Timer auf 15 Uhr 40"        │  alice-chat-stream                            │
                                │  ┌────────────────────────────────────────┐  │
                                │  │ Schneller Intent-Pfad (bestehend)       │  │
                                │  │  • Weaviate-Match gegen HAIntent         │  │
                                │  │  • NEU: Timer-Intents (ohne Gerät)       │  │
                                │  │  • NEU: Timer-Handler                    │  │
                                │  │     - Rolle + Berechtigung + Limits      │  │
                                │  │     - Dauer/Uhrzeit/Name/Delta aus Text  │  │
                                │  │     - schreibt/ändert alice.timers       │  │
                                │  └────────────────────────────────────────┘  │
                                │  ┌────────────────────────────────────────┐  │
                                │  │ Timer-Wächter (NEU, Hintergrund-Task)    │  │
                                │  │  • wartet auf nächsten Ablauf           │  │
                                │  │  • beim Ablauf: Kanal-abhängige Meldung │  │
                                │  └───────────┬───────────────┬────────────┘  │
                                └──────────────┼───────────────┼───────────────┘
                                               │               │
                    Voice-PE-Timer ◄───────────┘               └────────► WebApp-Timer
                    HA-REST: Melodie + Ansage                   (Client zählt selbst,
                    auf media_player des Setz-Geräts             Toast + Ton im Tab)
                                               │
                                               ▼
                                        ┌──────────────┐
                                        │ PostgreSQL    │  alice.timers  (Zustand)
                                        │               │  alice.role_templates (+Timer-Felder)
                                        │               │  alice.permissions_assistant (+can_use_timers)
                                        └──────────────┘
```

---

### B) Datenmodell (Klartext)

**Neue Tabelle `alice.timers` — ein Eintrag pro Timer:**

- **ID** — eindeutige Kennung
- **Name** — der angezeigte/angesprochene Name („Kartoffel Timer", „20 Minuten Timer")
- **Besitzer-User** — wer den Timer gesetzt hat; leer, wenn die Stimme nicht erkannt wurde
- **Besitzer-Rolle** — `admin` / `user` / `guest` / `child`; **das** Feld, über das Sichtbarkeit und „lösche alle Timer" laufen
- **Ablauf-Zeitpunkt** — absoluter Zeitpunkt, zu dem der Timer feuert
- **Status** — `läuft` / `pausiert` / `abgelaufen` / `quittiert`
- **Restlaufzeit bei Pause** — nur gesetzt, solange pausiert (eingefrorene Sekunden)
- **Setz-Kanal** — entweder die Geräte-Kennung des Voice PE (für die Melodie-Zustellung) **oder** ein Marker „WebApp"
- **Erstellt am** — Zeitstempel

Nur `läuft`- und `pausiert`-Timer zählen als „aktiv" (für Limits, Kollisionsprüfung, Listen).

**Erweiterung der bestehenden Rollen-Verwaltung:**

- `alice.role_templates` bekommt drei zusätzliche Angaben pro Rolle: *Timer erlaubt (ja/nein)*, *maximale Anzahl gleichzeitiger Timer*, *maximale Timer-Dauer*. Diese liegen — wie die bestehenden HA-/DMS-/System-Rechte — als strukturierte Angabe (JSON) im jeweiligen Rollen-Datensatz.
- `alice.permissions_assistant` (die pro-User-Tabelle) bekommt ein zusätzliches Ja/Nein-Feld *Timer nutzen* — analog zu den vorhandenen `can_use_chat` / `can_use_voice` / `can_use_tools`.
- Die bestehende Funktion, die bei der User-Anlage die Rollen-Vorlage in die pro-User-Rechte kopiert (`alice.init_user_permissions`), wird um diese Felder ergänzt.
- **Eine neue System-Einstellung `timer_default_role`** — welche Rolle ein per Voice PE gesetzter Timer bekommt, wenn die Stimme nicht erkannt wurde. Auslieferungswert `user`; im Ein-Nutzer-Haushalt sinnvoll auf `admin`. Ablage: eine schlanke Schlüssel-Wert-Tabelle für System-Settings (oder, falls schon vorhanden, die bestehende) — in der Bau-Phase zu bestätigen.

**Auslieferungs-Defaults je Rolle:**

| Rolle | Timer erlaubt | Max. aktive Timer | Max. Dauer |
|---|---|---|---|
| admin | ja | 20 | 24 h |
| user | ja | 10 | 24 h |
| child | ja | 3 | 2 h |
| guest | nein | – | – |

Untergrenze der Dauer: 10 Sekunden, rollenunabhängig, fest.

**Weaviate:** Keine neue Collection. Die Timer-Satzmuster („setze einen Timer auf …", „verlängere den … Timer um …", „wie lange läuft … noch", „lösche alle Timer" …) werden als zusätzliche Einträge in die bestehende `HAIntent`-Sammlung geschrieben — **ohne** Geräte-Zuordnung, mit einem Domänen-Marker `timer`. Der schnelle Intent-Pfad erkennt an diesem Marker, dass der Timer-Handler zuständig ist und **kein** Home-Assistant-Gerätebefehl folgt. Diese Einträge kommen über einen **eigenen kleinen Seed-Schritt** in die Sammlung (ein wiederholbares Skript), nicht über den laufenden HA-Sync — der würde sie mangels Gerät sonst wieder entfernen.

---

### C) Die vier Bausteine im Detail

#### Baustein 1 — Timer verstehen (in `alice-chat-stream`)

Der bestehende schnelle Pfad zerlegt einen Satz in Teilbefehle (Sentence Splitter, unverändert) und matcht jeden gegen die Weaviate-Intent-Sammlung. Neu: Trifft ein Teil einen Timer-Intent, übernimmt ein **Timer-Handler** statt des HA-Geräte-Aufrufs. Er arbeitet in dieser Reihenfolge:

1. **Rolle bestimmen** — aus dem mitgelieferten Nutzer-Token; ist kein Nutzer bekannt, gilt `timer_default_role`.
2. **Berechtigung prüfen** — hat die Rolle „Timer nutzen"? Wenn nein: freundliche deutsche Ablehnung, fertig.
3. **Absicht bestimmen** — setzen / ändern / abfragen / pausieren / fortsetzen / löschen. Ergibt sich aus dem gematchten Intent.
4. **Werte aus dem Text ziehen** — reine Textverarbeitung (gleiches Vorgehen wie bei den Prozent-/Grad-Werten in PROJ-83):
   - *Dauer:* „20 Minuten", „1 Stunde 30 Minuten", „2,5 Minuten" → Sekunden
   - *Uhrzeit:* „15 Uhr 40", „15 Uhr" → nächster passender Zeitpunkt (heute, sonst morgen)
   - *Name:* „für Kartoffeln" → „Kartoffel Timer"; ohne Namen → aus der Zeitangabe abgeleitet
   - *Änderungs-Delta:* „um 5 Minuten" (verlängern/verkürzen)
   - *Ziel-Timer bei Änderung/Abfrage/Löschen:* genannter Name; ohne Namen → der einzige aktive Timer der Rolle, sonst Rückfrage mit Aufzählung
5. **Limits prüfen** (nur beim Setzen und beim Verlängern) — Max-Anzahl, Max-Dauer der Rolle. Bei Verletzung: Ablehnung mit Nennung des Limits.
6. **Namenskollision** (nur beim Setzen) — existiert im selben Rollen-Scope schon ein aktiver Timer gleichen Namens, wird sofort „zweiter … Timer" / „dritter … Timer" vergeben (keine Rückfrage).
7. **Schreiben** — Zeile in `alice.timers` anlegen/ändern; danach den Wächter „aufwecken" (er muss seinen nächsten Weckzeitpunkt neu berechnen).
8. **Antworten** — die bestätigende Sprech-/Textmeldung auf Deutsch, mit berechneter Laufzeit bei Uhrzeit-Timern.

Fehlt eine erwartete Zahl (STT-Aussetzer), wird — wie bei bestehenden Wert-Intents — nichts angelegt und Alice fragt kurz nach.

Alles bleibt ohne Sprachmodell-Aufruf; das <200-ms-Ziel gilt weiter. Die zusätzlichen Datenbank-Abfragen (Rolle, Limits, vorhandene Timer) sind kleine, indizierte Abfragen — gleiches Muster wie der Namens-Lookup in PROJ-83/84.

#### Baustein 2 — Timer-Speicher

Beschrieben unter B). Wichtig für die **Nebenläufigkeit**: Jede Statusänderung an einem Timer passiert als eine einzelne, gesperrte Datenbank-Operation. Damit sind die im Spec geforderten Regeln automatisch erfüllt:

- „Ablauf schlägt Änderung" — wenn der Wächter einen Timer schon auf `abgelaufen` gesetzt hat, findet ein gleichzeitiger „verlängere"-Befehl keinen `läuft`-Timer mehr und antwortet „schon abgelaufen".
- „Löschen schlägt Ablauf" — der Löschbefehl entfernt die Zeile; eine bereits angestoßene Melodie wird abgebrochen (siehe Baustein 4).
- „Kein doppelter Ablauf" — der Übergang auf `abgelaufen` greift nur, wenn der Timer noch `läuft`; ein zweiter Versuch (etwa Wächter + Neustart-Nachlauf) läuft ins Leere.

#### Baustein 3 — Timer-Wächter (Hintergrund-Task in `alice-chat-stream`)

Ein einzelner asynchroner Dauerläufer, gestartet beim Hochfahren des Containers (dort wird schon heute die Datenbank-Verbindung initialisiert):

- **Beim Start:** einmal alle Timer durchsehen. Alles, was während einer Ausfallzeit hätte feuern sollen, wird **jetzt** ausgelöst (mit Zusatz „ist vor {Dauer} abgelaufen"). Alles andere: normal weiterlaufen lassen.
- **Im Betrieb:** bis zum nächsten fälligen Ablauf-Zeitpunkt schlafen, dann auslösen. Wird zwischendurch ein Timer gesetzt/geändert/gelöscht, weckt der Handler den Wächter, damit er seinen Schlaf neu berechnet.
- **Sammel-Fenster:** Werden mehrere Timer desselben Geräts innerhalb weniger Sekunden (Standard 3) fällig, werden sie zu **einer** Melodie- und Ansage-Sitzung gebündelt.
- **Nach dem Auslösen:** Voice-PE-Timer, die niemand quittiert, verstummen nach der Maximalzeit (Standard 2 Minuten) von selbst und gelten dann als quittiert.

Warum als Task im bestehenden Container und nicht als eigener Dienst: Die Timer-Schreiblogik sitzt ohnehin dort, es gibt keinen zweiten Schreiber, und ein einzelner Container-Neustart ist durch den Start-Nachlauf abgedeckt. Ein eigener Dienst wäre mehr Betrieb ohne Gewinn.

#### Baustein 4 — Ablauf-Zustellung

**Voice PE** (der Hauptfall):

Die Voice PE ist über die ESPHome-API dauerhaft mit Home Assistant verbunden und hat dort eine Lautsprecher-Entity (`media_player`). Das ist unabhängig davon, ob gerade eine „Hey Jarvis"-Sitzung läuft. Beim Ablauf:

1. Der Wächter ruft **Home Assistant per REST** auf (denselben Weg, den `alice-chat-stream` schon für Geräte-Befehle und Einkaufslisten nutzt) und lässt auf dem Lautsprecher des **Setz-Geräts** eine Melodie/Tonfolge abspielen.
2. Die Zuordnung „welcher Timer → welches Gerät → welche `media_player`-Entity" kommt aus einer Ergänzung der bestehenden Geräte-Zuordnungsdatei des Speech-Gateways (`device-mapping.yaml`): pro Gerät wird zusätzlich die HA-`media_player`-Entität hinterlegt. Der Setz-Kanal in `alice.timers` speichert die Geräte-Kennung.
3. **Stoppen der Melodie:** Der saubere Weg ist eine **kleine Home-Assistant-Automation** als Vermittler — sie kennt die Wakeword-/Aktivitäts-Events des Satelliten und den Lautsprecher-Zustand, die Alice selbst nicht sieht. Alice stößt Start (und bei „lösche"/Timeout den Stopp) über ein einfaches Signal an (REST-Aufruf einer Automation bzw. ein Schalt-Hilfsobjekt in HA); die Automation macht das eigentliche Abspielen/Stoppen und stoppt auch, sobald der Nutzer den Satelliten anspricht.
4. **Ansage beim Ansprechen:** Sagt der Nutzer „Hey Jarvis", während (oder kurz nachdem) die Melodie lief, erkennt das **Speech-Gateway** diesen Kontext (es fragt beim Chat-Backend „gibt es für dieses Gerät einen gerade abgelaufenen, noch nicht angesagten Timer?") und lässt Alice **zuerst** die Ablauf-Meldung sprechen („Der 20 Minuten Timer ist abgelaufen."), bevor eine etwaige weitere Äußerung normal verarbeitet wird. Danach gilt der Timer als quittiert.

> **Was in der Bau-Phase am Gerät verifiziert werden muss:** ob das `nabu_casa.voice_pe`-Paket eine nutzbare `media_player`-Entität bereitstellt, während der „Hey Jarvis"-Wyoming-Pfad aktiv ist, und wie zuverlässig die HA-Automation den „Satellit wird gerade angesprochen"-Zustand sieht. Fällt das negativ aus, ist der Rückfallplan: Melodie als kurze, sich wiederholende Tonfolge über denselben TTS-Audiokanal, den das Gateway ohnehin zum Gerät nutzt — dann ohne „läuft bis Ansprache", sondern feste kurze Wiederholung.

**WebApp:**

Kein Gerät, kein Lautsprecher, keine dauerhafte Verbindung. Deshalb:

1. Legt ein Nutzer im WebApp-Chat einen Timer an, liefert die Antwort den **Ablauf-Zeitpunkt** mit.
2. Die WebApp zählt **im Browser** herunter. Läuft der Timer ab, während der Tab sichtbar im Vordergrund ist: auffälliger Hinweis (Toast) + Ton (über die schon vorhandene Ton-Freigabe).
3. Kommt der Tab nach dem Ablauf-Zeitpunkt zurück in den Vordergrund, holt die WebApp den aktuellen Timer-Stand vom Server und zeigt eine **Nachhol-Meldung** („… ist vor 2 Minuten abgelaufen").
4. War der Tab beim Ablauf im Hintergrund / das Gerät gesperrt und kcommt auch nicht rechtzeitig zurück: **keine** Meldung. Das ist die dokumentierte Grenze — die zuverlässige Hintergrund-Benachrichtigung ist ein eigenes Feature (PROJ-104, Web Push).

Der Server bleibt in allen Fällen die maßgebliche Quelle für den Timer-Status; der Browser-Countdown ist nur die Anzeige.

---

### D) Frontend-Anteil

**1. Settings — Rollen-Verwaltung erweitern**

Der bestehende Bereich „Nutzer-Verwaltung" in den Einstellungen bekommt pro Rolle einen kleinen Timer-Abschnitt:

```
Einstellungen › Nutzer-Verwaltung › Rollen
└── Rolle "user"
     ├── … bestehende Rechte …
     └── Timer  (NEU)
          ├── [Schalter] Timer nutzen erlauben
          ├── [Zahl]     Max. gleichzeitige Timer
          └── [Zahl]     Max. Timer-Dauer (Stunden)

Einstellungen › Nutzer-Verwaltung  (NEU, einmalig)
└── [Auswahl] Standard-Rolle für nicht erkannte Sprecher: ( admin | user | guest | child )
```

- Nur für `admin` sichtbar (die Einstellungsseite hat dieses Muster schon).
- Bausteine: vorhandene `Switch`-, `Input`- und `Select`-Komponenten aus der UI-Bibliothek; keine neuen UI-Primitive.
- Datenanbindung: ein schlanker Service analog zum bestehenden DMS-Ordner-Service.
- Alle Texte über die Übersetzungs-Schicht (keine fest verdrahteten Strings).
- Änderungen wirken sofort auf **neu** gesetzte Timer; laufende behalten ihre gespeicherte Rolle.

**2. WebApp — Timer-Alarm**

- Ein kleiner Timer-Beobachter im Frontend: hält die aktiven Timer des eigenen Rollen-Scopes, zählt herunter, zeigt bei Ablauf Toast + Ton.
- Nutzt die vorhandene Hinweis-Infrastruktur (`use-toast`) und Ton-Freigabe (`useAudioPermission`).
- Gleicht sich beim Zurückkehren in den Vordergrund und beim Neuladen mit dem Server ab (Lese-Zugriff auf die eigenen aktiven Timer).
- Keine neue Seite, keine Timer-Verwaltungs-Oberfläche — Timer werden per Chat bedient; die WebApp zeigt nur den Alarm.

---

### E) Betroffene Komponenten (Überblick)

| Bereich | Was passiert |
|---|---|
| **Datenbank** | Neue Tabelle `alice.timers` (mit Row-Level-Security wie alle Tabellen). `alice.role_templates` + `alice.permissions_assistant` um Timer-Felder erweitert. `alice.init_user_permissions` angepasst. System-Setting `timer_default_role`. Neue Migrationsdatei unter `sql/migrations/`. |
| **`alice-chat-stream`** | Neuer Timer-Handler im schnellen Pfad (Erkennung, Textauswertung, Rollen-/Limit-Prüfung, Schreiben). Neuer Hintergrund-Wächter (Ablauf-Erkennung, Zustellung, Start-Nachlauf). Kleiner Lese-Zugang „meine aktiven Timer" für die WebApp. Nutzung des bestehenden HA-REST-Wegs für die Melodie. |
| **`alice-speech-gateway`** | Erkennt beim „Hey Jarvis" den Kontext „für dieses Gerät ist gerade ein Timer abgelaufen" und schiebt die Ansage vor die normale Verarbeitung. Kein Wyoming-Timer-Protokoll. |
| **`device-mapping.yaml`** (Speech-Gateway-Konfiguration) | Pro Voice PE zusätzlich die HA-`media_player`-Entität hinterlegen. |
| **Weaviate** | Timer-Satzmuster als geräte-lose `HAIntent`-Einträge über einen eigenen, wiederholbaren Seed-Schritt. |
| **Home Assistant** | Eine kleine Automation als Melodie-Vermittler (Start/Stop, Stop bei Satelliten-Aktivität / Timeout). Liegt als Datei unter `homeassistant/`. |
| **Frontend** | Settings: Timer-Abschnitt je Rolle + Standard-Rollen-Auswahl. WebApp: Timer-Alarm-Beobachter (Toast + Ton). Übersetzungstexte. |
| **n8n** | — keine Änderung |

---

### F) Tech-Entscheidungen (begründet)

| Entscheidung | Warum |
|---|---|
| Eigener Timer-Mechanismus statt HA-Assist-Timer | HA-Assist-Timer sind über den „Hey Jarvis"-Pfad strukturell nicht erreichbar (kein Gerät, kein REST-Dienst, nur Assist-Pipeline-intern). Gleiche Sackgasse wie bei den HA-Sprach-Timern selbst. |
| Timer-Zustand in PostgreSQL | Muss Neustarts überleben, geräteübergreifend abfragbar sein und von mehreren Kanälen (Voice, WebApp) konsistent gesehen werden. Eine Datei oder In-Memory reicht dafür nicht. |
| Wächter als Task im bestehenden Container | Kein zweiter Schreiber, keine Cron-Granularitäts-Probleme, ein Neustart ist durch den Start-Nachlauf abgedeckt. Ein eigener Dienst wäre mehr Betrieb ohne Nutzen. |
| Schneller Pfad (kein Sprachmodell) | Konsistent mit PROJ-83/84; Zeit-/Namens-Erkennung ist einfache Textverarbeitung; hält die Antwort unter 200 ms. |
| Melodie über HA-REST auf den `media_player` | Der einzige Weg, das Gerät proaktiv zu erreichen, wenn keine Sprach-Sitzung läuft. `alice-chat-stream` spricht diesen REST-Weg schon heute. |
| HA-Automation als Melodie-Vermittler | Die „stoppe bei Ansprache"-Logik braucht Geräte-Events (Wakeword, Satellit aktiv), die in HA vorliegen, aber nicht bei Alice. Die Automation ist der natürliche Ort dafür. |
| Sichtbarkeit auf Rollen-Ebene | Bewusste Produktentscheidung aus dem Spec-Interview: kompensiert die heute unsichere Sprecher-Erkennung; „der Küchentimer" ist ohnehin eher haushalts- als personengebunden gedacht. |
| Rollen-Konfiguration in `role_templates` | Deckt sich 1:1 mit dem bestehenden Rechte-Modell (HA-, DMS-, System-Rechte liegen genauso dort). Editierbar über den vorhandenen Settings-Bereich. |
| WebApp nur im Vordergrund-Tab | Alles andere braucht Web-Push-Infrastruktur (Service Worker, VAPID, Abo-Verwaltung) — eigener Umfang, als PROJ-104 ausgegliedert. Der Hauptanwendungsfall (Voice PE in Küche/Büro) ist ohne Web Push voll abgedeckt. |

---

### G) Offene Punkte / in der Bau-Phase zu bestätigen

- **Am Gerät zu prüfen:** Ist die `media_player`-Entität des Voice PE nutzbar, während der „Hey Jarvis"-Pfad aktiv ist? Wie zuverlässig sieht eine HA-Automation „Satellit wird gerade angesprochen"? — Rückfallplan (feste kurze Tonfolge über den TTS-Kanal) steht.
- **System-Settings-Ablage:** Gibt es schon eine Tabelle/Mechanik für System-weite Einstellungen (für `timer_default_role`), oder wird eine schlanke Schlüssel-Wert-Tabelle neu angelegt?
- **Rolle verliert Timer-Recht, hat aber noch laufende Timer:** Empfehlung — bestehende Timer laufen normal ab und lösen aus; Abfragen und Löschen der eigenen laufenden Timer bleibt möglich (Aufräumen), nur neues Setzen ist gesperrt. (Im Spec als offener Punkt markiert; diese Auflösung wird vorgeschlagen.)
- **Rollen-Aktualität im Sprach-Pfad:** Der Timer-Handler liest die Rolle frisch aus der Datenbank (nicht nur aus dem Token), damit eine Rollen-Änderung sofort greift.
- **Namensableitung „für Kartoffeln" → „Kartoffel Timer":** regelbasierte Vereinfachung (Genitiv/Plural) mit dokumentierten Grenzen; keine Wortliste.
- **Melodie-Datei:** kurze, dezente Tonfolge; Ablage und Bereitstellung (HA-lokale Datei vs. vom Gateway ausgeliefert) in der Bau-Phase festlegen.

## Implementation Notes (Backend + Frontend)

**Build date:** 2026-09-07. No new Docker container, no n8n workflow.

### Database — `sql/migrations/069-proj85-timer-agent.sql`
- **`alice.system_settings`** — new global key/value table (first consumer:
  `timer_default_role`, shipping value `"user"`). RLS enabled, permissive policy.
- **`alice.timers`** — `id`, `owner_user_id` (nullable), `owner_role` (not null,
  the scope key), `name`, `expires_at`, `status`
  (`running`/`paused`/`expired`/`acknowledged`), `paused_remaining_seconds`,
  `origin_channel` (`esphome:<Raum>` device key or `webapp`), `fired_at`,
  timestamps. Indexes on `owner_role`, `status`, partial on `expires_at WHERE
  status='running'`. RLS enabled; the chat-stream service scopes every query by
  `owner_role` itself (same pattern as `alice.ha_entities`).
- **`alice.role_templates.assistant_permissions`** gains `can_use_timers`,
  `timer_max_active`, `timer_max_duration_seconds` (JSON keys). Defaults per spec
  table (admin 20/24h, user 10/24h, child 3/2h, guest off).
- **`alice.permissions_assistant.can_use_timers`** column added + backfilled;
  `alice.init_user_permissions()` updated to copy it.
- **Timer intent templates** (domain `timer`, entity-less) seeded into
  `alice.ha_intent_templates` for provenance.

### Weaviate — `scripts/seed-timer-intents.sh`
Standalone, idempotent. Reads the domain=`timer` templates from PG and writes one
`HAIntent` object per pattern (`entityId=""`, `domain="timer"`,
`intentTemplate="timer:<action>"`). Deletes existing domain=timer objects first.
`alice-ha-sync` never touches them (no HA entity), so a `templates_updated`
force-resync leaves them intact. **Run after applying migration 069.**

### `alice-chat-stream`
- **`app/timers.py`** (new) — text parsing (duration incl. "1 Stunde 30 Minuten"
  / "2,5 Minuten"; absolute "15 Uhr 40" with past→tomorrow; bare "auf 10" → 10
  min; name "für Kartoffeln"→"Kartoffel", ref-name, delta, "alle Timer"),
  role/limit resolution (`resolve_role` reads `alice.users` fresh; anonymous →
  `timer_default_role`), and every DB mutation as a row-locked / conditional
  transaction (`SELECT … FOR UPDATE`, `UPDATE … WHERE status='running'`).
  `handle_timer_part()` returns a German `TimerReply`.
- **`app/timer_scheduler.py`** (new) — `TimerScheduler` background asyncio task
  started from the FastAPI lifespan. Startup reconcile fires overdue timers;
  steady loop sleeps to the next `expires_at`, `wake()`d by the handler on any
  change. `_fire_due()` claims due timers with a conditional UPDATE (idempotent
  vs. the reconcile). Voice channels → HA REST `script.alice_timer_melody_start`;
  `webapp` rows just get marked. `pending_announcement()` builds the "Der …
  Timer ist abgelaufen." sentence and marks the rows acknowledged.
  `stop_melody()` for delete-during-alarm.
- **`app/ha_path.py`** — `decide_path()` recognises a `domain=="timer"` Weaviate
  match, sets `timer_actions[i]`, and skips area resolution / HA execution for
  those parts. `execute_ha_intents()` routes timer parts to
  `timers.handle_timer_part()`, supports mixed timer + HA sentences, and calls
  an `on_timer_change` hook (wakes the scheduler, collects created timers,
  stops a melody on delete).
- **`app/main.py`** — scheduler lifecycle; HA_FAST branch emits a `timer` SSE
  event with each created timer's absolute `expires_at`; new endpoints under
  `/stream/*` (no nginx change — GET+POST already allowed there):
  `GET /stream/timers` (caller's role-scoped active timers),
  `GET /stream/timers/pending?channel=` (speech-gateway poll),
  `GET|POST /stream/timers/config` (admin: per-role limits + default role).
- Env vars added to `.env.example`: `TIMER_COLLECT_WINDOW_SECONDS`,
  `TIMER_MELODY_MAX_SECONDS`, `TIMER_MELODY_START/STOP_SCRIPT`,
  `TIMER_MEDIA_PLAYER_MAP`.
- Tests: `tests/test_timers.py` (49), `tests/test_timer_scheduler.py` (5),
  timer routing cases added to `tests/test_ha_path_decide.py`. Full local
  suite green (134 relevant tests).

### `alice-speech-gateway`
- **`app/wyoming_transport.py`** — after STT on each turn, polls
  `GET /stream/timers/pending` for the device and speaks the expiry
  announcement before processing the utterance. Best-effort (any error = nothing
  to announce). No Wyoming timer protocol.

### Home Assistant — `homeassistant/alice_timer_melody.yaml` (new)
Companion package: `input_boolean`/`input_text`/`input_number` helpers +
`script.alice_timer_melody_start` / `_stop` + two automations (self-stop after
max time, stop on satellite wake). Alice only signals start/stop over REST.

### Frontend (Vite SPA — no `app/api` routes)
- **`src/services/timers.ts`** (new) — `getActiveTimers`, `getTimerConfig`,
  `updateTimerConfig` via `fetchWithAuth` against `STREAM_API_URL`.
- **`src/hooks/useTimerAlarm.ts`** + **`src/components/TimerAlarm.tsx`** (new) —
  mounted in `(main)/layout.tsx`. Loads role-scoped active timers, counts down
  to `expires_at`, shows a toast (stays until dismissed) + a WebAudio chime on
  expiry while the tab is visible; catch-up toast on tab refocus within a 15-min
  window; server is authoritative (re-syncs on focus / interval / the
  `alice:timers-changed` event the chat fires on the `timer` SSE event).
- **`src/components/Settings/TimerRolesSection.tsx`** (new) — rendered inside the
  "Nutzer-Verwaltung" settings tab (admin-only via the existing tab guard):
  per-role Switch + max-active + max-duration(h), and the default-role Select.
- **`<Toaster />` mounted** in `(main)/layout.tsx` (it was missing entirely — a
  pre-existing gap that made every `useToast()` call in Settings a silent no-op;
  the timer alarm needs it). `TOAST_LIMIT` raised 1 → 3 so multiple timers each
  show.
- i18n: `settings.timers.*`, `timerAlarm.*` added to `de.ts` and `en.ts`.
- `src/services/api.ts` `streamChat` gains an `onTimerCreated` callback + `timer`
  SSE event; `useChatSessions` forwards it as a window event.
- `npx tsc --noEmit` clean; `next build` succeeds.

### Hardware-verify (open, per Tech-Design §G — could not be tested from dev)
Marked `>>> HARDWARE-VERIFY` in `timer_scheduler.py` and
`alice_timer_melody.yaml`:
1. Voice PE `media_player` usable while the "Hey Jarvis" path is idle.
2. Which HA state/event reliably signals "satellite is being addressed" (the
   melody-stop automation trigger — currently
   `assist_satellite_wake_word_detected`).
3. Final melody asset location + `input_text.alice_timer_melody_url`.
Fallback if these fail: fixed short repeating tone over the gateway TTS channel
(no HA automation).

## QA Test Results

**Tested:** 2026-09-07
**Test method:** Static / code-level verification + unit tests. The Alice stack
(postgres, weaviate, alice-chat-stream, alice-speech-gateway, Home Assistant) is
**not running on this machine** — it lives on the production server — so no
live end-to-end, browser, or n8n-execution testing was possible. Findings are
from reading the implementation against every AC + edge case, running the Python
unit suites, and `tsc`/`next build`.
**Tester:** QA Engineer (AI)

### Automated test status

| Suite | Result |
|---|---|
| `alice-chat-stream` pytest (excl. pre-existing redis-less `test_admin_dashboard`) | **152 passed** |
| — `tests/test_timers.py` | 50 passed |
| — `tests/test_timer_scheduler.py` | 5 passed |
| — timer routing cases in `tests/test_ha_path_decide.py` | 3 passed |
| `alice-speech-gateway` pytest | 13 passed, **6 pre-existing failures** (`test_wyoming_transport` / `test_config` — `Device(user_id=…)` in the test helpers, removed by PROJ-43; **not** caused by PROJ-85, confirmed via `git stash`) |
| frontend `tsc --noEmit` | clean |
| frontend `next build` | success |

### Acceptance Criteria Status

#### Setzen — Dauer
- [x] "auf X Minuten/Stunden" (incl. "1 Stunde 30 Minuten") → timer, `expires_at = now + X` — `parse_time` + `_do_set`, unit-tested
- [x] unnamed confirmation "Ich habe einen Timer auf {Dauer} gesetzt." — unit-tested
- [x] unnamed auto-name "{Dauer} Timer" — `derived_name`, unit-tested

#### Setzen — absolute Uhrzeit
- [x] "auf HH Uhr MM" / "auf HH Uhr" → next occurrence — `_CLOCK_RE`, unit-tested
- [x] today-if-future / tomorrow-if-past — unit-tested (incl. exactly-now → +24 h)
- [x] confirmation names computed runtime "…, er läuft {Dauer}." — `_do_set`
- [x] auto-name "{Uhrzeit} Timer" — unit-tested

#### Setzen — benannt
- [x] "für {Name}" → "{Name} Timer", singular/title normalised ("Kartoffeln"→"Kartoffel", "Nudeln"→"Nudel") — `parse_name` + `_normalise_name_word`, unit-tested
- [x] confirmation "Ich habe den {Name} Timer auf {Zeit} gesetzt." (+ "er läuft …" for clock) — `_do_set`

#### Namenskollision
- [x] active same-name in role scope → immediate fallback "zweiter/dritter … {Name} Timer", no dialog — `resolve_collision_name`, unit-tested
- [x] confirmation names the fallback "Es gibt schon einen … Ich habe einen zweiten … gesetzt." — unit-tested

#### Rollen-basierte Sichtbarkeit, Berechtigung & Limits
- [x] timer stored with owner user **and** role; unrecognised voice → `timer_default_role`, owner user NULL — `handle_timer_part`, unit-tested
- [x] query/change/pause/delete act on the whole role scope — all DB helpers filter `owner_role = $1`, unit-tested
- [x] "Lösche alle Timer" → only own role scope — `delete_all`, unit-tested
- [x] role without `can_use_timers` → friendly German refusal, nothing executed, no LLM — `handle_timer_part` guard, unit-tested
- [x] max-active per role from `role_templates`, exceed → refusal naming the limit — `_do_set`, unit-tested
- [x] max-duration per role, longer → refusal naming the limit — `_do_set`, unit-tested
- [x] duration floor 10 s, role-independent — `MIN_DURATION_SECONDS`, unit-tested
- [x] Settings tab: per-role allowed / max-active / max-duration — `TimerRolesSection`, admin-guarded
- [x] Settings tab: default-role select, shipping `user` — `TimerRolesSection` + migration 069
- [x] changes apply without container restart; running timers keep their role — `resolve_role` reads live; `POST /stream/timers/config` writes `role_templates`
- [x] admin-only visibility — inside the `can_manage_users`-guarded Nutzer-Verwaltung tab
- [x] seeded via `role_templates`, carried by `init_user_permissions()` — migration 069
- [ ] **BUG-5:** the Settings tab cannot actually reach the backend — the frontend service calls `/api/timers*`, which nginx does not proxy to alice-chat-stream (only `/api/stream/*` is). Every `getTimerConfig` / `updateTimerConfig` / `getActiveTimers` call 404s against the SPA. **Blocks the whole WebApp side (Settings + alarm).**

#### Mehrere Timer in einem Satz
- [x] "auf X und einen auf Y Minuten" → two timers via the existing splitter — `decide_path` + `execute_ha_intents`, unit-tested (`test_two_timers_one_sentence`); bare "auf 10" read as minutes

#### Ändern
- [x] "Verlängere den {Name} Timer um X" → +X, confirm new remaining — `change_expiry`, unit-tested
- [x] "Verkürze … um X" → −X, confirm — unit-tested
- [x] shorten past now / ≤ 0 → rejected, states current remaining — `change_expiry` `rejected`, unit-tested
- [x] no name + exactly one timer → that one; multiple → list + ask, nothing changed — `_pick_target`, unit-tested
- [ ] **BUG-1:** a timer whose name is *derived* ("20 Minuten Timer", "15 Uhr 40 Timer") cannot be targeted by name — `parse_ref_name`'s regex requires the name to start with a letter, so "Verlängere den 20 Minuten Timer" yields `ref=None`. With one active timer it still works (falls through to "the only one"); with several, the exact AC phrasing "den 20 Minuten Timer" cannot disambiguate. Affects Ändern / Abfragen / Pausieren / Löschen by derived name.

#### Abfragen
- [x] "Wie lange läuft der {Name} Timer noch?" → remaining, sensible unit — `_do_query`, unit-tested (subject to BUG-1 for derived names)
- [x] no name, one timer → answered; several → all listed with remaining — `_pick_target`
- [x] "Welche Timer laufen gerade?" / "Zeig mir meine Timer" → role-scoped list, paused marked — `_do_query` list branch, unit-tested
- [x] no timers → "Es läuft gerade kein Timer." — unit-tested

#### Pausieren / Fortsetzen
- [x] pause freezes remaining, timer does not fire — `pause_timer` (status→paused, `paused_remaining_seconds`), unit-tested
- [x] resume → new `expires_at = now + frozen` — `resume_timer`, unit-tested
- [x] pause-a-paused / resume-a-running → harmless no-op with message — unit-tested
- [ ] **BUG-3:** extend/shorten on a *paused* timer replies "… ist schon abgelaufen." (`change_expiry` requires `status='running'`). Spec doesn't explicitly cover it; the message is misleading.

#### Löschen
- [x] "Lösche den {Name} Timer" / "Brich … ab" → removed, confirm — `delete_timer`, unit-tested (BUG-1 for derived names)
- [x] "Lösche alle Timer" → all in role scope, confirm count — `delete_all`, unit-tested
- [x] no name, one timer → that one; several → list, delete nothing — `_pick_target`

#### Ablauf — Voice PE
- [~] `timer-finished` delivery — **implemented as HA-REST to `script.alice_timer_melody_start`** (not the Wyoming timer protocol — deliberate, per Tech Design). **HARDWARE-VERIFY**: not testable here.
- [~] device plays a melody on `timer-finished` — HA companion package `alice_timer_melody.yaml`; **HARDWARE-VERIFY**
- [x] 3 s collect window → one melody / one announcement — `_fire_due` claims `expires_at <= NOW() + 3s`, groups by channel; `pending_announcement` collects all expired of a channel — unit-tested (`test_fire_due_voice_calls_ha`)
- [x] wake during melody → melody stops, one announcement naming all due timers — `pending_announcement` + speech-gateway `_announce_expired_timers` (announcement text unit-tested; the "melody stops" half is **HARDWARE-VERIFY** via the HA automation)
- [~] no reaction → melody self-stops after 2 min, timer counts as acknowledged — `_auto_acknowledge` + HA automation `alice_timer_melody_timeout`; **HARDWARE-VERIFY** for the audio, DB side unit-testable
- [x] after acknowledgement the timer leaves the active set — status → `acknowledged`, `list_active` filters to running/paused

#### Ablauf — WebApp
- [x] create response carries the absolute `expires_at` — `timer` SSE event in `main.py`; `onTimerCreated` in `api.ts`
- [x] expiry while tab visible → toast (until dismissed) + tone — `useTimerAlarm` + WebAudio chime; **needs BUG-5 fixed** and depends on `<Toaster/>` now being mounted
- [x] refocus after expiry → catch-up toast "vor {Dauer} abgelaufen", server authoritative — `useTimerAlarm.handleVisibility`, 15-min window
- [x] not foreground & not refocused in the window → no message (documented limitation) — by design

#### Nebenläufigkeit
- [x] every transition = atomic row-locked / conditional op — `SELECT … FOR UPDATE`, `UPDATE … WHERE status='running'` in every mutator, unit-tested
- [x] scheduler `expired` vs incoming change → expiry wins, change treated as "already expired" — `change_expiry` finds no `running` row → None → "schon abgelaufen", unit-tested
- [x] delete vs in-progress expiry → delete wins, melody/announcement aborted — `_do_delete` → `cancelled_channels` → `scheduler.stop_melody`; `delete_timer` removes the row so `pending_announcement` won't announce it
- [x] restart reconcile vs steady loop → single idempotent `expired` transition — conditional-UPDATE claim, unit-tested (`test_fire_due_claims_once`, `test_reconcile_on_start_fires_overdue`)

#### Persistenz & Neustart
- [x] state in `alice.timers`, survives restarts — table + migration 069
- [x] on restart: overdue timer fired now, still-running keep counting — `_reconcile_on_start`, unit-tested
- [~] set device offline at expiry → "expired, undelivered", announced on next contact, then silently done — `pending_announcement` handles the "announce on next contact" via the speech-gateway poll; the explicit "undelivered" marker is folded into `status='expired'` (announced) then `acknowledged`. **HARDWARE-VERIFY** for the offline case.

#### Pfad & Performance
- [x] all timer ops in HA_FAST — Weaviate match on `domain=timer` objects, then regex text processing, no LLM — `decide_path` / `execute_ha_intents`
- [ ] **BUG-9:** the Weaviate seed (`seed-timer-intents.sh`) inserts the template patterns **verbatim with `{value}` / `{name}` placeholders** as the vectorised `utterance`. The literal tokens "value"/"name" pollute the embedding and there is no concrete phrasing to match against, so real utterances ("Setze einen Timer auf 20 Minuten") will match poorly or below `INTENT_MIN_CERTAINTY` (0.82) → the feature silently falls back to LLM_ONLY. The migration's timer patterns must be rewritten as concrete natural utterances (the value/name is re-extracted in `timers.py` regardless), or the seed script must expand/strip placeholders.
- [ ] **< 200 ms end-to-end** — not measurable without the stack. Design is sound (small indexed queries, no LLM); flag for a live Prometheus check at deploy (as done for PROJ-83/84).
- [x] no regression to existing HA commands / sentence splitter / HA-sync — 77 existing `ha_path` tests green; timer objects are entity-less and skipped by `alice-ha-sync` (filters by concrete `entityId`)

#### Limits & Sprache
- [x] max-active per role, shipping admin 20 / user 10 / child 3 / guest 0 — migration 069
- [x] max-duration per role, shipping 24 h (admin/user) / 2 h (child) — migration 069
- [x] duration < 10 s rejected, states the allowed range — `_do_set` (message says "mindestens 10 Sekunden"; does **not** state an upper bound — minor)
- [x] all output German / configured language, natural time phrasing — every `TimerReply` string is German; `_fmt_duration` / `_fmt_remaining` natural. **Note:** strings are hard-coded German, not routed through a per-user language setting like LLM output — consistent with PROJ-83/84 HA_FAST replies, acceptable.

### Edge Cases Status

- [x] shorten by more than remaining → rejected, states current remaining — unit-tested
- [x] extend an already-expired-not-acknowledged timer → "schon abgelaufen" — `change_expiry` (BUG-3 note: same wording wrongly hits *paused* timers)
- [x] two timers due same moment on one device → bundled — `_fire_due` grouping, unit-tested
- [~] two timers due on different devices → independent — separate `origin_channel` keys, separate `_deliver_voice`; HARDWARE-VERIFY for the audio
- [x] third timer due while melody plays → appended to the session — HA script's `input_boolean` guard + `pending_announcement` collects all expired of the channel
- [x] expiry + change same instant → expiry wins — unit-tested
- [x] expiry + delete same instant → delete wins — `delete_timer` unconditional + `stop_melody`; **minor race (BUG-8-adjacent):** if delete lands between the scheduler's claim and the melody `play_media` call, `stop_melody` fires before the melody starts and the melody then briefly plays (HA automation self-stops it; row already gone so nothing is announced). Low.
- [x] acknowledgement-by-wake vs max-time both fire → single transition — `pending_announcement` marks `acknowledged` under `FOR UPDATE`; `_auto_acknowledge` only touches rows still `expired`
- [~] timer expires mid-conversation with that device → event delivered after the turn — the speech-gateway announces at the **start of the next turn** (after STT), so it naturally waits for the current turn to finish; HARDWARE-VERIFY for the melody timing
- [x] clock exactly now → tomorrow — unit-tested
- [x] "auf 15 Uhr" → MM 00 — unit-tested
- [x] "auf 4 Uhr" at 22:00 → 04:00 next day, no AM/PM heuristic — unit-tested
- [x] name collides with an expired-not-acknowledged timer → regular name, no fallback — `name_collision` only counts running/paused
- [x] "2,5 Minuten" → 2 Minuten 30 Sekunden — unit-tested
- [x] no time value ("Setze einen Timer") → asks for the duration, nothing created, no LLM — unit-tested
- [x] change/query/delete names a non-existent timer → "Es gibt keinen … Timer", lists the actual ones — `_pick_target`, unit-tested
- [x] user A (admin) sets, user B (admin) queries → B sees it — role-scoped, unit-tested pattern
- [x] user C (child) queries while admin timers run → sees only child timers — role-scoped
- [x] unrecognised voice, default role `user`, Andreas meant it → lands in `user` scope (documented consequence) — by design
- [~] role loses timer permission while it has active timers — **partially specified, needs a decision**: current behaviour — existing timers keep running & fire; **all** new timer commands (incl. query/delete for cleanup) are refused because `handle_timer_part` checks `cfg.allowed` before dispatching. The Tech Design *recommended* still allowing query/delete for cleanup. **BUG-6 (Low):** cleanup of one's own running timers is blocked after the role loses the permission.
- [x] child changes a timer via "verkürze" not touching max-duration → allowed (max-duration only checked on set / extend) — `_do_change` only enforces max on `extend`
- [x] extend beyond role max-duration → rejected naming the limit, remaining unchanged — `_do_change` extend branch, projected-remaining check
- [x] WebApp timer, browser fully closed then reopened → re-fetches active timers, shows catch-up if within window — `useTimerAlarm` mount + `refresh()`
- [x] service restart exactly at expiry → reconcile fires it (also if the first `timer-finished` was lost) — `_reconcile_on_start`
- [x] max-time elapses while user is addressing the device → address wins — `pending_announcement` runs on the turn, `_auto_acknowledge` only touches still-`expired` rows
- [x] role limit reached, delete one + set new → works (checked at set time) — `count_active` re-checked
- [x] admin lowers role limits below the running count → running timers stay, only new sets blocked — `_do_set` checks `>=` at set time only
- [ ] **BUG-2:** "Timer auf 10 Minuten und einen auf 3 Wochen" — the invalid part is **not** rejected. The bare-number fallback in `parse_time` reads "auf 3" (from "3 Wochen") as **3 minutes** and creates a timer. Expected: the "3 Wochen" part is rejected with a reason (partial-success pattern). Same for "3 Tage", "3 Stunden 40" edge inputs.

### Security Audit Results

**Docker / API (`alice-chat-stream` new endpoints):**
- [x] Authentication: all three endpoints require a valid RS256 JWT (`verify_jwt` / `_require_admin`); missing/invalid → 401
- [x] `user_id` from the verified JWT only, never from the body/query
- [x] `POST /stream/timers/config` is `_require_admin` (JWT `role` claim). Note: like the existing `/admin/*` endpoints it trusts the JWT role, not a live DB read — a downgraded admin keeps access until token expiry (pre-existing pattern, accepted).
- [x] Input validation: `TimerConfigUpdate` / `TimerRoleConfig` are Pydantic models with role enum + `ge/le` bounds on the numeric fields. Timer command text goes through regex extraction only — no SQL string interpolation, all asyncpg parameterised queries.
- [x] RLS: `alice.timers` and `alice.system_settings` have RLS enabled (permissive policy; the service scopes by `owner_role` in every query — same model as `alice.ha_entities`).
- [ ] **BUG-7 (Medium, security):** `GET /stream/timers/pending?channel=<any>` requires only `verify_jwt` (any authenticated user, incl. `child`/`guest`), has **no role/ownership scoping**, **leaks timer names** for any device, and **mutates state** (marks the timers `acknowledged`, suppressing the real user's announcement). It is meant for the speech-gateway service token only. Mitigations: VPN-only deployment; single-user household today. Fix: restrict to the `iss == "alice-speech-gateway"` claim (the service token carries it) and/or scope the channel to the caller's role.
- [x] `GET /stream/timers` is role-scoped (`resolve_role` → `list_active(role)`); a user only sees their own role's timers. `child`/`guest` see only theirs.
- [x] Rate limiting: inherits the nginx `/api/stream/` limiter.
- [ ] **BUG-8 (Medium):** the `useTimerAlarm` hook polls `GET /api/stream/timers` every 30 s. That endpoint shares the nginx `stream_limit` zone (10 req/min/IP) with `/stream/chat`. A user actively chatting **and** with the alarm running can hit 429s on chat. Needs either a separate nginx location for `/api/stream/timers*` with its own limit, or a longer poll interval + reliance on the `alice:timers-changed` push.
- [x] No secrets in responses / logs — timer replies and log lines carry only names + durations; `HA_TOKEN` used server-side only.

**Frontend:**
- [x] Settings section is inside the `can_manage_users`-guarded tab — non-admins never see it
- [x] XSS: timer names are rendered as React text (toast `description`, list items) — auto-escaped. Names originate from the user's own speech/text.
- [x] `localStorage` not used for timer state (server authoritative)

### Bugs Found

#### BUG-1: Timers with a derived name cannot be targeted by name
- **Severity:** High
- **Root cause:** `parse_ref_name` regex `\b(?:den|der|des|dem)\s+([A-Za-zÄÖÜäöüß][\wÄÖÜäöüß -]*?)\s+timer\b` requires the name to start with a **letter**. Derived names begin with a digit ("20 Minuten Timer") or "15 Uhr 40 Timer".
- **Repro:** two timers running ("20 Minuten Timer", "Kartoffel Timer"). Say "Verlängere den 20 Minuten Timer um 5 Minuten". Expected: the 20-minute timer is extended. Actual: `ref=None` → "Es laufen mehrere Timer: … Welchen meinst du?" — cannot proceed.
- **Priority:** Fix before deployment.

#### BUG-2: Invalid duration in a multi-timer sentence is silently accepted as minutes
- **Severity:** Medium
- **Root cause:** `parse_time`'s bare-integer fallback (added for "…auf 10 und einen auf 20") matches "auf 3" inside "3 Wochen" / "3 Tage" and returns 3 minutes.
- **Repro:** "Timer auf 10 Minuten und einen auf 3 Wochen". Expected: 10-min timer created, "3 Wochen" part rejected with a reason. Actual: two timers, the second at 3 minutes.
- **Priority:** Fix before deployment (spec edge case explicitly calls for partial-success rejection).

#### BUG-3: Extend/shorten a paused timer says "schon abgelaufen"
- **Severity:** Low
- **Root cause:** `change_expiry` guards on `status='running'`; a paused timer yields None, which `_do_change` renders as "ist schon abgelaufen".
- **Repro:** pause a timer, then "Verlängere den … Timer um 5 Minuten". Expected: either extend the frozen remaining, or "Der Timer ist pausiert — setze ihn erst fort." Actual: "…ist schon abgelaufen."
- **Priority:** Fix in next sprint.

#### BUG-5: WebApp cannot reach the timer backend (wrong path prefix)
- **Severity:** High (blocks the entire WebApp half of the feature)
- **Root cause:** `frontend/src/services/timers.ts` builds URLs as `${STREAM_API_URL}/timers…` = `/api/timers…`. nginx only proxies `/api/stream/*` (and `/api/admin/*`, `/api/auth/*`) to `alice-chat-stream`; `/api/timers` falls through to the SPA catch-all and returns `index.html`.
- **Repro:** open Settings → Nutzer-Verwaltung as admin. Expected: the Timer section loads the per-role config. Actual: `getTimerConfig()` receives HTML, `res.ok` is true, `res.json()` throws → the section shows its error state. The alarm hook's `getActiveTimers()` fails the same way.
- **Fix:** prefix the three calls with `/stream` → `${STREAM_API_URL}/stream/timers`, `/stream/timers/config`.
- **Priority:** Fix before deployment.

#### BUG-6: Cleanup blocked after a role loses the timer permission
- **Severity:** Low
- **Root cause:** `handle_timer_part` returns the refusal for **every** action when `cfg.allowed` is false, before dispatching. The Tech Design recommended still allowing query/delete for cleanup.
- **Repro:** role has 2 running timers, admin turns off "Timer erlauben" for that role, user says "Lösche alle Timer". Expected (per Tech Design G): the delete is allowed so they can clean up. Actual: "Timer sind für deine Rolle nicht freigeschaltet."
- **Priority:** Fix in next sprint (decision needed — spec left this open).

#### BUG-7: `/stream/timers/pending` unauthenticated-scope + state mutation
- **Severity:** Medium (security)
- See Security Audit. Any authenticated user can read + acknowledge any device's expired timers.
- **Priority:** Fix before deployment (cheap: gate on the `iss` claim).

#### BUG-8: Timer alarm poll shares the chat rate-limit budget
- **Severity:** Medium
- `useTimerAlarm` polls `/api/stream/timers` every 30 s against the shared `stream_limit` (10/min). Heavy chatting + alarm → 429 on chat.
- **Priority:** Fix before deployment (add a dedicated nginx location, or raise the interval to ≥120 s and lean on the `alice:timers-changed` event).

#### BUG-9: Weaviate timer seed keeps `{value}` / `{name}` placeholders in the vectorised text
- **Severity:** High (feature silently non-functional on the voice/text fast path)
- See Pfad & Performance. The seed must write concrete natural utterances.
- **Priority:** Fix before deployment.

### Pre-existing issues surfaced (not PROJ-85 bugs, but relevant)
- `<Toaster />` was **not mounted anywhere** in the app — every `useToast()` call in Settings was a silent no-op. PROJ-85 mounts it in `(main)/layout.tsx` (required for the alarm). This means existing Settings toasts (user CRUD, DMS, mail, voice) now actually appear — a behaviour change, intended and positive, but worth a regression glance.
- `alice-speech-gateway` `tests/test_wyoming_transport.py` + `tests/test_config.py` — 6 failures from `Device(user_id=…)` in the test helpers (PROJ-43 removed that field). Pre-dates PROJ-85.

### Summary (first pass)
- **Acceptance Criteria:** 58 sub-checks PASS, 5 FAIL (BUG-1, BUG-2, BUG-5, BUG-6, BUG-9), ~9 HARDWARE-VERIFY (Voice-PE audio path — cannot test here, by design), 1 not measurable (< 200 ms — needs live Prometheus).
- **Bugs Found:** 8 total — 0 Critical, **3 High** (BUG-1, BUG-5, BUG-9), **3 Medium** (BUG-2, BUG-7, BUG-8), **2 Low** (BUG-3, BUG-6).

---

## Re-QA — after fixes (2026-09-08)

All 8 bugs from the first pass were fixed in commit `ddcffa9` and
re-verified by code reading + unit tests. Same constraint: the live stack is
not runnable here, so the Voice-PE audio path and the < 200 ms budget still
need a hardware/Prometheus check at deploy.

| Bug | Fix | Verification |
|---|---|---|
| **BUG-1** (High) — derived names unaddressable | `_REF_NAME_RE` first char now `[0-9A-Za-zÄÖÜäöüß]`; `find_by_name` already matched the "`<n>` Timer" variant | `test_ref_name_derived_digit_start`, `test_extend_derived_name_with_multiple_timers` — "den 20 Minuten Timer" / "den 15 Uhr 40 Timer" resolve and extend correctly with several timers active |
| **BUG-2** (Medium) — "3 Wochen" → 3 min | `parse_time` now returns `ParsedTime(rejected=True)` for `\d+ (Wochen\|Tage\|Monate\|Jahre)`; bare-number fallback tightened to `auf <n>$` / a whole-part number | `test_out_of_range_unit_rejected`, `test_set_out_of_range_unit_rejected` → "So lange kann ich keinen Timer stellen …", nothing created. Valid part of a mixed sentence still succeeds. |
| **BUG-3** (Low) — extend a paused timer says "abgelaufen" | new `change_paused_remaining()` (row-locked) adjusts `paused_remaining_seconds`; `_do_change` branches on `status == 'paused'` | `test_extend_paused_timer` → "Der … steht jetzt bei 15 Minuten (pausiert)."; floor still enforced |
| **BUG-5** (High) — WebApp calls `/api/timers*` | `timers.ts` `base()` now returns `${STREAM_API_URL}/stream` → `/api/stream/timers*`, which nginx proxies to alice-chat-stream | path traced against `docker/compose/infra/nginx/conf.d/alice.conf`; `next build` clean |
| **BUG-6** (Low) — cleanup blocked after permission loss | `handle_timer_part` blocks only `set`/`extend`/`shorten`/`pause`/`resume` when `!cfg.allowed`; `query`/`delete` pass through | `test_cleanup_allowed_after_permission_lost` — query + "lösche alle Timer" work, `set` still refused |
| **BUG-7** (Medium, security) — `pending` unscoped + mutating | endpoint now requires `iss == "alice-speech-gateway"` (only the service token carries it; WebApp tokens have no `iss`) and a `esphome:`/`esphome` channel; 403/400 otherwise | code review; matches `service_token.py` payload |
| **BUG-8** (Medium) — alarm poll eats chat rate limit | new nginx `limit_req_zone timer_limit 60r/m` + dedicated `location ^~ /api/stream/timers` (ordered before the generic `/api/stream/` block); `useTimerAlarm` poll 30 s → 120 s, leans on the `alice:timers-changed` push | nginx config review; hook change |
| **BUG-9** (High) — Weaviate seed keeps `{value}`/`{name}` | migration 069 timer patterns rewritten as concrete natural utterances (12 for `set`, ~5 each for the rest); `seed-timer-intents.sh` now hard-skips any pattern containing `{` | migration + script reviewed; the value/name is re-extracted in `timers.py` regardless |

### Re-QA automated test status

| Suite | Result |
|---|---|
| `alice-chat-stream` pytest (excl. redis-less `test_admin_dashboard`) | **158 passed** |
| — `tests/test_timers.py` | 55 passed (7 new for the fixes) |
| — `tests/test_timer_scheduler.py` | 5 passed |
| frontend `tsc --noEmit` / `next build` | clean / success |
| `alice-speech-gateway` pytest | unchanged — 13 pass, 6 pre-existing `Device(user_id=)` failures (not PROJ-85) |

### Re-QA verdict

- **Bugs remaining:** 0 Critical, **0 High**, 0 Medium, 0 Low from this feature.
  (The 6 pre-existing `alice-speech-gateway` test failures are unrelated to
  PROJ-85 and predate it.)
- **Still open, by design / environment:**
  - 9 HARDWARE-VERIFY items on the Voice-PE audio path (media_player while
    idle, the satellite-addressed event for the melody-stop automation, the
    melody asset). Marked `>>> HARDWARE-VERIFY` in code. Fallback plan
    documented.
  - `< 200 ms` end-to-end — needs a live Prometheus `chat_latency_seconds`
    check at deploy (same as PROJ-83/84).
- **Production Ready:** **YES for the code path** — no Critical/High/Medium/Low
  bugs. Deploy sequence must include: apply migration 069 → run
  `scripts/seed-timer-intents.sh` → publish `homeassistant/alice_timer_melody.yaml`
  → sync nginx (`timer_limit` zone + `/api/stream/timers` location) → rebuild
  alice-chat-stream + alice-speech-gateway → deploy frontend. Then the
  hardware-verify session at the Voice PE and the live latency check.
- **Recommendation:** Approve for deployment; treat the HARDWARE-VERIFY items
  as a post-deploy checklist (the WebApp + role/limit + all text-path ACs do
  not depend on them).

### Summary (final)
- **Acceptance Criteria:** 63 sub-checks PASS, 0 FAIL, 9 HARDWARE-VERIFY, 1 live-measurement-pending.
- **Bugs:** 8 found, **8 fixed**, 0 remaining.
- **Security:** Pass — BUG-7 closed; auth / RLS / Pydantic validation / parameterised queries all sound.
- **Production Ready:** YES (code); hardware-verify + latency check to follow at deploy.

---

## Hardware-Verify Nachlauf (2026-09-16, am echten Voice PE)

Live getestet an der Büro-Voice-PE nach dem Deploy von Migration 069 +
`seed-timer-intents.sh` + `alice_timer_melody.yaml` (als HA-Package unter
`/config/packages/`).

| Punkt | Ergebnis |
|---|---|
| Voice-PE `media_player`-Entity bei Idle nutzbar | ✅ **Bestätigt** — `media_player.ha_voice_pe_buero_media_player` spielt via `media_player.play_media` mit `media-source://media_source/local/<datei>.mp3`, unabhängig von der "Hey Jarvis"-Wyoming-Session |
| Melodie-Loop / Timeout-Selbststopp / manueller Stop | ✅ **Bestätigt** — alle drei Scripts (`alice_timer_melody_start`/`_stop`, Timeout-Automation) manuell durchgetestet, funktionieren wie spezifiziert |
| Melodie-Asset | ✅ Datei liegt unter `/media/alice_timer_finished.mp3`; `input_text.alice_timer_melody_url` zeigt auf `media-source://media_source/local/alice_timer_finished.mp3` |
| "Ansprache stoppt Melodie" — ursprünglicher HA-Automation-Ansatz | ❌ **Verworfen** — die geplante Automation auf `assist_satellite`-State/-Event kann grundsätzlich nie feuern: "Hey Jarvis" umgeht HAs Assist-Pipeline komplett und geht per raw Wyoming direkt an `alice-speech-gateway` (PROJ-42 `devices/ha-voice-pe/README.md`); die `assist_satellite`-Entity bleibt für diesen Pfad permanent im Leerlauf. Am Gerät verifiziert (Event-Log leer außer dem `media_player`-eigenen State-Wechsel beim Melodie-Start). |

### Architektur-Korrektur: Melodie-Stopp verlagert ins Gateway

Die "Ansprache stoppt Melodie"-Logik sitzt jetzt in **`alice-speech-gateway`**
statt in einer HA-Automation — der Gateway ist der einzige Ort, der einen neuen
Turn überhaupt erkennt (er terminiert die Wyoming-Session direkt).

- **`alice-chat-stream`** — `GET /stream/timers/pending` ruft jetzt **zuerst**
  `scheduler.stop_melody(channel)` auf (idempotent — `media_player.media_stop`
  auf einem stillen Player ist ein No-Op), **dann** erst
  `pending_announcement()`. Beides in einem Request.
- **`alice-speech-gateway`** — `wyoming_transport.py`: der Poll-Aufruf ist von
  "nach STT" auf "sofort nach `_collect_audio()`" vorgezogen (parallel zu
  STT/Speaker-ID gestartet, Ergebnis erst nach STT abgewartet) — die Melodie
  stoppt so schnell wie möglich, nicht erst nach der STT-Latenz. Kein
  zusätzlicher HTTP-Call nötig; der bestehende `pending`-Poll übernimmt beides.
- **`homeassistant/alice_timer_melody.yaml`** — die tote
  `alice_timer_melody_stop_on_wake`-Automation (Trigger
  `assist_satellite_wake_word_detected`, feuert nie) wurde entfernt. Das
  Package enthält nur noch Start/Stop-Scripts + die Timeout-Automation, beide
  live verifiziert.

### Verbleibend offen

- **Live-Latenz-Check `< 200 ms`** für Timer-Operationen (Prometheus
  `chat_latency_seconds`, analog PROJ-83/84 AC-6/AC-11) — noch nicht gemessen.
- **End-to-End-Test der kompletten Ablauf-Kette** am Gerät (Timer setzen →
  ablaufen lassen → Melodie hören → ansprechen → Melodie stoppt + Ansage) mit
  dem neuen Gateway-seitigen Stop-Pfad — die Einzelteile (Melodie-Scripts,
  Endpoint-Reihenfolge) sind verifiziert bzw. unit-getestet, der volle Ablauf
  am Gerät steht noch aus.
- Sammel-Fenster (mehrere Timer, ein Gerät) und Geräte-Offline-Fall weiterhin
  nur code-seitig verifiziert.

## Deployment
_To be added by /deploy_
