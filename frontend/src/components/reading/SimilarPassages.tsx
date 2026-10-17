import { Link } from 'react-router-dom';
import type { CompareMatch } from '../../api/types';

/** Where the match sits, when it is a passage and not a whole-book fallback. */
function matchLocation(m: CompareMatch): string {
  if (m.page_start) {
    return m.page_end && m.page_end !== m.page_start
      ? `pp. ${m.page_start}-${m.page_end}`
      : `p. ${m.page_start}`;
  }
  return m.section || '';
}

/**
 * "Similar in Other Books" — the same 25-line block previously lived in both
 * `ReadingView` and `ReaderSidebar`.
 *
 * Two things the passage index changed and this card had not caught up with.
 * It was keyed on `book_id`, which was unique while a match *was* a book;
 * passage-level matching returns several passages from one book, so React saw
 * duplicate keys and warned on every Analysis run. And the server has sent a
 * `deep_link` to the matching passage since the index shipped, while the card
 * went on linking to the book's detail page — the reader was told a passage
 * existed and then dropped at the front cover to find it.
 */
export function SimilarPassages({ matches }: { matches: CompareMatch[] }) {
  if (matches.length === 0) return null;

  return (
    <div>
      <h4 className="mb-2 text-xs font-semibold text-slate-500">Similar in Other Books</h4>
      <div className="space-y-2">
        {matches.map((m) => {
          const location = matchLocation(m);
          return (
            <Link
              key={m.chunk_id != null ? `chunk-${m.chunk_id}` : `book-${m.book_id}`}
              to={m.deep_link || `/books/${m.book_id}`}
              className="block rounded-lg bg-white p-3 text-xs shadow-sm ring-1 ring-slate-100 transition-shadow hover:shadow dark:bg-slate-700 dark:ring-slate-600"
            >
              <div className="flex items-center gap-2">
                <span className="rounded bg-primary-100 px-1.5 py-0.5 font-bold text-primary-700 dark:bg-primary-900/50 dark:text-primary-300">
                  {m.similarity}%
                </span>
                <span className="truncate font-medium text-slate-700 dark:text-slate-300">
                  {m.title}
                </span>
                {location && (
                  <span className="ml-auto shrink-0 text-[10px] font-medium text-slate-400">
                    {location}
                  </span>
                )}
              </div>
              {m.excerpt && (
                <p className="mt-1.5 line-clamp-2 text-slate-500 dark:text-slate-400">{m.excerpt}</p>
              )}
            </Link>
          );
        })}
      </div>
    </div>
  );
}
