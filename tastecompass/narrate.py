"""Optional: an LLM rewrites the panel's points in each advisor's voice.

Provider: OpenAI (openai_api.py). The model only rephrases facts it is given; the panel's scores
and verdicts come from panel.py and are never changed here. Any failure -> the caller keeps the
template text, so the demo never depends on the network.
"""
from __future__ import annotations

import json

from . import openai_api

SYSTEM = """You voice a panel of four advisors helping a student choose a UK master's programme:
- Admissions Advisor: precise, practical about requirements and deadlines.
- Finance Planner: careful, frank about money.
- Lifestyle Scout: warm and enthusiastic about city life and the student's tastes.
- Career Coach: forward-looking, focused on skills and jobs.
And a Chair who weighs them up.

You receive JSON with each advisor's verdict and factual points per programme.
For every programme write one or two sentences per advisor, in that advisor's voice, using ONLY the given points.
Never add numbers, names, places, dates or facts that are not in the points; never change a verdict.
If a point says data is missing or mock, keep that caveat. Then write the chair's one-sentence verdict.
Reply with JSON only: {"programmes": {"<program_id>": {"admissions": "...", "finance": "...", "lifestyle": "...", "career": "...", "chair": "..."}}}"""

KEYS = ("admissions", "finance", "lifestyle", "career", "chair")
NarrateError = openai_api.OpenAIError


def available() -> tuple[bool, str]:
    if not openai_api.configured():
        return False, "set OPENAI_API_KEY and restart the server"
    return True, f"OpenAI {openai_api.MODEL}"


def _facts(panel: dict) -> dict:
    return {"programmes": [{
        "program_id": p["program_id"], "programme": p["programme"], "school": p["school"], "city": p["city"],
        "advisors": {k: {"verdict": o["verdict"], "points": o["points"]} for k, o in p["opinions"].items()},
        "chair": p["chair"],
    } for p in panel["programmes"]]}


def narrate(panel: dict) -> dict:
    """Returns {program_id: {advisor_id/chair: text}}; raises NarrateError on any failure."""
    msg = openai_api.chat({
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": json.dumps(_facts(panel), ensure_ascii=False)}],
        "response_format": {"type": "json_object"},
    })
    try:
        parsed = json.loads(msg["content"])["programmes"]
    except (KeyError, TypeError, json.JSONDecodeError) as e:
        raise NarrateError("OpenAI returned an unexpected format") from e

    wanted = {p["program_id"] for p in panel["programmes"]}
    out = {}
    for pid, voices in (parsed.items() if isinstance(parsed, dict) else []):
        if pid in wanted and isinstance(voices, dict):
            out[pid] = {k: v.strip() for k, v in voices.items() if k in KEYS and isinstance(v, str) and v.strip()}
    if not out:
        raise NarrateError("OpenAI's reply had no usable advisor text")
    return out
