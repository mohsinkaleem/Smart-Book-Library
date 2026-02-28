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
            <BookCover coverUrl={book.cover_url} title={book.title} fileType={book.file_type} className="aspect-[3/4] w-full rounded-lg shadow-md transition-transform group-hover:scale-105" />
            <p className="line-clamp-2 text-xs font-medium text-slate-700 dark:text-slate-300">{book.title}</p>
            <div className="flex items-center gap-1.5">
              {book.similarity_score !== undefined && (
                <span className="rounded-full bg-primary-100 px-1.5 py-0.5 text-[10px] font-bold text-primary-700 dark:bg-primary-900/50 dark:text-primary-300">{book.similarity_score}% match</span>
              )}
              {book.author_primary && (
                <span className="truncate text-[10px] text-slate-400">{book.author_primary}</span>
              )}
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
