# PROJ-75: Bildersuche und Bilddarstellung

## Status: Planned
**Created:** 2026-08-04
**Last Updated:** 2026-08-04

## Kontext & Motivation

PROJ-56 hat die Bildanalyse-Pipeline implementiert: Bilder werden automatisch erkannt, mit EXIF-Metadaten (Datum, GPS, Kamera) angereichert, per Ollama Vision mit einer KI-Bildbeschreibung versehen und per Geoapify reverse-geocodiert (`country`, `country_code`, `city`, `district`). Das Ergebnis landet in der Weaviate-Collection "Image" — aber es gibt noch keine Suchanfrage darauf. Diese Spec ergänzt die fehlende Suchfunktion sowie die zugehörige Kachel-Darstellung der Treffer.

Die Suchlogik übernimmt bewusst das in PROJ-73 etablierte Muster (Recency- vs. Relevanz-Sortierung, wörtliche Übernahme von Suchbegriffen, Standardanzahl) statt eine Parallelwelt für Bilder zu bauen. Im Rahmen der Interviews zu dieser Spec wurde zusätzlich eine Lücke in PROJ-73 identifiziert: Ein explizites „alle zeigen"-Verhalten (z. B. „zeige mir alle Rechnungen") führte bisher dazu, dass das LLM unaufgefordert und ohne Rückfrage die volle (potenziell sehr große) Trefferliste zurückgibt. Diese Spec führt eine Rückfrage-Pflicht für „alle"-Wünsche ein — einheitlich für `search_documents`, `search_emails` **und** das neue Bilder-Suchwerkzeug.

## Dependencies

- Requires: PROJ-56 (DMS Bildanalyse) — liefert die Weaviate-Collection "Image" (`ai_description`, EXIF-Felder, Geocoding-Felder `city`/`country`/`district`)
- Requires: PROJ-55 (DMS Thumbnail-Generierung) — liefert Thumbnails für die Kachel-Vorderseite
- Requires: PROJ-54 (Vision-Chat: Flip-Card Ergebnisansicht) — die Kachel-/Flip-Card-Infrastruktur wird für Bilder wiederverwendet, nicht neu gebaut
- Related: PROJ-73 (Weaviate-Suchkriterien-Qualität) — das dort etablierte `sort_mode`/Literal-Begriffs-Muster wird für Bilder übernommen; diese Spec erweitert zusätzlich die PROJ-73-Tools um die neue „Alle"-Rückfrage-Regel (siehe Acceptance Criteria)

## User Stories

- Als Andreas möchte ich mit „Zeige mir Bilder aus Tokyo" die neuesten Bilder aus Tokyo als Kachel-Raster sehen (Standardanzahl, Datum absteigend), damit ich schnell einen visuellen Überblick über meine Reisefotos bekomme, ohne die Ordnerstruktur zu kennen.
- Als Andreas möchte ich, wenn ich „alle Bilder aus Tokyo" sehen will, zunächst gefragt werden, ob wirklich alle (potenziell sehr vielen) Treffer gezeigt werden sollen, damit ich nicht versehentlich ein überfülltes Kachel-Raster bekomme.
- Als Andreas möchte ich mit „Zeige mir Bilder mit einem Sonnenuntergang" eine inhaltlich passende Auswahl in Standardanzahl sehen, damit ich Motive finden kann, ohne mich an Ort oder Zeitpunkt erinnern zu müssen.
- Als Andreas möchte ich mit „Zeige mir die letzten Bilder" die zuletzt aufgenommenen Bilder in Standardanzahl sehen, damit ich einen schnellen Überblick über neue Fotos bekomme.
- Als Andreas möchte ich mit „Zeige mir die letzten 10 Bilder mit einer Wiese" genau 10 zum Motiv passende, nach Datum sortierte Bilder bekommen, damit ich eine exakt dosierte Auswahl erhalte.
- Als Andreas möchte ich mit einer kombinierten Anfrage wie „Zeige mir die letzten Bilder aus Hiroshima mit Kirschblüten" gleichzeitig nach Ort, Motiv und Aktualität filtern können, ohne mehrere Anfragen stellen zu müssen.
- Als Andreas möchte ich, dass Bilderergebnisse immer als Kachel-Raster erscheinen — auch ohne „zeige mir" (z. B. „Welche Aufnahmen aus China stammen aus Januar 2026?") — damit ich Bilder nie als Fließtext-Liste bekomme.
- Als Andreas möchte ich die Standardanzahl der angezeigten Bilder in den Einstellungen selbst festlegen können, damit das Kachel-Raster für mich passend gefüllt ist.
- Als Nutzer mit eingeschränkten Rechten (Partner/Gast) möchte ich nur die Bilder sehen, für die mir explizit Leserecht eingeräumt wurde, damit private Fotos nicht ungewollt sichtbar werden.

## Acceptance Criteria

### Ortssuche

- [ ] Ein Ortsbegriff in der Anfrage (z. B. „Tokyo", „Japan") wird gegen die strukturierten Geocoding-Felder `city`, `country`, `district` (PROJ-56) gematcht — nicht gegen `ai_description`.
- [ ] Matching ist fallunabhängig und toleriert abweichende Schreibweisen als Teilstring-Match (z. B. „Tokyo" matcht gespeichertes „Tokio"); exaktes Fuzzy-/Transliterations-Matching ist technische Detailfrage für `/architecture`.
- [ ] Ein Ortsbegriff matcht, sobald er in mindestens einem der drei Felder vorkommt (z. B. „Japan" über `country`, „Tokyo" über `city`).
- [ ] Bilder ohne Geocoding-Daten (kein GPS im EXIF oder Geocoding noch ausstehend) erscheinen nie in Ortssuchergebnissen — kein Fehler, sie werden schlicht nicht gefunden.

### Inhaltliche Suche

- [ ] Ein inhaltliches Suchkriterium (z. B. „Sonnenuntergang", „Wiese", „Kirschblüten") wird unverändert (nicht paraphrasiert) gegen `ai_description` gesucht — analog zur bestehenden Regel für `search_documents`/`search_emails` (PROJ-73).
- [ ] Ortsfilter und Inhaltskriterium können kombiniert in einer Anfrage auftreten (z. B. „Sonnenuntergangsbilder aus Tokyo") — beide Kriterien müssen erfüllt sein (UND-Verknüpfung).

### Anzahl & „Alle"-Verhalten

- [ ] Nennt der Nutzer eine explizite Anzahl („die letzten 10 Bilder …"), werden genau diese N Treffer geliefert.
- [ ] Nennt der Nutzer keine Anzahl und kein „Alle"-Signal, wird die für ihn konfigurierte Standardanzahl verwendet (System-Default: 5, individuell in den Einstellungen änderbar, siehe unten).
- [ ] Äußert der Nutzer einen expliziten „alle zeigen"-Wunsch (z. B. „alle Bilder aus Tokyo", „sämtliche Fotos mit …"), fragt Alice zunächst nach, ob wirklich alle (potenziell vielen) Treffer gezeigt werden sollen, bevor die Suche mit unbegrenzter Anzahl ausgeführt wird.
- [ ] Bestätigt der Nutzer den „Alle"-Wunsch, werden alle passenden Treffer bis zur technischen Obergrenze (100) geliefert, nach Datum absteigend sortiert; werden mehr als 100 Treffer gefunden, weist Alice im Text explizit darauf hin, dass weitere, nicht angezeigte Treffer existieren.
- [ ] Lehnt der Nutzer den „Alle"-Wunsch nach der Rückfrage ab oder nennt stattdessen eine Zahl, wird diese Zahl bzw. die Standardanzahl verwendet.
- [ ] Jede neue „Alle"-Anfrage löst erneut die Rückfrage aus — keine sitzungsweite Persistenz einer früheren Zustimmung.
- [ ] Diese Rückfrage-Regel gilt gleichermaßen für `search_documents` und `search_emails` (Nachzug zu PROJ-73) — kein Doppelstandard zwischen Bildern und Dokumenten.

### Sortierung

- [ ] Anfragen mit Recency-Signal („die letzten …", „neueste …") liefern Treffer nach Aufnahmedatum absteigend sortiert.
- [ ] Anfragen ohne Inhaltskriterium und ohne Recency-Signal (z. B. reiner Ortsfilter „Bilder aus Tokyo") werden ebenfalls automatisch nach Datum absteigend sortiert (kein Relevanz-Score ohne Inhaltskriterium) — analog zur bestehenden PROJ-73-Regel für Dokumente/Mails.
- [ ] Anfragen mit reinem Inhaltskriterium ohne Recency-Signal (z. B. „Bilder mit Sonnenuntergang") liefern die relevantesten Treffer per Hybrid-/Vektorsuche gegen `ai_description` — unverändertes Verhalten wie bei Dokumenten.
- [ ] Bilder ohne Aufnahmedatum (`exif_datetime` fehlt) werden bei datumssortierten Anfragen nicht stillschweigend ausgeschlossen, sondern ans Ende der Ergebnisliste einsortiert (analog zur PROJ-73-Lösung für Dokumente ohne Datum).

### Kachel-Anzeige

- [ ] Bildersuchergebnisse werden immer als Kachel-Raster angezeigt (Wiederverwendung der Flip-Card-Komponente aus PROJ-54) — unabhängig davon, ob die Anfrage einen visuellen Intent-Marker wie „zeige mir" enthält.
- [ ] Front der Kachel: quadratisches Thumbnail (zentrierter Zuschnitt, PROJ-55), darunter Datum und Ort (falls vorhanden) als Metadatenzeile.
- [ ] Back der Kachel: EXIF-Felder (Kameramodell, GPS-Koordinaten, Ort/Land) aus der Weaviate „Image"-Collection.
- [ ] ∑-Icon zeigt die KI-generierte Bildbeschreibung (`ai_description`) als Summary-Ansicht.
- [ ] 0 Treffer: Kachel-Raster öffnet sich mit Leerzustand („Keine Bilder gefunden"), analog zum bestehenden PROJ-54-Verhalten.

### Berechtigungen

- [ ] Bildersuche respektiert eine granulare Leseberechtigung pro Nutzer, analog zu den übrigen DMS-Dokumenttypen (`alice.permissions_dms`).
- [ ] Nutzer ohne Leserecht auf Bilder erhalten bei einer Bildersuche keine Treffer und keine Fehlermeldung, die auf die Existenz von Bildern hindeutet — konsistent mit dem bestehenden Sicherheitsverhalten anderer Dokumenttypen.
- [ ] Rollen mit bestehender Wildcard-Berechtigung (admin: alles erlaubt; guest/child: alles verboten) sind automatisch abgedeckt, sobald der neue Dokumenttyp „Image" im System existiert.
- [ ] Die Rolle „user" (Standard-Vorlage) erhält einen expliziten Berechtigungs-Eintrag für „Image" mit Leserecht, analog zu „Document"/„Invoice" — persönliche Fotos gelten nicht als sensibel wie Bank-/Finanzdaten.
- [ ] Das neue Suchwerkzeug wird in der `tools_allowed`-Liste der Rollen-Vorlage „user" ergänzt, sonst ist es trotz DMS-Leserecht für Standardnutzer faktisch nicht aufrufbar.

### Standardanzahl-Einstellung

- [ ] Die Standardanzahl für Bildersuchergebnisse ist eine nutzerspezifische Einstellung (System-Default: 5), änderbar über die Settings-UI.
- [ ] Ändert der Nutzer die Einstellung, gilt der neue Wert ab der nächsten Bildersuche, wenn keine explizite Zahl genannt wird.

## Edge Cases

- Ortsbegriff ohne Treffer (z. B. ein Ort, aus dem nie fotografiert wurde) → 0 Treffer, „keine Bilder gefunden", kein Fehler.
- Ortsbegriff matcht mehrdeutig (z. B. „Georgia" als Bundesstaat vs. Land) → alle Treffer aus beiden Interpretationen werden gemeinsam zurückgegeben; ein Disambiguierungs-Dialog ist nicht Teil dieser Spec.
- Kombinierte Anfrage mit Ort + Inhalt + expliziter Zahl, aber weniger Treffer als verlangt (z. B. „die letzten 10 Sonnenuntergangsbilder aus Tokyo", aber nur 3 vorhanden) → nur die 3 tatsächlichen Treffer, keine Auffüllung mit unpassenden Bildern (analog PROJ-73).
- Nutzer bestätigt die „Alle"-Rückfrage, es gibt aber mehr als 100 Treffer → die neuesten 100 werden gezeigt, Alice weist im Text explizit auf weitere, nicht angezeigte Treffer hin.
- Duplikat-Bild unter zwei Pfaden (`additionalPaths`, PROJ-56) → erscheint nur einmal im Ergebnis-Raster (ein Weaviate-Objekt = eine Kachel).
- Anfrage nach Videos (z. B. „Zeige mir Videos aus Tokyo") → außerhalb des Scopes; PROJ-56 verarbeitet keine Videodateien, es existieren keine Video-Objekte in der Collection.
- Bild mit `extraction_failed: true` (KI-Beschreibung fehlt wegen Verarbeitungsfehler) → erscheint nicht in inhaltlichen Suchergebnissen (kein Vektor-Treffer möglich), kann aber weiterhin über Ortsfilter oder Recency gefunden werden, da EXIF-Daten unabhängig von der KI-Beschreibung erfasst wurden.
- Nutzer stellt direkt hintereinander zwei „Alle"-Anfragen zu unterschiedlichen Orten → jede löst eigenständig die Rückfrage aus (keine übergreifende Zustimmung).

## Technical Requirements (optional)

- Neues Suchwerkzeug (Name z. B. `search_images`, final in `/architecture` festzulegen) in `alice-chat-stream`/`tools.py`; Ziel-Workflow (neuer n8n-Workflow oder Erweiterung von `alice-tool-search`) ebenfalls in `/architecture` zu entscheiden — die Weaviate „Image"-Collection ist bisher an keinen Such-Workflow angebunden.
- `alice.permissions_dms`-CHECK-Constraint muss um `'Image'` erweitert werden; Rollen-Vorlage „user" benötigt einen neuen Eintrag.
- Standardanzahl-Einstellung: neues Feld (z. B. in `alice.user_profiles`), exponiert über bestehende Settings-UI.
- Wiederverwendung der bestehenden Flip-Card-/`vision_results`-SSE-Infrastruktur aus PROJ-54 — kein neuer Anzeige-Mechanismus.
- „Alle"-Rückfrage-Regel: gemeinsame Formulierung im Tool-Schema/System-Prompt für `search_documents`, `search_emails`, `search_images` — eine Textstelle statt dreifacher Logik.
- Technische Obergrenze: 100 Treffer (konsistent mit PROJ-73).

## Scope-Abgrenzung

**In Scope:**

- Neues Suchwerkzeug für die Weaviate „Image"-Collection (Ortsfilter, Inhaltskriterium, Recency, Kombinationen, Standardanzahl/explizite Zahl).
- Kachel-Anzeige der Ergebnisse über die bestehende Flip-Card-Infrastruktur (PROJ-54).
- Granulare Leseberechtigung für den neuen Dokumenttyp „Image".
- Nutzerspezifische Standardanzahl-Einstellung für Bilderergebnisse.
- „Alle"-Rückfrage-Mechanismus — eingeführt für Bilder, gleichzeitig nachgezogen für `search_documents`/`search_emails` (PROJ-73).

**Out of Scope:**

- Videosuche (keine Video-Ingestion-Pipeline vorhanden).
- Vollbild-/Lightbox-Ansicht des Originalbilds (Flip-Card-Metapher wird wiederverwendet, kein neuer Original-Bild-Endpunkt).
- Fuzzy-/Transliterations-Matching von Ortsnamen über reine Teilstring-Suche hinaus.
- Neue Filter-/Sortier-UI-Elemente (alles läuft weiterhin über Text-/Spracheingabe).
- Änderungen an EXIF-Extraktion, Geocoding oder KI-Bildbeschreibung selbst (PROJ-56 bleibt unverändert).

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
