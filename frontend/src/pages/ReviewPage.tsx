/**
 * Review queue — records the verification gate could not confirm.
 *
 * 11% of the catalog was wrong with no way to see it and no way to fix one
 * A correction saved here is pinned as
 * source "user", confidence 1.0, so no future pipeline run overwrites it.
 */
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useReviewQueue, usePinField, useResolveReview, type ReviewBook } from '../api/review';
import { Spinner } from '../components/common/Spinner';
import { EmptyState } from '../components/common/EmptyState';

function scoreLabel(score: number | null): { text: string; className: string } {
  if (score === null || score === undefined) {
    return { text: 'no match', className: 'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200' };
  }
  if (score >= 0.75) return { text: score.toFixed(2), className: 'bg-emerald-100 text-emerald-800' };
  if (score >= 0.45) return { text: score.toFixed(2), className: 'bg-amber-100 text-amber-800' };
  return { text: score.toFixed(2), className: 'bg-rose-100 text-rose-800' };
}

function ReviewCard({ book }: { book: ReviewBook }) {
  const [title, setTitle] = useState(book.title ?? '');
  const [authors, setAuthors] = useState((book.authors ?? []).join(', '));
  const pin = usePinField();
  const resolve = useResolveReview();
  const badge = scoreLabel(book.match_score);
  const titleSource = book.field_sources?.title?.source ?? 'none';

  const saveCorrections = async () => {
    if (title.trim() && title !== book.title) {
      await pin.mutateAsync({ id: book.id, field: 'title', value: title.trim() });
    }
    const parsed = authors.split(',').map((a) => a.trim()).filter(Boolean);
    if (parsed.join(', ') !== (book.authors ?? []).join(', ')) {
      await pin.mutateAsync({ id: book.id, field: 'authors', value: parsed });
    }
    await resolve.mutateAsync({ id: book.id, resolution: 'corrected' });
  };

  const busy = pin.isPending || resolve.isPending;

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link to={`/books/${book.id}`} className="truncate font-medium text-slate-900 hover:underline dark:text-white">
            {book.file_name}
          </Link>
          <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
            title from <span className="font-mono">{titleSource}</span>
            {book.file_type ? ` · ${book.file_type}` : ''}
          </p>
        </div>
        <span className={`shrink-0 rounded px-2 py-0.5 text-xs font-medium ${badge.className}`}>
          {badge.text}
        </span>
      </div>

      <ul className="mb-3 space-y-1">
        {(book.review_reasons ?? []).map((reason) => (
          <li key={reason} className="text-sm text-amber-700 dark:text-amber-400">↳ {reason}</li>
        ))}
      </ul>

      {(book.rejected_candidates ?? []).length > 0 && (
        <details className="mb-3 text-xs text-slate-600 dark:text-slate-400">
          <summary className="cursor-pointer">
            {book.rejected_candidates.length} rejected candidate(s)
          </summary>
          <ul className="mt-1 space-y-0.5 pl-4">
            {book.rejected_candidates.map((c, i) => (
              <li key={i}>
                <span className="font-mono">{c.score.toFixed(2)}</span> {c.provider}: {c.title}
                {c.authors?.length ? ` — ${c.authors.join(', ')}` : ''}
              </li>
            ))}
          </ul>
        </details>
      )}

      <div className="grid gap-2 sm:grid-cols-2">
        <label className="text-xs text-slate-500 dark:text-slate-400">
          Title
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm text-slate-900 dark:border-slate-600 dark:bg-slate-900 dark:text-white"
          />
        </label>
        <label className="text-xs text-slate-500 dark:text-slate-400">
          Authors (comma separated)
          <input
            value={authors}
            onChange={(e) => setAuthors(e.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm text-slate-900 dark:border-slate-600 dark:bg-slate-900 dark:text-white"
          />
        </label>
      </div>

      <div className="mt-3 flex gap-2">
        <button
          onClick={saveCorrections}
          disabled={busy}
          className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          Save &amp; pin
        </button>
        <button
          onClick={() => resolve.mutate({ id: book.id, resolution: 'confirmed' })}
          disabled={busy}
          className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-700"
        >
          Looks right
        </button>
      </div>
    </div>
  );
}

export function ReviewPage() {
  const [page, setPage] = useState(1);
  const { data, isLoading, error } = useReviewQueue(page);

  if (isLoading) return <div className="p-8"><Spinner /></div>;
  if (error) return <div className="p-8 text-rose-600">Failed to load the review queue.</div>;
  if (!data || data.total === 0) {
    return (
      <div className="p-8">
        <EmptyState message="Nothing to review — every record was either verified against a provider or left untouched." />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl p-6">
      <header className="mb-4">
        <h1 className="text-xl font-bold text-slate-900 dark:text-white">Review queue</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          {data.total} record(s) the verification gate could not confirm. Corrections are pinned
          and survive future pipeline runs.
        </p>
      </header>

      <div className="space-y-3">
        {data.items.map((book) => (
          <ReviewCard key={book.id} book={book} />
        ))}
      </div>

      {data.pages > 1 && (
        <div className="mt-4 flex items-center justify-between text-sm">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="rounded border border-slate-300 px-3 py-1 disabled:opacity-40 dark:border-slate-600"
          >
            Previous
          </button>
          <span className="text-slate-500 dark:text-slate-400">Page {page} of {data.pages}</span>
          <button
            onClick={() => setPage((p) => Math.min(data.pages, p + 1))}
            disabled={page >= data.pages}
            className="rounded border border-slate-300 px-3 py-1 disabled:opacity-40 dark:border-slate-600"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
