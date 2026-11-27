"""Title and content part."""
import importlib.util
import pathlib
import sys

from app import document

REGISTRY_MD = pathlib.Path(__file__).resolve().parents[2] / "alice-source-registry" / "app" / "markdown.py"


def test_title_format():  # AK-27
    prefix = document.time_prefix("2024-07-12T14:03:22", None, "Europe/Berlin")
    title = document.with_place(document.base_title(prefix, "Strand bei Sonnenuntergang"),
                                {"city": "Rimini", "country": "Italien"})
    assert title == "2024-07-12 14.03.22 Strand bei Sonnenuntergang – Rimini"


def test_title_from_modified_without_place():  # AK-28
    prefix = document.time_prefix(None, "2026-10-14T07:32:11+00:00", "Europe/Berlin")
    assert document.with_place(document.base_title(prefix, "Screenshot"), None) == "2026-10-14 09.32.11 Screenshot"


def test_place_suffix_country_and_replace():  # AK-29
    t = document.with_place("2024-07-12 14.03.22 Meer", {"city": None, "country": "Italien"})
    assert t == "2024-07-12 14.03.22 Meer – Italien"
    assert document.with_place(t, {"city": "Rimini"}) == "2024-07-12 14.03.22 Meer – Rimini"
    assert document.with_place(t, None) == "2024-07-12 14.03.22 Meer"


def test_taken_with_offset_keeps_camera_clock():
    assert document.time_prefix("2024-07-12T14:03:22+02:00", None, "UTC") == "2024-07-12 14.03.22"


def test_content_with_and_without_text():  # AK-20
    locs = [{"path": "/mnt/nas/fotos/IMG_1.jpg"}]
    with_text = document.content("Beschreibung.", "Strand\nRimini", locs)
    assert "## Text im Bild\n\n```text\nStrand\nRimini\n```" in with_text
    assert with_text.endswith("- Original: [IMG_1.jpg](</mnt/nas/fotos/IMG_1.jpg>)\n")
    without = document.content("Beschreibung.", "", locs)
    assert "Text im Bild" not in without


def test_hostile_text_keeps_markdown_valid():  # EC-8
    spec = importlib.util.spec_from_file_location("registry_markdown", REGISTRY_MD)
    md = importlib.util.module_from_spec(spec)
    sys.modules["registry_markdown"] = md
    spec.loader.exec_module(md)
    text = "---\ntitle: kaputt\n---\n```\n# Überschrift\n````"
    body = document.content("Beschreibung.", text, [{"path": "/mnt/nas/fotos/a.jpg"}])
    fm = {k: None for k in md.BASE_FIELDS} | {"id": "abcdefghijkl", "schema": 1, "kind": "image", "title": "T",
                                             "locations": [], "parents": [], "manual": []}
    parsed_fm, parsed_body = md.parse(md.render(fm, body))
    assert parsed_fm["title"] == "T" and parsed_fm["kind"] == "image"
    assert text in parsed_body and "`````text" in parsed_body
