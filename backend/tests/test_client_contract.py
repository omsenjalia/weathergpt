"""Every path the clients call must exist (weathergpt-app, weathergpt-android, web)."""

import re
from pathlib import Path

from weathergpt.app import create_app

# src/core/config/apiEndpoints.ts in both mobile apps + the web app's api.js
CLIENT_PATHS = {
    "/chat", "/weather", "/health", "/dev", "/dev/sandbox", "/advisory", "/historical", "/comparison",
    "/v2/weather", "/v2/weather/health", "/v2/weather/catalog", "/v2/weather/series",
    "/v2/speech/health", "/v2/speech/tts", "/v2/speech/asr",
}


def test_every_client_path_is_served():
    served = set(create_app().openapi()["paths"])
    assert CLIENT_PATHS <= served


def test_declared_endpoints_when_app_source_is_present():
    """In the monorepo (android) and submodule (app) layouts the app's endpoint file sits nearby."""
    here = Path(__file__).resolve()
    candidates = [here.parents[2] / "app/src/core/config/apiEndpoints.ts",   # weathergpt-android
                  here.parents[3] / "src/core/config/apiEndpoints.ts"]       # weathergpt-app/backend/backend
    served = set(create_app().openapi()["paths"])
    for path in candidates:
        if path.exists():
            declared = set(re.findall(r'^\s+\w+: "(/[^"]*)",$', path.read_text(encoding="utf-8"), re.MULTILINE))
            assert declared and declared <= served, declared - served
