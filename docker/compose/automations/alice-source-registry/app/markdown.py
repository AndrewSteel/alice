"""Source markdown: frontmatter schema, parsing, validation, rendering, slugs."""
from __future__ import annotations

import posixpath
import re
import unicodedata
from datetime import date, datetime

import yaml

SCHEMA_VERSION = 1
KIND_DIRS = {"document": "documents", "image": "images", "email": "emails", "audio": "audio", "video": "video"}
KINDS = tuple(KIND_DIRS)
BASE_FIELDS = ("id", "schema", "kind", "title", "locations", "parents", "hash", "size", "modified",
               "captured", "language", "type", "manual")
# Fields owned by the register; stages cannot set them through a document write.
REGISTER_FIELDS = ("id", "schema", "kind", "locations", "parents", "hash", "size", "modified", "captured", "deleted")
# Register fields the pipeline always sets, even if a human listed them in `manual`.
ALWAYS_REGISTER = ("id", "kind", "schema", "deleted")
# Register fields that reset only stages naming them in resets_on_fields (PROJ-119).
META_FIELDS = ("locations", "deleted")
# Markdowns of deleted sources live below this folder with the same sub-structure (PROJ-116).
DELETED_DIR = "deleted"
WATCH_DIRS = (*KIND_DIRS.values(), DELETED_DIR)
CONTENT = "content"  # name of the markdown body in `manual`
SLUG_MAX = 60
_UMLAUTS = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}


class InvalidDocument(Exception):
    """Frontmatter cannot be accepted; the message is shown to humans."""


def slugify(title: str) -> str:
    text = "".join(_UMLAUTS.get(c, c) for c in str(title))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    text = text[:SLUG_MAX].rstrip("-")
    return text or "untitled"


def file_name(source_id: str, title: str) -> str:
    return f"{source_id}-{slugify(title)}.md"


def rel_path(kind: str, captured: datetime, source_id: str, title: str) -> str:
    return f"{KIND_DIRS[kind]}/{captured:%Y}/{captured:%m}/{file_name(source_id, title)}"


def is_deleted_path(path: str) -> bool:
    return path.startswith(DELETED_DIR + "/")


def regular_path(path: str) -> str:
    """Path of the markdown outside deleted/."""
    return path[len(DELETED_DIR) + 1:] if is_deleted_path(path) else path


def deleted_path(path: str) -> str:
    return f"{DELETED_DIR}/{regular_path(path)}"


def sibling_path(path: str, source_id: str, title: str) -> str:
    """Same folder, name rebuilt from the title."""
    return posixpath.join(posixpath.dirname(path), file_name(source_id, title))


def _plain(value):
    """YAML may load timestamps as datetime objects; keep everything as plain strings."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def parse(text: str) -> tuple[dict, str]:
    """(frontmatter, content). The `# title` heading is generated and not part of the content."""
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise InvalidDocument("Frontmatter fehlt (Datei muss mit '---' beginnen)")
    end = text.find("\n---", 3)
    if end < 0 or text[end + 4:end + 5] not in ("", "\n"):
        raise InvalidDocument("Frontmatter ist nicht abgeschlossen (zweites '---' fehlt)")
    try:
        fm = yaml.safe_load(text[4:end + 1])
    except yaml.YAMLError as exc:
        raise InvalidDocument(f"Frontmatter ist kein gültiges YAML: {str(exc).splitlines()[0]}") from None
    if not isinstance(fm, dict):
        raise InvalidDocument("Frontmatter ist kein YAML-Objekt mit Feldern")
    body = text[end + 5:].lstrip("\n")
    if body.startswith("# "):
        body = body.split("\n", 1)[1] if "\n" in body else ""
    return _plain(fm), normalize_content(body)


def normalize_content(content: str | None) -> str:
    content = (content or "").replace("\r\n", "\n").strip("\n")
    return content + "\n" if content else ""


def changed_parts(key: str, old, new) -> list[str]:
    """`manual` entries for a changed frontmatter field. In a block (both values are objects, e.g.
    `fields`) each changed inner field counts on its own: `fields.amount_gross` (PROJ-118)."""
    if isinstance(old, dict) and isinstance(new, dict):
        return [f"{key}.{k}" for k in sorted(set(old) | set(new), key=str)
                if k not in old or k not in new or old[k] != new[k]]
    return [key]


def keep_manual_parts(key: str, value, old, manual: list[str]):
    """Value a stage writes for `key`, keeping inner fields listed in `manual` as `<key>.<field>`."""
    parts = [m[len(key) + 1:] for m in manual if m.startswith(key + ".")]
    if not parts or not isinstance(value, dict) or not isinstance(old, dict):
        return value
    value = dict(value)
    for part in parts:
        if part in old:
            value[part] = old[part]
    return value


def frontmatter_id(text: str) -> str | None:
    try:
        fm, _ = parse(text)
    except InvalidDocument:
        return None
    value = fm.get("id")
    return value if isinstance(value, str) else None


def validate(fm: dict, *, source_id: str, kind: str) -> None:
    missing = [f for f in BASE_FIELDS if f not in fm]
    if missing:
        raise InvalidDocument(f"Pflichtfeld fehlt: {', '.join(missing)}")
    if fm["id"] != source_id:
        raise InvalidDocument(f"Feld 'id' darf nicht geändert werden (erwartet {source_id})")
    if fm["kind"] != kind:
        raise InvalidDocument(f"Feld 'kind' darf nicht geändert werden (erwartet {kind})")
    schema = fm["schema"]
    if isinstance(schema, bool) or not isinstance(schema, int) or not 1 <= schema <= SCHEMA_VERSION:
        raise InvalidDocument(f"Feld 'schema' muss eine Zahl von 1 bis {SCHEMA_VERSION} sein")
    if not isinstance(fm["title"], str) or not fm["title"].strip():
        raise InvalidDocument("Feld 'title' muss ein nicht leerer Text sein")
    for name in ("locations", "parents", "manual"):
        if not isinstance(fm[name], list):
            raise InvalidDocument(f"Feld '{name}' muss eine Liste sein")
    if not all(isinstance(m, str) for m in fm["manual"]):
        raise InvalidDocument("Feld 'manual' darf nur Feldnamen enthalten")


def order(fm: dict) -> dict:
    """Base fields first in schema order, then extension fields."""
    out = {k: fm.get(k) for k in BASE_FIELDS}
    out.update({k: v for k, v in fm.items() if k not in out})
    return out


def render(fm: dict, content: str) -> str:
    fm = order(fm)
    head = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, default_flow_style=False, width=1000)
    content = normalize_content(content)
    heading = " ".join(str(fm["title"]).split())  # one line, even if the title has line breaks
    return f"---\n{head}---\n\n# {heading}\n" + (f"\n{content}" if content else "")


def original_links(locations: list[dict]) -> str:
    """Content of a source without extracted text: links to its originals."""
    lines = []
    for loc in locations:
        if loc.get("path"):
            lines.append(f"- Original: [{posixpath.basename(loc['path'])}](<{loc['path']}>)")
        elif loc.get("mailbox"):
            lines.append(f"- Original: Postfach {loc['mailbox']}, Message-ID {loc['message_id']}")
    return normalize_content("\n".join(lines))


README = """# Quelle der Wahrheit

Dieser Ordner wird von Alice (Dienst `alice-source-registry`) verwaltet. Jede Quelle
(Dokument, Bild, Mail, Audio, Video) hat hier genau eine Markdown-Datei. Originale bleiben
unverändert an ihrem Ort. Datenbank, Suche (RAG) und Wiki werden aus diesen Dateien abgeleitet.

## Ordnerstruktur

```
documents/<JJJJ>/<MM>/<id>-<slug>.md
images/<JJJJ>/<MM>/<id>-<slug>.md
emails/<JJJJ>/<MM>/<id>-<slug>.md
audio/<JJJJ>/<MM>/<id>-<slug>.md
video/<JJJJ>/<MM>/<id>-<slug>.md
```

- `<JJJJ>/<MM>`: Zeitpunkt der ersten Erfassung (bei Mails das Mail-Datum). Ändert sich nie.
- `<id>`: stabile, unveränderliche Kennung der Quelle. Alle Verweise laufen über die `id`.
- `<slug>`: aus dem Titel gebildet (Kleinbuchstaben, Umlaute als ae/oe/ue/ss, höchstens 60 Zeichen).
  Ändert sich der Titel, wird die Datei umbenannt; der Ordner bleibt gleich.
- Wird ein Original verschoben oder umbenannt, ändern sich nur die Fundorte (`locations`),
  nicht Ort oder Name der Markdown-Datei.
- `deleted/<art>/<JJJJ>/<MM>/`: Markdowns gelöschter Quellen (kein Original mehr vorhanden), mit
  `deleted: <Zeitpunkt>` im Frontmatter. Taucht das Original wieder auf, wandert die Datei zurück.
  Dateien unter `deleted/` dürfen von Hand gelöscht werden.

## Frontmatter (Schema 1)

| Feld | Inhalt |
|---|---|
| `id` | stabile, unveränderliche ID (nicht ändern) |
| `schema` | Versionsnummer des Frontmatter-Formats |
| `kind` | `document` / `image` / `email` / `audio` / `video` (nicht ändern) |
| `title` | lesbarer Titel, steht auch als Überschrift im Markdown |
| `locations` | Fundorte des Originals (Pfad bzw. Postfach + Message-ID) |
| `parents` | IDs der Mails, an denen die Quelle als Anhang hängt |
| `hash` | Hash des Originals |
| `size` | Größe des Originals in Bytes |
| `modified` | Änderungszeit des Originals |
| `captured` | Zeitpunkt der ersten Erfassung |
| `language` | Sprache des Inhalts (leer bis zur Extraktion) |
| `type` | Dokumenttyp (leer bis zur Klassifizierung) |
| `manual` | von Hand gesetzte Felder; `content` steht für den Inhaltsteil |
| `deleted` | nur bei gelöschten Quellen: Zeitpunkt, seit dem kein Original mehr vorhanden ist |

Spätere Stufen ergänzen weitere Felder. Verarbeitungszustand, Fehler und Wiederholungen
stehen nicht hier, sondern im Register (Datenbank).

## Hand-Korrekturen

- Dateien dürfen direkt hier bearbeitet werden (Editor genügt, ein eigener Git-Commit ist nicht nötig).
- Jede Änderung, die nicht von der Pipeline stammt, wird spätestens nach 5 Minuten erkannt und
  als Hand-Korrektur committet (Autor „Alice Hand-Korrektur" bzw. der eigene Commit bleibt erhalten).
- Geänderte Felder und ein geänderter Inhaltsteil (`content`) werden in `manual` eingetragen.
  Die Pipeline überschreibt diese Felder danach nie wieder, auch nicht bei einem Neuaufbau.
- In Blöcken wie `fields` zählt jedes Feld einzeln (`fields.amount_gross`); nur dieses Feld ist dann
  geschützt. Ein Eintrag `fields` schützt den ganzen Block.
- Wer einen Eintrag aus `manual` entfernt, gibt das Feld wieder für die Pipeline frei.
- Ungültiges Frontmatter (kein gültiges YAML, fehlendes Pflichtfeld, geänderte `id` oder `kind`)
  wird nicht übernommen. Die Datei wird dann nicht überschrieben, bis sie repariert ist; der
  Fehler steht im Register.
- Umbenennen oder Verschieben einer Datei ist keine Korrektur: Sie wird an ihren Ort zurückgelegt.
  Gelöschte Dateien werden aus Git wiederhergestellt (Löschen läuft über das Original).
  Ausnahme: Dateien unter `deleted/` dürfen gelöscht werden; das wird übernommen.

## Commits

- Pipeline: Autor „Alice ETL", ein Commit je Quelle und Stufe (`<stufe>: <id> <titel>`),
  bei Massenläufen Sammel-Commits (`rebuild: <stufe> <anzahl> sources`).
- Jede Änderung lässt sich mit Git einzeln nachvollziehen und zurücknehmen.
"""
