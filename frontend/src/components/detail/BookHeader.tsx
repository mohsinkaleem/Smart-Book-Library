import type { ReactNode } from 'react';
import type { Book } from '../../api/types';
import { BookCover } from '../books/BookCover';
import { Rating } from '../common/Rating';
import { Badge } from '../common/Badge';
import { ProgressBar } from '../common/ProgressBar';
import { Heart } from 'lucide-react';
import { formatDate } from '../../utils/format';
import clsx from 'clsx';

interface BookHeaderProps {
  book: Book;
  onRate: (v: number | null) => void;
  onFavorite: () => void;
  onStatusChange: (s: string) => void;
  /** Read / excerpt / export. They belong beside the cover, not below the prose. */
  actions?: ReactNode;
}

const statusOptions = [
  { value: 'not_started', label: 'Not Started' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'finished', label: 'Finished' },
  { value: 'abandoned', label: 'Abandoned' },
];

export function BookHeader({ book, onRate, onFavorite, onStatusChange, actions }: BookHeaderProps) {
  return (
    <div className="flex flex-col gap-6 md:flex-row md:gap-8">
      {/* Cover. `shrink-0` on the column, `min-h-0` on the cover itself: a
          cover with a fixed height is still a flex item whose `min-height:
          auto` floors it at the jacket's own intrinsic height. */}
      <div className="shrink-0">
        <BookCover
          coverUrl={book.cover_url}
          title={book.title}
          fileType={book.file_type}
          className="mx-auto h-[360px] w-[240px] min-h-0 shadow-xl md:mx-0"
        />
      </div>

      {/* Details */}
      <div className="flex min-w-0 flex-1 flex-col gap-4">
        <div>
          <h1 className="text-2xl font-bold leading-tight text-slate-900 dark:text-white">
            {book.title || 'Untitled'}
          </h1>
          {book.subtitle && (
            <p className="mt-1 text-base text-slate-500 dark:text-slate-400">{book.subtitle}</p>
          )}
          <p className="mt-2 text-lg text-slate-600 dark:text-slate-400">
            by {book.authors?.join(', ') || 'Unknown'}
          </p>
        </div>

        {/* Opening the book is the point of this page, so it is the first
            thing under the title. It used to sit below the description, the
            summary, the keywords and the tag editor — a scroll away from the
            only button most visits are here to press. */}
        {actions}

        {/* Your own marks on the book, kept together and away from the
            actions: rating and status are not things you click by accident. */}
        <div className="flex flex-wrap items-center gap-4 border-t border-slate-200 pt-4 dark:border-slate-700">
          <Rating value={book.user_rating} onChange={onRate} size={22} />
          <button
            onClick={onFavorite}
            className={clsx(
              'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors',
              book.favorite ? 'bg-red-50 text-red-600 dark:bg-red-900/30 dark:text-red-400' : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-700 dark:text-slate-300',
            )}
          >
            <Heart size={16} className={book.favorite ? 'fill-current' : ''} />
            {book.favorite ? 'Favorited' : 'Favorite'}
          </button>
          <select
            value={book.reading_status}
            onChange={(e) => onStatusChange(e.target.value)}
            aria-label="Reading status"
            className="rounded-lg border-0 bg-slate-100 px-3 py-1.5 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-200 dark:bg-slate-700 dark:text-slate-300 dark:ring-slate-600"
          >
            {statusOptions.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        {/* Reading progress. Written by the readers, which until now never
            touched `progress_percent` or `last_opened`. */}
        {book.progress_percent > 0 && (
          <div className="flex max-w-sm items-center gap-3">
            <ProgressBar percent={book.progress_percent} className="h-1.5" />
            <span className="shrink-0 text-xs tabular-nums text-slate-500">
              {Math.round(book.progress_percent)}%
            </span>
            {book.last_opened && (
              <span className="shrink-0 text-xs text-slate-400">
                opened {formatDate(book.last_opened)}
              </span>
            )}
          </div>
        )}

        {/* What the book *is*. Size, format and date-added used to sit in this
            same grid, so "768.6 KB" read with the same weight as the ISBN;
            they are facts about the file and now live with the other ones at
            the foot of the page. */}
        <dl className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm sm:grid-cols-3">
          {book.publisher && <MetaItem label="Publisher" value={book.publisher} />}
          {book.publication_year && <MetaItem label="Year" value={String(book.publication_year)} />}
          {book.page_count && <MetaItem label="Pages" value={String(book.page_count)} />}
          {book.language && <MetaItem label="Language" value={book.language} />}
          {book.isbn_13 && <MetaItem label="ISBN-13" value={book.isbn_13} />}
          {book.isbn_10 && <MetaItem label="ISBN-10" value={book.isbn_10} />}
        </dl>

        {/* Categories are the controlled vocabulary; themes are what the
            analyzer read out of the text. They are labelled now because two
            unlabelled rows of pills read as one list of twelve. */}
        {book.categories?.length > 0 && (
          <TagRow label="Categories">
            {book.categories.map((c) => <Badge key={c} label={c} />)}
          </TagRow>
        )}
        {book.themes?.length > 0 && (
          <TagRow label="Themes">
            {book.themes.map((t) => (
              <Badge key={t} label={t} className="bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300" />
            ))}
          </TagRow>
        )}
      </div>
    </div>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-medium text-slate-400 dark:text-slate-500">{label}</dt>
      <dd className="truncate font-medium text-slate-700 dark:text-slate-300" title={value}>{value}</dd>
    </div>
  );
}

function TagRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
      <span className="text-xs font-medium uppercase tracking-wide text-slate-400 dark:text-slate-500">
        {label}
      </span>
      {children}
    </div>
  );
}
