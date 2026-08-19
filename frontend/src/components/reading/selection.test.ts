import { beforeEach, describe, expect, it } from 'vitest';
import {
  MIN_COMPARE_CHARS,
  MIN_SELECTION_CHARS,
  clearSelection,
  readSelection,
} from './selection';

/** Select `text` inside a fresh paragraph and return the containing block. */
function selectWithin(html: string, selector = 'p'): void {
  document.body.innerHTML = html;
  const node = document.querySelector(selector)!;
  const range = document.createRange();
  range.selectNodeContents(node);
  const selection = window.getSelection()!;
  selection.removeAllRanges();
  selection.addRange(range);
}

beforeEach(() => {
  document.body.innerHTML = '';
  window.getSelection()?.removeAllRanges();
});

describe('readSelection', () => {
  it('returns null when nothing is selected', () => {
    expect(readSelection(window)).toBeNull();
  });

  it('returns null for a selection below the threshold', () => {
    // A click that dragged a few pixels, not an intent to select.
    selectWithin('<p>short</p>');
    expect(readSelection(window)).toBeNull();
  });

  it('returns the selected text once it is long enough', () => {
    selectWithin('<p>a passage long enough to count as a selection</p>');
    expect(readSelection(window)?.text)
      .toBe('a passage long enough to count as a selection');
  });

  it('trims surrounding whitespace before measuring', () => {
    selectWithin('<p>   \n  tiny  \n </p>');
    expect(readSelection(window)).toBeNull();
  });

  it('defaults to the parent window when given nothing', () => {
    selectWithin('<p>a passage long enough to count as a selection</p>');
    expect(readSelection(undefined)?.text).toContain('a passage long enough');
  });

  it('is safe against a window with no getSelection', () => {
    expect(readSelection({} as unknown as Window)).toBeNull();
  });
});

describe('readSelection surrounding context', () => {
  it('returns the enclosing block, not just the selection', () => {
    document.body.innerHTML =
      '<div id="page"><p>Preceding sentence for context. </p>' +
      '<p id="target">the selected passage of prose here</p>' +
      '<p>Following sentence for context.</p></div>';
    const target = document.querySelector('#target')!;
    const range = document.createRange();
    range.selectNodeContents(target.firstChild!);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);

    // Selecting a whole paragraph is the common case, and that paragraph
    // holds nothing the model does not already have — so the climb has to
    // continue past it to the block that carries the neighbouring prose.
    const found = readSelection(window);
    expect(found?.text).toBe('the selected passage of prose here');
    expect(found?.surrounding).toContain('Preceding sentence for context');
    expect(found?.surrounding).toContain('Following sentence for context');
  });

  it('stops climbing once an ancestor carries real context', () => {
    document.body.innerHTML =
      '<main><article><div id="page"><p>' + 'Context prose. '.repeat(40) + '</p>' +
      '<p id="target">the selected passage of prose here</p></div></article></main>';
    const target = document.querySelector('#target')!;
    const range = document.createRange();
    range.selectNodeContents(target.firstChild!);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);

    const surrounding = readSelection(window)?.surrounding ?? '';
    expect(surrounding).toContain('Context prose.');
    expect(surrounding.length).toBeLessThanOrEqual(2200);
  });

  it('is empty when the page holds nothing beyond the selection itself', () => {
    selectWithin('<p>a passage long enough to count as a selection</p>');
    expect(readSelection(window)?.surrounding).toBe('');
  });
});

describe('thresholds', () => {
  it('needs more text to retrieve against than to act on', () => {
    // Comparing a six-word fragment against 618 books returns noise.
    expect(MIN_COMPARE_CHARS).toBeGreaterThan(MIN_SELECTION_CHARS);
  });
});

describe('clearSelection', () => {
  it('drops the current selection', () => {
    selectWithin('<p>a passage long enough to count as a selection</p>');
    clearSelection(window);
    expect(readSelection(window)).toBeNull();
  });

  it('does not throw on a window it cannot reach', () => {
    expect(() => clearSelection(null)).not.toThrow();
    expect(() => clearSelection({} as unknown as Window)).not.toThrow();
  });
});
