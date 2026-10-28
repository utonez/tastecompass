"""Qloo client: a real HTTP client and a mock with the same interface.

Real API facts used here (from public hackathon projects; confirm against the
docs you receive with your key):
  base URL   https://hackathon.api.qloo.com
  auth       header  X-Api-Key: <key>
  GET /search?query=...&types=urn:entity:artist&take=5     -> {"results": [entity, ...]}
  GET /v2/insights?filter.type=urn:entity:place
                  &filter.location.query=Bristol, United Kingdom
                  &signal.interests.entities=<id1>,<id2>
                  &feature.explainability=true&take=10
      -> {"success": true, "results": {"entities": [
            {"entity_id", "name", "subtype", "properties": {...},
             "query": {"affinity": 0.87,
                       "explainability": {"signal.interests.entities": [{"entity_id", "score"}]}}}]}}
  GET /v2/tags?filter.query=hiking                          -> {"results": {"tags": [...]}}
  GET /v2/insights?filter.type=urn:heatmap&filter.location.query=United Kingdom&signal...
      -> {"results": {"heatmap": [{"location": {...}, "query": {"affinity": ...}}]}}
Empty list parameters make the live API answer 400, so they are dropped.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = "https://hackathon.api.qloo.com"


class QlooError(RuntimeError):
    pass


def _clean(params: dict) -> dict:
    out = {}
    for k, v in params.items():
        if v is None or v == "" or v == []:
            continue
        out[k] = ",".join(map(str, v)) if isinstance(v, (list, tuple)) else v
    return out


class QlooClient:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL, timeout: float = 12.0):
        if not api_key:
            raise QlooError("QLOO_API_KEY is empty")
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._cache: dict[str, dict] = {}
        # disk cache: a repeated demo run never waits on (or fails because of) the network
        self.cache_dir = Path(os.environ.get("QLOO_CACHE_DIR", Path(__file__).resolve().parent.parent / ".qloo_cache"))

    def _get(self, path: str, params: dict, timeout: float | None = None) -> dict:
        url = f"{self.base_url}{path}?{urllib.parse.urlencode(_clean(params))}"
        if url in self._cache:
            return self._cache[url]
        cache_file = self.cache_dir / (hashlib.md5(url.encode()).hexdigest() + ".json")
        if cache_file.exists():
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            self._cache[url] = data
            return data
        if any(ch.isspace() or not ch.isprintable() for ch in self.api_key):
            # never echo the key: urllib's own error message would include it
            raise QlooError("QLOO_API_KEY contains a space or line break - re-paste it without extra characters")
        req = urllib.request.Request(url, headers={"X-Api-Key": self.api_key, "Accept": "application/json"})
        delay = 0.5
        timeouts = 0
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    self._cache[url] = data
                    try:
                        self.cache_dir.mkdir(parents=True, exist_ok=True)
                        cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                    except OSError:
                        pass
                    return data
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500:
                    time.sleep(delay)
                    delay = min(delay * 2, 4)
                    continue
                body = e.read().decode("utf-8", "replace")[:300]
                raise QlooError(f"HTTP {e.code} for {path}: {body}") from e
            except urllib.error.URLError as e:
                if attempt == 4:
                    raise QlooError(f"Network error for {path}: {e}") from e
                time.sleep(delay)
            except TimeoutError as e:  # read timeout (heatmap can be slow): one more try, then give up
                timeouts += 1
                if timeouts >= 2:
                    raise QlooError(f"Timed out twice for {path}") from e
        raise QlooError(f"Gave up on {path} after retries")

    def search(self, query: str, types: str | None = None, take: int = 3) -> list[dict]:
        data = self._get("/search", {"query": query, "types": types, "take": take})
        res = data.get("results", data)
        return res if isinstance(res, list) else res.get("entities", [])

    def insights(self, params: dict) -> list[dict]:
        data = self._get("/v2/insights", params)
        res = data.get("results", {})
        return res.get("entities", []) if isinstance(res, dict) else res

    def tags(self, query: str, take: int = 3) -> list[dict]:
        """GET /v2/tags?filter.query=hiking -> [{"id" or "tag_id", "name", "type"}]"""
        data = self._get("/v2/tags", {"filter.query": query, "take": take})
        res = data.get("results", data)
        if isinstance(res, dict):
            res = res.get("tags") or res.get("entities") or []
        return res if isinstance(res, list) else []

    def heatmap(self, params: dict) -> list[dict]:
        """GET /v2/insights?filter.type=urn:heatmap -> [{"location": {"latitude", "longitude", "geohash"},
        "query": {"affinity", "affinity_rank", "popularity"}}]. One call covers a whole country, so
        affinities are comparable between cities (per-city place affinities are not)."""
        data = self._get("/v2/insights", {**params, "filter.type": "urn:heatmap"}, timeout=45)
        res = data.get("results", {})
        return res.get("heatmap", []) if isinstance(res, dict) else []


class MockQlooClient:
    """Offline stand-in. Same methods and response shapes as QlooClient.

    Affinity is synthetic: overlap between the interest's tags (mock/catalog.json)
    and the city's fallback_tags, plus small deterministic noise. It exists so the
    pipeline can be built and demoed before the key arrives - never present mock
    numbers as Qloo results.
    """

    def __init__(self, catalog_path: Path, cities: list[dict]):
        self.catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))["entities"]
        self.city_tags = {c["qloo_location"]: set(c["fallback_tags"]) for c in cities}
        self.city_coords = {c["qloo_location"]: (c["lat"], c["lon"]) for c in cities}
        self.by_id = {e["entity_id"]: e for e in self.catalog}

    def search(self, query: str, types: str | None = None, take: int = 3) -> list[dict]:
        q = query.strip().lower()
        hits = [e for e in self.catalog if q in e["name"].lower() or q in [a.lower() for a in e.get("aliases", [])]]
        if not hits:  # unknown interest: invent a placeholder entity tagged with the words themselves
            eid = "MOCK-" + hashlib.md5(q.encode()).hexdigest()[:8].upper()
            ent = {"entity_id": eid, "name": query, "subtype": types or "urn:entity:unknown", "tags": q.split()}
            self.by_id[eid] = ent
            hits = [ent]
        return hits[:take]

    @staticmethod
    def _noise(*parts: str) -> float:
        h = int(hashlib.md5("|".join(parts).encode()).hexdigest()[:6], 16)
        return (h % 1000) / 1000 * 0.08  # 0 - 0.08

    def insights(self, params: dict) -> list[dict]:
        loc = params.get("filter.location.query", "")
        ids = params.get("signal.interests.entities") or []
        if isinstance(ids, str):
            ids = ids.split(",")
        ctags = self.city_tags.get(loc, set())
        take = int(params.get("take", 10))
        out = []
        for i in range(take):
            contribs, total = [], 0.0
            for eid in ids:
                ent = self.by_id.get(eid, {"tags": []})
                overlap = len(set(ent.get("tags", [])) & ctags) / max(len(ent.get("tags", [])), 1)
                s = overlap * (1 - i * 0.04) + self._noise(eid, loc, str(i))
                contribs.append({"entity_id": eid, "score": round(s, 3)})
                total += s
            aff = total / max(len(ids), 1)
            # label the place with a city tag its strongest interest shares, so mock places read like
            # "cafes spot" / "live music spot" instead of a bare number (does not affect affinity)
            top = max(contribs, key=lambda c: c["score"])["entity_id"] if contribs else None
            kinds = sorted(set(self.by_id.get(top, {}).get("tags", [])) & ctags) or sorted(ctags) or ["local"]
            kind = kinds[i % len(kinds)]
            city = loc.split(",")[0]
            out.append({
                "entity_id": f"MOCKPLACE-{hashlib.md5((loc + str(i)).encode()).hexdigest()[:6]}",
                "name": f"[mock] {kind} spot #{i + 1} in {city}",
                "subtype": "urn:entity:place",
                "properties": {"geocode": {"city": city}},
                "tags": [{"name": kind}],
                "query": {"affinity": round(min(aff, 1.0), 3),
                          "explainability": {"signal.interests.entities": sorted(contribs, key=lambda c: -c["score"])}},
            })
        return sorted(out, key=lambda e: -e["query"]["affinity"])


    def tags(self, query: str, take: int = 3) -> list[dict]:
        """Only words that exist as tags in the mock world (catalog + city tags) resolve to a tag."""
        q = query.strip().lower()
        vocab = {t for e in self.catalog for t in e.get("tags", [])} | {t for ts in self.city_tags.values() for t in ts}
        names = [q] if q in vocab else sorted(v for v in vocab if v in q)
        out = []
        for n in names[:take]:
            tid = "urn:tag:mock:" + n.replace(" ", "_")
            self.by_id[tid] = {"tags": [n]}
            out.append({"id": tid, "name": n.title() if n == q else n, "type": "urn:tag:mock"})
        return out

    def heatmap(self, params: dict) -> list[dict]:
        ids = []
        for k in ("signal.interests.entities", "signal.interests.tags"):
            v = params.get(k) or []
            ids += v.split(",") if isinstance(v, str) else list(v)
        cells = []
        for loc, (lat, lon) in self.city_coords.items():
            ctags = self.city_tags.get(loc, set())
            scores = []
            for eid in ids:
                t = set(self.by_id.get(eid, {}).get("tags", []))
                scores.append(len(t & ctags) / max(len(t), 1) + self._noise(eid, loc, "heat"))
            aff = sum(scores) / max(len(scores), 1)
            cells.append({"location": {"latitude": lat, "longitude": lon, "geohash": "mock"},
                          "query": {"affinity": round(min(aff, 1.0), 3), "affinity_rank": None, "popularity": None}})
        return cells


def make_client(root: Path, cities: list[dict], force_mock: bool = False):
    key = os.environ.get("QLOO_API_KEY", "")
    if key and not force_mock:
        return QlooClient(key, os.environ.get("QLOO_BASE_URL", DEFAULT_BASE_URL)), "live"
    return MockQlooClient(root / "mock" / "catalog.json", cities), "mock"
