"""Read-only IMAP access with the standard library (runs in worker threads).

Only EXAMINE (read-only select), LIST, UID SEARCH and UID FETCH with BODY.PEEK are used: no command
of this module can set a flag, move or delete a mail (AK-4). Error messages are plain German causes
without passwords (AK-41, AK-55)."""
from __future__ import annotations

import imaplib
import re
import socket
import ssl
from datetime import date, datetime

_LIST = re.compile(rb'^\((?P<flags>[^)]*)\)\s+(?P<delim>"(?:[^"\\]|\\.)*"|NIL)\s+(?P<name>.*)$')
_INTERNALDATE = re.compile(rb'INTERNALDATE "([^"]+)"')
_UID = re.compile(rb"UID (\d+)")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class ImapError(Exception):
    """Mailbox not usable right now (login, connection, timeout): status `error`, next tick retries."""


class ConnectionLost(ImapError):
    """The connection broke during the work."""


def _quote(name: str) -> str:
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _unquote(raw: bytes) -> str:
    raw = raw.strip()
    if raw.startswith(b'"') and raw.endswith(b'"'):
        raw = re.sub(rb"\\(.)", rb"\1", raw[1:-1])
    return raw.decode("utf-8", "replace")


def imap_date(d: date) -> str:
    return f"{d.day:02d}-{_MONTHS[d.month - 1]}-{d.year}"


def parse_internaldate(meta: bytes) -> datetime | None:
    m = _INTERNALDATE.search(meta or b"")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1).decode().strip(), "%d-%b-%Y %H:%M:%S %z")
    except ValueError:
        return None


def _cause(exc: BaseException, host: str) -> str:
    if isinstance(exc, socket.gaierror):
        return f"Server {host} nicht gefunden"
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "Zeitüberschreitung beim Mailserver"
    if isinstance(exc, ConnectionRefusedError):
        return "Mailserver nicht erreichbar (Verbindung abgelehnt)"
    if isinstance(exc, ssl.SSLError):
        return "TLS-Verbindung zum Mailserver fehlgeschlagen"
    if isinstance(exc, imaplib.IMAP4.abort):
        return "Verbindung zum Mailserver abgebrochen"
    if isinstance(exc, OSError):
        return f"Mailserver nicht erreichbar ({exc.__class__.__name__})"
    return f"IMAP-Fehler ({exc.__class__.__name__})"


class ImapSession:
    def __init__(self, host: str, port: int, use_ssl: bool, username: str, password: str, timeout: float):
        self.host, self.port, self.use_ssl = host, port, use_ssl
        self._username, self._password = username, password
        self.timeout = timeout
        self.c: imaplib.IMAP4 | None = None

    # ---------------------------------------------------------------- connection
    def open(self) -> None:
        try:
            if self.use_ssl:
                self.c = imaplib.IMAP4_SSL(self.host, self.port, timeout=self.timeout,
                                           ssl_context=ssl.create_default_context())
            else:
                self.c = imaplib.IMAP4(self.host, self.port, timeout=self.timeout)
        except Exception as exc:
            raise ImapError(_cause(exc, self.host)) from None
        try:
            self.c.login(self._username, self._password)
        except imaplib.IMAP4.abort as exc:
            self.close()
            raise ImapError(_cause(exc, self.host)) from None
        except imaplib.IMAP4.error:
            self.close()
            raise ImapError("Anmeldung abgelehnt (Benutzername oder Passwort falsch)") from None
        except Exception as exc:
            self.close()
            raise ImapError(_cause(exc, self.host)) from None
        finally:
            self._password = ""  # not kept longer than needed

    def close(self) -> None:
        c, self.c = self.c, None
        if c is None:
            return
        try:
            c.logout()
        except Exception:
            try:
                c.shutdown()
            except Exception:
                pass

    def _call(self, fn, *args):
        if self.c is None:
            raise ConnectionLost("Keine Verbindung zum Mailserver")
        try:
            typ, data = fn(*args)
        except imaplib.IMAP4.abort as exc:
            raise ConnectionLost(_cause(exc, self.host)) from None
        except imaplib.IMAP4.error as exc:
            raise ImapError(f"Mailserver lehnt den Befehl ab ({str(exc)[:200]})") from None
        except (OSError, EOFError) as exc:
            raise ConnectionLost(_cause(exc, self.host)) from None
        if typ != "OK":
            raise ImapError(f"Mailserver antwortet {typ}")
        return data

    # ---------------------------------------------------------------- folders
    def folders(self) -> list[tuple[set[str], str]]:
        """(flags, name) of every folder; the name as the server spells it (modified UTF-7)."""
        out = []
        data = self._call(self.c.list, '""', "*")
        for item in data:
            if item is None:
                continue
            if isinstance(item, tuple):  # name sent as literal
                head, literal = item
                m = _LIST.match(head.strip())
                if m:
                    out.append(({f.lower() for f in m.group("flags").decode().split()},
                                literal.decode("utf-8", "replace")))
                continue
            m = _LIST.match(item.strip())
            if m:
                out.append(({f.lower() for f in m.group("flags").decode().split()}, _unquote(m.group("name"))))
        return out

    def examine(self, folder: str) -> tuple[int, int | None]:
        """Open a folder read-only; (UIDVALIDITY, UIDNEXT)."""
        self._call(self.c.select, _quote(folder), True)
        uv = self.c.response("UIDVALIDITY")[1]
        nx = self.c.response("UIDNEXT")[1]
        uidvalidity = int(uv[0]) if uv and uv[0] else 0
        uidnext = int(nx[0]) if nx and nx[0] else None
        return uidvalidity, uidnext

    # ---------------------------------------------------------------- search / fetch
    def _search(self, *criteria: str) -> list[int]:
        data = self._call(self.c.uid, "SEARCH", *criteria)
        uids: list[int] = []
        for chunk in data:
            if chunk:
                uids.extend(int(x) for x in chunk.split())
        return sorted(set(uids))

    def uids_since(self, since: date) -> list[int]:
        return self._search("SINCE", imap_date(since))

    def uids_from(self, first_uid: int) -> list[int]:
        return [u for u in self._search("UID", f"{max(1, first_uid)}:*") if u >= first_uid]

    def all_uids(self) -> list[int]:
        return self._search("ALL")

    def fetch(self, uid: int) -> tuple[bytes, datetime | None] | None:
        """Raw mail without setting \\Seen (BODY.PEEK); None if the UID is gone meanwhile."""
        data = self._call(self.c.uid, "FETCH", str(uid), "(UID INTERNALDATE BODY.PEEK[])")
        for item in data:
            if isinstance(item, tuple) and len(item) >= 2:
                m = _UID.search(item[0])
                if m and int(m.group(1)) != uid:
                    continue
                return item[1], parse_internaldate(item[0])
        return None

    def message_ids(self, uids: list[int], chunk: int = 500) -> dict[int, str | None]:
        """Message-ID header per UID (for new UIDs after a UIDVALIDITY change, EC-4)."""
        out: dict[int, str | None] = {}
        for i in range(0, len(uids), chunk):
            part = uids[i:i + chunk]
            data = self._call(self.c.uid, "FETCH", ",".join(map(str, part)),
                              "(UID BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
            for item in data:
                if isinstance(item, tuple) and len(item) >= 2:
                    m = _UID.search(item[0])
                    if not m:
                        continue
                    header = item[1].decode("utf-8", "replace")
                    mid = re.search(r"<[^<>\s]+>", header)
                    out[int(m.group(1))] = mid.group(0) if mid else None
        return out
