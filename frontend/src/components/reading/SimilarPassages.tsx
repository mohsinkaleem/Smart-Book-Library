import { Link } from 'react-router-dom';
import type { CompareMatch } from '../../api/types';

/**
 * "Similar in Other Books" — the same 25-line block previously lived in both
 * `ReadingView` and `ReaderSidebar`.
 */
export function SimilarPassages({ matches }: { matches: CompareMatch[] }) {
  if (matches.length === 0) return null;

  return (
    <div>
      <h4 className="mb-2 text-xs font-semibold text-slate-500">Similar in Other Books</h4>
      <div className="space-y-2">
        {matches.map((m) => (
          <Link
            key={m.book_id}
            to={`/books/${m.book_id}`}
            className="block rounded-lg bg-white p-3 text-xs shadow-sm ring-1 ring-slate-100 transition-shadow hover:shadow dark:bg-slate-700 dark:ring-slate-600"
          >
            <div className="flex items-center gap-2">
              <span className="rounded bg-primary-100 px-1.5 py-0.5 font-bold text-primary-700 dark:bg-primary-900/50 dark:text-primary-300">
                {m.similarity}%
              </span>
              <span className="truncate font-medium text-slate-700 dark:text-slate-300">
                {m.title}
              </span>
            </div>
            {m.excerpt && (
              <p className="mt-1.5 line-clamp-2 text-slate-500 dark:text-slate-400">{m.excerpt}</p>
            )}
          </Link>
        ))}
      </div>
    </div>
  );
}
