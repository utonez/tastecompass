"""Fit(p) = w_T*T(city) + w_A*A(p) + w_B*B(p) + w_L*L(p), each component in [0, 1].

A component that cannot be computed because the official data is missing gets
a neutral 0.5 and is reported in `unknown`, so missing data never silently
helps or hurts a programme.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_WEIGHTS = {"taste": 0.35, "academic": 0.35, "budget": 0.20, "language": 0.10}
NEUTRAL = 0.5


@dataclass
class CityTaste:
    city_id: str
    raw: float                      # heatmap affinity near the city (fallback: mean affinity of top places)
    score: float = 0.0              # normalised across candidate cities
    evidence: list[dict] = field(default_factory=list)   # top places + which interest drove them
    driver_counts: dict[str, float] = field(default_factory=dict)
    n_places: int = 0               # places Qloo returned for this city
    source: str = "places"           # 'heatmap' or 'places'


@dataclass
class ProgramFit:
    program: dict
    city: dict
    components: dict
    fit: float
    unknown: list[str]
    notes: list[str]


MIN_SPREAD = 0.02   # below this, cities are a tie: min-max would turn noise into 0 vs 1


def normalise(tastes: list[CityTaste]) -> bool:
    """Min-max scale raw taste to 0..1. Returns False (all neutral) when the spread is too small to mean anything."""
    if not tastes:
        return False
    lo, hi = min(t.raw for t in tastes), max(t.raw for t in tastes)
    if hi - lo < MIN_SPREAD:
        for t in tastes:
            t.score = NEUTRAL
        return False
    for t in tastes:
        t.score = (t.raw - lo) / (hi - lo)
    return True


def academic_fit(profile: dict, program: dict) -> tuple[float, list[str]]:
    wanted = [w.lower() for w in profile.get("field_interests", [])]
    if not wanted:
        return NEUTRAL, []
    tags = [t.lower() for t in program.get("field_tags", [])]
    modules = " ".join(program.get("modules", [])).lower()
    matched = [w for w in wanted if w in tags or w in modules]
    score = len(matched) / len(wanted)
    if program.get("modules"):
        hits = sum(1 for w in wanted if w in modules)
        score = min(1.0, score * 0.8 + 0.2 * hits / len(wanted))
    return round(score, 3), matched


def budget_fit(profile: dict, program: dict, city: dict) -> float | None:
    fee = program.get("fee_overseas_gbp")
    budget = profile.get("tuition_budget_gbp")
    if fee is None or not budget:
        return None
    fee_score = 1.0 if fee <= budget else max(0.0, 1 - 2 * (fee - budget) / budget)
    living = 1 - ((city.get("cost_tier") or 3) - 1) / 4   # unknown tier = middle
    return round(0.7 * fee_score + 0.3 * living, 3)


def language_fit(profile: dict, program: dict) -> tuple[float | None, str | None]:
    req = program.get("english", {})
    need_o, need_c = req.get("ielts_overall"), req.get("ielts_min_component")
    have = profile.get("ielts", {})
    have_o, have_c = have.get("overall"), have.get("min_component")
    if need_o is None or have_o is None:
        return None, None
    gap = max(need_o - have_o, (need_c or 0) - (have_c or have_o))
    if gap <= 0:
        return 1.0, None
    if gap <= 0.5:
        return 0.5, f"IELTS short by {gap:.1f} - plan a retake"
    return 0.0, f"IELTS short by {gap:.1f}"


def program_fit(profile: dict, program: dict, city: dict, taste: CityTaste | None, weights: dict) -> ProgramFit:
    unknown, notes = [], []
    t = taste.score if taste else NEUTRAL
    if taste is None:
        unknown.append("taste")
    a, matched = academic_fit(profile, program)
    if matched:
        notes.append("matches your interests in " + ", ".join(matched))
    b = budget_fit(profile, program, city)
    if b is None:
        unknown.append("budget (fee not on official page)")
        b = NEUTRAL
    l, lnote = language_fit(profile, program)
    if l is None:
        unknown.append("language (IELTS score not stated as a number)")
        l = NEUTRAL
    if lnote:
        notes.append(lnote)
    comps = {"taste": round(t, 3), "academic": a, "budget": b, "language": l}
    total = sum(weights[k] * comps[k] for k in weights) / sum(weights.values())
    return ProgramFit(program, city, comps, round(total, 3), unknown, notes)
