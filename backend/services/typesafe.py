"""TypeSafe System One client (Jev) — typed, calibrated decisions for code.

TypeSafe is *not* a text-generation model: you send a `state` plus typed questions
(Choice / Score / Noul) and get structured answers with probabilities and a
confidence value that this backend can branch on directly. See
https://docs.typesafe.ai for the full API contract.

Integration policy used across this backend:

* **Best effort, always.** Any failure (missing key, timeout, 4xx/5xx, malformed
  body) makes `evaluate()` return `None`; callers fall back to the deterministic
  keyword/threshold logic that predates this module. TypeSafe refines routing and
  scoring — it never becomes a hard dependency.
* **Keys stay server-side.** `TYPESAFE_API_KEY` is only read here. The Flutter app
  talks to this backend and never sees the key.
* **One call per decision point.** Questions are batched into a single request
  (they are evaluated in parallel and in isolation server-side) following the
  "speculative fan-out" pattern: adding questions barely changes latency.
* **Confidence gates actions.** Answers below ``TYPESAFE_*_MIN_CONFIDENCE`` are
  treated as "no opinion" and the deterministic path decides.

Environment
-----------
    TYPESAFE_API_KEY                Bearer key; absent or "your_*" disables the module
    TYPESAFE_ENABLED                "0" hard-disables even when a key is present
    TYPESAFE_MODEL                  model id (default: jev-latest)
    TYPESAFE_BASE_URL               API base (default: https://api.typesafe.ai/v1)
    TYPESAFE_TIMEOUT_SECONDS        per-attempt timeout (default 4)
    TYPESAFE_MAX_ATTEMPTS           attempts for retryable failures (default 3)
    TYPESAFE_RETRY_BACKOFF_SECONDS  base backoff between retries (default 0.4)
"""

from __future__ import annotations

import os
import random
import time
from typing import Any, Callable

import httpx

from state import log_event

DEFAULT_BASE_URL = "https://api.typesafe.ai/v1"
DEFAULT_MODEL = "jev-latest"


# --------------------------------------------------------------------------- #
# Question builders — thin dicts mirroring the System One request schema.
# --------------------------------------------------------------------------- #
def choice(instructions: str, criteria: dict[str, str]) -> dict[str, Any]:
    """A Choice question: pick one option from a closed, described set."""
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


def score(instructions: str, levels: list[str]) -> dict[str, Any]:
    """A Score question: rate the state against ordered, descriptive levels."""
    return {"type": "score", "instructions": instructions, "criteria": levels}


def noul(instructions: str) -> dict[str, Any]:
    """A Noul question: return the probability that a yes/no statement holds."""
    return {"type": "noul", "instructions": instructions}


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
def api_key() -> str:
    return (os.getenv("TYPESAFE_API_KEY") or "").strip()


def model_name() -> str:
    return (os.getenv("TYPESAFE_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL


def base_url() -> str:
    return (os.getenv("TYPESAFE_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/") or DEFAULT_BASE_URL


def is_enabled() -> bool:
    """True when a real key is configured and the module is not hard-disabled."""
    if os.getenv("TYPESAFE_ENABLED", "1") == "0":
        return False
    key = api_key()
    return bool(key) and not key.startswith("your_")


def _default_client(timeout: float) -> httpx.Client:
    return httpx.Client(
        base_url=base_url(),
        headers={"Authorization": f"Bearer {api_key()}"},
        timeout=timeout,
    )


# Tests monkeypatch this to inject an httpx.MockTransport-backed client.
_client_factory: Callable[[float], httpx.Client] = _default_client


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
def evaluate(
    state: str,
    questions: dict[str, dict[str, Any]],
    *,
    timeout: float | None = None,
    label: str = "decision",
) -> dict[str, Any] | None:
    """POST one System One request; return ``{"answers", "model", "usage", "latency_ms", "attempts"}`` or None.

    Never raises. Retryable failures (429 / 5xx / network) are retried with
    exponential backoff; other 4xx fail fast. All questions are evaluated in
    parallel and in isolation against the same state, so batching is free.
    """
    if not is_enabled() or not (state or "").strip() or not questions:
        return None

    attempts = max(1, int(os.getenv("TYPESAFE_MAX_ATTEMPTS", "3")))
    per_attempt = float(timeout if timeout is not None else os.getenv("TYPESAFE_TIMEOUT_SECONDS", "4"))
    backoff = float(os.getenv("TYPESAFE_RETRY_BACKOFF_SECONDS", "0.4"))
    payload = {"state": state[:8000], "model": model_name(), "questions": questions}

    started = time.perf_counter()
    last_error = "unknown"
    try:
        with _client_factory(per_attempt) as client:
            for attempt in range(1, attempts + 1):
                try:
                    response = client.post("/systemone", json=payload)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error = type(exc).__name__
                else:
                    if response.status_code == 200:
                        body = response.json()
                        answers = body.get("answers")
                        if isinstance(answers, dict):
                            result = {
                                "answers": answers,
                                "model": body.get("model") or model_name(),
                                "usage": body.get("usage") or {},
                                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                                "attempts": attempt,
                            }
                            if os.getenv("TYPESAFE_LOG_CALLS", "0") == "1":
                                log_event("INFO", f"[typesafe:{label}] ok",
                                          {"latency_ms": result["latency_ms"],
                                           "attempts": attempt})
                            return result
                        last_error = "malformed response body"
                        break  # a 200 with a bad body will not heal on retry
                    last_error = f"HTTP {response.status_code}"
                    if response.status_code != 429 and response.status_code < 500:
                        break  # non-retryable client error
                if attempt < attempts:
                    time.sleep(backoff * (2 ** (attempt - 1)) + random.uniform(0.0, 0.15))
    except Exception as exc:  # last-resort guard: TypeSafe must never break a request
        last_error = f"{type(exc).__name__}: {exc}"

    log_event("WARN", f"[typesafe:{label}] evaluation failed: {last_error}",
              {"latency_ms": round((time.perf_counter() - started) * 1000, 1), "attempts": attempts})
    return None


# --------------------------------------------------------------------------- #
# Answer accessors — defensive by design; bad payloads read as "no opinion".
# --------------------------------------------------------------------------- #
def _answer(answers: dict[str, Any] | None, key: str) -> dict[str, Any] | None:
    if not isinstance(answers, dict):
        return None
    value = answers.get(key)
    return value if isinstance(value, dict) else None


def _number(answer: dict[str, Any] | None, key: str) -> float | None:
    if not answer:
        return None
    try:
        value = float(answer.get(key))
    except (TypeError, ValueError):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def choice_of(answers: dict[str, Any] | None, key: str) -> str | None:
    answer = _answer(answers, key)
    value = answer.get("choice") if answer else None
    return str(value) if value else None


def score_of(answers: dict[str, Any] | None, key: str) -> float | None:
    return _number(_answer(answers, key), "score")


def noul_of(answers: dict[str, Any] | None, key: str) -> float | None:
    return _number(_answer(answers, key), "noul")


def confidence_of(answers: dict[str, Any] | None, key: str) -> float | None:
    return _number(_answer(answers, key), "confidence")


def probabilities_of(answers: dict[str, Any] | None, key: str) -> dict[str, float]:
    answer = _answer(answers, key)
    raw = answer.get("probabilities") if answer else None
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for name, probability in raw.items():
        try:
            out[str(name)] = float(probability)
        except (TypeError, ValueError):
            continue
    return out
