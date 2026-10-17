/**
 * Painting highlights and search hits onto a PDF's text layer.
 *
 * There is no styleable text on a PDF canvas — the ink is a bitmap. What is
 * styleable is pdf.js's *text layer*: an invisible run of positioned spans
 * laid over the canvas so text can be selected. react-pdf hands each of those
 * runs to `customTextRenderer` and sets the returned string as innerHTML, so
 * marking a run is how a highlight becomes visible.
 *
 * The hard part is deciding *which* runs. A text run is a positioning
 * artefact, not a word: one highlighted sentence is spread over dozens of
 * them and a run can end mid-word. The obvious heuristic — "mark any run
 * whose text appears inside the highlighted passage" — is wrong in a way that
 * shows: a passage containing the word `namedtuple` makes every other
 * occurrence of `namedtuple` on the page light up too, because each is its
 * own short run and each is genuinely a substring of the passage.
 *
 * So the match is positional instead. The page's runs are joined back into
 * one string, the passage is located *in that string*, and only the runs
 * covering that span are marked. Ranges are resolved once per page from
 * react-pdf's `onGetTextSuccess`, not per run.
 */

export interface PageHighlight {
  id: string;
  color: string;
  /** The full selected passage. */
  text: string;
  /**
   * Accept a prefix of `text` when the whole of it cannot be found.
   *
   * A saved highlight came from this very text layer, so if it does not match
   * exactly the page has reflowed and marking a guess would be worse than
   * marking nothing. A *retrieved* passage did not: its text was extracted by
   * the indexer, which hyphenates, orders columns and spaces ligatures
   * differently from pdf.js, and it can also run onto the next page. Marking
   * its first sentence is the whole point of the jump; marking nothing
   * because its last line disagrees is not.
   */
  approximate?: boolean;
}

/** What one text run should be painted as. */
export interface RunMark {
  id: string;
  color: string;
}

/** `itemIndex` → the highlight covering it. */
export type RunMarks = Map<number, RunMark>;

const ESCAPES: Record<string, string> = {
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
};

export function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (c) => ESCAPES[c]);
}

/** Lowercase with runs of whitespace collapsed, for comparing two renderings. */
export function normalize(value: string): string {
  return value.toLowerCase().replace(/\s+/g, ' ').trim();
}

/**
 * A lowercased, whitespace-collapsed copy of `source`, plus the index in
 * `source` that each surviving character came from.
 *
 * The offset table is the point: normalizing alone would find the passage but
 * lose the ability to say *where* in the original it sits, which is what the
 * run mapping needs.
 */
function compact(source: string): { text: string; offsets: number[] } {
  let text = '';
  const offsets: number[] = [];
  let pendingSpace = false;

  for (let i = 0; i < source.length; i++) {
    const ch = source[i];
    if (/\s/.test(ch)) {
      pendingSpace = text.length > 0;
      continue;
    }
    if (pendingSpace) {
      text += ' ';
      offsets.push(i);
      pendingSpace = false;
    }
    text += ch.toLowerCase();
    offsets.push(i);
  }
  return { text, offsets };
}

/** Shorter than this, a prefix stops identifying a passage. */
const MIN_NEEDLE = 24;

/**
 * Where a passage sits in the page text, and how much of it was found.
 *
 * Halves the needle until something matches or it gets too short to identify
 * a passage. Two halvings are not enough, measured against the real index: a
 * 1,229-character passage on page 315 of *Minkowski Spacetime* matched at
 * one eighth and at nothing longer, because the page's rendered text differs
 * from the indexer's somewhere in the first quarter — a ligature, a
 * hyphenated line break, a run that pdf.js emits without a trailing space.
 * Each disagreement only costs the reader the tail of the mark, and the
 * opening lines are what a jump needs to land on.
 */
function locate(
  haystack: string,
  needle: string,
  approximate: boolean,
): { at: number; length: number } {
  const exact = haystack.indexOf(needle);
  if (exact !== -1 || !approximate) return { at: exact, length: needle.length };

  for (let cut = Math.floor(needle.length / 2); cut >= MIN_NEEDLE; cut = Math.floor(cut / 2)) {
    const probe = needle.slice(0, cut);
    const at = haystack.indexOf(probe);
    if (at !== -1) return { at, length: probe.length };
  }
  return { at: -1, length: 0 };
}

/**
 * Which text runs each highlight covers.
 *
 * Runs are joined with a space because pdf.js emits them without trailing
 * separators — joining bare would fuse the last word of one run to the first
 * of the next and make a passage that spans runs unfindable.
 *
 * Earlier highlights win an overlap: two highlights over the same words can
 * only paint one colour, and the stable choice is the one already listed.
 */
export function mapHighlightsToRuns(
  items: { str: string }[],
  highlights: PageHighlight[],
): RunMarks {
  const marks: RunMarks = new Map();
  if (!items.length || !highlights.length) return marks;

  // Join, recording where each run starts in the joined string.
  const runStarts: number[] = [];
  let joined = '';
  for (const item of items) {
    runStarts.push(joined.length);
    joined += item.str + ' ';
  }

  const page = compact(joined);

  for (const highlight of highlights) {
    const needle = normalize(highlight.text);
    if (needle.length < 8) continue;      // too short to place unambiguously

    const { at, length } = locate(page.text, needle, highlight.approximate === true);
    if (at === -1) continue;              // not on this page, or reflowed away

    const from = page.offsets[at];
    const to = page.offsets[Math.min(at + length - 1, page.offsets.length - 1)];

    for (let i = 0; i < items.length; i++) {
      const start = runStarts[i];
      const end = start + items[i].str.length;
      // Any overlap with the passage's span marks the run.
      if (end > from && start <= to && !marks.has(i)) {
        marks.set(i, { id: highlight.id, color: highlight.color });
      }
    }
  }
  return marks;
}

/**
 * Wrap every occurrence of `needle` in `run` with `<mark class="pdf-search">`.
 * Case-insensitive; returns HTML-escaped output.
 */
export function markSearchHits(run: string, needle: string): string {
  const query = normalize(needle);
  if (query.length < 2) return escapeHtml(run);

  const haystack = run.toLowerCase();
  let out = '';
  let from = 0;
  for (;;) {
    const at = haystack.indexOf(query, from);
    if (at === -1) break;
    out += escapeHtml(run.slice(from, at));
    out += `<mark class="pdf-search">${escapeHtml(run.slice(at, at + query.length))}</mark>`;
    from = at + query.length;
  }
  return out + escapeHtml(run.slice(from));
}

/**
 * The innerHTML for one text-layer run: search hits marked inside it, and the
 * whole run wrapped when `mapHighlightsToRuns` assigned it to a highlight.
 */
export function renderRun(
  run: string,
  mark: RunMark | undefined,
  searchQuery: string,
): string {
  const inner = markSearchHits(run, searchQuery);
  if (!mark) return inner;
  return (
    `<mark class="pdf-hl pdf-hl-${escapeHtml(mark.color)}" ` +
    `data-annotation="${escapeHtml(mark.id)}">${inner}</mark>`
  );
}
