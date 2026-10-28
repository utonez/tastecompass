"""First thing to run when the Qloo key arrives.

    export QLOO_API_KEY=xxxx
    python probe.py "Radiohead" "Specialty coffee"

It resolves each interest with /search, then asks /v2/insights for places in two
very different cities, and prints raw JSON + a one-line comparison. If the two
cities' mean affinities are almost the same for several different interest sets,
switch the taste score to the fallback (tags vs cities.json fallback_tags).
"""
import json
import os
import sys

from tastecompass.qloo import DEFAULT_BASE_URL, QlooClient

CITIES = ["Edinburgh, United Kingdom", "Manchester, United Kingdom"]


def main():
    client = QlooClient(os.environ["QLOO_API_KEY"], os.environ.get("QLOO_BASE_URL", DEFAULT_BASE_URL))
    interests = sys.argv[1:] or ["Radiohead", "Hiking"]
    ids = []
    for q in interests:
        hits = client.search(q, take=1)
        print(f"\n/search {q!r}:\n" + json.dumps(hits[:1], indent=2, ensure_ascii=False)[:1500])
        if hits:
            ids.append(hits[0].get("entity_id") or hits[0].get("id"))
    for city in CITIES:
        ents = client.insights({"filter.type": "urn:entity:place", "filter.location.query": city,
                                "signal.interests.entities": ids, "feature.explainability": "true", "take": 10})
        affs = [e.get("query", {}).get("affinity", 0) for e in ents]
        print(f"\n/v2/insights places in {city}: {len(ents)} results, mean affinity {sum(affs)/max(len(affs),1):.3f}")
        print(json.dumps(ents[:2], indent=2, ensure_ascii=False)[:2000])


if __name__ == "__main__":
    main()
