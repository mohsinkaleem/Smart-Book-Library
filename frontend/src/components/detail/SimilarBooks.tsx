import { Link } from 'react-router-dom';
import { Sparkles } from 'lucide-react';
import type { Book } from '../../api/types';
import { BookCover } from '../books/BookCover';

interface SimilarBooksProps {
  books: Book[];
}

export function SimilarBooks({ books }: SimilarBooksProps) {
  if (!books.length) return null;
  return (
    <section className="rounded-xl bg-slate-50 p-6 dark:bg-slate-800/50">
      <h2 className="mb-4 flex items-center gap-2 text-lg font-bold text-slate-900 dark:text-white">
        <Sparkles size={20} className="text-primary-500" />
        You Might Also Like
      </h2>
      <div className="flex gap-4 overflow-x-auto pb-2">
        {books.map((book) => (
          <Link
            key={book.id}
            to={`/books/${book.id}`}
            className="group flex w-36 shrink-0 flex-col gap-2"
          >
            {/* `min-h-0`: same bug as the library grid had. These are flex
                items, so `min-height: auto` floored each cover at its own
                jacket's intrinsic height and the shelf came out ragged. */}
            <BookCover coverUrl={book.cover_url} title={book.title} fileType={book.file_type} className="aspect-[3/4] w-full min-h-0 shrink-0 rounded-lg shadow-md transition-transform group-hover:scale-105" />
            <p className="line-clamp-2 text-xs font-medium text-slate-700 dark:text-slate-300">{book.title}</p>
            {/* Stacked, not side by side: in a 144px column the badge and a
                truncating author name were fighting over the same row, and
                the name won by overlapping the badge. */}
            <div className="flex flex-col items-start gap-1">
              {book.similarity_score !== undefined && (
                <span className="shrink-0 rounded-full bg-primary-100 px-1.5 py-0.5 text-[10px] font-bold text-primary-700 dark:bg-primary-900/50 dark:text-primary-300">{book.similarity_score}% match</span>
              )}
              {book.author_primary && (
                <span className="w-full truncate text-[10px] text-slate-400">{book.author_primary}</span>
              )}
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
