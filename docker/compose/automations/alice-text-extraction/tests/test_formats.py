"""Readers: PDF (text layer + OCR per page), Office via a fake converter, csv/txt/md, text helpers."""
import os
import shutil
import stat
import zipfile

import pytest

from app.errors import PermanentError, TransientError
from app.extractor import Extractor
from app.formats import office
from app.text import clean_ocr_text, decode_text, detect_language, md_table, text_layer_usable

from .conftest import FakeOcr, make_pdf, write

DE = ("Die Stadtwerke teilen Ihnen mit, dass der Abschlag für Strom und Gas ab dem nächsten Monat angepasst wird. "
      "Bitte prüfen Sie die beigefügte Rechnung und überweisen Sie den offenen Betrag bis zum Monatsende auf das "
      "bekannte Konto. Bei Fragen erreichen Sie unseren Kundendienst werktags zwischen acht und achtzehn Uhr.")
EN = ("The insurance company informs you that your policy will be renewed automatically next month. Please review "
      "the attached statement and contact our customer service if any of the listed details are incorrect or have "
      "changed since your last renewal. We are available on weekdays between eight and six.")


# ---------------------------------------------------------------- PDF
def test_pdf_pages_text(tmp_path, extractor, ocr):  # AK-5
    pages = [f"Seite {i} Inhalt: " + DE for i in range(1, 4)]
    path = make_pdf(tmp_path / "a.pdf", pages)
    r = extractor.extract(path)
    md = r.markdown()
    assert [s.heading for s in r.sections] == ["Seite 1", "Seite 2", "Seite 3"]
    assert md.index("## Seite 1") < md.index("## Seite 2") < md.index("## Seite 3")
    assert "Seite 2 Inhalt: Die Stadtwerke" in md.replace("\n", " ")
    assert r.method == "text" and r.ocr_pages == [] and ocr.calls == []


def test_pdf_long_text_not_cut(tmp_path, extractor):  # AK-6
    words = [f"Wort{i:05d}" for i in range(9000)]  # > 50,000 characters
    chunk = 1500
    pages = [" ".join(words[i:i + chunk]) for i in range(0, len(words), chunk)]
    path = make_pdf(tmp_path / "long.pdf", pages)
    md = extractor.extract(path).markdown()
    found = sum(1 for w in words if w in md)
    assert found == len(words) and len(md) > 50000
    assert "gekürzt" not in md and "truncated" not in md.lower()


def test_pdf_mixed_ocr_only_scanned_pages(tmp_path, extractor, ocr):  # AK-7, EC-2
    pages = [DE, ("scan",), EN, ("scan",), ("both", "Textebene gewinnt auf dieser Seite mit Bild")]
    path = make_pdf(tmp_path / "mixed.pdf", pages)
    r = extractor.extract(path)
    assert ocr.calls == [2, 4]  # only the pages without text layer
    assert r.method == "mixed" and r.ocr_pages == [2, 4]
    assert all(s.body.strip() for s in r.sections) and len(r.sections) == 5
    assert "Gescannter Text der Seite 4" in r.markdown()
    assert "Textebene gewinnt" in r.sections[4].body


def test_pdf_fully_scanned_cleaned(tmp_path, settings):  # AK-8
    ocr = FakeOcr(text="Rech-\nnung Nr. {n}\x0c\x07 vom Okto-\nber\n\n\n\nnnnnnnnnn Betrag")
    path = make_pdf(tmp_path / "scan.pdf", [("scan",)] * 3)
    r = Extractor(settings, ocr=ocr).extract(path)
    assert r.method == "ocr" and r.ocr_pages == [1, 2, 3] and ocr.calls == [1, 2, 3]
    body = r.sections[0].body
    assert "Rechnung Nr. 1" in body and "Oktober" in body
    assert "\x0c" not in body and "\x07" not in body and "nnnnn" not in body and "\n\n\n" not in body


def test_pdf_empty_pages_keep_numbers(tmp_path, extractor, ocr):  # AK-16
    path = make_pdf(tmp_path / "gaps.pdf", [DE, None, None, EN])
    r = extractor.extract(path)
    md = r.markdown()
    assert "## Seite 1" in md and "## Seite 4" in md
    assert "## Seite 2" not in md and "## Seite 3" not in md
    assert ocr.calls == [] and r.method == "text"


def test_pdf_single_page_without_marker(tmp_path, extractor):
    r = extractor.extract(make_pdf(tmp_path / "one.pdf", [DE]))
    assert "## Seite" not in r.markdown() and "Stadtwerke" in r.markdown()


def test_pdf_only_empty_pages(tmp_path, extractor):  # AK-20
    r = extractor.extract(make_pdf(tmp_path / "blank.pdf", [None, None]))
    assert r.empty and r.markdown() == ""


def test_pdf_ocr_without_result(tmp_path, settings):  # AK-20 (OCR finds nothing)
    r = Extractor(settings, ocr=FakeOcr(text="  \n")).extract(make_pdf(tmp_path / "s.pdf", [("scan",)]))
    assert r.empty and r.method == "ocr" and r.ocr_pages == []


def test_pdf_password(tmp_path, extractor):  # AK-21
    path = make_pdf(tmp_path / "secret.pdf", [DE], password="geheim")
    with pytest.raises(PermanentError, match="passwortgeschützt"):
        extractor.extract(path)


def test_pdf_truncated(tmp_path, extractor):  # AK-22
    path = make_pdf(tmp_path / "full.pdf", [DE, EN, DE])
    data = open(path, "rb").read()
    cut = write(tmp_path / "cut.pdf", data[: len(data) // 2])
    with pytest.raises(PermanentError, match="abgeschnitten"):
        extractor.extract(cut)


def test_pdf_garbage(tmp_path, extractor):  # AK-22, EC-6
    with pytest.raises(PermanentError):
        extractor.extract(write(tmp_path / "x.pdf", b"PK\x03\x04 not a pdf at all"))
    with pytest.raises(PermanentError, match="beschädigt"):
        extractor.extract(write(tmp_path / "y.pdf", b"%PDF-1.7\n garbage garbage\n%%EOF\n"))


def test_pdf_ocr_timeout_is_transient(tmp_path, settings):  # AK-23
    path = make_pdf(tmp_path / "s.pdf", [("scan",), ("scan",)])
    with pytest.raises(TransientError, match="Zeitüberschreitung"):
        Extractor(settings, ocr=FakeOcr(fail_on=2)).extract(path)


def test_text_layer_quality():  # EC-1
    assert text_layer_usable(DE, 10, 0.6)
    assert not text_layer_usable("", 10, 0.6)
    assert not text_layer_usable("�" * 50 + " ab", 10, 0.6)
    assert not text_layer_usable(" " * 30 + "abc def ghij klm", 10, 0.6)


def test_size_limit(tmp_path, settings, ocr):  # AK-26
    settings.max_file_mb = 0.001
    path = write(tmp_path / "big.txt", "x" * 5000)
    with pytest.raises(PermanentError, match=r"Datei zu groß \(0 MB, Grenze 0.001 MB\)"):
        Extractor(settings, ocr=ocr).extract(path)


def test_unsupported_extension(tmp_path, extractor):
    with pytest.raises(PermanentError, match="nicht unterstützt"):
        extractor.extract(write(tmp_path / "a.pages", b"x"))


# ---------------------------------------------------------------- csv / txt / md
def test_csv_semicolon_latin1(tmp_path, extractor):  # AK-13
    data = "Name;Ort;Betrag\nMüller;Köln;12,50\nGrößer;Düsseldorf;3\n".encode("latin-1")
    md = extractor.extract(write(tmp_path / "a.csv", data)).markdown()
    assert md.splitlines() == ["| Name | Ort | Betrag |", "|---|---|---|", "| Müller | Köln | 12,50 |",
                               "| Größer | Düsseldorf | 3 |"]


def test_csv_comma_utf8_quoted(tmp_path, extractor):
    md = extractor.extract(write(tmp_path / "b.csv", 'a,b\n"x, y","z|w"\n')).markdown()
    assert "| x, y | z\\|w |" in md


@pytest.mark.parametrize("enc", ["utf-8", "utf-8-sig", "latin-1"])
@pytest.mark.parametrize("ext", ["txt", "md"])
def test_txt_md_encodings(tmp_path, extractor, enc, ext):  # AK-15
    text = "# Notiz\n\nÄpfel, Öl und Übermaß – Straße\n" + "Zeile\n" * 3000
    if enc == "latin-1":
        text = text.replace("–", "-")
    r = extractor.extract(write(tmp_path / f"n.{ext}", text.encode(enc)))
    md = r.markdown()
    assert "Äpfel, Öl und Übermaß" in md and "Straße" in md and md.count("Zeile") == 3000
    assert "## Seite" not in md and r.method == "text"


def test_binary_with_txt_extension(tmp_path, extractor):  # EC-6
    path = make_pdf(tmp_path / "real.pdf", [DE])
    fake = shutil.copy(path, tmp_path / "fake.txt")
    data = open(fake, "rb").read()
    if b"\x00" not in data:
        write(fake, data + b"\x00")
    with pytest.raises(PermanentError, match="keine Textdatei"):
        extractor.extract(str(fake))


def test_empty_txt(tmp_path, extractor):  # AK-20
    assert extractor.extract(write(tmp_path / "e.txt", b"")).empty


def test_md_table_escaping():  # EC-3, EC-7
    long = "x" * 5000
    t = md_table([["a", "b"], ["1|2", "line1\nline2"], [long, None]])
    assert "1\\|2" in t and "line1<br>line2" in t and long in t
    assert md_table([[None, ""]]) == ""


def test_decode_fallback():
    assert decode_text("Grüße".encode("cp1252"), "txt") == "Grüße"
    assert decode_text("Preis 5 €".encode("cp1252"), "txt") == "Preis 5 €"


def test_clean_ocr_dehyphenation():
    assert clean_ocr_text("Rech-\nnung") == "Rechnung"
    # "Ein- und Ausgaben", or a break before a capitalised word, stays as it is
    assert clean_ocr_text("Ein- und\nAus-\nGaben") == "Ein- und\nAus-\nGaben"


def test_language():  # AK-18, EC-12
    assert detect_language(DE, 100) == "de"
    assert detect_language(EN, 100) == "en"
    assert detect_language("Rechnung 2024", 100) is None
    assert detect_language("", 100) is None


# ---------------------------------------------------------------- Office (fake converter)
HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>t</title><style>p{}</style></head><body>
<h1 class="x">Mietvertrag</h1><p>Erster <b>Absatz</b> mit&nbsp;Text.</p><p>Zweiter<br>Absatz</p>
<h2>Kosten</h2><table border="1"><tr><td><p>Posten</p></td><td><p>Betrag</p></td></tr>
<tr><td><p>Miete</p></td><td><p>800 €</p></td></tr></table><ul><li>Punkt eins</li><li>Punkt zwei</li></ul>
</body></html>"""


def fake_converter(files: dict[str, str]):
    """Converter double: returns a prepared file per target and records the calls."""
    calls = []

    def convert(path, target, timeout):
        calls.append((os.path.basename(path), target))
        return files[target]

    convert.calls = calls
    return lambda: convert, calls


def make_docx_zip(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document/>")
    return str(path)


def make_xlsx(path):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Umsätze"
    ws.append(["Monat", "Betrag", "Notiz"])
    ws.append(["Januar", 1200.0, "x" * 3000])
    ws.append(["Februar", 950.5, None])
    ws["A10"] = None
    hidden = wb.create_sheet("Geheim")
    hidden.sheet_state = "hidden"
    hidden.append(["Wert", 42])
    wb.save(path)
    return str(path)


def make_pptx(path):
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[1])
    s1.shapes.title.text = "Projektstart"
    s1.placeholders[1].text = "Ziele\nZeitplan"
    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    s2.shapes.title.text = "Budget"
    table = s2.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(4), Inches(1)).table
    for (r, c), v in {(0, 0): "Posten", (0, 1): "Euro", (1, 0): "Hardware", (1, 1): "5000"}.items():
        table.cell(r, c).text = v
    s3 = prs.slides.add_slide(prs.slide_layouts[5])
    s3.shapes.title.text = "Fazit"
    s3.notes_slide.notes_text_frame.text = "Hier auf die Risiken eingehen"
    prs.slides.add_slide(prs.slide_layouts[6])  # empty slide
    prs.save(path)
    return str(path)


def test_docx_via_html(tmp_path, settings, ocr):  # AK-9
    html = write(tmp_path / "out.html", HTML)
    factory, calls = fake_converter({"html": html})
    for ext in ("docx", "odt", "doc", "rtf"):
        src = tmp_path / f"vertrag.{ext}"
        if ext == "doc":
            write(src, office.OLE_MAGIC + b"\x00" * 100)
        elif ext == "rtf":
            write(src, b"{\\rtf1 x}")
        else:
            make_docx_zip(src)
        md = Extractor(settings, ocr=ocr, converter_factory=factory).extract(str(src)).markdown()
        assert md.split("\n\n")[:3] == ["## Mietvertrag", "Erster Absatz mit Text.", "Zweiter\nAbsatz"]
        assert "### Kosten" in md and "| Posten | Betrag |\n|---|---|\n| Miete | 800 € |" in md
        assert "- Punkt eins\n\n- Punkt zwei" in md or "- Punkt eins\n- Punkt zwei" in md
    assert [c[1] for c in calls] == ["html"] * 4


def test_sheets(tmp_path, settings, ocr):  # AK-10, EC-3, EC-5
    xlsx = make_xlsx(tmp_path / "conv.xlsx")
    factory, calls = fake_converter({"xlsx": xlsx})
    src = make_docx_zip(tmp_path / "tabelle.ods")
    r = Extractor(settings, ocr=ocr, converter_factory=factory).extract(src)
    md = r.markdown()
    assert [s.heading for s in r.sections] == ["Blatt Umsätze", "Blatt Geheim"]
    assert "| Monat | Betrag | Notiz |" in md and "| Januar | 1200 | " + "x" * 3000 + " |" in md
    assert "| Februar | 950.5 |  |" in md and "| Wert | 42 |" in md
    assert calls[0][1] == "xlsx"


def test_slides(tmp_path, settings, ocr):  # AK-11
    pptx = make_pptx(tmp_path / "conv.pptx")
    factory, _ = fake_converter({"pptx": pptx})
    src = make_docx_zip(tmp_path / "vortrag.odp")
    r = Extractor(settings, ocr=ocr, converter_factory=factory).extract(src)
    md = r.markdown()
    assert [s.heading for s in r.sections] == ["Folie 1", "Folie 2", "Folie 3", "Folie 4"]
    assert "## Folie 4" not in md  # empty slide: no section, numbering kept
    assert "Projektstart" in md and "Ziele\nZeitplan" in md
    assert "| Posten | Euro |\n|---|---|\n| Hardware | 5000 |" in md
    folie3 = md[md.index("## Folie 3"):]
    assert "Fazit" in folie3 and "### Notizen\n\nHier auf die Risiken eingehen" in folie3


def test_office_precheck(tmp_path, extractor):  # AK-21, AK-22
    with pytest.raises(PermanentError, match="beschädigt"):
        extractor.extract(write(tmp_path / "a.docx", b"PK\x03\x04garbage"))
    data = open(make_docx_zip(tmp_path / "ok.docx"), "rb").read()
    with pytest.raises(PermanentError, match="beschädigt"):
        extractor.extract(write(tmp_path / "cut.docx", data[:-30]))
    enc = office.OLE_MAGIC + b"\x00" * 64 + office.ENCRYPTED_PACKAGE + b"\x00" * 64
    with pytest.raises(PermanentError, match="passwortgeschützt"):
        extractor.extract(write(tmp_path / "p.xlsx", enc))
    odt = tmp_path / "p.odt"
    with zipfile.ZipFile(odt, "w") as z:
        z.writestr("META-INF/manifest.xml", "<manifest:encryption-data/>")
    with pytest.raises(PermanentError, match="passwortgeschützt"):
        extractor.extract(str(odt))
    with pytest.raises(PermanentError, match="beschädigt"):
        extractor.extract(write(tmp_path / "x.doc", b"not an ole file"))


# ---------------------------------------------------------------- group from the content (not the extension)
def make_ole(path, root_streams, storage=None):
    """Minimal OLE compound file (512-byte sectors): the given empty streams below the root,
    optionally one sub-storage (embedded object) with its own streams."""
    import struct

    free, eoc, fatsect, nostream = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFF

    def entry(name, kind, right=nostream, child=nostream):
        raw = name.encode("utf-16-le") + b"\0\0"
        return (raw.ljust(64, b"\0") + struct.pack("<HBB", len(raw), kind, 1)
                + struct.pack("<III", nostream, right, child) + b"\0" * 36 + struct.pack("<IQ", eoc, 0))

    names = list(root_streams) + ([storage[0]] if storage else [])
    entries = [entry("Root Entry", 5, child=1)]
    sub_first = len(names) + 1
    for i, name in enumerate(names, start=1):  # siblings as a chain of right links
        right = i + 1 if i < len(names) else nostream
        if storage and name == storage[0]:
            entries.append(entry(name, 1, right, sub_first))
        else:
            entries.append(entry(name, 2, right))
    for j, name in enumerate(storage[1] if storage else []):
        last = j == len(storage[1]) - 1
        entries.append(entry(name, 2, nostream if last else sub_first + j + 1))
    dir_bytes = b"".join(entries)
    dir_sectors = (len(dir_bytes) + 511) // 512
    dir_bytes = dir_bytes.ljust(dir_sectors * 512, b"\0")
    fat = [fatsect] + [i + 1 for i in range(1, dir_sectors)] + [eoc]  # directory chain from sector 1
    fat = struct.pack("<128I", *(fat + [free] * (128 - len(fat))))
    header = (office.OLE_MAGIC + b"\0" * 16 + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + b"\0" * 10
              + struct.pack("<IIII", 1, 1, 0, 4096) + struct.pack("<IIII", eoc, 0, eoc, 0)
              + struct.pack("<109I", 0, *([free] * 108)))
    assert len(header) == 512
    write(path, header + fat + dir_bytes)
    return str(path)


def make_ods_zip(path, mimetype):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", mimetype)
        z.writestr("content.xml", "<office:document-content/>")
    return str(path)


def test_content_group_markers(tmp_path):
    ods = "application/vnd.oasis.opendocument.spreadsheet"
    assert office.content_group(make_ods_zip(tmp_path / "a.odt", ods)) == "sheet"
    assert office.content_group(make_ods_zip(tmp_path / "b.ods", ods + "-template")) == "sheet"
    assert office.content_group(make_ods_zip(tmp_path / "c.odt", "application/vnd.oasis.opendocument.text")) == "text"
    assert office.content_group(make_ods_zip(tmp_path / "d.odp",
                                             "application/vnd.oasis.opendocument.presentation")) == "slide"
    assert office.content_group(make_xlsx(tmp_path / "e.docx")) == "sheet"
    assert office.content_group(make_pptx(tmp_path / "f.docx")) == "slide"
    assert office.content_group(make_ole(tmp_path / "g.doc", ["Workbook", "SummaryInformation"])) == "sheet"
    assert office.content_group(make_ole(tmp_path / "h.xls", ["Book"])) == "sheet"
    assert office.content_group(make_ole(tmp_path / "i.doc", ["1Table", "WordDocument"])) == "text"
    assert office.content_group(make_ole(tmp_path / "j.ppt", ["Current User", "PowerPoint Document"])) == "slide"
    # a Word document with an embedded spreadsheet: only streams below the root count
    assert office.content_group(make_ole(tmp_path / "k.doc", ["WordDocument", "1Table"],
                                         ("ObjectPool", ["Workbook"]))) == "text"
    # no readable marker: None, the extension decides
    assert office.content_group(make_docx_zip(tmp_path / "l.docx")) is None
    assert office.content_group(write(tmp_path / "m.doc", office.OLE_MAGIC + b"\x00" * 100)) is None
    assert office.content_group(make_ole(tmp_path / "n.doc", ["Other"])) is None
    assert office.content_group(write(tmp_path / "o.docx", b"PK\x03\x04garbage")) is None
    assert office.content_group(write(tmp_path / "p.rtf", b"{\\rtf1 x}")) is None


@pytest.mark.parametrize("name,make,target", [
    ("terrasse.odt", lambda p: make_ods_zip(p, "application/vnd.oasis.opendocument.spreadsheet"), "xlsx"),
    ("tabelle.docx", make_xlsx, "xlsx"),
    ("tabelle.doc", lambda p: make_ole(p, ["Workbook"]), "xlsx"),
    ("vortrag.xlsx", make_pptx, "pptx"),
    ("brief.ppt", lambda p: make_ole(p, ["WordDocument"]), "html"),
])
def test_group_from_content_wins(tmp_path, settings, ocr, caplog, name, make, target):
    files = {"xlsx": make_xlsx(tmp_path / "conv.xlsx"), "pptx": make_pptx(tmp_path / "conv.pptx"),
             "html": write(tmp_path / "out.html", HTML)}
    factory, calls = fake_converter(files)
    src = make(tmp_path / "nas" / name)
    token = office.source_id.set("src-42")
    try:
        r = Extractor(settings, ocr=ocr, converter_factory=factory).extract(src)
    finally:
        office.source_id.reset(token)
    assert [c[1] for c in calls] == [target]
    if target == "xlsx":
        assert [s.heading for s in r.sections] == ["Blatt Umsätze", "Blatt Geheim"]
    warning = next(rec.getMessage() for rec in caplog.records if rec.levelname == "WARNING")
    ext = name.rsplit(".", 1)[1]
    group = {"xlsx": "sheet", "pptx": "slide", "html": "text"}[target]
    assert warning == (f"Source src-42: content is a {group} document although the extension is .{ext}; "
                       f"extracting as {group}")
    assert str(tmp_path) not in caplog.text  # no NAS path in the log


def test_group_matching_extension_unchanged(tmp_path, settings, ocr, caplog):
    files = {"xlsx": make_xlsx(tmp_path / "conv.xlsx"), "pptx": make_pptx(tmp_path / "conv.pptx"),
             "html": write(tmp_path / "out.html", HTML)}
    factory, calls = fake_converter(files)
    for name, make in (("a.ods", lambda p: make_ods_zip(p, "application/vnd.oasis.opendocument.spreadsheet")),
                       ("b.xlsx", make_xlsx), ("c.pptx", make_pptx), ("d.doc", lambda p: make_ole(p, ["WordDocument"])),
                       ("e.xls", lambda p: make_ole(p, ["Workbook"])), ("f.pps", lambda p: make_ole(p, ["PowerPoint Document"])),
                       ("g.ott", lambda p: make_ods_zip(p, "application/vnd.oasis.opendocument.text-template"))):
        Extractor(settings, ocr=ocr, converter_factory=factory).extract(make(tmp_path / name))
    assert [c[1] for c in calls] == ["xlsx", "xlsx", "pptx", "html", "xlsx", "pptx", "html"]
    assert not [rec for rec in caplog.records if rec.levelname == "WARNING"]


def test_precheck_unchanged_for_wrong_family(tmp_path, extractor):
    # a zip file named .doc is still rejected by the precheck, content detection does not bypass it
    with pytest.raises(PermanentError, match="keine gültige .doc-Datei"):
        extractor.extract(make_xlsx(tmp_path / "x.doc"))


# ---------------------------------------------------------------- LibreOffice process handling
@pytest.fixture
def fake_soffice(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()

    def install(script: str):
        p = bindir / "soffice"
        p.write_text("#!/bin/sh\n" + script)
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    return install


def test_libreoffice_timeout_transient(tmp_path, settings, fake_soffice):  # AK-23
    fake_soffice("sleep 30\n")
    settings.file_timeout_seconds = 0.5
    src = make_docx_zip(tmp_path / "a.docx")
    with pytest.raises(TransientError, match="Zeitüberschreitung"):
        Extractor(settings, ocr=FakeOcr()).extract(src)


def test_libreoffice_crash_transient(tmp_path, settings, fake_soffice):  # AK-23
    fake_soffice("kill -SEGV $$\n")
    with pytest.raises(TransientError, match="abgestürzt"):
        Extractor(settings, ocr=FakeOcr()).extract(make_docx_zip(tmp_path / "a.docx"))


def test_libreoffice_no_output_permanent(tmp_path, settings, fake_soffice):  # AK-22
    fake_soffice("exit 0\n")
    with pytest.raises(PermanentError, match="kann nicht geöffnet werden"):
        Extractor(settings, ocr=FakeOcr()).extract(make_docx_zip(tmp_path / "a.docx"))


def test_libreoffice_args_and_profile(tmp_path, settings, fake_soffice, monkeypatch):  # AK-12 (no macros)
    import tempfile

    tmpd = tmp_path / "tmpd"
    tmpd.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmpd))
    log = tmp_path / "args.txt"
    # the fake records its arguments and the macro settings of the profile, then "converts"
    fake_soffice(f"""echo "$@" > {log}
for a in "$@"; do case "$a" in -env:UserInstallation=file://*) prof="${{a#-env:UserInstallation=file://}}";; esac; done
cat "$prof/user/registrymodifications.xcu" >> {log}
while [ $# -gt 0 ]; do [ "$1" = "--outdir" ] && out="$2"; last="$1"; shift; done
cp {tmp_path / "conv.html"} "$out/input.html"
""")
    write(tmp_path / "conv.html", HTML)
    md = Extractor(settings, ocr=FakeOcr()).extract(make_docx_zip(tmp_path / "Brief an Müller.docm")).markdown()
    assert "## Mietvertrag" in md
    args = log.read_text()
    assert "--headless" in args and "input.docm" in args and "Müller" not in args
    assert '"DisableMacrosExecution"' in args and "<value>true</value>" in args
    assert '"MacroSecurityLevel"' in args
    assert os.listdir(tmpd) == []  # working directory and profile removed
