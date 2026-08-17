import { Link } from 'react-router-dom';
import { BookOpen } from 'lucide-react';
import { useContinueReading } from '../../api/books';
import { BookCover } from './BookCover';
import { ProgressBar } from '../common/ProgressBar';

/**
 * The shelf that `progress_percent` and `last_opened` were always for.
 *
 * Both columns existed in the schema from the start and nothing ever wrote
 * them, so this could not be built. The readers stamp them now
 * (`useReadingProgress`), which makes "recently opened" a real ordering and
 * `in_progress` a status the app maintains rather than one the user sets by
 * hand.
 *
 * Hidden entirely when nothing is in progress — an empty shelf on a fresh
 * library is just noise above the grid.
 */
export function ContinueReading() {
  const { data: books } = useContinueReading(6);

  if (!books?.length) return null;

  return (
    <section aria-labelledby="continue-reading-heading" className="flex flex-col gap-3">
      <h2
        id="continue-reading-heading"
        className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-slate-500"
      >
        <BookOpen size={13} /> Continue reading
      </h2>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {books.map((book) => (
          <Link
            key={book.id}
            to={`/reader/${book.file_type === 'epub' ? 'epub' : 'pdf'}/${book.id}`}
            className="group flex gap-2.5 rounded-lg bg-white p-2 shadow-sm ring-1 ring-slate-200/60 transition-shadow hover:shadow-md dark:bg-slate-800 dark:ring-slate-700"
          >
            <BookCover
              coverUrl={book.cover_url}
              title={book.title}
              fileType={book.file_type}
              className="h-16 w-11 shrink-0 rounded"
            />
            <div className="flex min-w-0 flex-1 flex-col justify-between">
              <p className="line-clamp-2 text-xs font-medium leading-tight text-slate-800 dark:text-slate-200">
                {book.title || 'Untitled'}
              </p>
              <div className="space-y-1">
                <ProgressBar percent={book.progress_percent} />
                <p className="text-[10px] tabular-nums text-slate-400">
                  {Math.round(book.progress_percent)}%
                </p>
              </div>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
