import type { Book } from '../../api/types';
import { BookCard } from './BookCard';

interface BookGridProps {
  books: Book[];
  onFavorite?: (id: string, fav: boolean) => void;
}

export function BookGrid({ books, onFavorite }: BookGridProps) {
  // `auto-fill` rather than a column count per breakpoint. The count used to
  // be fixed per breakpoint (5 at lg, 6 at xl, 7 at 2xl), which ignored the
  // sidebar: collapsing it widened every card instead of fitting another one
  // in, and at 2xl a cover was 207px across — small enough that a jacket is a
  // smudge and a long title is three dots. A minimum card width says the one
  // thing that actually matters, and the browser does the arithmetic.
  //
  // Two fixed columns below `sm`: a 220px minimum on a 375px phone would give
  // one book per row.
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-[repeat(auto-fill,minmax(220px,1fr))]">
      {books.map((book) => (
        <BookCard key={book.id} book={book} onFavorite={onFavorite} />
      ))}
    </div>
  );
}
