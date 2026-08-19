import { Navigate, useLocation, useParams } from 'react-router-dom';
import { useBook } from '../../api/books';
import { Spinner } from '../common/Spinner';
import { ErrorState } from '../common/ErrorBoundary';

/**
 * `/read/:id` — pick the reader from the book's format.
 *
 * Deep links from passage cards are generated server-side, where the reader
 * *route* is not something the API should have to know. The server emits
 * `/read/{id}?page=…` (or `?spine=…&anchor=…`) and this resolves it to
 * `/reader/pdf/:id` or `/reader/epub/:id`.
 *
 * The query string is carried across verbatim: it is the destination, and
 * dropping it would land the reader on page 1 of the right book, which looks
 * enough like working to go unnoticed.
 */
export function ReaderRoute() {
  const { id } = useParams<{ id: string }>();
  const { search } = useLocation();
  const { data: book, isLoading, isError, error, refetch } = useBook(id || '');

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner size={28} />
      </div>
    );
  }

  if (isError) {
    return (
      <ErrorState
        title="Couldn't open that book"
        message={(error as Error)?.message}
        onRetry={() => refetch()}
      />
    );
  }

  if (!book) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-slate-500">Book not found</p>
      </div>
    );
  }

  const reader = book.file_type === 'epub' ? 'epub' : 'pdf';
  return <Navigate to={`/reader/${reader}/${book.id}${search}`} replace />;
}
