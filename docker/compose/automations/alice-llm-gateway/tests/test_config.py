import pytest

from app.config import find_client, parse_clients


def test_parse_clients_and_tiers():
    clients = parse_clients(
        "# comment\n"
        "chat interactive k1\n"
        "\n"
        "n8n background k2  # trailing comment\n"
        "newsvc priority k3\n"
    )
    assert [(c.name, c.tier) for c in clients] == [
        ("chat", "interactive"),
        ("n8n", "background"),
        ("newsvc", "background"),  # unknown tier never becomes interactive
    ]


@pytest.mark.parametrize("text", ["", "# only comments\n", "chat interactive\n",
                                  "a interactive k\nb background k\n",
                                  "a interactive k1\na background k2\n"])
def test_parse_clients_rejects_bad_files(text):
    with pytest.raises(ValueError):
        parse_clients(text)


def test_find_client():
    clients = parse_clients("chat interactive k1\nn8n background k2\n")
    assert find_client(clients, "k2").name == "n8n"
    assert find_client(clients, "k") is None
    assert find_client(clients, "k1x") is None
