"""Live check of the 10/27 fix: tags for activities + one UK heatmap for comparable city scores.

    $env:QLOO_API_KEY = "..."      (PowerShell)
    python probe2.py

Prints a short summary only - paste the whole output back (no key in it).
"""
import json
import os

from tastecompass.agent import COUNTRY_QUERY, TasteCompassAgent, heat_near, load_data
from tastecompass.qloo import DEFAULT_BASE_URL, QlooClient

SETS = {
    "indie/outdoors": ["Radiohead", "Hiking", "Specialty coffee", "Banksy"],
    "theatre/history": ["Les Misérables", "Harry Potter", "Museums", "Afternoon tea"],
}


def main():
    client = QlooClient(os.environ["QLOO_API_KEY"], os.environ.get("QLOO_BASE_URL", DEFAULT_BASE_URL))
    cities, programs = load_data()
    print("tags('hiking') ->", json.dumps(client.tags("hiking", take=3), ensure_ascii=False)[:600])
    for label, interests in SETS.items():
        agent = TasteCompassAgent(client, "live", cities, programs)
        res = agent.resolve_interests(interests)
        ents = [r["entity_id"] for r in res if r["kind"] == "entity"]
        tags = [r["entity_id"] for r in res if r["kind"] == "tag"]
        print(f"\n=== {label}")
        for line in agent.trace:
            print("  ", line)
        try:
            cells = client.heatmap({"filter.location.query": COUNTRY_QUERY,
                                    "signal.interests.entities": ents, "signal.interests.tags": tags})
        except Exception as e:
            print("  heatmap ERROR:", e)
            continue
        print(f"  heatmap cells: {len(cells)}")
        if cells:
            print("  sample cell:", json.dumps(cells[0], ensure_ascii=False)[:300])
        for c in cities:
            v = heat_near(c, cells)
            print(f"  {c['name']:<11} {'-' if v is None else f'{v:.3f}'}")


if __name__ == "__main__":
    main()
