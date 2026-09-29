"""IMD relay mode in the backend, and the relay script itself (relay/imd_relay.py)."""

import importlib.util
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from weathergpt import http
from weathergpt.imd import client as imd_client

RELAY_PATH = Path(__file__).resolve().parents[2] / "relay" / "imd_relay.py"
SECRET = "s" * 32


# --------------------------------------------------------------------------- backend side
def test_backend_sends_only_the_relay_secret(upstreams, monkeypatch):
    from weathergpt.config import reset_settings, settings
    calls = []

    def relay(method, url, params, headers, body, timeout):
        calls.append((url, dict(headers)))
        return http.Reply(200, {"content-type": "application/json"}, json.dumps([{"Station": "Ahmedabad"}]).encode())

    monkeypatch.setenv("IMD_RELAY_TOKEN", SECRET)
    monkeypatch.setenv("IMD_BASE_URL", "http://relay.example:43321/api/v1")
    reset_settings()
    http.set_transport(relay)
    assert settings().imd.configured and settings().imd.missing() == []

    resp = imd_client.fetch("current_weather", {"id": "42647"})
    assert resp.rows[0]["Station"] == "Ahmedabad"
    url, headers = calls[-1]
    assert url == "http://relay.example:43321/api/v1/current_wx"
    assert headers["X-Relay-Token"] == SECRET
    assert "X-API-KEY" not in headers and "Authorization" not in headers
    assert imd_client.status()["token_source"] == "relay"


def test_backend_reports_a_rejected_relay_secret(monkeypatch):
    from weathergpt.config import reset_settings
    monkeypatch.setenv("IMD_RELAY_TOKEN", "wrong")
    reset_settings()
    http.set_transport(lambda *a: http.Reply(401, {"content-type": "application/json"},
                                             b'{"error": "relay token rejected"}'))
    with pytest.raises(imd_client.IMDError) as exc:
        imd_client.fetch("port_warning")
    assert exc.value.status == 401 and "relay token rejected" in str(exc.value)


# --------------------------------------------------------------------------- relay side
# These start the relay on 127.0.0.1; its upstream calls are faked, so nothing leaves the machine.
local_socket = pytest.mark.enable_socket


@pytest.fixture
def relay(monkeypatch):
    spec = importlib.util.spec_from_file_location("imd_relay", RELAY_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for key, value in {"IMD_API_KEY": "k", "IMD_EMAIL": "me@example.com", "IMD_PASSWORD": "pw",
                       "IMD_RELAY_TOKEN": SECRET}.items():
        monkeypatch.setenv(key, value)

    seen = []
    state = {"minted": 0, "reject_first": False}

    def fake_open(req):
        seen.append((req.get_method(), req.full_url, {k.lower(): v for k, v in req.header_items()}))
        if req.full_url == mod.TOKEN_URL:
            state["minted"] += 1
            return 200, "application/json", json.dumps({"access_token": f"jwt{state['minted']}", "expires_in": 3600}).encode()
        if state["reject_first"] and seen[-1][2]["authorization"] == "Bearer jwt1":
            return 401, "application/json", b'{"error": "Invalid or expired JWT token"}'
        return 200, "application/json", b'[{"ok": 1}]'

    monkeypatch.setattr(mod, "_open", fake_open)
    server = mod.ThreadingHTTPServer(("127.0.0.1", 0), mod.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def get(path, token=SECRET):
        req = urllib.request.Request(base + path, headers={"X-Relay-Token": token} if token else {})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as err:
            return err.code, err.read()

    yield get, seen, state
    server.shutdown()


@local_socket
def test_relay_forwards_with_imd_credentials(relay):
    get, seen, state = relay
    status, body = get("/api/v1/current_wx?id=42647")
    assert (status, json.loads(body)) == (200, [{"ok": 1}])
    _, url, headers = seen[-1]
    assert url == "https://api.imd.gov.in/api/v1/current_wx?id=42647"
    assert headers["x-api-key"] == "k" and headers["authorization"] == "Bearer jwt1"
    get("/api/v1/port_warning")
    assert state["minted"] == 1          # the token is reused until it nears expiry


@local_socket
def test_relay_renews_a_rejected_token_once(relay):
    get, _, state = relay
    state["reject_first"] = True
    status, _ = get("/api/v1/port_warning")
    assert status == 200 and state["minted"] == 2


@local_socket
def test_relay_rejects_callers_without_the_secret(relay):
    get, seen, _ = relay
    assert get("/api/v1/current_wx", token=None)[0] == 401
    assert get("/api/v1/current_wx", token="nope")[0] == 401
    assert seen == []                    # nothing reached IMD


@local_socket
def test_relay_only_forwards_imd_api_paths(relay):
    get, seen, _ = relay
    for path in ("/api/oauth/token.php", "/api/v1/../oauth/token.php", "/other", "/api/v1/"):
        assert get(path)[0] == 404, path
    assert seen == []
    assert get("/healthz", token=None)[0] == 200
