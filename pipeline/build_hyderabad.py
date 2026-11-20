"""Turn the curated Hyderabad seed file into mb_projects.json records, then run the shared city build.

Hyderabad has no Magicbricks crawl yet, so its societies come from OpenStreetMap plus hand research
(data/seed/hyderabad.json). Only the record shape lives here: pricing, scoring, shapes, events and the CSV
exports stay in build_city, so Hyderabad inherits every upstream fix and the Gurugram build is untouched.

usage: python build_hyderabad.py  -> out/hyderabad/mb_projects.json, then the shared build for the city
"""
import hashlib
import json
import pathlib
import re

import build_city
import geo

ROOT = pathlib.Path(__file__).parent
OUT = ROOT / "out"
SEED = ROOT.parent / "data" / "seed" / "hyderabad.json"
CITY = "hyderabad"
ID_MARK = "seed-"  # a Magicbricks psmid is always 7 digits, so this marker cannot collide with a real id
# Magicbricks unit codes, read off build_city.UNIT_KIND (mb_parse.parse_unit_info is where they come from).
# Setting one is what makes kind_of() read the kind as data instead of guessing "apartment~" from the name.
KIND_CODE = {"apartment": "10002", "builder floor": "10003", "villa": "10017", "plot": "10000"}
NEAR_M = 400  # the radius build_city.dedupe uses to call two listings the same society


def seed_id(s):
    """Same seed row, same id on every run (a digest, never a date or a counter).

    The coordinates are in the digest so two societies sharing a name in different localities never collide,
    rounded to ~11 m so a small coordinate correction in the seed does not silently rename the society: this
    id becomes s<id>, the permalink the web app opens.
    """
    key = f"{build_city.norm(s.get('name'))}|{s['lat']:.4f}|{s['lng']:.4f}"
    return ID_MARK + hashlib.sha1(key.encode()).hexdigest()[:10]


def source_url(s):
    """The page behind the card and every research event, so it has to be one that exists.

    The seed's own source wins, else the OSM object the coordinates were read from, which is where the record
    really comes from. Never a Magicbricks URL: a pdpid guessed for a society that was never crawled would
    404 and would credit a page we never read.
    """
    if s.get("source"):
        return s["source"]
    src = s.get("coord_source") or ""
    return "https://www.openstreetmap.org/" + src[4:] if src.startswith("osm:") and "/" in src else None


def unit_rows(s, code):
    """[{bhk, sqft, kind}] like mb_parse.parse_unit_info, which drops units without a printed size: a null
    size would both crash build_city.portal_units (it formats int(sqft)) and mean inventing the number."""
    return [{"bhk": u.get("bhk"), "sqft": float(u["sqft"]), "kind": code}
            for u in s.get("unit_types") or [] if u.get("sqft")]


def to_project(s):
    """One seed society -> one mb_projects.json record, shaped like a crawled project.

    Anything the seed does not know stays null rather than estimated: prices, ratings, trends and listing
    counts are portal numbers we do not have, and only the build may publish a labelled estimate.
    """
    code = KIND_CODE.get(s.get("kind"))
    units = unit_rows(s, code)
    return {"mb_id": seed_id(s), "name": s["name"], "developer": s.get("developer"), "locality": s.get("locality"),
            "pincode": s.get("pincode"), "status": s.get("status"), "possession": s.get("possession"),
            "units": s.get("units"), "towers": s.get("towers"), "acres": s.get("acres"),
            "price_min": None, "price_max": None, "prop_types": None, "brochure_url": None,
            "card_units": units, "images": [], "type_codes": [code] if code else [],
            "url": source_url(s), "lat": s["lat"], "lng": s["lng"],
            "configs": {"units": list(units), "by_bhk": {}},
            "rating_count": None, "ratings": {}, "description": None,
            "amenities": s.get("amenities") or [], "sale_listings": s.get("sale_listings") or [],
            "rent_listings": s.get("rent_listings") or []}


def stem(t):
    """Trailing plural off a word longer than three letters, so "homes" and "home" are one token."""
    return t[:-1] if len(t) > 3 and t.endswith("s") else t


GENERIC_S = {stem(g) for g in build_city.GENERIC}


def name_key(name):
    """build_city.tokens, but plural-blind: the two sources being matched here disagree about plurals.

    OSM says "My Home Navadweepa" where the portal says "My Homes Navadweepa", and GENERIC lists only one of
    each such pair ("homes" but not "home", "park" but not "parks"), so a strict token set treats the leftover
    singular as a distinguishing word and the same society arrives twice. On the real crawl index that is 20 of
    the 635 seed societies. Stemming both sides is safe here because the 400 m test below still has to agree.
    """
    return {s for t in re.findall(r"[a-z0-9]+", (name or "").lower()) if len(t) > 2
            for s in [stem(t)] if s not in GENERIC_S}


def same_society(a, b):
    """build_city.dedupe's rule: the same name words, less than 400 m apart. A name built only of generic
    words (tokens() drops "homes", "towers", ...) has no distinguishing token, so compare the whole name."""
    at, bt = name_key(a.get("name")), name_key(b.get("name"))
    same_name = at == bt if at or bt else build_city.norm(a.get("name")) == build_city.norm(b.get("name"))
    if not same_name or not (a.get("lat") and a.get("lng") and b.get("lat") and b.get("lng")):
        return False
    return geo.dist_m((a["lng"], a["lat"]), (b["lng"], b["lat"])) < NEAR_M


def merge_crawled(existing, seeded):
    """Crawled records win: a seed society is added only when the crawl has nothing by that name nearby.

    Rows an earlier run wrote are rebuilt, not kept, so a correction in the seed file is picked up instead of
    being shadowed by this script's own output.
    """
    kept = [p for p in existing if not str(p.get("mb_id") or "").startswith(ID_MARK)]
    added = [s for s in seeded if not any(same_society(s, p) for p in kept)]
    # crawled first: build_city.dedupe keeps the first of two near-duplicates, which should be the crawled one
    return kept + added, {"kept": len(kept), "merged": len(seeded) - len(added), "added": len(added)}


def main():
    records = [to_project(s) for s in json.loads(SEED.read_text())["societies"]]
    out = OUT / CITY
    f = out / "mb_projects.json"
    if f.exists():
        records, c = merge_crawled(json.loads(f.read_text()), records)
        print(f"crawled kept {c['kept']} · seed already crawled {c['merged']} · seed added {c['added']}")
    else:
        print(f"no Magicbricks crawl for {CITY} yet: {len(records)} societies from the seed file")
    out.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(records, indent=0))  # indent=0, the way mb_crawl writes this file
    build_city.main(CITY)


if __name__ == "__main__":
    main()
