"""Turn the curated Hyderabad seed file into mb_projects.json records, then run the shared city build.

Hyderabad has no Magicbricks crawl yet, so its societies come from OpenStreetMap plus hand research
(data/seed/hyderabad.json). Only the record shape lives here: pricing, scoring, shapes, events and the CSV
exports stay in build_city, so Hyderabad inherits every upstream fix and the Gurugram build is untouched.

usage: python build_hyderabad.py  -> out/hyderabad/mb_projects.json, then the shared build for the city
"""
import collections
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
LOCALITY_M = 500  # how close a crawled project has to be to name this one's neighbourhood


def seed_id(s):
    """Same seed row, same id on every run (a digest, never a date or a counter).

    Keyed on the OSM object the row was read from, because that object is what the row is about: this id
    becomes s<id>, the permalink the web app opens, and both of the alternatives move. A re-traced outline
    shifts the coordinates, and OSM names get corrected -- "Pakshiraj Apartments" losing its plural would
    rename the society. Every one of the 626 seeded rows has an OSM way or relation; a hand-placed row
    falls back to its name and coordinates, rounded to ~11 m.
    """
    src = s.get("coord_source") or ""
    key = src if src.startswith("osm:") else f"{build_city.norm(s.get('name'))}|{s['lat']:.4f}|{s['lng']:.4f}"
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
    """Trailing plural off a word longer than three letters, so "homes" and "home" are one word."""
    return t[:-1] if len(t) > 3 and t.endswith("s") else t


def words(name):
    """Every word of a name in order, stemmed, generic ones kept: "My Homes Navadweepa" -> (my, home, navadweepa).

    This exists because the two sources disagree about plurals: OSM says "My Home Navadweepa" where the portal
    says "My Homes Navadweepa", and build_city.GENERIC lists only one of each such pair ("homes" but not
    "home"), so the leftover singular reads as a distinguishing word and the society arrives twice.

    Keeping the generic words is what makes this safe. Dropping them as well would erase the brand from every
    "My Home X" -- Hyderabad's largest developer -- leaving {x}, which equals "NC X" and "X Residency". The
    order is kept for the same reason: "Villa Greens" and "Green Villas" are two Kollur projects 300 m apart,
    and the same three words in the same order really is the same name written twice.
    """
    return tuple(stem(t) for t in re.findall(r"[a-z0-9]+", (name or "").lower()))


def letters(name):
    """A name with the spacing thrown away, so "R K Towers" and "RK Towers" compare equal."""
    return re.sub(r"[^a-z0-9]", "", build_city.norm(name) or "")


def builder_words(p):
    """The developer's distinguishing words that the project's own name does not already contain.

    A record whose developer field merely repeats the name -- OSM carries "Villa Gooncha Hill" as both --
    says nothing about whether a longer name is the same project under its builder's brand.
    """
    return build_city.tokens(p.get("developer")) - build_city.tokens(p.get("name"))


def builder_prefix(a, b):
    """One name is the other with its developer's name added: "Aditya Eden Park" is the portal's "Eden Park".

    The portal lists a project under the builder's brand and OSM under the name on the gate, which is 10 of
    the 626 seeded societies arriving twice. Subset alone merges far too much -- "Janapriya Apartments" into
    "Janapriya Arvind Avenue" 1 m away, "Alekhya Homes" into "Alekhya Palm Woods" -- so every word the longer
    name adds has to be a word one of the two records names as the developer.
    """
    at, bt = build_city.tokens(a.get("name")), build_city.tokens(b.get("name"))
    if not (at and bt) or at == bt:
        return False
    extra = (bt - at) if at < bt else (at - bt) if bt < at else None
    if extra is None:  # neither contains the other: two different names, not one with a prefix
        return False
    dev = builder_words(a) | builder_words(b)
    return bool(dev) and extra <= dev


def same_society(a, b):
    """The same society under either source's spelling, and less than 400 m away.

    Four ways to agree on the name, all of which still have to pass the distance test: dedupe's own rule (the
    same distinguishing words), the same words outright whatever the plurals, the same letters once the
    spacing is thrown away, or one name being the other under the builder's brand.

    The letters rule is not reserved for names dedupe gives up on. "Hardhik Anmol Apartments" and "Anmol
    Apartments" both leave tokens behind, so dedupe compares them and finds them different, which is right
    for two listings and wrong for two sources describing one building 20 m apart.

    A clash of building form still refuses, as it does in dedupe: "Meenakshi Towers" and "Meenakshi
    Apartment" at the same point are two buildings on one site, and merging drops one of them off the map.
    """
    an, bn = a.get("name"), b.get("name")
    at, bt = build_city.tokens(an), build_city.tokens(bn)
    if build_city.other_form(build_city.forms(an), build_city.forms(bn)):
        return False
    same_name = (bool(at) and at == bt) or words(an) == words(bn) or letters(an) == letters(bn) \
        or builder_prefix(a, b)
    if not same_name or not (a.get("lat") and a.get("lng") and b.get("lat") and b.get("lng")):
        return False
    return geo.dist_m((a["lng"], a["lat"]), (b["lng"], b["lat"])) < NEAR_M


def nearby(s, grid):
    """The crawled projects close enough to s to be the same society, or to name its neighbourhood.

    A 0.01 degree grid cell is ~1.1 km, so the 3x3 block around a point cannot miss anything within 400 m,
    and comparing 626 seed rows against the ~300 projects around each beats comparing them against all
    27,000: the same answer, in a second instead of four minutes.
    """
    if not (s.get("lat") and s.get("lng")):
        return []
    return list(grid.near((s["lng"], s["lat"])))


def borrow_locality(s, grid):
    """Name this society's neighbourhood the way the crawled projects around it do. True when any were near.

    The seed reads its locality off the nearest OSM place node, which in the suburbs is kilometres away: it
    agrees with the portal's label for the same spot on 138 of 614 societies, calling Kokapet "Narsingi" and
    Tellapur "Ramachandrapuram". The portal's vocabulary is the one the other 27,000 societies use, and the
    locality filter, the rental yields and the locality price medians are all computed per label, so a seeded
    society in a crawled neighbourhood is better off named the way its neighbours are. Judged against the
    majority label within 1 km, which neither source controls, the crawl is right where they differ by 265
    rows to 44.

    The majority of the block rather than the single nearest project, because one mislabelled listing should
    not decide: the project 54 m from a society in Alwal says Kompally, where 66 of the 67 around it say
    Alwal, and the nearest neighbour to three Gandipet societies says Madhapur, Ameenpur and Kokapet.
    """
    pt = (s["lng"], s["lat"])
    near = sorted((geo.dist_m(pt, (p["lng"], p["lat"])), p["locality"]) for p in nearby(s, grid)
                  if p.get("locality") and p.get("lat") and p.get("lng"))
    near = [t for t in near if t[0] < LOCALITY_M]
    if not near:
        return False
    votes = collections.Counter(loc for _, loc in near)
    top = max(votes.values())
    loc = next(loc for _, loc in near if votes[loc] == top)  # ties go to the nearest, hence the sort
    s["locality"] = loc
    s["locality_source"] = f"the label on {top} of {len(near)} crawled projects within {LOCALITY_M} m"
    return True


def merge_crawled(existing, seeded):
    """Crawled records win: a seed society is added only when the crawl has nothing by that name nearby.

    Rows an earlier run wrote are rebuilt, not kept, so a correction in the seed file is picked up instead of
    being shadowed by this script's own output. A seed row that survives still borrows its neighbourhood's
    name from the crawl, so the locality filter lists it where a resident would look for it.
    """
    kept = [p for p in existing if not str(p.get("mb_id") or "").startswith(ID_MARK)]
    grid = build_city.Grid([p for p in kept if p.get("lat") and p.get("lng")], lambda p: (p["lng"], p["lat"]))
    added = [s for s in seeded if not any(same_society(s, p) for p in nearby(s, grid))]
    relabelled = sum(borrow_locality(s, grid) for s in added if s.get("lat") and s.get("lng"))
    # crawled first: build_city.dedupe keeps the first of two near-duplicates, which should be the crawled one
    return kept + added, {"kept": len(kept), "merged": len(seeded) - len(added), "added": len(added),
                          "relabelled": relabelled}


def main():
    records = [to_project(s) for s in json.loads(SEED.read_text())["societies"]]
    out = OUT / CITY
    f = out / "mb_projects.json"
    if f.exists():
        records, c = merge_crawled(json.loads(f.read_text()), records)
        print(f"crawled kept {c['kept']} · seed already crawled {c['merged']} · seed added {c['added']}"
              f" ({c['relabelled']} taking a neighbour's locality)")
    else:
        print(f"no Magicbricks crawl for {CITY} yet: {len(records)} societies from the seed file")
    out.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(records, indent=0))  # indent=0, the way mb_crawl writes this file
    build_city.main(CITY)


if __name__ == "__main__":
    main()
