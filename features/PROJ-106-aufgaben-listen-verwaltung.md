# PROJ-106: Aufgaben- & Listen-Verwaltung (lokal) — Kern

## Status: Architected
**Created:** 2026-10-08
**Last Updated:** 2026-10-08

## Dependencies
- Ersetzt: PROJ-88 (Google-Aufgaben-Agent, verworfen) und PROJ-100 (HA-Todo-Listen-Agent, verworfen) — Begründung im verworfenen Entwurf `PROJ-88-aufgaben-agent.md`
- Ändert: PROJ-83 (HA-Agent variable Intents) — der HA_FAST-Einkaufslisten-Pfad entfällt vollständig
- Ändert: PROJ-87 (Kalender-Agent) — allgemeine Tagesabfragen („Was steht morgen an?") liefern künftig Termine **und** Aufgaben
- Requires: bestehendes Rollen-/Permission-System (`alice.role_templates` / `alice.permissions_assistant`) — neue Listen-Berechtigung pro Rolle
- Requires: Speaker-ID im `alice-speech-gateway` (Verbesserung → PROJ-103)
- Abgrenzung: PROJ-102 (Multi-Intent über **verschiedene Domänen** in einem Satz) — mehrere Einträge für **eine** Liste gehören zu PROJ-106
- Folge-Features (bauen auf PROJ-106 auf): PROJ-107 (WebApp-Ansicht), PROJ-108 (Erinnerungen), PROJ-109 (Wiederkehrende Aufgaben), PROJ-110 (Unteraufgaben)

## Kontext

Alice verwaltet Aufgaben und Listen künftig **selbst und lokal**, statt sie an Google Tasks oder Home-Assistant-Todo-Listen zu delegieren. Damit verschwindet die Mehrdeutigkeit „Google-Aufgabe oder HA-Liste?", und Alice kann, was beide nicht konnten: Fälligkeit mit Uhrzeit **und** Frist, Priorität, private **und** gemeinsame Listen.

**Ein Modell für alles:** Es gibt nur **Listen** und **Einträge**. Ob etwas eine Einkaufsliste oder eine Aufgabenliste ist, ergibt sich allein aus der Liste („Butter" auf der Einkaufsliste, „Steuererklärung bis 15.10." auf „Arbeit"). Alice muss nur noch entscheiden: **welche Liste?** — ohne Namen gilt die Standardliste des Users.

Bedienung im Kern ausschließlich **per Chat und Sprache** (auch die Listenverwaltung). Eine WebApp-Oberfläche folgt mit PROJ-107. Bestehende Einträge aus HA bzw. Google Tasks überträgt der User manuell; PROJ-106 sieht **keine** Migration vor. Keine Spiegelung nach HA.

## User Stories

- Als User möchte ich per Sprache „Setze Milch, Butter und Eier auf die Einkaufsliste" sagen, und alle drei Einträge stehen auf der gemeinsamen Einkaufsliste.
- Als User möchte ich Aufgaben mit Fälligkeit (inkl. Uhrzeit), Frist und Priorität anlegen, damit ich weiß, wann ich etwas angehe und bis wann es fertig sein muss.
- Als User möchte ich fragen „Was steht heute an?" und eine Antwort mit meinen Terminen und meinen heute fälligen Aufgaben/Fristen bekommen.
- Als User möchte ich private Listen nur für mich und gemeinsame Listen für den Haushalt haben.
- Als User möchte ich Listen per Sprache anlegen, umbenennen, löschen und meine Standardliste festlegen, ohne eine Oberfläche zu brauchen.
- Als User möchte ich Einträge abhaken, wieder öffnen, ändern und entfernen — bei Aufgaben ohne Gefahr, dass ein Hörfehler etwas Falsches löscht.
- Als Familienmitglied, das von Alice nicht erkannt wird, möchte ich trotzdem etwas auf die Einkaufsliste setzen können.
- Als Admin möchte ich festlegen, welche gemeinsame Liste die Einkaufsliste ist, und pro Rolle steuern, wer Listen nutzen darf.
- Als User möchte ich kurze, verlässliche Antworten — ohne Geschwätz, erfundene Rückfragen oder vorgetäuschte Erfolge.

## Acceptance Criteria

### Listen

- [ ] Es gibt **private Listen** (nur der Ersteller sieht/ändert sie, auch kein Admin-Zugriff) und **gemeinsame Listen** (sichtbar für alle berechtigten User des Haushalts).
- [ ] Bei Einführung existiert die gemeinsame Liste „Einkaufsliste", gekennzeichnet als Einkaufsliste. Jeder User erhält beim ersten Gebrauch eine private Liste „Meine Aufgaben", die seine Standardliste ist.
- [ ] Per Chat/Sprache: Liste anlegen („Leg eine Liste ‚Baumarkt' an", „Leg eine gemeinsame Liste ‚Urlaub' an"), umbenennen, löschen, Standardliste festlegen („Mach ‚Arbeit' zu meiner Standardliste"), Übersicht („Welche Listen habe ich?" — private und gemeinsame, Standard- und Einkaufsliste markiert).
- [ ] Listennamen sind unter den für einen User sichtbaren Listen eindeutig (ohne Beachtung der Groß-/Kleinschreibung); ein Duplikat wird mit Hinweis abgelehnt.
- [ ] Legt ein anderer User eine gemeinsame Liste an, deren Name einer (für ihn unsichtbaren) privaten Liste entspricht, ist das erlaubt; nennt der Besitzer der privaten Liste diesen Namen, fragt Alice „deine private oder die gemeinsame Liste ‚X'?".
- [ ] Ungefähre Namen werden aufgelöst, wenn genau eine Liste passt („Baumarktliste" → „Baumarkt"); bei mehreren Kandidaten Rückfrage. „Einkaufsliste"/„Einkaufszettel" meint immer die gekennzeichnete Einkaufsliste, unabhängig von ihrem Namen.
- [ ] Unbekannter Listenname: Alice legt nicht automatisch an, sondern fragt „Die Liste ‚X' gibt es nicht. Soll ich sie anlegen?".
- [ ] Liste löschen nur nach Rückfrage, die die Zahl der enthaltenen Einträge nennt; die Einträge werden mitgelöscht. War sie Standardliste eines Users, fällt dessen Standard auf „Meine Aufgaben" zurück. Wird „Meine Aufgaben" gelöscht, wird sie beim nächsten Gebrauch neu angelegt.

### Einkaufsliste

- [ ] Genau **eine** gemeinsame Liste ist als Einkaufsliste gekennzeichnet; ihr Name ist frei wählbar.
- [ ] Nur `admin` kann eine gemeinsame Liste als Einkaufsliste kennzeichnen („Mach ‚Lidl' zur Einkaufsliste"). Die bisherige verliert die Kennzeichnung; Alice nennt das in der Bestätigung. Private Listen können nicht gekennzeichnet werden.
- [ ] Die gekennzeichnete Einkaufsliste kann nur `admin` löschen (Rückfrage weist darauf hin, dass es die Einkaufsliste ist). Danach gibt es keine Einkaufsliste, bis `admin` eine neue kennzeichnet; Einkaufslisten-Anfragen werden bis dahin mit klarer Meldung abgelehnt.
- [ ] Der HA_FAST-Einkaufslisten-Pfad aus PROJ-83 entfällt vollständig; sämtliche Listen-Anfragen laufen über PROJ-106. Alice schreibt nicht mehr in `todo.einkaufsliste`.

### Einträge — Felder

- [ ] Pflicht ist nur der Titel. Optional: Notiz, **Fälligkeit** (Datum, optional Uhrzeit — wann man es angeht), **Frist** (Datum, optional Uhrzeit — bis wann es fertig sein muss), **Priorität** (hoch / normal = Standard / niedrig).
- [ ] Sprachregeln: „am …"/„um …" → Fälligkeit; „bis …"/„spätestens …" → Frist; „wichtig"/„dringend" → hoch; „unwichtig"/„irgendwann" → niedrig. Nicht genannte Felder bleiben leer bzw. normal, Alice fragt **nicht** danach.
- [ ] Ein Datum (Fälligkeit oder Frist) in der Vergangenheit wird nicht stillschweigend gesetzt; Alice fragt nach.

### Einträge — Anlegen

- [ ] Ohne Listennamen → Standardliste des Users; mit Listennamen → diese Liste (Auflösung siehe „Listen").
- [ ] Mehrere Einträge in einem Satz: **jedes „und" und jedes Komma trennt Einträge, ohne Ausnahme** („Salz und Pfeffer" → zwei Einträge). Mengenangaben bleiben Teil des Eintrags („2 Packungen Milch und 6 Eier" → „2 Packungen Milch", „6 Eier").
- [ ] Einkaufsliste: offene Duplikate werden ohne Hinweis angelegt (kein Dedup). Steht derselbe Artikel als **erledigt** auf der Liste, wird dieser Eintrag wieder geöffnet statt dupliziert.
- [ ] Andere Listen: Existiert ein offener Eintrag mit gleichem Titel in derselben Liste, weist Alice darauf hin und fragt, ob trotzdem angelegt werden soll.
- [ ] Die Bestätigung zählt die angelegten Einträge auf und nennt die Liste sowie ggf. Fälligkeit/Frist/Priorität, damit eine falsche Aufteilung oder ein Hörfehler auffällt.

### Einträge — Anzeigen

- [ ] Alice versteht u. a.: „Was steht auf der Einkaufsliste?", „Welche Aufgaben habe ich?", „Was ist heute/morgen/diese Woche fällig?", „Welche Fristen habe ich diese Woche?" (nur Fristen), „Was ist überfällig?" (Fälligkeit oder Frist verstrichen, noch offen), „Steht Butter auf der Einkaufsliste?", „Wie viele Einträge hat die Liste ‚Baumarkt'?".
- [ ] Ohne Listennamen werden alle für den User sichtbaren Listen (private + gemeinsame) durchsucht; der Listenname erscheint in der Ausgabe, wenn Treffer aus mehr als einer Liste stammen.
- [ ] Sortierung: überfällige zuerst, dann nach dem früheren der beiden Daten (Fälligkeit/Frist), bei gleichem Datum hohe Priorität zuerst, zuletzt Einträge ohne Datum. Fälligkeit und Frist werden in der Ausgabe unterscheidbar gekennzeichnet.
- [ ] Notizen nur auf Nachfrage.
- [ ] Per Sprache höchstens 5 Einträge plus Restanzahl („… und 3 weitere"); im Chat alle Treffer (max. 50, bei Überschreitung Hinweis auf Kürzung).
- [ ] Ohne Treffer sagt Alice klar, dass nichts ansteht bzw. die Liste leer ist.
- [ ] „Heute", „überfällig" usw. beziehen sich auf die Zeitzone des Users (Default Europe/Berlin).

### Kombinierte Tagesabfrage (mit PROJ-87)

- [ ] „Termin"/„Kalender"/„was habe ich … vor" → nur Kalender (unverändert PROJ-87).
- [ ] „Aufgabe"/„zu erledigen"/„Frist"/„fällig"/„überfällig" oder ein Listenname → nur Listen/Einträge.
- [ ] Allgemeine Tagesabfragen („Was steht morgen an?", „Was habe ich heute?") → **eine kombinierte Antwort**: erst Termine, dann fällige Einträge und Fristen; keine Rückfrage. Per Sprache insgesamt höchstens 5 Elemente plus Restanzahl.
- [ ] Ohne Kalender-Verbindung bzw. Kalender-Berechtigung → nur Einträge; ohne Listen-Berechtigung → nur Termine.

### Einträge — Ändern, Abhaken, Entfernen

- [ ] Änderbar: Titel, Notiz, Fälligkeit, Frist (jeweils setzen/ändern/entfernen), Priorität, Liste (verschieben). Ohne Rückfrage; Alice bestätigt danach die neue Fassung.
- [ ] Der Eintrag wird über den (auch ungefähr genannten) Titel identifiziert; mehrere Treffer → kurze Auflistung und Rückfrage; kein Treffer → klare Meldung.
- [ ] Abhaken („Hake … ab", „… ist erledigt") ohne Rückfrage; der Eintrag bleibt als erledigt gespeichert (mit Zeitpunkt und wer abgehakt hat) und erscheint nicht mehr in normalen Abfragen.
- [ ] Wieder öffnen („Öffne … wieder", „Butter ist doch nicht da") setzt einen erledigten Eintrag auf offen.
- [ ] Abhaken und Entfernen funktionieren für mehrere Einträge in einem Satz (gleiche Trennregel wie beim Anlegen); nicht gefundene Einträge werden ausdrücklich benannt, der Rest wird trotzdem ausgeführt.
- [ ] **Einkaufsliste:** „Entferne … von der Einkaufsliste" entfernt ohne Rückfrage; Alice bestätigt danach.
- [ ] **Alle anderen Listen:** Löschen eines Eintrags nur nach Rückfrage — Alice nennt den konkreten Eintrag und löscht erst nach „Ja" im folgenden Turn; „Nein"/anderes → nichts wird gelöscht. Genau ein Eintrag pro Rückfrage.
- [ ] Erledigte Einträge abfragbar („Was habe ich diese Woche erledigt?", „Was wurde von der Einkaufsliste abgehakt?"), maximal für die letzten 30 Tage.
- [ ] „Räume die Liste ‚X' auf" entfernt alle erledigten Einträge dieser Liste sofort, ohne Rückfrage.
- [ ] Erledigte Einträge werden 30 Tage nach dem Abhaken automatisch endgültig entfernt.

### Berechtigungen und Sprecher

- [ ] Neue Listen-Berechtigung pro Rolle im bestehenden Rollen-System, im Admin-Bereich editierbar. Defaults:

  | Rolle | Private Listen | Gemeinsame Listen |
  |---|---|---|
  | `admin` | voll | voll, inkl. Einkaufsliste kennzeichnen/löschen |
  | `user` | voll | voll (Listen anlegen; eigene gemeinsame Listen umbenennen/löschen; Einträge lesen/anlegen/ändern/abhaken/entfernen) |
  | `child` | voll | Einträge lesen, anlegen, abhaken; **nicht** entfernen/löschen, keine gemeinsamen Listen anlegen/umbenennen/löschen |
  | `guest` | kein Zugriff | kein Zugriff (auch nicht lesend) |

- [ ] Gemeinsame Listen umbenennen/löschen: `admin` und der User, der die Liste angelegt hat.
- [ ] Ohne Berechtigung lehnt Alice höflich ab und nennt den Grund (Rolle hat keinen Zugriff auf diese Aktion).
- [ ] **Unbekannter Sprecher** (Voice, nicht identifiziert): darf ausschließlich Einträge **zur gekennzeichneten Einkaufsliste hinzufügen**. Alles andere (lesen, abhaken, entfernen, andere Listen, Tagesabfrage) lehnt Alice ab mit dem Hinweis, dass sie nicht weiß, wer spricht. Kein Fallback auf Admin oder Geräte-Default.
- [ ] Private Listen sind strikt privat: kein Zugriff anderer User, auch nicht durch Admin.

### Antwortverhalten (Erkenntnisse aus PROJ-87)

- [ ] Antworten knapp und gleichbleibend (in der Regel 1–2 Sätze): keine internen/technischen Begriffe, keine Wiederholung der Anfrage, keine doppelte Bestätigung.
- [ ] Rückfragen nur, wenn etwas wirklich fehlt oder mehrdeutig ist (mehrdeutiger Eintrag/Listenname, unbekannte Liste, Datum in der Vergangenheit, Duplikat außerhalb der Einkaufsliste, Löschbestätigung). Nicht genannte optionale Angaben (Notiz, Fälligkeit, Frist, Priorität) werden **nie** erfragt.
- [ ] Alice meldet eine Aktion nur dann als ausgeführt, wenn sie tatsächlich gespeichert wurde, und nennt keine Einträge, die es nicht gibt (kein Halluzinieren von Erfolg, vgl. PROJ-102).
- [ ] Ein „Ja" auf eine Löschrückfrage führt verlässlich zum Löschen — per Chat **und** per Voice; eine nicht beantwortete Rückfrage verfällt nach dem nächsten, nicht bestätigenden Turn.
- [ ] Voice: Datums-/Uhrzeitangaben gesprochen („Freitag, den 10. Oktober um 14 Uhr"), keine Listen/Markdown/Emojis. Nach abgeschlossener Aktion/Abfrage endet die Voice-Sitzung; bei einer Rückfrage bleibt sie offen.
- [ ] Listen-Anfragen und die Antwort auf eine offene Listen-Rückfrage werden nicht vom Smart-Home-Schnellpfad (HA_FAST) abgefangen.
- [ ] Antworten in der konfigurierten Nutzersprache.
- [ ] Folgende Testsätze funktionieren im Live-Test über WebApp **und** Voice PE wie beschrieben:
  - „Setze Milch, Butter und Eier auf die Einkaufsliste" → drei Einträge, Bestätigung zählt sie auf
  - „Setze Salz und Pfeffer auf die Einkaufsliste" → zwei Einträge
  - „Entferne Butter und Eier von der Einkaufsliste" → entfernt ohne Rückfrage
  - „Steht Butter auf der Einkaufsliste?" → ja/nein
  - Unbekannter Sprecher: „Setze Milch auf die Einkaufsliste" → hinzugefügt; „Was steht auf der Einkaufsliste?" → abgelehnt
  - „Neue Aufgabe Reifen wechseln morgen um 14 Uhr" → Fälligkeit mit Uhrzeit, Standardliste
  - „Steuererklärung bis 31. Juli, wichtig" → Frist + hohe Priorität
  - „Was steht morgen an?" → Termine + fällige Einträge/Fristen
  - „Was ist überfällig?" → überfällige Einträge
  - „Hake Reifen wechseln ab" / „Öffne Reifen wechseln wieder"
  - „Lösche die Aufgabe Reifen wechseln" → Rückfrage; „Ja" → gelöscht; „Nein" → nichts gelöscht
  - „Leg eine gemeinsame Liste Urlaub an" / „Lösche die Liste Urlaub" → Rückfrage mit Anzahl
  - „Setze Dübel auf die Liste Werkstatt" (unbekannt) → Anlege-Rückfrage
  - Admin: „Mach Lidl zur Einkaufsliste" → Kennzeichnung gewechselt

## Edge Cases

- **Gleichzeitige Änderungen** (zwei User haken denselben Einkaufslisten-Eintrag ab / einer entfernt, der andere hakt ab): Die zweite Aktion meldet sachlich, dass der Eintrag bereits erledigt bzw. nicht mehr vorhanden ist; kein Fehlerabbruch, keine Doppelaktion.
- **Eintrag zwischen Rückfrage und Bestätigung verändert/entfernt** (z. B. per anderem Gerät): Alice meldet, dass der Eintrag nicht mehr gefunden wurde bzw. sich geändert hat, statt blind zu löschen.
- **Abhaken eines bereits erledigten Eintrags:** Alice sagt, dass er schon erledigt ist.
- **Gleichnamige Einträge in verschiedenen Listen** ohne Listennamen in der Anfrage: Rückfrage mit Nennung der Liste.
- **Uhrzeit ohne Datum** („um 14 Uhr"): bezieht sich auf heute, bzw. auf morgen, wenn die Uhrzeit heute bereits verstrichen ist; die Bestätigung nennt das Datum.
- **Frist vor Fälligkeit** („am Freitag anfangen, bis Donnerstag fertig"): Alice legt nicht stillschweigend an, sondern weist auf den Widerspruch hin und fragt nach.
- **Einkaufsliste nicht gekennzeichnet** (gelöscht, noch keine neue): Hinzufügen zur Einkaufsliste wird klar abgelehnt — auch für unbekannte Sprecher; Admin wird in der Meldung als zuständig genannt.
- **Child versucht, von der Einkaufsliste zu entfernen:** höfliche Ablehnung mit Hinweis, dass Abhaken möglich ist.
- **Rolle verliert Berechtigung:** sofortige Sperre; die privaten Listen des Users bleiben unverändert erhalten.
- **User wird gelöscht:** seine privaten Listen werden mitgelöscht; von ihm angelegte gemeinsame Listen bleiben bestehen (umbenennen/löschen dann nur durch `admin`).
- **Whisper-Transkriptionsfehler** (falscher Artikel, falsche Aufteilung): Die Bestätigung nennt das Verstandene; Korrektur per „Entferne …"/„Ändere …".
- **Sehr lange Einträge** (ganzer Satz statt kurzem Artikel): werden vollständig übernommen, keine Kürzung.
- **Zeitumstellung:** Fälligkeit/Frist mit Uhrzeit liegt zur korrekten Ortszeit.

## Technical Requirements

- **Datenhaltung:** lokal in PostgreSQL (Schema `alice`); keine Cloud, keine HA-Spiegelung. Lokal-First ohne Ausnahme.
- **Sicherheit:** alle Zugriffe user-scoped; private Listen nur für den Besitzer; Rollen-Rechte serverseitig geprüft, nicht nur per Prompt.
- **Performance:** Listen-Aktionen und -Abfragen in der Regel < 2 s Ende-zu-Ende (kein Cloud-Roundtrip); kein HA_FAST-Ziel (< 200 ms gilt nicht).
- **Sprache:** Alice-Antworten in der Nutzersprache; Code/Kommentare/Commit-Messages auf Englisch; Datenbank-Bezeichner Englisch.
- **Hinweis für `/architecture`:** Die PROJ-87-Mechanismen (Vorlagen-Antworten statt LLM-Formulierung, erzwungenes Tool je Absicht, serverseitige Löschbestätigung aus früherem Turn, offene Rückfrage über Turns hinweg, `conversation_end` bei Voice, Umgehung des HA-Fast-Path) prüfen und nach Möglichkeit wiederverwenden. Die Trennregel für Mehrfach-Einträge („und"/Komma) soll deterministisch sein, nicht vom LLM entschieden. Rückbau des PROJ-83-Einkaufslisten-Pfads und Anpassung der PROJ-87-Tagesabfrage einplanen.

## Out of Scope (bewusst nicht in PROJ-106)

- WebApp-Oberfläche für Listen/Einträge (→ PROJ-107)
- Erinnerungen/proaktive Hinweise (→ PROJ-108)
- Wiederkehrende Einträge (→ PROJ-109)
- Unteraufgaben (→ PROJ-110)
- Gepflegte „feste Begriffe" (z. B. „Salz und Pfeffer" als ein Eintrag)
- Freigabe einzelner Listen an ausgewählte Personen (nur privat oder haushaltsweit)
- Migration bestehender Einträge aus HA oder Google Tasks (manuell durch den User)
- Synchronisation/Spiegelung nach HA oder Google
- Sortieren/Umordnen von Einträgen innerhalb einer Liste
- Multi-Intent über verschiedene Domänen in einem Satz (→ PROJ-102)

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

**Entworfen:** 2026-10-08

### Überblick

PROJ-106 besteht aus fünf Bausteinen:

1. **Neuer Service `alice-lists`** — hält Listen und Einträge in PostgreSQL, erzwingt alle Regeln (Sichtbarkeit, Rollen, Einkaufsliste, Duplikate, Löschbestätigung) und löst Zeiträume/Zeitzonen auf. Gleiches Muster wie `alice-calendar` (PROJ-87): eigener Container, interne Tool-Endpoints für den Chat. Weil PROJ-107 (WebApp-Ansicht) später dieselbe Logik braucht, bekommt der Service schon jetzt eine saubere Schnittstelle, statt die Regeln im Chat-Service zu vergraben.
2. **Chat-Anbindung in `alice-chat-stream`** — neue Listen-Tools für das LLM, deterministische Mehrfach-Trennung, Antworten per Vorlage, erzwungene Tool-Nutzung je Absicht (PROJ-87-Mechanismen wiederverwendet).
3. **Kombinierte Tagesabfrage** — der Chat-Service ruft Kalender **und** Listen ab und setzt eine gemeinsame Antwort zusammen.
4. **Rückbau** des Einkaufslisten-Pfads aus PROJ-83 (HA_FAST).
5. **Admin-Bereich:** Rollen-Schalter „Listen nutzen“ in der Nutzerverwaltung (neben Timer- und Kalender-Rollen).

Kein n8n-Workflow, keine neue UI-Seite (die kommt mit PROJ-107), keine Cloud.

### A) Komponentenstruktur

Einzige sichtbare UI-Änderung:

```
Settings → Nutzer-Verwaltung (bestehend, admin)
+-- Rollen-Abschnitt Timer      (bestehend)
+-- Rollen-Abschnitt Kalender   (bestehend)
+-- Rollen-Abschnitt Listen     (NEU)
    +-- je Rolle: Schalter „Listen nutzen“ (admin/user/child an, guest aus)
```

Wiederverwendet: das Rollen-Abschnitt-Muster von `TimerRolesSection` / `CalendarRolesSection`, i18n-Schicht (de/en). Alles andere läuft über Chat und Sprache.

### B) Datenmodell (einfach beschrieben)

**Tabelle „Listen“** — eine Zeile pro Liste:
- Eindeutige ID, Name
- Besitzer/Ersteller (User); bei privaten Listen der einzige Zugriffsberechtigte
- Art: privat oder gemeinsam
- Einkaufslisten-Kennzeichen (höchstens eine Liste im ganzen Haushalt; nur gemeinsame Listen können es tragen — per Datenbank erzwungen)
- Zeitstempel

Regeln, die die Datenbank selbst absichert: Listennamen sind je Sichtbarkeitsbereich ohne Beachtung der Groß-/Kleinschreibung eindeutig (gemeinsam: haushaltsweit; privat: je Besitzer). Dass ein *anderer* User einen Namen nutzt, den eine für ihn unsichtbare private Liste trägt, bleibt dadurch erlaubt. Wird ein User gelöscht, verschwinden seine privaten Listen mit; seine gemeinsamen Listen bleiben (Ersteller wird leer, danach nur noch Admin zuständig).

**Tabelle „Einträge“** — eine Zeile pro Eintrag:
- Eindeutige ID, Liste (Löschen der Liste löscht die Einträge mit)
- Titel (Pflicht, beliebig lang), Notiz
- Fälligkeit und Frist — jeweils Zeitpunkt plus Kennzeichen „nur Datum / mit Uhrzeit“ (damit „morgen“ ohne Uhrzeit von „morgen 14 Uhr“ unterscheidbar ist und die Sommerzeit stimmt)
- Priorität (hoch / normal / niedrig)
- Status offen/erledigt, Zeitpunkt des Abhakens, wer abgehakt hat
- Angelegt von, Zeitstempel

Erledigte Einträge werden 30 Tage nach dem Abhaken endgültig entfernt (täglicher Aufräum-Lauf im Service).

**Standardliste je User:** wird am User gespeichert (Verweis auf eine Liste). Fällt die Liste weg, greift automatisch „Meine Aufgaben“, die bei Bedarf neu angelegt wird.

**Berechtigung:** neues Flag „Listen nutzen“ bei Rollen-Vorlagen und Assistenten-Berechtigungen (wie `can_use_timers` / `can_use_calendar`); die Funktion, die neuen Usern Rechte zuweist, übernimmt es. Die feinere Abstufung aus der Spec (child darf lesen/anlegen/abhaken, aber nicht entfernen; Einkaufsliste kennzeichnen/löschen nur admin) ist **fest im Service verdrahtet** und nicht pro Rolle konfigurierbar — die Spec sieht im Admin-Bereich nur eine Rollenebene vor; mehr Schalter wären Spekulation. *(Zur Bestätigung, siehe Offene Punkte 1.)*

**Löschbestätigung & offene Rückfragen (flüchtig):** wie bei PROJ-87 kurzzeitig im vorhandenen Redis, kein neuer Dauer-Speicher.

Alle neuen Tabellen: Row Level Security aktiv, Indizes auf Besitzer, Liste, Status und Datumsfelder.

### C) Ablauf-Architektur

**Sprecher und Zugriff (für jede Aktion, serverseitig)**
1. Chat-Service ermittelt den Sprecher (Nil-UUID = unbekannt) und die Rolle **frisch aus der Datenbank** (das Gateway-JWT behauptet immer „user“).
2. `alice-lists` prüft Rolle × Aktion × Listenart. Private Listen sind nur für den Besitzer sichtbar — auch Admins sehen sie nicht (die Abfragen filtern hart nach Besitzer, zusätzlich RLS).
3. Unbekannter Sprecher: ausschließlich „zur gekennzeichneten Einkaufsliste hinzufügen“. Alles andere → Ablehnung mit Hinweis, dass Alice nicht weiß, wer spricht. Kein Fallback auf Admin/Gerät. Ohne Berechtigung werden dem LLM nur dann Tools angeboten, wenn sie nutzbar sind; ansonsten erklärt ein Prompt-Hinweis die Ablehnung.

**Mehrere Einträge in einem Satz — deterministisch**
Das LLM extrahiert nur die Rohangabe pro Aufruf (z. B. „Milch, Butter und Eier“ als *ein* Textfeld plus Liste/Datum/Priorität). Die Trennung an jedem Komma und jedem „und“ passiert **im Service per festem Regelwerk**, nicht im Modell; Mengenangaben („2 Packungen Milch“) bleiben am Eintrag. So bleibt „Salz und Pfeffer“ garantiert zwei Einträge. Gleiches gilt für Abhaken und Entfernen mehrerer Einträge.

**Einträge anlegen**
1. Liste bestimmen: genannt → Auflösung (exakt → eindeutig ähnlich → bei mehreren Rückfrage); „Einkaufsliste/Einkaufszettel“ → gekennzeichnete Liste; sonst Standardliste. Unbekannt → Rückfrage „anlegen?“. Gleichnamig privat/gemeinsam → Rückfrage „deine private oder die gemeinsame?“.
2. Datumslogik: Fälligkeit/Frist auflösen (Zeitzone des Users, Uhrzeit ohne Datum = heute bzw. morgen, wenn verstrichen). Vergangenes Datum oder Frist vor Fälligkeit → Rückfrage-Ergebnis statt stillschweigendem Speichern.
3. Duplikate: Einkaufsliste → ohne Hinweis anlegen; steht der Artikel als erledigt drauf → wieder öffnen. Andere Listen → Rückfrage, wenn offener Eintrag gleichen Titels existiert.
4. Speichern und **das tatsächlich Gespeicherte** zurückgeben; die Vorlagen-Antwort zählt es auf (Eintrag, Liste, Fälligkeit/Frist/Priorität).

**Abfragen**
Filter: Liste, Zeitraum, nur Fristen, überfällig, „steht X drauf?“, Anzahl, erledigt (max. 30 Tage). Ohne Listenname werden alle sichtbaren Listen durchsucht. Sortierung wie in der Spec (überfällig → früheres Datum → Priorität → ohne Datum); Kürzung Sprache max. 5 + Rest, Chat max. 50 mit Hinweis.

**Ändern / Abhaken / Wieder öffnen**
Eintrag wird über den (ungefähren) Titel gefunden; 0 Treffer → klare Meldung, mehrere → Kandidatenliste für die Rückfrage (bei gleichnamigen Einträgen in mehreren Listen mit Listennamen). Abhaken/Öffnen/Ändern ohne Rückfrage. Gleichzeitige Aktionen (zwei User haken dasselbe ab) werden als „bereits erledigt/nicht mehr vorhanden“ gemeldet, nie als Fehler.

**Entfernen — zweistufig, serverseitig abgesichert (nur außerhalb der Einkaufsliste)**
Identisch zum PROJ-87-Muster: Stufe 1 identifiziert genau einen Eintrag und gibt ein einmaliges Ticket aus (an User, Eintrag, Session und Turn gebunden); Stufe 2 löscht nur mit einem Ticket **aus dem unmittelbar vorherigen Turn** und nach erneuter Prüfung, dass der Eintrag unverändert existiert. Ein „Ja“ führt so verlässlich zum Löschen (Chat und Voice), „Nein“ oder ein anderer Turn lässt das Ticket verfallen. Auf der Einkaufsliste entfällt die Rückfrage; Child wird dort höflich abgewiesen mit Hinweis auf „Abhaken“. **Listen löschen** nutzt denselben Ticket-Mechanismus (Rückfrage nennt die Anzahl der Einträge, bei der Einkaufsliste den Hinweis darauf; nur Admin).

**Listenverwaltung**
Anlegen (privat/gemeinsam), Umbenennen, Löschen, Standardliste setzen, Übersicht, Einkaufsliste kennzeichnen (nur Admin; Kennzeichen wandert, Bestätigung nennt die bisherige Liste). Namens-Eindeutigkeit und Rechte (Admin + Ersteller bei gemeinsamen Listen) werden im Service geprüft. Ohne Einkaufsliste werden Einkaufslisten-Anfragen mit Hinweis auf den Admin abgelehnt — auch für unbekannte Sprecher.

**Kombinierte Tagesabfrage (PROJ-87-Änderung)**
Der Chat-Service entscheidet die Absicht **vor** dem LLM-Aufruf per festen Stichwortregeln (Termin/Kalender → nur Kalender; Aufgabe/fällig/Frist/überfällig/Listenname → nur Listen; allgemeine „Was steht an?“ → beides). Bei „beides“ werden Kalender und Listen parallel abgefragt (je nach Berechtigung/Verbindung auch nur eines davon), und **eine** Vorlagen-Antwort setzt Termine zuerst, dann Fälligkeiten und Fristen zusammen; Sprache insgesamt max. 5 Elemente + Rest. Keine Rückfrage. Eine Lücke in einem der beiden Teile (z. B. Google nicht erreichbar) führt zu der Antwort des anderen Teils plus kurzem Hinweis.

**Antwortverhalten (aus PROJ-87 übernommen)**
- Antworten entstehen **aus Vorlagen** anhand strukturierter Service-Ergebnisse, nicht aus freier LLM-Formulierung → kurz, ohne interne Begriffe, ohne erfundene Erfolge. Sprache der Vorlagen folgt der Nutzersprache.
- **Erzwungene Tool-Nutzung** je erkannter Absicht in der ersten Runde (`tool_choice=required`), Text dieser Runde wird verworfen; nach einer Rückfrage keine Tools im Antwort-Turn außer der Bestätigung.
- **Offene Rückfrage über Turns hinweg:** der Service merkt sich die letzte offene Rückfrage je User+Session (Redis) und liefert sie für genau den Folgeturn.
- **Voice:** Vorlagen sprechen Datum/Uhrzeit aus; `conversation_end` nach abgeschlossener Aktion, offen bei Rückfrage; Token-Limit und Wiederholungsbremse wie bei Kalender.
- **HA_FAST-Umgehung:** Listen-Anfragen und Antworten auf offene Listen-Rückfragen werden nicht vom Smart-Home-Schnellpfad abgefangen (analog zur Kalender-Umgehung).

**Fehlerbehandlung**
Datenbank/Service nicht erreichbar → klare Fehlermeldung ohne Erfolgsbehauptung; keine Tool-Ergebnisse ohne bestätigte Speicherung. Zeitüberschreitung → „später nochmal versuchen“. Keine Teilausführung ohne Hinweis: bei Mehrfach-Aktionen werden erledigte und nicht gefundene Einträge getrennt benannt.

### D) Tech-Entscheidungen (Begründung)

- **Eigener Service `alice-lists`** statt Modul im Chat-Service: PROJ-107 (WebApp), PROJ-108 (Erinnerungen), PROJ-109/110 bauen darauf auf und brauchen dieselben Regeln über eine Schnittstelle. Die Regeln (Rechte, Duplikate, Einkaufsliste) gehören nicht in den Orchestrierungs-Service. Aufwand: ein Container mehr — bewährtes Muster aus PROJ-87.
- **Kein n8n:** Datums-/Zeitzonenlogik, Trennregel und Rechteprüfung brauchen automatisierte Tests; n8n-Code-Nodes sind dafür ungeeignet und langsamer (Ziel < 2 s).
- **Eigene Datenbanktabellen statt Weaviate:** strukturierte, relationale Daten mit Filtern, Sortierung und Rechten — Weaviate bringt hier nichts. Ungefähre Namensauflösung („Baumarktliste“ → „Baumarkt“) geschieht per einfacher Ähnlichkeitssuche in PostgreSQL; kein Embedding nötig.
- **Eine Listen-Art, zwei Sichtbarkeiten:** ein Modell für Einkaufen und Aufgaben (wie in der Spec); die Einkaufsliste ist nur ein Kennzeichen an einer gemeinsamen Liste, keine eigene Struktur.
- **Fälligkeit/Frist als Zeitpunkt + „mit/ohne Uhrzeit“:** nur so lässt sich „morgen“ von „morgen 14 Uhr“ trennen, ohne Zeitzonen- und Sommerzeitfehler.
- **Trennregel im Code, nicht im Prompt:** Spec fordert Determinismus; ein Prompt garantiert „Salz und Pfeffer = zwei Einträge“ nicht.
- **Rechte serverseitig + RLS statt nur Prompt:** Rolle wird frisch aus der DB gelesen, private Listen sind doppelt abgesichert (Abfragefilter + RLS) — auch gegen Admin.
- **Lösch-Ticket wiederverwendet:** gleicher Mechanismus wie PROJ-87, damit Hörfehler per Voice nie etwas ohne „Ja“ löschen. Wenn möglich wird der Ticket-Code gemeinsam genutzt statt kopiert (Entscheidung in der Umsetzung, siehe Offene Punkte 3).
- **Vorlagen-Antworten:** hat bei PROJ-87 erfundene Erfolge und Geschwätz beseitigt; wird übernommen.
- **Kein HA_FAST:** Listen-Anfragen sind kein < 200-ms-Fall; sie laufen über den LLM-Tool-Pfad mit erzwungener Tool-Wahl.

### E) Offene Punkte / Änderungen an bestehenden Teilen

1. **Feinabstufung der Rechte:** Vorschlag wie oben — ein Rollen-Schalter „Listen nutzen“ im Admin-Bereich; die Unterschiede admin/user/child (Entfernen, Listen verwalten, Einkaufsliste) sind fest im Service. Alternative wäre ein eigener Schalter je Aktion — würde über die Spec hinausgehen.
2. **Rückbau PROJ-83:** der Einkaufslisten-Pfad in `ha_path.py` (Schreiben nach `todo.einkaufsliste`, zugehörige Intents/Vorlagen, Tests) entfällt vollständig; HA-Sync-Daten zur Einkaufsliste werden darauf geprüft, ob sie Reste hinterlassen.
3. **Gemeinsamer Ticket-Code:** `tickets.py` aus `alice-calendar` ist fachlich identisch nutzbar. Sauberste Lösung (gemeinsames Modul vs. angepasste Kopie in `alice-lists`) wird in der Umsetzung entschieden; Kalender-Verhalten darf sich nicht ändern.
4. **PROJ-87-Anpassung Tagesabfrage:** Stichwort-Weiche und kombinierte Antwortvorlage liegen im Chat-Service; die bestehende reine Kalender-Antwort bleibt für „Termin/Kalender“-Anfragen unverändert.
5. **Erste Nutzung / Startdaten:** Migration legt die gemeinsame „Einkaufsliste“ (gekennzeichnet) an; „Meine Aufgaben“ entsteht pro User beim ersten Gebrauch. Keine Datenmigration aus HA/Google (Out of Scope).
6. **Speaker-ID:** unbekannter Sprecher funktioniert technisch bereits über die Nil-UUID; die Qualität der Erkennung gehört zu PROJ-103.
7. **System-Prompt/Tool-Beschreibungen:** Erfolg nur nach bestätigtem Tool-Ergebnis melden; bei Rückfrage-Ergebnissen (mehrdeutig, unbekannte Liste, Duplikat, Vergangenheit, Löschticket) den User fragen; optionale Felder nie erfragen.

### F) Neue/geänderte Infrastruktur

- Neuer Service-Ordner `docker/compose/automations/alice-lists/` (Dockerfile, compose.yml, `.env.example`, Tests), Eintrag in `docker/compose/scripts/Makefile` (STACKS), `.gitignore` für `.env`
- Neue nginx-Location `/api/lists/` → `alice-lists` (normale Timeouts, eigene Rate-Limit-Zone; für PROJ-107 vorbereitet; Chat-Tools laufen intern ohne nginx)
- Neue Migration: Tabellen Listen + Einträge (RLS, Indizes), Standardliste am User, Flag „Listen nutzen“ in Vorlagen/Berechtigungen, angepasste Rechte-Zuweisungsfunktion, Backfill für bestehende User, Startliste „Einkaufsliste“
- `alice-chat-stream`: neue Tool-Definitionen + Dispatch, Absichtserkennung/Weiche (Listen / Kalender / kombiniert), Vorlagen-Antworten, Berechtigungs-/Sprecher-Vorprüfung, HA_FAST-Umgehung, Prompt-Anpassung, neue Env `LISTS_URL`; Rückbau Einkaufslisten-Pfad
- `alice-auth`: `/auth/permissions` liefert zusätzlich `can_use_lists`
- Frontend: Rollen-Abschnitt „Listen“ in der Nutzerverwaltung, Service-Client, i18n-Keys (de/en) — keine neue Route
- Täglicher Aufräum-Lauf (erledigte Einträge > 30 Tage) im Service

### G) Dependencies (Pakete)

- Backend `alice-lists`: `fastapi`, `uvicorn`, `asyncpg`, `httpx`, `redis` (Tickets/Rückfragen), `pyjwt` + `cryptography` (RS256), `tzdata` (Zeitzonen), `pytest` (Tests) — dieselben wie `alice-calendar`
- Frontend: keine neuen Pakete (vorhandene shadcn/ui-Bausteine)

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
