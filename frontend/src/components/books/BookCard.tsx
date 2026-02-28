import { Link } from 'react-router-dom';
import { Heart } from 'lucide-react';
import clsx from 'clsx';
import type { Book } from '../../api/types';
import { BookCover } from './BookCover';
import { Rating } from '../common/Rating';
import { Badge } from '../common/Badge';

interface BookCardProps {
  book: Book;
  onFavorite?: (id: string, fav: boolean) => void;
}

const statusDot: Record<string, string> = {
  not_started: 'bg-slate-400',
  in_progress: 'bg-blue-500',
  finished: 'bg-emerald-500',
  abandoned: 'bg-red-400',
};

export function BookCard({ book, onFavorite }: BookCardProps) {
  return (
    <Link
      to={`/books/${book.id}`}
      className="group relative flex flex-col overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-slate-200/60 transition-all duration-200 hover:shadow-lg hover:ring-slate-300 dark:bg-slate-800 dark:ring-slate-700 dark:hover:ring-slate-600"
    >
      {/* Cover */}
      <div className="relative aspect-[3/4] w-full">
        <BookCover coverUrl={book.cover_url} title={book.title} fileType={book.file_type} className="h-full w-full" />
        {/* File type badge */}
        <span className="absolute right-1.5 top-1.5 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-bold uppercase text-white">
          {book.file_type}
        </span>
        {/* Status dot */}
        <span className={clsx('absolute left-1.5 top-1.5 h-2.5 w-2.5 rounded-full ring-2 ring-white dark:ring-slate-800', statusDot[book.reading_status])} />
        {/* Favorite */}
        <button
          onClick={(e) => { e.preventDefault(); e.stopPropagation(); onFavorite?.(book.id, !book.favorite); }}
          className={clsx(
            'absolute right-1.5 bottom-1.5 rounded-full p-1 opacity-0 transition-all group-hover:opacity-100',
            book.favorite ? 'bg-red-500 text-white opacity-100' : 'bg-black/40 text-white hover:bg-red-500',
          )}
        >
          <Heart size={14} className={book.favorite ? 'fill-current' : ''} />
        </button>
      </div>
      {/* Info */}
      <div className="flex flex-1 flex-col gap-1 p-3">
        <h3 className="line-clamp-2 text-sm font-semibold leading-tight text-slate-900 dark:text-white">
          {book.title || 'Untitled'}
        </h3>
        <p className="line-clamp-1 text-xs text-slate-500 dark:text-slate-400">
          {book.author_primary || book.authors?.[0] || 'Unknown'}
        </p>
        <div className="mt-auto flex items-center justify-between pt-1">
          {book.categories?.[0] && <Badge label={book.categories[0]} className="text-[10px]" />}
          <Rating value={book.user_rating} size={12} readonly />
        </div>
      </div>
    </Link>
  );
}
