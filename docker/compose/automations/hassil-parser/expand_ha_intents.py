"""
Hassil template expansion for Home Assistant intent sentences.

Handles four constructs:
  [optional]   -> two variants: with and without
  (alt1|alt2)  -> one variant per alternative
  <rule>       -> recursive resolution via expansion_rules
  {slot}       -> kept as placeholder (never replaced)

Hard cap: MAX_PATTERNS_PER_INTENT patterns per intent (default 50).
"""

import itertools
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mapping from HA intent names (PascalCase, Hass-prefixed) to service actions
# Source: https://github.com/home-assistant/intents/blob/main/README.md
# ---------------------------------------------------------------------------
_INTENT_TO_ACTION: dict[str, str] = {
    "HassTurnOn": "turn_on",
    "HassTurnOff": "turn_off",
    "HassToggle": "toggle",
    "HassLightSet": "turn_on",
    "HassSetVolume": "volume_set",
    "HassMediaPause": "media_pause",
    "HassMediaUnpause": "media_play",
    "HassMediaNext": "media_next_track",
    "HassMediaPrevious": "media_previous_track",
    "HassSetTimer": "set_timer",
    "HassCancelTimer": "cancel_timer",
    "HassTimerStatus": "timer_status",
    "HassClimateSetTemperature": "set_temperature",
    "HassClimateGetTemperature": "get_temperature",
    "HassClimateSetHvacMode": "set_hvac_mode",
    "HassOpenCover": "open_cover",
    "HassCloseCover": "close_cover",
    "HassSetCoverPosition": "set_cover_position",
    "HassLockLock": "lock",
    "HassLockUnlock": "unlock",
    "HassVacuumStart": "start",
    "HassVacuumReturnToBase": "return_to_base",
    "HassGetWeather": "get_forecast",
}


def _intent_to_service(intent_name: str, domain: str) -> str:
    """
    Derive the HA service string from an intent name and domain.

    Strategy:
      1. Check the explicit mapping table first.
      2. Strip the 'Hass' prefix and convert PascalCase to snake_case.
      3. If the result contains the domain name, strip it (e.g. 'climate_set_temperature' → 'set_temperature').
      4. Return '{domain}.{action}'.
    """
    if intent_name in _INTENT_TO_ACTION:
        return f"{domain}.{_INTENT_TO_ACTION[intent_name]}"

    # Strip leading 'Hass' prefix
    name = intent_name
    if name.startswith("Hass"):
        name = name[4:]

    # PascalCase → snake_case
    action = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()

    # Strip leading domain prefix if present (e.g. "light_set" with domain "light" → "set")
    domain_prefix = domain + "_"
    if action.startswith(domain_prefix):
        action = action[len(domain_prefix):]

    return f"{domain}.{action}"

MAX_PATTERNS = int(os.environ.get("MAX_PATTERNS_PER_INTENT", "50"))

# ---------------------------------------------------------------------------
# Try to use the official hassil library; fall back to custom implementation
# ---------------------------------------------------------------------------
_USE_HASSIL = False
try:
    from hassil.expression import Expression
    from hassil.intents import Intents
    from hassil.parse_expression import parse_expression
    from hassil.recognize import MISSING_ENTITY

    _USE_HASSIL = True
    logger.info("hassil library available (using custom expansion for now)")
except ImportError:
    logger.info("hassil library not available, using custom expansion")
# NOTE: _USE_HASSIL is intentionally not yet used to switch expansion paths.
# The custom implementation handles all required constructs. Full hassil
# integration is reserved for a future iteration if deeper parsing is needed.


# ===================================================================
# Custom expansion implementation (fallback)
# ===================================================================


def _resolve_rules(template: str, expansion_rules: dict[str, list[str]]) -> list[str]:
    """Replace <rule> references with their expansions recursively."""
    match = re.search(r"<(\w+)>", template)
    if not match:
        return [template]

    rule_name = match.group(1)
    replacements = expansion_rules.get(rule_name, [])
    if not replacements:
        logger.warning("Expansion rule <%s> not found, removing from template", rule_name)
        replacements = [""]

    results: list[str] = []
    for replacement in replacements:
        expanded = template[: match.start()] + replacement + template[match.end() :]
        # Recurse to resolve further <rule> references in the result
        results.extend(_resolve_rules(expanded, expansion_rules))
    return results


def _expand_optionals(template: str) -> list[str]:
    """Expand [optional] into two variants: with and without the content."""
    match = re.search(r"\[([^\[\]]*)\]", template)
    if not match:
        return [template]

    prefix = template[: match.start()]
    suffix = template[match.end() :]
    content = match.group(1)

    results: list[str] = []
    # Variant with the optional content
    results.extend(_expand_optionals(prefix + content + suffix))
    # Variant without the optional content
    results.extend(_expand_optionals(prefix + suffix))
    return results


def _expand_alternatives(template: str) -> list[str]:
    """Expand (alt1|alt2|...) into one variant per alternative."""
    match = re.search(r"\(([^()]*)\)", template)
    if not match:
        return [template]

    prefix = template[: match.start()]
    suffix = template[match.end() :]
    alternatives = match.group(1).split("|")

    results: list[str] = []
    for alt in alternatives:
        results.extend(_expand_alternatives(prefix + alt.strip() + suffix))
    return results


def _normalize(text: str) -> str:
    """Clean up whitespace artifacts from expansion."""
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def expand_template(
    template: str,
    expansion_rules: dict[str, list[str]],
    max_patterns: int = MAX_PATTERNS,
) -> list[str]:
    """
    Expand a single Hassil template string into concrete patterns.

    Order of expansion:
      1. Resolve <rule> references
      2. Expand (alternatives)
      3. Expand [optionals]
      4. Normalize whitespace
      5. Deduplicate
      6. Cap at max_patterns
    """
    # Step 1: resolve rule references
    after_rules = _resolve_rules(template, expansion_rules)

    # Step 2 + 3: expand alternatives and optionals
    all_patterns: list[str] = []
    for t in after_rules:
        after_alts = _expand_alternatives(t)
        for a in after_alts:
            after_opts = _expand_optionals(a)
            all_patterns.extend(after_opts)

        # Early exit if we already have too many
        if len(all_patterns) > max_patterns * 10:
            break

    # Step 4 + 5: normalize and deduplicate
    seen: set[str] = set()
    unique: list[str] = []
    for p in all_patterns:
        normalized = _normalize(p)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)

    # Step 6: cap
    if len(unique) > max_patterns:
        logger.debug(
            "Capping patterns from %d to %d for template: %s",
            len(unique),
            max_patterns,
            template[:80],
        )
        unique = unique[:max_patterns]

    return unique


def expand_intent_sentences(
    sentences: list[str],
    expansion_rules: dict[str, list[str]],
    max_patterns: int = MAX_PATTERNS,
) -> list[str]:
    """
    Expand a list of Hassil template sentences for a single intent.
    Returns deduplicated patterns capped at max_patterns total.
    """
    all_patterns: list[str] = []
    seen: set[str] = set()

    for sentence in sentences:
        expanded = expand_template(sentence, expansion_rules, max_patterns)
        for p in expanded:
            if p not in seen:
                seen.add(p)
                all_patterns.append(p)
            if len(all_patterns) >= max_patterns:
                break
        if len(all_patterns) >= max_patterns:
            break

    return all_patterns


# ===================================================================
# YAML parsing: extract intents from HA intent YAML files
# ===================================================================


def parse_intent_yaml(
    yaml_data: dict,
    domain: str,
    max_patterns: int = MAX_PATTERNS,
) -> list[dict]:
    """
    Parse a single HA intent YAML structure and return a list of dicts:
      [{"domain": str, "intent": str, "language": "de",
        "patterns": list[str], "source": "github",
        "default_parameters": dict | None}, ...]
    """
    language = yaml_data.get("language", "de")
    expansion_rules = yaml_data.get("expansion_rules", {})
    lists_data = yaml_data.get("lists", {})
    intents = yaml_data.get("intents", {})

    # Merge list values into expansion_rules so <list_name> references resolve
    for list_name, list_def in lists_data.items():
        if list_name not in expansion_rules:
            if isinstance(list_def, dict) and "values" in list_def:
                values = []
                for v in list_def["values"]:
                    if isinstance(v, dict) and "in" in v:
                        values.append(str(v["in"]))
                    elif isinstance(v, str):
                        values.append(v)
                if values:
                    expansion_rules[list_name] = values

    results: list[dict] = []

    for intent_name, intent_data in intents.items():
        data_blocks = intent_data.get("data", [])
        all_sentences: list[str] = []
        default_parameters: dict = {}

        for block in data_blocks:
            sentences = block.get("sentences", [])
            all_sentences.extend(sentences)

            # Check for excludes_context
            excludes_context = block.get("excludes_context", {})
            if excludes_context:
                if "domain" in excludes_context:
                    default_parameters.setdefault("excludes_domain", [])
                    excluded = excludes_context["domain"]
                    if isinstance(excluded, str):
                        if excluded not in default_parameters["excludes_domain"]:
                            default_parameters["excludes_domain"].append(excluded)
                    elif isinstance(excluded, list):
                        for d in excluded:
                            if d not in default_parameters["excludes_domain"]:
                                default_parameters["excludes_domain"].append(d)

            # Check for requires_context
            requires_context = block.get("requires_context", {})
            if requires_context:
                if "domain" in requires_context:
                    default_parameters["requires_domain"] = requires_context["domain"]

        if not all_sentences:
            logger.warning("Intent %s in domain %s has no sentences, skipping", intent_name, domain)
            continue

        patterns = expand_intent_sentences(all_sentences, expansion_rules, max_patterns)

        if not patterns:
            logger.warning(
                "Intent %s in domain %s expanded to 0 patterns, skipping",
                intent_name,
                domain,
            )
            continue

        logger.info(
            "Intent %s (domain=%s): %d sentences -> %d patterns",
            intent_name,
            domain,
            len(all_sentences),
            len(patterns),
        )

        results.append(
            {
                "domain": domain,
                "intent": intent_name,
                "service": _intent_to_service(intent_name, domain),
                "language": language,
                "patterns": patterns,
                "source": "github",
                "default_parameters": default_parameters if default_parameters else None,
            }
        )

    return results
