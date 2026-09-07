# PROJ-85: Timer-Agent

## Status: Planned
**Created:** 2026-09-07
**Last Updated:** 2026-09-07

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
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
