import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Check, CopyCheck, FileWarning, X } from 'lucide-react';
import { get, post } from '../api/client';
import { Spinner } from '../components/common/Spinner';
import { BookCover } from '../components/books/BookCover';
import type { Book, DuplicateGroup } from '../api/types';

function formatSize(bytes: number | undefined): string {
  if (!bytes) return '—';
  const mb = bytes / 1024 / 1024;
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`;
}

function CopyCard({
  book,
  canonical,
  onKeep,
  onDismiss,
  busy,
}: {
  book: Book;
  canonical: boolean;
  onKeep: () => void;
  onDismiss: () => void;
  busy: boolean;
}) {
  return (
    <div
      className={`flex gap-3 rounded-lg border p-3 ${
        canonical
          ? 'border-primary-300 bg-primary-50/50 dark:border-primary-700 dark:bg-primary-900/20'
          : 'border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800'
      }`}
    >
      <div className="w-14 shrink-0">
        <BookCover
          coverUrl={book.cover_url}
          title={book.title || book.file_name}
          fileType={book.file_type}
        />
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-start gap-2">
          <Link
            to={`/books/${book.id}`}
            className="min-w-0 flex-1 truncate text-sm font-medium text-slate-800 hover:text-primary-600 dark:text-slate-200"
          >
            {book.title || book.file_name}
          </Link>
          {canonical && (
            <span className="shrink-0 rounded bg-primary-100 px-1.5 py-0.5 text-[10px] font-bold text-primary-700 dark:bg-primary-900/50 dark:text-primary-300">
              KEEPING
            </span>
          )}
        </div>

        <p className="mt-0.5 truncate font-mono text-[11px] text-slate-400">{book.file_path}</p>

        {/* Size, pages and text layer are the fields that actually differ
            between a good scan and a bad one — the rest is identical by
            definition of "duplicate", so showing it would be noise. */}
        <div className="mt-1.5 flex flex-wrap gap-2 text-[11px] text-slate-500 dark:text-slate-400">
          <span>{(book.file_type || '').toUpperCase()}</span>
          <span>· {formatSize(book.size)}</span>
          {book.page_count ? <span>· {book.page_count} pages</span> : null}
          {book.ocr_required ? (
            <span className="flex items-center gap-1 font-medium text-amber-600 dark:text-amber-400">
              <FileWarning size={11} /> no text layer
            </span>
          ) : null}
        </div>

        <div className="mt-2 flex gap-1.5">
          {!canonical && (
            <button
              onClick={onKeep}
              disabled={busy}
              className="flex items-center gap-1 rounded-md bg-primary-600 px-2 py-1 text-[11px] font-medium text-white hover:bg-primary-700 disabled:opacity-50"
            >
              <Check size={11} /> Keep this one
            </button>
          )}
          <button
            onClick={onDismiss}
            disabled={busy}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-slate-500 hover:bg-slate-100 disabled:opacity-50 dark:hover:bg-slate-700"
          >
            <X size={11} /> Not a duplicate
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * Duplicate resolution (Part 5).
 *
 * `catalog/duplicate_detector.py` and the `duplicate_of` column shipped with
 * the pipeline and nothing ever surfaced them — the detector had flagged real
 * duplicates in `epubs/` and no screen said so.
 *
 * Nothing here deletes a file, and the page says so. Choosing which of two
 * files on disk to destroy is the user's call to make in a file manager, and a
 * wrong one is not recoverable from inside this app.
 */
export function DuplicatesPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery<{ groups: DuplicateGroup[]; total: number }>({
    queryKey: ['duplicates'],
    queryFn: () => get('/api/duplicates'),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['duplicates'] });
    qc.invalidateQueries({ queryKey: ['books'] });
    qc.invalidateQueries({ queryKey: ['stats'] });
  };

  const keep = useMutation({
    mutationFn: (bookId: string) => post(`/api/duplicates/${bookId}/keep`, {}),
    onSuccess: invalidate,
  });

  const dismiss = useMutation({
    mutationFn: async (bookId: string) => {
      const res = await fetch(`/api/duplicates/${bookId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Failed to dismiss');
      return bookId;
    },
    onSuccess: invalidate,
  });

  const busy = keep.isPending || dismiss.isPending;
  const groups = data?.groups ?? [];

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner size={28} />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-6">
      <div className="mb-5">
        <h1 className="flex items-center gap-2 text-xl font-bold text-slate-900 dark:text-white">
          <CopyCheck size={20} className="text-primary-500" />
          Duplicates
        </h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          {groups.length === 0
            ? 'No duplicate books detected.'
            : `${groups.length} group${groups.length === 1 ? '' : 's'} the pipeline flagged as the same book.`}
        </p>
        <p className="mt-2 rounded-md bg-slate-100 px-3 py-2 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-400">
          Resolving a duplicate only changes which copy the library shows. No
          file is ever deleted from disk.
        </p>
      </div>

      {groups.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-300 p-10 text-center dark:border-slate-700">
          <CopyCheck size={32} className="mx-auto mb-3 text-slate-300 dark:text-slate-600" />
          <p className="text-sm text-slate-500">Nothing to resolve.</p>
        </div>
      ) : (
        <div className="space-y-5">
          {groups.map((group) => {
            const members = group.canonical
              ? [group.canonical, ...group.copies]
              : group.copies;
            return (
              <section
                key={group.canonical_id}
                className="rounded-xl bg-slate-50 p-3 dark:bg-slate-800/50"
              >
                <h2 className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
                  {group.orphaned
                    ? 'Marked as duplicates of a book no longer in the catalog'
                    : `${members.length} copies`}
                </h2>
                <div className="space-y-2">
                  {members.map((book) => (
                    <CopyCard
                      key={book.id}
                      book={book}
                      canonical={!group.orphaned && book.id === group.canonical?.id}
                      busy={busy}
                      onKeep={() => keep.mutate(book.id)}
                      onDismiss={() => dismiss.mutate(book.id)}
                    />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
