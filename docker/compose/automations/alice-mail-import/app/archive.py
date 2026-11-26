"""Mail archive on the NAS: `<key>/<YYYY>/<MM>/<id>.eml` and `<key>/<YYYY>/<MM>/<id>.attachments/<name>`.

Files appear only complete: everything is written to a temporary name, flushed to disk and renamed
(AK-43, AK-45). Existing archive files are never overwritten or deleted (AK-16, AK-33).
The archive root itself is never created: if the NAS share is missing, the folder is missing and the
import pauses (AK-44)."""
from __future__ import annotations

import logging
import os
import secrets
import shutil
import time
from datetime import datetime

logger = logging.getLogger("alice-mail-import.archive")

TMP_PREFIX = ".tmp-"
STALE_TMP_SECONDS = 3600


class ArchiveUnavailable(Exception):
    """Archive root missing or not writable: pause without changes (AK-44)."""


def month_dir(key: str, when: datetime) -> str:
    return f"{key}/{when:%Y}/{when:%m}"


class Archive:
    def __init__(self, root: str):
        self.root = root.rstrip("/") or "/"

    def path(self, rel: str) -> str:
        return os.path.join(self.root, rel)

    def check(self) -> None:
        """Root exists and is writable (a probe file is created and removed)."""
        if not os.path.isdir(self.root):
            raise ArchiveUnavailable(f"Mail-Archiv {self.root} nicht vorhanden (NAS nicht eingebunden?)")
        probe = os.path.join(self.root, f"{TMP_PREFIX}probe-{secrets.token_hex(4)}")
        try:
            with open(probe, "wb") as fh:
                fh.write(b"ok")
            os.remove(probe)
        except OSError as exc:
            raise ArchiveUnavailable(f"Mail-Archiv {self.root} nicht beschreibbar: {exc.strerror or exc}") from exc

    def exists(self, rel: str) -> bool:
        return os.path.exists(self.path(rel))

    def read(self, rel: str) -> bytes:
        with open(self.path(rel), "rb") as fh:
            return fh.read()

    @staticmethod
    def _write_file(path: str, data: bytes) -> None:
        with open(path, "xb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())

    def stage_attachments(self, folder_rel: str, files: list[tuple[str, bytes]]) -> str | None:
        """Write the attachments into a temporary folder next to their final place; returns its relative
        path (None without attachments)."""
        if not files:
            return None
        os.makedirs(self.path(folder_rel), exist_ok=True)
        tmp_rel = f"{folder_rel}/{TMP_PREFIX}{secrets.token_hex(8)}.attachments"
        os.mkdir(self.path(tmp_rel))
        try:
            for name, data in files:
                self._write_file(os.path.join(self.path(tmp_rel), name), data)
        except BaseException:
            shutil.rmtree(self.path(tmp_rel), ignore_errors=True)
            raise
        return tmp_rel

    def discard(self, tmp_rel: str | None) -> None:
        if tmp_rel and os.path.basename(tmp_rel).startswith(TMP_PREFIX):
            shutil.rmtree(self.path(tmp_rel), ignore_errors=True)

    def commit_attachments(self, tmp_rel: str | None, final_rel: str) -> None:
        """Move the staged folder to `<id>.attachments`; an existing folder is never replaced (AK-16):
        missing files are added to it, existing ones stay."""
        if not tmp_rel:
            return
        final = self.path(final_rel)
        if not os.path.exists(final):
            os.rename(self.path(tmp_rel), final)
            return
        for name in os.listdir(self.path(tmp_rel)):
            target = os.path.join(final, name)
            if not os.path.exists(target):
                os.rename(os.path.join(self.path(tmp_rel), name), target)
        self.discard(tmp_rel)

    def write_new(self, rel: str, data: bytes) -> bool:
        """Write a file under `rel` atomically; False (and nothing changed) if it already exists."""
        final = self.path(rel)
        if os.path.exists(final):
            return False
        os.makedirs(os.path.dirname(final), exist_ok=True)
        tmp = os.path.join(os.path.dirname(final), f"{TMP_PREFIX}{secrets.token_hex(8)}")
        try:
            self._write_file(tmp, data)
            if os.path.exists(final):
                return False
            os.rename(tmp, final)
            return True
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def cleanup_tmp(self, max_age: float = STALE_TMP_SECONDS) -> int:
        """Remove temporary leftovers of an interrupted import (older than `max_age`)."""
        removed = 0
        now = time.time()
        if not os.path.isdir(self.root):
            return 0
        for dirpath, dirnames, filenames in os.walk(self.root):
            for name in list(dirnames) + filenames:
                if not name.startswith(TMP_PREFIX):
                    continue
                full = os.path.join(dirpath, name)
                try:
                    if now - os.lstat(full).st_mtime < max_age:
                        continue
                    if os.path.isdir(full):
                        shutil.rmtree(full, ignore_errors=True)
                        dirnames.remove(name)
                    else:
                        os.remove(full)
                    removed += 1
                except OSError:
                    continue
        return removed
