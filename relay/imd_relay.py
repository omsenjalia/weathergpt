"""IMD relay: forwards the backend's IMD calls from a host with a fixed, whitelisted IP.

IMD binds each API key to one caller IP, and Vercel has no fixed egress IP. This relay
runs on a host that does, holds the IMD key and account, mints/renews JWTs itself, and
forwards GET /api/v1/<path> to https://api.imd.gov.in only for callers that present the
shared secret in ``X-Relay-Token``. IMD credentials never leave this host.

Standard library only (Python 3.9+). Configuration, from the environment or a ``.env``
file next to this script:

    IMD_API_KEY       key registered for this host's outgoing IP
    IMD_EMAIL         IMD account; the relay mints 1-hour JWTs with it
    IMD_PASSWORD
    IMD_RELAY_TOKEN   shared secret; the backend sends the same value
    PORT              listen port (falls back to SERVER_PORT, then 43321)

Routes:
    GET /healthz        no secret; reports whether the relay is configured
    GET /api/v1/<path>  needs X-Relay-Token; answered with IMD's status and body

Run:  python imd_relay.py
"""

from __future__ import annotations

import hmac
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

IMD_ORIGIN = "https://api.imd.gov.in"
TOKEN_URL = IMD_ORIGIN + "/api/oauth/token.php"
TIMEOUT_SECONDS = 15.0
REFRESH_MARGIN_SECONDS = 120
_PATH_RE = re.compile(r"^/api/v1/[A-Za-z0-9_\-]+(/[A-Za-z0-9_\-]+)*$")


def load_dotenv(path: str) -> None:
    """Fill unset env vars from KEY=VALUE lines; existing variables win."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _config() -> dict:
    return {
        "api_key": os.getenv("IMD_API_KEY", "").strip(),
        "email": os.getenv("IMD_EMAIL", "").strip(),
        "password": os.getenv("IMD_PASSWORD", ""),
        "relay_token": os.getenv("IMD_RELAY_TOKEN", "").strip(),
    }


def _log(message: str) -> None:
    print(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), message, flush=True)


# --------------------------------------------------------------------------- upstream
def _open(req: urllib.request.Request) -> tuple[int, str, bytes]:
    """Send a request -> (status, content-type, body) for any HTTP status."""
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.headers.get("Content-Type", "") if err.headers else "", err.read()


_token_lock = threading.Lock()
_token: dict = {"value": None, "expires": 0.0}


def _mint() -> tuple[str, float]:
    cfg = _config()
    body = json.dumps({"email": cfg["email"], "password": cfg["password"]}).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "WeatherGPT-Relay/1.0"})
    status, _, raw = _open(req)
    try:
        data = json.loads(raw or b"{}")
    except ValueError:
        data = {}
    token = data.get("access_token") if isinstance(data, dict) else None
    if status >= 400 or not isinstance(token, str) or not token.strip():
        raise RuntimeError(f"IMD token endpoint answered HTTP {status}: {raw[:200]!r}")
    lifetime = data.get("expires_in") if isinstance(data.get("expires_in"), (int, float)) else 3600
    _log(f"IMD token renewed (valid {int(lifetime)} s)")
    return token.strip(), time.time() + float(lifetime)


def current_token(force: bool = False) -> str:
    with _token_lock:
        if force or not _token["value"] or _token["expires"] - time.time() < REFRESH_MARGIN_SECONDS:
            _token["value"], _token["expires"] = _mint()
        return _token["value"]


def forward(path: str, query: str) -> tuple[int, str, bytes]:
    url = IMD_ORIGIN + path + ("?" + query if query else "")

    def call(token: str) -> tuple[int, str, bytes]:
        return _open(urllib.request.Request(url, method="GET", headers={
            "X-API-KEY": _config()["api_key"], "Authorization": f"Bearer {token}",
            "Accept": "application/json", "User-Agent": "WeatherGPT-Relay/1.0"}))

    status, ctype, body = call(current_token())
    if status == 401 and b"token" in body.lower():
        status, ctype, body = call(current_token(force=True))  # rejected early: renew once
    return status, ctype, body


# --------------------------------------------------------------------------- server
class Handler(BaseHTTPRequestHandler):
    server_version = "IMDRelay/1.0"
    sys_version = ""

    def _send(self, status: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj: dict) -> None:
        self._send(status, json.dumps(obj).encode())

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        cfg = _config()
        if parsed.path == "/healthz":
            ready = bool(cfg["api_key"] and cfg["email"] and cfg["password"] and cfg["relay_token"])
            self._json(200 if ready else 503, {"ok": ready})
            return
        presented = self.headers.get("X-Relay-Token", "")
        if not cfg["relay_token"] or not hmac.compare_digest(presented.encode(), cfg["relay_token"].encode()):
            self._json(401, {"error": "relay token rejected"})
            return
        if not _PATH_RE.match(parsed.path):
            self._json(404, {"error": "only /api/v1/<endpoint> is relayed"})
            return
        started = time.perf_counter()
        try:
            status, ctype, body = forward(parsed.path, parsed.query)
        except (OSError, RuntimeError, ValueError) as exc:  # network failure or token minting failed
            _log(f"{parsed.path} failed: {exc}")
            self._json(502, {"error": f"relay could not reach IMD: {exc}"})
            return
        _log(f"{parsed.path} -> {status} ({round((time.perf_counter() - started) * 1000)} ms)")
        self._send(status, body, ctype)

    def do_POST(self) -> None:
        self._json(405, {"error": "GET only"})

    def log_message(self, fmt: str, *args) -> None:  # request lines are logged in do_GET
        pass


def main() -> None:
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    cfg = _config()
    missing = [name for name, key in (("IMD_API_KEY", "api_key"), ("IMD_EMAIL", "email"),
                                      ("IMD_PASSWORD", "password"), ("IMD_RELAY_TOKEN", "relay_token"))
               if not cfg[key]]
    if missing:
        sys.exit(f"Missing configuration: {', '.join(missing)}")
    if len(cfg["relay_token"]) < 24:
        sys.exit("IMD_RELAY_TOKEN is too short; use at least 24 random characters")
    port = int(os.getenv("PORT") or os.getenv("SERVER_PORT") or 43321)
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    _log(f"IMD relay listening on :{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
