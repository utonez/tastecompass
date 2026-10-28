"""LLM layer: an LLM (Claude, or OpenAI as a fallback) explains the agent's result and answers follow-ups.

The LLM only explains. Every number it may quote comes from `facts()` (built
from the data files and scoring code), and "what if" questions are answered by
the `what_if` tool, which reruns the real agent with a modified profile.

Claude: `pip install anthropic` and set ANTHROPIC_API_KEY. OpenAI: set OPENAI_API_KEY (no package).
Claude is used when both are set; TASTECOMPASS_LLM=openai|claude forces one. With neither,
`available()` reports why, and the rest of the app still works.
"""
from __future__ import annotations

import copy
import json
import os
import threading
import uuid

from . import openai_api

try:
    import anthropic
except ImportError:  # the rest of TasteCompass stays stdlib-only
    anthropic = None

MODEL = os.environ.get("TASTECOMPASS_MODEL", "claude-opus-5-5")
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOOL_ROUNDS = 4

SYSTEM = """You are TasteCompass's advisor. A student is choosing a UK taught master's programme.
A deterministic agent has already scored programmes: Fit = weighted taste (Qloo city taste), academic (field match), budget (fee vs budget + living cost tier) and language (IELTS gap), each 0-1.

Rules:
- Every fact (fee, deadline, IELTS band, score, rank) must come from the FACTS JSON or a what_if tool result. Never use outside knowledge for these; if a value is null or listed as unknown, say it is not on the official page and the student should check the source link.
- Component scores of exactly 0.5 listed under "unknown" are neutral placeholders for missing data, not real judgements - point this out when it matters.
- If client is "mock", taste scores are synthetic; say so briefly whenever you rely on them.
- For any hypothetical ("what if my budget were £3,000 higher", "if I retake IELTS to 7.5", "if I care less about taste"), call what_if instead of estimating. Compare before/after ranks and fits.
- Explain trade-offs concretely: which component drives each gap, what the student would give up.
- Answer in English unless the student writes in another language, then match it.
- Write like a chat message, not a report: lead with the answer in one sentence, then at most 3 short bullets or 2 short sentences. Stay under 100 words unless the student asks for detail.
- No headings, no tables, no horizontal rules, no preamble or sign-off. Bold at most one or two key numbers or names."""

WHAT_IF_TOOL = {
    "name": "what_if",
    "description": ("Rerun the TasteCompass agent with some profile fields changed and get the new ranking. "
                    "Only include fields that change. Use it for every hypothetical question."),
    "input_schema": {
        "type": "object",
        "properties": {
            "tuition_budget_gbp": {"type": "number", "description": "New yearly tuition budget in GBP"},
            "ielts_overall": {"type": "number"},
            "ielts_min_component": {"type": "number"},
            "weights": {"type": "object", "description": "Any of taste, academic, budget, language (0-1)",
                        "properties": {k: {"type": "number"} for k in ("taste", "academic", "budget", "language")},
                        "additionalProperties": False},
            "field_interests": {"type": "array", "items": {"type": "string"}, "description": "Replaces the field list"},
            "interests": {"type": "array", "items": {"type": "string"}, "description": "Replaces the taste interests"},
            "target_intake": {"type": "integer"},
        },
        "additionalProperties": False,
    },
    # stream tool input as generated; we validate it ourselves in validate_what_if()
    "eager_input_streaming": True,
}


# OpenAI function-calling form of the same tool
OPENAI_TOOL = {"type": "function", "function": {"name": WHAT_IF_TOOL["name"], "description": WHAT_IF_TOOL["description"],
                                                "parameters": WHAT_IF_TOOL["input_schema"]}}


def _claude_ready() -> bool:
    return anthropic is not None and bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
                                          or os.environ.get("ANTHROPIC_PROFILE"))


def provider() -> str | None:
    """'claude' or 'openai' (TASTECOMPASS_LLM forces one); Claude first when both are configured."""
    forced = os.environ.get("TASTECOMPASS_LLM", "").lower()
    if forced in ("claude", "openai"):
        return forced if (_claude_ready() if forced == "claude" else openai_api.configured()) else None
    if _claude_ready():
        return "claude"
    return "openai" if openai_api.configured() else None


def available() -> tuple[bool, str]:
    p = provider()
    if p == "claude":
        return True, f"Claude {MODEL}"
    if p == "openai":
        return True, f"OpenAI {openai_api.MODEL}"
    return False, "set OPENAI_API_KEY (or ANTHROPIC_API_KEY with pip install anthropic) and restart the server"


# ---- facts the model is allowed to use ---------------------------------------
def _fit_row(f: dict, deadlines: dict) -> dict:
    p = f["program"]
    e = p.get("english") or {}
    return {
        "id": p["id"], "programme": p["name"], "school": p["school"], "city": f["city"]["name"],
        "fit": f["fit"], "components": f["components"], "unknown": f["unknown"], "notes": f["notes"],
        "fee_overseas_gbp": p.get("fee_overseas_gbp"),
        "ielts": {"overall": e.get("ielts_overall"), "min_component": e.get("ielts_min_component"), "note": e.get("note")},
        "next_deadline": deadlines.get(p["id"]),
        "data_entry_year": p.get("data_entry_year"), "source_url": p.get("source_url"),
    }


def facts(out: dict, profile: dict) -> dict:
    """Compact, model-facing view of a serialised agent result (web.serialise output)."""
    d = out.get("deadlines", {})
    return {
        "client": out["client"], "mode": out["mode"], "today": out["today"], "target_intake": out["target_intake"],
        "weights": out["weights"],
        "profile": {k: profile.get(k) for k in ("interests", "field_interests", "tuition_budget_gbp", "ielts", "scope")},
        "city_taste_ranking": [{"city": t["city_id"], "score": round(t["score"], 3),
                                "drivers": [out["names"].get(k, k) for k, _ in sorted(t["driver_counts"].items(), key=lambda kv: -kv[1])[:2]],
                                "top_places": [{"name": e["name"], "affinity": e["affinity"],
                                                "because_of": [out["names"].get(d, d) for d in e.get("drivers", [])]}
                                               for e in t.get("evidence", [])[:3]]}
                               for t in out["city_ranking"][:10]],
        "universities_in_top_cities": [{"name": u["name"], "city": u["city"], "verified_programmes": u["verified_programmes"]}
                                       for u in out.get("universities", [])],
        "ranked_in_scope": [_fit_row(f, d) for f in out["ranked"]],
        "shown_as_top": [f["program"]["id"] for f in out["top"]],
        "alternatives_outside_scope": [_fit_row(f, d) for f in out["alternatives"]],
        "timelines": out["plans"],
    }


def validate_what_if(inp) -> tuple[dict | None, str | None]:
    if not isinstance(inp, dict):
        return None, "input must be an object"
    num = (int, float)
    for k in ("tuition_budget_gbp", "ielts_overall", "ielts_min_component"):
        if k in inp and (isinstance(inp[k], bool) or not isinstance(inp[k], num)):
            return None, f"{k} must be a number"
    if "target_intake" in inp and not isinstance(inp["target_intake"], int):
        return None, "target_intake must be an integer"
    for k in ("field_interests", "interests"):
        if k in inp and not (isinstance(inp[k], list) and all(isinstance(x, str) for x in inp[k])):
            return None, f"{k} must be a list of strings"
    w = inp.get("weights", {})
    if not isinstance(w, dict) or any(k not in ("taste", "academic", "budget", "language") or not isinstance(v, num) for k, v in w.items()):
        return None, "weights must map taste/academic/budget/language to numbers"
    extra = set(inp) - set(WHAT_IF_TOOL["input_schema"]["properties"])
    if extra:
        return None, f"unknown fields: {sorted(extra)}"
    return inp, None


def apply_what_if(profile: dict, change: dict) -> dict:
    p = copy.deepcopy(profile)
    for k in ("tuition_budget_gbp", "field_interests", "interests", "target_intake"):
        if k in change:
            p[k] = change[k]
    if "ielts_overall" in change or "ielts_min_component" in change:
        ielts = dict(p.get("ielts") or {})
        if "ielts_overall" in change:
            ielts["overall"] = change["ielts_overall"]
        if "ielts_min_component" in change:
            ielts["min_component"] = change["ielts_min_component"]
        p["ielts"] = ielts
    if change.get("weights"):
        p["weights"] = {**(p.get("weights") or {}), **change["weights"]}
    return p


# ---- conversations ----------------------------------------------------------------
class Advisor:
    """Holds one message history per conversation (in memory) and runs the tool loop.

    run_fn(profile) -> serialised agent result; used for the first turn and for what_if.
    """

    def __init__(self, run_fn):
        self.run_fn = run_fn
        self.provider = provider()
        self.client = anthropic.Anthropic() if self.provider == "claude" else None
        self.convs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def start(self, profile: dict) -> str:
        out = self.run_fn(profile)
        cid = uuid.uuid4().hex
        with self.lock:
            self.convs[cid] = {"profile": profile, "facts": facts(out, profile), "messages": [], "lock": threading.Lock()}
        return cid

    def ask(self, cid: str, question: str, emit):
        """emit(event_type, data) streams to the browser: text / tool / reset / error / done."""
        conv = self.convs.get(cid)
        if conv is None:
            return emit("error", "This conversation has expired - run the recommendation again.")
        with conv["lock"]:
            msgs = conv["messages"]
            checkpoint = len(msgs)
            if not msgs:  # first turn carries the facts; later turns only the question
                content = f"FACTS (from TasteCompass, the only source of truth):\n{json.dumps(conv['facts'], ensure_ascii=False)}\n\nQuestion: {question}"
            else:
                content = question
            msgs.append({"role": "user", "content": content})
            try:
                (self._loop_openai if self.provider == "openai" else self._loop)(conv, emit)
            except Exception as e:  # roll back so a failed turn doesn't poison the history
                del msgs[checkpoint:]
                emit("error", _describe(e))
                return
            emit("done", "")

    def _loop(self, conv: dict, emit):
        msgs = conv["messages"]
        for _ in range(MAX_TOOL_ROUNDS + 1):
            with self.client.beta.messages.stream(
                model=MODEL,
                max_tokens=16000,
                system=SYSTEM,
                messages=msgs,
                tools=[WHAT_IF_TOOL],
                thinking={"type": "adaptive"},
                output_config={"effort": "medium"},
                cache_control={"type": "ephemeral"},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                for event in stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        emit("text", event.delta.text)
                msg = stream.get_final_message()

            msgs.append({"role": "assistant", "content": msg.content})
            if msg.stop_reason == "refusal":
                emit("reset", "")  # discard any partial text from a mid-stream decline
                raise RuntimeError("Claude declined to answer this (refusal). Try rephrasing.")
            if msg.stop_reason != "tool_use":
                return
            results = []
            for block in msg.content:
                if block.type != "tool_use":
                    continue
                content, is_error = self._tool(conv, block.name, block.input, emit)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": content, "is_error": is_error})
            msgs.append({"role": "user", "content": results})
        raise RuntimeError("Too many tool calls - stopped.")

    def _loop_openai(self, conv: dict, emit):
        """Same tool loop over OpenAI Chat Completions (non-streaming: each round's text arrives whole)."""
        msgs = conv["messages"]
        for _ in range(MAX_TOOL_ROUNDS + 1):
            msg = openai_api.chat({"messages": [{"role": "system", "content": SYSTEM}, *msgs], "tools": [OPENAI_TOOL]})
            if msg.get("refusal"):
                raise RuntimeError("The model declined to answer this. Try rephrasing.")
            text, calls = msg.get("content") or "", msg.get("tool_calls") or []
            turn = {"role": "assistant", "content": text or None}
            if calls:
                turn["tool_calls"] = calls
            msgs.append(turn)
            if text:
                emit("text", text + ("\n\n" if calls else ""))
            if not calls:
                return
            for call in calls:
                fn = call.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = None
                content, _ = self._tool(conv, fn.get("name"), args, emit)
                msgs.append({"role": "tool", "tool_call_id": call.get("id"), "content": content})
        raise RuntimeError("Too many tool calls - stopped.")

    def _tool(self, conv: dict, name, args, emit) -> tuple[str, bool]:
        """Run one tool call from either provider -> (content, is_error)."""
        change, err = validate_what_if(args) if name == "what_if" else (None, f"unknown tool {name}")
        if err:
            return err, True
        emit("tool", change)
        profile = apply_what_if(conv["profile"], change)
        try:
            new = facts(self.run_fn(profile), profile)
        except (ValueError, KeyError) as e:
            return f"agent error: {e}", True
        return json.dumps({"change": change, **new}, ensure_ascii=False), False


def _describe(e: Exception) -> str:
    if anthropic is not None:
        if isinstance(e, anthropic.AuthenticationError):
            return "Invalid API key - check ANTHROPIC_API_KEY."
        if isinstance(e, anthropic.RateLimitError):
            return "Rate limited (429) - wait a moment and try again."
        if isinstance(e, anthropic.APIStatusError):
            return f"Claude API error {e.status_code}: {e.message}"
        if isinstance(e, anthropic.APIConnectionError):
            return "Cannot reach the Claude API - check your connection."
    if isinstance(e, openai_api.OpenAIError):
        return str(e)
    if isinstance(e, ValueError):  # unparseable streamed tool input
        return "Could not parse Claude's tool input - please ask again."
    return str(e)
