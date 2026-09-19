"""System 1: one HTTP request per page, thirty questions in it, a probability per answer. No text comes back."""

from __future__ import annotations

import http.client
import json
import os
import threading
import time
from urllib.parse import urlparse

URL = os.environ.get("JEV_URL", "https://openrouter.ai/api/alpha/decisions")
MODEL = os.environ.get("JEV_MODEL", "jev-latest")
KEY_ENV = ("JEV_API_KEY", "OPENROUTER_API_KEY", "TYPESAFE_API_KEY")
PRICE_PER_INPUT_TOKEN = float(os.environ.get("JEV_PRICE_PER_MTOK", "0.042")) / 1e6  # used only when the API reports no cost

_local = threading.local()


def api_key() -> str:
    for name in KEY_ENV:
        if os.environ.get(name):
            return os.environ[name]
    raise SystemExit("set JEV_API_KEY (an OpenRouter key, or a TypeSafe key together with JEV_URL)")


def noul(instructions: str) -> dict:
    return {"type": "noul", "instructions": instructions}


def choice(instructions: str, criteria: dict[str, str]) -> dict:
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


def ask(state: dict, questions: dict) -> tuple[dict, dict]:
    """Answers and a meter. Each worker thread keeps one warm TLS connection: a handshake costs more than a decision."""
    u = urlparse(URL)
    payload = json.dumps({"model": MODEL, "state": state, "questions": questions}).encode()
    headers = {"Authorization": "Bearer " + api_key(), "Content-Type": "application/json", "Connection": "keep-alive"}
    started = time.perf_counter()
    for attempt in (0, 1):
        try:
            conn = getattr(_local, "conn", None)
            if conn is None:
                conn = _local.conn = http.client.HTTPSConnection(u.netloc, timeout=60)
            conn.request("POST", u.path, body=payload, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            if resp.status >= 400:
                raise RuntimeError(f"jev http {resp.status}: {data[:300]!r}")
            out = json.loads(data)
            break
        except (http.client.HTTPException, ConnectionError, TimeoutError, OSError):
            _local.conn = None  # the server closed an idle socket: reconnect once
            if attempt:
                raise
    usage = out.get("usage") or {}
    tokens = int(usage.get("input_tokens") or 0)
    meter = {
        "seconds": round(time.perf_counter() - started, 3),
        "input_tokens": tokens,
        "cost": float(usage.get("cost") or 0) or tokens * PRICE_PER_INPUT_TOKEN,
        "model": out.get("model"),
    }
    return out["answers"], meter
