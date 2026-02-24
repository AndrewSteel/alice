# Alice Phase 1.2.2 - GitHub Sync für offizielle HA Intent-Sentences

## Dokumentstatus

| Attribut | Wert |
|----------|------|
| **Dokumenttyp** | Feinkonzept |
| **Phase** | 1.2.2 |
| **Version** | 1.0 |
| **Status** | Entwurf |
| **Basiert auf** | Feinkonzept Phase 1.2 v2.0 |
| **Repository** | https://github.com/AndrewSteel/alice |

---

## Übersicht

Automatischer Import der offiziellen Home Assistant Intent-Sentences aus dem GitHub Repository in unser System.

**Quelle:** https://github.com/home-assistant/intents/tree/main/sentences/de

## Herausforderung: Hassil-Syntax

Die HA Intent-Sentences nutzen eine spezielle Template-Syntax:

```yaml
# sentences/de/_common.yaml
expansion_rules:
  an: "(an|ein)"
  aus: "(aus)"
  schalten: "(schalte|schalt)"
  machen: "(mach|mache)"
  aktivieren: "(aktiviere|aktivier|starte|start)"

# sentences/de/homeassistant_HassTurnOn.yaml
intents:
  HassTurnOn:
    data:
      - sentences:
          - (<schalten>|<machen>) <name>[ <area>] <an>
          - starte <name>[ <area>]
          - <aktivieren> <name>[ <area>]
        excludes_context:
          domain: [binary_sensor, cover, lock, scene, script, sensor, vacuum]
```

**Syntax-Elemente:**
- `<regel>` → Referenz zu `expansion_rules`
- `[optional]` → Optionale Teile (können weggelassen werden)
- `(alt1|alt2)` → Alternativen
- `{slot}` → Dynamische Slots (name, area)

**Beispiel-Expansion:**
```
"(<schalten>|<machen>) <name> <an>"

→ Expansion der Regeln:
"((schalte|schalt)|(mach|mache)) {name} (an|ein)"

→ Konkrete Varianten:
"schalte {name} an"
"schalte {name} ein"
"schalt {name} an"
"schalt {name} ein"
"mach {name} an"
"mach {name} ein"
"mache {name} an"
"mache {name} ein"
```

---

## Architektur

```
┌─────────────────────────────────────────────────────────────────────┐
│                    n8n Workflow: alice-github-intent-sync           │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 1: GitHub Repository laden                                    │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Option A: ZIP Download + Entpacken                          │    │
│  │  https://github.com/home-assistant/intents/archive/main.zip  │    │
│  │                                                              │    │
│  │  Option B: GitHub API (Datei-Liste + Raw-Downloads)          │    │
│  │  GET /repos/home-assistant/intents/contents/sentences/de     │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 2: YAML-Dateien parsen                                        │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  • _common.yaml → expansion_rules, lists, skip_words         │    │
│  │  • *_HassTurnOn.yaml → Intent-Sentences                      │    │
│  │  • *_HassTurnOff.yaml → Intent-Sentences                     │    │
│  │  • etc.                                                      │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 3: Hassil-Syntax expandieren (Python Helper)                  │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  • <regel> ersetzen durch expansion_rules                    │    │
│  │  • [optional] → mit und ohne                                 │    │
│  │  • (alt1|alt2) → alle Varianten                              │    │
│  │  • Kombinatorische Explosion begrenzen (max 50 pro Intent)   │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 4: In unser Format konvertieren                               │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Hassil: "schalte {name} an"                                 │    │
│  │       ↓                                                      │    │
│  │  Alice: { pattern: "schalte {name} an",                      │    │
│  │          intent: "turn_on",                                  │    │
│  │          domain: "light",                                    │    │
│  │          service: "light.turn_on" }                          │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 5: PostgreSQL + Weaviate aktualisieren                        │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  • ha_intent_templates mit source='github' aktualisieren     │    │
│  │  • Auto-Sync triggern für Weaviate Intent-Generierung        │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Option A: Python Helper Script (Empfohlen)

### Warum Python?
- `hassil` ist die offizielle Python-Bibliothek für HA Intent-Parsing
- Kann Sentences sampeln und expandieren
- Robuster als eigener Parser

### Python Script: `expand_ha_intents.py`

```python
#!/usr/bin/env python3
"""
Expandiert Home Assistant Intent-Sentences aus dem GitHub Repository
und gibt sie als JSON für n8n aus.

Verwendung:
  python3 expand_ha_intents.py /path/to/intents/sentences/de --output /tmp/expanded_intents.json
"""

import argparse
import json
import sys
from pathlib import Path

# Optional: hassil für offizielle Expansion
try:
    from hassil.sample import sample_intents
    from hassil.intents import Intents
    HAS_HASSIL = True
except ImportError:
    HAS_HASSIL = False
    print("Warning: hassil not installed, using simple expansion", file=sys.stderr)

import yaml


def load_yaml_files(sentences_dir: Path) -> dict:
    """Lädt alle YAML-Dateien aus dem Verzeichnis."""
    result = {
        'common': None,
        'intents': {}
    }
    
    for yaml_file in sentences_dir.glob('*.yaml'):
        with open(yaml_file, 'r', encoding='utf-8') as f:
            content = yaml.safe_load(f)
        
        if yaml_file.name == '_common.yaml':
            result['common'] = content
        elif 'intents' in content:
            # Dateiname: domain_IntentName.yaml oder homeassistant_IntentName.yaml
            for intent_name, intent_data in content.get('intents', {}).items():
                if intent_name not in result['intents']:
                    result['intents'][intent_name] = []
                result['intents'][intent_name].append({
                    'file': yaml_file.name,
                    'data': intent_data
                })
    
    return result


def expand_rules(text: str, expansion_rules: dict) -> str:
    """Ersetzt <regel> durch die Expansion."""
    for rule_name, rule_value in expansion_rules.items():
        text = text.replace(f'<{rule_name}>', rule_value)
    return text


def expand_optionals(text: str) -> list:
    """Expandiert [optional] zu Varianten mit und ohne."""
    import re
    
    # Finde alle [optional] Teile
    pattern = r'\[([^\]]+)\]'
    matches = list(re.finditer(pattern, text))
    
    if not matches:
        return [text]
    
    # Erste Optional expandieren
    match = matches[0]
    optional_text = match.group(1)
    before = text[:match.start()]
    after = text[match.end():]
    
    # Variante ohne
    without = before + after
    # Variante mit
    with_opt = before + optional_text + after
    
    # Rekursiv weitere Optionals expandieren
    results = []
    results.extend(expand_optionals(without.strip()))
    results.extend(expand_optionals(with_opt.strip()))
    
    return results


def expand_alternatives(text: str) -> list:
    """Expandiert (alt1|alt2) zu allen Varianten."""
    import re
    
    # Finde erste Alternative (nicht-gierig)
    pattern = r'\(([^)]+)\)'
    match = re.search(pattern, text)
    
    if not match:
        return [text]
    
    alternatives = match.group(1).split('|')
    before = text[:match.start()]
    after = text[match.end():]
    
    results = []
    for alt in alternatives:
        expanded = before + alt.strip() + after
        # Rekursiv weitere Alternativen
        results.extend(expand_alternatives(expanded))
    
    return results


def expand_sentence(sentence: str, expansion_rules: dict, max_variants: int = 20) -> list:
    """Expandiert eine Sentence zu allen Varianten."""
    # 1. Regeln ersetzen
    expanded = expand_rules(sentence, expansion_rules)
    
    # 2. Alternativen expandieren
    variants = expand_alternatives(expanded)
    
    # 3. Optionals expandieren
    final_variants = []
    for variant in variants:
        final_variants.extend(expand_optionals(variant))
    
    # 4. Cleanup und Deduplizierung
    cleaned = []
    seen = set()
    for v in final_variants:
        # Mehrfache Leerzeichen entfernen
        v = ' '.join(v.split())
        if v and v not in seen:
            seen.add(v)
            cleaned.append(v)
    
    # 5. Limitieren
    return cleaned[:max_variants]


def hassil_intent_to_service(intent_name: str, domain: str = None) -> tuple:
    """Mappt HA Intent-Namen zu unserem Format."""
    mapping = {
        'HassTurnOn': ('turn_on', '{domain}.turn_on'),
        'HassTurnOff': ('turn_off', '{domain}.turn_off'),
        'HassToggle': ('toggle', '{domain}.toggle'),
        'HassLightSet': ('set_brightness', 'light.turn_on'),
        'HassOpenCover': ('open', 'cover.open_cover'),
        'HassCloseCover': ('close', 'cover.close_cover'),
        'HassStopCover': ('stop', 'cover.stop_cover'),
        'HassMediaPause': ('pause', 'media_player.media_pause'),
        'HassMediaUnpause': ('play', 'media_player.media_play'),
        'HassMediaNext': ('next', 'media_player.media_next_track'),
        'HassMediaPrevious': ('previous', 'media_player.media_previous_track'),
        'HassVolumeUp': ('volume_up', 'media_player.volume_up'),
        'HassVolumeDown': ('volume_down', 'media_player.volume_down'),
        'HassVolumeMute': ('mute', 'media_player.volume_mute'),
        'HassSetVolume': ('set_volume', 'media_player.volume_set'),
        'HassClimateSetTemperature': ('set_temperature', 'climate.set_temperature'),
        'HassClimateGetTemperature': ('get_temperature', None),  # Query, kein Service
        'HassVacuumStart': ('start', 'vacuum.start'),
        'HassVacuumReturnToBase': ('return_to_base', 'vacuum.return_to_base'),
        'HassLockLock': ('lock', 'lock.lock'),
        'HassLockUnlock': ('unlock', 'lock.unlock'),
        'HassActivateScene': ('activate', 'scene.turn_on'),
    }
    
    if intent_name in mapping:
        intent, service_template = mapping[intent_name]
        service = service_template.format(domain=domain) if domain and service_template else service_template
        return intent, service
    
    # Fallback
    return intent_name.lower().replace('hass', ''), None


def extract_domain_from_file(filename: str) -> str:
    """Extrahiert Domain aus Dateiname."""
    # light_HassTurnOn.yaml → light
    # homeassistant_HassTurnOn.yaml → None (generisch)
    parts = filename.replace('.yaml', '').split('_')
    if parts[0] != 'homeassistant':
        return parts[0]
    return None


def process_intents(yaml_data: dict, max_patterns_per_intent: int = 50) -> list:
    """Verarbeitet alle Intents und gibt sie in unserem Format aus."""
    expansion_rules = yaml_data['common'].get('expansion_rules', {}) if yaml_data['common'] else {}
    
    results = []
    
    for intent_name, intent_sources in yaml_data['intents'].items():
        for source in intent_sources:
            file_domain = extract_domain_from_file(source['file'])
            intent_data = source['data']
            
            for data_block in intent_data.get('data', []):
                sentences = data_block.get('sentences', [])
                slots = data_block.get('slots', {})
                excludes = data_block.get('excludes_context', {})
                
                # Domain aus slots oder Dateiname
                domain = slots.get('domain', file_domain)
                
                # Intent und Service bestimmen
                our_intent, service = hassil_intent_to_service(intent_name, domain)
                
                # Alle Sentences expandieren
                all_patterns = []
                for sentence in sentences:
                    expanded = expand_sentence(sentence, expansion_rules)
                    all_patterns.extend(expanded)
                
                # Limitieren
                all_patterns = all_patterns[:max_patterns_per_intent]
                
                if all_patterns and service:
                    results.append({
                        'ha_intent': intent_name,
                        'intent': our_intent,
                        'domain': domain,
                        'service': service,
                        'patterns': all_patterns,
                        'slots': slots,
                        'excludes_context': excludes,
                        'source_file': source['file']
                    })
    
    return results


def main():
    parser = argparse.ArgumentParser(description='Expand HA Intent Sentences')
    parser.add_argument('sentences_dir', help='Path to sentences/de directory')
    parser.add_argument('--output', '-o', help='Output JSON file', default='-')
    parser.add_argument('--max-patterns', type=int, default=50, 
                        help='Max patterns per intent (default: 50)')
    args = parser.parse_args()
    
    sentences_path = Path(args.sentences_dir)
    if not sentences_path.exists():
        print(f"Error: Directory not found: {sentences_path}", file=sys.stderr)
        sys.exit(1)
    
    # YAML-Dateien laden
    yaml_data = load_yaml_files(sentences_path)
    
    # Intents verarbeiten
    results = process_intents(yaml_data, args.max_patterns)
    
    # Output
    output_data = {
        'language': 'de',
        'source': 'github.com/home-assistant/intents',
        'intent_count': len(results),
        'intents': results
    }
    
    if args.output == '-':
        print(json.dumps(output_data, ensure_ascii=False, indent=2))
    else:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        print(f"Written {len(results)} intents to {args.output}", file=sys.stderr)


if __name__ == '__main__':
    main()
```

---

## Option B: n8n Workflow mit Execute Command

### Voraussetzungen

1. **Python im n8n Container installieren** (falls nicht vorhanden)
2. **Script auf dem Host/Volume ablegen**
3. **PyYAML installieren:** `pip install pyyaml`

### n8n Workflow: alice-github-intent-sync

```
┌─────────────┐
│  Schedule   │  (Wöchentlich, z.B. Sonntag 3:00)
│  Trigger    │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│  HTTP Request: Download ZIP                                         │
│  URL: https://github.com/home-assistant/intents/archive/main.zip   │
│  Response: Binary                                                   │
└─────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Execute Command: Entpacken                                         │
│  cd /tmp && rm -rf intents-main && unzip -o intents.zip            │
└─────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Execute Command: Python Script                                     │
│  python3 /scripts/expand_ha_intents.py \                           │
│    /tmp/intents-main/sentences/de \                                 │
│    --output /tmp/expanded_intents.json                              │
└─────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Read File: /tmp/expanded_intents.json                              │
│  Parse JSON                                                         │
└─────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Code: Convert to our Template Format                               │
│  • Gruppieren nach domain                                           │
│  • {name} und {area} Platzhalter behalten                          │
│  • In ha_intent_templates Format konvertieren                       │
└─────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PostgreSQL: Upsert Templates                                       │
│  INSERT INTO alice.ha_intent_templates ... ON CONFLICT UPDATE      │
│  SET source = 'github', updated_at = NOW()                          │
└─────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│  MQTT Publish: Trigger Entity-Sync                                  │
│  alice/ha/sync → {"event": "templates_updated", "source": "github"} │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Option C: Reiner JavaScript-Ansatz in n8n (ohne Python)

Falls Python nicht verfügbar, kann die Expansion auch in JavaScript erfolgen:

```javascript
// n8n Code Node: Hassil-Syntax Expander

function expandRules(text, expansionRules) {
  for (const [ruleName, ruleValue] of Object.entries(expansionRules)) {
    text = text.replace(new RegExp(`<${ruleName}>`, 'g'), ruleValue);
  }
  return text;
}

function expandAlternatives(text) {
  const regex = /\(([^)]+)\)/;
  const match = regex.exec(text);
  
  if (!match) return [text];
  
  const alternatives = match[1].split('|').map(s => s.trim());
  const before = text.slice(0, match.index);
  const after = text.slice(match.index + match[0].length);
  
  const results = [];
  for (const alt of alternatives) {
    const expanded = before + alt + after;
    results.push(...expandAlternatives(expanded));
  }
  return results;
}

function expandOptionals(text) {
  const regex = /\[([^\]]+)\]/;
  const match = regex.exec(text);
  
  if (!match) return [text];
  
  const optional = match[1];
  const before = text.slice(0, match.index);
  const after = text.slice(match.index + match[0].length);
  
  const withoutOpt = (before + after).replace(/\s+/g, ' ').trim();
  const withOpt = (before + optional + after).replace(/\s+/g, ' ').trim();
  
  return [
    ...expandOptionals(withoutOpt),
    ...expandOptionals(withOpt)
  ];
}

function expandSentence(sentence, expansionRules, maxVariants = 20) {
  // 1. Regeln ersetzen
  let expanded = expandRules(sentence, expansionRules);
  
  // 2. Alternativen expandieren
  let variants = expandAlternatives(expanded);
  
  // 3. Optionals expandieren
  let finalVariants = [];
  for (const variant of variants) {
    finalVariants.push(...expandOptionals(variant));
  }
  
  // 4. Deduplizieren und limitieren
  const unique = [...new Set(finalVariants.map(v => v.replace(/\s+/g, ' ').trim()))];
  return unique.slice(0, maxVariants);
}

// Beispiel-Verwendung:
const expansionRules = {
  'an': '(an|ein)',
  'aus': '(aus)',
  'schalten': '(schalte|schalt)',
  'machen': '(mach|mache)',
  'aktivieren': '(aktiviere|aktivier|starte|start)'
};

const sentence = '(<schalten>|<machen>) {name}[ im {area}] <an>';
const expanded = expandSentence(sentence, expansionRules);

// → ["schalte {name} an", "schalte {name} ein", "schalte {name} im {area} an", ...]
```

---

## Empfehlung

**Option A (Python Helper) ist die robusteste Lösung:**

1. Offizielles `hassil`-Paket kann genutzt werden
2. Komplexe YAML-Strukturen werden korrekt verarbeitet
3. Edge Cases (verschachtelte Regeln, Kontexte) werden behandelt

**Aufwand:**
| Schritt | Dauer |
|---------|-------|
| Python Script erstellen | 2h |
| n8n Workflow bauen | 2h |
| PostgreSQL Integration | 1h |
| Tests | 1h |
| **Gesamt** | **~6h** |

---

## Implementierungsschritte

| # | Aufgabe | Dauer | Abhängigkeit |
|---|---------|-------|--------------|
| 1.2.10.1 | Python Script `expand_ha_intents.py` erstellen | 2h | - |
| 1.2.10.2 | Script in n8n Container/Volume bereitstellen | 30 min | 1.2.10.1 |
| 1.2.10.3 | n8n Workflow alice-github-intent-sync erstellen | 2h | 1.2.10.2 |
| 1.2.10.4 | PostgreSQL: Upsert-Logik für source='github' | 30 min | 1.2.10.3 |
| 1.2.10.5 | Integration mit Entity-Sync (MQTT Trigger) | 30 min | 1.2.10.4 |
| 1.2.10.6 | Tests: Manueller Sync, Verify in Weaviate | 30 min | 1.2.10.5 |

---

## Sync-Strategie

| Trigger | Frequenz | Aktion |
|---------|----------|--------|
| **Scheduled** | Wöchentlich (So 3:00) | Full GitHub Sync |
| **Manual** | Bei Bedarf | API-Call oder n8n UI |
| **HA Update** | Nach Core-Update | Optional: Prüfung auf neue Intents |

---

## Mapping: HA Intent → Alice Intent

| HA Intent | Alice Intent | Domain | Service |
|-----------|--------------|--------|---------|
| HassTurnOn | turn_on | (aus slots) | {domain}.turn_on |
| HassTurnOff | turn_off | (aus slots) | {domain}.turn_off |
| HassToggle | toggle | (aus slots) | {domain}.toggle |
| HassLightSet | set_brightness | light | light.turn_on |
| HassOpenCover | open | cover | cover.open_cover |
| HassCloseCover | close | cover | cover.close_cover |
| HassMediaPause | pause | media_player | media_player.media_pause |
| HassMediaNext | next | media_player | media_player.media_next_track |
| HassVolumeUp | volume_up | media_player | media_player.volume_up |
| HassActivateScene | activate | scene | scene.turn_on |
