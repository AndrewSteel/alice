---
name: sector-workflow
description: Führt den vollständigen 7-Schritte-Sektor-Analyse-Workflow durch (Sektor verstehen → Screenen → Vergleichen → Tiefenanalyse → DCF → Thesen → Dashboard) und aktualisiert danach automatisch das Dashboard. Verwende diesen Skill immer wenn der Benutzer einen neuen Sektor analysieren möchte, den kompletten Workflow starten will, "neuen Sektor", "Vollanalyse", "kompletter Workflow", "Sektor analysieren", "von vorne anfangen" oder "Dashboard aktualisieren" sagt – auch wenn er nur einen Sektor-Namen nennt und implizit die ganze Analyse meint.
---

# Sektor-Analyse Vollworkflow

Dieser Skill führt den gesamten Analyse-Workflow durch und integriert alle Ergebnisse am Ende in `dashboard.html`.

---

## 0. Initiierung

**Sammle zunächst folgende Angaben (falls nicht bereits im Kontext):**

1. **Sektor-Name** (z.B. "Energy Transition", "AI Infrastructure", "Healthcare IT")
2. **These / Angle** (optional): Gibt es eine spezifische Investmentthese dahinter?
3. **Einstiegspunkt**: Ab welchem Schritt? (Standard: Schritt 1)

**Lege sofort die Ordnerstruktur an:**
```
[SectorName]/
└── Initiating_Coverage/
```

**Zeige nach Initiierung einen Fortschritts-Header:**
```
◆ Sektor-Analyse: [SectorName]
──────────────────────────────
⬜ Schritt 1: Sektor verstehen
⬜ Schritt 2: Kandidaten screenen
⬜ Schritt 3: Vergleich & Bewertung
⬜ Schritt 4: Tiefenanalyse pro Firma
⬜ Schritt 5: Fairer Wert (DCF)
⬜ Schritt 6: Investment-Thesen
⬜ Schritt 7: Dashboard aktualisieren
```

---

## Schritt 1: Sektor verstehen

Invoke `/equity-research:sector-overview` für den Sektor.

**Output-Datei**: `[Sector]_Sektor_Uebersicht_[YYYY].docx` im Sektorordner.

**Checkpoint nach Schritt 1** – fasse kompakt zusammen:
- Marktgröße (TAM) und Wachstumsrate (CAGR)
- Die 2–3 stärksten strukturellen Trends
- Vorläufige Liste von 8–10 Kandidaten für den nächsten Schritt

Aktualisiere den Fortschritts-Header: ✅ Schritt 1.

---

## Schritt 2: Kandidaten screenen

Invoke `/equity-research:screen` für den Sektor.

**Output-Datei**: `[Theme]_Screen_[MonYYYY].xlsx`

**Checkpoint nach Schritt 2:**
Präsentiere eine Shortlist der besten 5 Kandidaten:

| Ticker | Name | Marktgröße | Wachstum | Begründung |
|--------|------|------------|----------|------------|

Warte auf explizite Bestätigung der finalen 5 Firmen durch den Benutzer.

Aktualisiere den Fortschritts-Header: ✅ Schritt 2.

---

## Schritt 3: Vergleich & Bewertung

Invoke nacheinander:
1. `/financial-analysis:competitive-analysis` für die 5 Kandidaten
2. `/financial-analysis:comps-analysis` für die 5 Kandidaten

**Output-Dateien**:
- `[Sector]_Competitive_Analysis_[YYYY].docx`
- `[Sector]_Comps_[YYYY].xlsx`

**Checkpoint nach Schritt 3:**
- Welche 2–3 Favoriten haben sich herauskristallisiert?
- Kurze Begründung (Wettbewerbsposition, Bewertung, Wachstum)

Aktualisiere den Fortschritts-Header: ✅ Schritt 3.

---

## Schritt 4: Tiefenanalyse pro Firma

Invoke `/equity-research:initiating-coverage` für jeden der Top-Kandidaten (mindestens Top 2–3, idealerweise alle 5).

**Output-Dateien** pro Firma: `[TICKER]_Research_Document_[MonYYYY].md` in `Initiating_Coverage/`

**Sammle für das Dashboard** – halte diese Daten für Schritt 7 bereit:

```
Für jede Firma:
- ticker, name, fullName, exchange
- marketCap (Mrd. USD), revenue (TTM Mrd. USD)
- growth (YoY %), grossMargin (%), fcfMargin (%)
- ev (Mrd. USD), evRev (Multiple)
- ruleOf40 = growth + fcfMargin
- nrr (z.B. ">120%")
- moat (1–5 Sterne)
- verdict (z.B. "Qualitätsführer", "Günstigste Wahl", "Wachstumswette")
- what (1–2 Sätze: Was macht das Unternehmen?)
- bull (1–2 Sätze: Bull-Case)
- bear (1–2 Sätze: Bear-Case)
- strategy (3–4 Sätze: Wohin will das Unternehmen?)
- moatDetails (4 Dimensionen: Netzwerkeffekte, Wechselhürden, Skalenvorteile, KI/Datenvorteil; score 1–3 + explain)
- scenarios: bull/base/bear (Wahrscheinlichkeit % + Text)
- summary (emoji + ausführlicher Text für Einsteiger + borderColor + bgColor)
```

Aktualisiere den Fortschritts-Header: ✅ Schritt 4.

---

## Schritt 5: Fairer Wert (DCF)

Invoke `/financial-analysis:dcf-model` für die Top-Kandidaten.

**Output-Dateien** pro Firma: `[TICKER]_DCF_Model_[MonYYYY].xlsx` in `Initiating_Coverage/`

Ergänze für das Dashboard die DCF-Szenarien (Bull/Base/Bear mit Rendite-% und Kurztext).

Aktualisiere den Fortschritts-Header: ✅ Schritt 5.

---

## Schritt 6: Investment-Thesen dokumentieren

Invoke `/equity-research:thesis-tracker` für alle Coverage-Firmen.

**Output-Datei**: `Investment_Thesen_[TICKER1]_[TICKER2]_..._[MonYYYY].md` in `Initiating_Coverage/`

Aktualisiere den Fortschritts-Header: ✅ Schritt 6.

---

## Schritt 7: Dashboard aktualisieren

### 7a: Radar-Scores berechnen

Für jede Firma die 5 Dimensionen auf Skala 0–100:

```
radarScores = [Wachstum, Effizienz, Marge, Bewertung, Burggraben]
```

Formeln (Peer-Gruppe = die 5 analysierten Firmen):

1. Wachstum:   round((growth / max_growth_in_group) × 100)
2. Effizienz:  ruleOf40 (= growth + fcfMargin)
3. Marge:      grossMargin (direkt als Prozentzahl)
4. Bewertung:  min(100, round(800 / evRev))  — günstig = hoher Score
5. Burggraben: moat × 20

### 7b: Farbschema (nach Ticker alphabetisch sortiert)

| # | color     | lightBg   | darkText  |
|---|-----------|-----------|-----------|
| 1 | #3b82f6   | #dbeafe   | #1e40af   |
| 2 | #8b5cf6   | #ede9fe   | #5b21b6   |
| 3 | #10b981   | #d1fae5   | #065f46   |
| 4 | #f59e0b   | #fef3c7   | #92400e   |
| 5 | #ef4444   | #fee2e2   | #991b1b   |

verdictColor = color, verdictBg = lightBg

### 7c: Summary-Box Farben

```
summary.borderColor = color
summary.bgColor:
  blau:  '#eff6ff'
  lila:  '#f5f3ff'
  grün:  '#f0fdf4'
  gelb:  '#fffbeb'
  rot:   '#fff5f5'
```

### 7d: Sektorspezifische Markt-Tiles (4 Kacheln)

Recherchiere 4 Markt-Fakten:
```
label: Kurzes Thema (max. 5 Wörter)
val:   Kennzahl (Zahl, %, Status-Wort)
sub:   Einordnung in 1 Satz
```

### 7e: dashboard.html bearbeiten

Ersetze nur Datenpunkte — niemals CSS oder JS-Logik.

1. Nav-Badge: `Stand: [Monat YYYY]`
2. Hero eyebrow: `Sektor: [SectorName]`
3. Hero-Stats: TAM, CAGR, Anzahl Aktien, Datenstand
4. Market Tiles: 4 Kacheln aus 7d
5. STOCKS-Array — ersetze alles zwischen `const STOCKS = [` und `];`:

```javascript
const STOCKS = [
  {
    ticker: 'XXX',
    name: 'Kurzname',
    fullName: 'Vollständiger Name, Inc.',
    exchange: 'Nasdaq',
    color: '#3b82f6',
    lightBg: '#dbeafe',
    darkText: '#1e40af',
    marketCap: 0,
    revenue: 0,
    growth: 0,
    grossMargin: 0,
    fcfMargin: 0,
    ev: 0,
    evRev: 0,
    ruleOf40: 0,
    nrr: '>120%',
    moat: 4,
    verdict: 'Label',
    verdictColor: '#3b82f6',
    verdictBg: '#dbeafe',
    priceLabel: 'Fair',
    what: '...',
    bull: '...',
    bear: '...',
    radarScores: [0, 0, 0, 0, 0],
    moatDetails: [
      { name: 'Netzwerkeffekte',   score: 2, explain: '...' },
      { name: 'Wechselhürden',     score: 3, explain: '...' },
      { name: 'Skalenvorteile',    score: 2, explain: '...' },
      { name: 'KI / Datenvorteil', score: 2, explain: '...' },
    ],
    strategy: '...',
    scenarios: {
      bull: { pct: 30, text: '...' },
      base: { pct: 50, text: '...' },
      bear: { pct: 20, text: '...' },
    },
    summary: {
      emoji: '⭐',
      text: '...',
      borderColor: '#3b82f6',
      bgColor: '#eff6ff',
    },
  },
  // ... weitere Firmen
];
```

priceLabel-Regeln:
- evRev ≤ 10  →  'Günstig'
- evRev ≤ 15  →  'Fair'
- evRev ≤ 22  →  'Teuer'
- evRev > 22  →  'Sehr teuer'

### 7f: Abschluss-Validierung

1. JavaScript syntaktisch korrekt (kein fehlendes Komma, keine offenen Klammern)?
2. Alle 5 Firmen im STOCKS-Array enthalten?
3. radarScores hat immer genau 5 Werte?

Aktualisiere den Fortschritts-Header: ✅ Schritt 7.

---

## Abschluss-Zusammenfassung

```
✅ Sektor-Analyse abgeschlossen: [SectorName]
─────────────────────────────────────────────

📁 Erstellte Dokumente:
  • [Sector]/[Sector]_Sektor_Uebersicht_YYYY.docx
  • [Sector]/[Theme]_Screen_MonYYYY.xlsx
  • [Sector]/[Sector]_Competitive_Analysis_YYYY.docx
  • [Sector]/[Sector]_Comps_YYYY.xlsx
  • [Sector]/Initiating_Coverage/[T1]_Research_Document_MonYYYY.md
  • [Sector]/Initiating_Coverage/[T1]_DCF_Model_MonYYYY.xlsx
  • [Sector]/Initiating_Coverage/Investment_Thesen_..._MonYYYY.md

🏆 Top-Pick: [TICKER] – [Kurze Begründung in 1 Satz]

📊 Dashboard aktualisiert → dashboard.html im Browser öffnen
```
