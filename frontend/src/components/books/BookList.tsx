import type { Book } from '../../api/types';
import { BookRow } from './BookRow';

interface BookListProps {
  books: Book[];
}

export function BookList({ books }: BookListProps) {
  return (
    <div className="overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-slate-200/60 dark:bg-slate-800 dark:ring-slate-700">
      {/* Header */}
      <div className="flex items-center gap-4 border-b border-slate-200 bg-slate-50 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:border-slate-700 dark:bg-slate-800/50">
        <div className="w-8 shrink-0" />
        <div className="min-w-0 flex-1">Title</div>
        <div className="hidden w-40 md:block">Author</div>
        <div className="hidden w-36 md:block">Category</div>
        <div className="hidden w-16 text-center lg:block">Year</div>
        <div className="hidden w-16 text-center lg:block">Pages</div>
        <div className="hidden w-16 text-center lg:block">Type</div>
        <div className="w-20">Rating</div>
        <div className="hidden w-20 xl:block">Status</div>
        <div className="hidden w-16 text-right xl:block">Size</div>
      </div>
      {books.map((book) => (
        <BookRow key={book.id} book={book} />
      ))}
    </div>
  );
}
