"""The place lookup against a real Weaviate (test-weaviate, collection `Image` with the properties of
schemas/image.json, vectorizer none). Skipped without TEST_WEAVIATE_URL, e.g.:

  docker compose -p sf-alice-test -f docker/test/compose.test.yml --profile weaviate up -d --wait test-weaviate
  TEST_WEAVIATE_URL=http://test-weaviate:8080 pytest tests/test_weaviate_live.py
"""
import json
import os
import pathlib

import httpx
import pytest

from app.geo import OldWeaviate

URL = os.environ.get("TEST_WEAVIATE_URL")
SCHEMA = pathlib.Path(__file__).resolve().parents[5] / "schemas" / "image.json"
H1, H2 = "1" * 64, "2" * 64


@pytest.fixture
async def weaviate_live():
    if not URL:
        pytest.skip("TEST_WEAVIATE_URL not set")
    schema = json.loads(SCHEMA.read_text())
    schema["vectorizer"] = "none"
    schema.pop("moduleConfig", None)
    for p in schema["properties"]:
        p.pop("moduleConfig", None)
    async with httpx.AsyncClient(base_url=URL, timeout=30) as c:
        await c.delete("/v1/schema/Image")
        r = await c.post("/v1/schema", json=schema)
        assert r.status_code == 200, r.text
        objs = [{"file_hash": H1, "country": None, "city": None},
                {"file_hash": H1, "country": "Italien", "country_code": "IT", "city": "Rimini", "district": "Centro"},
                {"file_hash": H2, "country": "Deutschland", "country_code": "DE"}]
        for o in objs:
            r = await c.post("/v1/objects", json={"class": "Image", "properties": {k: v for k, v in o.items() if v},
                                                  "vector": [0.1, 0.2, 0.3]})
            assert r.status_code == 200, r.text
        yield
        await c.delete("/v1/schema/Image")


async def test_lookup_against_real_weaviate(weaviate_live):  # AK-10, EC-5, EC-6
    w = OldWeaviate(URL, 10)
    try:
        assert (await w.lookup("sha256:" + H1))["city"] == "Rimini"
        assert await w.lookup("sha256:" + H2) == {"country": "Deutschland", "country_code": "DE", "city": None,
                                                  "district": None}
        assert await w.lookup("sha256:" + "3" * 64) is None
    finally:
        await w.close()
