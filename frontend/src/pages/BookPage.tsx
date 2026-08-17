import { useParams, Link } from 'react-router-dom';
import { ArrowLeft, BookMarked, Copy, FileText } from 'lucide-react';
import { useBook, useSimilarBooks, useUpdateBook } from '../api/books';
import { BookHeader } from '../components/detail/BookHeader';
import { SimilarBooks } from '../components/detail/SimilarBooks';
import { TagEditor } from '../components/detail/TagEditor';
import { Spinner } from '../components/common/Spinner';
import { ErrorState } from '../components/common/ErrorBoundary';


export function BookPage() {
  const { id } = useParams<{ id: string }>();
  const { data: book, isLoading, isError, error, refetch } = useBook(id || '');
  const { data: similar } = useSimilarBooks(id || '');
  const updateBook = useUpdateBook();

  if (isLoading) return <div className="flex h-full items-center justify-center"><Spinner /></div>;
  // A network failure used to render "Book not found", blaming the catalog.
  if (isError) {
    return (
      <ErrorState
        title="Couldn't load this book"
        message={(error as Error)?.message}
        onRetry={() => refetch()}
      />
    );
  }
  if (!book) return <div className="p-8 text-center text-slate-500">Book not found</div>;

  const handleRate = (v: number | null) => updateBook.mutate({ id: book.id, fields: { user_rating: v } });
  const handleFavorite = () => updateBook.mutate({ id: book.id, fields: { favorite: !book.favorite } });
  const handleStatus = (s: string) => updateBook.mutate({ id: book.id, fields: { reading_status: s } });
  const handleTags = (tags: string[]) => updateBook.mutate({ id: book.id, fields: { user_tags: tags } });

  const readerPath = `/reader/${book.file_type === 'epub' ? 'epub' : 'pdf'}/${book.id}`;
  // `reader_position` is only set once a reader has actually saved one.
  const canResume = !!book.reader_position && book.reading_status !== 'finished';

  return (
    <div className="mx-auto max-w-5xl space-y-8 p-6">
      <Link to="/" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700 dark:hover:text-slate-300">
        <ArrowLeft size={16} /> Back to Library
      </Link>

      <BookHeader book={book} onRate={handleRate} onFavorite={handleFavorite} onStatusChange={handleStatus} />

      {/* `duplicate_of` was computed by the pipeline, stored, indexed and
          present in the TS type — and rendered nowhere, so the detection did
          no visible work. */}
      {book.duplicate_of && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg bg-amber-50 px-4 py-2.5 text-sm text-amber-800 dark:bg-amber-900/20 dark:text-amber-200">
          <Copy size={15} className="shrink-0" />
          <span>The pipeline flagged this file as a possible duplicate.</span>
          <Link to={`/books/${book.duplicate_of}`} className="font-medium underline underline-offset-2">
            Open the other copy
          </Link>
        </div>
      )}

      {/* Description */}
      {book.description && (
        <section>
          <h2 className="mb-2 text-sm font-bold uppercase tracking-wider text-slate-500">Description</h2>
          <p className="leading-relaxed text-slate-700 dark:text-slate-300">{book.description}</p>
        </section>
      )}

      {/* Summary */}
      {book.summary && (
        <section>
          <h2 className="mb-2 text-sm font-bold uppercase tracking-wider text-slate-500">Summary</h2>
          <p className="leading-relaxed text-slate-700 dark:text-slate-300">{book.summary}</p>
        </section>
      )}

      {/* Keywords */}
      {book.keywords?.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-bold uppercase tracking-wider text-slate-500">Keywords</h2>
          <div className="flex flex-wrap gap-1.5">
            {book.keywords.map((k) => (
              <span key={k} className="rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-600 dark:bg-slate-700 dark:text-slate-300">{k}</span>
            ))}
          </div>
        </section>
      )}

      {/* Tags */}
      <TagEditor tags={book.user_tags ?? []} onChange={handleTags} disabled={updateBook.isPending} />

      {/* Actions */}
      <div className="flex flex-wrap gap-3">
        {/* Open in full reader (PDF/EPUB) */}
        <Link
          to={readerPath}
          className="flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm hover:bg-primary-700"
        >
          <BookMarked size={16} />
          {canResume
            ? `Resume at ${Math.round(book.progress_percent)}%`
            : 'Read Book'}
        </Link>

        {book.text_excerpt && (
          <Link
            to={`/reading/${book.id}`}
            className="flex items-center gap-2 rounded-lg bg-slate-100 px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-200 dark:bg-slate-700 dark:text-slate-300 dark:hover:bg-slate-600"
          >
            <FileText size={16} /> View Text Excerpt
          </Link>
        )}
      </div>

      {/* Similar Books */}
      {similar && <SimilarBooks books={similar} />}

      {/* Processing Info */}
      <section className="rounded-xl bg-slate-50 p-4 text-sm dark:bg-slate-800/50">
        <h2 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500">Processing Info</h2>
        <div className="grid grid-cols-2 gap-2 text-xs md:grid-cols-3">
          {book.api_sources?.length > 0 && (
            <div><span className="text-slate-400">API Sources:</span> {book.api_sources.join(', ')}</div>
          )}
          <div><span className="text-slate-400">Text:</span> {book.has_text ? `Yes (${book.text_excerpt?.length || 0} chars)` : 'No'}</div>
          <div><span className="text-slate-400">OCR:</span> {book.ocr_required ? 'Required' : 'No'}</div>
          <div><span className="text-slate-400">Embeddings:</span> {book.has_embeddings ? 'Yes' : 'No'}</div>
          <div><span className="text-slate-400">File:</span> {book.file_name}</div>
          {book.processing_errors?.length > 0 && (
            <div className="col-span-full text-red-500">Errors: {book.processing_errors.join('; ')}</div>
          )}
        </div>
      </section>
    </div>
  );
}
