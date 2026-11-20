import json

import build_city
import build_hyderabad
import pricing

# the six keys the seed contract guarantees; everything else can be missing entirely
MIN = {"name": "My Home Bhooja", "locality": "Gachibowli", "lat": 17.4295, "lng": 78.3526,
       "coord_source": "osm:way/123456789", "kind": "apartment"}
# every key the crawl puts on all 2,708 Gurugram records, so build_city reads one shape for both cities
PORTAL_KEYS = ["mb_id", "name", "developer", "locality", "pincode", "status", "possession", "units", "towers",
               "acres", "price_min", "price_max", "prop_types", "brochure_url", "card_units", "images",
               "type_codes", "url", "lat", "lng", "configs", "rating_count", "ratings", "description"]
HYDERABAD = {"bbox": [17.20, 78.20, 17.65, 78.70]}


def soc(**kw):
    return {**MIN, **kw}


def crawled(name, lat, lng):
    return {"mb_id": "5023849", "name": name, "lat": lat, "lng": lng, "url": "https://www.magicbricks.com/x"}


def test_minimal_seed_record_has_the_whole_portal_shape():
    r = build_hyderabad.to_project(soc())
    assert [k for k in PORTAL_KEYS if k not in r] == []
    assert r["name"] == "My Home Bhooja" and r["locality"] == "Gachibowli"
    assert build_city.in_city(r, HYDERABAD)
    assert build_city.portal_units(r) == []  # the seed has no unit sizes, and that is not a crash
    assert pricing.listing_stats(r) == {}  # empty sale/rent listings
    assert json.loads(json.dumps(r)) == r  # the record is plain JSON, nothing clever


def test_unknown_numbers_stay_null_and_are_never_estimated():
    r = build_hyderabad.to_project(soc())
    assert all(r[k] is None for k in ("price_min", "price_max", "towers", "units", "acres", "pincode",
                                      "status", "possession", "rating_count", "description", "brochure_url"))
    assert r["ratings"] == {} and r["images"] == [] and r["amenities"] == []
    assert "psf_now" not in r and "trend" not in r and "rating" not in r  # no made-up portal numbers


def test_seed_fields_are_passed_through_when_present():
    r = build_hyderabad.to_project(soc(developer="My Home Constructions", towers=11, units=1900, acres=9.5,
                                       pincode="500032", status="Ready To Move", possession="2021",
                                       amenities=["Club House", "Swimming Pool"]))
    assert r["developer"] == "My Home Constructions" and r["towers"] == 11 and r["units"] == 1900
    assert r["acres"] == 9.5 and r["pincode"] == "500032" and r["status"] == "Ready To Move"
    assert r["possession"] == "2021" and r["amenities"] == ["Club House", "Swimming Pool"]


def test_mb_id_is_deterministic_and_cannot_be_a_magicbricks_id():
    r = build_hyderabad.to_project(soc())
    assert r["mb_id"] == build_hyderabad.to_project(soc())["mb_id"]
    assert r["mb_id"] != build_hyderabad.to_project(soc(name="Lanco Hills"))["mb_id"]
    assert r["mb_id"] != build_hyderabad.to_project(soc(lat=17.5000))["mb_id"]  # same name, other place
    # a real psmid is a 7 digit string ("5023849"), so a marked, non-numeric id can never shadow one
    assert r["mb_id"].startswith(build_hyderabad.ID_MARK) and not r["mb_id"].isdigit()


def test_mb_id_survives_a_sub_metre_coordinate_correction():
    a = build_hyderabad.to_project(soc())
    b = build_hyderabad.to_project(soc(lat=17.429512, lng=78.352603))
    assert a["mb_id"] == b["mb_id"]  # the id is a permalink; 11 m of OSM jitter must not change it


def test_kind_round_trips_through_build_city():
    for kind in ("apartment", "villa", "plot", "builder floor"):
        r = build_hyderabad.to_project(soc(kind=kind))
        assert build_city.kind_of(r) == kind  # no trailing ~: the kind is data, not inferred from the name


def test_an_unknown_kind_falls_back_to_inference_instead_of_a_wrong_code():
    r = build_hyderabad.to_project(soc(kind="duplex"))
    assert r["type_codes"] == [] and build_city.kind_of(r) == "apartment~"


def test_unit_types_without_a_size_are_dropped_not_guessed():
    r = build_hyderabad.to_project(soc(unit_types=[{"bhk": 3, "sqft": 2150}, {"bhk": 4, "sqft": None}, {"bhk": 2}]))
    assert r["configs"]["units"] == [{"bhk": 3, "sqft": 2150.0, "kind": "10002"}]
    assert r["card_units"] == r["configs"]["units"]
    units = build_city.portal_units(r)
    assert len(units) == 1 and units[0]["label"] == "3 BHK 2,150 sq ft" and units[0]["size_sqft"] == 2150.0


def test_a_sizeless_unit_list_still_resolves_the_kind():
    r = build_hyderabad.to_project(soc(kind="villa", unit_types=[{"bhk": 4, "sqft": None}]))
    assert r["card_units"] == [] and build_city.kind_of(r) == "villa"


def test_rent_listings_reach_the_price_model():
    r = build_hyderabad.to_project(soc(rent_listings=[{"bhk": 3, "price": 55000, "sqft": 2150, "psf": 25.6},
                                                      {"bhk": 3, "price": 65000}, {"bhk": 2, "price": 30000}]))
    st = pricing.listing_stats(r)
    assert st[3]["rent"] == {"median": 60000, "min": 55000, "max": 65000, "n": 2}
    assert st[2]["rent"]["median"] == 30000 and "buy" not in st[3]


def test_sale_listings_reach_the_price_model():
    r = build_hyderabad.to_project(soc(sale_listings=[{"bhk": 3, "price": 2e7, "sqft": 2150, "psf": 9300},
                                                      {"bhk": 3, "price": 2.4e7, "sqft": 2150, "psf": 11000}]))
    st = pricing.listing_stats(r)
    assert st[3]["buy"]["median"] == 22000000 and st[3]["psf"] == 10150


def test_url_is_a_real_page_never_a_guessed_magicbricks_link():
    osm = build_hyderabad.to_project(soc())["url"]
    assert osm == "https://www.openstreetmap.org/way/123456789" and "magicbricks" not in osm
    assert build_hyderabad.to_project(soc(source="https://example.com/bhooja"))["url"] == "https://example.com/bhooja"
    assert build_hyderabad.to_project(soc(coord_source="hand-placed"))["url"] is None


def test_crawled_record_wins_over_a_nearby_seed_society():
    have = [crawled("My Home Bhooja", 17.4297, 78.3528)]  # ~30 m from the seed point
    out, c = build_hyderabad.merge_crawled(have, [build_hyderabad.to_project(soc())])
    assert out == have and c == {"kept": 1, "merged": 1, "added": 0}


def test_seed_society_missing_from_the_crawl_is_added():
    have = [crawled("Lanco Hills", 17.3900, 78.3800)]
    out, c = build_hyderabad.merge_crawled(have, [build_hyderabad.to_project(soc())])
    assert [p["name"] for p in out] == ["Lanco Hills", "My Home Bhooja"]
    assert c == {"kept": 1, "merged": 0, "added": 1}
    assert out[0] is have[0]  # crawled first, so dedupe downstream keeps the crawled copy


def test_same_name_five_km_away_is_a_different_society():
    far = crawled("My Home Bhooja", 17.4295 + 0.045, 78.3526)  # ~5 km north
    out, c = build_hyderabad.merge_crawled([far], [build_hyderabad.to_project(soc())])
    assert len(out) == 2 and c == {"kept": 1, "merged": 0, "added": 1}


def test_rows_written_by_an_earlier_seed_run_are_rebuilt():
    old = build_hyderabad.to_project(soc(developer="Stale Builders"))
    new = build_hyderabad.to_project(soc(developer="My Home Constructions"))
    out, c = build_hyderabad.merge_crawled([old], [new])
    assert c == {"kept": 0, "merged": 0, "added": 1} and out[0]["developer"] == "My Home Constructions"


def test_merge_without_a_crawl_keeps_every_seed_society():
    seeded = [build_hyderabad.to_project(soc()), build_hyderabad.to_project(soc(name="Lanco Hills"))]
    out, c = build_hyderabad.merge_crawled([], seeded)
    assert out == seeded and c == {"kept": 0, "merged": 0, "added": 2}


def test_main_writes_the_city_file_then_calls_the_shared_builder(tmp_path, monkeypatch, capsys):
    lanco = {**MIN, "name": "Lanco Hills", "lat": 17.3900, "lng": 78.3800}
    seed = tmp_path / "hyderabad.json"
    seed.write_text(json.dumps({"_generated": "2026-11-20", "societies": [MIN, lanco]}))
    monkeypatch.setattr(build_hyderabad, "SEED", seed)
    monkeypatch.setattr(build_hyderabad, "OUT", tmp_path / "out")
    built = []
    monkeypatch.setattr(build_city, "main", built.append)
    f = tmp_path / "out" / "hyderabad" / "mb_projects.json"

    build_hyderabad.main()
    assert [r["name"] for r in json.loads(f.read_text())] == ["My Home Bhooja", "Lanco Hills"]
    assert built == ["hyderabad"]

    # a real crawl landing on disk is merged into, not overwritten
    f.write_text(json.dumps([crawled("My Home Bhooja", 17.4295, 78.3526)]))
    build_hyderabad.main()
    recs = json.loads(f.read_text())
    assert [r["mb_id"] for r in recs] == ["5023849", build_hyderabad.seed_id(lanco)]
    out = capsys.readouterr().out
    assert "2 societies from the seed file" in out and "seed added 1" in out
