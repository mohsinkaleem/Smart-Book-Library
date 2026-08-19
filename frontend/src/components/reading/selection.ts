/**
 * Reading a text selection out of a reader.
 *
 * The 10-character threshold below used to be written three times — in
 * `PdfReader`, in `EpubReader`'s `selected` handler, and again in the iframe
 * fallback listener — so "how much text counts as a selection" was three
 * independent decisions that happened to agree.
 *
 * The EPUB selection lives inside the rendered iframe's own window, not the
 * parent's, which is why every reader passes the window it wants read rather
 * than calling `window.getSelection()` and hoping.
 */

/** Below this, a selection is a click that dragged, not an intent to select. */
export const MIN_SELECTION_CHARS = 10;

/** Below this there is not enough signal to retrieve against. */
export const MIN_COMPARE_CHARS = 15;

/** How much prose either side of the selection is worth sending as context. */
export const SURROUNDING_RADIUS = 900;

export interface ReaderSelection {
  text: string;
  /** Viewport-relative box of the selection, for anchoring the toolbar. */
  rect: DOMRect | null;
  /**
   * Prose around the selection, from its enclosing block.
   *
   * A paragraph read in isolation loses the argument it belongs to, and the
   * model used to see the selection and nothing else. In a PDF the enclosing
   * block is pdf.js's text layer, so this is the page; in an EPUB it is the
   * section element, clipped to a window around the match.
   */
  surrounding: string;
}

/**
 * The current selection in `win`, or null if there is not enough of one.
 *
 * `rect` is translated into the *parent* viewport when the selection is
 * inside an iframe, because that is the coordinate space the floating
 * toolbar is positioned in — an iframe-relative rect would place the toolbar
 * at the wrong place on the page, off by the iframe's own offset.
 */
export function readSelection(win: Window | null | undefined): ReaderSelection | null {
  const target = win ?? window;
  const selection = target.getSelection?.();
  const text = selection?.toString().trim() ?? '';
  if (text.length < MIN_SELECTION_CHARS) return null;

  let rect: DOMRect | null = null;
  try {
    const range = selection?.rangeCount ? selection.getRangeAt(0) : null;
    const raw = range?.getBoundingClientRect() ?? null;
    rect = raw && raw.width + raw.height > 0 ? raw : null;
    if (rect && target !== window) {
      const frame = target.frameElement?.getBoundingClientRect();
      if (frame) {
        rect = new DOMRect(rect.x + frame.x, rect.y + frame.y, rect.width, rect.height);
      }
    }
  } catch {
    /* cross-origin iframe, or a selection that vanished mid-read */
  }

  return { text, rect, surrounding: surroundingText(selection, text) };
}


/** At least this much more text than the selection counts as context. */
const MIN_CONTEXT_GAIN = 200;
/** Give up climbing after this many ancestors rather than reaching for body. */
const MAX_CLIMB = 6;

/**
 * The text around a selection, clipped to `SURROUNDING_RADIUS` either side.
 *
 * Climbing is the whole job. A selection's common ancestor is usually a text
 * node, whose `textContent` *is* the selection — and stopping at the first
 * element above it is barely better, because selecting a whole paragraph is
 * the common case and that paragraph then contains nothing the model does not
 * already have. So the walk continues until an ancestor carries meaningfully
 * more text than the selection, which is the point at which "surrounding"
 * starts to mean something.
 */
function surroundingText(selection: Selection | null | undefined, text: string): string {
  try {
    const range = selection?.rangeCount ? selection.getRangeAt(0) : null;
    let node: Node | null = range?.commonAncestorContainer ?? null;
    while (node && node.nodeType !== Node.ELEMENT_NODE) node = node.parentNode;

    // Keep the widest ancestor seen, and stop at `body`. Walking past it
    // reaches the Document node, whose `textContent` is null — which used to
    // overwrite a perfectly good result with an empty string.
    let block = '';
    let element = node as Element | null;
    for (let i = 0; element && i < MAX_CLIMB; i++) {
      const candidate = element.textContent?.replace(/\s+/g, ' ').trim() ?? '';
      if (candidate.length > block.length) block = candidate;
      if (block.length >= text.length + MIN_CONTEXT_GAIN) break;
      if (element === document.body) break;
      element = element.parentElement;
    }

    if (!block || block.length <= text.length) return '';

    const at = block.indexOf(text.slice(0, 40));
    if (at === -1) return block.slice(0, SURROUNDING_RADIUS * 2);
    return block.slice(
      Math.max(0, at - SURROUNDING_RADIUS),
      at + text.length + SURROUNDING_RADIUS,
    );
  } catch {
    return '';
  }
}

/** Drop the current selection in `win`, after acting on it. */
export function clearSelection(win: Window | null | undefined): void {
  try {
    (win ?? window).getSelection()?.removeAllRanges();
  } catch {
    /* nothing selected, or the frame went away */
  }
}
