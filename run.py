"""Usage:
    python run.py profiles/mode_b.json            # mock Qloo unless QLOO_API_KEY is set
    python run.py profiles/mode_d.json --mock     # force mock
    python run.py profiles/mode_b.json --today 2026-10-21 --out out/report.md
"""
import argparse
import json
from datetime import date
from pathlib import Path

from tastecompass.agent import ROOT, TasteCompassAgent, load_data
from tastecompass.qloo import make_client
from tastecompass.report import render


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("profile")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--today")
    ap.add_argument("--out")
    args = ap.parse_args()

    cities, programs = load_data()
    client, kind = make_client(ROOT, cities, force_mock=args.mock)
    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    today = date.fromisoformat(args.today) if args.today else None

    agent = TasteCompassAgent(client, kind, cities, programs)
    res = agent.run(profile, today)
    md = render(res, {c["id"]: c for c in cities})
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
