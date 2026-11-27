"""Vision calls through the gateway (fake), prompts and answers."""
import httpx
import pytest

from app.errors import TransientError
from app.vision import VisionUnavailable, clean_title

from .conftest import KEY, LONG_DESCRIPTION

JPEG = "AAAA"


async def test_one_call_with_background_key_and_no_thinking(vision, gateway):  # AK-18, AK-21
    from .conftest import make_image  # noqa: F401  (images not needed: the fake ignores the bytes)

    gateway.answers.append({"description": LONG_DESCRIPTION, "title": "Strand", "text_in_image": ""})
    d = await vision.describe([_jpeg()], True, None)
    assert len(gateway.requests) == 1
    r = gateway.requests[0]
    assert r["auth"] == f"Bearer {KEY}" and r["template_kwargs"] == {"enable_thinking": False}
    assert r["model"] == "qwen-vision"
    p = r["prompt"]
    assert "Deutsch" in p and "title" in p and "text_in_image" in p and "Abschrift" in p
    assert "rate keine Namen" in p and "Identifiziere keine Personen" in p
    assert "800 bis 1500 Zeichen" in p
    assert "Aufnahmeort laut GPS" not in p  # AK-19: no place, no hint
    assert d.model == "qwen3.8-27b" and d.title == "Strand" and d.text == ""


async def test_place_as_hint(vision, gateway):  # AK-19
    await vision.describe([_jpeg()], True, {"city": "Rimini", "country": "Italien", "district": None})
    assert "Aufnahmeort laut GPS (Hinweis): Rimini, Italien." in gateway.requests[0]["prompt"]


async def test_model_name_falls_back_to_configured(vision, gateway):
    gateway.model = None
    assert (await vision.describe([_jpeg()], True, None)).model == "qwen-vision"


async def test_text_in_image(vision, gateway):  # AK-20
    gateway.answers.append({"description": LONG_DESCRIPTION, "title": "Schild", "text_in_image": "Strand\nRimini"})
    assert (await vision.describe([_jpeg()], True, None)).text == "Strand\nRimini"


async def test_panorama_tiles_and_merge(vision, gateway):  # AK-23
    gateway.answers.extend([{"description": f"Ausschnitt Nummer {i} mit Bergen und Himmel.", "text_in_image":
                             "HOTEL" if i == 3 else ""} for i in range(1, 9)])
    gateway.answers.append({"description": LONG_DESCRIPTION, "title": "Bergpanorama", "text_in_image": "HOTEL"})
    d = await vision.describe([_jpeg()] * 8, True, None)
    assert len(gateway.requests) == 9
    assert [len(r["images"]) for r in gateway.requests] == [1] * 8 + [0]
    assert [r["prompt"].split(" eines")[0] for r in gateway.requests[:8]] == [
        f"Dies ist Ausschnitt {i} von 8" for i in range(1, 9)]
    merge = gateway.requests[8]["prompt"]
    assert "von links nach rechts" in merge and "Ausschnitt 8: Ausschnitt Nummer 8" in merge
    assert "Text in Ausschnitt 3:\nHOTEL" in merge
    assert d.title == "Bergpanorama" and d.text == "HOTEL"


async def test_panorama_portrait_direction(vision, gateway):
    await vision.describe([_jpeg()] * 3, False, None)
    assert "von oben nach unten" in gateway.requests[-1]["prompt"]


async def test_failed_tile_fails_everything(vision, gateway):  # AK-24
    gateway.answers.extend([gateway.tile_default, httpx.ReadTimeout("slow")])
    with pytest.raises(VisionUnavailable):
        await vision.describe([_jpeg()] * 8, True, None)
    assert len(gateway.requests) == 2  # no further tiles, no merge


@pytest.mark.parametrize("answer,exc", [
    ("", TransientError),                                                  # empty
    ("Das ist kein JSON", TransientError),                                 # unusable
    ({"description": LONG_DESCRIPTION, "title": ""}, TransientError),      # EC-7: no title
    ({"description": "", "title": "Strand"}, TransientError),
    (httpx.ReadTimeout("slow"), VisionUnavailable),                       # timeout
])
async def test_unusable_answers(vision, gateway, answer, exc):  # AK-26, EC-7
    gateway.answers.append(answer)
    with pytest.raises(exc):
        await vision.describe([_jpeg()], True, None)


async def test_gateway_down_or_overloaded(vision, gateway):  # AK-26
    gateway.down = True
    with pytest.raises(VisionUnavailable):
        await vision.describe([_jpeg()], True, None)
    gateway.down, gateway.status = False, 503
    with pytest.raises(VisionUnavailable):
        await vision.describe([_jpeg()], True, None)


async def test_answer_in_code_fence_and_think_block(vision, gateway):
    gateway.answers.append('<think>x</think>```json\n{"description": "%s", "title": "Strand"}\n```' % LONG_DESCRIPTION)
    assert (await vision.describe([_jpeg()], True, None)).title == "Strand"


def test_clean_title():
    assert clean_title("  „Strand – Abend“. ") == "Strand - Abend"
    assert len(clean_title("Wort " * 40)) <= 80


def _jpeg() -> str:
    import base64
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()
