"""A small IMAP4rev1 test server (real protocol over TCP, plain text) for the tests of the mail import.

Supports what a read-only client needs: CAPABILITY, LOGIN, LIST (with SPECIAL-USE flags), EXAMINE,
UID SEARCH (ALL / SINCE / UID range), UID FETCH (UID, INTERNALDATE, BODY.PEEK[...], BODY[...]), NOOP,
LOGOUT. Every command that could change the mailbox (SELECT, STORE, COPY, MOVE, EXPUNGE, APPEND,
DELETE, BODY[] without PEEK) is recorded in `violations` (AK-4). It counts connections (AK-48) and can
reject logins (AK-41), drop the connection after a number of fetches (AK-43) and change UIDVALIDITY
(EC-4). No real mail data: tests build their own messages.
"""
from __future__ import annotations

import re
import socketserver
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|(\([^)]*\))|(\S+)')


@dataclass
class Mail:
    uid: int
    raw: bytes
    internaldate: datetime
    flags: set = field(default_factory=set)


@dataclass
class Folder:
    name: str
    special: str = ""        # e.g. "\\Sent", "\\Junk", "\\Trash", "\\Drafts", "\\All"
    uidvalidity: int = 1
    uidnext: int = 1
    mails: list = field(default_factory=list)


def imap_internaldate(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return f"{dt.day:02d}-{MONTHS[dt.month - 1]}-{dt.year} {dt:%H:%M:%S} +0000"


def _uidset(spec: str, maxuid: int) -> set[int]:
    out: set[int] = set()
    for part in spec.split(","):
        if ":" in part:
            a, b = part.split(":", 1)
            a = maxuid if a == "*" else int(a)
            b = maxuid if b == "*" else int(b)
            lo, hi = min(a, b), max(a, b)
            out.update(range(lo, hi + 1))
        else:
            out.add(maxuid if part == "*" else int(part))
    return out


class FakeImapServer:
    def __init__(self, username: str = "user@example.invalid", password: str = "secret"):
        self.username, self.password = username, password
        self.folders: dict[str, Folder] = {}
        self.lock = threading.RLock()
        self.violations: list[str] = []
        self.commands: list[str] = []
        self.active = 0
        self.max_active = 0
        self.total_connections = 0
        self.reject_login = False
        self.drop_after_fetches: int | None = None
        self.fetch_count = 0
        self.down = False
        for name, special in (("INBOX", ""), ("Gesendet", "\\Sent"), ("Spam", "\\Junk"), ("Papierkorb", "\\Trash"),
                              ("Entwürfe", "\\Drafts"), ("Archiv", "")):
            self.folders[name] = Folder(name, special)
        server = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                server._session(self)

        class TCP(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.tcp = TCP(("127.0.0.1", 0), Handler)
        self.port = self.tcp.server_address[1]
        self.thread = threading.Thread(target=self.tcp.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.tcp.shutdown()
        self.tcp.server_close()

    # ---------------------------------------------------------------- test helpers
    def add(self, folder: str, raw: bytes, internaldate: datetime | None = None, flags=()) -> int:
        with self.lock:
            f = self.folders[folder]
            uid = f.uidnext
            f.uidnext += 1
            f.mails.append(Mail(uid, raw, internaldate or datetime.now(timezone.utc), set(flags)))
            return uid

    def remove(self, folder: str, uid: int) -> Mail:
        with self.lock:
            f = self.folders[folder]
            mail = next(m for m in f.mails if m.uid == uid)
            f.mails.remove(mail)
            return mail

    def move(self, src: str, uid: int, dst: str) -> int:
        mail = self.remove(src, uid)
        return self.add(dst, mail.raw, mail.internaldate, mail.flags)

    def renumber(self, folder: str) -> None:
        """New UIDVALIDITY, all mails get new UIDs (EC-4)."""
        with self.lock:
            f = self.folders[folder]
            f.uidvalidity += 100
            for m in f.mails:
                m.uid = f.uidnext
                f.uidnext += 1

    def flags(self) -> dict:
        with self.lock:
            return {(f.name, m.uid): set(m.flags) for f in self.folders.values() for m in f.mails}

    # ---------------------------------------------------------------- protocol
    def _session(self, h):
        with self.lock:
            if self.down:
                return
            self.active += 1
            self.total_connections += 1
            self.max_active = max(self.max_active, self.active)
        try:
            self._serve(h)
        except (ConnectionError, OSError):
            pass
        finally:
            with self.lock:
                self.active -= 1

    def _serve(self, h):
        w = h.wfile
        w.write(b"* OK [CAPABILITY IMAP4rev1 SPECIAL-USE] fake server ready\r\n")
        authed = False
        selected: Folder | None = None
        while True:
            line = h.rfile.readline()
            if not line:
                return
            line = line.rstrip(b"\r\n").decode("utf-8", "replace")
            # client literals {n} (long passwords etc.)
            while line.endswith("}") and re.search(r"\{(\d+)\}$", line):
                n = int(re.search(r"\{(\d+)\}$", line).group(1))
                w.write(b"+ go ahead\r\n")
                w.flush()
                data = h.rfile.read(n).decode("utf-8", "replace")
                rest = h.rfile.readline().rstrip(b"\r\n").decode("utf-8", "replace")
                line = line[: line.rfind("{")] + '"' + data.replace("\\", "\\\\").replace('"', '\\"') + '"' + rest
            tag, _, rest = line.partition(" ")
            cmd, _, args = rest.partition(" ")
            cmd = cmd.upper()
            with self.lock:
                self.commands.append(cmd + (" " + args.split(" ")[0] if cmd == "UID" else ""))
            if cmd == "CAPABILITY":
                w.write(b"* CAPABILITY IMAP4rev1 SPECIAL-USE\r\n" + f"{tag} OK done\r\n".encode())
            elif cmd == "NOOP":
                w.write(f"{tag} OK done\r\n".encode())
            elif cmd == "LOGOUT":
                w.write(b"* BYE bye\r\n" + f"{tag} OK done\r\n".encode())
                w.flush()
                return
            elif cmd == "LOGIN":
                toks = [a or b or c for a, b, c in _TOKEN.findall(args)]
                user = toks[0].replace('\\"', '"').replace("\\\\", "\\") if toks else ""
                pw = toks[1].replace('\\"', '"').replace("\\\\", "\\") if len(toks) > 1 else ""
                if self.reject_login or user != self.username or pw != self.password:
                    w.write(f"{tag} NO [AUTHENTICATIONFAILED] Invalid credentials\r\n".encode())
                else:
                    authed = True
                    w.write(f"{tag} OK logged in\r\n".encode())
            elif not authed:
                w.write(f"{tag} BAD not authenticated\r\n".encode())
            elif cmd == "LIST":
                with self.lock:
                    for f in self.folders.values():
                        flags = "\\HasNoChildren" + (" " + f.special if f.special else "")
                        w.write(f'* LIST ({flags}) "/" "{f.name}"\r\n'.encode())
                w.write(f"{tag} OK done\r\n".encode())
            elif cmd in ("EXAMINE", "SELECT"):
                name = args.strip().strip('"')
                if cmd == "SELECT":
                    self.violations.append(f"SELECT {name}")
                with self.lock:
                    f = self.folders.get(name)
                    if f is None:
                        w.write(f"{tag} NO no such folder\r\n".encode())
                        continue
                    selected = f
                    w.write(f"* {len(f.mails)} EXISTS\r\n* 0 RECENT\r\n* FLAGS (\\Seen \\Answered \\Flagged \\Deleted)\r\n"
                            f"* OK [UIDVALIDITY {f.uidvalidity}] ok\r\n* OK [UIDNEXT {f.uidnext}] ok\r\n".encode())
                mode = "READ-ONLY" if cmd == "EXAMINE" else "READ-WRITE"
                w.write(f"{tag} OK [{mode}] done\r\n".encode())
            elif cmd == "UID":
                sub, _, a = args.partition(" ")
                sub = sub.upper()
                if selected is None:
                    w.write(f"{tag} BAD no folder\r\n".encode())
                elif sub == "SEARCH":
                    w.write(self._search(selected, a) + f"{tag} OK done\r\n".encode())
                elif sub == "FETCH":
                    if not self._fetch(w, selected, a):
                        return  # connection dropped
                    w.write(f"{tag} OK done\r\n".encode())
                else:
                    self.violations.append(f"UID {sub}")
                    w.write(f"{tag} NO not allowed\r\n".encode())
            else:
                self.violations.append(cmd)
                w.write(f"{tag} NO not allowed\r\n".encode())
            w.flush()

    def _search(self, f: Folder, criteria: str) -> bytes:
        crit = criteria.split()
        with self.lock:
            mails = list(f.mails)
            maxuid = max((m.uid for m in mails), default=0)
        if crit and crit[0].upper() == "SINCE":
            day, mon, year = crit[1].strip('"').split("-")
            since = datetime(int(year), MONTHS.index(mon) + 1, int(day)).date()
            uids = [m.uid for m in mails if m.internaldate.astimezone(timezone.utc).date() >= since]
        elif crit and crit[0].upper() == "UID":
            wanted = _uidset(crit[1], max(maxuid, 1))
            uids = [m.uid for m in mails if m.uid in wanted]
            if not uids and mails and crit[1].endswith(":*"):
                uids = [maxuid]  # RFC 3501: n:* always matches the last message
        else:
            uids = [m.uid for m in mails]
        return ("* SEARCH" + "".join(f" {u}" for u in sorted(uids)) + "\r\n").encode()

    def _fetch(self, w, f: Folder, args: str) -> bool:
        spec, _, items = args.partition(" ")
        items_u = items.upper()
        with self.lock:
            mails = list(f.mails)
            maxuid = max((m.uid for m in mails), default=0)
        wanted = _uidset(spec, max(maxuid, 1))
        for seq, m in enumerate(mails, start=1):
            if m.uid not in wanted:
                continue
            parts = [f"UID {m.uid}"]
            if "INTERNALDATE" in items_u:
                parts.append(f'INTERNALDATE "{imap_internaldate(m.internaldate)}"')
            literal = None
            if "HEADER.FIELDS" in items_u:
                head = m.raw.replace(b"\r\n", b"\n").split(b"\n\n", 1)[0]
                mid = [l for l in head.split(b"\n") if l.lower().startswith(b"message-id:")]
                literal = (b"\r\n".join(mid) + b"\r\n\r\n") if mid else b"\r\n"
                parts.append(f"BODY[HEADER.FIELDS (MESSAGE-ID)] {{{len(literal)}}}")
            elif "BODY.PEEK[]" in items_u or "BODY[]" in items_u or "RFC822" in items_u:
                if "BODY.PEEK" not in items_u:
                    self.violations.append("FETCH without PEEK")
                    m.flags.add("\\Seen")
                with self.lock:
                    self.fetch_count += 1
                    if self.drop_after_fetches is not None and self.fetch_count > self.drop_after_fetches:
                        w.flush()
                        return False
                literal = m.raw
                parts.append(f"BODY[] {{{len(literal)}}}")
            head = f"* {seq} FETCH (" + " ".join(parts)
            if literal is None:
                w.write((head + ")\r\n").encode())
            else:
                w.write(head.encode() + b"\r\n" + literal + b")\r\n")
        return True
