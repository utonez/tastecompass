"""Local web UI for TasteCompass (standard library only).

    python web.py                 # http://localhost:8000 , mock Qloo unless QLOO_API_KEY is set
    python web.py --port 8080 --mock

GET  /            -> static/landing.html (homepage)
GET  /app         -> static/index.html (the agent UI)
GET  /api/meta    -> cities, programmes and client kind (for the form)
POST /api/run     -> body = profile JSON (same shape as profiles/*.json), returns the agent result
                     plus the advisory panel (template text) and Taste DNA
POST /api/narrate -> body = profile JSON; the panel with each advisor's text rewritten by OpenAI (optional)
POST /api/chat    -> Claude explanations, server-sent events (optional)
"""
import argparse
import json
import os
from dataclasses import asdict
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tastecompass import dna, explain, narrate, panel
from tastecompass.agent import ROOT, TasteCompassAgent, load_data
from tastecompass.planner import AFTER_OFFER, CHECKLIST, pick_deadline
from tastecompass.qloo import QlooError, make_client
from tastecompass.report import render

STATIC = ROOT / "static"


def fit_to_dict(f):
    return {"program": f.program, "city": f.city, "components": f.components,
            "fit": f.fit, "unknown": f.unknown, "notes": f.notes}


def serialise(res: dict) -> dict:
    out = dict(res)
    out["city_ranking"] = [asdict(t) for t in res["city_ranking"]]
    for k in ("ranked", "top", "alternatives"):
        out[k] = [fit_to_dict(f) for f in res[k]]
    out["checklist"], out["after_offer"] = CHECKLIST, AFTER_OFFER
    # next usable deadline for every ranked programme (plans only cover the top N), for the comparison table
    today = date.fromisoformat(res["today"])
    out["deadlines"] = {}
    for f in res["ranked"] + res["alternatives"]:
        d, label = pick_deadline(f.program, today)
        out["deadlines"][f.program["id"]] = {"date": d.isoformat() if d else None, "label": label, "passed": bool(d and d < today)}
    return out


class App:
    def __init__(self, force_mock: bool):
        self.cities, self.programs = load_data()
        self.client, self.kind = make_client(ROOT, self.cities, force_mock=force_mock)
        self.llm_ok, self.llm_detail = explain.available()
        self.advisor = explain.Advisor(self.run) if self.llm_ok else None
        self.narrator_ok, self.narrator_detail = narrate.available()

    def meta(self) -> dict:
        return {"client": self.kind, "today": date.today().isoformat(), "cities": self.cities,
                "llm": {"available": self.llm_ok, "detail": self.llm_detail},
                "narrator": {"available": self.narrator_ok, "detail": self.narrator_detail},
                "programs": [{k: p.get(k) for k in ("id", "school", "city_id", "name")} for p in self.programs]}

    def run(self, profile: dict) -> dict:
        today = date.fromisoformat(profile["today"]) if profile.get("today") else None
        # a fresh agent per request so traces don't pile up; the client (and its cache) is shared
        res = TasteCompassAgent(self.client, self.kind, self.cities, self.programs).run(profile, today)
        out = serialise(res)
        out["markdown"] = render(res, {c["id"]: c for c in self.cities})
        out["panel"] = panel.convene(out, profile)
        out["dna"] = dna.build(out, self.cities)
        return out

    def narrate(self, profile: dict) -> dict:
        """The panel for this profile with LLM-voiced text; template text stays if the LLM fails."""
        p = self.run(profile)["panel"]
        if not self.narrator_ok:
            return {**p, "narration_error": self.narrator_detail}
        try:
            voices = narrate.narrate(p)
        except narrate.NarrateError as e:
            return {**p, "narration_error": str(e)}
        for prog in p["programmes"]:
            prog["voices"] = voices.get(prog["program_id"], {})
        return {**p, "narrated": True}


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            path = self.path.split("?")[0].split("#")[0]
            if path in ("/", "/index.html"):
                self._send(200, (STATIC / "landing.html").read_bytes(), "text/html; charset=utf-8")
            elif path in ("/app", "/app/"):
                self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif path == "/healthz":
                self._json(200, {"ok": True, "qloo": app.kind})
            elif self.path == "/api/meta":
                self._json(200, app.meta())
            else:
                self._json(404, {"error": "not found"})

        def _chat(self, body: dict):
            """Server-sent events: conv / text / tool / reset / error / done."""
            if app.advisor is None:
                return self._json(503, {"error": app.llm_detail})
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            def emit(kind, data):
                self.wfile.write(f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()

            try:
                cid = body.get("conv_id")
                if not cid or cid not in app.advisor.convs:
                    cid = app.advisor.start(body["profile"])
                    emit("conv", cid)
                app.advisor.ask(cid, str(body.get("question", ""))[:2000], emit)
            except (BrokenPipeError, ConnectionResetError):
                pass  # browser went away mid-stream
            except (ValueError, KeyError) as e:
                emit("error", str(e))

        def do_POST(self):
            if self.path not in ("/api/run", "/api/chat", "/api/narrate"):
                return self._json(404, {"error": "not found"})
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                if self.path == "/api/chat":
                    return self._chat(body)
                self._json(200, app.narrate(body) if self.path == "/api/narrate" else app.run(body))
            except (ValueError, KeyError) as e:
                self._json(400, {"error": str(e)})
            except QlooError as e:
                self._json(502, {"error": f"Qloo: {e}"})

        def log_message(self, fmt, *args):
            print(f"[web] {self.address_string()} {fmt % args}")

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))   # hosts like Render set PORT
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))            # 0.0.0.0 when deployed
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()
    app = App(args.mock)
    print(f"TasteCompass on http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}  (Qloo client: {app.kind}; "
          f"Ask: {app.llm_detail if app.llm_ok else 'off - ' + app.llm_detail}; "
          f"panel voices: {app.narrator_detail if app.narrator_ok else 'templates - ' + app.narrator_detail})")
    ThreadingHTTPServer((args.host, args.port), make_handler(app)).serve_forever()


if __name__ == "__main__":
    main()
