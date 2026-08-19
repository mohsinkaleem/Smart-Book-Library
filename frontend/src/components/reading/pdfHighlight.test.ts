import { describe, expect, it } from 'vitest';
import {
  escapeHtml,
  mapHighlightsToRuns,
  markSearchHits,
  normalize,
  renderRun,
  type PageHighlight,
} from './pdfHighlight';

/** A page of pdf.js text runs, the way the text layer actually splits prose. */
const runs = (...strs: string[]) => strs.map((str) => ({ str }));

describe('normalize', () => {
  it('lowercases and collapses whitespace', () => {
    expect(normalize('  The   Quick\nBrown ')).toBe('the quick brown');
  });
});

describe('escapeHtml', () => {
  it('escapes every character that could close a tag or attribute', () => {
    expect(escapeHtml('<a href="x">&\'</a>'))
      .toBe('&lt;a href=&quot;x&quot;&gt;&amp;&#39;&lt;/a&gt;');
  });
});

describe('mapHighlightsToRuns', () => {
  const highlight = (text: string, id = 'h1', color = 'yellow'): PageHighlight =>
    ({ id, color, text });

  it('marks the contiguous runs a passage spans', () => {
    const items = runs('The state does not', 'merely regulate', 'religion; it produces');
    const marks = mapHighlightsToRuns(items, [highlight('does not merely regulate religion')]);
    expect([...marks.keys()]).toEqual([0, 1, 2]);
  });

  it('does NOT mark other occurrences of a word inside the passage', () => {
    // The regression this file exists for. A run-containment heuristic marks
    // every `namedtuple` on the page, because each is a substring of the
    // passage and each is its own run.
    const items = runs(
      'A ', 'namedtuple', ' is created from values outside the program.',
      ' Later on this page, ', 'namedtuple', ' appears again.',
    );
    const marks = mapHighlightsToRuns(
      items,
      [highlight('A namedtuple is created from values outside the program.')],
    );
    expect([...marks.keys()]).toEqual([0, 1, 2]);
    expect(marks.has(4)).toBe(false);
  });

  it('finds a passage whose words straddle a run boundary', () => {
    const items = runs('the unity of', 'method between science');
    const marks = mapHighlightsToRuns(items, [highlight('unity of method between')]);
    expect([...marks.keys()]).toEqual([0, 1]);
  });

  it('tolerates whitespace differing between selection and page text', () => {
    const items = runs('Every  act of\nhuman knowledge');
    const marks = mapHighlightsToRuns(items, [highlight('Every act of human knowledge')]);
    expect(marks.has(0)).toBe(true);
  });

  it('is case-insensitive', () => {
    const items = runs('The Reconstruction of Religious Thought');
    const marks = mapHighlightsToRuns(items, [highlight('reconstruction of RELIGIOUS thought')]);
    expect(marks.has(0)).toBe(true);
  });

  it('marks nothing when the passage is not on this page', () => {
    const items = runs('Something else entirely on this page');
    const marks = mapHighlightsToRuns(items, [highlight('a passage from another chapter')]);
    expect(marks.size).toBe(0);
  });

  it('ignores passages too short to place unambiguously', () => {
    const items = runs('the cat sat on the mat');
    expect(mapHighlightsToRuns(items, [highlight('the')]).size).toBe(0);
  });

  it('keeps two highlights on the same page apart', () => {
    const items = runs('First passage here.', ' Middle. ', 'Second passage here.');
    const marks = mapHighlightsToRuns(items, [
      highlight('First passage here.', 'a', 'green'),
      highlight('Second passage here.', 'b', 'blue'),
    ]);
    expect(marks.get(0)).toEqual({ id: 'a', color: 'green' });
    expect(marks.get(2)).toEqual({ id: 'b', color: 'blue' });
    expect(marks.has(1)).toBe(false);
  });

  it('gives an overlap to the earlier highlight rather than painting twice', () => {
    const items = runs('a shared stretch of prose here');
    const marks = mapHighlightsToRuns(items, [
      highlight('shared stretch of prose', 'first', 'green'),
      highlight('stretch of prose here', 'second', 'pink'),
    ]);
    expect(marks.get(0)).toEqual({ id: 'first', color: 'green' });
  });

  it('handles empty inputs', () => {
    expect(mapHighlightsToRuns([], [highlight('anything at all')]).size).toBe(0);
    expect(mapHighlightsToRuns(runs('text'), []).size).toBe(0);
  });
});

describe('markSearchHits', () => {
  it('wraps each occurrence and escapes the rest', () => {
    expect(markSearchHits('dict <b> and dict again', 'dict'))
      .toBe('<mark class="pdf-search">dict</mark> &lt;b&gt; and '
          + '<mark class="pdf-search">dict</mark> again');
  });

  it('is case-insensitive but preserves the original casing', () => {
    expect(markSearchHits('Defaultdict here', 'defaultdict'))
      .toBe('<mark class="pdf-search">Defaultdict</mark> here');
  });

  it('ignores a needle too short to be meaningful', () => {
    expect(markSearchHits('a & b', 'a')).toBe('a &amp; b');
  });

  it('ignores a needle that is only whitespace padding', () => {
    // The needle is normalized before use, so `'a '` is one character.
    expect(markSearchHits('a & b', 'a ')).toBe('a &amp; b');
  });

  it('returns escaped text when there is no match', () => {
    expect(markSearchHits('5 > 3', 'zebra')).toBe('5 &gt; 3');
  });
});

describe('renderRun', () => {
  it('wraps a highlighted run and keeps search marks inside it', () => {
    const html = renderRun('the defaultdict case', { id: 'h1', color: 'green' }, 'defaultdict');
    expect(html).toBe(
      '<mark class="pdf-hl pdf-hl-green" data-annotation="h1">' +
      'the <mark class="pdf-search">defaultdict</mark> case</mark>',
    );
  });

  it('returns bare escaped text when the run is neither highlighted nor matched', () => {
    expect(renderRun('a < b', undefined, '')).toBe('a &lt; b');
  });

  it('escapes a colour and id that came from stored data', () => {
    const html = renderRun('x', { id: '"><script>', color: 'y"z' }, '');
    expect(html).not.toContain('<script>');
    expect(html).toContain('&quot;&gt;&lt;script&gt;');
  });
});
