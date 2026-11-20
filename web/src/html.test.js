import { describe, expect, it } from 'vitest';
import { esc, gmapsUrl, href } from './html.js';

describe('esc', () => {
  it('closes the ways out of an attribute or a text node', () => {
    expect(esc('<img src=x onerror="alert(1)">')).toBe('&lt;img src=x onerror=&quot;alert(1)&quot;&gt;');
    expect(esc('Tom & Jerry')).toBe('Tom &amp; Jerry');
  });
  it('null and undefined are empty, not the words', () => {
    expect(esc(null)).toBe('');
    expect(esc(undefined)).toBe('');
  });
});

describe('href', () => {
  it('passes the urls the data files actually hold', () => {
    expect(href('https://www.magicbricks.com/propertyDetails/x-1234')).toBe('https://www.magicbricks.com/propertyDetails/x-1234');
    expect(href('http://example.com/a?b=1&c=2')).toBe('http://example.com/a?b=1&amp;c=2');
  });
  it('drops a scheme that would run as code in our origin', () => {
    expect(href('javascript:alert(1)')).toBe('');
    expect(href('JavaScript:alert(1)')).toBe('');
    expect(href('data:text/html,<script>alert(1)</script>')).toBe('');
    // the browser strips tabs and newlines inside a url before following it, so a scheme test has to
    // run on the parsed url and not on the raw string
    expect(href('java\nscript:alert(1)')).toBe('');
    expect(href('\t javascript:alert(1)')).toBe('');
  });
  it('drops what it cannot parse, and never throws', () => {
    expect(href('/data/gurgaon.json')).toBe('');
    expect(href('')).toBe('');
    expect(href(null)).toBe('');
    expect(href(undefined)).toBe('');
    expect(href({})).toBe('');
  });
});

describe('gmapsUrl', () => {
  // These are the exact strings pipeline/tests/test_build.py asserts for the same three societies: the
  // link is derived here and published in the CSV from there, so the two encoders have to agree.
  it('searches for the society by name, locality and city', () => {
    expect(gmapsUrl('DLF Magnolias', 'DLF Phase 5', 'Gurugram'))
      .toBe('https://www.google.com/maps/search/?api=1&query=DLF%20Magnolias%2C%20DLF%20Phase%205%2C%20Gurugram');
  });
  it("keeps what a url encoder keeps and escapes the rest, apostrophes and slashes included", () => {
    expect(gmapsUrl("King's Court A/B", 'Sector 54 & 55', 'Gurugram'))
      .toBe("https://www.google.com/maps/search/?api=1&query=King's%20Court%20A%2FB%2C%20Sector%2054%20%26%2055%2C%20Gurugram");
  });
  it('a society with no locality still gets a city-wide search', () => {
    expect(gmapsUrl('My Home Bhooja', null, 'Hyderabad'))
      .toBe('https://www.google.com/maps/search/?api=1&query=My%20Home%20Bhooja%2C%20%2C%20Hyderabad');
  });
});
