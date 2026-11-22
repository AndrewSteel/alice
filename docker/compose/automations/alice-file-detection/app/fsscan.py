"""File system helpers: skip rules, classification, listing, hashing (blocking; run in a thread)."""
from __future__ import annotations

import fnmatch
import hashlib
import os
import posixpath
from dataclasses import dataclass

from .config import Settings

HASH_CHUNK = 1024 * 1024  # constant memory for very large files (EC-4)


@dataclass(frozen=True)
class Entry:
    name: str
    path: str
    is_dir: bool
    size: int = 0
    mtime_ns: int = 0
    bad_name: bool = False  # not valid UTF-8: cannot be stored as a location


def valid_utf8(name: str) -> bool:
    try:
        name.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


def printable(path: str) -> str:
    """Path with undecodable bytes replaced, safe to store and log."""
    return path.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def norm(path: str) -> str:
    path = posixpath.normpath(path)
    return path


def under(path: str, folder: str) -> bool:
    folder = folder.rstrip("/") or "/"
    return path == folder or path.startswith(folder if folder == "/" else folder + "/")


def share_of(path: str, nas_root: str, folder: str) -> str:
    """Share for the deletion limit: first path element below the NAS root, else the watched folder."""
    root = nas_root.rstrip("/")
    if root and path.startswith(root + "/"):
        first = path[len(root) + 1:].split("/", 1)[0]
        if first:
            return f"{root}/{first}"
    return folder


def skip_dir(name: str, s: Settings) -> bool:
    return name.startswith(".") or name.lower() in {d.lower() for d in s.skip_dirs}


def skip_file(name: str, s: Settings) -> bool:
    low = name.lower()
    return name.startswith(".") or any(fnmatch.fnmatchcase(low, p.lower()) for p in s.skip_files)


def extension(name: str) -> str:
    _, ext = posixpath.splitext(name)
    return ext[1:].lower()


def kind_of(name: str, s: Settings) -> str | None:
    """document/image/audio/video, None for an extension that is not processed."""
    return s.extensions.get(extension(name))


def list_dir(path: str) -> list[Entry]:
    """Directories and regular files of a folder; symbolic links and other types are left out (EC-8).
    Raises OSError if the folder itself cannot be read."""
    out: list[Entry] = []
    with os.scandir(path) as it:
        for e in it:
            try:
                if e.is_symlink():
                    continue
                if not valid_utf8(e.name):
                    out.append(Entry(e.name, posixpath.join(path, e.name), e.is_dir(follow_symlinks=False),
                                     bad_name=True))
                    continue
                if e.is_dir(follow_symlinks=False):
                    out.append(Entry(e.name, posixpath.join(path, e.name), True))
                elif e.is_file(follow_symlinks=False):
                    st = e.stat(follow_symlinks=False)
                    out.append(Entry(e.name, posixpath.join(path, e.name), False, st.st_size, st.st_mtime_ns))
            except FileNotFoundError:
                continue  # vanished while listing (EC-1)
    return out


def dir_mtime(path: str) -> int | None:
    """mtime of a real directory (no symlink), None if it is gone or not a directory."""
    try:
        st = os.lstat(path)
    except OSError:
        return None
    import stat as _stat

    return st.st_mtime_ns if _stat.S_ISDIR(st.st_mode) else None


def file_stat(path: str) -> tuple[int, int] | None:
    """(size, mtime_ns) of a regular file, None if it is gone, a link or not a file."""
    import stat as _stat

    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    if not _stat.S_ISREG(st.st_mode):
        return None
    return st.st_size, st.st_mtime_ns


def folder_state(path: str) -> tuple[bool, bool, str]:
    """(readable, empty, error) of a watched folder without listing it completely."""
    try:
        with os.scandir(path) as it:
            empty = next(iter(it), None) is None
        return True, empty, ""
    except OSError as exc:
        return False, False, exc.strerror or str(exc)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:  # read only: originals are never changed
        while chunk := f.read(HASH_CHUNK):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def problem_cause(exc: OSError) -> str:
    if isinstance(exc, PermissionError):
        return "Keine Leserechte"
    return f"Lesefehler: {exc.strerror or exc}"
