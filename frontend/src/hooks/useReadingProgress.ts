import { useCallback, useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { patch, patchKeepalive } from '../api/client';
import type { Book } from '../api/types';

/** How long the reader sits still before the position is written. */
const SAVE_DEBOUNCE_MS = 1500;

interface Progress {
  /** 0–100. */
  percent: number;
  /** An EPUB CFI, or a PDF page number as a string. Opaque to the server. */
  position: string;
}

/**
 * Persist where the reader is.
 *
 * `progress_percent` and `last_opened` were in the schema, in `USER_FIELDS`,
 * in the TypeScript `Book` type and offered as a `sort=last_opened` option —
 * and nothing in the app ever wrote either one. The EPUB location was
 * component state and the PDF page reset to 1, so reopening a 600-page book
 * put you back at the cover.
 *
 * Three writes, deliberately separated:
 *
 * - **on open**, once: `last_opened`, plus a promotion from `not_started` to
 *   `in_progress`. Only that one transition, so a book you marked *finished*
 *   or *abandoned* is not silently reopened as in-progress by glancing at it.
 * - **while reading**, debounced: percent and position. A page turn every
 *   two seconds must not be a PATCH every two seconds.
 * - **on the way out** — unmount, tab close, backgrounding — whatever the
 *   debounce still owes.
 */
export function useReadingProgress(book: Book | undefined) {
  const queryClient = useQueryClient();
  const bookId = book?.id;

  const pending = useRef<Progress | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const opened = useRef<string | null>(null);

  /** Write the outstanding position now, if there is one. */
  const flush = useCallback(
    (unloading = false) => {
      const id = bookId;
      const next = pending.current;
      if (!id || !next) return;
      pending.current = null;
      if (timer.current) clearTimeout(timer.current);

      const fields = {
        progress_percent: Math.min(100, Math.max(0, Math.round(next.percent * 10) / 10)),
        reader_position: next.position,
        last_opened: new Date().toISOString(),
      };
      if (unloading) {
        patchKeepalive(`/api/books/${id}`, fields);
        return;
      }
      patch(`/api/books/${id}`, fields)
        .then(() => {
          // The library list and the book page both render progress.
          queryClient.invalidateQueries({ queryKey: ['book', id] });
          queryClient.invalidateQueries({ queryKey: ['continueReading'] });
        })
        .catch(() => {
          /* a lost position is not worth interrupting reading over */
        });
    },
    // Only changes when the route moves to a different book, at which point
    // the cleanup below flushing the previous one is exactly right.
    [bookId, queryClient],
  );

  // Opening the book.
  useEffect(() => {
    if (!book || opened.current === book.id) return;
    opened.current = book.id;

    const fields: Record<string, unknown> = { last_opened: new Date().toISOString() };
    if (book.reading_status === 'not_started') fields.reading_status = 'in_progress';

    patch(`/api/books/${book.id}`, fields)
      .then(() => {
        queryClient.invalidateQueries({ queryKey: ['book', book.id] });
        queryClient.invalidateQueries({ queryKey: ['continueReading'] });
      })
      .catch(() => {});
  }, [book, queryClient]);

  // Leaving: unmount, or the tab going away. `pagehide` rather than
  // `beforeunload` — it is the one that fires on mobile and on bfcache.
  useEffect(() => {
    const onLeave = () => flush(true);
    const onHide = () => {
      if (document.visibilityState === 'hidden') flush(true);
    };
    window.addEventListener('pagehide', onLeave);
    document.addEventListener('visibilitychange', onHide);
    return () => {
      window.removeEventListener('pagehide', onLeave);
      document.removeEventListener('visibilitychange', onHide);
      flush();
    };
  }, [flush]);

  /** Call on every page turn; the debounce decides when it reaches the server. */
  return useCallback(
    (percent: number, position: string) => {
      if (!bookId || !Number.isFinite(percent)) return;
      pending.current = { percent, position };
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => flush(), SAVE_DEBOUNCE_MS);
    },
    [bookId, flush],
  );
}
