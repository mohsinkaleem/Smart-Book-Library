import { Link } from 'react-router-dom';
import type { Book } from '../../api/types';
import { BookCover } from './BookCover';
import { Rating } from '../common/Rating';
import { Badge } from '../common/Badge';
import { formatBytes } from '../../utils/format';

interface BookRowProps {
  book: Book;
}

const statusLabel: Record<string, string> = {
  not_started: 'Unread',
  in_progress: 'Reading',
  finished: 'Finished',
  abandoned: 'Abandoned',
};

export function BookRow({ book }: BookRowProps) {
  return (
    <Link
      to={`/books/${book.id}`}
      className="flex items-center gap-4 border-b border-slate-100 px-4 py-2.5 transition-colors hover:bg-slate-50 dark:border-slate-700/50 dark:hover:bg-slate-800/50"
    >
      <BookCover coverUrl={book.cover_url} title={book.title} fileType={book.file_type} className="h-10 w-8 shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-slate-900 dark:text-white">{book.title || 'Untitled'}</p>
      </div>
      <div className="hidden w-40 truncate text-sm text-slate-600 dark:text-slate-400 md:block">
        {book.author_primary || 'Unknown'}
      </div>
      <div className="hidden w-36 md:block">
        {book.categories?.[0] && <Badge label={book.categories[0]} className="text-[10px]" />}
      </div>
      <div className="hidden w-16 text-center text-xs text-slate-500 lg:block">{book.publication_year || '—'}</div>
      <div className="hidden w-16 text-center text-xs text-slate-500 lg:block">{book.page_count || '—'}</div>
      <div className="hidden w-16 text-center text-xs font-medium uppercase text-slate-500 lg:block">{book.file_type}</div>
      <div className="w-20"><Rating value={book.user_rating} size={12} readonly /></div>
      <div className="hidden w-20 text-xs text-slate-500 xl:block">{statusLabel[book.reading_status]}</div>
      <div className="hidden w-16 text-right text-xs text-slate-400 xl:block">{formatBytes(book.size)}</div>
    </Link>
  );
}
