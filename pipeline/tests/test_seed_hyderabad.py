import pytest

import seed_hyderabad as seed


def el(name, lat, lng, kind="way", oid=1, **tags):
    return {"type": kind, "id": oid, "center": {"lat": lat, "lon": lng}, "tags": {"name": name, **tags}}


def cand(name, lat, lng, src="apt", oid=1):
    return {"raw": name, "name": seed.clean(name), "src": src, "osm": f"way/{oid}",
            "lat": lat, "lng": lng, "tags": {}}


def test_clean_strips_a_block_or_phase_however_osm_spelt_it():
    for raw in ["My Home Avatar Block - A", "My Home Avatar Block-A", "My Home Avatar A Block",
                "My Home Avatar (Phase 2)", "My Home Avatar Tower - C", "My Home Avatar Block B & C",
                "My Home Avatar Block - A, B, C &d"]:
        assert seed.clean(raw) == "My Home Avatar", raw
    # a tail at a time, so a name carrying both sheds both
    assert seed.clean("Sarovar Grande Block A Phase 2") == "Sarovar Grande"


def test_clean_keeps_a_name_that_merely_ends_in_a_word_a_tail_uses():
    # "Towers" is the society; only a separated identifier after it is one of its buildings
    assert seed.clean("Lanco Hills Signature Towers") == "Lanco Hills Signature Towers"
    assert seed.clean("Ramky Towers") == "Ramky Towers"  # became "Ramky", which the bare-developer rule dropped
    assert seed.clean("Aditya Empress Towers") == "Aditya Empress Towers"
    assert seed.clean("Aparna Sarovar Zenith") == "Aparna Sarovar Zenith"
    assert seed.clean("Ramky Towers Block 3") == "Ramky Towers"
    # singular "Tower" does designate one, so it still goes
    assert seed.clean("Rajapushpa Regalia, Tower - A") == "Rajapushpa Regalia"


def test_a_comma_written_name_is_read_from_whichever_end_it_starts_at():
    # six of Prestige High Fields' towers are mapped from the inside out, and arrived as six societies
    for raw in ["Tower 1, Daisy, Prestige High Fields", "Tower 10, Lotso, Prestige High Fields",
                "Tower 9, Russell, Prestige High Fields"]:
        assert seed.clean(raw) == "Prestige High Fields", raw
    # a name that starts with the building names the colony second, so the first segment is the society
    assert seed.clean("Gayatri Nest Apartments, Cyber Hill") == "Gayatri Nest Apartments"
    assert seed.clean("Milestone Apartments, Kallari CHS") == "Milestone Apartments"
    assert seed.clean("Sri Sai Krupa,Saptagiri Enclave") == "Sri Sai Krupa"
    assert seed.designator("Tower 1") and seed.designator("Block - A") and not seed.designator("Daisy")


def test_the_record_keeps_the_same_osm_object_when_an_outline_is_retraced():
    # the head's id is the row's provenance and the seed id hashes it, so it must not depend on where OSM
    # currently draws the buildings: this cluster used to be headed by whichever block was furthest south
    here = [cand("Aparna Cyber Life", 17.4100, 78.3800, oid=7),
            cand("Aparna Cyber Life", 17.4110, 78.3805, oid=3),
            cand("Aparna Cyber Life", 17.4105, 78.3802, oid=5)]
    assert seed.merge_blocks(here)[0]["osm"] == "way/3"
    moved = [here[1], here[0], {**here[2], "lat": 17.4095}]  # re-traced, and read back in another order
    assert seed.merge_blocks(moved)[0]["osm"] == "way/3"


def test_clean_normalises_spelling_and_case_without_shouting_initialisms():
    assert seed.clean("aparna  appartments") == "Aparna Apartments"
    assert seed.clean("Vasavi Apts") == "Vasavi Apartments"
    assert seed.clean("NCC Urban Gardenia") == "NCC Urban Gardenia"  # a real initialism stays upper
    assert seed.clean("MES OFFICERS ENCLAVE") == "MES Officers Enclave"


def test_developer_is_named_anywhere_in_the_name_not_only_at_the_front():
    assert seed.developer_of("My Home Bhooja") == "My Home"
    assert seed.developer_of("The Botanika By Sattva Group") == "Sattva"
    assert seed.developer_of("Aparna") == "Aparna"  # the bare name still resolves; main() then drops the row
    # a longer word that merely starts the same is a different name, so it gets no developer
    assert seed.developer_of("Aparnagiri Residency") is None
    assert seed.developer_of("Sri Nilayam") is None


def test_kind_reads_the_name_osm_wrote_not_the_cleaned_one():
    assert seed.kind_of("Aparna Cyber Life Villas Phase 2") == "villa"
    assert seed.kind_of("Alekhya Nestor Plots") == "plot"
    assert seed.kind_of("My Home Jewel") == "apartment"


def test_candidates_need_positive_evidence_and_survive_the_reject_list():
    raw = {"seed-apartments": {"elements": [
        el("Aparna Sarovar", 17.44, 78.34, oid=1),          # developer
        el("Sai Krupa Residency", 17.45, 78.35, oid=2),     # society word
        el("Sri Sai Mens Hostel", 17.46, 78.36, oid=3),     # rejected outright
        el("Block C", 17.47, 78.37, oid=4),                 # a block, not a society
        el("Defence Colony", 17.48, 78.38, oid=5),          # "colony" alone is not evidence
        el("Lotus Function Hall", 17.49, 78.39, oid=6),     # not residential
        {"type": "way", "id": 7, "tags": {"name": "No Centre Apartments"}},  # no coordinates
    ]}, "seed-residential": {"elements": []}}
    counts, got = seed.candidates(raw)
    assert [c["name"] for c in got] == ["Aparna Sarovar", "Sai Krupa Residency"]
    assert counts == {"named": 6, "after_reject": 3, "after_signal": 2}


def test_staff_quarters_are_not_a_society_unless_something_else_vouches_for_them():
    raw = {"seed-apartments": {"elements": [
        el("Raj Bhavan Quarters", 17.41, 78.46, oid=1),      # the Governor's estate, not a society
        el("RBI Staff Quarters", 17.44, 78.47, oid=2),       # housing an employer allots
        el("Janapriya Quarters", 17.37, 78.56, oid=3),       # a real society: the developer is the evidence
    ]}, "seed-residential": {"elements": []}}
    counts, got = seed.candidates(raw)
    assert [c["name"] for c in got] == ["Janapriya Quarters"]
    assert counts["after_signal"] == 1


def test_merge_blocks_joins_one_society_and_prefers_its_mapped_site():
    blocks = [cand("Lanco Hills Apartments", 17.4100, 78.3800, oid=1),
              cand("Lanco Hills Apartments", 17.4120, 78.3805, src="res", oid=2),  # ~220 m away
              cand("Lanco Hills Apartments", 17.5000, 78.5000, oid=3)]             # a different Lanco Hills
    out = sorted(seed.merge_blocks(blocks), key=lambda s: -s["members"])
    assert [s["members"] for s in out] == [2, 1]
    assert out[0]["osm"] == "way/2"  # the landuse=residential area is the society site, not one building
    assert out[0]["lat"] == pytest.approx(17.411, abs=1e-4)  # the pin sits between the parts


def test_merge_sites_keeps_one_pin_when_osm_names_the_parts_differently():
    a = {"name": "Janapriya Metropolis Apartments And Classic Homes", "lat": 17.4802, "lng": 78.3910,
         "rank": (0, 0, -3, "a")}
    b = {"name": "Janapriya Classic Apartments", "lat": 17.4806, "lng": 78.3912, "rank": (0, 1, -1, "b")}
    far = {"name": "Aparna Sarovar", "lat": 17.44, "lng": 78.34, "rank": (0, 0, -1, "c")}
    assert seed.dist_m((a["lat"], a["lng"]), (b["lat"], b["lng"])) < seed.SAME_SITE_M
    kept = [s["name"] for s in seed.merge_sites([b, a, far])]
    assert kept == ["Janapriya Metropolis Apartments And Classic Homes", "Aparna Sarovar"]


def test_locality_prefers_the_suburb_a_renter_searches_over_the_colony_next_door():
    raw = {"seed-places": {"elements": [
        el("Gachibowli", 17.4400, 78.3480, kind="node", oid=10, place="suburb"),
        el("Masjid Banda", 17.4640, 78.3600, kind="node", oid=11, place="neighbourhood"),
        el("Kismatpur", 17.3450, 78.3720, kind="node", oid=12, place="neighbourhood"),
        el("Hyderabad", 17.3850, 78.4867, kind="node", oid=13, place="city"),
    ]}}
    by, canon = seed.place_layers(raw)
    # the distance is part of the provenance: a suburb node 5 km away is a guess at the neighbourhood
    assert seed.locality_of({"lat": 17.4420, "lng": 78.3500, "tags": {}}, by, canon) == \
        ("Gachibowli", "osm:nearest-node/10 at 308 m")
    # a colony 3 km from the suburb loses to it: a renter searches Gachibowli, not Masjid Banda
    assert seed.locality_of({"lat": 17.4645, "lng": 78.3605, "tags": {}}, by, canon)[0] == "Gachibowli"
    # but beyond every suburb's 5 km radius a mapped colony is better than nothing
    assert seed.locality_of({"lat": 17.3455, "lng": 78.3725, "tags": {}}, by, canon)[0] == "Kismatpur"
    # the city is not a locality: a society with no place node nearby stays unlocated and is dropped
    assert seed.locality_of({"lat": 17.64, "lng": 78.69, "tags": {}}, by, canon) == (None, None)


def test_locality_from_the_society_tags_only_when_osm_maps_that_place_too():
    raw = {"seed-places": {"elements": [el("Gachibowli", 17.44, 78.348, kind="node", oid=10, place="suburb")]}}
    by, canon = seed.place_layers(raw)
    tagged = {"lat": 17.50, "lng": 78.40, "tags": {"addr:suburb": "gachibowli"}}
    assert seed.locality_of(tagged, by, canon) == ("Gachibowli", "osm:addr:suburb")  # canonical spelling wins
    # an addr:suburb naming a place OSM does not map would add a near-duplicate to the filter, so it is ignored
    invented = {"lat": 17.4402, "lng": 78.3482, "tags": {"addr:suburb": "Lingampally X Roads"}}
    assert seed.locality_of(invented, by, canon) == ("Gachibowli", "osm:nearest-node/10 at 31 m")


def test_validate_refuses_a_row_that_claims_a_number_it_has_no_source_for():
    row = seed.record({"name": "Aparna Sarovar", "developer": "Aparna", "locality": "Gachibowli",
                       "locality_source": "osm:nearest-node/10", "lat": 17.44, "lng": 78.348,
                       "osm": "way/1", "kind": "apartment", "tags": {}})
    seed.validate([row])
    with pytest.raises(AssertionError, match="claims towers"):
        seed.validate([{**row, "towers": 4}])
    with pytest.raises(AssertionError, match="outside the city"):
        seed.validate([{**row, "lat": 28.4027, "lng": 77.0891}])  # a Gurgaon coordinate in the Hyderabad seed
    with pytest.raises(AssertionError, match="missing provenance"):
        seed.validate([{**row, "locality": None}])
    with pytest.raises(SystemExit):
        seed.validate([])


def test_snapshot_reports_the_oldest_extract_so_the_claim_holds_for_every_input():
    raw = {"a": {"osm3s": {"timestamp_osm_base": "2026-11-20T14:47:51Z"}},
           "b": {"osm3s": {"timestamp_osm_base": "2026-11-20T14:40:39Z"}},
           "c": {}}
    assert seed.snapshot(raw) == "2026-11-20T14:40:39Z"
    assert seed.snapshot({"a": {}}) is None
