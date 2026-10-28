"""Does Qloo's destination ranking compare UK cities better than the heatmap?

    python probe3.py

Uses the same two interest sets as probe2 and tries a few parameter variants for
filter.type=urn:entity:destination. Prints top destinations with affinity - paste the output back.
"""
import json

import tastecompass  # loads .env
from tastecompass.agent import TasteCompassAgent, load_data
from tastecompass.qloo import QlooClient, QlooError, DEFAULT_BASE_URL
import os

SETS = {
    "indie/outdoors": ["Radiohead", "Hiking", "Specialty coffee", "Banksy", "Studio Ghibli"],
    "theatre/history": ["Les Misérables", "Harry Potter", "Museums", "Afternoon tea"],
}
VARIANTS = {
    "location.query=United Kingdom": {"filter.location.query": "United Kingdom"},
    "geocode.country_code=GB": {"filter.geocode.country_code": "GB"},
    "no location filter": {},
}


def main():
    client = QlooClient(os.environ["QLOO_API_KEY"], os.environ.get("QLOO_BASE_URL", DEFAULT_BASE_URL))
    cities, programs = load_data()
    for label, interests in SETS.items():
        agent = TasteCompassAgent(client, "live", cities, programs)
        res = agent.resolve_interests(interests)
        ents = [r["entity_id"] for r in res if r["kind"] == "entity"]
        tags = [r["entity_id"] for r in res if r["kind"] == "tag"]
        print(f"\n=== {label}")
        for vname, extra in VARIANTS.items():
            params = {"filter.type": "urn:entity:destination", "signal.interests.entities": ents,
                      "signal.interests.tags": tags, "take": 25, **extra}
            try:
                out = client.insights(params)
            except QlooError as e:
                print(f"  [{vname}] ERROR {str(e)[:160]}")
                continue
            rows = []
            for e in out:
                geo = (e.get("properties") or {}).get("geocode") or {}
                rows.append(f"{e.get('name')} [{geo.get('country_code') or geo.get('country') or '?'}] {e.get('query', {}).get('affinity', 0):.2f}")
            print(f"  [{vname}] {len(out)} results: " + "; ".join(rows[:25]))


if __name__ == "__main__":
    main()
