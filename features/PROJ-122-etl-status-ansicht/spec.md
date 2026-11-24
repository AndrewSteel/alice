# PROJ-122: ETL-Status-Ansicht (Admin, WebApp)

**Erstellt:** 2026-11-24
**Phase:** 4.1

<!-- Der Status steht nur in features/INDEX.md. Diese Datei schreibt nur der Mensch (/write-spec, /refine). -->

## Abhängigkeiten
- Benötigt: PROJ-115 (Quelle-der-Wahrheit-Repo + Quellen-Register) — Stufen, Stufenzustände, Versuchszähler, Fehlermeldungen, „erneut versuchen“, Sperre bei ungültigem Frontmatter, Ereignisse je Quelle, Fundorte
- Benötigt: PROJ-120 (Neuaufbau + Vollständigkeitsabgleich) — Schnittstelle für Neuaufbau-Steuerung, Fortschritt, Fehlerliste, Läufe, Abgleich auf Abruf, Neu-Hashen, Abgleich-Ergebnisse
- Benötigt: PROJ-121 (Rollenmodell Haushalt) — Rolle `admin`
- Benötigt: PROJ-77 (Admin-Dashboard, Historie) — Kachel-Registry für die ETL-Kachel
- Spätere Stufen (z. B. `rag`, `wiki`, `thumbnail`) und Abgleich-Ebenen aus PROJ-123–129 erscheinen ohne Änderung an PROJ-122

## Überblick
PROJ-122 macht den Zustand des neuen ETL für den Admin sichtbar und bedienbar. Es gibt dafür eine eigene Admin-Seite in der WebApp. Sie zeigt den Verarbeitungsstand aller Quellen je Stufe, führt zu Fehlern mit Ursache, erlaubt „erneut versuchen“, steuert den Neuaufbau und zeigt die Ergebnisse des Vollständigkeitsabgleichs. Eine Kachel im Admin-Dashboard fasst das Wichtigste zusammen und verlinkt auf die Seite.

PROJ-122 baut keine eigene Pipeline-Logik. Es nutzt Register (PROJ-115) und Neuaufbau/Abgleich (PROJ-120) und macht deren interne Schnittstellen über eine admin-geschützte Schnittstelle für die WebApp zugänglich.

## User Stories
- Als Admin möchte ich auf einen Blick sehen, wie viele Quellen in welcher Stufe in welchem Zustand sind, damit ich weiß, ob der ETL rund läuft.
- Als Admin möchte ich alle fehlgeschlagenen und gesperrten Quellen mit Fehlerursache finden, damit keine Quelle still verloren geht.
- Als Admin möchte ich zu einer Quelle alle Stufen, Fundorte und Ereignisse sehen, damit ich einen Fehler nachvollziehen kann.
- Als Admin möchte ich eine fehlgeschlagene Stufe einzeln oder für eine Auswahl erneut versuchen, nachdem ich die Ursache behoben habe.
- Als Admin möchte ich einen Neuaufbau mit Startstufe und Art starten, seinen Fortschritt mit Restzeit verfolgen und ihn pausieren, fortsetzen oder abbrechen.
- Als Admin möchte ich morgens sehen, ob der nächtliche Abgleich vollständig war und was er repariert oder gemeldet hat, und einen Abgleich bei Bedarf selbst anstoßen.
- Als Haushaltsmitglied oder Gast möchte ich diese Verwaltungsansicht weder sehen noch erreichen können.

## Fachliches Modell

### Ort und Zugang
- Eigene Seite (eigene Route) in der WebApp, nur für `admin`.
- Einstieg über die Dashboard-Kachel „ETL“ und einen zusätzlichen Eintrag „ETL-Status“ in der UserCard (nur für Admins). Von der Seite zurück zu Dashboard bzw. Chat.
- Alle Daten und Aktionen sind serverseitig auf `admin` beschränkt. `haushalt` und `guest` bekommen 403 und werden von der Seite weggeleitet wie bei anderen Admin-Bereichen. Sie sehen weder Kachel noch Menüeintrag.

### Bereiche der Seite
1. **Zusammenfassung oben:**
   - Status des letzten Abgleichs: Zeitpunkt, Art, `vollständig`/`unvollständig` mit Grund, Anzahl der Lücken, Reparaturen und Meldungen. Auffällig hervorgehoben, wenn er älter als 36 h oder `unvollständig` ist.
   - Kurzstand eines aktiven Neuaufbaus.
   - Anzahl der Fehler.
2. **Übersicht (Matrix):**
   - Zeilen sind die Stufen in der Reihenfolge des Registers, Spalten die Zustände `pending`, `running`, `done`, `failed`, `failed_permanent`, `skipped`. Jede Zelle zeigt die Anzahl der Quellen.
   - Filter nach Art (`document`, `image`, `email`, `audio`, `video`).
   - Gelöschte Quellen zählen standardmäßig nicht mit; ein Filter blendet sie ein.
   - Neue Stufen aus späteren Features erscheinen automatisch als Zeile.
3. **Quellenliste:**
   - Öffnet sich per Klick auf eine Matrix-Zelle und ist danach nach Stufe und Zustand gefiltert. Seitenweiser Abruf.
   - Spalten: Titel, Art, Zustand, Versuche, letzte Fehlermeldung (gekürzt), Zeitpunkt des letzten Versuchs, nächster Retry.
   - Weitere Filter: Art, gelöscht ja/nein, gesperrt (ungültiges Frontmatter). Suche nach Titel oder `id`.
4. **Fehler:**
   - Alle Quellen mit mindestens einer Stufe in `failed` oder `failed_permanent` oder mit Sperre durch ungültiges Frontmatter, über alle Stufen hinweg.
   - Sortiert nach jüngstem Fehler, mit Filter nach Stufe, Zustand und Art. Seitenweiser Abruf.
5. **Quellen-Detail:**
   - Für eine Quelle: `id`, Titel, Art, Typ, Hash, gelöscht ja/nein, Sperre mit Ursache.
   - Alle Stufen mit Zustand, Versuchen, vollständiger Fehlermeldung, Zeitpunkt des letzten Versuchs und nächstem Retry.
   - Alle Fundorte (vorhanden/verschwunden), die Ereignisse aus dem Register (neueste zuerst) und der Pfad der Quell-Markdown im Repo.
6. **Neuaufbau:** Start, laufender Lauf, Fehlerliste des Laufs, Verlauf (siehe unten).
7. **Abgleich:** letzte Ergebnisse, Detail, Auslösen auf Abruf (siehe unten).

### Erneut versuchen
- **Einzeln:** Im Quellen-Detail hat jede Stufe mit `failed` oder `failed_permanent` den Button „erneut versuchen“. Er setzt die Stufe über PROJ-115 auf `pending` mit Versuchszähler 0.
- **Sammelweise:** In Quellenliste und Fehlerbereich gibt es „Alle N erneut versuchen“ für die aktuelle Filterauswahl. Er wirkt nur auf Stufen in `failed`/`failed_permanent` innerhalb der Auswahl. Vorher kommt ein Bestätigungsdialog mit der Anzahl.
- **Grenze:** Eine Auswahl mit mehr als einer einstellbaren Zahl (Standard 1.000) Quellen kann nicht sammelweise wiederholt werden. Die Ansicht verweist auf den Neuaufbau, weil dieser gedrosselt läuft und den Normalbetrieb nicht flutet.
- **Nicht angeboten:**
  - Retry für gesperrte Quellen. Die Ansicht zeigt die Ursache und den Hinweis, die Quell-Markdown von Hand zu reparieren.
  - Erneutes Anstoßen einer `done`-Stufe (dafür gibt es den Neuaufbau).
  - Retry für gelöschte Quellen.
- Jede Retry-Aktion wird als Ereignis an der Quelle protokolliert, mit dem Namen des Admins.

### Neuaufbau
- **Starten:**
  - Dialog mit Startstufe (alle Stufen außer `detect`) und optional einer Art.
  - Vor der Bestätigung eine Vorschau: ungefähre Anzahl betroffener Quellen und die Stufen, die neu laufen (Startstufe und alle folgenden).
  - Als „gestartet von“ wird der Name des angemeldeten Admins übergeben.
  - Ist bereits ein Lauf aktiv oder pausiert, ist der Start deaktiviert und nennt den Grund.
- **Laufender oder pausierter Lauf:**
  - Status mit Grund (`läuft`, `pausiert`, `wartet`), Umfang, Start, „gestartet von“, Gesamtzahl, Ausgenommene je Grund.
  - Je Stufe ein Balken: erledigt, fehlgeschlagen, in Arbeit, offen.
  - Durchsatz, geschätzte Restzeit (oder „unbekannt“, z. B. bei Durchsatz 0) und Zeitpunkt des Stands.
  - Buttons Pausieren, Fortsetzen und Abbrechen, jeweils nur, wo sinnvoll. Abbrechen fragt vorher nach.
- **Fehlerliste des Laufs:** `id`, Titel, Stufe, Fehlermeldung; seitenweise, mit Sprung ins Quellen-Detail.
- **Verlauf:** Liste der beendeten Läufe (`abgeschlossen`, `abgebrochen`) mit Umfang, Zeiten, „gestartet von“, Endzahlen und Link zum zugehörigen Abgleich-Ergebnis.
- Die Drosselung N wird nicht in der Oberfläche eingestellt; sie bleibt Dienst-Konfiguration (PROJ-120).

### Abgleich
- **Liste der Ergebnisse** der letzten mindestens 30 Tage: Zeitpunkt, Dauer, Art (nachts, auf Abruf, nach Neuaufbau), Status mit Grund, Anzahl der Lücken, Reparaturen und Meldungen; seitenweise.
- **Ergebnis-Detail:**
  - Je Ebene die Lücken als Liste, getrennt in „repariert“ und „nur gemeldet“.
  - Hinweis, wenn die Sicherung gegen Massenreparatur gegriffen hat.
  - Übersprungene Ordner und Fortschritt des Hash-Zyklus.
  - Lücken mit Quellen-`id` springen ins Quellen-Detail.
  - Später hinzukommende Ebenen erscheinen ohne Änderung an PROJ-122.
- **Auf Abruf:** Buttons „Abgleich jetzt“ und „Vollständig neu hashen“; der zweite fragt vorher nach, weil er das ganze NAS liest. Läuft bereits ein Abgleich, sind beide deaktiviert und nennen den Grund.
- Keine Aktionen auf einzelnen Lücken (z. B. Markdown ohne Registereintrag löschen); gemeldete Fälle behebt der Admin von Hand.

### Dashboard-Kachel „ETL“
- Kommt neu ins Admin-Dashboard (über die Kachel-Registry) und zeigt drei Zeilen:
  - Fehler gesamt (`failed_permanent` + gesperrt), dahinter `failed` mit geplantem Retry.
  - Aktiver Neuaufbau mit Status und Prozent, oder „kein Lauf“.
  - Letzter Abgleich mit Status, Zeitpunkt und Ampel.
- **Ampel:**
  - grün: letzter Abgleich `vollständig`, nicht älter als 36 h, keine `failed_permanent`/gesperrten Quellen
  - gelb: `failed_permanent` oder gesperrte Quellen vorhanden, oder nur gemeldete Lücken
  - rot: letzter Abgleich `unvollständig`, älter als 36 h oder nicht vorhanden
- Ein Klick öffnet die ETL-Seite.
- Die alten Kacheln (`DmsCoverageTile`, `DmsQualityWarningsTile`) bleiben unverändert.

### Aktualisierung
- Die Seite aktualisiert sich automatisch, Standard alle 5 s. Ein Auswahlfeld bietet „aus / 5 s / 15 s / 60 s“; die Wahl wird im Browser gemerkt.
- Die Kachel aktualisiert sich im Takt der übrigen Dashboard-Kacheln.

### Störungen und leere Zustände
- **Register oder Neuaufbau/Abgleich-Dienst nicht erreichbar:**
  - Ein Banner meldet „Status-Dienst nicht erreichbar“.
  - Die zuletzt geladenen Daten bleiben mit Zeitstempel und Vermerk „veraltet“ sichtbar, Aktions-Buttons sind deaktiviert.
  - Der Auto-Refresh versucht es weiter, ohne wiederholte Fehler-Toasts.
- **Aktion abgelehnt oder fehlgeschlagen:** Ein Toast zeigt den Grund aus der Schnittstelle, danach lädt die Ansicht neu. Doppelte Aktionen, z. B. aus zwei Tabs, sind harmlos.
- **Leere Zustände** mit Erklärung statt leerer Tabellen: „Noch keine Quellen registriert“, „Keine Fehler“, „Noch kein Neuaufbau gelaufen“, „Noch kein Abgleich“.

### Darstellung und Sprache
- Alle Texte laufen über die i18n-Schicht (Deutsch und Englisch). Fehlermeldungen der Stufen und Gründe aus dem Register werden unverändert angezeigt.
- Zeiten stehen in lokaler Zeit: relativ („vor 3 min“), wo es um Aktualität geht, sonst absolut.
- Mobil bedienbar; breite Tabellen und die Matrix scrollen horizontal in ihrem Container, die Seite selbst nicht.

## Außerhalb des Umfangs
- Pipeline-Logik: Stufen, Retry-Backoff, Neuaufbau-Ablauf, Abgleich (PROJ-115–120)
- Einstellen der Drosselung N, der Abgleich-Grenzen oder Zeitpläne in der Oberfläche (bleibt Dienst-Konfiguration)
- Bearbeiten oder Anzeigen des Inhalts von Quell-Markdowns in der WebApp, Hand-Korrekturen über die Oberfläche
- Aktionen auf einzelne Abgleich-Lücken (Löschen, Zuordnen)
- Erneutes Anstoßen von `done`-Stufen einzelner Quellen (nur per Neuaufbau)
- Aktive Benachrichtigungen (Push, Mail)
- Zugriff für `haushalt` oder `guest`, Anzeige per Sprache
- Änderungen oder Entfernen der alten Dashboard-Kacheln und Altsystem-Ansichten (PROJ-142)
- Logs der Dienste in der Oberfläche (Grafana/Log-Ansichten bleiben, wie sie sind)

## Akzeptanzkriterien

### Zugang und Navigation
- [ ] AK-1: Angenommen ein angemeldeter `admin`, wenn er das Dashboard öffnet, dann sieht er die Kachel „ETL“, und ein Klick darauf öffnet die ETL-Seite.
- [ ] AK-2: Angenommen ein angemeldeter `admin`, wenn er die UserCard öffnet, dann gibt es den Eintrag „ETL-Status“, der die ETL-Seite öffnet.
- [ ] AK-3: Angenommen ein angemeldeter `haushalt`- bzw. `guest`-Nutzer, wenn er die Route der ETL-Seite direkt aufruft, dann wird er weggeleitet und sieht keine ETL-Daten; Kachel und Menüeintrag sind für ihn nicht vorhanden.
- [ ] AK-4: Angenommen ein `haushalt`-, ein `guest`-Nutzer und ein nicht angemeldeter Aufruf, wenn sie die ETL-Schnittstelle (Lesen und jede Aktion) direkt aufrufen, dann antwortet sie mit 403 bzw. 401 und ändert nichts.

### Übersicht, Liste, Detail
- [ ] AK-5: Angenommen ein Register mit Quellen verschiedener Arten und Stufenzustände, wenn der Admin die Seite öffnet, dann zeigt die Matrix je Stufe und Zustand genau die Anzahl aus dem Register (ohne gelöschte Quellen).
- [ ] AK-6: Angenommen der Art-Filter `document`, wenn er gesetzt wird, dann zählt die Matrix nur Dokumente; mit dem Filter „gelöschte einblenden“ zählen gelöschte Quellen mit.
- [ ] AK-7: Angenommen eine zusätzliche Stufe wird im Register angelegt, wenn die Seite neu lädt, dann erscheint sie als Zeile in der Matrix an ihrer Position, ohne Änderung an PROJ-122.
- [ ] AK-8: Angenommen 3 Quellen mit `classify` = `failed_permanent`, wenn der Admin auf diese Zelle klickt, dann zeigt die Quellenliste genau diese 3 mit Titel, Art, Zustand, Versuchen, letzter Fehlermeldung, letztem Versuch und nächstem Retry.
- [ ] AK-9: Angenommen 120 Quellen in einer Zelle, wenn die Liste geöffnet wird, dann wird sie seitenweise geladen, und alle 120 sind über die Seiten erreichbar.
- [ ] AK-10: Angenommen eine Quelle mit bekanntem Titelteil bzw. `id`, wenn der Admin danach sucht, dann findet die Liste sie.
- [ ] AK-11: Angenommen Quellen mit `failed` in `extract`, `failed_permanent` in `classify` und eine durch ungültiges Frontmatter gesperrte Quelle, wenn der Admin den Fehlerbereich öffnet, dann enthält er alle drei, sortiert nach jüngstem Fehler; Filter nach Stufe, Zustand und Art grenzen korrekt ein.
- [ ] AK-12: Angenommen eine Quelle mit zwei Fundorten (einer verschwunden), Ereignissen und einer fehlgeschlagenen Stufe, wenn der Admin ihr Detail öffnet, dann sieht er `id`, Titel, Art, Typ, Hash, gelöscht/gesperrt, alle Stufen mit Zustand, Versuchen, vollständiger Fehlermeldung, Zeitpunkten, beide Fundorte mit ihrem Zustand, die Ereignisse (neueste zuerst) und den Pfad der Quell-Markdown.

### Erneut versuchen
- [ ] AK-13: Angenommen eine Stufe in `failed_permanent` mit Versuchszähler 5, wenn der Admin im Detail „erneut versuchen“ klickt, dann steht sie auf `pending` mit Versuchszähler 0, die Ansicht zeigt den neuen Zustand, und an der Quelle steht ein Ereignis mit dem Namen des Admins.
- [ ] AK-14: Angenommen eine Stufe in `failed` (Retry geplant), wenn der Admin „erneut versuchen“ klickt, dann steht sie sofort auf `pending` mit Versuchszähler 0.
- [ ] AK-15: Angenommen Stufen in `done`, `pending`, `running`, `skipped` sowie eine gesperrte und eine gelöschte Quelle, wenn der Admin deren Detail öffnet, dann gibt es dort keinen „erneut versuchen“-Button; bei der gesperrten Quelle steht die Ursache mit dem Hinweis, die Quell-Markdown von Hand zu reparieren.
- [ ] AK-16: Angenommen eine Filterauswahl mit 40 Quellen, davon 30 mit `failed_permanent` in der gewählten Stufe, wenn der Admin „Alle erneut versuchen“ wählt, dann nennt der Bestätigungsdialog die Anzahl 30, nach Bestätigung stehen genau diese 30 auf `pending` mit Versuchszähler 0, und keine andere Stufe oder Quelle ist verändert.
- [ ] AK-17: Angenommen der Admin bricht den Bestätigungsdialog des Sammel-Retrys ab, wenn er schließt, dann ist nichts verändert.
- [ ] AK-18: Angenommen eine Auswahl mit 1.001 betroffenen Quellen (Grenze 1.000), wenn der Admin den Sammel-Retry auslösen will, dann ist er nicht möglich, und die Ansicht verweist auf den Neuaufbau; auch ein direkter Aufruf der Schnittstelle mit dieser Auswahl wird abgelehnt.
- [ ] AK-19: Angenommen eine Stufe steht beim Klick auf „erneut versuchen“ inzwischen schon auf `pending` (z. B. aus einem zweiten Tab), wenn die Aktion ausgeführt wird, dann ändert sich nichts Fehlerhaftes, und die Ansicht zeigt den aktuellen Zustand.

### Neuaufbau
- [ ] AK-20: Angenommen kein aktiver Lauf, wenn der Admin den Start-Dialog öffnet und Startstufe `classify` und Art `document` wählt, dann zeigt die Vorschau die ungefähre Anzahl betroffener Quellen und die Stufen ab `classify`; `detect` ist nicht wählbar.
- [ ] AK-21: Angenommen der Admin bestätigt den Start, wenn der Lauf angelegt ist, dann hat PROJ-120 einen Lauf mit diesem Umfang und dem Namen des Admins als „gestartet von“, und die Seite zeigt ihn als `läuft`.
- [ ] AK-22: Angenommen ein aktiver oder pausierter Lauf, wenn der Admin die Seite öffnet, dann ist der Start deaktiviert und nennt den bestehenden Lauf als Grund.
- [ ] AK-23: Angenommen ein laufender Lauf (PROJ-120 im Test mit festen Fortschrittsdaten), wenn die Seite ihn anzeigt, dann stehen Status mit Grund, Umfang, Start, „gestartet von“, Gesamtzahl, Ausgenommene je Grund, je Stufe erledigt/fehlgeschlagen/in Arbeit/offen, Durchsatz, Restzeit und Zeitpunkt des Stands genau wie geliefert.
- [ ] AK-24: Angenommen ein Lauf mit Durchsatz 0 bzw. ohne Restzeit-Schätzung, wenn er angezeigt wird, dann steht als Restzeit „unbekannt“.
- [ ] AK-25: Angenommen ein laufender Lauf, wenn der Admin „Pausieren“ klickt, dann ist er bei PROJ-120 pausiert, und die Seite zeigt `pausiert` mit dem Button „Fortsetzen“; „Fortsetzen“ setzt ihn wieder auf `läuft`.
- [ ] AK-26: Angenommen ein laufender Lauf, wenn der Admin „Abbrechen“ klickt, dann kommt eine Rückfrage; erst nach Bestätigung ist der Lauf bei PROJ-120 abgebrochen, bei Abbruch der Rückfrage läuft er unverändert weiter.
- [ ] AK-27: Angenommen ein Lauf mit 2 Fehlern, wenn der Admin die Fehlerliste des Laufs öffnet, dann sieht er beide mit `id`, Titel, Stufe und Fehlermeldung und kann ins Quellen-Detail springen.
- [ ] AK-28: Angenommen zwei beendete Läufe, wenn der Admin den Verlauf öffnet, dann sieht er beide mit Umfang, Status, Zeiten, „gestartet von“, Endzahlen und Link auf das zugehörige Abgleich-Ergebnis.
- [ ] AK-29: Angenommen ein Lauf mit Status `wartet`, wenn er angezeigt wird, dann steht der Grund aus PROJ-120 dabei.

### Abgleich
- [ ] AK-30: Angenommen das letzte Abgleich-Ergebnis ist `vollständig` und 2 h alt, wenn der Admin die Seite öffnet, dann zeigt die Zusammenfassung Zeitpunkt, Art, Status, Lücken, Reparaturen und Meldungen ohne Hervorhebung; ist es `unvollständig` oder älter als 36 h, ist es auffällig hervorgehoben.
- [ ] AK-31: Angenommen Ergebnisse über 31 Tage, wenn der Admin die Liste öffnet, dann sind mindestens die der letzten 30 Tage seitenweise abrufbar.
- [ ] AK-32: Angenommen ein Ergebnis mit reparierten und gemeldeten Lücken auf mehreren Ebenen, gegriffener Massenreparatur-Sicherung und einem übersprungenen Ordner, wenn der Admin das Detail öffnet, dann sieht er je Ebene die Lücken getrennt nach „repariert“/„nur gemeldet“, den Hinweis auf die Sicherung, den Ordner und den Fortschritt des Hash-Zyklus; Lücken mit Quellen-`id` verlinken ins Quellen-Detail.
- [ ] AK-33: Angenommen kein laufender Abgleich, wenn der Admin „Abgleich jetzt“ klickt, dann startet PROJ-120 einen Abgleich auf Abruf; „Vollständig neu hashen“ startet erst nach einer Rückfrage.
- [ ] AK-34: Angenommen ein laufender Abgleich, wenn die Seite angezeigt wird, dann sind beide Buttons deaktiviert und nennen den laufenden Abgleich als Grund.
- [ ] AK-35: Angenommen ein Ergebnis-Detail, wenn der Admin es ansieht, dann gibt es keine Aktion, die eine einzelne Lücke löscht oder ändert.

### Dashboard-Kachel
- [ ] AK-36: Angenommen 4 Quellen mit `failed_permanent`, 1 gesperrte und 7 mit `failed`, ein Neuaufbau bei 63 % und ein vollständiger Abgleich von heute Nacht, wenn das Dashboard angezeigt wird, dann zeigt die Kachel Fehler 5 (dahinter 7 mit geplantem Retry), Neuaufbau `läuft` 63 % und den Abgleich mit Status und Zeitpunkt.
- [ ] AK-37: Angenommen jeweils (a) vollständiger Abgleich < 36 h und keine `failed_permanent`/gesperrten Quellen, (b) `failed_permanent` vorhanden, (c) letzter Abgleich `unvollständig`, älter als 36 h oder nicht vorhanden, wenn die Kachel angezeigt wird, dann ist die Ampel (a) grün, (b) gelb, (c) rot.
- [ ] AK-38: Angenommen die alten Dashboard-Kacheln, wenn PROJ-122 ausgeliefert ist, dann sind sie unverändert vorhanden.

### Aktualisierung, Störungen, Darstellung
- [ ] AK-39: Angenommen die Seite ist offen mit Standard-Refresh, wenn sich ein Stufenzustand im Register ändert, dann zeigt die Seite ihn spätestens nach 5 s plus der Aktualität der Schnittstelle (PROJ-120: ≤ 5 s); mit Refresh „aus“ wird nicht automatisch neu geladen.
- [ ] AK-40: Angenommen der Admin wählt Refresh 60 s, wenn er die Seite neu lädt, dann ist 60 s weiterhin gewählt.
- [ ] AK-41: Angenommen die Seite hat Daten geladen, wenn das Register bzw. der PROJ-120-Dienst nicht mehr antwortet, dann erscheint ein Banner, die letzten Daten bleiben mit Zeitstempel und Vermerk „veraltet“ stehen, Aktionen sind deaktiviert, und es erscheint kein wiederholter Fehler-Toast je Refresh; kommt der Dienst zurück, verschwindet das Banner ohne Neuladen der Seite.
- [ ] AK-42: Angenommen eine Aktion wird von der Schnittstelle abgelehnt (z. B. Neuaufbau-Start, während ein anderer Tab schon gestartet hat), wenn der Admin sie auslöst, dann zeigt ein Toast den Grund, und die Ansicht lädt den aktuellen Stand.
- [ ] AK-43: Angenommen ein leeres Register, keine Fehler, kein Lauf und kein Abgleich, wenn der Admin die Seite öffnet, dann sieht er für jeden Bereich einen erklärenden Leerzustand statt leerer Tabellen.
- [ ] AK-44: Angenommen Sprache Englisch bzw. Deutsch im Profil, wenn der Admin Seite und Kachel öffnet, dann sind alle Texte der Oberfläche in dieser Sprache; es gibt keine fest eingebauten Texte außerhalb der i18n-Schicht.
- [ ] AK-45: Angenommen eine Bildschirmbreite von 375 px, wenn der Admin die Seite bedient, dann sind alle Bereiche und Aktionen erreichbar; Matrix und breite Tabellen scrollen in ihrem Container, die Seite hat keinen horizontalen Scroll.

### Last und Betrieb
- [ ] AK-46: Angenommen ein Register mit 60.000 Quellen und 7 Stufen in der Wegwerf-DB, wenn der Admin die Seite öffnet, dann liefert die Schnittstelle Matrix und Zusammenfassung in < 1 s und eine Seite der Quellen- bzw. Fehlerliste in < 1 s; das Abrufen der Seite greift weder auf Repo noch auf NAS-Ordner zu.
- [ ] AK-47: Angenommen PROJ-122 ist ausgeliefert, wenn das Altsystem arbeitet, dann laufen die alten n8n-Workflows unverändert, und PROJ-122 schreibt weder nach Weaviate noch in Redis-Schlüssel des alten Systems.

### Live-Tests nach Deploy
- [ ] AK-48 (Live-Test nach Deploy): Angenommen der echte Bestand, wenn der Admin die Seite öffnet, dann stimmen die Zahlen der Matrix plausibel mit dem Register überein, die Seite reagiert flüssig, und das Ergebnis des letzten nächtlichen Abgleichs ist sichtbar.
- [ ] AK-49 (Live-Test nach Deploy): Angenommen eine Quelle mit `failed_permanent` (oder eine absichtlich fehlerhafte Testdatei), wenn der Admin sie über die Seite erneut versucht, dann durchläuft sie die Stufe erneut, und das Ergebnis ist in der Ansicht sichtbar.
- [ ] AK-50 (Live-Test nach Deploy): Angenommen ein kleiner Neuaufbau (z. B. ab `database` über eine Art mit wenigen Quellen), wenn der Admin ihn über die Seite startet, pausiert, fortsetzt und durchlaufen lässt, dann zeigt die Seite plausible Fortschrittszahlen, und danach erscheint das Abgleich-Ergebnis „nach Neuaufbau“.

## Edge Cases
- EC-1: Eine Quelle wechselt den Zustand, während der Admin ihr Detail ansieht → der nächste Refresh zeigt den neuen Stand; ein Button für eine nicht mehr gültige Aktion verschwindet bzw. die Aktion wird mit Grund abgelehnt (AK-42).
- EC-2: Die Filterauswahl ändert sich zwischen Bestätigungsdialog und Ausführung des Sammel-Retrys (z. B. Quellen werden inzwischen `done`) → es werden nur Stufen wiederholt, die bei der Ausführung noch `failed`/`failed_permanent` sind; die Rückmeldung nennt die tatsächliche Anzahl.
- EC-3: Die Quelle ist zwischen Liste und Detail gelöscht oder gesperrt worden → das Detail zeigt den neuen Zustand, Retry ist nicht mehr angeboten.
- EC-4: Eine Quelle mit sehr langer Fehlermeldung (mehrere KB, Stacktrace) → in der Liste gekürzt, im Detail vollständig lesbar und umbrechend, ohne das Layout zu sprengen.
- EC-5: Titel mit Sonderzeichen, sehr lang oder leer → wird sicher dargestellt (kein HTML-Einschleusen); ohne Titel erscheint die `id`.
- EC-6: Zwei Admins bzw. zwei Tabs steuern den Neuaufbau gleichzeitig (Pausieren und Abbrechen) → PROJ-120 entscheidet; beide Ansichten zeigen nach dem nächsten Refresh denselben Stand, eine abgelehnte Aktion meldet ihren Grund.
- EC-7: Die Sitzung des Admins läuft ab, während die Seite offen ist → der Auto-Refresh führt zur Anmeldung wie im übrigen Frontend, kein Fehler-Loop.
- EC-8: Die Rolle eines Admins wird während der offenen Sitzung auf `haushalt` herabgesetzt → spätestens die nächste Anfrage wird abgelehnt, die Seite leitet weg.
- EC-9: Der PROJ-120-Dienst ist nicht erreichbar, das Register aber schon → Übersicht, Listen, Detail und Retry funktionieren weiter; nur die Bereiche Neuaufbau und Abgleich zeigen das Banner „nicht erreichbar“ (und umgekehrt).
- EC-10: Eine Art ohne Quellen ist im Filter gewählt → Matrix zeigt überall 0 bzw. einen Leerzustand, kein Fehler.
- EC-11: Neuaufbau mit 0 Quellen im Umfang (PROJ-120 EC-4) → erscheint sofort als `abgeschlossen` mit 0 im Verlauf.

## Technische Anforderungen
- Nur Rolle `admin`; Prüfung serverseitig in der Schnittstelle, nicht nur in der Oberfläche.
- Die internen Schnittstellen von PROJ-115 und PROJ-120 bleiben ohne nginx-Route; die WebApp erreicht nur die neue, admin-geschützte Schnittstelle.
- Frontend-Regeln aus `docs/planning/frontend-design.md` (Abschnitt 9), bestehende UI-Bausteine, i18n für alle Texte.
- Grenze für den Sammel-Retry konfigurierbar (Standard 1.000); neue Variablen nur als Platzhalter in `.env.example`.
- Testbar ohne Produktivsysteme: Wegwerf-Postgres mit Register-Testdaten, PROJ-120 als echter Dienst gegen Wegwerf-DB oder gemockt, Browser-Tests der Seite.
- Keine echten Pfade, Hostnamen oder personenbezogenen Daten im Code oder in Testdaten.

## Offene Fragen
- Keine

## Product Decisions
- Eigene Admin-Seite statt Settings-Tab oder reiner Dashboard-Kachel: Matrix, Listen, Detail, Neuaufbau-Steuerung und Abgleich-Ergebnisse brauchen Platz; die Kachel dient als Einstieg (2026-11-24)
- Aufbau in drei Ebenen (Matrix Stufe × Zustand → gefilterte Quellenliste → Quellen-Detail) plus eigener Fehlerbereich: skaliert auf 50.000+ Quellen, Fehler sind der häufigste Einstieg (2026-11-24)
- „Erneut versuchen“ einzeln und sammelweise für die Filterauswahl, Sammel-Retry auf 1.000 Quellen begrenzt mit Verweis auf den Neuaufbau: Retries haben Vorrang vor Neuaufbau-Arbeit (PROJ-120) und würden den Normalbetrieb sonst fluten (2026-11-24)
- Kein Retry für gesperrte Quellen und kein Einzel-Neuanstoß von `done`-Stufen: Sperren löst nur die Hand-Reparatur, Neuverarbeitung läuft gedrosselt über den Neuaufbau (2026-11-24)
- Drosselung N und Zeitpläne bleiben Dienst-Konfiguration, nicht in der Oberfläche (2026-11-24)
- Auto-Refresh Standard 5 s, wählbar aus / 5 / 15 / 60 s, im Browser gemerkt (2026-11-24)
- Abgleich: Zusammenfassung oben mit Hervorhebung ab 36 h oder `unvollständig`, Detail je Ebene, Auslösen auf Abruf; keine Aktionen auf einzelne Lücken, gemeldete Fälle behebt der Admin von Hand (2026-11-24)
- Dashboard-Kachel mit Fehlerzahl, Neuaufbau und letztem Abgleich samt Ampel; Navigation zusätzlich über die UserCard; alte Kacheln bleiben bis PROJ-142 (2026-11-24)
- Admin-Aktionen (Retry, Neuaufbau-Start) werden mit dem Namen des Admins protokolliert (Ereignis an der Quelle bzw. „gestartet von“) (2026-11-24)
- Bei Ausfall eines Dienstes bleiben die letzten Daten als „veraltet“ sichtbar, Aktionen deaktiviert, keine Toast-Flut (2026-11-24)
