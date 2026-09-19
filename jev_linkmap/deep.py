"""The deep model behind the referee and System 2, through whichever seat you already pay for.

  LINKMAP_DEEP=claude   the Claude Code CLI (default): Opus 5 referees, Fable 5.1 rewrites the rubric
  LINKMAP_DEEP=codex    the Codex CLI (`codex exec`), your ChatGPT plan, whatever model it is set to
  LINKMAP_DEEP=api      the Anthropic API with ANTHROPIC_API_KEY

Jev never needs any of them. They exist for the race and for the System 1 + System 2 loop.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import urllib.request

BACKEND = os.environ.get("LINKMAP_DEEP", "claude").lower()
MODELS = {
    "referee": os.environ.get("FRONTIER_MODEL", "claude-opus-5"),
    "system2": os.environ.get("SYSTEM2_MODEL", "claude-fable-5-1"),
}
CODEX_MODEL = os.environ.get("CODEX_MODEL", "")  # empty: the model your Codex config already uses


def model_name(role: str) -> str:
    if BACKEND == "codex":
        return f"codex:{CODEX_MODEL or 'default'}"
    return MODELS[role]


def command(role: str, system: str, last_message_file: str = "") -> list[str]:
    if BACKEND == "codex":
        # read-only sandbox in an empty folder: the model gets text in and text out, nothing to touch
        cmd = ["codex", "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "--color", "never", "-o", last_message_file]
        return cmd + (["-m", CODEX_MODEL] if CODEX_MODEL else []) + ["-"]
    return ["claude", "-p", "--model", MODELS[role], "--disable-slash-commands", "--strict-mcp-config", "--setting-sources", "", "--tools", "", "--system-prompt", system, "--output-format", "json"]


def call(role: str, system: str, prompt: str, procs: set | None = None, timeout: int = 900) -> tuple[str, dict]:
    """The model's text and a meter. `procs` lets a race kill calls still in flight when the clock stops."""
    started = time.perf_counter()
    if BACKEND == "api":
        body = {"model": MODELS[role], "max_tokens": 8000, "system": system, "messages": [{"role": "user", "content": prompt}]}
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(body).encode(),
            headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"},
        )
        out = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        usage = out.get("usage") or {}
        return out["content"][-1]["text"], {"seconds": round(time.perf_counter() - started, 3), "cost": 0.0, "input_tokens": int(usage.get("input_tokens") or 0), "output_tokens": int(usage.get("output_tokens") or 0), "model": MODELS[role]}

    with tempfile.TemporaryDirectory() as empty:
        last = os.path.join(empty, "last-message.txt")
        stdin = f"{system}\n\n---\n\n{prompt}" if BACKEND == "codex" else prompt
        proc = subprocess.Popen(command(role, system, last), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=empty)
        if procs is not None:
            procs.add(proc)
        try:
            raw, err = proc.communicate(stdin, timeout=timeout)
        finally:
            if procs is not None:
                procs.discard(proc)
        seconds = round(time.perf_counter() - started, 3)
        if proc.returncode != 0:
            raise RuntimeError(f"{BACKEND} exit {proc.returncode}: {(err or raw).strip()[-300:]}")
        if BACKEND == "codex":
            if not os.path.exists(last):
                raise RuntimeError(f"codex wrote no answer: {(err or raw).strip()[-300:]}")
            # the ChatGPT plan reports no dollar cost, so the meter carries time only
            return open(last, encoding="utf-8").read(), {"seconds": seconds, "model_seconds": seconds, "cost": 0.0, "input_tokens": 0, "output_tokens": 0, "model": model_name(role)}
    out = json.loads(raw)
    if out.get("is_error"):
        raise RuntimeError(f"claude error: {str(out.get('result'))[:300]}")
    usage = out.get("usage") or {}
    meter = {
        "seconds": seconds,
        "model_seconds": round((out.get("duration_api_ms") or 0) / 1000, 3),
        "cost": float(out.get("total_cost_usd") or 0),
        "input_tokens": int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0) + int(usage.get("cache_creation_input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "model": MODELS[role],
    }
    return out.get("result") or "", meter
