# Entscheidungs-Matrix

## Lokale LLM-Hardware vs. Cloud-LLM-API

---

## Ziel dieses Dokuments

Diese Matrix unterstützt Anwender bei der Entscheidung zwischen:

* **lokaler KI-Hardware (eigene GPU)**
* **Cloudbasierter LLM-Nutzung per API**

Die Bewertung basiert auf realistischen Nutzungsprofilen im privaten und semi-professionellen Umfeld (Smart Home, Assistenzsysteme, Automationen, Analyse).

---

# 1. Grundprinzip

| Modell         | Charakteristik                             |
| -------------- | ------------------------------------------ |
| **LLM API**    | Nutzung wird pro Anfrage bezahlt           |
| **Lokale GPU** | Einmalige Investition mit Flatrate-Nutzung |

---

# 2. Nutzungsprofil-Analyse

## Klasse A — Gelegenheitsnutzer

**Typische Nutzung**

* Sprachassistent
* gelegentliche Chat-Anfragen
* einfache Automationen
* Wissensfragen

| Bewertung          | Ergebnis              |
| ------------------ | --------------------- |
| Nutzungshäufigkeit | niedrig               |
| Monatsverbrauch    | < 5 Mio Tokens        |
| API-Kosten         | 10–40 €               |
| Hardware sinnvoll? | ❌ Nein                |
| Empfehlung         | **LLM API verwenden** |

✅ Keine Wartung
✅ Immer aktuelle Modelle
✅ Niedrige Einstiegskosten

---

## Klasse B — Regelmäßige KI-Nutzung

**Typische Nutzung**

* tägliche Assistenz
* Dokumentanalyse
* Coding-Unterstützung
* Home-Automation Erweiterungen

| Bewertung          | Ergebnis                         |
| ------------------ | -------------------------------- |
| Nutzungshäufigkeit | mittel                           |
| Monatsverbrauch    | 5–20 Mio Tokens                  |
| API-Kosten         | 40–120 €                         |
| Hardware sinnvoll? | ⚖️ Grenzbereich                  |
| Empfehlung         | **API starten → Nutzung messen** |

Strategie:

1. API einsetzen
2. reale Kosten 2–3 Monate beobachten
3. bei steigender Nutzung Hardware prüfen

---

## Klasse C — Power User / AI-First Umgebung

**Typische Nutzung**

* permanente Assistenzsysteme
* Hintergrund-Agenten
* Sprachpipeline (STT/TTS)
* Embeddings / Automationen
* lokale Datenanalyse
* Dauerbetrieb

| Bewertung          | Ergebnis                  |
| ------------------ | ------------------------- |
| Nutzungshäufigkeit | hoch                      |
| Monatsverbrauch    | > 20 Mio Tokens           |
| API-Kosten         | 150–800 €                 |
| Hardware sinnvoll? | ✅ Ja                      |
| Empfehlung         | **Lokale GPU anschaffen** |

Vorteile:

* konstante Kosten
* niedrige Latenz
* Datenschutz
* Offlinefähigkeit
* dauerhaft geladene Modelle

---

# 3. Wirtschaftlicher Vergleich

## Lokale GPU (Referenzsystem)

| Komponente           | Kosten               |
| -------------------- | -------------------- |
| KI-PC inkl. RTX 4090 | ~3.000 €             |
| Lebensdauer          | 4 Jahre              |
| Abschreibung         | ~62 €/Monat          |
| Strom                | 25–40 €/Monat        |
| **Gesamtkosten**     | **≈ 90–100 €/Monat** |

---

## API-Kostenvergleich

| Monatliche Nutzung | API wirtschaftlich?      |
| ------------------ | ------------------------ |
| < 50 €             | ✅ API                    |
| 50–120 €           | ⚖️ abhängig vom Wachstum |
| > 150 € dauerhaft  | ✅ lokale GPU günstiger   |

---

# 4. Technische Entscheidungsfaktoren

| Kriterium       | API             | Lokale GPU    |
| --------------- | --------------- | ------------- |
| Einstiegskosten | ✅ sehr gering   | ❌ hoch        |
| Wartungsaufwand | ✅ keiner        | ❌ vorhanden   |
| Datenschutz     | ❌ extern        | ✅ lokal       |
| Offlinebetrieb  | ❌ nein          | ✅ ja          |
| Skalierbarkeit  | ✅ hoch          | ⚠️ begrenzt   |
| Dauerbetrieb    | ❌ teuer         | ✅ ideal       |
| Modellkontrolle | ❌ eingeschränkt | ✅ vollständig |

---

# 5. Empfohlene Entscheidungsstrategie

## Schritt 1 — Einstieg

LLM per API nutzen.

## Schritt 2 — Nutzung messen

Monatliche Kosten beobachten.

## Schritt 3 — Break-Even prüfen

Wenn dauerhaft gilt:

> API-Kosten > 100 € / Monat

→ lokale GPU wirtschaftlich sinnvoll.

---

# 6. Praxis-Faustregel

> **Gelegentliche KI → API**
> **Tägliche KI → lokale GPU**

Oder quantitativ:

> **Mehr als 5 Mio Tokens pro Woche → Hardware prüfen**

---

# 7. Empfohlene Zielarchitektur (Best Practice)

Langfristig optimal:

* Lokale GPU für Daueraufgaben
* API für komplexe Spezialmodelle
* automatische Auswahl je Anfrage

(Hybrid-KI-Architektur)

---

**Stand:** 2026
**Anwendungsbereich:** Private KI-Systeme, Smart Home, Home Server, Prosumer

