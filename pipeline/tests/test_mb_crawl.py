import gzip
import hashlib
import json
import pathlib
import threading
import time

import mb_crawl
import pytest

# padded with hex digests, not a repeated character: the cache only trusts a file over 2 KB *compressed*
NOISE = "".join(hashlib.sha1(str(i).encode()).hexdigest() for i in range(500))
REAL = "<html><body>" + mb_crawl.STATE + " = {}</body></html>" + NOISE
DENIED = "<html><title>Access Denied</title><body>You don't have permission to access this page.</body></html>"


class Resp:
    def __init__(self, html):
        self.html = html

    def read(self):
        return self.html.encode()


def serve(monkeypatch, html, tmp_path, sent=None):
    """Point the cache at tmp_path and answer every request with html."""
    monkeypatch.setattr(mb_crawl, "CACHE", tmp_path)
    monkeypatch.setattr(mb_crawl, "DELAY", 0)
    monkeypatch.setattr(mb_crawl.urllib.request, "urlopen",
                        lambda req, **kw: (sent.append(req.full_url) if sent is not None else None) or Resp(html))


def cache_file(tmp_path, url):
    return tmp_path / (hashlib.sha1(url.encode()).hexdigest() + ".html.gz")


def test_every_worker_shares_one_request_slot(monkeypatch):
    # three workers must not mean three requests a second: the gate is the whole crawl's rate limit
    monkeypatch.setattr(mb_crawl, "DELAY", 0.05)
    monkeypatch.setattr(mb_crawl, "_slot", 0.0)
    threads = [threading.Thread(target=mb_crawl.wait_turn) for _ in range(9)]
    start = time.monotonic()
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert time.monotonic() - start >= 8 * 0.05  # 9 requests cost at least 8 delays, whoever makes them


def test_a_cache_hit_takes_no_rate_slot(monkeypatch, tmp_path):
    monkeypatch.setattr(mb_crawl, "CACHE", tmp_path)
    monkeypatch.setattr(mb_crawl, "DELAY", 60)
    monkeypatch.setattr(mb_crawl.urllib.request, "urlopen",
                        lambda *a, **k: pytest.fail("asked the site for a page it already had"))
    cache_file(tmp_path, "https://x/a").write_bytes(gzip.compress(REAL.encode(), 9))
    assert mb_crawl.fetch("https://x/a") == REAL  # would sleep a minute if it asked for a slot


def test_a_block_page_is_reported_and_never_cached(monkeypatch, tmp_path):
    serve(monkeypatch, DENIED, tmp_path)
    with pytest.raises(mb_crawl.Blocked):
        mb_crawl.fetch("https://x/a")
    assert list(tmp_path.iterdir()) == []  # not cached, so a later run does not serve the block page
    assert mb_crawl.is_block(DENIED) and not mb_crawl.is_block(REAL)


def test_a_real_page_that_mentions_a_captcha_is_not_a_block(monkeypatch, tmp_path):
    page = REAL.replace("<body>", "<body>captcha widget ")
    serve(monkeypatch, page, tmp_path)
    assert mb_crawl.fetch("https://x/a") == page  # the preloaded state is what says it is a real page


def test_a_half_written_cache_file_is_refetched_instead_of_killing_the_run(monkeypatch, tmp_path):
    sent = []
    serve(monkeypatch, REAL, tmp_path, sent)
    whole = gzip.compress((NOISE * 4).encode(), 9)
    f = cache_file(tmp_path, "https://x/a")
    f.write_bytes(whole[: len(whole) // 2])  # truncated, but far over the 2 KB size test
    assert f.stat().st_size > 2000 and mb_crawl.fetch("https://x/a") == REAL
    assert sent == ["https://x/a"] and gzip.decompress(f.read_bytes()).decode() == REAL


def test_the_checkpoint_is_written_atomically(monkeypatch, tmp_path):
    f = tmp_path / "mb_projects.json"
    mb_crawl.write_atomic(f, json.dumps([{"mb_id": "1"}]))
    assert json.loads(f.read_text()) == [{"mb_id": "1"}] and list(tmp_path.glob("*.tmp")) == []

    def boom(self, data):
        raise KeyboardInterrupt  # a kill in the middle of writing the new checkpoint

    monkeypatch.setattr(pathlib.Path, "write_bytes", boom)
    with pytest.raises(KeyboardInterrupt):
        mb_crawl.write_atomic(f, json.dumps([{"mb_id": "2"}]))
    assert json.loads(f.read_text()) == [{"mb_id": "1"}]  # the previous checkpoint is still whole


def test_resume_skips_parsed_projects_and_keeps_rows_from_another_source(tmp_path):
    index = [{"url": "https://m/a"}, {"url": "https://m/b"}]
    seed = {"url": "https://www.openstreetmap.org/way/1", "mb_id": "seed-abc", "name": "My Home Bhooja"}
    rows = [{"url": "https://m/a", "name": "A", "lat": 17.4}, {"url": "https://m/b", "name": "B"}, seed]
    f = tmp_path / "mb_projects.json"
    f.write_text(json.dumps(rows))

    done, foreign = mb_crawl.resume(f, index)
    assert list(done) == ["https://m/a"]  # b has no lat, so its page was never parsed: fetch it again
    assert foreign == [seed]  # a seeded society survives a crawl restart instead of being clobbered

    mb_crawl.save(f, index, done, foreign)
    out = json.loads(f.read_text())
    assert [r["url"] for r in out] == ["https://m/a", seed["url"]]  # index order, foreign rows last


def test_resume_from_a_truncated_checkpoint_starts_over_instead_of_crashing(tmp_path):
    f = tmp_path / "mb_projects.json"
    f.write_text("")  # the 0-byte file the old non-atomic write could leave behind
    assert mb_crawl.resume(f, [{"url": "https://m/a"}]) == ({}, [])


def test_a_pincode_sits_at_the_median_of_the_pages_already_read():
    rows = [{"pincode": "500081", "lng": 78.30, "lat": 17.40},
            {"pincode": "500081", "lng": 78.38, "lat": 17.45},  # the middle one, and the answer
            {"pincode": "500081", "lng": 78.90, "lat": 17.90},  # an outlier a mean would chase
            {"pincode": "500084", "lng": 78.30, "lat": 17.50},
            {"pincode": "500084", "lng": 78.31, "lat": 17.51},  # two pages is too thin to place a pincode
            {"pincode": None, "lng": 78.30, "lat": 17.50},
            {"pincode": "500072", "lat": None, "lng": None}]  # a page whose coordinates never parsed
    assert mb_crawl.place_by_pincode({str(i): r for i, r in enumerate(rows)}) == {"500081": (78.38, 17.45)}


def read_pages(n, step=0.025):
    """n pincodes due north of (78, 17) at ~2.8 km spacing, three already-read projects on each."""
    return {f"https://m/read/{i}/{j}": {"pincode": f"5000{i:02d}", "lng": 78.0, "lat": 17.0 + i * step}
            for i in range(n) for j in range(3)}


def test_the_priority_area_is_read_first_and_nothing_is_dropped(capsys):
    done = read_pages(25)  # pincodes 0.0, 2.8, 5.6, 8.3, 11.1 ... km from the centre, so four are inside
    todo = [{"url": f"https://m/todo/{i}", "pincode": f"5000{i:02d}"} for i in reversed(range(25))]
    todo += [{"url": "https://m/todo/nowhere", "pincode": "999999"},  # a pincode no read page placed
             {"url": "https://m/todo/blank"}]  # a card the portal gave no pincode at all
    out = mb_crawl.prioritise(todo, done, {"name": "Test City", "center": [78.0, 17.0], "km": 10})

    assert sorted(p["url"] for p in out) == sorted(p["url"] for p in todo)  # a permutation: nothing dropped
    assert [p["url"] for p in out[:4]] == [f"https://m/todo/{i}" for i in range(4)]  # the area, nearest first
    assert [p["url"] for p in out[4:25]] == [f"https://m/todo/{i}" for i in range(4, 25)]  # then the rest, same way
    assert [p["url"] for p in out[25:]] == ["https://m/todo/nowhere", "https://m/todo/blank"]  # last, not never
    assert "4 of 27 unread projects are within 10 km of Test City" in capsys.readouterr().out


def test_a_crawl_with_nothing_placed_yet_keeps_the_index_order():
    pri = {"name": "Test City", "center": [78.0, 17.0], "km": 10}
    todo = [{"url": "https://m/a", "pincode": "500081"}, {"url": "https://m/b", "pincode": "500084"}]
    assert mb_crawl.prioritise(todo, read_pages(25), None) is todo  # a city that named no priority area
    # a fresh crawl has read no project page, so it has no idea where anything is: do not pretend otherwise
    assert mb_crawl.prioritise(todo, {}, pri) is todo
    assert mb_crawl.prioritise(todo, read_pages(19), pri) is todo  # 19 placed pincodes is still too few
