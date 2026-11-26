# PROJ-125: Bilder in der Quelle der Wahrheit

**Erstellt:** 2026-11-26
**Phase:** 4.2

<!-- Der Status steht nur in features/INDEX.md. Diese Datei schreibt nur der Mensch (/write-spec, /refine). -->

## Abhängigkeiten
- Benötigt: PROJ-115 (Quelle-der-Wahrheit-Repo + Quellen-Register) — Stufen/Zustände, Arbeit übernehmen/abschließen, Abschluss „endgültig fehlgeschlagen“ (aus PROJ-117), Retry/Backoff, Quell-Markdown schreiben, Titel → Dateiname, `manual`-Schutz, Commits
- Benötigt: PROJ-116 (Datei-Erkennung) — registriert Quellen der Art `image` (`jpg`, `jpeg`, `png`, `webp`, `heic`, `tif`, `tiff`) mit Hash `sha256`, setzt Stufen bei in-place geänderten Originalen zurück
- Benötigt: PROJ-124 (Mail-Anhänge als Quelldokumente) — registriert Bild-Anhänge als Quellen `kind: image`; PROJ-125 verarbeitet sie wie jedes andere Bild
- Nutzt: `alice-llm-gateway` (PROJ-111) mit dem dort konfigurierten Vision-Modell; Beschreibungslogik inkl. Teilbild-Zerlegung aus PROJ-112 (Wiederverwendung der Logik, nicht des Containers `dms-extractor-image`)
- Liest: alte Weaviate-Collection `Image` (nur lesend, Ort je `file_hash`), solange die Übernahme eingeschaltet ist
- Ersetzt: PROJ-114 (Neu-Beschreibung aller DMS-Bilder) — der Bestand wird hier vollständig neu beschrieben
- Grundlage für: PROJ-126 (Vorschaubilder), PROJ-127 (RAG-Index, inkl. Bildsuche), PROJ-128 (Such-Tools), PROJ-129 (Wiki-Ingest)

## Überblick
PROJ-125 füllt die Quell-Markdown von Quellen der Art `image` (aus überwachten Ordnern und Mail-Anhängen):

1. **EXIF** — Aufnahmezeit, GPS-Koordinaten, Höhe, Kamera und Bildmaße, immer frisch aus dem Original gelesen.
2. **Ort** — Land, Ländercode, Stadt, Ortsteil. Übernommen aus dem alten Weaviate-Objekt mit gleichem Hash, falls dort gefüllt; sonst per Reverse-Geocoding bei Geoapify.
3. **Beschreibung** — alle Bilder (auch der Bestand von rund 52.000 Bildern) werden mit dem aktuellen Vision-Modell neu beschrieben: ausführliche deutsche Beschreibung, kurzer Titel, wörtliche Abschrift von lesbarem Text im Bild. Das verwendete Modell steht im Frontmatter.

Beschreibung und Ort werden im Register getrennt nachverfolgt und scheitern unabhängig voneinander. Neue Bilder haben Vorrang vor dem Bestand; der Bestand startet erst nach Freigabe durch den Admin (Stichprobe).

Das Feature hat keine Oberfläche. Getestet wird mit Testbildern als Originale, Wegwerf-Postgres/Redis/Weaviate, PROJ-115 mit temporärem Git-Repo, gemocktem Vision-Modell (OpenAI-kompatibler Fake) und gemocktem Geoapify.

## User Stories
- Als Haushaltsmitglied möchte ich zu jedem Foto eine lesbare Markdown mit sprechendem Titel, Beschreibung, Aufnahmezeit und Ort finden, damit ich nachvollziehen kann, was Alice über das Bild weiß.
- Als Haushaltsmitglied möchte ich, dass alle Bilder mit dem aktuellen, besseren Vision-Modell ausführlich beschrieben werden, damit ich sie später über die Suche (PROJ-127/128) zuverlässig wiederfinde.
- Als Haushaltsmitglied möchte ich, dass Text auf Fotos (Schilder, abfotografierte Briefe, Kassenzettel, Screenshots) mit erfasst wird, damit ich auch danach suchen kann.
- Als Haushaltsmitglied möchte ich, dass ein neues Foto auch während des großen Bestandsdurchlaufs zeitnah verarbeitet wird.
- Als Haushaltsmitglied möchte ich, dass die Beschreibung keine Orte oder Gebäude erfindet.
- Als Admin möchte ich die Qualität der neuen Beschreibungen an einer Stichprobe prüfen, bevor 52.000 Bilder tagelang die GPU belegen.
- Als Admin möchte ich, dass der Bestandsdurchlauf Chat und Sprache nicht spürbar ausbremst.
- Als Admin möchte ich, dass vorhandene Ortsangaben übernommen werden, damit das Geoapify-Kontingent nicht für den ganzen Bestand verbraucht wird.
- Als Admin möchte ich an jeder Bild-Markdown sehen, mit welchem Modell sie beschrieben wurde, damit ich bei einem späteren Modellwechsel gezielt neu beschreiben lassen kann.

## Fachliches Modell

### Was verarbeitet wird
- Alle aktiven (nicht `deleted`) Quellen `kind: image`, egal ob aus überwachtem Ordner oder Mail-Anhang.
- Stufen `classify` und `database` stehen bei Bildern auf `skipped` (keine Klassifizierung, keine Bild-Tabelle in PostgreSQL). `rag`, `wiki` und `thumbnail` regeln PROJ-127, PROJ-129, PROJ-126.
- Im Register gibt es für Bilder zwei getrennt nachverfolgte Schritte: **Beschreibung** (inkl. EXIF und Titel) und **Ort**. Jeder hat eigenen Zustand, Fehler und Retry nach PROJ-115. Bezeichnung und Einordnung in die Stufenliste legt `design.md` fest.

### Frontmatter-Felder (Ergänzung des Basisschemas aus PROJ-115)
| Feld | Inhalt |
|---|---|
| `taken` | Aufnahmezeit aus EXIF (leer, wenn nicht vorhanden) |
| `width`, `height` | Bildmaße in Pixeln |
| `gps` | `latitude`, `longitude`, `altitude` in Dezimalgrad bzw. Metern (leer ohne GPS) |
| `camera` | `make`, `model` (leer ohne EXIF) |
| `location` | `country`, `country_code` (ISO 3166-1 alpha-2), `city`, `district` (leer ohne GPS bzw. bis zum Geocoding) |
| `description_model` | Name des Vision-Modells, wie das Gateway ihn meldet (z. B. `qwen3.8-27b`) |

- `language` ist bei Bildern `de` (Sprache der Beschreibung).
- Verarbeitungszustände stehen wie immer nur im Register, nicht im Frontmatter.

### Inhaltsteil
- Überschrift `# <title>` (PROJ-115), darunter die **Beschreibung**.
- Abschnitt **„Text im Bild“** mit der wörtlichen Abschrift gut lesbaren Texts; fehlt lesbarer Text, entfällt der Abschnitt.
- Link aufs Original wie bei allen Quellen (PROJ-115).

### EXIF
- Wird bei jedem Beschreibungs-Durchlauf aus dem Original gelesen (alle Formate aus PROJ-116, auch HEIC und TIFF). Kein Rückgriff auf EXIF-Werte im alten Weaviate.
- Fehlende EXIF-Daten sind kein Fehler; die Felder bleiben leer.

### Ort
- Nur für Bilder mit GPS-Koordinaten; ohne GPS gilt der Schritt als `skipped`.
- **Übernahme:** Gibt es in der alten Collection `Image` ein Objekt mit gleichem `file_hash` und gefülltem Ort, werden `country`, `country_code`, `city`, `district` übernommen, ohne Geoapify-Aufruf.
- **Geoapify:** Fehlt das Objekt oder dessen Ort, wird der Ort per Reverse-Geocoding bei Geoapify ermittelt, Ortsnamen auf Deutsch.
- **Altes Weaviate nicht erreichbar:** Der Schritt gilt als vorübergehend gescheitert und wird später wiederholt, ohne Geoapify-Aufruf und ohne Fehlversuch.
- **Übernahme abschaltbar** per Konfiguration (Standard: an). Ausgeschaltet wird das alte Weaviate nicht mehr angesprochen; nötig spätestens mit PROJ-142.
- **Grenzen:** Tageslimit für Geoapify-Aufrufe konfigurierbar (Standard 3.000), höchstens 5 Aufrufe pro Sekunde. Ist das Tageslimit erreicht, wartet der Schritt bis zum nächsten Tag ohne Fehlversuch.
- Der Ort wird nach Möglichkeit vor der Beschreibung ermittelt (siehe Beschreibung, Hinweis an das Modell); die Beschreibung wartet aber nie auf den Ort.

### Beschreibung
- Ein Aufruf des Vision-Modells über `alice-llm-gateway` mit Hintergrund-Priorität und `enable_thinking=false` liefert:
  - **Beschreibung** auf Deutsch, ausführlich (etwa 800–1.500 Zeichen): Motiv, Personen (Anzahl, Tätigkeit, keine Identifizierung), Umgebung, Architektur, Licht, Stimmung, Jahreszeit.
  - **Kurztitel** auf Deutsch (wenige Wörter).
  - **Text im Bild:** wörtliche Abschrift gut lesbaren Texts, sonst leer.
- **Keine Spekulation:** Orte, Gebäude und Sehenswürdigkeiten werden nur genannt, wenn sie eindeutig erkennbar sind (z. B. durch Beschriftung im Bild) oder als Ort mitgegeben wurden; sonst neutral beschrieben.
- **Ort als Hinweis:** Liegt `location` bereits vor, bekommt das Modell Stadt/Land als Hinweis mit.
- **Format und Größe wie PROJ-112:**
  - Seitenverhältnis bis 2:1 bzw. 1:2: ein Bild, längste Seite auf 1024 px verkleinert (konfigurierbar).
  - Darüber: Zerlegung in höchstens 8 überlappende Teilbilder (ca. 3:2, ca. 10 % Überlappung, links → rechts bzw. oben → unten) plus ein Zusammenfassungs-Aufruf zu **einer** Beschreibung, **einem** Titel und **einer** zusammengeführten Abschrift.
  - Alles oder nichts: scheitert ein Teilbild oder die Zusammenfassung, scheitert die ganze Beschreibung; nie wird eine Teilbeschreibung gespeichert.
  - Bilder über 250 Megapixel (konfigurierbar) werden abgelehnt.
- `description_model` wird mit dem Modellnamen gesetzt.

### Titel
- Format: `<Zeitpunkt> <Kurztitel>[ – <Ort>]`, z. B. `2024-07-12 14.03.22 Strand bei Sonnenuntergang – Rimini`.
- `<Zeitpunkt>` = `taken` im Format `YYYY-MM-DD hh.mm.ss`, ersatzweise `modified` des Originals (wie PROJ-118).
- `<Ort>` = `city`, ersatzweise `country`; ohne Ort entfällt der Zusatz. Kommt der Ort erst nach der Beschreibung, wird der Titel dann ergänzt.
- Steht `title` in `manual`, wird er nie verändert. Dateiname folgt dem Titel (PROJ-115).

### Fehlerarten
- **Sofort `failed_permanent`:** Datei unlesbar/kaputt, Format nicht dekodierbar, über der Pixelgrenze.
- **Retry mit Backoff (PROJ-115):** Zeitüberschreitung oder Fehler des Vision-Modells, Gateway nicht erreichbar, leere oder unbrauchbare Antwort; beim Ort: Geoapify-Fehler.
- **Kein Fehlversuch, Arbeit zurück:** NAS nicht erreichbar, Original kurzzeitig nicht vorhanden (über das Löschen entscheidet PROJ-116); Ort: altes Weaviate nicht erreichbar, Tageslimit erreicht.
- Beschreibung und Ort scheitern unabhängig: Scheitert der Ort, bleiben Beschreibung und EXIF geschrieben und erledigt; scheitert die Beschreibung, wird der Ort trotzdem geschrieben.

### Reihenfolge, Last und Bestand
- Höchstens ein Bild gleichzeitig in Beschreibung (konfigurierbar).
- **Bestand** = alle Bilder, die vor dem ersten Start der Stufe registriert waren; **neu** = alle danach registrierten (Tagesscan, Mail-Anhänge).
- Neue Bilder werden vor dem Bestand bearbeitet (Beschreibung und Ort).
- **Freigabe des Bestands:** Die Beschreibung des Bestands ist per Konfiguration gesperrt (Standard: gesperrt). Neue Bilder und der Ort laufen unabhängig davon. Nach Freigabe läuft der Bestand rund um die Uhr ohne Zeitfenster.
- Einzelne Bilder lassen sich über eine interne Schnittstelle gezielt zur Beschreibung anstoßen, auch bei gesperrtem Bestand (Stichprobe, Fehlersuche).

### Änderungen, Handkorrekturen, Neuaufbau
- Handkorrekturen nach PROJ-115: Felder in `manual` und ein von Hand geänderter Inhaltsteil werden nie überschrieben.
- In-place geändertes Original (PROJ-116 setzt Stufen zurück): EXIF, Beschreibung und Ort laufen neu; die Ortsübernahme greift nur, wenn der neue Hash im alten Weaviate vorkommt.
- Neuaufbau (PROJ-120) mit Art `image`: Bilder werden neu beschrieben und verortet, `manual` bleibt geschützt.
- `deleted`-Quellen werden nicht übernommen (PROJ-116). Da PROJ-125 keine abgeleiteten Daten außerhalb der Quell-Markdown erzeugt, ist bei `deleted` nichts weiter zu tun.

### Parallelbetrieb
- Das alte System (`dms-extractor-image`, Geocoding im `alice-dms-processor`, Backfills, Weaviate `Image`) bleibt unverändert. PROJ-125 liest Weaviate nur, abonniert keine alten MQTT-Topics und schreibt nicht in alte Redis-Schlüssel.
- Alter und neuer Dienst teilen sich das Geoapify-Kontingent; die Tageslimits beider stellt der Mensch so ein, dass ihre Summe in den Tarif passt.

## Außerhalb des Umfangs
- Vorschaubilder für Bilder (PROJ-126)
- RAG-Index und Bildsuche (PROJ-127), Such-Tools (PROJ-128), Wiki (PROJ-129)
- Bild-Tabelle in PostgreSQL; Klassifizierung von Bildern
- Separate OCR für Bilder (Text kommt aus dem Vision-Aufruf); Umwandlung von Bildern in `kind: document`
- Mail-Kontext (Betreff, Absender) im Prompt für Bild-Anhänge
- Gesichtserkennung oder Identifizierung von Personen
- Übernahme alter Beschreibungen oder alter EXIF-Werte aus Weaviate
- Lokaler Geocoder
- Zeitfenster für den Bestandsdurchlauf
- Automatische Neubeschreibung bei Modellwechsel (manuell über Neuaufbau PROJ-120)
- Audio/Video
- Abschaltung des alten Bildpfads und der alten Collection (PROJ-142)
- Oberfläche (Fortschritt sichtbar über PROJ-122)

## Akzeptanzkriterien

### Ablauf und Umfang
- [ ] AK-1: Angenommen ein neu registriertes JPEG mit EXIF (Aufnahmezeit, GPS, Kamera), wenn die Stufe läuft, dann enthält seine Quell-Markdown `taken`, `width`, `height`, `gps`, `camera`, `location`, `description_model`, `language: de`, eine Beschreibung und den Titel; Beschreibung und Ort sind im Register erledigt, und es gibt Commits des Pipeline-Autors.
- [ ] AK-2: Angenommen Testbilder in allen Formaten `jpg`, `jpeg`, `png`, `webp`, `heic`, `tif`, `tiff`, wenn die Stufe läuft, dann werden alle beschrieben und ihre vorhandenen EXIF-Daten gelesen.
- [ ] AK-3: Angenommen ein Bild-Anhang aus PROJ-124 (Quelle mit `parents`), wenn die Stufe läuft, dann wird er wie jedes andere Bild verarbeitet.
- [ ] AK-4: Angenommen Quellen der Arten `document`, `email`, `audio`, `video`, wenn der Dienst läuft, dann übernimmt er sie nicht und verändert ihre Quell-Markdown nicht.
- [ ] AK-5: Angenommen eine Quelle `kind: image`, wenn sie registriert ist, dann stehen `classify` und `database` auf `skipped`.
- [ ] AK-6: Angenommen eine `deleted`-Bild-Quelle mit offener Beschreibung, wenn der Dienst Arbeit anfordert, dann bekommt er sie nicht.

### EXIF
- [ ] AK-7: Angenommen ein Bild ohne EXIF (z. B. PNG-Screenshot), wenn es verarbeitet wird, dann sind `taken`, `gps`, `camera` leer, `width`/`height` gesetzt, die Beschreibung ist erledigt, und der Ort steht auf `skipped`.
- [ ] AK-8: Angenommen ein Bild mit GPS in Grad/Minuten/Sekunden mit Süd-/West-Referenz, wenn EXIF gelesen wird, dann stehen in `gps` die korrekten vorzeichenbehafteten Dezimalgrad.
- [ ] AK-9: Angenommen ein altes Weaviate-Objekt mit gleichem Hash und abweichenden EXIF-Werten, wenn das Bild verarbeitet wird, dann stehen im Frontmatter die Werte aus dem Original.

### Ort
- [ ] AK-10: Angenommen ein Bild mit GPS und ein altes `Image`-Objekt mit gleichem `file_hash` und gefülltem Ort, wenn der Ort ermittelt wird, dann stehen `country`, `country_code`, `city`, `district` aus dem Altobjekt in `location`, und Geoapify wird nicht aufgerufen.
- [ ] AK-11: Angenommen ein Bild mit GPS ohne Altobjekt (oder Altobjekt ohne Ort), wenn der Ort ermittelt wird, dann wird Geoapify mit deutscher Sprache aufgerufen und das Ergebnis in `location` geschrieben.
- [ ] AK-12: Angenommen das alte Weaviate ist nicht erreichbar, wenn der Ort eines Bildes ermittelt werden soll, dann wird Geoapify nicht aufgerufen, der Ort bleibt offen ohne Fehlversuch, und nach Rückkehr von Weaviate wird er übernommen bzw. ermittelt.
- [ ] AK-13: Angenommen die Übernahme ist per Konfiguration abgeschaltet, wenn der Ort ermittelt wird, dann wird Weaviate nicht angesprochen und Geoapify direkt gefragt.
- [ ] AK-14: Angenommen ein Tageslimit von 3 und 5 Bilder mit GPS ohne Altobjekt, wenn der Ort ermittelt wird, dann werden am selben Tag genau 3 Geoapify-Aufrufe gemacht, die übrigen 2 bleiben ohne Fehlversuch offen und werden am Folgetag bearbeitet.
- [ ] AK-15: Angenommen viele offene Orte, wenn Geoapify aufgerufen wird, dann liegen nie mehr als 5 Aufrufe in einer Sekunde.
- [ ] AK-16: Angenommen Geoapify antwortet mit Fehler, wenn der Ort ermittelt wird, dann bekommt der Schritt Ort einen Fehlversuch mit Backoff, und Beschreibung, EXIF und Titel bleiben unverändert erledigt; das Vision-Modell wird nicht erneut aufgerufen.
- [ ] AK-17: Angenommen die Beschreibung eines Bildes mit GPS scheitert, wenn der Ort verfügbar ist, dann wird `location` trotzdem geschrieben.

### Beschreibung
- [ ] AK-18: Angenommen ein Bild, wenn es beschrieben wird, dann geht genau ein Aufruf an das Gateway mit Hintergrund-Priorität und `enable_thinking=false`, und der Prompt verlangt deutsche Beschreibung, Kurztitel, Abschrift von lesbarem Text und verbietet spekulative Orts-/Gebäudenamen.
- [ ] AK-19: Angenommen ein Bild, dessen Ort bereits vorliegt, wenn es beschrieben wird, dann enthält der Prompt Stadt und Land als Hinweis; liegt kein Ort vor, wird ohne Hinweis beschrieben, ohne zu warten.
- [ ] AK-20: Angenommen das (gemockte) Modell liefert Text im Bild, wenn die Markdown geschrieben wird, dann enthält der Inhaltsteil den Abschnitt „Text im Bild“ mit der Abschrift; liefert es keinen, fehlt der Abschnitt.
- [ ] AK-21: Angenommen das Gateway meldet das Modell `qwen3.8-27b`, wenn ein Bild beschrieben wird, dann steht `description_model: qwen3.8-27b` im Frontmatter.
- [ ] AK-22: Angenommen Bilder 6000×4000, 4000×6000 und 4000×2000, wenn sie beschrieben werden, dann je genau ein Vision-Aufruf mit längster Seite ≤ 1024 px.
- [ ] AK-23: Angenommen ein Panorama 22704×1760 bzw. 1760×22704, wenn es beschrieben wird, dann gehen 8 Teilbilder (≤ 1024 px, Reihenfolge links → rechts bzw. oben → unten) und ein Zusammenfassungs-Aufruf an das Gateway, und die Markdown enthält eine Beschreibung, einen Titel und eine Abschrift.
- [ ] AK-24: Angenommen ein Panorama, bei dem ein Teilbild-Aufruf scheitert, wenn es beschrieben wird, dann wird keine Beschreibung geschrieben, und der Schritt Beschreibung bekommt einen Fehlversuch mit Backoff.
- [ ] AK-25: Angenommen ein Bild über 250 Megapixel bzw. eine kaputte Bilddatei, wenn es beschrieben wird, dann steht die Beschreibung sofort auf `failed_permanent` mit lesbarem Grund, ohne Vision-Aufruf.
- [ ] AK-26: Angenommen das Vision-Modell antwortet leer, mit Timeout oder das Gateway ist nicht erreichbar, wenn ein Bild beschrieben wird, dann bekommt die Beschreibung einen Fehlversuch mit Backoff, und die Markdown bleibt unverändert.

### Titel
- [ ] AK-27: Angenommen ein Bild mit `taken` 2024-07-12 14:03:22, Kurztitel „Strand bei Sonnenuntergang“ und `city` Rimini, wenn es fertig verarbeitet ist, dann ist `title` = `2024-07-12 14.03.22 Strand bei Sonnenuntergang – Rimini`, und die Markdown ist entsprechend umbenannt.
- [ ] AK-28: Angenommen ein Bild ohne `taken` und ohne Ort, wenn es beschrieben wird, dann beginnt der Titel mit `modified` des Originals und hat keinen Ortszusatz.
- [ ] AK-29: Angenommen der Ort kommt erst nach der Beschreibung, wenn er geschrieben wird, dann wird der Titel um den Ort ergänzt.
- [ ] AK-30: Angenommen `title` steht in `manual`, wenn Beschreibung oder Ort geschrieben werden, dann bleibt `title` unverändert.

### Reihenfolge, Last und Bestand
- [ ] AK-31: Angenommen der Bestand ist gesperrt, wenn Bestandsbilder und neue Bilder offen sind, dann werden nur die neuen Bilder beschrieben; der Ort wird für beide ermittelt.
- [ ] AK-32: Angenommen der Bestand ist freigegeben und hat offene Bilder, wenn ein neues Bild registriert wird, dann wird es vor den übrigen Bestandsbildern beschrieben.
- [ ] AK-33: Angenommen der Bestand ist gesperrt, wenn ein Bestandsbild über die interne Schnittstelle angestoßen wird, dann wird genau dieses Bild beschrieben.
- [ ] AK-34: Angenommen Parallelität 1 und viele offene Bilder, wenn die Stufe läuft, dann ist nie mehr als ein Bild gleichzeitig in Beschreibung.

### Änderungen und Handkorrekturen
- [ ] AK-35: Angenommen eine Bild-Markdown, deren Inhaltsteil in `manual` steht, wenn die Beschreibung erneut läuft (z. B. Neuaufbau), dann bleibt der Inhaltsteil unverändert; nicht-manuelle Felder dürfen aktualisiert werden.
- [ ] AK-36: Angenommen ein in-place geändertes Bild (PROJ-116 setzt die Stufen zurück), wenn die Stufe läuft, dann werden EXIF, Beschreibung und Ort neu ermittelt.

### Betrieb
- [ ] AK-37: Angenommen das Quellen-Register ist nicht erreichbar, wenn der Dienst Arbeit holen will, dann pausiert er mit Warnung im Log, der Healthcheck meldet „unhealthy“ mit Grund, und nach Rückkehr läuft er selbstständig weiter.
- [ ] AK-38: Angenommen der NAS-Pfad eines Originals ist nicht lesbar, wenn ein Bild verarbeitet werden soll, dann geht die Arbeit ohne Fehlversuch zurück.
- [ ] AK-39: Angenommen der Dienst, wenn man ihn von außerhalb des Docker-Netzes (über nginx) aufrufen will, dann ist er nicht erreichbar.
- [ ] AK-40: Angenommen das alte System läuft, wenn der neue Dienst läuft, dann verarbeitet `dms-extractor-image` seine MQTT-/Redis-Aufträge unverändert; der neue Dienst abonniert keine alten Topics, schreibt nicht in alte Redis-Schlüssel und nicht in Weaviate.

### Live-Tests nach Deploy
- [ ] AK-41 (Live-Test nach Deploy): Angenommen der Bestand ist gesperrt, wenn der Admin 30–50 ausgewählte Bestandsbilder (Landschaft, Gebäude/Sehenswürdigkeit, Personen, Panorama, Screenshot, abfotografierter Brief) anstößt, dann sind die Beschreibungen ausführlich, ohne erfundene Orts-/Gebäudenamen, Texte sind abgeschrieben, Titel und Ort plausibel; erst danach gibt der Admin den Bestand frei.
- [ ] AK-42 (Live-Test nach Deploy): Angenommen der Bestand läuft, wenn ein Haushaltsmitglied chattet und spricht, dann bleibt die Antwortzeit spürbar unverändert, und ein neu abgelegtes Foto ist innerhalb von 15 Minuten beschrieben.
- [ ] AK-43 (Live-Test nach Deploy): Angenommen der erste Tag Bestandsdurchlauf, wenn der Admin nachsieht, dann haben die meisten Bilder mit GPS ihren Ort aus dem alten Weaviate, und die Geoapify-Aufrufe liegen unter dem Tageslimit.

## Edge Cases
- EC-1: HEIC mit EXIF in anderem Container als JPEG → EXIF wird trotzdem gelesen (AK-2).
- EC-2: EXIF-Aufnahmezeit offensichtlich falsch (z. B. 1970 oder Zukunft) → wird übernommen wie gelesen; die Korrektur erfolgt von Hand (`manual`).
- EC-3: GPS-Koordinaten 0/0 oder ungültig → gelten als „kein GPS“, Ort `skipped`.
- EC-4: Geoapify liefert für Koordinaten auf dem Meer kein Land/keine Stadt → `location` bleibt teilweise leer, Schritt erledigt, kein Retry.
- EC-5: Altobjekt in Weaviate hat nur `country` ohne `city` → gilt als gefüllt, wird übernommen; kein Geoapify-Aufruf.
- EC-6: Mehrere Altobjekte mit gleichem `file_hash` → das erste mit gefülltem Ort wird genommen.
- EC-7: Modell liefert Beschreibung ohne Titel oder unparsbare Antwort → unbrauchbare Antwort, Fehlversuch mit Backoff; nichts wird geschrieben.
- EC-8: Abschrift enthält Zeichen, die YAML/Markdown stören (`---`, Backticks) → Inhaltsteil bleibt gültig, Frontmatter wird nicht zerstört.
- EC-9: Animiertes WebP/mehrseitiges TIFF → das erste Bild/die erste Seite wird beschrieben.
- EC-10: Bild mit EXIF-Orientierung (gedreht) → wird für die Beschreibung richtig ausgerichtet; `width`/`height` sind die angezeigten Maße.
- EC-11: Gleiches Bild an mehreren Fundorten bzw. in mehreren Mails → wird einmal verarbeitet (PROJ-115).
- EC-12: Modellwechsel im Gateway während des Bestandsdurchlaufs → folgende Bilder tragen den neuen Namen in `description_model`; bereits beschriebene bleiben, wie sie sind.
- EC-13: Handkorrektur und Beschreibung kurz nacheinander → Handkorrektur zuerst committet, Beschreibung respektiert `manual` (PROJ-115).
- EC-14: Restart von Redis oder des Dienstes → keine Auswirkung, Arbeit kommt aus dem Register; hängende Arbeit fällt nach Zeitüberschreitung zurück (PROJ-115).
- EC-15: Mitternacht während das Tageslimit erreicht ist → am neuen Tag läuft das Geocoding selbstständig weiter.

## Technische Anforderungen
- Testbar ohne NAS, GPU und Internet: Testbilder (mit/ohne EXIF, alle Formate, Panorama, gedreht), Wegwerf-Postgres/Redis/Weaviate (alte Collection `Image` mit Testobjekten), PROJ-115 mit temporärem Git-Repo, Vision-Modell als OpenAI-kompatibler Fake, Geoapify als HTTP-Mock.
- Neuer Dienst oder Erweiterung eines bestehenden ETL-Dienstes (entscheidet `design.md`); `dms-extractor-image` bleibt unverändert (Wiederverwendung der Logik aus PROJ-112, nicht des Containers).
- Alle LLM-Aufrufe über `alice-llm-gateway` mit eigenem Gateway-Key, Hintergrund-Priorität, `enable_thinking=false`.
- Konfigurierbar: Parallelität (Standard 1), Freigabe des Bestands (Standard gesperrt), Ortsübernahme aus Weaviate (Standard an), Geoapify-Tageslimit (Standard 3.000) und Rate (Standard 5/s), längste Seite (Standard 1024 px), Pixelgrenze (Standard 250 MP), Zeitgrenze je Vision-Aufruf. Neue Variablen nur als Platzhalter in `.env.example`.
- Zugriff auf Originale über `nas-volumes.yml` (NAS-Konto, kein root, nur lesend; auch das Mail-Archiv für Anhänge). Schreiben der Quell-Markdowns ausschließlich über PROJ-115.
- Schnittstelle nur intern im Docker-Netz, keine nginx-Route.
- Keine neue Queue-/Event-Infrastruktur.
- Geoapify-API-Key nur als Platzhalter; keine echten Koordinaten, Pfade, Hostnamen oder personenbezogenen Daten in Code oder Testdaten.

## Offene Fragen
- Keine

## Product Decisions
- Reverse-Geocoding über Geoapify statt lokalem Geocoder: lokaler Geocoder wurde ausprobiert und verworfen; „local-first, nicht local-only“ (2026-11-26)
- Vollständige Neubeschreibung des Bestands statt Übernahme der alten Beschreibungen: das aktuelle Vision-Modell liefert deutlich bessere Ergebnisse; ersetzt PROJ-114; ändert die PRD-Entscheidung „vorhandene Beschreibungen übernehmen“ (2026-11-26)
- `description_model` mit dem Modellnamen statt einer Herkunftsangabe: zeigt bei künftigen Modellwechseln, welche Bilder neu beschrieben werden sollten (2026-11-26)
- EXIF immer aus dem Original, nur der Ort aus dem alten Weaviate: EXIF zu lesen ist lokal und billig, Übernahme bräuchte einen zweiten Pfad und Konfliktregeln; teuer ist nur der Geoapify-Aufruf (2026-11-26)
- Beschreibung und Ort scheitern unabhängig: ein Geoapify-Ausfall darf keine teuren Vision-Aufrufe wiederholen oder blockieren (2026-11-26)
- Sprechender Titel `<Zeitpunkt> <Kurztitel> – <Ort>` aus demselben Vision-Aufruf: Repo voller `IMG_…`-Namen ist für Menschen unlesbar; Format analog PROJ-118 (2026-11-26)
- Text im Bild wird vom Vision-Modell abgeschrieben, keine separate OCR, Bild bleibt `image`: die meisten Fotos haben keinen Text, eine OCR für alle wäre teuer (2026-11-26)
- Keine Bild-Tabelle, `classify`/`database` = `skipped`: Filter nach Zeit und Ort deckt der RAG-Index mit Metadaten ab (2026-11-26)
- Parallelität 1, Hintergrund-Priorität, neue Bilder vor dem Bestand, kein Nachtfenster: Chat bleibt bedienbar, neue Fotos erfüllen das 15-Minuten-Ziel, der Bestand ist trotzdem in einigen Tagen durch (2026-11-26)
- Beschreibungsverhalten aus PROJ-112 (Teilbilder, alles oder nichts, 250 MP) und Fehlerregeln aus PROJ-117 übernommen (2026-11-26)
- Altes Weaviate nicht erreichbar → Ort warten statt Geoapify; Übernahme abschaltbar für PROJ-142: spart Kontingent, macht die Abhängigkeit vom alten System auflösbar (2026-11-26)
- Geoapify: Tageslimit 3.000, 5/s, Limit erreicht = warten ohne Fehlversuch, deutsche Ortsnamen; Grenzen wie im alten Prozess (2026-11-26)
- Ausführliche Beschreibung (~800–1.500 Zeichen), Verbot spekulativer Orts-/Gebäudenamen, Ort als Hinweis im Prompt, Bestand erst nach abgenommener Stichprobe von 30–50 Bildern: Erkenntnisse aus PROJ-114 (erfundenes „Edogawa-Tor der Edo-Burg“), ~52.000 Bilder ≈ 107 h GPU-Zeit sollen nur einmal laufen (2026-11-26)
- Kein Mail-Kontext im Prompt für Bild-Anhänge: Bildinhalt soll für sich beschrieben werden; bei Bedarf später (2026-11-26)
