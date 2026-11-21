"""Polite, cached, resumable Magicbricks crawler.

usage: python mb_crawl.py list <city>      # all list pages -> out/<city>/mb_index.json
       python mb_crawl.py projects <city>  # every project page -> out/<city>/mb_projects.json
<city> is a key in data/cities.json (default gurgaon).
"""
import collections
import gzip
import hashlib
import json
import pathlib
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request

import geo
import mb_parse

ROOT = pathlib.Path(__file__).parent
CACHE = ROOT / "cache" / "mb"
OUT = ROOT / "out"
CITIES = json.loads((ROOT.parent / "data" / "cities.json").read_text())
CITY = next((a for a in sys.argv[1:] if a in CITIES), "gurgaon")
CFG = CITIES[CITY]
LIST_URL = "https://www.magicbricks.com/residential-projects-in-" + CFG["magicbricks"] + "-nprid/page-{}"
OUT = OUT / CITY
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
DELAY = 1.0  # seconds between requests for the whole crawl, not for each worker
WORKERS = 3  # overlapping fetches; the gate below sets the request rate, this only hides latency
EVERY = 500  # projects between checkpoints: a city the size of Hyderabad rewrites ~140 MB each time
# A block or captcha page answers 200 and looks like any other page, so only the body gives it away.
# The last nine are the challenge and block pages the big CDNs put in front of a site -- Cloudflare's
# interstitial and its "Attention Required", AWS WAF's and Akamai's block pages -- any of which could
# appear between this crawler and the portal without the portal changing anything.
BLOCK = ("access denied", "captcha", "unusual traffic", "request unsuccessful", "verify you are a human",
         "attention required", "checking your browser", "just a moment", "enable javascript and cookies",
         "ddos protection", "request blocked", "too many requests", "are you a robot", "bot detection")
STATE = "window.SERVER_PRELOADED_STATE_"  # every real list and project page carries it
REFUSED = (403, 429)  # the site saying no, not a hiccup: stop the run instead of retrying around it
MISSING = (404, 410)  # this page is not there; nothing to wait for, so do not spend three attempts on it

_gate = threading.Lock()
_slot = 0.0  # monotonic time the next request may leave
_say = threading.Lock()
stop = threading.Event()  # set when the site blocks us, so the other workers stop asking


class Blocked(Exception):
    """The site refused us. Report it and stop: never retry around it, never cache it."""


class Gone(Exception):
    """This page is a 404 or a 410. Not a refusal and not a hiccup: there is nothing there to wait for."""


def say(msg):
    """One line at a time. Three workers print mid-fetch, and print() writes the text and the newline
    separately, so their messages spliced into each other: "  retry 1 http  blocked: http...".
    """
    with _say:
        print(msg, flush=True)


def wait_turn():
    """Hand out one request slot per DELAY seconds, shared by every worker.

    The sleep used to sit after each fetch inside the worker, so three threads meant three requests a
    second (1.7/s measured, the rest of the budget eaten by fetch latency) against a docstring that
    promises one. Reserving the slot under the lock and sleeping outside it keeps fetches overlapping.
    """
    global _slot
    with _gate:
        now = time.monotonic()
        _slot = max(now, _slot) + DELAY
        wait = _slot - DELAY - now
    time.sleep(max(0.0, wait))


def read_cache(f):
    """The cached page, or None when the file cannot be read.

    A half-written cache file is bigger than the size test but fails to decompress, and that used to
    raise out of the worker and kill a run with hours of work behind it. Drop it and fetch it again.
    """
    try:
        return gzip.decompress(f.read_bytes()).decode("utf-8", "ignore")
    except Exception as e:
        say(f"  unreadable cache file, refetching: {f.name} {e}")
        f.unlink(missing_ok=True)
        return None


def is_block(html):
    """True when the site served a block or captcha page instead of the thing we asked for.

    These answer 200, so no status code reveals them. Caching one would poison the cache for good (a
    real block page clears the 2 KB size test) and parse to all-nulls merged into a record that looks
    exactly like a real project whose page happened to be thin.
    """
    return STATE not in html and any(s in html[:4000].lower() for s in BLOCK)


def write_atomic(f, data):
    """Write beside the file and rename, so a kill mid-write cannot leave a truncated file behind.

    mb_projects.json is read by the build with a bare json.loads, and serialising ~140 MB leaves a
    window long enough to catch: polling the old write_text caught the file at 0 bytes.
    """
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_bytes(data if isinstance(data, bytes) else data.encode())
    tmp.replace(f)


def fetch(url):
    """The page, from the cache or the site, or None when three attempts could not get one.

    Only a page that proves it is a page is cached. An answer with no preloaded state on it is not a
    block page we recognise and not a real one either -- an interstitial, an empty shell, a redirect to
    a holding page -- and caching it would freeze this project at all-nulls for as long as the cache
    lives, looking exactly like a real project whose page happened to be thin. If the portal ever
    renames the state variable this stalls the crawl and says so on every page, which is the right way
    round: loud and with nothing poisoned.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".html.gz")
    if f.exists() and f.stat().st_size > 2000:
        html = read_cache(f)
        if html is not None:
            return html  # a cache hit sends no request, so it takes no rate slot
    for attempt in range(3):
        try:
            wait_turn()
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            html = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "ignore")
            if is_block(html):
                raise Blocked(url)
            if STATE not in html:
                say(f"  no page state in {len(html)} bytes, not caching: {url}")
                time.sleep(5 * (attempt + 1))
                continue
            write_atomic(f, gzip.compress(html.encode("utf-8"), 9))
            return html
        except Blocked:
            raise
        except urllib.error.HTTPError as e:
            if e.code in REFUSED:
                raise Blocked(f"{url} ({e.code} {e.reason})") from None
            if e.code in MISSING:
                raise Gone(f"{url} ({e.code} {e.reason})") from None
            say(f"  retry {attempt + 1} {url} {e}")  # 5xx and the rest: a hiccup, back off and retry
            time.sleep(5 * (attempt + 1))
        except Exception as e:  # network hiccup: back off and retry
            say(f"  retry {attempt + 1} {url} {e}")
            time.sleep(5 * (attempt + 1))
    return None


def crawl_list():
    first = fetch(LIST_URL.format(1))
    total = mb_parse.parse_total(first)
    pages = -(-total // 20)
    projects = {}
    for n in range(1, pages + 1):
        try:
            html = fetch(LIST_URL.format(n))
        except Gone:
            # pages are sequential, so past the last one they are all gone: the total over-counted
            say(f"  list page {n} is gone, so the site has fewer than the {pages} pages it reported")
            break
        if not html:
            continue
        for c in mb_parse.parse_list_page(html):
            projects[c["psmid"]] = mb_parse.card_to_project(c)
        say(f"list {n}/{pages}: {len(projects)} projects")
    OUT.mkdir(parents=True, exist_ok=True)
    write_atomic(OUT / "mb_index.json", json.dumps(list(projects.values()), indent=0))
    say(f"total reported {total} collected {len(projects)}")


def resume(f, index):
    """(projects an earlier run already parsed, keyed by url) and (rows this crawler did not write).

    The page cache means a restart costs no requests, but re-parsing a whole city costs half an hour,
    so a record that already carries a detail-page field is kept as it is. Rows whose url is not in
    the index belong to someone else -- build_hyderabad.py seeds this same file -- and are written
    back untouched: the crawl must not delete a society it did not create.
    """
    if not f.exists():
        return {}, []
    try:
        rows = json.loads(f.read_text())
    except Exception as e:
        say(f"  unreadable checkpoint, parsing again from the page cache: {e}")
        return {}, []
    urls = {p["url"] for p in index}
    # lat is read off the project page and is never on an index card, so it marks a parsed record
    return ({r["url"]: r for r in rows if r.get("url") in urls and r.get("lat")},
            [r for r in rows if r.get("url") not in urls])


def place_by_pincode(done, least=3):
    """Where each pincode sits, from the project pages this crawl has already read.

    An index card carries a name, a locality and a pincode but no coordinates -- those are only on the
    project page -- so the queue cannot be ordered by distance until something has been read. The pages
    already in hand give it: the median position of the projects sharing a pincode. Hyderabad's first
    9,986 pages placed 144 pincodes and 28,021 of its 28,101 cards, with half the projects inside 760 m
    of their pincode's median and nine in ten inside 3.9 km. Coarse, so the smaller the radius the fuzzier
    its edge -- but the queue is ordered by distance throughout, so a misplaced project is read a little
    early or a little late, never skipped.
    """
    at = collections.defaultdict(list)
    for r in done.values():
        if r.get("pincode") and r.get("lat") is not None and r.get("lng") is not None:
            at[r["pincode"]].append((r["lng"], r["lat"]))
    return {k: (statistics.median(x for x, _ in v), statistics.median(y for _, y in v))
            for k, v in at.items() if len(v) >= least}


def prioritise(todo, done, pri):
    """todo reordered so a city's priority area is read first. Nothing is dropped, only moved later.

    A city names its area in data/cities.json: "priority": {"name": "HITEC City", "center": [lng, lat],
    "km": 5}. Inside that radius, nearest first; then everything else, also nearest first, so the
    boundary is a priority line and not a cliff; then the few cards no pincode could place. The output
    file stays in index order either way -- save() writes it that way -- so this changes when a project
    is read and nothing about what the build then makes of it.

    A crawl with nothing read yet has nothing to sort by and keeps the index order; stop it and start it
    again once a few hundred pages are in and the priority takes effect.
    """
    if not pri:
        return todo
    at = place_by_pincode(done)
    if len(at) < 20:
        say(f"  only {len(at)} pincodes placed so far: keeping index order")
        return todo
    center = tuple(pri["center"])

    def rank(p):
        here = at.get(p.get("pincode"))
        if here is None:
            return (2, 0.0)  # unplaceable: read last, but still read
        km = geo.dist_m(center, here) / 1000
        return (0 if km <= pri["km"] else 1, km)

    ranked = sorted(((rank(p), p) for p in todo), key=lambda t: t[0])
    inside = sum(1 for r, _ in ranked if r[0] == 0)
    say(f"  {inside} of {len(ranked)} unread projects are within {pri['km']} km of {pri['name']}: those "
        f"first, nearest first, then the rest ({inside / 3600:.1f} h to clear the area at one a second)")
    return [p for _, p in ranked]


def save(f, index, done, foreign):
    """The checkpoint, in index order, with the rows this crawl did not write last: build_city.dedupe
    keeps the first of two near-duplicates, which should be the crawled copy with the prices on it."""
    write_atomic(f, json.dumps([done[p["url"]] for p in index if p["url"] in done] + foreign, indent=0))


def crawl_projects():
    index = json.loads((OUT / "mb_index.json").read_text())
    f = OUT / "mb_projects.json"
    done, foreign = resume(f, index)
    todo = [p for p in index if p["url"] not in done]
    say(f"{len(index)} projects: {len(done)} already parsed, {len(todo)} to fetch"
        + (f", {len(foreign)} rows from another source kept" if foreign else ""))
    todo = prioritise(todo, done, CFG.get("priority"))

    def one(p):
        """The project's card merged with its page, or None when there is no page to merge.

        A record that never reached its project page has no coordinates, so the build drops it and
        counts it as not located -- which reads as a project the map could not place rather than one
        this crawl has not read yet. Leaving it out of the checkpoint keeps the two apart: resume()
        then has it in todo, and the next run asks again.
        """
        if stop.is_set():
            return None  # a block ended this run: stop asking, and publish nothing half-read
        try:
            html = fetch(p["url"])
        except Blocked as e:
            say(f"  blocked: {e}")
            stop.set()
            return None
        except Gone as e:
            say(f"  gone: {e}")
            return None
        if not html:
            return None
        try:
            detail = mb_parse.parse_project_page(html)
        except Exception as e:
            say(f"  parse failed {p['url']} {e}")
            detail = {}
        return {**p, **{k: v for k, v in detail.items() if v not in (None, [], "")}}

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, merged in enumerate(ex.map(one, todo), 1):
            if merged:
                done[merged["url"]] = merged
            if i % EVERY == 0 or i == len(todo):
                say(f"project {i}/{len(todo)}")
                save(f, index, done, foreign)
    save(f, index, done, foreign)
    if stop.is_set():
        say(f"stopped: the site blocked us, {len(index) - len(done)} projects still unread. Re-run "
            "later and it picks up from here -- nothing was worked around.")


if __name__ == "__main__":
    try:
        {"list": crawl_list, "projects": crawl_projects}[sys.argv[1]]()
    except Blocked as e:
        sys.exit(f"blocked by the site at {e}: stopping instead of working around it")
