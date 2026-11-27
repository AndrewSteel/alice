"""Old Weaviate lookup, Geoapify and the rate limit."""
import asyncio
import time

import pytest

from app.errors import TransientError
from app.geo import RateLimiter, WeaviateUnavailable, old_hash

H = "ab" * 32


async def test_takeover_first_filled_object(weaviate, weaviate_mock):  # AK-10, EC-5, EC-6
    weaviate_mock.objects[H] = [{"country": None, "country_code": None, "city": None, "district": None},
                                {"country": "Italien", "country_code": "it", "city": None, "district": None},
                                {"country": "Frankreich", "country_code": "FR", "city": "Paris", "district": None}]
    loc = await weaviate.lookup("sha256:" + H)
    assert loc == {"country": "Italien", "country_code": "IT", "city": None, "district": None}
    assert f'valueText: "{H}"' in weaviate_mock.queries[0] and "file_hash" in weaviate_mock.queries[0]
    assert weaviate_mock.methods == ["POST /v1/graphql"]  # read only (AK-40)


async def test_no_object_or_no_place(weaviate, weaviate_mock):  # AK-11
    assert await weaviate.lookup("sha256:" + H) is None
    weaviate_mock.objects[H] = [{"country": "", "city": None}]
    assert await weaviate.lookup("sha256:" + H) is None


async def test_weaviate_down(weaviate, weaviate_mock):  # AK-12
    weaviate_mock.down = True
    with pytest.raises(WeaviateUnavailable):
        await weaviate.lookup("sha256:" + H)


def test_old_hash():
    assert old_hash("sha256:" + H.upper()) == H
    assert old_hash(H) == H
    assert old_hash("sha256:1234") is None and old_hash('x" } }') is None


async def test_geoapify_german(geoapify, geoapify_mock):  # AK-11
    loc = await geoapify.reverse(44.0596, 12.5683)
    assert loc == {"country": "Italien", "country_code": "IT", "city": "Rimini", "district": "Marina Centro"}
    p = geoapify_mock.requests[0]["params"]
    assert p["lang"] == "de" and p["format"] == "json" and p["apiKey"] == "test-geo-key"
    assert float(p["lat"]) == pytest.approx(44.0596)


async def test_geoapify_sea_without_city(geoapify, geoapify_mock):  # EC-4
    geoapify_mock.result = {"country": "Italien", "country_code": "it"}
    assert (await geoapify.reverse(44.1, 12.9))["city"] is None
    geoapify_mock.result = None
    assert await geoapify.reverse(44.1, 12.9) == {"country": None, "country_code": None, "city": None,
                                                  "district": None}


async def test_geoapify_error(geoapify, geoapify_mock):  # AK-16
    geoapify_mock.status = 500
    with pytest.raises(TransientError):
        await geoapify.reverse(1.0, 2.0)


async def test_rate_limit_five_per_second():  # AK-15
    limiter = RateLimiter(5)
    stamps = []
    for _ in range(12):
        await limiter.wait()
        stamps.append(time.monotonic())
    for i, t in enumerate(stamps):
        assert sum(1 for s in stamps if t <= s < t + 1.0) <= 5, i
    assert stamps[-1] - stamps[0] >= 2.0


async def test_rate_limit_under_concurrency():
    limiter = RateLimiter(5)
    stamps = []

    async def call():
        await limiter.wait()
        stamps.append(time.monotonic())
    await asyncio.gather(*[call() for _ in range(11)])
    stamps.sort()
    for t in stamps:
        assert sum(1 for s in stamps if t <= s < t + 1.0) <= 5
