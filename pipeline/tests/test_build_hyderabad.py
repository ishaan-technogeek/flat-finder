import json
import pathlib

import build_city
import build_hyderabad
import mb_parse
import pricing

# the six keys the seed contract guarantees; everything else can be missing entirely
MIN = {"name": "My Home Bhooja", "locality": "Gachibowli", "lat": 17.4295, "lng": 78.3526,
       "coord_source": "osm:way/123456789", "kind": "apartment"}
HYDERABAD = {"bbox": [17.20, 78.20, 17.65, 78.70]}
FIXTURES = pathlib.Path(__file__).parent / "fixtures"
# Every key the crawl puts on a project, read off the parser that writes them rather than copied out of it:
# a hand-listed set stops being a promise about the shape the moment mb_parse grows a field.
CARD_KEYS = set(mb_parse.card_to_project({"pdpUrl": "propertyDetails/x"}))
DETAIL_KEYS = set(mb_parse.parse_project_page((FIXTURES / "mb_project_flat.html").read_text()))
# the portal's own measurements of a project, which a seeded society has no source for and leaves out
PORTAL_ONLY = {"rating", "locality_rating", "review_count", "reviews", "psf_now", "trend",
               "sale_count", "rent_count", "rera_id", "config_text"}


def soc(**kw):
    return {**MIN, **kw}


def crawled(name, lat, lng):
    return {"mb_id": "5023849", "name": name, "lat": lat, "lng": lng, "url": "https://www.magicbricks.com/x"}


def test_minimal_seed_record_has_the_whole_portal_shape():
    r = build_hyderabad.to_project(soc())
    # build_city reads one record shape for both cities, so every field the crawler fills has to be here
    assert sorted(CARD_KEYS - set(r)) == []
    assert sorted(DETAIL_KEYS - set(r) - PORTAL_ONLY) == []
    assert sorted(set(r) - CARD_KEYS - DETAIL_KEYS) == []  # and nothing invented that build_city will not read
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
    # no made-up portal numbers: every rating, trend, count and rate the crawl measures is simply absent
    assert sorted(PORTAL_ONLY & set(r)) == []


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
    assert r["mb_id"] != build_hyderabad.to_project(soc(coord_source="osm:way/987654321"))["mb_id"]
    # a real psmid is a 7 digit string ("5023849"), so a marked, non-numeric id can never shadow one
    assert r["mb_id"].startswith(build_hyderabad.ID_MARK) and not r["mb_id"].isdigit()


def test_mb_id_follows_the_osm_object_not_the_name_or_the_coordinates():
    # the id is the permalink the web app opens, and the seed is regenerated from OSM on every run: a
    # re-traced outline moves the centroid and a corrected OSM name changes the name, neither of which is
    # a different society. All 626 rows have an osm: way or relation, so this is the usual path.
    a = build_hyderabad.to_project(soc())
    for moved in (soc(lat=17.429512, lng=78.352603), soc(lat=17.5000), soc(name="My Homes Bhooja")):
        assert build_hyderabad.to_project(moved)["mb_id"] == a["mb_id"]
    # a row placed by hand has no OSM object to key on, so it falls back to its name and 11 m of position
    hand = soc(coord_source="hand-placed")
    assert build_hyderabad.to_project(hand)["mb_id"] == build_hyderabad.to_project(soc(
        coord_source="hand-placed", lat=17.429512))["mb_id"]
    assert build_hyderabad.to_project(hand)["mb_id"] != build_hyderabad.to_project(soc(
        coord_source="hand-placed", name="Lanco Hills"))["mb_id"]


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
    assert out == have and c == {"kept": 1, "merged": 1, "added": 0, "relabelled": 0}


def test_seed_society_missing_from_the_crawl_is_added():
    have = [crawled("Lanco Hills", 17.3900, 78.3800)]
    out, c = build_hyderabad.merge_crawled(have, [build_hyderabad.to_project(soc())])
    assert [p["name"] for p in out] == ["Lanco Hills", "My Home Bhooja"]
    assert c == {"kept": 1, "merged": 0, "added": 1, "relabelled": 0}
    assert out[0] is have[0]  # crawled first, so dedupe downstream keeps the crawled copy


def test_a_plural_the_portal_spells_differently_is_still_the_same_society():
    # the real case: OSM named it "My Home Navadweepa", Magicbricks "My Homes Navadweepa", 0 m apart. GENERIC
    # drops "homes" and keeps "home", so a strict token set would map this society twice, once without prices.
    have = [crawled("My Homes Navadweepa", 17.4297, 78.3528)]
    out, c = build_hyderabad.merge_crawled(have, [build_hyderabad.to_project(soc(name="My Home Navadweepa"))])
    assert out == have and c == {"kept": 1, "merged": 1, "added": 0, "relabelled": 0}
    # a plural is not a licence to merge on its own: the 400 m test still decides
    far = crawled("My Homes Navadweepa", 17.4297 + 0.045, 78.3528)
    assert not build_hyderabad.same_society(far, build_hyderabad.to_project(soc(name="My Home Navadweepa")))
    assert build_hyderabad.words("My Homes Navadweepa") == build_hyderabad.words("My Home Navadweepa")
    assert build_hyderabad.words("Lanco Hills") != build_hyderabad.words("Lanco Hill View")


def test_a_developer_name_is_not_generic_however_many_societies_carry_it():
    # "My Home" is a developer, not a word to throw away: 12 seeded societies are theirs. Dropping the generic
    # words from a plural-blind key erased it, and left every one of them matching any society of the same name.
    nc = crawled("NC Vihanga", 17.4295, 78.3526)  # same point, a different builder's society
    assert not build_hyderabad.same_society(nc, build_hyderabad.to_project(soc(name="My Home Vihanga")))
    jewel = crawled("Jewel Residency", 17.4295, 78.3526)
    assert not build_hyderabad.same_society(jewel, build_hyderabad.to_project(soc(name="My Home Jewels")))
    # ... while the two societies that really do share a name and a place still merge
    assert build_hyderabad.same_society(crawled("My Home Vihanga", 17.4296, 78.3527),
                                        build_hyderabad.to_project(soc(name="My Home Vihanga")))


def test_a_name_of_nothing_but_generic_words_is_matched_on_its_letters():
    # tokens() leaves "R K Towers" with nothing: "towers" is generic and the initials are too short. The seed
    # spells it "R K Towers" and the portal "RK Towers", so an exact-string fallback maps the society twice.
    rk = crawled("RK Towers", 17.4295, 78.3526)
    assert build_city.tokens("R K Towers") == set() and build_city.tokens("RK Towers") == set()
    assert build_hyderabad.same_society(rk, build_hyderabad.to_project(soc(name="R K Towers")))
    # spacing is all that may differ: a different society of generic words must not be absorbed
    kk = crawled("KK Towers", 17.4295, 78.3526)
    assert not build_hyderabad.same_society(kk, build_hyderabad.to_project(soc(name="R K Towers")))


def test_a_society_listed_under_its_builders_brand_is_one_society():
    # the portal lists the project under the brand and OSM under the name on the gate: "Aditya Eden Park"
    # and "Eden Park" are one society, 10 of the 626 seeded rows arrived twice this way
    eden = crawled("Eden Park", 17.4295, 78.3526)
    eden["developer"] = "Aditya Constructions"
    assert build_hyderabad.same_society(eden, build_hyderabad.to_project(soc(name="Aditya Eden Park")))
    # ... but a subset of the words is not enough on its own. These two are 1 m apart and not the same
    # society; nothing calls "Arvind Avenue" a developer, so the extra words are part of the name.
    arvind = crawled("Janapriya Arvind Avenue", 17.4295, 78.3526)
    assert not build_hyderabad.same_society(arvind, build_hyderabad.to_project(soc(name="Janapriya Apartments")))
    # and a developer field that only repeats the name is no evidence of anything
    hill = crawled("Gooncha Hill", 17.4295, 78.3526)
    hill["developer"] = "Villa Gooncha Hill"
    assert not build_hyderabad.same_society(hill, build_hyderabad.to_project(soc(name="Vasavi Gooncha Hill")))


def test_two_buildings_on_one_site_are_not_merged_into_one():
    # same rule as build_city.dedupe, for the same reason: the seed row is dropped on a merge, so calling
    # the towers and the apartments one society takes a real building off the map
    tow = crawled("Meenakshi Towers", 17.4295, 78.3526)
    assert not build_hyderabad.same_society(tow, build_hyderabad.to_project(soc(name="Meenakshi Apartment")))
    # a form the other name merely leaves out is still the same society, though
    greens = crawled("Cascade Greens", 17.4295, 78.3526)
    assert build_hyderabad.same_society(greens, build_hyderabad.to_project(soc(name="Cascade Green Apartments")))


def test_spacing_is_compared_even_when_the_name_has_tokens_left():
    # the letters rule used to apply only to names made of nothing but generic words. "Hardhik Anmol
    # Apartments" and "Anmol Apartments" both leave tokens, so the token rule compared them and said no.
    anmol = crawled("Jaya Lakshmi Apartments", 17.4295, 78.3526)
    assert build_city.tokens("Jayalakshmi Apartments") != build_city.tokens("Jaya Lakshmi Apartments")
    assert build_hyderabad.same_society(anmol, build_hyderabad.to_project(soc(name="Jayalakshmi Apartments")))


def test_the_same_words_in_another_order_are_another_society():
    # "Villa Greens" and "Green Villas" are two Kollur projects 300 m apart, and as word sets they are one
    assert build_hyderabad.words("Villa Greens") != build_hyderabad.words("Green Villas")
    assert build_hyderabad.words("My Homes Navadweepa") == ("my", "home", "navadweepa")
    vg = crawled("Green Villas", 17.4295, 78.3526)
    assert not build_hyderabad.same_society(vg, build_hyderabad.to_project(soc(name="Villa Greens", kind="villa")))


def test_a_seeded_society_takes_its_neighbourhoods_name_from_the_crawl():
    # the seed reads its locality off the nearest OSM place node, kilometres away in the suburbs: it says
    # "Narsingi" for Kokapet. Judged against the majority label within 1 km, the crawl wins 248 rows to 7.
    have = [crawled("Vertex Panache", 17.4100, 78.3300), crawled("Aparna Sarovar", 17.4101, 78.3301),
            crawled("Rajapushpa Atria", 17.4102, 78.3302)]
    for p, loc in zip(have, ("Kokapet", "Kokapet", "Gandipet")):
        p["locality"] = loc
    s = build_hyderabad.to_project(soc(name="Lanco Hills", lat=17.4103, lng=78.3303))
    out, c = build_hyderabad.merge_crawled(have, [s])
    assert c["relabelled"] == 1 and s["locality"] == "Kokapet"
    assert s["locality_source"] == "the label on 2 of 3 crawled projects within 500 m"
    # one stray label must not decide it: the project 54 m from a society in Alwal says Kompally, and 66
    # of the 67 around it say Alwal
    assert out[0]["locality"] == "Kokapet"  # the crawled rows keep their own, whatever the vote said


def test_a_seeded_society_with_no_crawled_neighbour_keeps_its_own_locality():
    far = [crawled("Aparna Sarovar", 17.5000, 78.5000)]
    far[0]["locality"] = "Nallagandla"
    s = build_hyderabad.to_project(soc())
    out, c = build_hyderabad.merge_crawled(far, [s])
    assert c["relabelled"] == 0 and s["locality"] == "Gachibowli" and "locality_source" not in s


def test_same_name_five_km_away_is_a_different_society():
    far = crawled("My Home Bhooja", 17.4295 + 0.045, 78.3526)  # ~5 km north
    out, c = build_hyderabad.merge_crawled([far], [build_hyderabad.to_project(soc())])
    assert len(out) == 2 and c == {"kept": 1, "merged": 0, "added": 1, "relabelled": 0}


def test_rows_written_by_an_earlier_seed_run_are_rebuilt():
    old = build_hyderabad.to_project(soc(developer="Stale Builders"))
    new = build_hyderabad.to_project(soc(developer="My Home Constructions"))
    out, c = build_hyderabad.merge_crawled([old], [new])
    assert c == {"kept": 0, "merged": 0, "added": 1, "relabelled": 0} and out[0]["developer"] == "My Home Constructions"


def test_merge_without_a_crawl_keeps_every_seed_society():
    seeded = [build_hyderabad.to_project(soc()), build_hyderabad.to_project(soc(name="Lanco Hills"))]
    out, c = build_hyderabad.merge_crawled([], seeded)
    assert out == seeded and c == {"kept": 0, "merged": 0, "added": 2, "relabelled": 0}


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
