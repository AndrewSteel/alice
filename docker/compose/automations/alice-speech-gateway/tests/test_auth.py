"""Tests for JWT auth — token verification and WS token extraction."""
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app import auth


@pytest.fixture(scope="module")
def keypair(tmp_path_factory):
    """Generate an RSA keypair and point auth at the public key file."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    pub_path = tmp_path_factory.mktemp("keys") / "jwt_public.pem"
    pub_path.write_text(public_pem)

    # Reset cached key and repoint config at the test public key.
    auth._public_key = None
    auth.config.JWT_PUBLIC_KEY_PATH = str(pub_path)
    yield private_pem, public_pem
    auth._public_key = None


def _make_token(private_pem: str, *, user_id="7", exp_offset=300) -> str:
    now = int(time.time())
    return jwt.encode(
        {"user_id": user_id, "username": "tester", "role": "user",
         "iat": now, "exp": now + exp_offset},
        private_pem,
        algorithm="RS256",
    )


def test_valid_token_returns_payload(keypair):
    private_pem, _ = keypair
    payload = auth.verify_token(_make_token(private_pem))
    assert payload["user_id"] == "7"
    assert payload["role"] == "user"


def test_missing_token_raises():
    with pytest.raises(auth.AuthError):
        auth.verify_token(None)
    with pytest.raises(auth.AuthError):
        auth.verify_token("")


def test_expired_token_raises(keypair):
    private_pem, _ = keypair
    expired = _make_token(private_pem, exp_offset=-10)
    with pytest.raises(auth.AuthError, match="abgelaufen"):
        auth.verify_token(expired)


def test_garbage_token_raises(keypair):
    with pytest.raises(auth.AuthError, match="ungültig"):
        auth.verify_token("not.a.jwt")


def test_token_signed_with_wrong_key_raises(keypair):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_pem = other.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    forged = _make_token(other_pem)
    with pytest.raises(auth.AuthError):
        auth.verify_token(forged)


def test_extract_ws_token_from_bearer_header():
    token = auth.extract_ws_token({"authorization": "Bearer abc123"}, {})
    assert token == "abc123"


def test_extract_ws_token_from_query_param():
    token = auth.extract_ws_token({}, {"token": "xyz789"})
    assert token == "xyz789"


def test_extract_ws_token_header_wins_over_query():
    token = auth.extract_ws_token(
        {"authorization": "Bearer fromheader"}, {"token": "fromquery"}
    )
    assert token == "fromheader"


def test_extract_ws_token_none_when_absent():
    assert auth.extract_ws_token({}, {}) is None
