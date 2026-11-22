"""MS Office / OpenDocument: LibreOffice converts every variant of a group into one intermediate
format (text documents → HTML, spreadsheets → xlsx, presentations → pptx); small readers turn
that into Markdown. Macros are never executed."""
from __future__ import annotations

import datetime as dt
import logging
import os
import re
import shutil
import signal
import subprocess
import tempfile
import zipfile
from html.parser import HTMLParser
from typing import Callable

from ..errors import PermanentError, TransientError
from ..text import Result, Section, md_table, strip_control, tidy

logger = logging.getLogger("alice-text-extraction.office")

TEXT_EXTS = ("doc", "docx", "docm", "dotx", "odt", "ott", "rtf")
SHEET_EXTS = ("xls", "xlsx", "xlsm", "ods", "ots")
SLIDE_EXTS = ("ppt", "pptx", "pptm", "pps", "ppsx", "odp", "otp")
ZIP_EXTS = {"docx", "docm", "dotx", "odt", "ott", "xlsx", "xlsm", "ods", "ots", "pptx", "pptm", "ppsx", "odp", "otp"}
OLE_EXTS = {"doc", "xls", "ppt", "pps"}
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
# the encrypted OOXML package is an OLE file with this stream name (UTF-16)
ENCRYPTED_PACKAGE = "EncryptedPackage".encode("utf-16-le")

TARGETS = {
    "html": 'html:HTML (StarWriter):UTF8',
    "xlsx": 'xlsx:Calc MS Excel 2007 XML',
    "pptx": 'pptx:Impress MS PowerPoint 2007 XML',
}

# Fresh LibreOffice profile: highest macro security, macros disabled, no update checks.
REGISTRY_XCU = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema"
           xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="BlockUntrustedRefererLinks" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="FirstRun" oor:op="fuse"><value>false</value></prop></item>
</oor:items>
"""

# convert(input_path, target, timeout) -> path of the converted file
Converter = Callable[[str, str, float], str]


def group(ext: str) -> str | None:
    if ext in TEXT_EXTS:
        return "text"
    if ext in SHEET_EXTS:
        return "sheet"
    if ext in SLIDE_EXTS:
        return "slide"
    return None


# ---------------------------------------------------------------- checks before converting
def precheck(path: str, ext: str) -> None:
    """Clear permanent errors for password protection and broken containers (AK-21, AK-22),
    instead of a converter that hangs on a repair dialog or silently produces nothing."""
    with open(path, "rb") as f:
        head = f.read(8)
    if ext in ZIP_EXTS:
        if head == OLE_MAGIC:
            with open(path, "rb") as f:
                if ENCRYPTED_PACKAGE in f.read(4 * 1024 * 1024):
                    raise PermanentError("Dokument ist passwortgeschützt")
            raise PermanentError(f"Datei ist beschädigt oder keine gültige .{ext}-Datei")
        try:
            with zipfile.ZipFile(path) as z:
                if z.testzip() is not None:
                    raise PermanentError("Datei ist beschädigt (fehlerhaftes Archiv)")
                if "META-INF/manifest.xml" in z.namelist():
                    if b"encryption-data" in z.read("META-INF/manifest.xml"):
                        raise PermanentError("Dokument ist passwortgeschützt")
        except (zipfile.BadZipFile, EOFError, OSError, ValueError, NotImplementedError):
            raise PermanentError("Datei ist beschädigt und kann nicht geöffnet werden") from None
        except zipfile.LargeZipFile:
            pass
    elif ext in OLE_EXTS:
        if head != OLE_MAGIC:
            raise PermanentError(f"Datei ist beschädigt oder keine gültige .{ext}-Datei")
    elif ext == "rtf":
        if not head.startswith(b"{\\rtf"):
            raise PermanentError("Datei ist beschädigt oder keine gültige .rtf-Datei")


# ---------------------------------------------------------------- LibreOffice
def libreoffice_convert(path: str, target: str, timeout: float, workdir: str) -> str:
    """Convert with a fresh, private LibreOffice profile (parallel runs do not share a profile)."""
    ext = os.path.splitext(path)[1].lower()
    src = os.path.join(workdir, "input" + ext)
    os.symlink(path, src)  # a neutral name: no NAS path in arguments or messages
    profile = os.path.join(workdir, "profile")
    os.makedirs(os.path.join(profile, "user"))
    with open(os.path.join(profile, "user", "registrymodifications.xcu"), "w") as f:
        f.write(REGISTRY_XCU)
    out = os.path.join(workdir, "out")
    os.makedirs(out)
    cmd = ["soffice", f"-env:UserInstallation=file://{profile}", "--headless", "--invisible", "--norestore",
           "--nolockcheck", "--nodefault", "--nologo", "--convert-to", TARGETS[target], "--outdir", out, src]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
                            env={**os.environ, "HOME": workdir})
    try:
        _, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise TransientError(f"Zeitüberschreitung bei der Umwandlung (Grenze {int(timeout)} s)") from None
    except MemoryError:
        os.killpg(proc.pid, signal.SIGKILL)
        raise TransientError("Speichermangel bei der Umwandlung") from None
    if proc.returncode < 0:
        raise TransientError(f"Umwandlungsprogramm abgestürzt (Signal {-proc.returncode})")
    produced = [os.path.join(out, n) for n in os.listdir(out)]
    if not produced:
        logger.info("LibreOffice produced no output (rc=%s): %s", proc.returncode,
                    err.decode(errors="replace").strip()[:300])
        if proc.returncode != 0:
            raise TransientError(f"Umwandlungsprogramm mit Fehler beendet (Code {proc.returncode})")
        raise PermanentError("Dokument kann nicht geöffnet werden (beschädigt, passwortgeschützt "
                             "oder nicht unterstützte Variante)")
    return produced[0]


class LibreOffice:
    """Converter with its own temporary working directory per call."""

    def __init__(self):
        self.dirs: list[str] = []

    def __call__(self, path: str, target: str, timeout: float) -> str:
        d = tempfile.mkdtemp(prefix="lo-")
        self.dirs.append(d)
        return libreoffice_convert(path, target, timeout, d)

    def cleanup(self) -> None:
        for d in self.dirs:
            shutil.rmtree(d, ignore_errors=True)
        self.dirs.clear()


# ---------------------------------------------------------------- HTML → Markdown
class _HtmlToMarkdown(HTMLParser):
    BLOCKS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "pre", "blockquote", "dt", "dd", "center"}
    SKIP = {"head", "style", "script", "title"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.buf: list[str] = []
        self.block: str | None = None
        self.skip = 0
        self.lists: list[str] = []
        self.tables: list[dict] = []  # stack: {"rows": [[cell text]], "cell": [text] | None}

    # text collection
    def _target(self) -> list[str]:
        if self.tables and self.tables[-1]["cell"] is not None:
            return self.tables[-1]["cell"]
        return self.buf

    def _flush(self) -> None:
        text = re.sub(r"[ \t ]+", " ", "".join(self.buf)).strip()
        text = "\n".join(line.strip() for line in text.split("\n")).strip()
        self.buf = []
        if not text:
            return
        tag = self.block or "p"
        if re.fullmatch(r"h[1-6]", tag):
            level = min(6, int(tag[1]) + 1)  # "#" is the title of the source markdown
            text = f"{'#' * level} {text.replace(chr(10), ' ')}"
        elif tag == "li":
            text = "  " * max(0, len(self.lists) - 1) + ("1. " if self.lists and self.lists[-1] == "ol" else "- ") + text
        self.out.append(text)

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "table":
            if not self.tables:
                self._flush()
            self.tables.append({"rows": [], "cell": None})
        elif tag == "tr" and self.tables:
            self.tables[-1]["rows"].append([])
        elif tag in ("td", "th") and self.tables:
            t = self.tables[-1]
            if not t["rows"]:
                t["rows"].append([])
            t["cell"] = []
        elif tag == "br":
            self._target().append("\n")
        elif tag in ("ul", "ol"):
            if not self.tables:
                self._flush()
            self.lists.append(tag)
        elif tag in self.BLOCKS and not self.tables:
            self._flush()
            self.block = tag

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag in ("td", "th") and self.tables:
            t = self.tables[-1]
            if t["cell"] is not None:
                t["rows"][-1].append(re.sub(r"[ \t ]+", " ", "".join(t["cell"])).strip())
                t["cell"] = None
        elif tag == "table" and self.tables:
            t = self.tables.pop()
            if self.tables:  # nested table: its text goes into the outer cell
                outer = self.tables[-1]
                if outer["cell"] is not None:
                    outer["cell"].append(" ".join(c for r in t["rows"] for c in r if c))
            else:
                table = md_table(t["rows"])
                if table:
                    self.out.append(table)
        elif tag in ("ul", "ol"):
            if not self.tables:
                self._flush()
            if self.lists:
                self.lists.pop()
        elif tag in self.BLOCKS and not self.tables:
            self._flush()
            self.block = None

    def handle_data(self, data):
        if self.skip:
            return
        self._target().append(data.replace("\n", " "))

    def result(self) -> str:
        self._flush()
        return "\n\n".join(self.out)


def html_to_markdown(html: str) -> str:
    p = _HtmlToMarkdown()
    p.feed(html)
    p.close()
    return tidy(p.result())


def _read_html(path: str) -> str:
    with open(path, "rb") as f:
        data = f.read()
    m = re.search(rb'charset=["\']?([A-Za-z0-9_\-]+)', data[:4096])
    enc = m.group(1).decode() if m else "utf-8"
    try:
        return data.decode(enc, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


# ---------------------------------------------------------------- spreadsheets
def _value(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "WAHR" if v else "FALSCH"
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    if isinstance(v, dt.datetime):
        return v.date().isoformat() if v.time() == dt.time(0) else v.isoformat(sep=" ")
    if isinstance(v, (dt.date, dt.time)):
        return v.isoformat()
    return str(v)


def sheets_to_result(xlsx_path: str) -> Result:
    """One section per sheet (hidden ones included, EC-5) with the stored values (EC-4)."""
    import openpyxl

    try:
        wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    except Exception as exc:
        raise PermanentError(f"Tabellendatei kann nicht gelesen werden ({exc.__class__.__name__})") from None
    result = Result()
    try:
        for ws in wb.worksheets:
            rows = [[_value(v) for v in row] for row in ws.iter_rows(values_only=True)]
            while rows and not any(rows[-1]):
                rows.pop()
            width = max((max((i + 1 for i, c in enumerate(r) if c), default=0) for r in rows), default=0)
            rows = [r[:width] for r in rows]
            result.sections.append(Section(f"Blatt {ws.title}", md_table(rows)))
    finally:
        wb.close()
    return result


# ---------------------------------------------------------------- presentations
def _shape_texts(shapes) -> list[str]:
    from pptx.shapes.group import GroupShape

    out = []
    for shape in shapes:
        if isinstance(shape, GroupShape):
            out += _shape_texts(shape.shapes)
            continue
        if getattr(shape, "has_table", False) and shape.has_table:
            rows = [[cell.text for cell in row.cells] for row in shape.table.rows]
            table = md_table(rows)
            if table:
                out.append(table)
        elif getattr(shape, "has_text_frame", False) and shape.has_text_frame:
            text = tidy(shape.text_frame.text.replace("\x0b", "\n"))
            if text.strip():
                out.append(text)
    return out


def slides_to_result(pptx_path: str) -> Result:
    """One section per slide: all text boxes and tables, then the speaker notes."""
    from pptx import Presentation

    try:
        prs = Presentation(pptx_path)
    except Exception as exc:
        raise PermanentError(f"Präsentation kann nicht gelesen werden ({exc.__class__.__name__})") from None
    result = Result()
    for n, slide in enumerate(prs.slides, start=1):
        parts = _shape_texts(slide.shapes)
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = tidy(slide.notes_slide.notes_text_frame.text.replace("\x0b", "\n"))
            if notes.strip():
                parts.append(f"### Notizen\n\n{notes}")
        result.sections.append(Section(f"Folie {n}", "\n\n".join(parts)))
    return result


# ---------------------------------------------------------------- entry
def extract_office(path: str, ext: str, *, convert: Converter, timeout: float) -> Result:
    precheck(path, ext)
    kind = group(ext)
    if kind == "text":
        html = _read_html(convert(path, "html", timeout))
        return Result(sections=[Section(None, html_to_markdown(strip_control(html)))])
    if kind == "sheet":
        return sheets_to_result(convert(path, "xlsx", timeout))
    if kind == "slide":
        return slides_to_result(convert(path, "pptx", timeout))
    raise PermanentError(f"Format .{ext} wird nicht unterstützt")
