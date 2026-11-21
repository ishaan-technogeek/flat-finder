import json

import osm_fetch


def test_a_cached_tile_is_not_reused_for_a_different_rectangle(tmp_path, monkeypatch):
    # "buildings-03" is the fourth tile of an n x n split: retune the bbox or the tile count and the same
    # name means a different rectangle, which the cache would answer with the old rectangle's buildings
    monkeypatch.setattr(osm_fetch, "CACHE", tmp_path)
    q1 = 'way["building"](17.2,78.2,17.3,78.3);out geom;'
    (tmp_path / "buildings-03.json").write_text(json.dumps({"elements": [1]}))
    assert osm_fetch.cached(q1, "buildings-03") == {"elements": [1]}  # no query recorded yet: trusted once
    assert (tmp_path / "buildings-03.query").read_text() == q1        # ... and labelled, so now it is known
    assert osm_fetch.cached(q1, "buildings-03") == {"elements": [1]}
    assert osm_fetch.cached('way["building"](17.3,78.3,17.4,78.4);out geom;', "buildings-03") is None
    assert osm_fetch.cached(q1, "buildings-04") is None               # nothing cached under that name at all


def test_tile_bboxes_is_a_noop_for_one_tile():
    # untiled cities must keep querying their exact bbox, so their cached response is still reused
    assert osm_fetch.tile_bboxes((28.33, 76.88, 28.55, 77.16), 1) == [(28.33, 76.88, 28.55, 77.16)]


def test_tile_bboxes_covers_the_bbox_without_gaps_or_overlap():
    s, w, n, e = 17.20, 78.20, 17.65, 78.70
    tiles = osm_fetch.tile_bboxes((s, w, n, e), 4)
    assert len(tiles) == 16
    assert (round(tiles[0][0], 6), round(tiles[0][1], 6)) == (s, w)
    assert (round(tiles[-1][2], 6), round(tiles[-1][3], 6)) == (n, e)
    # rows tile north, columns tile east: a tile's far edge is exactly where its neighbour starts
    for i in range(4):
        row = tiles[i * 4:(i + 1) * 4]
        for a, b in zip(row, row[1:]):
            assert round(a[3], 6) == round(b[1], 6)
        if i < 3:
            assert round(row[0][2], 6) == round(tiles[(i + 1) * 4][0], 6)
    area = sum((t[2] - t[0]) * (t[3] - t[1]) for t in tiles)
    assert round(area, 9) == round((n - s) * (e - w), 9)


def test_backoff_waits_longer_each_pass_over_the_mirrors():
    m = len(osm_fetch.MIRRORS)
    # within one pass, move to the next mirror quickly: it may be free while this one is at capacity
    assert osm_fetch.backoff(0) == osm_fetch.backoff(m - 1) == 10
    assert osm_fetch.backoff(m) == 20
    assert osm_fetch.backoff(3 * m) == 80
    assert osm_fetch.backoff(99 * m) == 300  # capped, so a 16 tile fetch still terminates
