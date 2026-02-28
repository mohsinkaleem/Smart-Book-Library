import type { Book } from '../../api/types';
import { BookCover } from '../books/BookCover';
import { Rating } from '../common/Rating';
import { Badge } from '../common/Badge';
import { Heart } from 'lucide-react';
import { formatBytes, formatDate } from '../../utils/format';
import clsx from 'clsx';

interface BookHeaderProps {
  book: Book;
  onRate: (v: number | null) => void;
  onFavorite: () => void;
  onStatusChange: (s: string) => void;
}

const statusOptions = [
  { value: 'not_started', label: 'Not Started' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'finished', label: 'Finished' },
  { value: 'abandoned', label: 'Abandoned' },
];

export function BookHeader({ book, onRate, onFavorite, onStatusChange }: BookHeaderProps) {
  return (
    <div className="flex flex-col gap-6 md:flex-row md:gap-8">
      {/* Cover */}
      <div className="shrink-0">
        <BookCover
          coverUrl={book.cover_url}
          title={book.title}
          fileType={book.file_type}
          className="mx-auto h-[360px] w-[240px] shadow-xl md:mx-0"
        />
      </div>

      {/* Details */}
      <div className="flex flex-1 flex-col gap-4">
        <h1 className="text-2xl font-bold leading-tight text-slate-900 dark:text-white">
          {book.title || 'Untitled'}
        </h1>
        <p className="text-lg text-slate-600 dark:text-slate-400">
          by {book.authors?.join(', ') || 'Unknown'}
        </p>

        {/* Actions row */}
        <div className="flex flex-wrap items-center gap-4">
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
            className="rounded-lg border-0 bg-slate-100 px-3 py-1.5 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-200 dark:bg-slate-700 dark:text-slate-300 dark:ring-slate-600"
          >
            {statusOptions.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        {/* Metadata grid */}
        <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm md:grid-cols-3">
          {book.publisher && <MetaItem label="Publisher" value={book.publisher} />}
          {book.publication_year && <MetaItem label="Year" value={String(book.publication_year)} />}
          {book.page_count && <MetaItem label="Pages" value={String(book.page_count)} />}
          <MetaItem label="Type" value={book.file_type.toUpperCase()} />
          <MetaItem label="Size" value={formatBytes(book.size)} />
          {book.language && <MetaItem label="Language" value={book.language} />}
          {book.isbn_13 && <MetaItem label="ISBN-13" value={book.isbn_13} />}
          {book.isbn_10 && <MetaItem label="ISBN-10" value={book.isbn_10} />}
          <MetaItem label="Added" value={formatDate(book.date_added)} />
        </div>

        {/* Categories & themes */}
        {book.categories?.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {book.categories.map((c) => <Badge key={c} label={c} />)}
          </div>
        )}
        {book.themes?.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {book.themes.map((t) => <Badge key={t} label={t} className="bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300" />)}
          </div>
        )}
      </div>
    </div>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-xs font-medium text-slate-400 dark:text-slate-500">{label}</span>
      <p className="font-medium text-slate-700 dark:text-slate-300">{value}</p>
    </div>
  );
}
