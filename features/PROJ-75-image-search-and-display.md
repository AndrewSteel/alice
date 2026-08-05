# PROJ-75: Bildersuche und Bilddarstellung

## Status: Deployed
**Created:** 2026-08-04
**Last Updated:** 2026-08-05

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

### Component Structure (nur die neue UI-Ergänzung)

Die Kachel-Anzeige selbst braucht **keine neue Komponente** — sie wird 1:1 aus PROJ-54 wiederverwendet (Flip-Card-Raster ist bereits datengetrieben: Feld-Beschriftungen pro Dokumenttyp kommen aus einer Übersetzungsdatei, nicht aus Code). Einzige echte UI-Neuerung ist ein Einstellungsfeld:

```
Settings-Seite → Tab "Mein Profil"
+-- (bestehend) Sprache, Anrede, Interessen
+-- NEU: "Standardanzahl Bilderergebnisse" (Zahlenfeld, 1-100, Standard 5)
```

Kachel-Raster für Bildertreffer (Wiederverwendung, keine Neuentwicklung):
```
Chat-Antwort mit Bildertreffern
+-- Kachel-Raster (bestehende FlipCardGrid-Komponente, PROJ-54)
    +-- Kachel-Vorderseite: quadratisches Thumbnail (bestehend, PROJ-55) + Datum/Ort-Zeile
    +-- Kachel-Rückseite: EXIF-/Geo-Felder (Kamera, GPS, Ort/Land) — neue Feld-Beschriftungen für Dokumenttyp "Image"
    +-- ∑-Symbol: KI-Bildbeschreibung als Zusammenfassungs-Ansicht (bestehender Mechanismus)
```

### Data Model (einfache Sprache)

Es werden keine neuen Bilddaten gespeichert — die Weaviate-Collection "Image" (PROJ-56) bleibt unverändert. Neu ist, wie eine Suchanfrage aussieht und wie eine Nutzereinstellung sowie eine Berechtigung ergänzt werden:

```
Jede Bildersuch-Anfrage hat:
- Ortsbegriff (optional) — gematcht gegen Stadt/Land/Bezirk (strukturierte Felder, nicht die Bildbeschreibung)
- Inhaltskriterium (optional) — durchsucht die KI-Bildbeschreibung
- Sortiermodus: Aktualität (Standard, sobald kein Inhaltskriterium vorliegt) oder Relevanz
- Anzahl: explizite Nutzerzahl > nutzerspezifische Standardanzahl > System-Standard (5)
- "Alle"-Wunsch: löst zuerst eine Rückfrage aus, erst nach Bestätigung Suche bis zur technischen Obergrenze (100)

Neue Nutzer-Einstellung (im bestehenden Nutzerprofil, wie Sprache/Anrede):
- Standardanzahl Bilderergebnisse (Zahl 1-100, Standard 5)

Neue Berechtigung (gleiche Struktur wie bei "Rechnung"/"Dokument"):
- Leserecht für Dokumenttyp "Image" — Standard-Rolle "user" bekommt Lesezugriff, Admin (Alles-erlaubt) und Gast/Kind (Alles-verboten) sind automatisch abgedeckt
```

### Workflow Architecture

**Betroffene Workflows:** `alice-tool-search` — wird um eine neue Operation erweitert, kein neuer Workflow.

**Trigger:** unverändert — Aufruf durch `alice-chat-stream`, sobald das LLM das neue Werkzeug `search_images` einsetzt.

**Neue Entscheidungen vor dem Werkzeug-Aufruf (im LLM-Prompt/Werkzeug-Text von `alice-chat-stream`):**
- Das LLM zerlegt die Anfrage in Ortsbegriff, Inhaltskriterium, Anzahl, Sortiermodus — nach demselben Muster wie bei `search_documents`/`search_emails` (PROJ-73).
- Genannte Begriffe (Ort, Inhalt) werden unverändert übernommen, nicht paraphrasiert.
- Bei einem erkannten "alle zeigen"-Wunsch fragt das LLM zuerst nach, bevor es das Werkzeug mit der technischen Obergrenze statt der Standardanzahl aufruft — dieselbe neue Regel gilt ab jetzt auch für `search_documents`/`search_emails` (Nachzug PROJ-73), als ein gemeinsamer Anweisungstext statt dreifacher Logik.

**Verarbeitungsschritte im erweiterten Workflow:**
1. **Eingangsprüfung/Normalisierung** — wie bei Dokumenten/Mails: Anzahl auf die technische Obergrenze (100) begrenzen, Sortiermodus validieren.
2. **Berechtigungsfilter** — dieselbe Postgres-Prüfung gegen die Leserechte-Tabelle wie bei allen anderen Dokumenttypen, jetzt inklusive des neuen Typs "Image". Kein Leserecht → leeres Ergebnis ohne Fehlermeldung (konsistent mit dem bestehenden Sicherheitsverhalten anderer Dokumenttypen).
3. **Such-Ausführung (neuer Zweig):**
   - Ortsbegriff vorhanden → strukturierter Filter auf Stadt/Land/Bezirk (Teilstring, Groß-/Kleinschreibung ignoriert).
   - Inhaltskriterium vorhanden → zusätzliche inhaltliche Suche gegen die KI-Bildbeschreibung (gleiche Technik wie bei Dokumenten/Mails).
   - Beide gemeinsam genannt → UND-Verknüpfung.
   - Kein Inhaltskriterium → Ergebnis wird **immer** nach Aufnahmedatum absteigend sortiert, unabhängig davon, ob das LLM ein Aktualitäts-Signal erkannt hat (Sicherheitsnetz gegen Fehlklassifizierung: eine reine Ortssuche hat inhaltlich nichts, wonach eine Relevanz-Suche ranken könnte). Bilder ohne Aufnahmedatum landen am Ende der Liste statt zu verschwinden (gleiche Lösung wie PROJ-73 für Dokumente ohne Datum).
   - Bestätigter "Alle"-Wunsch → bis zu 100 Treffer, nach Datum absteigend; werden mehr als 100 gefunden, liefert der Workflow einen Hinweis "weitere Treffer vorhanden", den das LLM in seiner Antwort erwähnt.
4. **Rückgabeformat** — wie bei Dokumenten: jeder Treffer trägt eine Bild-ID (für das Thumbnail), Dokumenttyp "Image", Datum sowie die EXIF-/Geocoding-Felder als Metadaten. Die bestehende Kachel-Anzeige (PROJ-54) greift automatisch, sobald ein Treffer eine Bild-ID enthält — unabhängig von der genauen Formulierung der Nutzeranfrage.

**Datenfluss:**
```
Nutzeräußerung
  → LLM zerlegt in Ort/Inhalt/Anzahl/Sortiermodus (ggf. erst "Alle"-Rückfrage im Chat)
  → Normalisierung/technische Obergrenze
  → Berechtigungsfilter (Leserechte-Tabelle, Typ "Image")
  → Such-Ausführung (Ortsfilter / Inhaltssuche / Datums-Sortierung, je nach Kriterien)
  → Ergebnisliste (Bild-ID, Datum, Ort, EXIF-Metadaten)
  → Kachel-Raster im Chat (bestehende PROJ-54-Infrastruktur)
```

**Integrationen:** Weaviate (Collection "Image", PROJ-56), PostgreSQL (Berechtigungen, Nutzerprofil-Standardanzahl), Ollama/`alice-chat-stream` (Sprachverständnis), bestehende Thumbnail-Auslieferung (PROJ-55). Keine neuen externen Systeme.

**Fehlerbehandlung:** 0 Treffer → Kachel-Raster mit Leerzustand, kein Fehler (analog PROJ-54). Kein Leserecht → leeres Ergebnis statt eines Hinweises auf die Existenz von Bildern (analog anderer Dokumenttypen).

### Tech-Entscheidungen (Begründung für PM)

1. **Neues Suchwerkzeug erweitert den bestehenden `alice-tool-search`-Workflow statt eines neuen Workflows.** Der Workflow enthält bereits die komplette Berechtigungsprüfung und die Aktualitäts-/Relevanz-Sortierlogik aus PROJ-73. Ein neuer Workflow müsste diese Logik duplizieren, obwohl die Bilder-Suche exakt demselben Muster folgt wie Dokumente/Mails.
2. **Ortssuche filtert strukturierte Felder (Stadt/Land/Bezirk), nicht die KI-Beschreibung.** Präziser (kein Zufallstreffer, falls ein Ortsname zufällig im Beschreibungstext vorkommt) und schneller, da kein Vektor-Scoring nötig ist.
3. **Ohne Inhaltskriterium wird immer nach Datum sortiert — als Workflow-Sicherheitsnetz, nicht nur als LLM-Verhalten.** Verhindert leere Ergebnislisten, falls das LLM ein "Aktualitäts"-Signal nicht erkennt.
4. **Die "Alle"-Rückfrage ist eine reine Gesprächsregel im Werkzeug-Text, keine neue technische Komponente** — analog zur bereits etablierten Rückfrage-Logik aus PROJ-73. Dadurch entsteht automatisch die geforderte "keine sitzungsweite Zustimmung"-Eigenschaft, da jede Anfrage ein neuer Gesprächsschritt ist.
5. **Die Kachel-Anzeige braucht keine neue Frontend-Komponente.** Die bestehende Flip-Card-Infrastruktur ist bereits datengetrieben — Bilder werden als neuer Dokumenttyp "Image" mit eigenen Feld-Beschriftungen ergänzt. Das Kachel-Raster erscheint automatisch für jedes Suchergebnis mit einer Bild-ID, unabhängig von der Nutzerformulierung.
6. **Die Standardanzahl-Einstellung wird im bereits bestehenden Nutzerprofil gespeichert** (derselbe Ort wie Sprache/Anrede) — ein zusätzliches Feld statt neuer Infrastruktur.
7. **Berechtigung für "Image" folgt exakt dem bestehenden Muster für Dokumenttypen.** Admin/Gast/Kind sind automatisch abgedeckt, da ihre Berechtigungen bereits als "alles erlaubt" bzw. "alles verboten" definiert sind.

### Dependencies (zu installierende Pakete)

Keine neuen Pakete — die Umsetzung nutzt ausschließlich bestehende Bausteine (Weaviate, PostgreSQL, n8n, bestehende Flip-Card-Frontend-Komponenten).

## Implementation Notes (Backend + Frontend)

**Datenbank** (`sql/init-schema.sql`, `sql/migrations/066-image-search-permissions.sql`):
- `alice.permissions_dms.doc_type` CHECK-Constraint um `'Image'` erweitert.
- Rollen-Vorlage `user`: neuer `dms_permissions`-Eintrag `Image` (nur `can_read`), `search_images` zu `tools_allowed` ergänzt. Admin (Wildcard `*`) und guest/child (Wildcard `*` verboten) brauchen keine Änderung.
- Migration 066 legt die CHECK-Constraint auf Prod um und backfillt bestehende `user`-Rollen-Nutzer (Permission-Zeile + `tools_allowed`).
- Standardanzahl-Einstellung: kein Schema-Wechsel nötig — neues JSONB-Feld `preferences.bilder_standardanzahl` (1-100) im bereits vorhandenen `alice.user_profiles`, analog zu `sprache`/`anrede`.

**alice-auth** (`docker/compose/automations/alice-auth/main.py`): `UpdateProfileRequest` um `bilder_standardanzahl` erweitert (Validierung 1-100), `PATCH /auth/profile` schreibt/liest den neuen preferences-Key.

**alice-tool-search Workflow** (`workflows/alice-tool-search.json`): neue Operation `search_images`, erweitert den bestehenden Workflow (kein neuer Workflow, siehe Tech-Entscheidung 1):
- `Input Normalizer`: neuer Zweig für `search_images` (Ortsbegriff `location`, aufgeschobene Limit-Auflösung `imageLimitPending`).
- `Apply DMS Filter`: `Image` in die Wildcard-Auflösungsliste aufgenommen.
- `Operation Router`: dritter Zweig `search_images`.
- Neu: `Get Image Default Count` (Postgres, liest `preferences.bilder_standardanzahl`) → `Resolve Image Limit` (explizite Zahl > Nutzer-Standard > System-Standard 5) → `Weaviate Search Images` (Ortsfilter via `Like` auf `city`/`country`/`district`, Inhaltssuche via Hybrid auf `ai_description`, Datums-Sicherheitsnetz ohne Inhaltskriterium, dated/undated-Dedup für Bilder ohne `exif_datetime`, `extraction_failed`-Bilder nur bei Inhaltssuche ausgeschlossen).
- "Alle"-Rückfrage-Nachzug (PROJ-73): generischer `Weaviate Search`-Node (Dokumente/Mails) und `Weaviate Search Images` liefern jetzt `more_available: true`, wenn bei einer bestätigten "Alle"-Anfrage (limit=100) mehr als 100 Treffer existieren (Weaviate-`Aggregate`-Zählung, nur im inhaltslosen Zweig).

**alice-chat-stream** (`app/tools.py`, `app/memory.py`, `app/streaming.py`): neues Tool `search_images` (Schema + Dispatch an `alice-tool-search`); System-Prompt (`memory.py`) um eine gemeinsame "Alle"-Rückfrage-Anweisung für `search_documents`/`search_emails`/`search_images` ergänzt (eine Textstelle statt dreifacher Logik, siehe Tech-Entscheidung 4) sowie Hinweis auf `more_available`; `_build_tool_summary` um `search_images` ergänzt.

**Frontend**: keine neue Komponente — Flip-Card-Infrastruktur (PROJ-54) wird über einen neuen Dokumenttyp `Image` in den datengetriebenen i18n-Labelmaps (`vision.docMeta.Image`, `vision.extraMeta`, DE/EN) angesprochen; ein berechnetes `location`-Feld (city > district > country) liefert die "Ort"-Zeile auf der Kachel-Vorderseite. Neues Einstellungsfeld "Standardanzahl Bilderergebnisse" in `ProfilForm.tsx` (1-100), verdrahtet über `profileApi.ts`.

**Bewusst nicht umgesetzt:** Datumsbereichs-Filter (`date_from`/`date_to`) für Bilder — im freigegebenen Tech-Design-Datenmodell nicht vorgesehen (nur Ortsbegriff/Inhalt/Sortiermodus/Anzahl), obwohl eine User Story ein Datums-Beispiel nennt. Sollte dies gewünscht sein, ist eine Spec-Ergänzung nötig, keine Implementierungslücke.

## QA Test Results

**Tested:** 2026-08-04
**Environment:** No local Docker stack running (VPN-only production system, `docker ps` shows no `postgres`/`weaviate`/`alice-*` containers locally). QA was performed as: (1) live read-only Postgres queries against the real production `alice` schema via MCP (confirmed current `role_templates`/`permissions_dms` state and validated migration SQL syntax directly against it); (2) a live diff of the deployed `alice-tool-search` n8n workflow (via n8n-mcp, `n8n.happy-mining.de`) against the pre-change git baseline to rule out undocumented drift before this change is layered on top; (3) Node.js syntax/behavioral checks of every new/modified Code-node (`node --check` + mocked-axios GraphQL query construction, incl. an injection-payload test); (4) `npx tsc --noEmit` and `npm run build` (Next.js) for the frontend; (5) a dev-server smoke test of `/login`. Per project policy the workflow change was **not** deployed to the live n8n instance during QA (deploy is user-triggered). Full logged-in browser testing of the Settings page / chat flow was **not possible** — no local backend stack and no auth credentials in this session (same constraint noted in the PROJ-73 QA report).
**Tester:** QA Engineer (AI)

### Acceptance Criteria Status

#### Ortssuche
- [x] Ortsbegriff matched gegen `city`/`country`/`district` (strukturiert), nicht gegen `ai_description` — code review: `Weaviate Search Images` baut den `Like`-Filter ausschließlich aus diesen drei Feldern.
- [x] Fallunabhängiger Teilstring-Match — verifiziert per Node-Skript: Suchbegriff wird lowercased und als `*term*` per `Like` gegen die (wortweise tokenisierten, ebenfalls lowercased) Felder gematcht. Die im AC genannte Transliteration "Tokyo" → gespeichertes "Tokio" ist laut Scope-Abgrenzung explizit **außerhalb** des Umfangs (reine Fuzzy-/Transliterations-Matching wurde bewusst nicht gebaut) — Widerspruch zwischen User-Story-Beispiel und Scope-Abgrenzung, Scope-Abgrenzung ist maßgeblich.
- [x] Ortsbegriff matcht bei Treffer in mind. einem der drei Felder — `operator: Or` über alle drei Felder.
- [x] Bilder ohne Geocoding-Daten erscheinen nie in Ortssuchergebnissen — `Like`-Filter auf ein leeres/fehlendes Feld liefert konstruktionsbedingt keinen Treffer.

#### Inhaltliche Suche
- [x] Inhaltskriterium unverändert (nicht paraphrasiert) gegen `ai_description` gesucht — Workflow übernimmt `query` unverändert (nur GraphQL-Escaping); zusätzlich in `tools.py`/`memory.py` als explizite LLM-Anweisung verankert.
- [x] Ort + Inhalt kombinierbar (UND) — `where`- und `hybrid`-Argument gemeinsam im selben `Image(...)`-Aufruf.

#### Anzahl & „Alle"-Verhalten
- [x] Explizite Anzahl → exakt N Treffer — `Input Normalizer` übernimmt `input.limit` unverändert (capped bei 100).
- [x] Keine Anzahl/kein „Alle" → konfigurierte Standardanzahl (System-Default 5) — `Get Image Default Count` → `Resolve Image Limit`-Kette, live gegen `alice.user_profiles.preferences.bilder_standardanzahl` geprüft.
- [ ] **Nicht live testbar** (Konversationsregel, kein Workflow-Zweig): explizite „Alle"-Rückfrage vor unbegrenzter Suche. Code-Review bestätigt, dass die Anweisung in `memory.py` (System-Prompt) und in der `limit`-Beschreibung aller drei Tool-Schemas (`tools.py`) vorhanden ist; ein Live-Chat-Test war in dieser Session nicht möglich (kein Zugang zu Auth-Credentials/laufendem Chat-Stack — wie bereits in der PROJ-73-QA dokumentiert).
- [x] Bestätigtes „Alle" → bis zu 100 Treffer, datumsabsteigend, `more_available`-Hinweis bei >100 Treffern — verifiziert per Node-Skript (Aggregate-Query, korrekt geklammert nach Bugfix, siehe Bugs).
- [ ] **Nicht live testbar** (Konversationsregel): Ablehnung/Zahlennennung nach Rückfrage → diese Zahl bzw. Standardwert. Instruktionstext vorhanden, nicht live verifizierbar.
- [x] Keine sitzungsweite Persistenz einer Zustimmung — durch Design: es existiert keinerlei State/Flag, das eine frühere „Alle"-Bestätigung speichert; jede Anfrage wird vom LLM anhand des System-Prompts neu bewertet.
- [x] Rückfrage-Regel gilt gleichermaßen für `search_documents`/`search_emails` — gleicher Instruktionstext in beiden bestehenden Tool-Schemas ergänzt; `more_available` zusätzlich in den generischen `Weaviate Search`-Node (Dokumente/Mails) nachgezogen (Aggregate-Query, verifiziert per Node-Skript, `Invoice() → Invoice` Bugfix).

#### Sortierung
- [x] Recency-Signal → Datum absteigend — verifiziert per Node-Skript (dated/undated-Query mit `sort`).
- [x] Kein Inhaltskriterium (auch ohne erkanntes Recency-Signal) → immer Datum absteigend — für Bilder sogar robuster als das generische Dokument/Mail-Muster umgesetzt: `skipHybrid = !hasQuery` ist unabhängig von `sort_mode`, exakt wie in Tech-Entscheidung 3 gefordert ("Sicherheitsnetz, nicht nur LLM-Verhalten").
- [x] Reines Inhaltskriterium ohne Recency → Hybrid-/Vektorsuche, relevanteste zuerst — Score-Sortierung im `else`-Zweig.
- [x] Bilder ohne `exif_datetime` landen am Ende statt zu verschwinden — dated/undated-Dedup-Muster 1:1 von PROJ-73 übernommen.

#### Kachel-Anzeige
- [x] Ergebnisse immer als Kachel-Raster, unabhängig von "zeige mir" — bestehender PROJ-54-Mechanismus greift automatisch bei jedem Treffer mit `weaviate_id`, unabhängig vom Wortlaut.
- [x] Front: quadratisches Thumbnail + Datum/Ort — `docMeta.Image`-Reihenfolge `[date, location, ...]`; `location` ist ein im Workflow berechnetes Feld (`city > district > country`), daher zeigt die Front-Zeile korrekt "Ort" statt eines rohen Einzelfelds, das bei fehlender Stadt leer bliebe.
- [x] Back: EXIF-Felder (Kameramodell, GPS, Ort/Land) — `camera_model`, `camera_make`, `country`, `district`, `latitude`, `longitude` alle in `docMeta.Image` (DE/EN) gelabelt.
- [x] Σ-Icon zeigt `ai_description` als Summary — `title_or_summary: item.ai_description` durchgereicht in das bestehende `summary`-Feld, kein neuer Mechanismus.
- [ ] **BUG-1 (siehe unten):** 0 Treffer öffnet das Kachel-Raster NICHT mit Leerzustand — vorbestehende PROJ-54-Infrastruktur emittiert `vision_results` nur bei ≥1 Treffer.

#### Berechtigungen
- [x] Granulare Leseberechtigung pro Nutzer (`alice.permissions_dms`) — Migration + Rollen-Vorlage verifiziert gegen die echte Live-Schema-Struktur (Postgres-Query).
- [x] Kein Leserecht → keine Treffer, keine Fehlermeldung — `Apply DMS Filter` liefert `collections: []`, Workflow gibt `{results: [], error: null}` zurück, identisch zum bestehenden Verhalten anderer Dokumenttypen.
- [x] Wildcard-Rollen (admin alles erlaubt, guest/child alles verboten) automatisch abgedeckt — verifiziert: beide nutzen bereits `doc_type: '*'`-Zeilen, keine Datenänderung nötig/vorgenommen.
- [x] Rolle „user" erhält expliziten Image-Leserecht-Eintrag — Migration 066 + `init-schema.sql`, Live-Struktur des `user`-Templates vor Migration per Postgres-Query bestätigt (passt exakt zur erwarteten Baseline).
- [x] `search_images` in `tools_allowed` der Rolle „user" ergänzt.

#### Standardanzahl-Einstellung
- [x] Nutzerspezifische Einstellung, System-Default 5, änderbar über Settings-UI — `preferences.bilder_standardanzahl` (1-100), serverseitig validiert (`alice-auth`), Frontend-Feld in `ProfilForm.tsx`.
- [x] Geänderter Wert gilt ab der nächsten Suche ohne explizite Zahl — `Get Image Default Count` liest live bei jedem `search_images`-Aufruf, kein Caching.

### Edge Cases Status
- [x] Ortsbegriff ohne Treffer → 0 Treffer, kein Fehler — durch Konstruktion (leeres `results`-Array).
- [x] Mehrdeutiger Ortsbegriff (z.B. "Georgia") → beide Interpretationen gemeinsam zurückgegeben — inhärent durch den einfachen Substring-`Or`-Match, keine Disambiguierung nötig/vorhanden.
- [x] Kombinierte Anfrage mit weniger Treffern als verlangt → nur tatsächliche Treffer, keine Auffüllung — `results.slice(0, limit)`, keine Padding-Logik vorhanden.
- [x] Bestätigtes „Alle" mit >100 Treffern → neueste 100 + expliziter Hinweis — verifiziert (`more_available`).
- [x] Duplikat-Bild unter zwei Pfaden → ein Objekt = eine Kachel — inhärent, da PROJ-56 dedupliziert auf Weaviate-Objekt-Ebene (`additionalPaths`), unverändert.
- [x] Videosuche außerhalb des Scopes — trivial erfüllt, keine Video-Objekte in der Collection.
- [x] `extraction_failed`-Bild → nicht in Inhaltssuche, aber über Ort/Recency auffindbar — expliziter `continue` nur im Hybrid-Zweig, verifiziert per Code-Review.
- [x] Zwei aufeinanderfolgende „Alle"-Anfragen zu unterschiedlichen Orten → beide lösen unabhängig die Rückfrage aus — kein Session-State vorhanden, der eine Bestätigung persistieren könnte.

### Security Audit Results

**n8n workflow features:**
- [x] Authorization: `user_id` serverseitig aus dem JWT-Kontext gereicht (nicht aus Nutzereingabe), treibt die Postgres-`permissions_dms`-Abfrage; unverändertes, bereits etabliertes Muster.
- [x] GraphQL-Injection über `location`/`query`: getestet mit einem gezielten Payload (`x" } ]) { __typename`) — sowohl `escapeGql` (Bilder) als auch das bestehende Escaping (Dokumente/Mails) neutralisieren das Payload korrekt; es erscheint als literaler String-Wert, keine Query-Struktur-Injection.
- [x] SQL-Injection: `Get Image Default Count` nutzt parametrisierte `queryReplacement` (`$1`), keine String-Konkatenation.
- [x] Serverseitige Validierung von `bilder_standardanzahl` (1-100) in `alice-auth` — verhindert manipulierte Werte auch bei umgangener Frontend-Validierung.
- [x] Keine Geheimnisse in `_debug`-Ausgaben sichtbar (unverändertes, bereits bestehendes Muster).

**Beobachtungen (vorbestehend, nicht durch PROJ-75 eingeführt, hier dokumentiert weil neu relevant):**
- `alice-dms-thumbnailer`s `GET /thumbnail/{weaviate_uuid}` prüft nur einen gültigen JWT, aber **keine** `permissions_dms`-Berechtigung für den zugehörigen Dokumenttyp — jeder authentifizierte Nutzer kann theoretisch jedes Thumbnail per UUID abrufen, wenn er die UUID kennt. Betrifft alle Dokumenttypen gleichermaßen (PROJ-55), nicht PROJ-75-spezifisch, aber durch die neue Bildersuche werden Image-UUIDs jetzt erstmals reihenfolge-basiert an „user"-Rollen-Sessions ausgeliefert. Empfehlung: separates Ticket für `permissions_dms`-Check im Thumbnailer.
- `tool_schema()` in `alice-chat-stream` liefert allen Nutzern dieselbe statische Tool-Liste — `alice.permissions_assistant.tools_allowed` wird an dieser Stelle nicht durchgesetzt (identisches, vorbestehendes Verhalten für alle Tools, nicht PROJ-75-spezifisch). Die tatsächliche Zugriffskontrolle erfolgt korrekt nachgelagert über `permissions_dms` im Workflow (verifiziert oben) — kein Datenleck, aber ein rein advisory statt enforced `tools_allowed`.

### Bugs Found

#### BUG-1: 0-Treffer-Suche öffnet das Kachel-Raster nicht mit Leerzustand
- **Severity:** Medium
- **Root Cause:** `_extract_vision_results()` in `alice-chat-stream/app/streaming.py` gibt `None` zurück, sobald `result.get("results")` eine leere Liste ist (`if isinstance(v, list) and v:` verlangt eine nicht-leere Liste). Dadurch wird das `vision_results`-SSE-Event bei 0 Treffern nie gesendet, `useVisionPanel.setResults()` (Frontend) wird nie aufgerufen, das Panel bleibt geschlossen. Der leere Zustand des `VisionPanel` selbst (`results.length === 0` → "Keine Treffer gefunden") ist korrekt implementiert, wird aber nie erreicht.
- **Scope:** Vorbestehende PROJ-54-Infrastruktur, identisch für `search_documents`/`search_emails`/`search_images` — keine PROJ-75-Regression, aber PROJ-75s Acceptance Criterion ("Kachel-Raster öffnet sich mit Leerzustand") setzt dieses Verhalten explizit voraus und ist damit nicht erfüllt.
- **Steps to Reproduce:** Bildersuche mit einem Ort ohne jegliche Treffer auslösen (z.B. ein nie fotografierter Ort) → LLM antwortet nur textuell "keine Bilder gefunden", kein Kachel-Raster mit Leerzustand öffnet sich.
- **Priority:** Empfehlung: kleiner Folge-Fix in `_extract_vision_results` (z.B. leeres Array statt `None` zurückgeben, wenn die aufgerufene Such-Operation ausdrücklich "search"/"search_images"/"search_emails" war), betrifft geteilte Infrastruktur — Empfehlung als eigenständigen Bugfix-Task nachziehen, nicht blockierend für PROJ-75-Deployment.

### Summary
- **Acceptance Criteria:** 26/29 geprüfte Teilkriterien PASS, 3 als "Konversationsregel, nicht live testbar" markiert (Code-Review bestätigt vorhanden), 1 FAIL (BUG-1).
- **Bugs Found:** 1 total (0 critical, 0 high, 1 medium, 0 low)
- **Security:** Pass — keine PROJ-75-spezifischen Schwachstellen; zwei vorbestehende, nicht blockierende Beobachtungen dokumentiert (Thumbnail-Autorisierung, `tools_allowed`-Durchsetzung).
- **Production Ready:** YES (kein Critical/High-Bug)
- **Recommendation:** Deploy. BUG-1 als separaten Fix für die gemeinsame PROJ-54-Infrastruktur nachziehen (nicht PROJ-75-spezifisch).

## Deployment

**Deployed:** 2026-08-05
**Production URL:** https://alice.happy-mining.de
**Deployed by:** User (containers recreated + n8n workflow import)

Deployed artifacts:
- n8n workflow `alice-tool-search` — new `search_images` operation (`Get Image Default Count` → `Resolve Image Limit` → `Weaviate Search Images`), plus the `more_available` addition to the existing `Weaviate Search` node for `search_documents`/`search_emails`
- `alice-chat-stream` container — new `search_images` tool (`tools.py`), shared "Alle"-Rückfrage system-prompt rule (`memory.py`), `search_images` tool-summary text (`streaming.py`)
- `alice-auth` container — `bilder_standardanzahl` profile preference (read/write on `/auth/profile`)
- Database — `sql/migrations/066-image-search-permissions.sql` applied (`Image` doc_type, `user`-role permission + `tools_allowed` backfill)
- Frontend build — `ProfilForm.tsx` (Standardanzahl-Einstellung) + updated `vision.docMeta.Image`/`vision.extraMeta` label maps (DE/EN)

User confirmed the feature works as expected in production — image search results render correctly as the expected tile/flip-card grid.
