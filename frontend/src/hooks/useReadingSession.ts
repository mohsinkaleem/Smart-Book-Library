import { useEffect, useRef } from 'react';
import { sendHeartbeat } from '../api/threads';

/** Matches `catalog.reading_sessions.HEARTBEAT_SECONDS`. */
const HEARTBEAT_MS = 60_000;

/**
 * Record that a book is being read, for as long as this reader is mounted.
 *
 * A heartbeat rather than an open/close pair, because there is no reliable
 * "closed the laptop" event and a session closed only on unmount reports a
 * fourteen-hour reading day. The server closes a session by noticing the beats
 * stopped, so the worst case is losing the final interval.
 *
 * Beating pauses while the tab is hidden. Without that, a reader left open in
 * a background tab overnight logs the night as reading — which is the same bug
 * in a different costume.
 */
export function useReadingSession(bookId: string, page?: number | null) {
  // The page is read through a ref so a page turn does not tear down and
  // rebuild the interval — otherwise a reader turning pages steadily would
  // reset the timer before it ever fired.
  const pageRef = useRef(page);
  pageRef.current = page;

  useEffect(() => {
    if (!bookId) return;

    const beat = () => {
      if (document.visibilityState === 'visible') {
        sendHeartbeat(bookId, pageRef.current);
      }
    };

    beat();
    const timer = window.setInterval(beat, HEARTBEAT_MS);

    // Beat once when the tab comes back, so returning to a book does not wait
    // out a full interval before the session resumes.
    document.addEventListener('visibilitychange', beat);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', beat);
      // A final beat on the way out records the time since the last one.
      if (document.visibilityState === 'visible') sendHeartbeat(bookId, pageRef.current);
    };
  }, [bookId]);
}
