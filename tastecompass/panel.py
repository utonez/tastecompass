"""Advisory panel: four specialist advisors judge each shown programme, then a chair sums up.

Every score, verdict and point here is computed from the data files and the agent result -
no LLM. An LLM (see narrate.py) may later rewrite the points in each advisor's voice, but it
never decides anything, so the panel works (and stays correct) with no API key at all.
"""
from __future__ import annotations

from datetime import date

ADVISORS = [
    {"id": "admissions", "name": "Admissions Advisor", "icon": "🎓", "focus": "entry requirements, English, deadlines"},
    {"id": "finance", "name": "Finance Planner", "icon": "💷", "focus": "tuition against your budget, living costs"},
    {"id": "lifestyle", "name": "Lifestyle Scout", "icon": "🎧", "focus": "how well the city fits your taste (Qloo)"},
    {"id": "career", "name": "Career Coach", "icon": "💼", "focus": "how the curriculum serves your goals"},
]
CAREER_SCENES = {"startups": "startup", "finance": "finance"}   # city tags (draft, cities.json) that hint at a job scene


def verdict(score: float, unverified: bool) -> str:
    if unverified:
        return "unverified"
    return "strong" if score >= 0.7 else "mixed" if score >= 0.4 else "concern"


def _admissions(f: dict, profile: dict, deadline: dict, today: date, target: int) -> dict:
    p, points = f["program"], []
    e, have = p.get("english") or {}, profile.get("ielts") or {}
    need_o, need_c = e.get("ielts_overall"), e.get("ielts_min_component")
    have_o, have_c = have.get("overall"), have.get("min_component")
    if need_o is None:
        points.append(f"English requirement isn't given as an IELTS score ({e.get('note') or 'not on the course page'}) - check the language page")
    elif have_o is None:
        points.append(f"Needs IELTS {need_o} (min {need_c} each); you haven't entered a score yet")
    else:
        gap = max(need_o - have_o, (need_c or 0) - (have_c or have_o))
        points.append(f"Your IELTS {have_o} meets the {need_o} requirement (min {need_c} each)" if gap <= 0
                      else f"IELTS short by {gap:.1f}: needs {need_o} overall, {need_c} per band")

    d = deadline.get("date")
    if not d:
        points.append("No deadline on the official page yet")
        dl_score = 0.5
    elif deadline.get("passed"):
        points.append(f"The listed deadline ({d}) has passed - it belongs to an earlier cycle")
        dl_score = 0.3
    else:
        days = (date.fromisoformat(d) - today).days
        points.append(f"Next deadline {d} - {days} days away ({deadline.get('label')})")
        dl_score = 1.0 if days >= 60 else 0.6 if days >= 21 else 0.3
    year = p.get("data_entry_year")
    if year and year < target:
        points.append(f"Figures are from the {year} intake; the {target} page may differ")
    if p.get("entry_requirement"):
        points.append(f"Entry: {p['entry_requirement']}")
    score = 0.6 * f["components"]["language"] + 0.4 * dl_score
    return {"score": round(score, 2), "verdict": verdict(score, need_o is None), "points": points}


def _finance(f: dict, profile: dict) -> dict:
    p, c, points = f["program"], f["city"], []
    fee, budget = p.get("fee_overseas_gbp"), profile.get("tuition_budget_gbp")
    if fee is None:
        points.append("Overseas fee isn't on the official page - can't check it against your budget")
    elif not budget:
        points.append(f"Overseas fee £{fee:,}; set a budget to compare")
    elif fee <= budget:
        points.append(f"Fee £{fee:,} is £{budget - fee:,} under your £{budget:,} budget")
    else:
        points.append(f"Fee £{fee:,} is £{fee - budget:,} over your £{budget:,} budget")
    tier = c.get("cost_tier")
    if tier:
        points.append(f"Living costs in {c['name']}: tier {tier} of 5 (draft estimate)")
    score = f["components"]["budget"]
    return {"score": round(score, 2), "verdict": verdict(score, fee is None or not budget), "points": points}


def _lifestyle(f: dict, taste: dict | None, rank: int | None, n_cities: int, names: dict, mock: bool) -> dict:
    c, points = f["city"], []
    if taste is None:
        return {"score": 0.5, "verdict": "unverified", "points": ["No interests entered, so the city's taste fit is unknown"]}
    points.append(f"{c['name']} scores {taste['score']:.2f} on taste - #{rank} of {n_cities} cities"
                  + (" (mock data)" if mock else ""))
    drivers = [names.get(k, k) for k, _ in sorted(taste["driver_counts"].items(), key=lambda kv: -kv[1])[:2]]
    if drivers:
        points.append("Mostly thanks to your love of " + " and ".join(drivers))
    places = [e["name"] for e in taste.get("evidence", [])[:3]]
    if places:
        points.append("You'd probably like: " + ", ".join(places))
    score = f["components"]["taste"]
    return {"score": round(score, 2), "verdict": verdict(score, False), "points": points}


def _career(f: dict, profile: dict) -> dict:
    p, c, points = f["program"], f["city"], []
    wanted = [w.lower() for w in profile.get("field_interests", [])]
    modules = [m for m in p.get("modules", []) if any(w in m.lower() for w in wanted)]
    if not wanted:
        points.append("No fields of interest entered")
    elif modules:
        points.append("Modules that match your goals: " + ", ".join(modules[:4]))
    elif p.get("modules"):
        points.append("No module titles directly match your fields of interest")
    else:
        points.append("Module list isn't on the official page")
    tags = [t.lower() for t in p.get("field_tags", []) if t.lower() in wanted]
    if tags:
        points.append("Programme is tagged for " + ", ".join(tags))
    scenes = [CAREER_SCENES[t] for t in c.get("fallback_tags", []) if t in CAREER_SCENES]
    if scenes:
        points.append(f"{c['name']} has a notable {' and '.join(scenes)} scene (draft city tags)")
    score = f["components"]["academic"]
    return {"score": round(score, 2), "verdict": verdict(score, not wanted), "points": points}


def _chair(f: dict, opinions: dict) -> dict:
    by = {a["id"]: a["name"] for a in ADVISORS}
    keen = [by[k] for k, o in opinions.items() if o["verdict"] == "strong"]
    worried = [by[k] for k, o in opinions.items() if o["verdict"] == "concern"]
    unsure = [by[k] for k, o in opinions.items() if o["verdict"] == "unverified"]
    fit = f["fit"]
    headline = "Strong candidate" if fit >= 0.7 else "Worth applying" if fit >= 0.5 else "Long shot"
    if keen and worried:
        summary = f"Split decision: the {_join(keen)} {'is' if len(keen) == 1 else 'are'} keen, but the {_join(worried)} {'has' if len(worried) == 1 else 'have'} concerns."
    elif worried:
        summary = f"The {_join(worried)} {'has' if len(worried) == 1 else 'have'} concerns; nobody is strongly in favour."
    elif keen:
        summary = f"Broad support, led by the {_join(keen)}."
    else:
        summary = "A middle-of-the-road option with no strong signals either way."
    if unsure:
        summary += f" The {_join(unsure)} can't judge yet - official data is missing."
    return {"headline": headline, "summary": summary}


def _join(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def convene(out: dict, profile: dict) -> dict:
    """out = serialised agent result (web.serialise). Judges every programme in out['top']."""
    today = date.fromisoformat(out["today"])
    ranking = out["city_ranking"]
    taste_by_city = {t["city_id"]: t for t in ranking}
    rank_by_city = {t["city_id"]: n for n, t in enumerate(ranking, 1)}
    mock = out["client"] == "mock"
    programmes = []
    for f in out["top"]:
        pid, cid = f["program"]["id"], f["city"]["id"]
        opinions = {
            "admissions": _admissions(f, profile, out["deadlines"].get(pid, {}), today, out["target_intake"]),
            "finance": _finance(f, profile),
            "lifestyle": _lifestyle(f, taste_by_city.get(cid), rank_by_city.get(cid), len(ranking), out["names"], mock),
            "career": _career(f, profile),
        }
        programmes.append({"program_id": pid, "programme": f["program"]["name"], "school": f["program"]["school"],
                           "city": f["city"]["name"], "fit": f["fit"], "opinions": opinions, "chair": _chair(f, opinions)})

    pick = None
    if programmes:
        best = programmes[0]  # out['top'] is already sorted by fit
        champions = {a["id"]: max(programmes, key=lambda p: p["opinions"][a["id"]]["score"])["programme"] for a in ADVISORS}
        pick = {"programme": best["programme"], "school": best["school"], "fit": best["fit"], "favourites": champions}
    return {"advisors": ADVISORS, "programmes": programmes, "pick": pick, "narrated": False}
