"""Image description through alice-llm-gateway (OpenAI compatible /v1/chat/completions, PROJ-111).

One call per image (AK-18) answers description, short title and the text in the image as JSON.
Panoramas: one call per tile plus one text-only call that merges them (AK-23). All or nothing:
any failed call fails the whole description (AK-24).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

from .errors import TransientError

_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)
MIN_DESCRIPTION_CHARS = 20
TITLE_MAX = 80

RULES = (
    "Regeln:\n"
    "- Schreibe auf Deutsch.\n"
    "- Beschreibe ausführlich (etwa 800 bis 1500 Zeichen): Motiv, Personen (Anzahl, Tätigkeit, Kleidung; "
    "niemals wer sie sind), Umgebung, Architektur, Licht, Stimmung und Jahreszeit.\n"
    "- Nenne Orte, Städte, Gebäude oder Sehenswürdigkeiten nur, wenn sie eindeutig erkennbar sind, "
    "z. B. durch eine Beschriftung im Bild, oder wenn sie unten als Aufnahmeort angegeben sind. "
    "Sonst beschreibe sie neutral (z. B. „ein historisches Tor“), rate keine Namen.\n"
    "- Identifiziere keine Personen.\n"
)

SINGLE_PROMPT = (
    "Du beschreibst ein Foto für ein privates Bildarchiv.\n" + RULES +
    "Antworte nur mit einem JSON-Objekt mit genau diesen Schlüsseln:\n"
    '{"description": "<ausführliche Beschreibung>", '
    '"title": "<kurzer Titel aus wenigen Wörtern, ohne Datum>", '
    '"text_in_image": "<wörtliche Abschrift gut lesbaren Texts im Bild, Zeilen mit \\n getrennt; '
    'leer, wenn kein Text lesbar ist>"}'
)

TILE_PROMPT = (
    "Dies ist Ausschnitt {i} von {n} eines Panoramabilds ({direction}).\n" + RULES +
    "Beschreibe nur diesen Ausschnitt in 3 bis 5 Sätzen. Antworte nur mit einem JSON-Objekt:\n"
    '{{"description": "<Beschreibung des Ausschnitts>", '
    '"text_in_image": "<wörtliche Abschrift gut lesbaren Texts in diesem Ausschnitt, sonst leer>"}}'
)

MERGE_PROMPT = (
    "Die folgenden Texte beschreiben nacheinander überlappende Ausschnitte eines einzigen Panoramabilds, "
    "{direction}.\n" + RULES +
    "Fasse sie zu einer zusammenhängenden Beschreibung des ganzen Bildes zusammen (eine Szene, keine "
    "Aufzählung der Ausschnitte; was in mehreren Ausschnitten vorkommt, nur einmal). Führe die Abschriften "
    "zu einer zusammen, ohne Wiederholungen aus den Überlappungen.\n"
    "Antworte nur mit einem JSON-Objekt mit genau diesen Schlüsseln:\n"
    '{{"description": "<ausführliche Beschreibung>", "title": "<kurzer Titel aus wenigen Wörtern>", '
    '"text_in_image": "<zusammengeführte wörtliche Abschrift, sonst leer>"}}\n\n{parts}'
)


def place_hint(location: dict | None) -> str:
    """`Aufnahmeort laut GPS: <city>, <country>` (AK-19); empty without a place."""
    if not isinstance(location, dict):
        return ""
    parts = [str(location.get(k)).strip() for k in ("city", "country")
             if isinstance(location.get(k), str) and location.get(k).strip()]
    return f"\nAufnahmeort laut GPS (Hinweis): {', '.join(parts)}." if parts else ""


@dataclass
class Description:
    description: str
    title: str
    text: str
    model: str


class VisionUnavailable(TransientError):
    """Gateway not reachable, timeout, overloaded: failed attempt with backoff, plus a short pause."""


def parse_json(text: str) -> dict:
    text = _THINK.sub("", text or "").strip()
    text = _FENCE.sub("", text).strip()
    try:
        value = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise TransientError("Antwort des Vision-Modells ist kein JSON") from None
        try:
            value = json.loads(text[start:end + 1])
        except ValueError:
            raise TransientError("Antwort des Vision-Modells ist kein JSON") from None
    if not isinstance(value, dict):
        raise TransientError("Antwort des Vision-Modells ist kein JSON-Objekt")
    return {k.strip() if isinstance(k, str) else k: v for k, v in value.items()}


def _str(value) -> str:
    if isinstance(value, list):
        value = "\n".join(str(v) for v in value if v is not None)
    return value.strip() if isinstance(value, str) else ""


def clean_title(value: str) -> str:
    """One line, no en dash (it separates the place in the image title), at most TITLE_MAX chars."""
    t = " ".join(value.replace("–", "-").replace("—", "-").split()).strip(" \"'„“.#")
    if len(t) > TITLE_MAX:
        cut = t[:TITLE_MAX + 1]
        space = cut.rfind(" ")
        t = (cut[:space] if space > 0 else t[:TITLE_MAX]).rstrip(" -:;,.")
    return t


def clean_text(value: str) -> str:
    lines = [ln.rstrip() for ln in value.replace("\r\n", "\n").split("\n")]
    out = "\n".join(lines).strip("\n")
    return "" if out.strip().lower() in ("", "-", "keiner", "kein text", "none", "null", "leer") else out


class VisionClient:
    def __init__(self, base_url: str, key: str, model: str, timeout: float, max_tokens: int,
                 client: httpx.AsyncClient | None = None):
        self.model = model
        self.max_tokens = max_tokens
        self.headers = {"Authorization": f"Bearer {key}"} if key else {}
        self.http = client or httpx.AsyncClient(base_url=base_url, timeout=timeout)
        self.calls = 0

    async def close(self) -> None:
        await self.http.aclose()

    async def chat(self, content) -> tuple[str, str]:
        """(answer text, model name reported by the gateway)."""
        body = {"messages": [{"role": "user", "content": content}], "temperature": 0.3,
                "max_tokens": self.max_tokens, "stream": False, "response_format": {"type": "json_object"},
                # Hybrid-thinking models think by default: that would block the GPU slot per image (AK-18)
                "chat_template_kwargs": {"enable_thinking": False}}
        if self.model:
            body["model"] = self.model
        self.calls += 1
        try:
            r = await self.http.post("/v1/chat/completions", json=body, headers=self.headers)
        except httpx.TimeoutException as exc:
            raise VisionUnavailable(f"Zeitüberschreitung beim LLM-Gateway ({exc.__class__.__name__})") from exc
        except httpx.TransportError as exc:
            raise VisionUnavailable(f"LLM-Gateway nicht erreichbar ({exc.__class__.__name__})") from exc
        if r.status_code in (401, 403, 429) or r.status_code >= 500:
            raise VisionUnavailable(f"LLM-Gateway antwortet {r.status_code}")
        if r.status_code >= 400:
            raise TransientError(f"LLM-Gateway lehnt die Anfrage ab ({r.status_code}): {r.text[:300]}")
        try:
            data = r.json()
            text = data["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError):
            raise TransientError("Antwort des Gateways ohne Inhalt") from None
        if not text.strip():
            raise TransientError("Vision-Modell antwortet leer")
        model = data.get("model") if isinstance(data.get("model"), str) and data.get("model").strip() else ""
        return text, (model.strip() or self.model)

    @staticmethod
    def _image(prompt: str, jpeg_b64: str) -> list[dict]:
        return [{"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{jpeg_b64}"}}]

    async def describe(self, jpegs: list[str], landscape: bool, location: dict | None, progress=None) -> Description:
        hint = place_hint(location)
        if len(jpegs) == 1:
            text, model = await self.chat(self._image(SINGLE_PROMPT + hint, jpegs[0]))
            data = parse_json(text)
        else:
            direction = "von links nach rechts" if landscape else "von oben nach unten"
            parts = []
            for i, jpeg in enumerate(jpegs, start=1):
                if progress:
                    progress(f"Teilbild {i}/{len(jpegs)}")
                text, _ = await self.chat(self._image(TILE_PROMPT.format(i=i, n=len(jpegs), direction=direction)
                                                      + hint, jpeg))
                part = parse_json(text)
                desc = _str(part.get("description"))
                if len(desc) < MIN_DESCRIPTION_CHARS:
                    raise TransientError(f"Teilbild {i}: Beschreibung fehlt")
                parts.append((desc, clean_text(_str(part.get("text_in_image")))))
            listing = "\n\n".join(f"Ausschnitt {i}: {d}" + (f"\nText in Ausschnitt {i}:\n{t}" if t else "")
                                  for i, (d, t) in enumerate(parts, start=1))
            if progress:
                progress("Zusammenfassung")
            text, model = await self.chat(MERGE_PROMPT.format(direction=direction, parts=listing) + hint)
            data = parse_json(text)
        description = _str(data.get("description"))
        title = clean_title(_str(data.get("title")))
        if len(description) < MIN_DESCRIPTION_CHARS:
            raise TransientError("Antwort ohne brauchbare Beschreibung")
        if not title:
            raise TransientError("Antwort ohne Titel")
        return Description(description=description, title=title, text=clean_text(_str(data.get("text_in_image"))),
                           model=model)
