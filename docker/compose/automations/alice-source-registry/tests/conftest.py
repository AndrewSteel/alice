"""
Shared fixtures.

Integration tests need a PostgreSQL with sql/init-schema.sql applied; they are
skipped unless TEST_POSTGRES_DSN is set (scripts/test-services.sh does that).
The source-of-truth repo is a temporary git repo below pytest's tmp_path.
Redis is replaced by an in-memory fake (a real Redis is used only where
TEST_REDIS_URL is set).
"""
import os
import subprocess

import pytest

from app.config import Settings
from app.service import Registry

DSN = os.environ.get("TEST_POSTGRES_DSN")
DEFAULT_STAGES = ("detect", "extract", "classify", "database", "rag", "wiki", "thumbnail")


class FakeRedis:
    """Just the sorted-set subset used by app.workqueue."""

    def __init__(self):
        self.z: dict[str, dict[str, float]] = {}
        self.kv: dict[str, str] = {}

    async def zadd(self, key, mapping):
        self.z.setdefault(key, {}).update(mapping)

    async def expire(self, key, ttl):
        return True

    async def zrem(self, key, member):
        self.z.get(key, {}).pop(member, None)

    async def zrangebyscore(self, key, lo, hi, start=0, num=None):
        items = sorted((s, m) for m, s in self.z.get(key, {}).items() if s <= hi)
        items = [m for _, m in items][start:]
        return items[:num] if num is not None else items

    async def exists(self, key):
        return int(key in self.kv or key in self.z)

    async def set(self, key, value, ex=None):
        self.kv[key] = value

    async def delete(self, key):
        self.z.pop(key, None)
        self.kv.pop(key, None)

    async def flushall(self):
        self.z.clear()
        self.kv.clear()


def git(repo, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "safe.directory=*", *args],
                          capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo_dir(tmp_path):
    d = tmp_path / "sot"
    d.mkdir()
    return d


@pytest.fixture
async def pool():
    if not DSN:
        pytest.skip("TEST_POSTGRES_DSN not set")
    import asyncpg

    p = await asyncpg.create_pool(dsn=DSN, min_size=1, max_size=10)
    async with p.acquire() as con:
        await con.execute("TRUNCATE alice.sources CASCADE")
        await con.execute("DELETE FROM alice.pipeline_stages WHERE NOT (name = ANY($1::text[]))",
                          list(DEFAULT_STAGES))
    yield p
    await p.close()


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def make_registry(pool, repo_dir, fake_redis):
    async def make(redis=fake_redis, **overrides) -> Registry:
        settings = Settings(repo_path=str(repo_dir), postgres_dsn=DSN, **overrides)
        reg = Registry(settings, pool, redis)
        await reg.startup()
        return reg
    return make


@pytest.fixture
async def reg(make_registry):
    return await make_registry()
