"""Shared backend services used by both clients (web `weathergpt`, mobile `weathergpt-app`).

- `open_meteo`  — thin Open-Meteo client + WMO code table (single source of truth)
- `fusion`      — multi-provider current-conditions fusion engine
- `response`    — output gate: strips chain-of-thought, validates widgets
- `chat`        — routing policy: client detect, language normalise, fast/agent/fallback
"""
