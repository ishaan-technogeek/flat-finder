// The research log's steps for one society, built from the fields the city file already carries.
//
// These used to be built in the pipeline and shipped as one `events` array per city: 16,174 entries and
// 3.1 MB of Gurugram's 9.1 MB city file, for a panel that shows fourteen lines at a time and only ever
// replays one society at a time. So the panel derives them instead, from the society it is about to show.
// Nothing is invented here: every step names a real field and links to the page it was read from.
import { feetLabel } from './filters.js';

// 1234567 -> "1,234,567", without depending on the browser's locale data.
const commas = (n) => String(Math.trunc(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ',');

// What Jev read off a plan, as a sentence. Shared with the card, which says the same thing in its own row:
// said twice, the two drifted, and the log was still printing 9.25 ft where the card said 9'3".
export const aiRead = (ai) => [ai.min_short != null && `narrowest bedroom ${feetLabel(ai.min_short)}`,
  ai.long_lb != null && `every bedroom at least ${feetLabel(ai.long_lb)} long`,
  ai.area_lb != null && `at least ${ai.area_lb} sq ft`].filter(Boolean).join(', ');

export function eventsFor(s, cityName) {
  const ev = [];
  const sid = s.id;
  const src = s.url ?? null;
  ev.push({ sid, step: 'Located on map', finding: `${s.locality || cityName} · ${s.lat.toFixed(4)}, ${s.lng.toFixed(4)}`, url: src });
  const page = [s.towers && `${Math.trunc(s.towers)} towers`, s.units && `${commas(s.units)} units`, s.acres && `${s.acres} acres`].filter(Boolean);
  if (page.length) ev.push({ sid, step: 'Project page read', finding: page.join(' · '), url: src });
  if (s.rera_id) ev.push({ sid, step: 'RERA registration', finding: s.rera_id.slice(0, 60), url: src });
  if (s.amenities?.length) ev.push({ sid, step: `${s.amenities.length} amenities listed`, finding: s.amenities.slice(0, 4).join(', '), url: src });
  for (const [k, f] of Object.entries(s.amen_facts || {}))
    ev.push({ sid, step: `Checked ${k} court`, finding: `${f.value} · p.${f.page}`, url: f.source, verified: true });
  for (const u of s.unit_types || []) {
    // A brochure page can carry a plan that never says how many bedrooms it is for, and 130 of Gurugram's
    // steps used to open "None BHK ·" because of it. The label already says "Unit plan": say nothing.
    const bhk = u.bhk ? `${u.bhk} BHK · ` : '';
    if (u.ai) {
      ev.push({ sid, step: 'Jev read floor plan', finding: bhk + aiRead(u.ai), url: u.source, verified: true, unit: u.label });
    } else if (u.bedrooms?.length && u.confidence === 'ocr') {
      const rooms = u.bedrooms.map((r) => `${feetLabel(r[0])} × ${feetLabel(r[1])}`).join(', ');
      ev.push({ sid, step: `Read floor plan (${u.checked_by})`, finding: `${bhk}bedrooms ${rooms}`, url: u.source, verified: true, unit: u.label });
    } else if (u.bedrooms?.length) {
      ev.push({ sid, step: `Reading plan p.${u.page}`, finding: `${u.label} · bedrooms ${(u.bedrooms_printed || []).join(', ')}`,
        url: u.source, verified: u.confidence === 'primary', unit: u.label });
    } else if (u.size_sqft) {
      ev.push({ sid, step: 'Unit type listed', finding: u.label, url: u.source });
    }
  }
  return ev;
}

// The societies that can produce a step worth replaying on its own: a court measured off a filing, or a
// floor plan somebody read. 575 of Gurugram's 2,580, so the ambient pool stays cheap to build up front.
export const canVouch = (s) => Boolean(s.verified || s.ai_read || (s.amen_facts && Object.keys(s.amen_facts).length));
