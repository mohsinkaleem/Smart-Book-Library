import { Link } from 'react-router-dom';
import { Heart } from 'lucide-react';
import clsx from 'clsx';
import type { Book } from '../../api/types';
import { BookCover } from './BookCover';
import { Rating } from '../common/Rating';
import { Badge } from '../common/Badge';
import { ProgressBar } from '../common/ProgressBar';
import { SnippetText } from '../search/SnippetText';

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
  // The favourite button used to be nested inside the `<Link>`, kept working
  // by `preventDefault`. That is invalid HTML and confusing for keyboard and
  // screen-reader users, so the link now covers the card via an overlay and
  // the button is a real sibling above it.
  return (
    <article className="group relative flex flex-col overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-slate-200/60 transition-all duration-200 hover:shadow-lg hover:ring-slate-300 dark:bg-slate-800 dark:ring-slate-700 dark:hover:ring-slate-600">
      {/* Cover */}
      <div className="relative aspect-[3/4] w-full">
        <BookCover coverUrl={book.cover_url} title={book.title} fileType={book.file_type} className="h-full w-full" />
        {/* File type badge */}
        <span className="absolute right-1.5 top-1.5 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-bold uppercase text-white">
          {book.file_type}
        </span>
        {/* Status dot */}
        <span className={clsx('absolute left-1.5 top-1.5 h-2.5 w-2.5 rounded-full ring-2 ring-white dark:ring-slate-800', statusDot[book.reading_status])} />
        {/* How far in. Nothing wrote `progress_percent` before the readers did. */}
        {book.progress_percent > 0 && book.reading_status !== 'finished' && (
          <ProgressBar percent={book.progress_percent} className="absolute inset-x-0 bottom-0 rounded-none" />
        )}
      </div>
      {/* Info */}
      <div className="flex flex-1 flex-col gap-1 p-3">
        <h3 className="line-clamp-2 text-sm font-semibold leading-tight text-slate-900 dark:text-white">
          <Link to={`/books/${book.id}`} className="after:absolute after:inset-0 after:content-['']">
            {book.title || 'Untitled'}
          </Link>
        </h3>
        <p className="line-clamp-1 text-xs text-slate-500 dark:text-slate-400">
          {book.author_primary || book.authors?.[0] || 'Unknown'}
        </p>
        {book.snippet && <SnippetText snippet={book.snippet} />}
        {/* `min-w-0` on the badge's cell is what lets it truncate: without it
            a long category name is an unshrinkable flex item, so it wrapped
            and every card in the row ended up a different height. */}
        <div className="mt-auto flex items-center justify-between gap-1.5 pt-1">
          <span className="min-w-0">
            {book.categories?.[0] && <Badge label={book.categories[0]} className="text-[10px]" />}
          </span>
          {book.user_rating != null && (
            <Rating value={book.user_rating} size={12} readonly />
          )}
        </div>
      </div>

      {/* Favourite — above the link overlay, so it stays clickable */}
      <button
        onClick={() => onFavorite?.(book.id, !book.favorite)}
        aria-label={book.favorite ? `Remove ${book.title} from favourites` : `Add ${book.title} to favourites`}
        aria-pressed={book.favorite}
        className={clsx(
          'absolute right-1.5 z-10 rounded-full p-1 transition-all',
          'top-[calc(75%-2rem)]',
          book.favorite
            ? 'bg-red-500 text-white opacity-100'
            : 'bg-black/40 text-white opacity-0 hover:bg-red-500 focus-visible:opacity-100 group-hover:opacity-100',
        )}
      >
        <Heart size={14} className={book.favorite ? 'fill-current' : ''} />
      </button>
    </article>
  );
}
