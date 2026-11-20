import { describe, expect, it } from 'vitest';
import { aiRead, canVouch, eventsFor } from './events.js';

const society = (over = {}) => ({
  id: 's1', name: 'Aparna Sarovar', locality: 'Gachibowli', lat: 17.440123, lng: 78.348456,
  url: 'https://example.com/p/1', amenities: [], unit_types: [], ...over,
});

describe('eventsFor', () => {
  it('always places the society, and names the city when the locality is unknown', () => {
    expect(eventsFor(society(), 'Hyderabad')[0]).toEqual({
      sid: 's1', step: 'Located on map', finding: 'Gachibowli · 17.4401, 78.3485', url: 'https://example.com/p/1',
    });
    expect(eventsFor(society({ locality: null }), 'Hyderabad')[0].finding).toBe('Hyderabad · 17.4401, 78.3485');
  });

  it('reads the project page, the registration and the amenity list, and skips what the data lacks', () => {
    const ev = eventsFor(society({ towers: 6, units: 1234, acres: 12, rera_id: 'P02400005555', amenities: ['Gym', 'Pool', 'Park', 'Clubhouse', 'Lift'] }), 'Hyderabad');
    expect(ev.map((e) => [e.step, e.finding])).toEqual([
      ['Located on map', 'Gachibowli · 17.4401, 78.3485'],
      ['Project page read', '6 towers · 1,234 units · 12 acres'],
      ['RERA registration', 'P02400005555'],
      ['5 amenities listed', 'Gym, Pool, Park, Clubhouse'],  // the first four, as the panel is two lines tall
    ]);
    // a society the portal said nothing about gets one step, not four empty ones
    expect(eventsFor(society(), 'Hyderabad')).toHaveLength(1);
  });

  it('credits the page a measurement came from, not the society page', () => {
    const [, court] = eventsFor(society({ amen_facts: { tennis: { value: '2 courts', page: 14, source: 'https://example.com/brochure.pdf' } } }), 'Hyderabad');
    expect(court).toEqual({ sid: 's1', step: 'Checked tennis court', finding: '2 courts · p.14', url: 'https://example.com/brochure.pdf', verified: true });
  });

  it('says what was read off a floor plan, in feet and inches like the card', () => {
    const u = { label: '3 BHK floor plan', bhk: 3, bedrooms: [[9.25, 12.0833], [11.5, 14.75]], confidence: 'ocr',
      checked_by: 'OCR of the brochure', source: 'https://example.com/plan.jpg' };
    const [, read] = eventsFor(society({ unit_types: [u] }), 'Hyderabad');
    expect(read).toEqual({
      sid: 's1', step: 'Read floor plan (OCR of the brochure)', finding: '3 BHK · bedrooms 9\'3" × 12\'1", 11\'6" × 14\'9"',
      url: 'https://example.com/plan.jpg', verified: true, unit: '3 BHK floor plan',
    });
    // a brochure page that never says how many bedrooms it is for used to open "None BHK ·"
    expect(eventsFor(society({ unit_types: [{ ...u, bhk: null, label: 'Unit plan' }] }), 'Hyderabad')[1].finding)
      .toBe('bedrooms 9\'3" × 12\'1", 11\'6" × 14\'9"');
  });

  it('marks only a reading that was actually verified', () => {
    const base = { label: '2 BHK plan', bhk: 2, bedrooms: [[10, 12]], bedrooms_printed: ["10'0\" x 12'0\""], page: '7', source: 'https://example.com/filing.pdf' };
    expect(eventsFor(society({ unit_types: [{ ...base, confidence: 'primary' }] }), 'Hyderabad')[1]).toMatchObject({ step: 'Reading plan p.7', verified: true });
    expect(eventsFor(society({ unit_types: [{ ...base, confidence: 'portal' }] }), 'Hyderabad')[1]).toMatchObject({ verified: false });
    // a portal unit with a size and no plan is a listing, not a reading
    expect(eventsFor(society({ unit_types: [{ label: '2 BHK 1,150 sq ft', bhk: 2, bedrooms: [], size_sqft: 1150, confidence: 'portal', source: 'https://example.com/p/1' }] }), 'Hyderabad')[1])
      .toEqual({ sid: 's1', step: 'Unit type listed', finding: '2 BHK 1,150 sq ft', url: 'https://example.com/p/1' });
  });

  it('says what Jev could bound and what it could not', () => {
    expect(aiRead({ min_short: 9.5, long_lb: 12.5, area_lb: 118 })).toBe('narrowest bedroom 9\'6", every bedroom at least 12\'6" long, at least 118 sq ft');
    expect(aiRead({ min_short: 10, long_lb: null, area_lb: null })).toBe('narrowest bedroom 10\'0"');
    expect(aiRead({})).toBe('');  // the card then says "partly read"
    const [, jev] = eventsFor(society({ unit_types: [{ label: '2 BHK floor plan', bhk: 2, ai: { min_short: 9.5 }, bedrooms: [], source: 'https://example.com/plan.jpg' }] }), 'Hyderabad');
    expect(jev).toEqual({ sid: 's1', step: 'Jev read floor plan', finding: '2 BHK · narrowest bedroom 9\'6"', url: 'https://example.com/plan.jpg', verified: true, unit: '2 BHK floor plan' });
  });
});

it('canVouch picks the societies that can show a verified step', () => {
  expect(canVouch(society())).toBe(false);
  expect(canVouch(society({ verified: true }))).toBe(true);
  expect(canVouch(society({ ai_read: true }))).toBe(true);
  expect(canVouch(society({ amen_facts: { tennis: {} } }))).toBe(true);
  expect(canVouch(society({ amen_facts: {} }))).toBe(false);
});
