"""Test setup for alice-auth: throwaway RSA key pair, optional test DB."""
import os
import subprocess
import tempfile

import pytest

_KEY_DIR = tempfile.mkdtemp(prefix="alice-auth-test-")
_PRIV = os.path.join(_KEY_DIR, "jwt_private.pem")
_PUB = os.path.join(_KEY_DIR, "jwt_public.pem")
subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-out", _PRIV], check=True, capture_output=True)
subprocess.run(["openssl", "pkey", "-in", _PRIV, "-pubout", "-out", _PUB], check=True, capture_output=True)

os.environ["JWT_PRIVATE_KEY_PATH"] = _PRIV
os.environ["JWT_PUBLIC_KEY_PATH"] = _PUB
# Integration tests only with the throwaway database (scripts/test-services.sh).
os.environ["POSTGRES_CONNECTION"] = os.environ.get("TEST_POSTGRES_DSN", "")

import main  # noqa: E402  (env must be set before import)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    main._rate_buckets.clear()
    return TestClient(main.app)


def token(role: str, user_id: str = "a1210000-0000-0000-0000-000000000001") -> str:
    return main._create_jwt(user_id, f"t-{role}", role)
