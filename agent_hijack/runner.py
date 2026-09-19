# -*- coding: utf-8 -*-
"""Talks to a local Ollama server, and to nothing else.

Everything here runs against models on this machine. No key, no account, no
request leaves the host - which is the point: a benchmark you cannot reproduce
offline is a benchmark you have to take on trust.

The request is pinned as hard as the API allows - temperature 0, a fixed seed,
a fixed context window - so that two runs of the same case give the same answer
and a difference between models is a difference in the models, not in the
weather.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_HOST = "http://127.0.0.1:11434"


@dataclass(frozen=True)
class Generation:
    """One model's answer, plus the numbers that say how it was produced."""

    text: str
    model: str
    eval_count: int
    total_seconds: float
    ok: bool
    error: str = ""


def generate(
    model: str,
    system: str,
    prompt: str,
    *,
    host: str = DEFAULT_HOST,
    seed: int = 7,
    num_ctx: int = 8192,
    num_predict: int = 512,
    timeout: float = 600.0,
) -> Generation:
    """One deterministic completion. Failure is a value, never an exception.

    A model that is not pulled, a server that is down, a request that times out
    - each comes back as ``ok=False`` with the reason, so a sweep over many
    models and cases records the gap instead of crashing on the first one.
    """
    payload = {
        "model": model,
        "system": system,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0,
            "seed": seed,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
        },
    }
    request = urllib.request.Request(
        f"{host}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:200]
        return Generation("", model, 0, 0.0, False, f"http {error.code}: {detail}")
    except (urllib.error.URLError, TimeoutError) as error:
        return Generation("", model, 0, 0.0, False, f"unreachable: {error}")
    except json.JSONDecodeError as error:
        return Generation("", model, 0, 0.0, False, f"bad json: {error}")

    return Generation(
        text=body.get("response", ""),
        model=model,
        eval_count=int(body.get("eval_count", 0)),
        total_seconds=round(body.get("total_duration", 0) / 1e9, 2),
        ok=True,
    )


def installed_models(host: str = DEFAULT_HOST, timeout: float = 20.0) -> list[str]:
    """The models this server can run right now, so a sweep can skip the rest."""
    request = urllib.request.Request(f"{host}/api/tags")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return []
    return [model.get("name", "") for model in body.get("models", []) if model.get("name")]
