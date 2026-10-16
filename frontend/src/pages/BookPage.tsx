import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ArrowLeft, BookMarked, Copy, Download, FileText, ScanText } from 'lucide-react';
import clsx from 'clsx';
import { useBook, useSimilarBooks, useUpdateBook } from '../api/books';
import { BookHeader } from '../components/detail/BookHeader';
import { SimilarBooks } from '../components/detail/SimilarBooks';
import { TagEditor } from '../components/detail/TagEditor';
import { Spinner } from '../components/common/Spinner';
import { usePassageIndexStatus } from '../api/passages';
import { ErrorState } from '../components/common/ErrorBoundary';
import { formatBytes, formatDate } from '../utils/format';


export function BookPage() {
  const { id } = useParams<{ id: string }>();
  const { data: book, isLoading, isError, error, refetch } = useBook(id || '');
  const { data: similar } = useSimilarBooks(id || '');
  const { data: passageStatus } = usePassageIndexStatus();
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

  const actions = (
    <div className="flex flex-wrap gap-3">
      {/* Open in full reader (PDF/EPUB) */}
      <Link
        to={readerPath}
        className="flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm hover:bg-primary-700"
      >
        <BookMarked size={16} />
        {canResume ? `Resume at ${Math.round(book.progress_percent)}%` : 'Read Book'}
      </Link>

      {book.text_excerpt && (
        <Link
          to={`/reading/${book.id}`}
          className="flex items-center gap-2 rounded-lg bg-slate-100 px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-200 dark:bg-slate-700 dark:text-slate-300 dark:hover:bg-slate-600"
        >
          <FileText size={16} /> View Text Excerpt
        </Link>
      )}

      {/* Part 5: portable notes. A plain anchor rather than a fetch-and-blob,
          because the endpoint already sets `Content-Disposition` and the
          browser's own download is better than one reimplemented in JS. */}
      <a
        href={`/api/export/markdown?book_id=${encodeURIComponent(book.id)}`}
        download
        className="flex items-center gap-2 rounded-lg bg-slate-100 px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-200 dark:bg-slate-700 dark:text-slate-300 dark:hover:bg-slate-600"
      >
        <Download size={16} /> Export notes
      </a>
    </div>
  );

  return (
    <div className="mx-auto max-w-5xl space-y-8 p-6">
      <Link to="/" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700 dark:hover:text-slate-300">
        <ArrowLeft size={16} /> Back to Library
      </Link>

      <BookHeader
        book={book}
        onRate={handleRate}
        onFavorite={handleFavorite}
        onStatusChange={handleStatus}
        actions={actions}
      />

      {/* The 19 books with no text layer (§1.10).

          Saying so is the whole fix. Without it the reader renders the page
          and every text affordance — selection, highlighting, in-document
          search, passage matching — is silently inert, which reads as a broken
          reader rather than as a scanned book. */}
      {book.ocr_required && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg bg-amber-50 px-4 py-2.5 text-sm text-amber-800 dark:bg-amber-900/20 dark:text-amber-200">
          <ScanText size={15} className="shrink-0" />
          <span>
            <strong className="font-semibold">No text layer.</strong> This is a
            scanned book, so search, highlighting and passage matching will not
            work in it until it is run through OCR.
          </span>
          <code className="rounded bg-amber-100 px-1.5 py-0.5 font-mono text-[11px] dark:bg-amber-900/40">
            python scripts/ocr_books.py --book {book.id}
          </code>
        </div>
      )}

      {/* Indexed for passage search, or not yet. Same principle as the banner
          above: an un-indexed book quietly returns nothing. */}
      {!book.ocr_required && passageStatus?.available === false && (
        <div className="rounded-lg bg-slate-100 px-4 py-2.5 text-sm text-slate-600 dark:bg-slate-800 dark:text-slate-400">
          Passage search is not built yet, so &ldquo;similar passages&rdquo; in the
          reader will be empty. Run{' '}
          <code className="rounded bg-slate-200 px-1.5 py-0.5 font-mono text-[11px] dark:bg-slate-700">
            python scripts/build_passage_index.py
          </code>
          .
        </div>
      )}

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

      <About description={book.description} summary={book.summary} />

      {/* Two chip lists, side by side. Stacked they filled a screen between
          the prose and the actions for no gain — they are the same shape of
          thing and read fine in two columns. */}
      <div className="grid gap-6 md:grid-cols-2">
        {book.keywords?.length > 0 && (
          <section>
            <SectionLabel>Keywords</SectionLabel>
            <div className="flex flex-wrap gap-1.5">
              {book.keywords.map((k) => (
                <span key={k} className="rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-600 dark:bg-slate-700 dark:text-slate-300">{k}</span>
              ))}
            </div>
          </section>
        )}
        <TagEditor tags={book.user_tags ?? []} onChange={handleTags} disabled={updateBook.isPending} />
      </div>

      {/* Similar Books */}
      {similar && <SimilarBooks books={similar} />}

      {/* Everything about the file rather than the book, in one place at the
          foot of the page: format and size moved down here from the header's
          metadata grid, where they sat among the ISBNs. */}
      <section className="rounded-xl bg-slate-50 p-4 text-sm dark:bg-slate-800/50">
        <SectionLabel>File &amp; processing</SectionLabel>
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs md:grid-cols-3">
          <Fact label="Format" value={book.file_type.toUpperCase()} />
          <Fact label="Size" value={formatBytes(book.size)} />
          <Fact label="Added" value={formatDate(book.date_added)} />
          <Fact label="Text" value={book.has_text ? `Yes (${book.text_excerpt?.length || 0} chars)` : 'No'} />
          <Fact label="OCR" value={book.ocr_required ? 'Required' : 'No'} />
          <Fact label="Embeddings" value={book.has_embeddings ? 'Yes' : 'No'} />
          {book.api_sources?.length > 0 && (
            <Fact label="Metadata from" value={book.api_sources.join(', ')} />
          )}
          <div className="col-span-full min-w-0">
            <span className="text-slate-400">File:</span>{' '}
            <span className="break-all">{book.file_name}</span>
          </div>
          {book.processing_errors?.length > 0 && (
            <div className="col-span-full text-red-500">Errors: {book.processing_errors.join('; ')}</div>
          )}
        </div>
      </section>
    </div>
  );
}

/**
 * The publisher's blurb and the locally generated summary, as two tabs over
 * one block of prose.
 *
 * They used to be two stacked sections, each fully expanded, each headed by a
 * near-identical label — roughly a screen of text saying the same thing twice
 * before you reached the keywords. Folding them away behind a disclosure
 * would have been worse: the description is the main thing this page has to
 * say about the book, and a page about a book should not open with it hidden.
 * Tabs keep both one click away, keep where each came from on the label, and
 * cost no scrolling at all.
 */
function About({ description, summary }: { description?: string; summary?: string }) {
  const tabs = [
    description && { key: 'description', label: 'Description', text: description },
    summary && { key: 'summary', label: 'Summary', text: summary },
  ].filter(Boolean) as { key: string; label: string; text: string }[];

  const [active, setActive] = useState(tabs[0]?.key);
  if (!tabs.length) return null;
  const shown = tabs.find((t) => t.key === active) ?? tabs[0];

  return (
    <section>
      {tabs.length === 1 ? (
        <SectionLabel>{shown.label}</SectionLabel>
      ) : (
        <div className="mb-3 flex gap-1 border-b border-slate-200 dark:border-slate-700">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActive(tab.key)}
              aria-current={tab.key === shown.key}
              className={clsx(
                '-mb-px border-b-2 px-3 py-2 text-sm font-semibold transition-colors',
                tab.key === shown.key
                  ? 'border-primary-500 text-slate-900 dark:text-white'
                  : 'border-transparent text-slate-400 hover:text-slate-600 dark:hover:text-slate-300',
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
      )}
      {/* `max-w-prose`: full-width lines at this page width run to about 120
          characters, which is past the point where the eye loses the line. */}
      <p className="max-w-prose leading-relaxed text-slate-700 dark:text-slate-300">
        {shown.text}
      </p>
    </section>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500">{children}</h2>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <span className="text-slate-400">{label}:</span>{' '}
      <span className="text-slate-600 dark:text-slate-300">{value}</span>
    </div>
  );
}
