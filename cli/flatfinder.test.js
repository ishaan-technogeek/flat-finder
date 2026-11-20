import { expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { linkFor, parseArgs, parseFeet, parsePrice, search } from './flatfinder.mjs';

it('reads feet and prices', () => {
  expect(parseFeet("11'3")).toBe(11.25);
  expect(parseFeet('11.25')).toBe(11.25);
  expect(parsePrice('3cr')).toBe(3e7);
  expect(parsePrice('90L')).toBe(9e6);
});

it("Divy's search finds Araya and Presidia as matches", () => {
  const city = JSON.parse(readFileSync(new URL('../web/public/data/gurgaon.json', import.meta.url)));
  const o = parseArgs(['--bhk', '2,3,4', '--min-bedroom', "11'3x12'3", '--min-sqft', '1620', '--amenity', 'squash']);
  const names = search(city, o).map((r) => r.s.name);
  expect(names).toContain('Pioneer Araya');
  expect(names).toContain('Pioneer Presidia');
  expect(names).not.toContain('Emaar Amaris');
});

it('links to the city the data came from, not the one --city defaulted to', () => {
  const s = { id: 'sseed-1f2f824bd8' };
  // --data hyderabad.json used to print ?city=gurgaon, so following the link opened the wrong city and the id missed
  expect(linkFor({ city: { id: 'hyderabad' } }, s, 'gurgaon')).toContain('?city=hyderabad&open=sseed-1f2f824bd8');
  expect(linkFor({ city: { id: 'gurgaon' } }, { id: 's123' }, 'gurgaon')).toContain('?city=gurgaon&open=s123');
  expect(linkFor({}, s, 'gurgaon')).toContain('?city=gurgaon');  // older data files carry no id
});

it('reads monthly rent', () => {
  expect(parsePrice('80k')).toBe(80000);
  expect(parseArgs(['--max-rent', '80k']).crit).toMatchObject({ mode: 'rent', maxRent: 80000 });
});
