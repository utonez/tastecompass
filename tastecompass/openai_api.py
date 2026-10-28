"""Minimal OpenAI Chat Completions client over plain HTTP (stdlib only).

Key from OPENAI_API_KEY, model from OPENAI_MODEL, base URL from OPENAI_BASE_URL. Used by the
advisory-panel voices (narrate.py) and, when Claude isn't configured, by Ask TasteCompass (explain.py).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

API_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
TIMEOUT = 60


class OpenAIError(RuntimeError):
    pass


def configured() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def chat(body: dict) -> dict:
    """POST /chat/completions (model filled in if missing); returns choices[0].message. Raises OpenAIError."""
    req = urllib.request.Request(API_URL, data=json.dumps({"model": MODEL, **body}).encode("utf-8"), method="POST", headers={
        "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', '').strip()}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        hint = {401: "invalid OPENAI_API_KEY", 429: "rate limited or out of credit"}.get(e.code, detail)
        raise OpenAIError(f"OpenAI HTTP {e.code}: {hint}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise OpenAIError(f"Cannot reach OpenAI: {e}") from e
    try:
        return data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as e:
        raise OpenAIError("OpenAI returned an unexpected format") from e
