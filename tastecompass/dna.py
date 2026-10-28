"""Taste DNA: the student's taste as weighted tags, an archetype name, and how much of it each
city covers. Tags come from the resolved interests (Qloo entity tags, or the mock catalog);
city coverage uses cities.json fallback_tags, which are draft editorial labels."""
from __future__ import annotations

from collections import Counter

ARCHETYPES = {
    "indie": "Indie Explorer", "live music": "Gig Goer", "art": "Culture Seeker", "street art": "Street Art Hunter",
    "cafes": "Café Hopper", "outdoors": "Outdoor Wanderer", "hiking": "Trail Seeker", "literature": "Bookworm",
    "history": "History Buff", "festivals": "Festival Fan", "theatre": "Stage Lover", "nightlife": "Night Owl",
    "football": "Matchday Regular", "fine dining": "Foodie", "street food": "Street Food Fan", "finance": "Power Player",
    "shopping": "Trendsetter", "museums": "Museum Lover", "startups": "Builder", "vegetarian": "Green Eater",
    "multicultural food": "Flavour Traveller",
}
TOP_TAGS = 8


def build(out: dict, cities: list[dict]) -> dict | None:
    counts = Counter(tag for i in out["interests"] for tag in i.get("tags", []))
    if not counts:
        return None
    top = counts.most_common(TOP_TAGS)
    total = sum(n for _, n in top)
    traits = [{"tag": t, "weight": round(n / total, 3), "from": [i["name"] for i in out["interests"] if t in i.get("tags", [])]}
              for t, n in top]
    names = [ARCHETYPES.get(t["tag"], t["tag"].title() + " Fan") for t in traits[:2]]
    archetype = " × ".join(dict.fromkeys(names))   # dedupe, keep order
    coverage = []
    for c in cities:
        ctags = set(c.get("fallback_tags", []))
        shared = [t["tag"] for t in traits if t["tag"] in ctags]
        coverage.append({"city_id": c["id"], "city": c["name"],
                         "match": round(sum(t["weight"] for t in traits if t["tag"] in ctags), 3), "shared": shared})
    coverage.sort(key=lambda x: -x["match"])
    return {"archetype": archetype, "traits": traits, "coverage": coverage}
