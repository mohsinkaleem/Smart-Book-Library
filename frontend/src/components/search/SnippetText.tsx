import { Fragment } from 'react';
import clsx from 'clsx';

/**
 * Delimiters FTS5's `snippet()` wraps around matched terms, mirroring
 * `SNIPPET_OPEN` / `SNIPPET_CLOSE` in `server/db.py`.
 *
 * Control characters rather than `<b>…</b>` on purpose: the snippet is
 * rendered as text, so the server never gets to inject markup into the page,
 * and these two bytes cannot occur in extracted book text.
 */
const OPEN = '';
const CLOSE = '';

interface SnippetTextProps {
  snippet: string;
  className?: string;
}

/**
 * Why a search result matched.
 *
 * Results used to render the same card as browsing, with no indication of
 * which of the 544 books' worth of prose or metadata contained the query.
 */
export function SnippetText({ snippet, className }: SnippetTextProps) {
  if (!snippet) return null;

  // Split on the open marker, then on the close marker inside each piece:
  // everything before a close marker was a match, everything after is plain.
  const parts = snippet.split(OPEN).flatMap((chunk, i) => {
    if (i === 0) return [{ text: chunk, hit: false }];
    const [hit, ...rest] = chunk.split(CLOSE);
    return [
      { text: hit, hit: true },
      { text: rest.join(CLOSE), hit: false },
    ];
  });

  return (
    <p className={clsx('line-clamp-2 text-[11px] leading-snug text-slate-500', className)}>
      {parts.map((part, i) =>
        part.hit ? (
          <mark
            key={i}
            className="rounded-sm bg-primary-100 px-0.5 text-primary-800 dark:bg-primary-900/50 dark:text-primary-200"
          >
            {part.text}
          </mark>
        ) : (
          <Fragment key={i}>{part.text}</Fragment>
        ),
      )}
    </p>
  );
}
