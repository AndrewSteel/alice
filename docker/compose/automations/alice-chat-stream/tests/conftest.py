"""
Set up module stubs so streaming.py can be imported in tests
without the full Docker environment.
"""
import sys
import types
from unittest.mock import MagicMock

# Stub heavy dependencies
for mod_name in ["httpx", "asyncpg", "jwt", "cryptography",
                 "prometheus_client", "fastapi", "pydantic", "uvicorn",
                 "fastapi.responses", "fastapi.middleware.cors",
                 "fastapi.security"]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

# Register the `app` package pointing to the real directory
import importlib.util
from pathlib import Path

app_dir = Path(__file__).parent.parent / "app"

# Create the `app` package in sys.modules
app_pkg = types.ModuleType("app")
app_pkg.__path__ = [str(app_dir)]
app_pkg.__package__ = "app"
sys.modules["app"] = app_pkg

# Stub app.metrics and app.tools so streaming.py's relative import works
sys.modules["app.metrics"] = MagicMock()
sys.modules["app.tools"] = MagicMock()
sys.modules["app.auth"] = MagicMock()
