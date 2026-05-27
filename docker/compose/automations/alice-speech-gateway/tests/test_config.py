"""Tests for the YAML config loaders — device mapping + interrupt phrases."""
from app import config


def test_load_device_mapping_valid(tmp_path):
    f = tmp_path / "devices.yaml"
    f.write_text(
        "devices:\n"
        '  "voice-living": 1\n'
        '  "voice-office": 2\n'
    )
    mapping = config.load_device_mapping(str(f))
    assert mapping == {"voice-living": 1, "voice-office": 2}


def test_load_device_mapping_missing_file_returns_empty():
    assert config.load_device_mapping("/nonexistent/path.yaml") == {}


def test_load_device_mapping_skips_invalid_user_id(tmp_path):
    f = tmp_path / "devices.yaml"
    f.write_text(
        "devices:\n"
        '  "good": 5\n'
        '  "bad": "not-a-number"\n'
    )
    mapping = config.load_device_mapping(str(f))
    assert mapping == {"good": 5}


def test_load_interrupt_phrases_valid(tmp_path):
    f = tmp_path / "phrases.yaml"
    f.write_text("phrases:\n  - Stop\n  - Warte Mal\n")
    phrases = config.load_interrupt_phrases(str(f))
    # phrases are normalised to lowercase
    assert phrases == ["stop", "warte mal"]


def test_load_interrupt_phrases_missing_file_uses_fallback():
    phrases = config.load_interrupt_phrases("/nonexistent/phrases.yaml")
    assert "stop" in phrases
    assert len(phrases) > 0


def test_load_interrupt_phrases_empty_uses_fallback(tmp_path):
    f = tmp_path / "phrases.yaml"
    f.write_text("phrases: []\n")
    phrases = config.load_interrupt_phrases(str(f))
    assert len(phrases) > 0
