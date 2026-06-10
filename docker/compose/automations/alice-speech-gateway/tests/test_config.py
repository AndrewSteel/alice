"""Tests for the YAML config loaders — device mapping + interrupt phrases."""
from app import config


def test_load_device_mapping_valid(tmp_path):
    f = tmp_path / "devices.yaml"
    f.write_text(
        "devices:\n"
        '  "192.168.1.10":\n'
        '    user_id: "uuid-living"\n'
        '    name: "Wohnzimmer"\n'
        '    room: "Wohnzimmer"\n'
        '  "192.168.1.11":\n'
        '    user_id: "uuid-office"\n'
        '    name: "Büro"\n'
        '    room: "Büro"\n'
    )
    mapping = config.load_device_mapping(str(f))
    assert mapping == {
        "192.168.1.10": config.Device(user_id="uuid-living", name="Wohnzimmer", room="Wohnzimmer"),
        "192.168.1.11": config.Device(user_id="uuid-office", name="Büro", room="Büro"),
    }


def test_load_device_mapping_defaults_name_and_room(tmp_path):
    """name defaults to the IP and room to empty when omitted."""
    f = tmp_path / "devices.yaml"
    f.write_text(
        "devices:\n"
        '  "192.168.1.10":\n'
        '    user_id: "uuid-1"\n'
    )
    mapping = config.load_device_mapping(str(f))
    assert mapping == {
        "192.168.1.10": config.Device(user_id="uuid-1", name="192.168.1.10", room=""),
    }


def test_load_device_mapping_missing_file_returns_empty():
    assert config.load_device_mapping("/nonexistent/path.yaml") == {}


def test_load_device_mapping_skips_entry_without_user_id(tmp_path):
    f = tmp_path / "devices.yaml"
    f.write_text(
        "devices:\n"
        '  "192.168.1.10":\n'
        '    user_id: "uuid-good"\n'
        '    name: "Good"\n'
        '  "192.168.1.11":\n'
        '    name: "Missing user_id"\n'
    )
    mapping = config.load_device_mapping(str(f))
    assert mapping == {
        "192.168.1.10": config.Device(user_id="uuid-good", name="Good", room=""),
    }


def test_load_device_mapping_skips_non_mapping_entry(tmp_path):
    """An old flat-format entry (IP -> string) is rejected, not crashed on."""
    f = tmp_path / "devices.yaml"
    f.write_text(
        "devices:\n"
        '  "192.168.1.10": "just-a-uuid-string"\n'
    )
    mapping = config.load_device_mapping(str(f))
    assert mapping == {}


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
