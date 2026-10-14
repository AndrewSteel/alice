# PROJ-112: Panorama-/Großbild-Beschreibung im DMS (zentrale Bildbeschreibung mit Teilbild-Zerlegung)

## Status: Planned
**Created:** 2026-10-14
**Last Updated:** 2026-10-14

## Dependencies
- Betrifft: `dms-extractor-image` (`get_ai_description`, MQTT-Topic `alice/dms/image`) und n8n-Workflow `alice-dms-image-description-backfill`
- Baut auf: PROJ-96 (Backfill Auto-Fortsetzung + Zeitlimit, Deployed) — Zeitfenster, Redis-Lock, Selbstaufruf-Kette und Zählung `updated`/`still_failed` bleiben unverändert; löst PROJ-96 **BUG-5** (Panorama-Bilder → HTTP 413 + Task-Runner-Abbruch)
- Nutzt: PROJ-99 (llama.cpp-Vision-Modell auf `llama-3090`), PROJ-111 (LLM-Gateway mit Priorisierung — Bildbeschreibungen laufen als DMS-Anfragen mit niedriger Priorität)

## Kontext

Bildbeschreibungen scheitern nicht an der Dateigröße, sondern am **Seitenverhältnis**. Heute existieren zwei unabhängige Implementierungen:

1. **`get_ai_description`** im Container `dms-extractor-image` (ausgelöst über MQTT `alice/dms/image`): verkleinert die längste Seite auf 1024 px. Ein Panorama mit 22704×1760 px wird so zu 1024×79 px — die Beschreibung ist unbrauchbar.
2. **`alice-dms-image-description-backfill`** (n8n, zeitgesteuert, für Bilder mit `extraction_failed=true`): liest das Originalbild selbst ein und schickt es unverkleinert als Base64 an das LLM. Große Bilder (z.B. 52,8 MB) scheitern mit HTTP 413 bzw. bringen den n8n-Task-Runner zum Absturz.

Ziel: **eine zentrale Bildbeschreibungs-Funktion** (Eingabe: Dateipfad, Ausgabe: Beschreibungstext), die auch Bilder außerhalb der Standard-Seitenverhältnisse sinnvoll beschreibt. Der Backfill ruft diese Funktion auf, statt selbst das LLM anzusprechen. Ob die Funktion im `dms-extractor-image` verbleibt oder in einen eigenen Container wandert, entscheidet `/architecture`.

## User Stories

- Als Admin möchte ich, dass Panoramabilder (quer und hochkant) eine inhaltlich brauchbare Beschreibung erhalten, damit ich sie über die DMS-Suche wiederfinde.
- Als Admin möchte ich, dass Bildbeschreibungen an genau einer Stelle erzeugt werden, damit Laufzeit-Pfad und Backfill identische Ergebnisse liefern und Verbesserungen nur einmal umgesetzt werden müssen.
- Als Admin möchte ich, dass der Backfill auch sehr große Bilddateien verarbeiten kann, ohne dass n8n an Speichergrenzen oder Request-Größenlimits scheitert.
- Als Admin möchte ich, dass eine fehlgeschlagene Beschreibung nie als scheinbar vollständige Teil-Beschreibung gespeichert wird, damit der Backfill sie später zuverlässig erneut versucht.
- Als Admin möchte ich, dass 200-MP-Aufnahmen (z.B. Oppo Find X9 Ultra) normal beschrieben werden.

## Acceptance Criteria

### Zentrale Beschreibungs-Funktion

- [ ] Es gibt genau **eine** Implementierung der Bildbeschreibung; Eingabe ist ein Dateipfad, Ausgabe ein Beschreibungstext (Schnittstelle wie heute `get_ai_description`)
- [ ] Der MQTT-Verarbeitungspfad (`alice/dms/image`) nutzt diese Funktion; EXIF- und GPS-Extraktion bleiben dort unverändert
- [ ] Die Beschreibung ist weiterhin deutsch, 3–5 Sätze pro (Gesamt-)Bild, max. 50.000 Zeichen (bestehendes Verhalten)
- [ ] Schlägt die Beschreibung fehl, liefert die Funktion einen Fehler (kein leerer oder Platzhalter-Text) — bestehendes Verhalten aus PROJ-99

### Standard-Format (Seitenverhältnis bis einschließlich 2:1 bzw. 1:2)

- [ ] Bilder, deren lange Seite höchstens doppelt so lang ist wie die kurze (Quer- **und** Hochformat), werden als **ein** Bild beschrieben
- [ ] Verkleinerung wie bisher: längste Seite auf 1024 px (Wert konfigurierbar, eine Regel für Einzelbilder und Teilbilder)
- [ ] Beispiel: 6000×4000 (3:2), 4000×6000 (2:3), 3840×2160 (16:9), 4000×2000 (2:1) → je ein LLM-Aufruf, Beschreibung wie bisher

### Nicht-Standard-Format (Seitenverhältnis über 2:1 bzw. 1:2) — Teilbild-Zerlegung

- [ ] Das Bild wird entlang der langen Seite in Teilbilder mit einem Seitenverhältnis von ca. **3:2** (hochkant: **2:3**) zerlegt; benachbarte Teilbilder überlappen um ca. **10 %**
- [ ] Es werden **höchstens 8 Teilbilder** erzeugt; würden mehr benötigt, werden die Teilbilder breiter (bei Hochformat: höher) bis maximal 2:1; reicht auch das nicht (Bild über ca. 16:1), werden trotzdem 8 Teilbilder erzeugt — kein Fehler
- [ ] Jedes Teilbild wird einzeln (verkleinert nach derselben 1024-px-Regel) an das Vision-Modell übergeben
- [ ] Reihenfolge der Teilbilder: links → rechts (Querformat) bzw. oben → unten (Hochformat)
- [ ] Anschließend erzeugt ein weiterer LLM-Aufruf aus den Teil-Beschreibungen **eine** zusammenhängende Gesamtbeschreibung, die das Bild als eine Szene beschreibt (keine Aufzählung „Teil 1 … Teil 8")
- [ ] Beispiel: 22704×1760 (Panorama, ≈12,9:1) → 8 Teilbilder + 1 Zusammenfassung → eine deutsche Beschreibung, die den Bildinhalt erkennbar wiedergibt
- [ ] Beispiel: 1760×22704 (senkrechtes Panorama) → analog, Zerlegung von oben nach unten

### Fehlerverhalten (alles oder nichts)

- [ ] Schlägt ein Teilbild-Aufruf oder die Zusammenfassung fehl (Timeout, HTTP-Fehler, leere Antwort), gilt die gesamte Beschreibung als fehlgeschlagen — es wird **nie** eine Teil-Beschreibung gespeichert
- [ ] Keine automatischen Wiederholungen innerhalb eines Aufrufs; Wiederholung übernimmt der Backfill beim nächsten Lauf
- [ ] Im MQTT-Pfad führt ein Fehler zu `extraction_failed=true` (bestehendes Verhalten)

### Pixel-Obergrenze

- [ ] Bilder bis einschließlich **250 Megapixel** werden verarbeitet (die Pillow-Standardgrenze von ca. 179 MP wird entsprechend angehoben; Wert konfigurierbar)
- [ ] Bilder über 250 MP werden nicht verarbeitet: `extraction_failed=true` und ein eindeutiger Log-Eintrag mit der Pixelzahl (z.B. „image too large: 312 MP")
- [ ] Beispiel: 16320×12240 (≈199,7 MP, 200-MP-Modus Oppo Find X9 Ultra) → wird normal beschrieben

### Backfill (`alice-dms-image-description-backfill`)

- [ ] Der Backfill übergibt pro Bild nur noch den aufgelösten Dateipfad an die zentrale Beschreibungs-Funktion und erhält Beschreibungstext oder Fehler zurück
- [ ] Der Backfill liest Bilddateien **nicht** mehr selbst ein und ruft das LLM **nicht** mehr selbst auf
- [ ] Erfolg: PATCH nach Weaviate wie bisher (`ai_description`, `extraction_failed=false`), Zählung `updated`
- [ ] Fehler: Bild bleibt `extraction_failed=true`, Zählung `still_failed`
- [ ] EXIF/GPS werden durch den Backfill nicht neu extrahiert
- [ ] Zeitfenster, Redis-Lock, Auto-Fortsetzung und Summary aus PROJ-96 bleiben funktional unverändert
- [ ] Das 52,8-MB-Panorama (22704×1760), das bisher HTTP 413 auslöste, wird vom Backfill erfolgreich beschrieben, ohne dass n8n abstürzt (PROJ-96 BUG-5 behoben)

## Edge Cases

- **Grenzfall exakt 2:1 bzw. 1:2** (z.B. 4000×2000): gilt als Standard-Format → Einzelbild.
- **Knapp darüber** (z.B. 4100×2000, 2,05:1): Teilbild-Zerlegung — ergibt 2 Teilbilder mit Überlappung.
- **Extremes Panorama** (z.B. 40000×1000, 40:1): 8 Teilbilder, jeweils deutlich breiter als 2:1; das Ergebnis darf qualitativ schlechter sein, aber es entsteht eine Beschreibung und kein Fehler.
- **Sehr kleines, aber extremes Bild** (z.B. 800×100, Banner/Grafik): wird ebenfalls zerlegt; Teilbilder werden nicht hochskaliert.
- **Bild über 250 MP**: abgelehnt mit `extraction_failed=true` + Log; der Backfill zählt es bei jedem Lauf erneut als `still_failed` (bewusst akzeptiert, sehr selten).
- **Teilbild 5 von 8 läuft in Timeout**: gesamte Beschreibung schlägt fehl, nichts wird gespeichert, Backfill versucht das ganze Bild später erneut.
- **Lange Laufzeit eines Panoramas** (bis zu 9 LLM-Aufrufe à ~30 s ≈ 4–5 min): Der Backfill-Zeit-Check greift wie bisher nur zwischen Bildern; ein begonnenes Panorama wird zu Ende verarbeitet, auch wenn das Zeitfenster dadurch um einige Minuten überschritten wird.
- **Datei zwischenzeitlich nicht mehr lesbar**: bestehendes Verhalten (Backfill: `still_failed`/`no_file`; MQTT-Pfad: `extraction_failed=true`).
- **Gleichzeitige Aufrufe** aus MQTT-Pfad und Backfill: beide nutzen dieselbe Funktion; die GPU-Reihenfolge regelt das LLM-Gateway (PROJ-111).

## Außerhalb des Scopes

- **Keine Nachbesserung bestehender Beschreibungen** im Code. Panoramen, die bisher mit 1024-px-Kante „erfolgreich" (aber unbrauchbar) beschrieben wurden, bleiben unverändert. Eine einmalige manuelle Prüfung kann im Nachhinein erfolgen; Treffer werden manuell auf `extraction_failed=true` gesetzt und dann automatisch vom Backfill neu beschrieben.
- Keine Neu-Extraktion von EXIF/GPS durch den Backfill.
- Keine Änderung an Zeitfenstern, Lock oder Selbstaufruf-Logik des Backfills (PROJ-96).
- Keine Speicherung von Bildbreite/-höhe in Weaviate.

## Technical Requirements (optional)

- Speicher: Dekodieren eines 250-MP-Bildes benötigt grob 750 MB RAM (RGB); das Container-Speicherlimit muss dafür ausgelegt sein (`/architecture`)
- Konfigurierbar: Verkleinerungskante (Default 1024 px), Pixel-Obergrenze (Default 250 MP); Schwelle 2:1, Teilbild-Verhältnis 3:2, Überlappung 10 % und max. 8 Teilbilder dürfen als Konstanten fest sein
- Offene Architekturfrage: zentrale Funktion im `dms-extractor-image` belassen (mit synchroner Schnittstelle für den Backfill) oder eigener Container

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
