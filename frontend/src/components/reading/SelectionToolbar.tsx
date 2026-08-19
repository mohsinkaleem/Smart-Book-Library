import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Copy, Check, GitCompare, Highlighter, MessageSquarePlus, Sparkles } from 'lucide-react';

export const HIGHLIGHT_COLORS = [
  { id: 'yellow', label: 'Yellow', swatch: '#fde68a' },
  { id: 'green', label: 'Green', swatch: '#bbf7d0' },
  { id: 'blue', label: 'Blue', swatch: '#bfdbfe' },
  { id: 'pink', label: 'Pink', swatch: '#fbcfe8' },
] as const;

interface SelectionToolbarProps {
  text: string;
  /** Viewport-relative box of the selection. */
  rect: DOMRect | null;
  onHighlight: (color: string) => void;
  onNote: () => void;
  onAsk: () => void;
  onCompare: () => void;
  onDismiss: () => void;
}

/** Keeps the toolbar fully on screen when the selection is near an edge. */
const MARGIN = 8;

/**
 * A floating toolbar over the selection: Highlight · Note · Ask · Compare · Copy.
 *
 * Replaces the previous interaction, where any selection of 10 characters or
 * more yanked the whole analysis sidebar open — including on an accidental
 * double-click, and including while the reader was mid-sentence. Offering the
 * actions at the selection means the reader chooses to open the sidebar
 * rather than having it happen to them, and it is the natural home for the
 * passage features in Part 1 of the roadmap.
 */
export function SelectionToolbar({
  text, rect, onHighlight, onNote, onAsk, onCompare, onDismiss,
}: SelectionToolbarProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [showColors, setShowColors] = useState(false);
  // Which text the reader last copied. Derived rather than reset by an
  // effect, so switching selections cannot leave a stale tick behind.
  const [copiedText, setCopiedText] = useState('');
  const copied = !!text && copiedText === text;

  /**
   * Place the toolbar against its own measured size.
   *
   * Written straight to the DOM rather than held in state: the position is
   * only knowable after layout, and routing it back through React would mean
   * a second render on every selection — one paint at the wrong place, then
   * a correction.
   */
  const place = useCallback(() => {
    const el = ref.current;
    if (!el || !rect) return;
    const { offsetWidth: width, offsetHeight: height } = el;

    // Above the selection by default; below it when there is no room above.
    const above = rect.top - height - MARGIN;
    const top = above > MARGIN ? above : rect.bottom + MARGIN;

    // Clamped to the viewport at both ends. The upper bound has its own
    // floor because on a narrow viewport it goes negative — a toolbar wider
    // than the window would otherwise be pushed off the *left* edge by the
    // rule meant to keep it off the right one.
    const centred = rect.left + rect.width / 2 - width / 2;
    const rightmost = Math.max(MARGIN, window.innerWidth - width - MARGIN);
    const left = Math.min(Math.max(MARGIN, centred), rightmost);

    el.style.top = `${top}px`;
    el.style.left = `${left}px`;
    el.style.visibility = 'visible';
  }, [rect]);

  // Placed twice: once synchronously, then again on the next frame. The first
  // pass can measure a toolbar whose icon fonts and borders have not settled,
  // and a stale width lands it in the wrong place with no later event to
  // correct it.
  useLayoutEffect(() => {
    place();
    const frame = requestAnimationFrame(place);
    return () => cancelAnimationFrame(frame);
  }, [place, showColors]);

  // Dismiss on Escape, and on a scroll that moves the selection out from
  // under the toolbar. `capture` catches scrolls inside the reader pane,
  // which do not bubble to window.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onDismiss();
    };
    window.addEventListener('keydown', onKey);
    window.addEventListener('scroll', onDismiss, true);
    window.addEventListener('resize', place);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', onDismiss, true);
      window.removeEventListener('resize', place);
    };
  }, [onDismiss, place]);

  if (!text || !rect) return null;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedText(text);
    } catch {
      setCopiedText('');
    }
  };

  const button =
    'flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-slate-600 ' +
    'transition-colors hover:bg-primary-50 hover:text-primary-700 ' +
    'dark:text-slate-300 dark:hover:bg-primary-900/30';

  return (
    <div
      ref={ref}
      role="toolbar"
      aria-label="Selection actions"
      // Hidden until `place` has measured it, so it never flashes at the
      // top-left corner on the frame before positioning.
      style={{ visibility: 'hidden' }}
      className="fixed left-0 top-0 z-50 flex max-w-[calc(100vw-16px)] flex-wrap items-center gap-0.5 rounded-lg border border-slate-200 bg-white p-1 shadow-lg dark:border-slate-600 dark:bg-slate-800"
      // The toolbar sits outside the reader, so a click on it would otherwise
      // clear the very selection it is about to act on.
      onMouseDown={(e) => e.preventDefault()}
    >
      {showColors ? (
        <>
          {HIGHLIGHT_COLORS.map((c) => (
            <button
              key={c.id}
              onClick={() => { onHighlight(c.id); setShowColors(false); }}
              title={c.label}
              aria-label={`Highlight ${c.label.toLowerCase()}`}
              className="h-6 w-6 rounded-full ring-1 ring-slate-300 transition-transform hover:scale-110 dark:ring-slate-500"
              style={{ backgroundColor: c.swatch }}
            />
          ))}
          <button onClick={() => setShowColors(false)} className={button}>
            Cancel
          </button>
        </>
      ) : (
        <>
          <button onClick={() => setShowColors(true)} className={button} title="Highlight">
            <Highlighter size={13} /> Highlight
          </button>
          <button onClick={onNote} className={button} title="Add a note">
            <MessageSquarePlus size={13} /> Note
          </button>
          <div className="mx-0.5 h-4 w-px bg-slate-200 dark:bg-slate-600" />
          <button onClick={onAsk} className={button} title="Ask the model about this passage">
            <Sparkles size={13} /> Ask
          </button>
          <button onClick={onCompare} className={button} title="Find similar passages">
            <GitCompare size={13} /> Compare
          </button>
          <button onClick={copy} className={button} title="Copy">
            {copied ? <Check size={13} className="text-green-600" /> : <Copy size={13} />}
          </button>
        </>
      )}
    </div>
  );
}
