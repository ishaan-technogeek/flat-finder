# Flat Finder

Every housing society in a city on one night map. Set the smallest bedroom you can live with, size, BHK, amenities and budget, and watch the societies that fit light up. Every number links to where it came from.

Gurugram is first: about 2,700 projects from Magicbricks, building outlines from OpenStreetMap, and a set of societies verified by reading builder brochures and HRERA plans.

Hyderabad is second and deliberately partial: 634 societies with their locations and localities from OpenStreetMap, and no prices, rents or unit sizes, because its listing pages have not been read. Nothing is estimated to cover the gap. What it can answer is where a society is, what type it is and what is near it; set a budget or a bedroom size and every society there turns to "not checked yet" until a crawl runs.

This is a fork of [kairothq/flat-finder](https://github.com/kairothq/flat-finder) that adds Hyderabad, published at <https://ishaan-technogeek.github.io/flat-finder/>.

## What the colours mean

- **Bright**: matches your search.
- **Amber**: likely. The rooms we have read pass, but not every bedroom has been read yet.
- **Faint outline**: not checked yet. We have no room sizes for it, so it is neither a pass nor a fail.
- **Dark**: does not match.

Building shapes come from OpenStreetMap where they are mapped. Where they are not, the outline is drawn to the listed site area and the towers to the listed tower count — and where those are not listed either, the card says so rather than claiming a number: 476 of Gurugram's drawn societies get one tower per 120 homes, and 434 list neither towers nor homes, so their towers are a placeholder. Shapes are visual only; data numbers are never estimated.

## How bedroom sizes are read

Four sources, most trusted first. Each unit on a card says which one it came from.

1. **Checked by hand**: rooms read from builder brochures or HRERA plans by a person, page cited (`data/verified/<city>.json`).
2. **OCR of a floor plan image**: macOS's built-in text recognition reads every printed size on the plan; code pairs each size with its own room label and takes the smallest bedroom. Free and local (`pipeline/plan_ocr.py`). Where Jev also read the plan, the two must agree within 2 inches.
3. **OCR of brochures and HRERA filings**: the same reading on brochure pages and HRERA "approved building plans" (`pipeline/brochure_ocr.py`, `pipeline/hrera.py`). A page can hold two unit plans, so these are never "complete": a failing room still fails, passing rooms only make a society "likely".
4. **Jev (TypeSafe)**: a fast typed-decision model that answers multiple-choice and yes/no questions about the plan image (`pipeline/jev_reader.py`). Used as a cross-check and a fallback. In spot checks it overstated a room about 1 time in 10, so a Jev-only reading is never more than "likely".

Bedrooms under 8 ft wide are dropped as mis-pairings. Plans that are 3D renders without printed sizes are skipped.

## Buy or rent

Every society shows buy prices and monthly rents per BHK: medians, ranges and counts of live Magicbricks listings (22,018 homes for sale and 7,371 for rent in Gurugram). Where a society has no listings, the site shows **our estimate, marked "~"**, with the working shown:

- rent from price (or price from rent) using the rental yield measured on 960 society and BHK pairs that have both (about 2.5% of the price per year, correlation between log price and log rent 0.91), using the locality's own yield where it has at least 4 pairs;
- when there are no listings at all, unit size x the project's price per sq ft, then rent via yield.

Cards also show resident ratings by category, review snippets, the 5-year price per sq ft trend, and links to Google Maps (with Google reviews) and directions.

## Download the data

- `/data/<city>-societies.csv` (`gurgaon`, `hyderabad`): one row per society (location, type, listings, buy and rent medians and estimates per BHK, ratings, amenities, links).
- `/data/<city>-units.csv`: one row per unit type, with bedroom sizes and sources. Hyderabad has no unit rows yet.
- "Export these results" on the site downloads whatever your filters currently match.

## Use it inside Claude (connector)

Flat Finder is an MCP server at `https://flat-finder.pages.dev/mcp` — upstream's deployment, so Gurugram only. This fork is on GitHub Pages, which serves files and cannot run `web/functions/mcp.js`, so `/mcp` on it answers 404 and there is no connector for Hyderabad yet; `--data` on the CLI below reads a local build in the meantime. In Claude, add a custom connector with the upstream URL, then ask things like "3 BHK in Gurgaon under ₹80k rent, every bedroom at least 11 by 12, park within 500 m". Tools: `search_societies` (any sector, budget, size, amenity, distance; up to 200 results per call), `breakdown` (group by sector, BHK, amenity, metro distance or rent band), `list_localities`, `get_society` (with reviews and rating categories), `compare_societies`. Listing prices that look like typos are flagged with a reason and not used for filtering.

## Search from a terminal

```bash
npx github:ishaan-technogeek/flat-finder --bhk 3,4 --min-bedroom "11'3x12'3" --min-sqft 1620 --amenity squash --likely
npx github:ishaan-technogeek/flat-finder --city hyderabad --type apartment --near park
```

## Use it with Claude Code

`skills/flat-finder/SKILL.md` is a Claude Code skill. Copy it into `~/.claude/skills/flat-finder/` and ask Claude to "add Bangalore to flat finder", "verify Ireo Skyon", or "find me a 3 BHK with every bedroom at least 11 by 12 feet". It follows the same rules as this repo: primary sources first, never estimate, every number keeps its page.

## Run it

```bash
# data
cd pipeline
python3 mb_crawl.py list gurgaon && python3 mb_crawl.py projects gurgaon   # polite, cached, resumable

# a city of 28,101 projects takes hours, so run it detached behind a log that rolls instead of growing
python3 -u mb_crawl.py projects hyderabad | python3 -u rolling_log.py logs/hyderabad-crawl.log
python3 osm_fetch.py gurgaon
python3 build_city.py gurgaon                                               # -> web/public/data/

# a city with no crawl yet: seed it from OpenStreetMap instead of the portal
python3 seed_hyderabad.py                                                   # -> data/seed/hyderabad.json
python3 osm_fetch.py hyderabad
python3 build_hyderabad.py          # seed -> the same build; crawled records win where both exist

# site
cd ../web && npm install && npm run dev
```

Tests: `cd pipeline && uv run --with pytest pytest` and `cd web && npx vitest run --root .. cli web/src`.

Cities live in `data/cities.json`. Gurugram and Hyderabad are built; Bengaluru and Mumbai are configured and need the pipeline run (see the skill, Job 2). A city may set `default_mode` to `rent` to open on monthly rents, `tiles` to split its buildings query when one bbox is too big for Overpass, and `priority` (`{name, center: [lng, lat], km}`) to have the crawler read one area first — Hyderabad reads the 10 km around HITEC City before the rest of the city. Nothing is dropped either way; `priority` only changes the order pages are fetched in.

Press `/` to search for a society. The Streets button switches to a street map with road and sector names.

Useful links: `?city=gurgaon` or `?city=hyderabad`, `?map=streets` or `?map=light`, `?preset=divy` loads the example search, `?open=<society id>` opens one society, `?nointro` skips the globe fly-in.

## Add verified research

Verified rows live in `data/verified/<city>.json`. Each unit type lists its bedrooms exactly as printed (`12'10"x16'4"` or millimetres `3350x3750`) with the source URL and page. Open a pull request, or use "Research this society" on any card to request one.

## Sources

Magicbricks project pages (listing facts, live sale and rent listings, resident ratings and reviews), OpenStreetMap contributors (outlines, ODbL), Esri World Imagery (basemap), OpenFreeMap (roads and city buildings), HRERA Gurugram and builder brochures (verified rows).
