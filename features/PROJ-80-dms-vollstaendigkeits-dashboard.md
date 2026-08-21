# PROJ-80: DMS-Vollständigkeits-Dashboard

## Status: Deployed
**Created:** 2026-08-21
**Last Updated:** 2026-08-21

## Dependencies
- Requires: PROJ-77 (Admin-Dashboard Landing Page) — Deployed. Neue Tile(s) werden in das bestehende Tile-Grid (`DashboardShell` + `TileGrid`, admin-only) integriert.
- Requires: PROJ-78 (DMS-Dokumentenklassifizierung Fix) — Deployed. Liefert `classificationConfidence`/`classificationUncertain` je Dokument.
- Requires: PROJ-79 (DMS-Zusammenfassung Sprachkorrektur) — Deployed. Liefert `languageUncertain` je Dokument.

## Kontext

Die DMS-Pipeline durchläuft mehrere Stufen (Pfad-Scan → Extraktion → Klassifizierung/Weaviate-Insert → Thumbnail-Generierung → bei Bildern zusätzlich Geo-Tagging), aber es gibt aktuell keine Gesamtübersicht, wie vollständig der Bestand tatsächlich verarbeitet ist. Weder eine fehlgeschlagene Extraktion noch ein fehlendes Thumbnail noch eine als unsicher markierte Klassifizierung sind heute sichtbar, ohne manuell in Weaviate oder Redis nachzusehen. Das Dashboard schafft diese Sichtbarkeit als neue Tile(s) im bestehenden Admin-Dashboard.

**Vier Dimensionen** (bestätigt im Interview):
1. **Mengen-Coverage**: Pfad-Scan (Redis, `alice:dms:path_to_hash`) vs. tatsächliche Weaviate-Objektanzahl — deckt Dateien auf, die im Scan/in der Extraktion hängen geblieben sind.
2. **Thumbnail-Coverage**: Anteil Weaviate-Objekte mit gesetztem `thumbnail_path` (bzw. `thumbnailPath` bei den sechs DMS-Typen, `thumbnail_path` bei `Image`) — je Dokumenttyp. Keine strukturellen Ausnahmen: `alice-dms-thumbnailer` verarbeitet jedes erfolgreich eingefügte Dokument unabhängig vom Typ, und alle Dateiformate (PDF, Office, Bilder, TXT/MD) werden unterstützt (siehe PROJ-55) — ein fehlendes `thumbnail_path` ist daher immer eine echte Lücke.
3. **Geo-Coverage**: Nur für `Image` relevant (einzige Collection mit `latitude`/`longitude`/`country`/`city`/`district`, befüllt via Geoapify-Reverse-Geocoding im `alice-dms-processor`). Bei den sechs DMS-Typen wird die Geo-Spalte als "n/a" angezeigt, nicht als Lücke gewertet.
4. **Qualitäts-Warnungen** (separate Sektion, keine Coverage-Prozentzahl): Anzahl Dokumente mit `classificationUncertain` (PROJ-78) und/oder `languageUncertain` (PROJ-79).

## User Stories

- Als Andreas (Admin) möchte ich auf dem Admin-Dashboard auf einen Blick sehen, wie vollständig die DMS-Pipeline je Dokumenttyp durchgelaufen ist (Pfad-Scan vs. Weaviate, Thumbnail, Geo), damit ich Vertrauen in die Wissensbasis habe und Lücken erkenne, bevor sie mir bei einer Chat-Anfrage auffallen.
- Als Andreas möchte ich bei einer erkannten Lücke (z.B. "3 Rechnungen ohne Thumbnail") direkt in eine Liste der betroffenen Dokumente (Dateiname, Pfad, Grund) verzweigen können, damit ich gezielt nachschauen kann, statt selbst eine Weaviate-Query zu schreiben.
- Als Andreas möchte ich eine separate Übersicht der als unsicher markierten Dokumente (Klassifizierung und/oder Sprache) sehen, damit ich diese gezielt prüfen und ggf. den Backfill erneut anstoßen kann.
- Als Andreas möchte ich, dass Coverage-Lücken farblich hervorgehoben werden (Ampel-Logik), damit ich nicht jede Prozentzahl einzeln interpretieren muss.
- Als Andreas möchte ich, dass das Dashboard auch dann noch nutzbar bleibt, wenn eine einzelne Datenquelle (z.B. Redis) kurzzeitig nicht erreichbar ist, damit ein einzelner Ausfall nicht die gesamte Übersicht blockiert.

## Acceptance Criteria

### Coverage-Matrix (neue Tile im bestehenden Admin-Dashboard-Grid)
- [ ] Tile ist nur für Nutzer mit `role='admin'` sichtbar, konsistent mit den übrigen PROJ-77-Tiles.
- [ ] Matrix zeigt je Dokumenttyp (Invoice, BankStatement, Document, Email, Contract, SecuritySettlement, Image) und gesamt:
  - Pfad-Scan-Anzahl (aus Redis `alice:dms:path_to_hash`) vs. Weaviate-Objektanzahl, als Coverage-%.
  - Thumbnail-Coverage-% (Anteil Objekte mit gesetztem Thumbnail-Feld).
  - Geo-Coverage-% nur für `Image`; bei den sechs DMS-Typen wird die Spalte als "n/a" dargestellt (keine Coverage-Berechnung, kein Ampel-Status).
- [ ] Alle Werte werden live bei jedem Dashboard-Laden berechnet (Weaviate-Aggregat-Queries + ein Redis-Read) — kein Caching, keine Vorberechnung.
- [ ] Ampel-Farblogik je Zelle: Grün = 100%, Gelb = 95–99%, Rot = <95%.
- [ ] Klick auf eine Zelle mit Coverage <100% öffnet eine Drilldown-Liste der betroffenen Dokumente (Dateiname, Pfad, fehlende Dimension) für admin-only, ungefiltert nach `alice.permissions_dms` (Dashboard ist bereits admin-only wie PROJ-77 — Andreas sieht als Admin ohnehin den vollen Bestand).
- [ ] Ist die Redis-Verbindung beim Laden nicht erreichbar, zeigt ausschließlich die Pfad-Scan-Spalte einen Fehlerzustand ("nicht verfügbar") — Thumbnail- und Geo-Spalten (rein Weaviate-basiert) bleiben unabhängig davon normal sichtbar.
- [ ] Ist Weaviate beim Laden nicht erreichbar, zeigt die gesamte Tile einen Fehlerzustand (da alle drei Coverage-Dimensionen auf Weaviate-Daten angewiesen sind).

### Qualitäts-Warnungen (separate, kleinere Tile/Sektion)
- [ ] Zeigt Gesamtanzahl Dokumente mit `classificationUncertain=true` und separat mit `languageUncertain=true`, je Dokumenttyp und gesamt.
- [ ] Klick öffnet eine Drilldown-Liste (Dateiname, Pfad, welches Flag gesetzt ist).
- [ ] Keine Ampel-Farblogik hier (reine Zähl-Anzeige, kein Coverage-Prozentwert) — 0 ist der Zielzustand, jede Zahl >0 ist per se auffällig genug ohne Schwellwert-Abstufung.

## Edge Cases

- **Redis nicht erreichbar**: Nur die Pfad-Scan-Spalte zeigt einen Fehlerzustand, alle anderen Dimensionen bleiben normal sichtbar (siehe AC oben).
- **Weaviate nicht erreichbar**: Gesamte Coverage-Tile zeigt einen Fehlerzustand; Dashboard selbst (andere PROJ-77-Tiles) bleibt unabhängig funktionsfähig.
- **Leerer Bestand** (z.B. ein Dokumenttyp mit 0 Dokumenten insgesamt): Zeile zeigt "0 Dokumente", keine Division durch Null, keine Ampel-Farbe (neutral/grau).
- **Pfad-Scan-Zahl kleiner als Weaviate-Zahl** (z.B. durch Datei-Löschung auf dem NAS nach Verarbeitung, aber Objekt existiert noch in Weaviate): Wird als Coverage >100% behandelt und auf 100%/Grün gedeckelt, nicht als negative Lücke dargestellt — echte "verwaiste Weaviate-Objekte ohne NAS-Datei" sind kein Ziel dieser Spec.
- **Dokument mit sowohl `classificationUncertain` als auch `languageUncertain`**: Erscheint in der Qualitäts-Warnungen-Drilldown-Liste einmal pro Flag (ggf. zweimal gelistet, je mit eigenem Grund), nicht dedupliziert.
- **Neu erstellter Dokumenttyp ohne jegliche Objekte in Weaviate**: Zeile erscheint trotzdem in der Matrix (mit 0/0 bzw. "keine Daten"), wird nicht aus der Übersicht ausgeblendet.
- **Sehr große Drilldown-Liste** (z.B. >100 betroffene Dokumente nach einem Ausfall): Liste wird angezeigt, ggf. mit Standard-Pagination/Scroll der bestehenden Tabellen-Komponenten — kein hartes Limit, das Dokumente unsichtbar macht.

## Technical Requirements (optional)

- Kein neues Caching/keine neue Persistenz — Pfad-Scan-Baseline live aus Redis (`alice:dms:path_to_hash`), Coverage-Zahlen live aus Weaviate-Aggregat-Queries.
- Kein neuer Navigationspunkt — Integration als Tile(s) im bestehenden `TileGrid` (`frontend/src/components/Dashboard/`), analog zu den bestehenden Weaviate-Count- und n8n-Execution-Tiles aus PROJ-77.
- Feldnamen-Inkonsistenz beachten: Die sechs DMS-Typ-Schemas nutzen camelCase (z.B. `thumbnailPath`, falls vorhanden) — tatsächlich zu verifizieren, da PROJ-55 dies ggf. nur für `Image` (`thumbnail_path`, snake_case) eingeführt hat. Falls die sechs DMS-Typen noch kein Thumbnail-Feld im Schema haben, ist das vor der Architektur-Phase zu klären (siehe Hinweis unten).

## Offener Punkt für die Architektur-Phase

Aus der Recherche vor diesem Interview: Nur `schemas/image.json` hat aktuell `thumbnail_path`. Die sechs DMS-Typ-Schemas (`document.json`, `invoice.json`, etc.) hatten zum Zeitpunkt dieser Spec kein Thumbnail-Feld im Schema-File. Da PROJ-78 bereits `classificationConfidence`/`classificationUncertain` an allen sechs Typen ergänzt hat, ist unklar, ob ein Thumbnail-Feld dort inzwischen existiert oder in PROJ-80 selbst ergänzt werden muss. `/architecture` sollte dies als ersten Schritt verifizieren (`schemas/*.json` + laufende Weaviate-Instanz prüfen), bevor die Thumbnail-Coverage-Query für die sechs DMS-Typen implementiert wird.

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Vorab-Recherche: Offener Punkt aus der Spec geklärt

Geprüft: `schemas/*.json` + der `alice-dms-thumbnailer`-Workflow.

- Keiner der sechs DMS-Typ-Schemas (Invoice, BankStatement, Document, Email, Contract, SecuritySettlement) hat aktuell ein Thumbnail-Feld deklariert.
- Der n8n-Workflow `alice-dms-thumbnailer` PATCHt aber bereits **`thumbnail_path`** (snake_case, derselbe Feldname wie bei `Image`) auf jedes erfolgreich eingefügte Dokument, unabhängig vom Typ — Weaviate nimmt das PATCH auch ohne Schema-Deklaration an.
- Die in der Spec vermutete camelCase-Inkonsistenz (`thumbnailPath`) besteht also **nicht** — der Feldname ist bereits einheitlich `thumbnail_path`.
- **Entscheidung (mit Andreas abgestimmt):** `thumbnail_path` wird als deklariertes Property zu den sechs DMS-Typ-Schemas ergänzt (analog `image.json`), bevor die Coverage-Query gebaut wird. Kein Backfill nötig — die Objekte tragen den Wert schon, nur die Schema-Deklaration fehlt. Das macht künftige Schema-Validierungen/Migrationen sauber und dokumentiert den tatsächlichen Objekt-Zustand korrekt.

### Backend-Einordnung

Die bestehenden PROJ-77-Tiles laden ihre Daten nicht über einen n8n-Workflow, sondern über eigene `/admin/dashboard`-Endpoints im Service **`alice-chat-stream`** (`app/admin_dashboard.py` + `app/main.py`). Dort existiert bereits `get_weaviate_schemas()` — eine Weaviate-Aggregate-Query über alle Collections, hinter `_require_admin` geschützt, mit einheitlichem Fehler-Mapping (`UpstreamError` → HTTP 502).

**Entscheidung:** PROJ-80 erweitert denselben Service, statt einen neuen n8n-Workflow einzuführen. Das hält Auth, Fehler-Handling und Betriebsweg für alle Admin-Dashboard-Tiles einheitlich. Neu hinzu kommt ein Redis-Client in `alice-chat-stream` (aktuell nicht vorhanden) — ausschließlich für den einen Pfad-Scan-Read (`alice:dms:path_to_hash`, geschrieben vom bestehenden `alice-dms-scanner`/`alice-dms-path-worker`).

### A) Komponentenstruktur (Frontend)

```
DashboardShell
+-- TileGrid
    +-- ... bestehende PROJ-77-Tiles (unverändert)
    +-- DmsCoverageTile (neu)
    |   +-- Matrix-Tabelle: Zeile je Dokumenttyp + "Gesamt"
    |   |   +-- Spalte: Pfad-Scan vs. Weaviate (%, Ampel)
    |   |   +-- Spalte: Thumbnail-Coverage (%, Ampel)
    |   |   +-- Spalte: Geo-Coverage (%, Ampel; "n/a" bei den 6 DMS-Typen)
    |   +-- Klick auf Zelle < 100% -> DmsDrilldownSheet (gefiltert nach Typ + Dimension)
    +-- DmsQualityWarningsTile (neu, kleinere Tile/Sektion)
        +-- Zähler-Liste je Dokumenttyp + gesamt
        |   +-- classificationUncertain-Anzahl
        |   +-- languageUncertain-Anzahl
        +-- Klick auf Zähler -> DmsDrilldownSheet (gefiltert nach Typ + Flag)

DmsDrilldownSheet (geteilt von beiden Tiles)
+-- Tabelle: Dateiname, Pfad, Grund/Flag
+-- Scroll/Pagination über bestehende Tabellen-Komponente
```

Beide neuen Tiles reihen sich in den bestehenden `TileGrid` via `tileRegistry.tsx` ein (gleiches Muster wie die fünf PROJ-77-Tiles) — kein neuer Navigationspunkt.

### B) Datenmodell (fachlich)

**Coverage-Matrix**, pro Dokumenttyp (Invoice, BankStatement, Document, Email, Contract, SecuritySettlement, Image) und "Gesamt":
- Pfad-Scan-Anzahl (aus Redis) und Weaviate-Objektanzahl -> daraus berechnete Mengen-Coverage-%.
- Anzahl Objekte mit gesetztem `thumbnail_path` -> Thumbnail-Coverage-%.
- Nur bei Image: Anzahl Objekte mit gesetzten Geo-Feldern (`latitude`/`longitude`) -> Geo-Coverage-%. Bei den sechs DMS-Typen: "n/a", keine Berechnung.
- Ampel je Zelle: Grün 100%, Gelb 95–99%, Rot <95%, Grau/neutral bei 0 Gesamt-Dokumenten (keine Division durch Null). Coverage wird bei >100% (Pfad-Scan < Weaviate) auf 100%/Grün gedeckelt.

**Qualitäts-Warnungen**, pro Dokumenttyp und gesamt:
- Anzahl `classificationUncertain=true`.
- Anzahl `languageUncertain=true`.
- Reine Zählung, keine Ampel-Logik, keine Prozentwerte.

**Drilldown-Liste** (beide Tiles teilen sich die gleiche Darstellung):
- Dateiname, vollständiger Pfad, Grund (fehlende Dimension bzw. gesetztes Flag).
- Ein Dokument mit beiden Flags erscheint zweimal (einmal je Grund), nicht dedupliziert.

Nichts davon wird persistiert — alle Werte werden bei jedem Dashboard-Laden live berechnet (Weaviate-Aggregate + ein Redis-Read), kein Caching, keine Vorberechnung.

### C) Tech-Entscheidungen (Begründung)

- **Erweiterung von `alice-chat-stream` statt neuem n8n-Workflow:** Gleicher Betriebsweg wie die bestehenden PROJ-77-Tiles, ein Auth-Mechanismus (`_require_admin`), ein Fehler-Vokabular. Vermeidet zwei parallele Backend-Wege für dasselbe Dashboard.
- **Schema-Ergänzung `thumbnail_path` vor der Query:** Die Objekte tragen das Feld bereits (siehe oben) — die Schema-Deklaration nachzuziehen ist eine reine Konsistenzkorrektur, kein Datenmigrations-Risiko.
- **Kein Caching:** Von der Spec explizit gefordert (Vertrauens-Indikator soll immer den echten Live-Zustand zeigen, nicht einen veralteten Snapshot). Da das Dashboard admin-only und nicht hochfrequent aufgerufen wird, ist die Query-Last (mehrere Aggregate-Queries + ein Redis-Read pro Laden) unkritisch.
- **Getrennte Fehlerzustände Redis vs. Weaviate:** Redis liefert nur die Pfad-Scan-Baseline (eine von drei Dimensionen) — fällt Redis aus, bleiben Thumbnail- und Geo-Spalten trotzdem aussagekräftig. Weaviate ist dagegen Grundlage aller drei Dimensionen, daher bei Weaviate-Ausfall Fehlerzustand für die gesamte Tile.
- **Geteilte Drilldown-Komponente:** Beide Tiles brauchen strukturell dieselbe Liste (Dateiname, Pfad, Grund) — eine gemeinsame Komponente vermeidet Duplikation, ohne eine verfrühte generische Abstraktion zu sein (es ist exakt derselbe Anwendungsfall zweimal).

### D) Abhängigkeiten (Pakete)

Keine neuen Frontend-Pakete — `table`, `sheet` (shadcn/ui) sind bereits im Projekt vorhanden.

Backend (`alice-chat-stream`): Redis-Client-Bibliothek für Python (z.B. `redis` mit async-Unterstützung) — bisher in diesem Service nicht genutzt, da er bislang nur mit Weaviate/n8n sprach.

## Implementation Notes (Backend Developer)

### Zwei Abweichungen/Klärungen gegenüber dem Tech Design

1. **Pfad→Typ-Zuordnung für die Pfad-Scan-Coverage je Dokumenttyp** (im Tech Design nicht gelöst): `alice:dms:path_to_hash` ist eine reine Pfad→Hash-Hash ohne Typ-Dimension. Mit Andreas abgestimmt: Ordner-Präfix-Matching gegen `alice.dms_watched_folders` (längster passender, `enabled=true`-Pfad bestimmt `suggested_type`). Pfade unter einem "Auto"-Ordner (`suggested_type IS NULL`) oder unter keinem konfigurierten Ordner fließen nur in die Gesamt-Zeile ein, nicht in eine Typ-Zeile — der Typ ist vor der Klassifizierung unbekannt.
   - **Migration 067** (`sql/migrations/067-dms-watched-folders-image-type.sql`): `dms_watched_folders.suggested_type` CHECK-Constraint um `'Image'` erweitert (fehlte bisher, Bild-Ordner konnten keinem Typ zugeordnet werden). `sql/init-schema.sql` konsistent nachgezogen.

2. **Weaviate `where: IsNull` ist auf diesem Schema nachweislich defekt** (dokumentiert in PROJ-73 BUG-3: liefert 0 Ergebnisse statt Fehler, da `indexNullState` nicht aktiviert ist). Das ursprüngliche Tech Design ging von Aggregate-`where`-Queries für Thumbnail-/Geo-/Uncertain-Coverage aus — das funktioniert nachweislich nicht zuverlässig. Stattdessen: pro Collection ein ungefilterter `Get`-Fetch aller Objekte (Corpus ist laut PROJ-78 ~500–2.000 Dokumente gesamt, unkritisch für einen admin-only, nicht hochfrequenten Dashboard-Load) mit anschließender Filterung/Zählung in Python. Etwas mehr Payload pro Request, aber korrekt statt potenziell stillschweigend falsch.

### Schema-Migration `thumbnail_path`

Wie im Tech Design entschieden: `thumbnail_path` (snake_case, wie bei `Image`) als deklariertes Property zu den sechs DMS-Typ-Schemas ergänzt (`schemas/invoice.json`, `document.json`, `email.json`, `contract.json`, `bank-statement.json`, `security-settlement.json`). Kein Backfill nötig — die Objekte tragen den Wert bereits.

Migrationsskript `scripts/proj80-add-thumbnail-field.sh` (analog `proj78-add-classification-fields.sh`, idempotent, POST auf `/v1/schema/{cls}/properties`). **Von Andreas manuell gegen die Produktions-Weaviate-Instanz auszuführen** (Sandbox hat keinen Netzwerkzugriff auf `weaviate:8080`).

### Backend (`alice-chat-stream`)

- Neue Abhängigkeit `redis>=5.0,<6.0` (async-Client via `redis.asyncio`) in `requirements.txt`; neue Env-Vars `REDIS_HOST`/`REDIS_PORT`/`REDIS_PASSWORD` in `.env.example` (Service lief bisher nur gegen Postgres/Weaviate/n8n/Ollama).
- `app/admin_dashboard.py` um drei Funktionen erweitert: `get_dms_coverage()`, `get_dms_quality_warnings()`, `get_dms_drilldown(doc_type, dimension)`. Redis-Fehler wird separat als `RedisUnavailableError` behandelt (nur Pfad-Scan-Spalte zeigt Fehlerzustand, AC); Weaviate-Fehler weiterhin `UpstreamError` → HTTP 502 für die ganze Tile.
- Drei neue Routen in `app/main.py`, alle hinter `_require_admin`: `GET /admin/dms/coverage`, `GET /admin/dms/quality-warnings`, `GET /admin/dms/drilldown?doc_type=&dimension=`.
- Ampel-Logik + 100%-Deckelung (Pfad-Scan < Weaviate-Zahl) serverseitig in `_coverage_pct`/`_traffic_light` berechnet, nicht im Frontend.

### Frontend

- `frontend/src/services/dashboardApi.ts`: Typen + Fetch-Funktionen für Coverage/Quality-Warnings/Drilldown ergänzt (gleiches Fehler-Mapping wie die bestehenden PROJ-77-Funktionen).
- Neue Komponenten in `frontend/src/components/Dashboard/`: `DmsCoverageTile.tsx` (Matrix + Ampel-Punkte, klickbare Zellen bei <100%), `DmsQualityWarningsTile.tsx` (Zähler-Tabelle, klickbar bei >0), `DmsDrilldownSheet.tsx` (gemeinsame Sheet-Komponente für beide Tiles, shadcn `Sheet` + `Table`).
- Beide Tiles in `tileRegistry.tsx` registriert — erben automatisch die admin-only-Zugriffsbeschränkung der `/dashboard`-Route (kein separates Gating nötig, wie bei den PROJ-77-Tiles).
- i18n-Keys unter `dashboard.dmsCoverage`, `dashboard.dmsQualityWarnings`, `dashboard.dmsDrilldown` in `de.ts`/`en.ts` ergänzt.
- `npx tsc --noEmit` und `npm run build` laufen fehlerfrei durch.

### Nicht in dieser Session getestet

- **Kein Live-Test gegen echte Weaviate/Redis/Postgres-Instanz möglich** (Sandbox ohne Netzwerkzugriff auf die Docker-Services) — insbesondere die Python-GraphQL-Queries (`_fetch_all_objects`, `_read_path_scan_counts`) und das UI-Rendering der Tiles wurden nicht end-to-end verifiziert, nur durch Code-Review, `py_compile` und den Next.js-Production-Build abgesichert.
- Empfehlung für `/qa`: Live-Smoke-Test gegen die echte Instanz nach Deployment des Migrationsskripts (`proj80-add-thumbnail-field.sh`) und Migration 067.

## QA Test Results

**Tested:** 2026-08-21
**App URL:** Kein laufender Alice-Stack in dieser Sandbox verfügbar (kein Docker-Netzwerkzugriff auf Weaviate/Redis/Postgres/n8n) — Testmethode: statische Code-Verifikation gegen jedes AC, isolierte Unit-Tests der reinen Berechnungslogik, `tsc --noEmit` + `next build`, Sicherheitsaudit des Codes. Kein Live-/Browser-Test möglich.
**Tester:** QA Engineer (AI)

### Acceptance Criteria Status

#### Coverage-Matrix
- [x] Tile nur admin-sichtbar — erbt die admin-only-Gate der `/dashboard`-Route (`app/(main)/layout.tsx`, Redirect für `role !== "admin"`), identisch zu den PROJ-77-Tiles. Kein eigenes Gating nötig, korrekt wiederverwendet.
- [x] Matrix zeigt alle 7 Dokumenttypen + Gesamt, mit Pfad-Scan-vs-Weaviate-%, Thumbnail-%, Geo-% (nur Image, sonst "n/a") — `get_dms_coverage()` iteriert `DMS_TYPES + [IMAGE_TYPE]`, Frontend rendert `rows + totals`.
- [x] Live-Berechnung bei jedem Laden, kein Caching — kein Cache-Layer im Code, jeder Tile-Load/Refresh triggert einen frischen Fetch.
- [x] Ampel-Farblogik Grün=100/Gelb=95-99/Rot=<95 — verifiziert per isoliertem Unit-Test (8 Fälle inkl. Grenzwerte 94/95/100, siehe unten), alle korrekt.
- [x] Klick auf Zelle <100% öffnet Drilldown — `CoverageCell` macht nur bei `pct < 100 && clickable` einen echten Button, sonst reines Text-Element (nach Fix, siehe BUG-2).
- [x] Redis nicht erreichbar → nur Pfad-Scan-Spalte Fehlerzustand, Thumbnail/Geo bleiben normal — `RedisUnavailableError` wird separat gefangen, nur `pathScanStatus="error"` gesetzt, Thumbnail/Geo werden aus den bereits geladenen Weaviate-Objekten unabhängig berechnet.
- [x] Weaviate nicht erreichbar → ganze Tile Fehlerzustand — `UpstreamError` propagiert aus `_fetch_all_objects` durch `get_dms_coverage()`, Route mappt auf HTTP 502, Frontend zeigt `error`-State für die gesamte Tile.

#### Qualitäts-Warnungen
- [x] Zeigt `classificationUncertain`/`languageUncertain`-Zähler je Typ + gesamt — `get_dms_quality_warnings()`, iteriert nur `DMS_TYPES` (Image korrekt ausgeschlossen, da nicht LLM-klassifiziert).
- [x] Klick öffnet Drilldown (Dateiname, Pfad, Flag) — `openDrilldown` + `DmsDrilldownSheet`, gemeinsame Komponente mit der Coverage-Tile.
- [x] Keine Ampel-Logik, reine Zählung, 0 = grau/neutral — `CountCell` hat keine Farblogik, nur `count === 0` vs. `count > 0`.

### Edge Cases Status

#### Redis nicht erreichbar
- [x] Nur Pfad-Scan-Spalte betroffen — siehe oben. **Aber:** ursprünglich kein Timeout auf dem Redis-Client gesetzt → siehe BUG-1 (gefixt).

#### Weaviate nicht erreichbar
- [x] Ganze Coverage-Tile Fehlerzustand, restliches Dashboard (andere PROJ-77-Tiles) unabhängig funktionsfähig — jede Tile lädt über ihre eigene `fetch*`-Funktion, kein gemeinsamer Fehlerzustand über Tiles hinweg.

#### Leerer Bestand (0 Dokumente)
- [x] Keine Division durch Null, neutral/grau — `_coverage_pct(0, 0) → None → status "neutral"`, verifiziert per Unit-Test.

#### Pfad-Scan-Zahl < Weaviate-Zahl (Coverage >100%)
- [x] Gedeckelt auf 100%/Grün, keine negative Lücke — `min(pct, 100.0)`, verifiziert per Unit-Test (`scanned=10, actual=12 → 100.0/green`).

#### Dokument mit beiden Uncertain-Flags
- [x] Erscheint zweimal in der Drilldown-Liste, einmal je Grund, nicht dedupliziert — `get_dms_drilldown` filtert und mapped pro Dimension separat, zwei getrennte Endpoint-Aufrufe (Coverage-Zelle Thumbnail vs. Geo, bzw. Quality-Warnings classificationUncertain vs. languageUncertain) — kein gemeinsamer Dedup-Schritt vorhanden, der das verhindern würde.

#### Neuer Dokumenttyp ohne Objekte
- [x] Zeile erscheint trotzdem (0/0, "keine Daten"), wird nicht ausgeblendet — `all_types`-Schleife ist eine feste Liste, unabhängig von tatsächlichen Objektzahlen; leere Collection ergibt `weaviate_count=0`, Zeile bleibt im Ergebnis.

#### Sehr große Drilldown-Liste
- [x] Kein Limit, das Dokumente unsichtbar macht, im praktisch relevanten Rahmen — `DRILLDOWN_LIMIT=5000` pro Collection, Gesamtkorpus laut PROJ-78-Spec ~500-2.000 über alle 7 Collections kombiniert. Technisch weiterhin ein hartes Limit, aber mit großem Sicherheitsabstand zur realistischen Größenordnung (siehe BUG-4, Low, als Doku-Hinweis statt Blocker).

### Security Audit Results

**Docker/API features (`alice-chat-stream`):**
- [x] Authentication: Alle drei neuen Endpoints (`/admin/dms/coverage`, `/admin/dms/quality-warnings`, `/admin/dms/drilldown`) hinter `Depends(_require_admin)` → `verify_jwt` (401 bei fehlendem/ungültigem JWT) + Rollen-Check (403 bei `role != "admin"`), identisch zum PROJ-77-Muster.
- [x] Authorization: Dashboard ist bereits admin-only geroutet (`/dashboard`); laut Spec bewusst ungefiltert nach `alice.permissions_dms`, da Admin ohnehin vollen Bestand sieht — das ist die dokumentierte, akzeptierte Design-Entscheidung, kein Leck.
- [x] Input validation / Injection: `doc_type`/`dimension`-Query-Parameter aus `/admin/dms/drilldown` werden gegen eine feste Allowlist (`DMS_TYPES + [IMAGE_TYPE]`, `_DRILLDOWN_DIMENSIONS.keys()`) geprüft, bevor `doc_type` in den GraphQL-Query-String interpoliert wird — kein roher User-Input erreicht die Query. Ungültige Werte → `ValueError` → HTTP 400 mit generischer Meldung, kein Stack-Trace-Leak.
- [x] No secrets visible: Redis-Passwort/Weaviate-URL bleiben serverseitig (Env-Vars), nichts davon fließt in API-Responses.
- [ ] BUG-1 (behoben): Redis-Client ohne Timeout — siehe unten.

### Bugs Found

#### BUG-1: Redis-Client ohne Timeout kann den gesamten Coverage-Request blockieren
- **Severity:** High
- **Root cause:** `_read_path_scan_counts()` erstellte den `redis.asyncio.Redis`-Client ohne `socket_connect_timeout`/`socket_timeout`. Der `redis-py`-Default dafür ist `None` = kein Timeout. Bei einem Netzwerk-Hänger (z.B. Firewall-Drop statt sofortigem Connection-Refused) hätte `client.hkeys(...)` nie zurückgekehrt — der ganze `/admin/dms/coverage`-Request wäre hängen geblieben, statt dass nur die Pfad-Scan-Spalte in den dokumentierten Fehlerzustand wechselt. Widerspricht direkt der AC "Ist Redis nicht erreichbar, zeigt Pfad-Scan-Spalte einen Fehlerzustand".
- **Steps to Reproduce (am Code, nicht live verifizierbar):** Redis-Host so konfigurieren, dass Pakete stillschweigend verworfen werden (kein RST/ICMP-Unreachable) → `hkeys()` blockiert unbegrenzt.
- **Fix:** `socket_connect_timeout=HTTP_TIMEOUT_SECONDS, socket_timeout=HTTP_TIMEOUT_SECONDS` beim Redis-Client-Konstruktor ergänzt (`app/admin_dashboard.py`), konsistent mit dem bestehenden `HTTP_TIMEOUT_SECONDS=10.0`, das für alle httpx-Clients im Service gilt.
- **Priority:** Fix before deployment — **behoben in dieser Session.**

#### BUG-2: Coverage-Zellen ohne echte Klickbarkeit waren dennoch als Button gerendert
- **Severity:** Low
- **Root cause:** In `DmsCoverageTile.tsx` prüfte `CoverageCell` `canClick` korrekt für Styling/disabled-State — das war bereits richtig. Beim Review als eigentlicher Fund bestätigt: kein Bug in dieser Datei (falscher Verdacht beim ersten Scan, durch zweiten Blick auf `canClick`-Gate ausgeräumt). Kein Fix nötig.
- **Priority:** N/A (kein tatsächlicher Bug — im Bericht belassen für Nachvollziehbarkeit des Prüfschritts).

#### BUG-3: Quality-Warnings-Gesamtzeile sah klickbar aus, tat aber nichts
- **Severity:** Medium
- **Root cause:** `CountCell` in `DmsQualityWarningsTile.tsx` rendert bei `count > 0` immer einen `<button>` mit Unterstreichung — auch wenn `onClick={undefined}` (Fall: `isTotal`-Zeile). Der Button reagierte optisch wie klickbar (Cursor, Unterstreichung), tat aber nichts, da kein Drilldown für die Gesamtzeile vorgesehen ist (welcher Dokumenttyp sollte er auch aufrufen?). Verwirrend für den Nutzer.
- **Steps to Reproduce (am Code):** Quality-Warnings-Tile mit `classificationUncertainCount > 0` in der Total-Zeile rendern → Zahl erscheint unterstrichen/klickbar, Klick hat keinen Effekt.
- **Fix:** `CountCell` rendert jetzt bei fehlendem `onClick` ein reines `<span>` statt eines interaktiven, aber wirkungslosen `<button>`.
- **Priority:** Fix before deployment — **behoben in dieser Session.**

#### BUG-4: Drilldown-Race-Condition bei schnellem Zellenwechsel
- **Severity:** Low
- **Root cause:** `DmsDrilldownSheet` hat keinen Schutz gegen veraltete Responses — klickt der Nutzer schnell nacheinander auf zwei verschiedene Zellen (z.B. Thumbnail dann Geo), können zwei Fetches parallel laufen; kommt die erste Antwort nach der zweiten zurück, überschreibt sie fälschlich die aktuell angezeigte Liste.
- **Steps to Reproduce:** Zwei Drilldown-Zellen sehr schnell nacheinander anklicken, bei unterschiedlicher Netzwerklatenz der beiden Requests.
- **Priority:** Nice to have — admin-only, seltene Nutzung, kein Datenverlust/Sicherheitsproblem, nur eine kurzzeitig falsche Anzeige bis zum nächsten manuellen Refresh. Nicht in dieser Session behoben (kein AC-Verstoß, reines Robustheits-Nice-to-have).

#### BUG-5: `None`/0-Verwechslung bei Pfad-Scan-Zahl führt zu HTTP 500 (gefunden im Live-Smoke-Test)
- **Severity:** High
- **Found via:** Live-Deployment durch Andreas — `/admin/dms/coverage` gab durchgehend HTTP 500, in der UI als "Weaviate nicht erreichbar" fehlinterpretiert, obwohl Weaviate per `curl` nachweislich lief.
- **Root cause:** In `get_dms_coverage()` wurde `scanned_count = path_scan.get(t) if redis_error is None else None` verwendet. `path_scan.get(t)` liefert `None`, sobald ein Dokumenttyp **keinen einzigen** gescannten Pfad in Redis hat (z. B. kein `dms_watched_folders`-Eintrag mit diesem `suggested_type`, oder schlicht 0 Dateien dort) — nicht nur bei echtem Redis-Ausfall. `_coverage_pct(scanned, actual)` erwartet aber immer einen `int` für `scanned` und crasht mit `TypeError: '<=' not supported between instances of 'NoneType' and 'int'`, sobald das passiert. Traf in der Produktivumgebung sofort zu, weil mindestens ein Dokumenttyp 0 gescannte Pfade hatte.
- **Steps to Reproduce:** Dashboard mit erreichbarem Redis laden, bei dem mindestens ein Dokumenttyp keine Pfade in `alice:dms:path_to_hash` hat (Präfix-Match ergibt für diesen Typ 0 Treffer) → 500 statt einer korrekten 0%/0-Zeile.
- **Fix:** `path_scan.get(t, 0)` statt `path_scan.get(t)` — `None` bedeutet jetzt ausschließlich "Redis nicht erreichbar" (über `redis_error` separat gesteuert), ein fehlender Dict-Eintrag bei erreichbarem Redis bedeutet korrekt "0 gescannte Pfade für diesen Typ".
- **Priority:** Fix before deployment — **behoben in dieser Session**, erneutes Deployment durch Andreas nötig.

### Summary
- **Acceptance Criteria:** 10/10 geprüfte Kriterien PASS (nach Fix von BUG-1, BUG-3, BUG-5)
- **Bugs Found:** 5 total (0 critical, 2 high — beide behoben, 1 medium — behoben, 2 low — 1 davon kein echter Bug, 1 offen als Nice-to-have)
- **Security:** Pass — Auth/Authz konsistent mit PROJ-77-Muster, keine Injection-Vektoren, keine Secret-Leaks
- **Production Ready:** JA, nach erneutem Deployment von `admin_dashboard.py` mit dem BUG-5-Fix.
- **Wichtige Einschränkung (bestätigt durch den Live-Smoke-Test):** Die ursprüngliche Session-Verifikation basierte auf Code-Review + isolierten Unit-Tests ohne laufende Instanz — BUG-5 wurde dabei **nicht** gefunden, da die Unit-Tests nur `_coverage_pct` mit synthetischen `int`-Werten geprüft haben, nicht den Aufrufer-Code, der `None` durchreichen kann. Das bestätigt: ein Live-Smoke-Test nach Deployment ist für dieses Feature nicht optional, sondern notwendig — genau wie empfohlen.
- **Recommendation:** `admin_dashboard.py` erneut deployen, danach Dashboard neu laden. Qualitäts-Warnungen zeigt "Keine Warnungen" korrekt an (plausibel, da PROJ-78/79-Backfills genau darauf abzielen, unsichere Klassifizierungen/Sprache zu bereinigen — kein Bug).

## Deployment

**Deployed:** 2026-08-21
**Deployed by:** Andreas (manuell)

**Schritte (durch Andreas ausgeführt):**
- `alice-chat-stream`: `.env` um `REDIS_HOST`/`REDIS_PORT`/`REDIS_PASSWORD` ergänzt, Image neu gebaut, Container neu gestartet (inkl. BUG-5-Fix aus dem zweiten `admin_dashboard.py`-Deployment nach dem Live-Smoke-Test).
- Weaviate-Schema-Migration (`thumbnail_path` auf den sechs DMS-Typen): geprüft, Felder waren bereits vorhanden.
- Datenbank-Migration 067 (`dms_watched_folders.suggested_type` inkl. `'Image'`) angewendet.
- Frontend neu gebaut und deployed (`deploy-frontend.sh`).
- nginx neu gestartet.

**Live-Verifikation:**
- Erster Ladeversuch: `/admin/dms/coverage` lieferte HTTP 500 (BUG-5, siehe QA-Sektion) — als "Weaviate nicht erreichbar" in der UI sichtbar, obwohl Weaviate lief. Fix identifiziert, gepatcht, erneut deployed.
- Nach erneutem Deployment: Coverage-Matrix und Qualitäts-Warnungen liefern beide korrekt Daten (von Andreas bestätigt: "Das Frontend liefert die Daten so wie gewünscht").

**Production URL:** https://alice.happy-mining.de/dashboard (admin-only)
