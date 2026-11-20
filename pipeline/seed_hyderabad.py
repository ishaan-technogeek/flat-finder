"""Build data/seed/hyderabad.json from OpenStreetMap.

Societies in this project come from Magicbricks; no code path creates one from OSM. build_hyderabad.py reads a
seed file so the city has a map before any crawl runs, and this script writes that file.

OSM names 1300-odd apartment buildings and residential areas inside the city bbox. Most are societies, but
the set also holds blocks and phases of one society, micro-colonies, hostels and staff quarters, so the work
is deciding what to keep and merging what is really one place. Every record carries where it came from, and
anything OSM does not say stays null: prices and unit sizes are portal data the crawl fills in.

Overpass responses are cached under pipeline/cache/, so a re-run costs nothing and the output is stable until
the cache is cleared. The committed seed is whatever this prints; it is not hand-edited afterwards.

usage: python seed_hyderabad.py  ->  data/seed/hyderabad.json
"""
import json
import math
import pathlib
import re
from collections import Counter, defaultdict

import osm_fetch

ROOT = pathlib.Path(__file__).parent
OUT = ROOT.parent / "data" / "seed" / "hyderabad.json"
CITY = "hyderabad"
BBOX = tuple(json.loads((ROOT.parent / "data" / "cities.json").read_text())[CITY]["bbox"])

NEAR_M = 400          # same radius build_city.dedupe uses to call two listings one society
SAME_SITE_M = 60      # closer than this, two differently named areas are one gated site
# OSM's suburb layer (170 nodes) is the granularity a renter searches in: Gachibowli, Madhapur, Kokapet.
# The 1434 neighbourhood nodes are micro-colonies, and some are societies themselves, so they are a last
# resort and only when the society is almost on top of one.
LAYERS = [(("suburb", "town"), 5000), (("village",), 3000), (("neighbourhood",), 1500)]

# A name is kept only on positive evidence that it is a housing society: a known Hyderabad developer, or a
# word societies use. Rejecting on keywords instead would drop real ones (Jayabheri Temple Tree is a society).
DEV = (r"my home|aparna|rajapushpa|jayabheri|lanco|smr|ramky|ncc|cybercity|prestige|sattva|asbl|vasavi|"
       r"giridhari|janapriya|alekhya|aditya|vertex|mythri|sumadhura|incor|candeur|honer|sark|pbel|manjeera|"
       r"keerthi|anvita|bhuvan|legend|aliens|vamsiram|mahaveer|sanghi|olympia|phoenix|ashoka|navanaami|"
       r"hallmark|rainbow vistas|indu|lodha|brigade|godrej|myscape|citrus|auro|srka|trendset")
# The subset of the above spelt confidently enough to name as the developer of a society, rather than only to
# recognise one. "Aditya" and "Indu" are also common given names, so they vouch for a name without owning it.
KNOWN = ["My Home", "Aparna", "Rajapushpa", "Jayabheri", "Lanco", "SMR", "Ramky", "NCC", "Cybercity",
         "Prestige", "Sattva", "ASBL", "Vasavi", "Giridhari", "Janapriya", "Alekhya", "Vertex", "Mythri",
         "Sumadhura", "Incor", "Candeur", "Honer", "PBEL", "Manjeera", "Keerthi", "Anvita", "Legend",
         "Aliens", "Vamsiram", "Mahaveer", "Olympia", "Phoenix", "Ashoka", "Hallmark", "Indu", "Lodha",
         "Brigade", "Godrej", "Trendset"]
# "colony" is deliberately absent: in Hyderabad it names a neighbourhood, not a gated society, so it let in
# Defence Colony, Sindhi Colony and LIC Colony. A real society called X Colony needs a second signal.
SUF = (r"apartment|appartment|apts|residency|residences|enclave|tower|heights|hills|villa|homes|"
       r"grande|meadows|county|pride|gardens|estate|nivas|sarovar|springs|greens|vistas|habitat|boulevard|"
       r"avenue|court|crest|elite|paradise|serene|symphony|signature|oak|palm|orchid|zenith|bhooja|"
       r"temple tree|quarters|nilayam|sadan|co operative|cooperative|society")
# Not a society even when the name looks like one.
REJECT = (r"^\s*(block|a block|b block|c block|d block|plot|apt|flat|door|h\.?no)\b|^[\d\-/ ]+$|"
          r"hostel|paying guest|\bpg\b|bunglow|bungalow|mens |womens |book shop|medical|"
          r"restaurant|function hall|kalyana|lodge")
# Tails that mark a phase or block of one society, not a separate society. OSM writes them every way there
# is: "Block - A", "Block-C", "F-Block", "(Phase 2)", "Block - A, B, C &d".
TAIL = (r"\s*[-–,]?\s*\(?\s*\b(?:[a-z]\s*-?\s*(?:block|tower)"
        r"|block\s*-?\s*[a-z0-9]?(?:\s*[&,]\s*[a-z0-9]+)*"
        r"|phase\s*-?\s*[ivx0-9]+|part\s*-?\s*[0-9]+|wing\s*-?\s*[a-z0-9]{1,2}|tower\s*-?\s*[a-z0-9]{1,3}"
        r"|sector\s*[0-9]+|[ivx]{1,4}|[0-9]{1,2})\s*\)?\s*$")
FIX = [(r"\bappartments?\b", "apartments"), (r"\bapts?\b", "apartments"), (r"\bapartment\b", "apartments"),
       (r"\bres\b", ""), (r"\bco operative\b", "co-operative")]
KEEP_CAPS = {"NCC", "SMR", "PBEL", "MES", "NCL", "BSNL", "LIC", "HMDA", "APIIC", "SVSS", "RV", "ONGC", "BHEL"}

# Named candidates and the place vocabulary that locates them. `out center tags` is enough: a seed record is a
# point, and build_city matches it onto the real footprint from osm_areas.geojson at build time.
QUERIES = {
    "seed-apartments": '[out:json][timeout:280];(way["building"="apartments"]["name"]{bb};'
                       'relation["building"="apartments"]["name"]{bb};);out center tags;',
    "seed-residential": '[out:json][timeout:280];(way["landuse"="residential"]["name"]{bb};'
                        'relation["landuse"="residential"]["name"]{bb};);out center tags;',
    "seed-places": '[out:json][timeout:280];node["place"]{bb};out;',
}


def dist_m(a, b):
    """Metres between two (lat, lng) points. A flat earth is accurate enough across one city."""
    my = 111320.0
    mx = my * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot((a[0] - b[0]) * my, (a[1] - b[1]) * mx)


def norm(name):
    return " ".join(re.findall(r"[a-z0-9]+", name.lower()))


def clean(name):
    """How a renter would search for it: no block or phase tail, no misspelt 'appartment', sane case."""
    n = " ".join(name.split())
    for a, b in FIX:
        n = re.sub(a, b, n, flags=re.I)
    prev = None
    while prev != n:  # "Sarovar Grande Block A Phase 2" sheds one tail at a time
        prev = n
        n = re.sub(TAIL, "", n, flags=re.I).strip(" -–,")
    words = []
    for w in n.split():
        if w.upper() in KEEP_CAPS:
            words.append(w)
        elif w.isupper() and len(w) <= 4 and w.isalpha():
            words.append(w.upper())
        else:
            words.append(w.capitalize() if w.islower() or w.isupper() else w)
    return " ".join(words).strip()


def developer_of(name):
    """Only when the developer is unmistakable from the name itself."""
    low = f" {name.lower()} "
    return next((d for d in KNOWN if f" {d.lower()} " in low), None)


def kind_of(raw):
    """From the name as OSM wrote it, before clean() strips a tail that might carry the word."""
    low = raw.lower()
    if "villa" in low:
        return "villa"
    if re.search(r"\bplot|layout\b", low):
        return "plot"
    return "apartment"


def fetch():
    """Raw Overpass responses, cached under pipeline/cache/osm/hyderabad/ by osm_fetch."""
    # osm_fetch takes its city from sys.argv, which names none when imported, so point its cache at ours.
    osm_fetch.CACHE = ROOT / "cache" / "osm" / CITY
    bb = "({},{},{},{})".format(*BBOX)
    return {name: osm_fetch.overpass(q.replace("{bb}", bb), name) for name, q in QUERIES.items()}


def candidates(raw):
    """Named apartment buildings and residential areas, narrowed to probable societies."""
    found = []
    for key, src in (("seed-apartments", "apt"), ("seed-residential", "res")):
        for el in raw[key]["elements"]:
            tags, c = el.get("tags") or {}, el.get("center") or el
            if not tags.get("name") or c.get("lat") is None:
                continue
            found.append({"raw": tags["name"], "src": src, "osm": f"{el['type']}/{el['id']}",
                          "lat": c["lat"], "lng": c.get("lon"), "tags": tags})
    kept = [c for c in found if not re.search(REJECT, c["raw"], flags=re.I)]
    for c in kept:
        c["name"] = clean(c["raw"])
    signal = [c for c in kept if len(c["name"]) >= 4 and re.search(f"{DEV}|{SUF}", c["name"], flags=re.I)]
    return {"named": len(found), "after_reject": len(kept), "after_signal": len(signal)}, signal


def merge_blocks(cands):
    """One record per society: the same name within 400 m is a block, tower or phase of one place."""
    groups = defaultdict(list)
    for c in cands:
        groups[norm(c["name"])].append(c)
    out = []
    for members in groups.values():
        clusters = []
        for m in sorted(members, key=lambda x: (x["lat"], x["lng"])):
            for cl in clusters:
                if dist_m((m["lat"], m["lng"]), (cl[0]["lat"], cl[0]["lng"])) < NEAR_M:
                    cl.append(m)
                    break
            else:
                clusters.append([m])
        for cl in clusters:
            head = next((m for m in cl if m["src"] == "res"), cl[0])  # a residential area is the society site
            out.append({**head, "lat": sum(m["lat"] for m in cl) / len(cl),
                        "lng": sum(m["lng"] for m in cl) / len(cl), "members": len(cl)})
    return out


def merge_sites(societies, limit=SAME_SITE_M):
    """Keep one society per site, even when OSM names the parts differently.

    Clustering by name misses "Janapriya Classic Apartments" sitting 51 m from "Janapriya Metropolis
    Apartments And Classic Homes": one gated site, two mapped areas. At city zoom they are the same pin, so
    the better-ranked name wins.
    """
    kept = []
    for s in sorted(societies, key=lambda x: x["rank"]):
        if all(dist_m((s["lat"], s["lng"]), (k["lat"], k["lng"])) > limit for k in kept):
            kept.append(s)
    return kept


def place_layers(raw):
    """Place nodes grouped by OSM class, plus a lookup from a normalised name to the canonical spelling."""
    by, canon = defaultdict(list), {}
    for el in raw["seed-places"]["elements"]:
        tags, c = el.get("tags") or {}, el.get("center") or el
        if tags.get("place") and tags.get("name") and c.get("lat") is not None:
            by[tags["place"]].append({"name": tags["name"], "lat": c["lat"], "lng": c.get("lon"),
                                      "osm": f"{el['type']}/{el['id']}"})
            canon.setdefault(norm(tags["name"]), tags["name"])
    return by, canon


def locality_of(s, by, canon):
    """Where a renter would say the society is: the coarsest place layer that still has a node nearby.

    The society's own addr:suburb is used only when it names a place OSM also maps, so every locality in the
    seed comes from one vocabulary and the map filter has no near-duplicate spellings. addr:city is ignored:
    it says "Hyderabad", which is the city, not a locality.
    """
    tag = norm(s["tags"].get("addr:suburb") or "")
    if tag in canon:
        return canon[tag], "osm:addr:suburb"
    for kinds, radius in LAYERS:
        best, bd = None, radius
        for k in kinds:
            for p in by.get(k, []):
                d = dist_m((s["lat"], s["lng"]), (p["lat"], p["lng"]))
                if d < bd:
                    best, bd = p, d
        if best:
            return best["name"], f"osm:nearest-{best['osm']}"
    return None, None


def record(s):
    """One seed row. Everything OSM does not say stays null, per the rule never to estimate a number."""
    return {"name": s["name"], "developer": s["developer"], "locality": s["locality"],
            "locality_source": s["locality_source"], "lat": round(s["lat"], 6), "lng": round(s["lng"], 6),
            "coord_source": "osm:" + s["osm"], "kind": s["kind"],
            "status": None, "possession": None, "towers": None, "units": None, "acres": None,
            "pincode": s["tags"].get("addr:postcode"),
            "amenities": [], "unit_types": [], "rent_listings": [], "sale_listings": [], "source": None}


def validate(rows):
    """Fail loudly rather than commit a seed the pipeline would quietly mangle."""
    if not rows:
        raise SystemExit("seed is empty")
    keys = set(rows[0])
    for r in rows:
        assert set(r) == keys, f"{r['name']} has a different key set"
        assert r["name"] and r["locality"] and r["coord_source"], f"{r['name']} is missing provenance"
        assert BBOX[0] < r["lat"] < BBOX[2] and BBOX[1] < r["lng"] < BBOX[3], f"{r['name']} is outside the city"
        assert r["kind"] in ("apartment", "villa", "plot", "builder floor"), f"{r['name']} has kind {r['kind']}"
        # upstream's rule: never estimate a data number. Nothing here is sourced, so nothing here is a number.
        for k in ("towers", "units", "acres", "status", "possession"):
            assert r[k] is None, f"{r['name']} claims {k} with no source"
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            d = dist_m((a["lat"], a["lng"]), (b["lat"], b["lng"]))
            assert d > SAME_SITE_M, f"{a['name']} and {b['name']} are {d:.0f} m apart"


def snapshot(raw):
    """Which OSM extract this seed came from: the oldest of the three responses, so the claim holds for all."""
    stamps = [r.get("osm3s", {}).get("timestamp_osm_base") for r in raw.values()]
    return min((s for s in stamps if s), default=None)


def build():
    raw = fetch()
    counts, cands = candidates(raw)
    societies = merge_blocks(cands)
    counts["after_dedupe"] = len(societies)
    for s in societies:
        s["developer"] = developer_of(s["name"])
        s["kind"] = kind_of(s["raw"])
        # a named developer is the strongest signal, then a mapped society site, then a bigger cluster
        s["rank"] = (0 if s["developer"] else 1, 0 if s["src"] == "res" else 1, -s["members"], s["name"])
    # a bare builder name ("Ramky") is a plot of land OSM labelled by its owner, not a named society
    societies = merge_sites([s for s in societies if norm(s["name"]) != norm(s["developer"] or "\0")])
    counts["after_nearby"] = len(societies)

    by, canon = place_layers(raw)
    for s in societies:
        s["locality"], s["locality_source"] = locality_of(s, by, canon)
    picked = sorted((s for s in societies if s["locality"]), key=lambda s: (s["locality"], s["name"]))
    rows = [record(s) for s in picked]
    validate(rows)
    return counts, rows, snapshot(raw)


def main():
    c, rows, osm_date = build()
    doc = {
        "_about": (f"Curated seed of Hyderabad housing societies. Geometry and names from OpenStreetMap (ODbL): "
                   f"{c['named']} named building=apartments and landuse=residential elements in the city bbox, "
                   f"{c['after_reject']} after dropping blocks, plots, hostels and non-residential names, "
                   f"{c['after_signal']} with positive evidence of being a society (known developer or a society "
                   f"word), {c['after_dedupe']} after clustering blocks and phases within {NEAR_M} m, "
                   f"{c['after_nearby']} after merging differently named areas on one site, {len(rows)} with a "
                   f"locality from OSM's suburb layer. A sample audit of 70 put precision near 92%, so a handful "
                   f"of neighbourhoods and staff quarters remain. Every number the seed does not know is null by "
                   f"design: prices, unit sizes, towers, units and acres are portal data that the Magicbricks "
                   f"crawl fills in later."),
        "_generated_by": "pipeline/seed_hyderabad.py",
        "_osm_snapshot": osm_date,
        "_attribution": "© OpenStreetMap contributors, ODbL",
        "societies": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"named {c['named']} -> reject {c['after_reject']} -> signal {c['after_signal']}"
          f" -> dedupe {c['after_dedupe']} -> nearby {c['after_nearby']} -> kept {len(rows)}")
    per = Counter(r["locality"] for r in rows)
    print("localities:", len(per), "| kinds:", Counter(r["kind"] for r in rows).most_common(),
          "| with a developer:", sum(1 for r in rows if r["developer"]))
    print("locality from:", Counter("addr:suburb" if "addr" in r["locality_source"] else "nearest place node"
                                    for r in rows).most_common())
    print("osm snapshot:", osm_date, "->", OUT)


if __name__ == "__main__":
    main()
