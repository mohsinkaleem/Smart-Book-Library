import type { Book } from '../../api/types';
import { BookCard } from './BookCard';

interface BookGridProps {
  books: Book[];
  onFavorite?: (id: string, fav: boolean) => void;
}

export function BookGrid({ books, onFavorite }: BookGridProps) {
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 2xl:grid-cols-7">
      {books.map((book) => (
        <BookCard key={book.id} book={book} onFavorite={onFavorite} />
      ))}
    </div>
  );
}
