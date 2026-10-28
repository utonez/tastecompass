"""Render the agent result as Markdown. Every factual line carries its source."""
from __future__ import annotations

from .planner import AFTER_OFFER, CHECKLIST

MODE_TEXT = {
    "A": "Nothing decided yet - ranking cities, then programmes",
    "B": "Country decided - ranking cities within it, then programmes",
    "C": "City decided - ranking programmes in that city only",
    "D": "School/programme decided - checking fit and planning the application",
}


def _fmt_money(v):
    return f"£{v:,}" if v else "unverified"


def _ielts(p):
    e = p.get("english", {})
    if e.get("ielts_overall"):
        return f"IELTS {e['ielts_overall']} (min {e.get('ielts_min_component')} each)"
    return e.get("note") or "unverified"


def render(res: dict, cities: dict) -> str:
    L = []
    L.append("# TasteCompass report\n")
    if res["client"] == "mock":
        L.append("> **MOCK MODE** - taste scores come from synthetic data, not Qloo. Set QLOO_API_KEY to use live Qloo.\n")
    L.append(f"**Scope mode {res['mode']}:** {MODE_TEXT[res['mode']]}  ")
    L.append(f"**Target intake:** {res['target_intake']} · **Generated:** {res['today']}  ")
    w = res["weights"]
    L.append(f"**Weights:** taste {w['taste']}, academic {w['academic']}, budget {w['budget']}, language {w['language']}\n")

    L.append("## Your taste profile")
    for i in res["interests"]:
        L.append(f"- {i['input']} → {i['name']}")
    L.append("")

    if res["city_ranking"]:
        L.append("## City taste fit")
        L.append("| Rank | City | Taste score | Driven mostly by |")
        L.append("|---|---|---|---|")
        for n, t in enumerate(res["city_ranking"][:10], 1):
            top = sorted(t.driver_counts.items(), key=lambda kv: -kv[1])[:2]
            drivers = ", ".join(res["names"].get(k, k) for k, _ in top if k in res["names"])
            if not drivers:  # tag signals carry no per-entity explainability: show the places Qloo matched instead
                drivers = "places: " + ", ".join(e["name"] for e in t.evidence[:2] if e.get("name")) if t.evidence else "-"
            L.append(f"| {n} | {cities[t.city_id]['name']} | {t.score:.2f} | {drivers} |")
        L.append("")

    L.append("## Recommended programmes" if res["mode"] != "D" else "## Your chosen programme(s)")
    for f in res["top"]:
        p, c = f.program, f.city
        L.append(f"### {p['name']} - {p['school']} ({c['name']})")
        L.append(f"**Fit {f.fit:.2f}** = taste {f.components['taste']:.2f} · academic {f.components['academic']:.2f} · "
                 f"budget {f.components['budget']:.2f} · language {f.components['language']:.2f}")
        if f.notes:
            L.append("- Why: " + "; ".join(f.notes))
        if f.unknown:
            L.append("- Unverified (scored neutral): " + "; ".join(f.unknown))
        L.append(f"- Overseas fee: {_fmt_money(p.get('fee_overseas_gbp'))} · English: {_ielts(p)} · Entry: {p.get('entry_requirement') or 'unverified'}")
        if p.get("modules"):
            L.append("- Modules include: " + ", ".join(p["modules"][:5]))
        plan = res["plans"].get(p["id"])
        if plan:
            if plan["deadline"]:
                L.append(f"- Deadline: **{plan['deadline']}** ({plan['label']})")
            for wmsg in plan["warnings"]:
                L.append(f"- ⚠ {wmsg}")
            if plan["steps"]:
                L.append("")
                L.append("| Date | Task |")
                L.append("|---|---|")
                for s in plan["steps"]:
                    L.append(f"| {s['date']}{' (overdue)' if s['late'] else ''} | {s['task']} |")
        L.append(f"\nSource: {p['source_url']} (checked {p.get('checked_on') or 'not yet'})\n")

    if res.get("universities"):
        L.append("## Universities in your top cities")
        L.append("Programme facts are only shown once checked on the official course page.\n")
        for u in res["universities"]:
            status = f"{u['verified_programmes']} verified programme(s)" if u["verified_programmes"] else "not yet verified - check the official site"
            L.append(f"- {u['name']} ({u['city']}): {status} · {u['url']}")
        L.append("")

    if res["alternatives"]:
        L.append("## Worth a look (outside your scope)")
        for f in res["alternatives"]:
            L.append(f"- {f.program['name']} - {f.program['school']} ({f.city['name']}): fit {f.fit:.2f}")
        L.append("")

    L.append("## Document checklist (typical - confirm on each course page)")
    L += [f"- [ ] {x}" for x in CHECKLIST]
    L.append("\nAfter an offer:")
    L += [f"- [ ] {x}" for x in AFTER_OFFER]
    L.append("\n<details><summary>Agent trace</summary>\n")
    L += [f"{n}. {t}" for n, t in enumerate(res["trace"], 1)]
    L.append("\n</details>")
    return "\n".join(L)
