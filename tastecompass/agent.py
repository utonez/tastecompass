"""TasteCompass agent: plans which tools to call from the user's Scope, runs them, and
keeps a trace of every step so the demo can show *why* it did what it did.

Scope modes
  A  nothing decided      -> rank cities, then programmes   (data currently UK only)
  B  country decided      -> rank cities in that country, then programmes
  C  city decided         -> city is a hard filter; rank programmes there
  D  school/programme decided -> hard filter; check life fit, plan the
                                 application, and surface better-fitting alternatives
Decided levels are HARD filters: the agent never recommends outside them
(except clearly labelled 'alternatives' in mode D).
"""
from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from datetime import date
from pathlib import Path

from . import planner
from .scoring import DEFAULT_WEIGHTS, CityTaste, normalise, program_fit

ROOT = Path(__file__).resolve().parent.parent
MAX_PARALLEL = 6       # concurrent Qloo calls (one per city); the client retries 429s with backoff
EVIDENCE_CITIES = 6    # besides cities with verified programmes, look up places for this many top-taste cities
EVIDENCE_PLACES = 10   # places kept per city (UI lists 5; "A week in your city" plans with all of them)
# /search without a type returns places anywhere ("Hiking" -> a trail in Rio), so restrict it to taste entities
CULTURAL_TYPES = ",".join(f"urn:entity:{t}" for t in
                          ["artist", "movie", "tv_show", "book", "brand", "podcast", "videogame", "person"])
COUNTRY_QUERY = "United Kingdom"
# 10 km = the city itself. At 25 km the circle takes in countryside and sea, so coastal/smaller cities
# (Edinburgh, Glasgow) were diluted and the score tracked city size instead of taste (checked on cached runs 10/27).
HEATMAP_RADIUS_KM = 10


def _name_ok(query: str, name: str | None) -> bool:
    q, n = query.lower().strip(), (name or "").lower().strip()
    return bool(n) and (q == n or q in n or n in q or SequenceMatcher(None, q, n).ratio() >= 0.6)


def _km(lat1, lon1, lat2, lon2) -> float:
    r = math.radians
    a = math.sin(r(lat2 - lat1) / 2) ** 2 + math.cos(r(lat1)) * math.cos(r(lat2)) * math.sin(r(lon2 - lon1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(a))


def heat_near(city: dict, cells: list[dict], radius_km: float = HEATMAP_RADIUS_KM) -> float | None:
    """Mean affinity of all heatmap cells within radius of the city centre; None if no cell is close.
    (Mean, not top-k: affinity saturates at 1.0 and big cities have more cells, so top-k would always favour London.)"""
    affs = []
    for c in cells:
        loc, q = c.get("location") or {}, c.get("query") or {}
        lat, lon = loc.get("latitude", loc.get("lat")), loc.get("longitude", loc.get("lon"))
        if lat is None or lon is None or q.get("affinity") is None:
            continue
        if _km(city["lat"], city["lon"], float(lat), float(lon)) <= radius_km:
            affs.append(float(q["affinity"]))
    if not affs:
        return None
    return sum(affs) / len(affs)


CHAINS = {"subway", "greggs", "mcdonald's", "kfc", "burger king", "starbucks", "costa coffee", "pret a manger",
          "next", "poundland", "tesco", "sainsbury's", "holiday inn", "premier inn", "travelodge", "bp", "shell",
          "wagamama", "nando's", "pizza express", "domino's", "boots", "primark"}
MIN_EVIDENCE_POPULARITY = 0.3


def good_evidence(city: dict, places: list[dict]) -> list[dict]:
    """Places worth showing as 'why this city': inside the city itself (Qloo's location query for Bristol
    also returns Bath and Wiltshire), not a national chain, and not near-unknown. Affects display only."""
    name = city["name"].lower()
    keep = []
    for p in places:
        geo_city = ((p.get("properties") or {}).get("geocode") or {}).get("city")
        pname = str(p.get("name", "")).lower().strip()
        if geo_city and geo_city.lower() != name:
            continue
        if any(pname == c or pname.startswith(c + " ") for c in CHAINS):
            continue
        if p.get("popularity") is not None and p["popularity"] < MIN_EVIDENCE_POPULARITY:
            continue
        keep.append(p)
    return keep


def _is_place_tag(t: dict) -> bool:
    """Tags usable as place signals (activities, amenities, offerings, dishes) rather than media genres."""
    parents = [x.get("type") for x in t.get("parents") or [] if isinstance(x, dict)]
    return "urn:entity:place" in parents or str(t.get("type", "")).endswith(":place")


def tag_names(entity: dict) -> list[str]:
    """Qloo tags come as dicts with a name; the mock catalog uses plain strings."""
    out = []
    for t in entity.get("tags") or []:
        name = t.get("name") if isinstance(t, dict) else t
        if isinstance(name, str) and name:
            out.append(name.lower())
    return out


def place_evidence(p: dict) -> dict:
    """The parts of a Qloo place worth showing: name, affinity, which interests drove it.
    Field names beyond name/query follow the shape noted in qloo.py; anything missing is just left out."""
    q = p.get("query", {})
    contribs = sorted(q.get("explainability", {}).get("signal.interests.entities", []), key=lambda c: -c.get("score", 0))
    props = p.get("properties") or {}
    tags = tag_names(p)[:3]
    return {"entity_id": p.get("entity_id"), "name": p.get("name"), "affinity": q.get("affinity"),
            "drivers": [c["entity_id"] for c in contribs[:2] if c.get("score", 0) > 0],
            "address": props.get("address"), "tags": tags}


def load_universities(root: Path = ROOT) -> list[dict]:
    try:
        return json.loads((root / "data" / "universities.json").read_text(encoding="utf-8"))["universities"]
    except FileNotFoundError:
        return []


def load_data(root: Path = ROOT):
    cities = json.loads((root / "data" / "cities.json").read_text(encoding="utf-8"))["cities"]
    programs = json.loads((root / "data" / "programs.json").read_text(encoding="utf-8"))["programs"]
    return cities, programs


def detect_mode(scope: dict) -> str:
    if scope.get("program_ids") or scope.get("school"):
        return "D"
    if scope.get("city"):
        return "C"
    if scope.get("country"):
        return "B"
    return "A"


class TasteCompassAgent:
    def __init__(self, client, client_kind: str, cities: list[dict], programs: list[dict], universities: list[dict] | None = None):
        self.client, self.client_kind = client, client_kind
        self.cities = {c["id"]: c for c in cities}
        self.programs = programs
        self.universities = universities if universities is not None else load_universities()
        self.trace: list[str] = []

    def log(self, msg: str):
        self.trace.append(msg)

    # ---- tools -----------------------------------------------------------
    def _resolve_one(self, text: str):
        """Activities ('hiking', 'specialty coffee') are Qloo *tags*; works and people are *entities*.
        Order: exact tag name -> entity whose name matches -> any tag -> first entity (loose)."""
        tags = []
        if hasattr(self.client, "tags"):
            try:
                tags = self.client.tags(text, take=10)
            except Exception:
                tags = []
        tags = sorted(tags, key=lambda t: not _is_place_tag(t))  # place-related tags first, order otherwise kept
        hits = self.client.search(text, types=CULTURAL_TYPES, take=3)

        def as_tag(t, how):
            tid = t.get("id") or t.get("tag_id") or t.get("value")
            return {"input": text, "entity_id": tid, "name": t.get("name", text), "kind": "tag",
                    "tags": [str(t.get("name", text)).lower()]}, how

        def as_entity(h, how):
            return {"input": text, "entity_id": h.get("entity_id") or h.get("id"), "name": h.get("name", text),
                    "kind": "entity", "tags": tag_names(h)}, how

        key = text.lower().strip()
        # a well-known work/person with exactly this name beats a tag ("Harry Potter" is the books, not a dish)
        # (name contains the query: "Harry Potter" -> "Harry Potter and the Philosopher's Stone")
        famous = [h for h in hits if key in str(h.get("name", "")).lower() and (h.get("popularity") or 0) >= 0.9]
        if famous:
            return as_entity(famous[0], "entity (exact)")
        exact = [t for t in tags if str(t.get("name", "")).lower().strip() == key]
        if exact:
            return as_tag(exact[0], "tag (exact)")
        named = [h for h in hits if _name_ok(text, h.get("name"))]
        if named:
            return as_entity(named[0], "entity")
        if tags:
            return as_tag(tags[0], "tag (closest)")
        if hits:
            return as_entity(hits[0], "entity (loose match - check it)")
        return None, "no match"

    def resolve_interests(self, interests: list[str]) -> list[dict]:
        # resolved in parallel; results (and the trace) keep input order
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as ex:
            outcomes = list(ex.map(self._resolve_one, interests))
        resolved = []
        for text, (item, how) in zip(interests, outcomes):
            if item:
                resolved.append(item)
                self.log(f"resolve('{text}') -> {item['name']} [{how}: {item['entity_id']}]")
            else:
                self.log(f"resolve('{text}') -> no match, skipped")
        return resolved

    def national_heatmap(self, entity_ids: list[str], tag_ids: list[str]) -> list[dict]:
        if not hasattr(self.client, "heatmap"):
            return []
        try:
            return self.client.heatmap({"filter.location.query": COUNTRY_QUERY,
                                        "signal.interests.entities": entity_ids,
                                        "signal.interests.tags": tag_ids})
        except Exception as e:  # keep the demo alive; fall back to per-city places
            self.log(f"heatmap({COUNTRY_QUERY}) failed: {e}")
            return []

    def city_taste(self, city: dict, entity_ids: list[str], tag_ids: list[str] | None = None) -> CityTaste:
        places = self.client.insights({
            "filter.type": "urn:entity:place",
            "filter.location.query": city["qloo_location"],
            "signal.interests.entities": entity_ids,
            "signal.interests.tags": tag_ids or [],
            "feature.explainability": "true",
            "take": 30,   # fetch more, then keep only good evidence (see good_evidence)
        })
        affs = sorted((p.get("query", {}).get("affinity", 0) for p in places), reverse=True)[:5]
        raw = sum(affs) / len(affs) if affs else 0.0
        drivers: dict[str, float] = {}
        for p in places[:5]:
            for c in p.get("query", {}).get("explainability", {}).get("signal.interests.entities", []):
                drivers[c["entity_id"]] = drivers.get(c["entity_id"], 0) + c.get("score", 0)
        shown = good_evidence(city, places)
        return CityTaste(city["id"], raw, evidence=[place_evidence(p) for p in shown[:EVIDENCE_PLACES]],
                         driver_counts=drivers, n_places=len(places))

    # ---- plan + run ------------------------------------------------------
    def run(self, profile: dict, today: date | None = None) -> dict:
        today = today or date.today()
        scope = profile.get("scope", {})
        mode = detect_mode(scope)
        weights = {**DEFAULT_WEIGHTS, **profile.get("weights", {})}
        target = profile.get("target_intake", today.year + 1)
        self.log(f"Scope mode {mode}; Qloo client = {self.client_kind}; weights = {weights}")

        # hard filters from scope
        chosen = self.programs
        if mode == "D":
            ids = set(scope.get("program_ids", []))
            school = (scope.get("school") or "").lower()
            chosen = [p for p in self.programs if p["id"] in ids or (school and school in p["school"].lower())]
            if not chosen:
                raise ValueError(f"No programme in data matches scope {scope}")
        elif mode == "C":
            chosen = [p for p in self.programs if p["city_id"] == scope["city"]]
        self.log(f"Hard filter -> {len(chosen)} programme(s) in scope")

        interests = self.resolve_interests(profile.get("interests", []))
        ids = [i["entity_id"] for i in interests if i.get("kind", "entity") == "entity"]
        tag_ids = [i["entity_id"] for i in interests if i.get("kind") == "tag"]
        names = {i["entity_id"]: i["name"] for i in interests}

        # taste for every city (needed for ranking, and for alternatives in mode D)
        tastes = []
        verified_cities = {p["city_id"] for p in self.programs}
        # cities compared on taste: the major student cities, plus any city the student fixed or has programmes in
        ranked_ids = [cid for cid, c in self.cities.items() if c.get("taste_ranked", True)
                      or cid in verified_cities or (mode == "C" and cid == scope.get("city"))]
        if ids or tag_ids:
            # One UK-wide heatmap scores every university city on the same scale (cheap: 1 call for ~60 cities).
            # Places are looked up only where they'll be shown: cities with verified programmes + the top-taste cities.
            cells = self.national_heatmap(ids, tag_ids)
            heat = {cid: heat_near(self.cities[cid], cells) for cid in ranked_ids} if cells else {}
            found = {cid: v for cid, v in heat.items() if v is not None}
            if found and len(found) >= len(ranked_ids) / 2:
                floor = min(found.values())
                tastes = [CityTaste(cid, found.get(cid, floor), source="heatmap" if cid in found else "heatmap (no nearby cell)")
                          for cid in ranked_ids]
                self.log(f"heatmap({COUNTRY_QUERY}) -> {len(cells)} cells; scored {len(found)}/{len(ranked_ids)} major student cities")
                best = [t.city_id for t in sorted(tastes, key=lambda t: -t.raw)[:EVIDENCE_CITIES]]
                focus = list(dict.fromkeys(best + sorted(verified_cities) + ([scope["city"]] if mode == "C" else [])))
            else:
                self.log(f"heatmap({COUNTRY_QUERY}) -> {len(cells)} cells, too few; using per-city place affinity "
                         f"for the {len(verified_cities)} cities with verified programmes")
                focus = sorted(verified_cities | ({scope["city"]} if mode == "C" else set()))
            def safe_taste(cid):
                try:
                    return self.city_taste(self.cities[cid], ids, tag_ids)
                except Exception as e:  # evidence is nice-to-have: one failed city must not sink the run
                    self.log(f"insights(place, {self.cities[cid]['name']}) failed: {str(e)[:80]}")
                    return CityTaste(cid, 0.0)
            with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as ex:
                looked = dict(zip(focus, ex.map(safe_taste, focus)))
            if tastes:
                for t in tastes:
                    if t.city_id in looked:
                        e = looked[t.city_id]
                        t.evidence, t.driver_counts, t.n_places = e.evidence, e.driver_counts, e.n_places
            else:
                tastes = list(looked.values())
            self.log("Top cities by taste: " + ", ".join(f"{self.cities[t.city_id]['name']} {t.raw:.3f}"
                                                         for t in sorted(tastes, key=lambda t: -t.raw)[:5]))
            self.log(f"insights(place) for {len(looked)} cities as evidence")
        if not normalise(tastes) and tastes:
            self.log("Cities are within 0.02 of each other on taste - treated as a tie (taste score 0.5 for all)")
        taste_by_city = {t.city_id: t for t in tastes}

        def fits(progs):
            return sorted((program_fit(profile, p, self.cities[p["city_id"]], taste_by_city.get(p["city_id"]), weights) for p in progs),
                          key=lambda f: -f.fit)

        ranked = fits(chosen)
        alternatives = []
        if mode == "D":
            floor = min(f.fit for f in ranked)
            alternatives = [f for f in fits([p for p in self.programs if p not in chosen]) if f.fit > floor][:2]
            self.log(f"Alternatives better than your weakest pick: {len(alternatives)}")

        top = ranked if mode == "D" else ranked[: profile.get("top_n", 3)]
        plans = {f.program["id"]: planner.timeline(f.program, today, target) for f in top}
        self.log(f"Built timelines for {len(plans)} programme(s)")

        city_rank = sorted(tastes, key=lambda t: -t.score)

        # discovery layer: every university in the cities that matter, flagged verified / not yet verified
        uni_cities = [scope["city"]] if mode == "C" else [] if mode == "D" else [t.city_id for t in city_rank[:5]]
        n_ver = {}
        for p in self.programs:
            n_ver[p.get("university_id")] = n_ver.get(p.get("university_id"), 0) + 1
        universities = [{**u, "city": self.cities[u["city_id"]]["name"], "verified_programmes": n_ver.get(u["id"], 0)}
                        for cid in uni_cities for u in self.universities if u["city_id"] == cid]
        if universities:
            self.log(f"{len(universities)} universities in {len(uni_cities)} top cit{'y' if len(uni_cities) == 1 else 'ies'}; "
                     f"{sum(1 for u in universities if u['verified_programmes'])} with verified programme data")
        return {
            "universities": universities,
            "mode": mode, "client": self.client_kind, "today": today.isoformat(), "target_intake": target,
            "weights": weights, "interests": interests, "names": names,
            "city_ranking": city_rank, "ranked": ranked, "top": top, "alternatives": alternatives,
            "plans": plans, "trace": self.trace,
        }
