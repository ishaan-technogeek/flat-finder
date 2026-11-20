// Putting data into HTML. Both helpers were written twice in this app; they are here once, with tests.

export const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// A url out of a data file, escaped for an href or src, or '' if it is not one we will link to.
// esc() makes a url safe to sit inside an attribute but says nothing about where it points, and a
// `javascript:` href runs in our own origin. These urls are scraped off portal pages and read from
// OpenStreetMap tags, so a data file is not a trusted source: only http(s) gets a link, and what we
// emit is the url the parser saw, since the browser strips tabs and newlines before following it.
export const href = (u) => {
  try {
    const parsed = new URL(String(u));
    return /^https?:$/.test(parsed.protocol) ? esc(parsed.href) : '';
  } catch {
    return ''; // relative or unparseable: every url in the data files is absolute
  }
};

// The "Google Maps and reviews" link: a search for the society by name, locality and city. It used to be
// built once per society in build_city and shipped in the city file, which is 2.8 MB of a string every
// reader can derive -- so everyone derives it here instead, and build_city.gmaps_url() produces the same
// bytes (same encoder, same safe set) for the CSV column, which is published and has to stay.
export const gmapsUrl = (name, locality, city) =>
  'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(`${name}, ${locality || ''}, ${city}`);
