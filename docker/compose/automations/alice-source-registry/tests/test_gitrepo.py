"""Unit tests with real git: repo init / reuse / foreign folder, orphaned locks (AK-1–3, AK-32)."""
import os
import time

import pytest

from app import gitrepo
from app.gitrepo import GitRepo, RepoBusy, RepoForeign, RepoUnavailable

from .conftest import git


def test_init_empty_folder(repo_dir):
    assert GitRepo(str(repo_dir)).init_or_open() == "initialized"
    for d in ("documents", "images", "emails", "audio", "video"):
        assert (repo_dir / d).is_dir()
    readme = (repo_dir / "README.md").read_text()
    for topic in ("Ordnerstruktur", "<id>-<slug>.md", "Frontmatter", "Hand-Korrekturen", "manual"):
        assert topic in readme
    log = git(repo_dir, "log", "--format=%an|%s").strip().splitlines()
    assert log == ["Alice ETL|init: source of truth repository"]
    assert git(repo_dir, "status", "--porcelain") == ""


def test_existing_repo_is_reused_unchanged(repo_dir):
    GitRepo(str(repo_dir)).init_or_open()
    (repo_dir / "documents" / "x.md").write_text("hand\n")
    head = git(repo_dir, "rev-parse", "HEAD")
    readme = (repo_dir / "README.md").read_bytes()
    assert GitRepo(str(repo_dir)).init_or_open() == "opened"
    assert git(repo_dir, "rev-parse", "HEAD") == head
    assert (repo_dir / "README.md").read_bytes() == readme
    assert (repo_dir / "documents" / "x.md").read_text() == "hand\n"


def test_foreign_folder_is_rejected_and_untouched(repo_dir):
    (repo_dir / "private.txt").write_text("data")
    with pytest.raises(RepoForeign, match="kein Git-Repo"):
        GitRepo(str(repo_dir)).init_or_open()
    assert os.listdir(repo_dir) == ["private.txt"]


def test_missing_folder_is_unavailable_and_not_created(tmp_path):
    missing = tmp_path / "nas" / "sot"
    with pytest.raises(RepoUnavailable):
        GitRepo(str(missing)).init_or_open()
    assert not missing.exists()


def test_orphaned_lock_removed_after_wait_time(repo_dir):
    repo = GitRepo(str(repo_dir), lock_stale_seconds=120)
    repo.init_or_open()
    lock = repo_dir / ".git" / "index.lock"
    lock.write_text("")
    old = time.time() - 300
    os.utime(lock, (old, old))
    (repo_dir / "documents" / "a.md").write_text("a\n")
    assert repo.commit(["documents/a.md"], "test", gitrepo.PIPELINE)
    assert not lock.exists()


def test_young_lock_means_busy_and_is_kept(repo_dir):
    repo = GitRepo(str(repo_dir), lock_stale_seconds=120)
    repo.init_or_open()
    lock = repo_dir / ".git" / "index.lock"
    lock.write_text("")
    (repo_dir / "documents" / "a.md").write_text("a\n")
    with pytest.raises(RepoBusy):
        repo.commit(["documents/a.md"], "test", gitrepo.PIPELINE)
    assert lock.exists()


def test_orphaned_lock_on_startup(repo_dir):
    repo = GitRepo(str(repo_dir), lock_stale_seconds=1)
    repo.init_or_open()
    lock = repo_dir / ".git" / "index.lock"
    lock.write_text("")
    old = time.time() - 10
    os.utime(lock, (old, old))
    assert repo.init_or_open() == "opened"
    assert not lock.exists()
