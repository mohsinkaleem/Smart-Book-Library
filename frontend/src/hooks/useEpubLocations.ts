import { useEffect, useRef, useState } from 'react';
import { get, post } from '../api/client';

/**
 * Break interval for the locations index, in characters.
 *
 * epub.js's own default. Roughly one "page" per 1,024 characters, which is
 * what makes the resulting count comparable to a printed page count rather
 * than an arbitrary number of scroll positions.
 */
const LOCATION_CHARS = 1024;

interface CachedLocations {
  generated: boolean;
  locations?: string;
  total?: number;
}

export interface EpubLocations {
  /** Total locations, or 0 while unavailable. */
  total: number;
  /** True while the first generation pass is running. */
  generating: boolean;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type EpubBook = any;

/**
 * Exact "page X of Y" for an EPUB (§2.1).
 *
 * `book.locations.generate()` walks the entire book and costs seconds on a
 * long one — far too slow to run on every open, which is why EPUB progress was
 * an approximate spine ratio ("chapter 4 of 20") rather than a position.
 *
 * So it runs **once**: generated in the background on first open, posted to the
 * server, and restored with `locations.load()` on every open after that, which
 * is a parse rather than a walk. The reader shows the spine ratio until this
 * lands and switches to exact numbers when it does — the approximate answer is
 * available immediately and is not wrong, just coarse.
 */
export function useEpubLocations(
  bookId: string,
  book: EpubBook | null,
  /**
   * Hold off until the book has actually rendered.
   *
   * `generate()` walks every spine item on the main thread. Started on
   * `book.ready` it races the first paint and the reader shows an empty page
   * for the length of the walk — which on a long book is seconds of looking
   * broken. The caller flips this after the first relocation, so the reader is
   * readable before the index costs anything.
   */
  ready: boolean = true,
): EpubLocations {
  const [total, setTotal] = useState(0);
  const [generating, setGenerating] = useState(false);
  // Generation is expensive and epub.js gives the same book object back on
  // re-render; without this guard a re-render during the walk starts a second.
  const startedFor = useRef<string>('');

  useEffect(() => {
    if (!bookId || !book || !ready || startedFor.current === bookId) return;
    startedFor.current = bookId;
    let cancelled = false;

    (async () => {
      try {
        await book.ready;
        if (cancelled) return;

        const cached = await get<CachedLocations>(
          `/api/books/${encodeURIComponent(bookId)}/locations`,
        );
        if (cancelled) return;

        if (cached.generated && cached.locations) {
          // A parse, not a walk — this is the whole point of caching it.
          book.locations.load(cached.locations);
          setTotal(book.locations.length() || cached.total || 0);
          return;
        }

        // Yield a frame before the walk so the pending render commits first.
        // `ready` already delays this past the first relocation; this covers
        // the paint that relocation itself scheduled.
        setGenerating(true);
        await new Promise((resolve) => window.requestAnimationFrame(() => resolve(null)));
        await book.locations.generate(LOCATION_CHARS);
        if (cancelled) return;

        const count = book.locations.length() || 0;
        setTotal(count);
        // Store it so no other open ever pays for this again. Failing to store
        // costs a regenerated index next time, not a broken reader, so the
        // error is swallowed rather than surfaced.
        void post(`/api/books/${encodeURIComponent(bookId)}/locations`, {
          locations: book.locations.save(),
          total: count,
          chars: LOCATION_CHARS,
        }).catch(() => {});
      } catch {
        // A book epub.js cannot index still reads perfectly well; it just
        // keeps the spine-ratio progress it already had.
      } finally {
        if (!cancelled) setGenerating(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [bookId, book, ready]);

  return { total, generating };
}
