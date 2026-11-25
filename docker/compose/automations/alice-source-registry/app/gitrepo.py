"""Git operations on the source-of-truth repo (blocking; called from a worker thread).

Every call is serialized by the caller (one lock in the service), so no commit
ever contains changes of another stage. Commits always name their paths.
"""
from __future__ import annotations

import glob
import logging
import os
import subprocess
import time
from dataclasses import dataclass

from .markdown import KIND_DIRS, README, WATCH_DIRS

logger = logging.getLogger("alice-source-registry.git")

SCANNED_REF = "refs/alice/scanned"
GIT_TIMEOUT = 300


@dataclass(frozen=True)
class Author:
    name: str
    email: str


PIPELINE = Author("Alice ETL", "etl@alice.invalid")
HAND = Author("Alice Hand-Korrektur", "hand-correction@alice.invalid")
PIPELINE_EMAILS = {PIPELINE.email, HAND.email}


class RepoUnavailable(Exception):
    """The repo folder (NAS) cannot be reached; nothing counts as a failed attempt."""


class RepoBusy(RepoUnavailable):
    """A git lock held by another (possibly running) git process."""


class RepoForeign(Exception):
    """The folder contains files but is not a git repo: never touch it."""


class GitError(Exception):
    pass


class GitRepo:
    def __init__(self, path: str, lock_stale_seconds: int = 120):
        self.path = os.path.abspath(path)
        self.lock_stale_seconds = lock_stale_seconds

    # ---------------------------------------------------------------- basics
    def abs(self, rel: str) -> str:
        return os.path.join(self.path, rel)

    def _run(self, *args: str, author: Author | None = None, stdin: bytes | None = None) -> subprocess.CompletedProcess:
        if not os.path.isdir(self.path):
            raise RepoUnavailable(f"Repo-Ordner {self.path} nicht erreichbar")
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
        if author:
            env.update(GIT_AUTHOR_NAME=author.name, GIT_AUTHOR_EMAIL=author.email,
                       GIT_COMMITTER_NAME=author.name, GIT_COMMITTER_EMAIL=author.email)
        cmd = ["git", "-c", "safe.directory=*", "-c", "core.quotePath=false", "-c", "core.hooksPath=/dev/null",
               "-c", "core.fileMode=false", "-c", "core.autocrlf=false",
               # no detached background gc/maintenance: it would outlive the call as an orphan
               "-c", "gc.autoDetach=false", "-c", "maintenance.autoDetach=false", "-C", self.path, *args]
        try:
            return subprocess.run(cmd, input=stdin, capture_output=True, env=env, timeout=GIT_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RepoUnavailable(f"git nicht ausführbar: {exc}") from exc

    def git(self, *args: str, author: Author | None = None, stdin: bytes | None = None) -> str:
        res = self._run(*args, author=author, stdin=stdin)
        if res.returncode != 0:
            err = res.stderr.decode(errors="replace").strip()
            if not os.path.isdir(self.path):
                raise RepoUnavailable(f"Repo-Ordner {self.path} nicht erreichbar")
            raise GitError(f"git {args[0]} failed: {err}")
        return res.stdout.decode(errors="replace")

    def available(self) -> tuple[bool, str]:
        if not os.path.isdir(self.path):
            return False, f"Repo-Ordner {self.path} nicht erreichbar"
        if not os.path.isfile(os.path.join(self.path, ".git", "HEAD")):
            return False, f"Repo-Ordner {self.path} ist kein Git-Repo"
        if not os.access(self.path, os.W_OK):
            return False, f"Repo-Ordner {self.path} ist nicht beschreibbar"
        return True, ""

    # ---------------------------------------------------------------- init
    def init_or_open(self) -> str:
        """'initialized' (empty folder), 'opened' (existing repo). Never creates the folder itself."""
        if not os.path.isdir(self.path):
            raise RepoUnavailable(f"Repo-Ordner {self.path} nicht erreichbar")
        if os.path.exists(os.path.join(self.path, ".git")):
            self.clear_stale_locks()
            return "opened"
        if os.listdir(self.path):
            raise RepoForeign(
                f"Repo-Ordner {self.path} enthält Dateien, ist aber kein Git-Repo. "
                "Bitte einen leeren Ordner oder ein bestehendes Repo der Quelle der Wahrheit konfigurieren.")
        self.git("init", "-q")
        self.git("symbolic-ref", "HEAD", "refs/heads/main")
        paths = ["README.md"]
        with open(self.abs("README.md"), "w", encoding="utf-8") as f:
            f.write(README)
        for d in KIND_DIRS.values():
            os.makedirs(self.abs(d), exist_ok=True)
            keep = f"{d}/.gitkeep"
            open(self.abs(keep), "w").close()
            paths.append(keep)
        self.git("add", "--", *paths)
        self.git("commit", "-q", "-m", "init: source of truth repository", author=PIPELINE)
        logger.info("Initialized source-of-truth repo in %s", self.path)
        return "initialized"

    # ---------------------------------------------------------------- locks
    def clear_stale_locks(self) -> None:
        """Remove git lock files left by a crash once they are older than the wait time;
        a younger lock may belong to a running git process → busy, try again later."""
        gitdir = os.path.join(self.path, ".git")
        locks = glob.glob(os.path.join(gitdir, "*.lock")) + glob.glob(os.path.join(gitdir, "refs", "**", "*.lock"), recursive=True)
        for lock in locks:
            try:
                age = time.time() - os.stat(lock).st_mtime
            except FileNotFoundError:
                continue
            if age < self.lock_stale_seconds:
                raise RepoBusy(f"Git-Sperre {os.path.relpath(lock, self.path)} ist aktiv (seit {int(age)} s)")
            try:
                os.remove(lock)
                logger.warning("Removed orphaned git lock %s (age %ds)", lock, age)
            except FileNotFoundError:
                pass

    # ---------------------------------------------------------------- files
    def read(self, rel: str) -> str | None:
        try:
            with open(self.abs(rel), encoding="utf-8", newline="") as f:
                return f.read()
        except FileNotFoundError:
            if not os.path.isdir(self.path):
                raise RepoUnavailable(f"Repo-Ordner {self.path} nicht erreichbar") from None
            return None
        except UnicodeDecodeError:
            return None

    def exists(self, rel: str) -> bool:
        return os.path.isfile(self.abs(rel))

    def write(self, rel: str, text: str) -> None:
        full = self.abs(rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        tmp = f"{full}.tmp-{os.getpid()}"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, full)

    def remove(self, rel: str) -> None:
        try:
            os.remove(self.abs(rel))
        except FileNotFoundError:
            pass

    def mtime(self, rel: str) -> float | None:
        try:
            return os.stat(self.abs(rel)).st_mtime
        except FileNotFoundError:
            return None

    # ---------------------------------------------------------------- objects
    def hash_text(self, text: str, write: bool = False) -> str:
        args = ["hash-object", "--stdin"] + (["-w"] if write else [])
        return self.git(*args, stdin=text.encode("utf-8")).strip()

    def cat_blob(self, sha: str) -> str | None:
        res = self._run("cat-file", "blob", sha)
        return res.stdout.decode("utf-8", errors="replace") if res.returncode == 0 else None

    def head(self) -> str | None:
        res = self._run("rev-parse", "-q", "--verify", "HEAD")
        return res.stdout.decode().strip() or None

    def get_ref(self, ref: str = SCANNED_REF) -> str | None:
        res = self._run("rev-parse", "-q", "--verify", ref)
        return res.stdout.decode().strip() or None

    def set_ref(self, sha: str, ref: str = SCANNED_REF) -> None:
        self.clear_stale_locks()
        self.git("update-ref", ref, sha)

    # ---------------------------------------------------------------- status
    def status_paths(self) -> list[str]:
        """Uncommitted (modified, deleted, untracked, renamed) paths below the kind folders and deleted/."""
        out = self.git("status", "--porcelain=v1", "-z", "-uall", "--", *WATCH_DIRS)
        parts = out.split("\0")
        paths, i = [], 0
        while i < len(parts):
            entry = parts[i]
            i += 1
            if len(entry) < 4:
                continue
            paths.append(entry[3:])
            if entry[0] in "RC":  # rename/copy: next field is the original path
                paths.append(parts[i])
                i += 1
        return paths

    def tracked_paths(self) -> list[str]:
        out = self.git("ls-files", "-z", "--", *WATCH_DIRS)
        return [p for p in out.split("\0") if p]

    def index_blobs(self) -> dict[str, str]:
        """{path: blob id} of the tracked files below the kind folders and deleted/ (PROJ-120)."""
        out = self.git("ls-files", "-s", "-z", "--", *WATCH_DIRS)
        blobs = {}
        for entry in out.split("\0"):
            if entry:
                meta, path = entry.split("\t", 1)
                blobs[path] = meta.split()[1]
        return blobs

    def untracked_paths(self) -> list[str]:
        out = self.git("ls-files", "-o", "--exclude-standard", "-z", "--", *WATCH_DIRS)
        return [p for p in out.split("\0") if p]

    def deleted_paths(self) -> list[str]:
        """Tracked, but missing in the working tree."""
        out = self.git("ls-files", "-d", "-z", "--", *WATCH_DIRS)
        return [p for p in out.split("\0") if p]

    def last_version(self, rel: str) -> str | None:
        """Last committed content of a path that may have been deleted since (PROJ-120)."""
        res = self._run("rev-list", "-n", "1", "HEAD", "--", rel)
        commit = res.stdout.decode().strip() if res.returncode == 0 else ""
        if not commit:
            return None
        for rev in (commit, commit + "^"):
            out = self._run("show", f"{rev}:{rel}")
            if out.returncode == 0:
                return out.stdout.decode("utf-8", errors="replace")
        return None

    def changed_since(self, rev: str) -> list[str]:
        out = self.git("diff", "--name-only", "-z", "--no-renames", rev, "HEAD", "--", *WATCH_DIRS)
        return [p for p in out.split("\0") if p]

    # ---------------------------------------------------------------- commit
    def commit(self, paths, message: str, author: Author) -> str | None:
        """Commit exactly these paths (additions, changes, deletions). None if nothing changed."""
        paths = sorted({p for p in paths if p})
        if not paths:
            return None
        self.clear_stale_locks()
        tracked = {p for p in self.git("ls-files", "-z", "--", *paths).split("\0") if p}
        present = [p for p in paths if p in tracked or os.path.lexists(self.abs(p))]
        if not present:
            return None
        self.git("add", "-A", "--", *present)
        if self._run("diff", "--cached", "--quiet", "HEAD", "--", *present).returncode == 0:
            return None
        self.git("commit", "-q", "-m", message, "--", *present, author=author)
        return self.head()
