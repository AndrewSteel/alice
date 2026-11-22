"""Real extraction inside the built image (used by container-smoke.sh): LibreOffice converts
generated test documents into every supported variant, Tesseract reads a scanned page.
Run with:  python tests/container_selftest.py   (or piped into `python -` in the container)
No NAS, no register: the Extractor is called directly."""
import os
import subprocess
import sys
import tempfile
import time
import zipfile

sys.path.insert(0, "/app")

from app.config import Settings  # noqa: E402
from app.errors import PermanentError, TransientError  # noqa: E402
from app.extractor import Extractor  # noqa: E402
from app.text import detect_language  # noqa: E402

WORK = tempfile.mkdtemp(prefix="selftest-")
MARKER = os.path.join(WORK, "macro-ran")
HTML = """<html><head><meta charset="utf-8"></head><body>
<h1>Mietvertrag Müller</h1><p>Zwischen dem Vermieter und der Mieterin wird folgender Vertrag geschlossen.</p>
<p>Die Wohnung liegt im zweiten Stock.</p>
<table border="1"><tr><td>Posten</td><td>Betrag</td></tr><tr><td>Kaltmiete</td><td>800 €</td></tr></table>
</body></html>"""


def soffice(src, fmt, outdir):
    profile = tempfile.mkdtemp(prefix="lo-gen-", dir=WORK)
    subprocess.run(["soffice", f"-env:UserInstallation=file://{profile}", "--headless", "--norestore",
                    "--convert-to", fmt, "--outdir", outdir, src], check=True, capture_output=True, timeout=180)
    out = os.path.join(outdir, os.path.splitext(os.path.basename(src))[0] + "." + fmt.split(":")[0])
    assert os.path.exists(out), (src, fmt)
    return out


def variants(src, formats):
    out = {}
    for ext, fmt in formats.items():
        d = os.path.join(WORK, ext)
        os.makedirs(d, exist_ok=True)
        out[ext] = soffice(src, fmt, d)
    return out


def check(label, cond, detail=""):
    if not cond:
        print(f"FAIL {label}: {detail}"[:3000])
        sys.exit(1)
    print(f"ok   {label}")


def macro_odt(path):
    """ODT with a Basic macro bound to the document's load event: it would create MARKER."""
    module = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE script:module PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "module.dtd">
<script:module xmlns:script="http://openoffice.org/2000/script" script:name="Module1" script:language="StarBasic">
Sub Main
  Open "{MARKER}" For Output As #1
  Print #1, "ran"
  Close #1
End Sub
</script:module>"""
    content = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:script="urn:oasis:names:tc:opendocument:xmlns:script:1.0"
 xmlns:xlink="http://www.w3.org/1999/xlink" office:version="1.3">
<office:scripts><office:event-listeners>
<script:event-listener script:language="ooo:script" script:event-name="dom:load"
 xlink:href="vnd.sun.star.script:Standard.Module1.Main?language=Basic&amp;location=document" xlink:type="simple"/>
</office:event-listeners></office:scripts>
<office:body><office:text><text:p>Dokument mit Makro Inhalt bleibt lesbar</text:p></office:text></office:body>
</office:document-content>"""
    manifest = """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.3">
<manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/>
<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
<manifest:file-entry manifest:full-path="Basic/Standard/Module1.xml" manifest:media-type="text/xml"/>
<manifest:file-entry manifest:full-path="Basic/Standard/script-lb.xml" manifest:media-type="text/xml"/>
<manifest:file-entry manifest:full-path="Basic/script-lc.xml" manifest:media-type="text/xml"/>
</manifest:manifest>"""
    lb = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE library:library PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "library.dtd">
<library:library xmlns:library="http://openoffice.org/2000/library" library:name="Standard" library:readonly="false" library:passwordprotected="false">
<library:element library:name="Module1"/></library:library>"""
    lc = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE library:libraries PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "libraries.dtd">
<library:libraries xmlns:library="http://openoffice.org/2000/library" xmlns:xlink="http://www.w3.org/1999/xlink">
<library:library library:name="Standard" library:link="false"/></library:libraries>"""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/vnd.oasis.opendocument.text")
        z.writestr("content.xml", content)
        z.writestr("Basic/Standard/Module1.xml", module)
        z.writestr("Basic/Standard/script-lb.xml", lb)
        z.writestr("Basic/script-lc.xml", lc)
        z.writestr("META-INF/manifest.xml", manifest)
    return path


def main():
    t0 = time.time()
    ex = Extractor(Settings(file_timeout_seconds=180, ocr_page_timeout_seconds=120))

    # ---- text documents (AK-9, AK-12)
    html = os.path.join(WORK, "vertrag.html")
    with open(html, "w", encoding="utf-8") as f:
        f.write(HTML)
    odt = soffice(html, "odt:writer8", WORK)
    docs = variants(odt, {"docx": "docx:MS Word 2007 XML", "doc": "doc:MS Word 97", "rtf": "rtf:Rich Text Format",
                          "ott": "ott:writer8_template", "dotx": "dotx:MS Word 2007 XML Template",
                          "docm": "docm:MS Word 2007 XML VBA"})
    docs["odt"] = odt
    for ext, path in sorted(docs.items()):
        md = ex.extract(path).markdown()
        check(f"{ext}: heading, paragraph, table",
              "## Mietvertrag Müller" in md and "folgender Vertrag geschlossen" in md
              and "| Kaltmiete | 800 € |" in md, md)

    # ---- spreadsheets (AK-10, AK-12, EC-4, EC-5)
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Einnahmen"
    ws.append(["Monat", "Betrag"])
    ws.append(["Januar", 100])
    ws.append(["Februar", 250])
    ws.append(["Summe", "=SUM(B2:B3)"])
    ws2 = wb.create_sheet("Ausgaben")
    ws2.append(["Posten", "Euro"])
    ws2.append(["Strom", 80])
    ws2.sheet_state = "hidden"
    xlsx = os.path.join(WORK, "haushalt.xlsx")
    wb.save(xlsx)
    ods = soffice(xlsx, "ods:calc8", WORK)  # LibreOffice calculates and stores the formula value
    sheets = variants(ods, {"xls": "xls:MS Excel 97", "xlsx": "xlsx:Calc MS Excel 2007 XML",
                            "ots": "ots:calc8_template", "xlsm": "xlsm:Calc MS Excel 2007 VBA XML"})
    sheets["ods"] = ods
    for ext, path in sorted(sheets.items()):
        r = ex.extract(path)
        md = r.markdown()
        check(f"{ext}: two sheets with tables, stored formula value",
              [s.heading for s in r.sections] == ["Blatt Einnahmen", "Blatt Ausgaben"]
              and "| Monat | Betrag |" in md and "| Summe | 350 |" in md and "| Strom | 80 |" in md, md)

    # ---- presentations (AK-11, AK-12)
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[1])
    s1.shapes.title.text = "Projektstart"
    s1.placeholders[1].text = "Ziele und Zeitplan"
    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    s2.shapes.title.text = "Budget"
    tbl = s2.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(5), Inches(1)).table
    for (r_, c_), v in {(0, 0): "Posten", (0, 1): "Euro", (1, 0): "Hardware", (1, 1): "5000"}.items():
        tbl.cell(r_, c_).text = v
    s3 = prs.slides.add_slide(prs.slide_layouts[5])
    s3.shapes.title.text = "Fazit"
    s3.notes_slide.notes_text_frame.text = "Auf die Risiken eingehen"
    pptx = os.path.join(WORK, "vortrag.pptx")
    prs.save(pptx)
    slides = variants(pptx, {"ppt": "ppt:MS PowerPoint 97", "odp": "odp:impress8", "otp": "otp:impress8_template",
                             "pps": "pps:MS PowerPoint 97 AutoPlay", "ppsx": "ppsx:Impress MS PowerPoint 2007 XML AutoPlay",
                             "pptm": "pptm:Impress MS PowerPoint 2007 XML VBA"})
    slides["pptx"] = pptx
    for ext, path in sorted(slides.items()):
        r = ex.extract(path)
        md = r.markdown()
        check(f"{ext}: three slides, table, notes",
              [s.heading for s in r.sections] == ["Folie 1", "Folie 2", "Folie 3"]
              and "Ziele und Zeitplan" in md and "| Hardware | 5000 |" in md
              and "### Notizen\n\nAuf die Risiken eingehen" in md[md.index("## Folie 3"):], md)

    # ---- macros are not executed (AK-12)
    md = ex.extract(macro_odt(os.path.join(WORK, "makro.odt"))).markdown()
    check("macro document: content read, macro not run",
          "Dokument mit Makro" in md and not os.path.exists(MARKER), md)

    # ---- broken office file (AK-22)
    broken = os.path.join(WORK, "kaputt.docx")
    with open(docs["docx"], "rb") as f:
        data = f.read()
    with open(broken, "wb") as f:
        f.write(data[: len(data) // 2])
    try:
        ex.extract(broken)
        check("broken docx: permanent error", False, "no error")
    except PermanentError as exc:
        check("broken docx: permanent error", "beschädigt" in str(exc), str(exc))

    # ---- conversion timeout (AK-23): transient error, the killed LibreOffice leaves no zombie
    #      (checked afterwards by no_zombies.py in container-smoke.sh)
    try:
        Extractor(Settings(file_timeout_seconds=0.5, ocr_page_timeout_seconds=120)).extract(docs["docx"])
        check("conversion timeout: transient error", False, "no error")
    except TransientError as exc:
        check("conversion timeout: transient error", "Zeitüberschreitung" in str(exc), str(exc))

    # ---- OCR of a scanned page with real Tesseract (AK-7, AK-8)
    import pymupdf

    text = ("Sehr geehrte Damen und Herren, hiermit kündige ich den Vertrag fristgerecht zum Ende des Monats. "
            "Bitte bestätigen Sie mir den Eingang dieses Schreibens.")
    src = pymupdf.open()
    page = src.new_page()
    page.insert_textbox(pymupdf.Rect(50, 80, 550, 400), text, fontsize=14)
    png = page.get_pixmap(dpi=200).tobytes("png")
    scan = pymupdf.open()
    scan.new_page().insert_text((72, 72), "Textseite eins mit ausreichend lesbarem Text fuer die Textebene.",
                                fontsize=11)
    scan.new_page().insert_image(pymupdf.Rect(0, 0, 595, 842), stream=png)
    path = os.path.join(WORK, "gemischt.pdf")
    scan.save(path)
    r = ex.extract(path)
    md = r.markdown()
    check("pdf: text page + scanned page via OCR", r.method == "mixed" and r.ocr_pages == [2]
          and "kündige ich den Vertrag" in md and "Textseite eins" in md, md)
    check("language of the OCR text", detect_language(md, 100) == "de", md)
    print(f"selftest ok in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
