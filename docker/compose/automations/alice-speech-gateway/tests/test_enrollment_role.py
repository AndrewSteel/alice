"""PROJ-121: voice enrollment creates household members ('haushalt') or guests."""
from app import enrollment


def test_member_enrollment_creates_haushalt():
    assert enrollment.is_enrollment_intent("Lass uns einen neuen Nutzer einrollen") == (True, "haushalt")


def test_guest_enrollment_creates_guest():
    assert enrollment.is_enrollment_intent("Neuen Gast aufnehmen") == (True, "guest")


def test_no_enrollment():
    assert enrollment.is_enrollment_intent("Schalte das Licht ein") == (False, "")
