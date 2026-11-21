"""Unit tests: slugs, paths, frontmatter parsing/validation (AK-4, AK-9, EC-1, EC-2, EC-10)."""
from datetime import datetime

import pytest

from app import markdown as md


def test_slug_umlauts_special_chars_and_length():
    assert md.slugify("Stromrechnung Stadtwerke Okt 2026") == "stromrechnung-stadtwerke-okt-2026"
    assert md.slugify("Größe/Übersicht: Äpfel & Öl") == "groesse-uebersicht-aepfel-oel"
    assert md.slugify("scan_0042.pdf") == "scan-0042-pdf"
    long = md.slugify("Sehr langer Titel " * 20)
    assert len(long) <= md.SLUG_MAX and not long.endswith("-")
    assert md.slugify("///") == "untitled"
    assert md.slugify("../../etc/passwd") == "etc-passwd"


def test_same_slug_different_ids_gives_unique_names():
    assert md.file_name("aaaaaaaaaaaa", "Rechnung") != md.file_name("bbbbbbbbbbbb", "Rechnung")


def test_rel_path_by_kind_year_month():
    p = md.rel_path("document", datetime(2026, 11, 3), "abcdefghijkl", "scan_0042.pdf")
    assert p == "documents/2026/11/abcdefghijkl-scan-0042-pdf.md"
    assert md.rel_path("audio", datetime(2025, 1, 9), "abcdefghijkl", "x").startswith("audio/2025/01/")


def _fm(**over):
    fm = {"id": "abcdefghijkl", "schema": 1, "kind": "document", "title": "T", "locations": [{"path": "/x"}],
          "parents": [], "hash": "h", "size": 1, "modified": None, "captured": "2026-11-01T00:00:00+00:00",
          "language": None, "type": None, "manual": []}
    fm.update(over)
    return fm


def test_render_parse_roundtrip_has_heading_and_no_state():
    text = md.render(_fm(title="Mein Titel"), "Inhalt\n")
    assert "\n# Mein Titel\n" in text
    fm, content = md.parse(text)
    assert fm["title"] == "Mein Titel" and content == "Inhalt\n"
    for forbidden in ("state", "attempts", "error", "retry"):
        assert forbidden not in fm
    assert list(fm)[:len(md.BASE_FIELDS)] == list(md.BASE_FIELDS)


@pytest.mark.parametrize("text,needle", [
    ("kein frontmatter", "Frontmatter fehlt"),
    ("---\nid: [unclosed\n---\n", "kein gültiges YAML"),
    ("---\nid: x\n", "nicht abgeschlossen"),
    ("---\n- a\n- b\n---\n", "YAML-Objekt"),
])
def test_parse_rejects_broken_frontmatter(text, needle):
    with pytest.raises(md.InvalidDocument, match=needle):
        md.parse(text)


@pytest.mark.parametrize("over,needle", [
    ({"id": "zzzzzzzzzzzz"}, "'id'"),
    ({"kind": "image"}, "'kind'"),
    ({"title": ""}, "'title'"),
    ({"manual": "title"}, "'manual'"),
    ({"schema": 99}, "'schema'"),
])
def test_validate_rejects(over, needle):
    with pytest.raises(md.InvalidDocument, match=needle):
        md.validate(_fm(**over), source_id="abcdefghijkl", kind="document")


def test_validate_missing_field():
    fm = _fm()
    del fm["hash"]
    with pytest.raises(md.InvalidDocument, match="Pflichtfeld fehlt: hash"):
        md.validate(fm, source_id="abcdefghijkl", kind="document")


def test_validate_accepts_extension_fields():
    md.validate(_fm(amount=12.5, vendor="X"), source_id="abcdefghijkl", kind="document")


def test_multiline_title_keeps_content_intact():
    text = md.render(_fm(title="Zeile 1\nZeile 2"), "Inhalt\n")
    fm, content = md.parse(text)
    assert fm["title"] == "Zeile 1\nZeile 2" and content == "Inhalt\n"
    assert "\n# Zeile 1 Zeile 2\n" in text
