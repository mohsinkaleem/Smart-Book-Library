import { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Quote, Search, Sparkles } from 'lucide-react';
import {
  usePassageIndexStatus,
  usePassageSearch,
  type PassageMode,
} from '../api/passages';
import { passageLocation } from '../components/reading/PassagePanel';
import { Spinner } from '../components/common/Spinner';
import type { Passage } from '../api/types';

const MODES: { id: PassageMode; label: string; hint: string }[] = [
  { id: 'hybrid', label: 'Hybrid', hint: 'Meaning and exact words, fused' },
  { id: 'semantic', label: 'Meaning', hint: 'Paraphrase and related ideas' },
  { id: 'keyword', label: 'Exact words', hint: 'Every mention of a term' },
];

function ResultRow({ passage }: { passage: Passage }) {
  const location = passageLocation(passage);
  return (
    <Link
      to={passage.deep_link}
      className="block rounded-lg border border-slate-200 bg-white p-4 transition-shadow hover:shadow dark:border-slate-700 dark:bg-slate-800"
    >
      <div className="mb-1.5 flex flex-wrap items-baseline gap-2">
        <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">
          {passage.title}
        </span>
        {passage.author && (
          <span className="text-xs text-slate-400">{passage.author}</span>
        )}
        {passage.year ? <span className="text-xs text-slate-400">· {passage.year}</span> : null}
        <span className="ml-auto flex items-center gap-2 text-xs text-slate-400">
          {location && <span>{location}</span>}
          {passage.score > 0 && (
            <span className="rounded bg-primary-100 px-1.5 py-0.5 font-bold text-primary-700 dark:bg-primary-900/50 dark:text-primary-300">
              {Math.round(passage.score * 100)}%
            </span>
          )}
        </span>
      </div>

      {passage.section && (
        <p className="mb-1.5 truncate text-[11px] uppercase tracking-wide text-slate-400">
          {passage.section}
        </p>
      )}

      <p className="flex gap-2 text-sm leading-relaxed text-slate-600 dark:text-slate-300">
        <Quote size={14} className="mt-1 shrink-0 text-slate-300 dark:text-slate-600" />
        <span className="line-clamp-4">{passage.text}</span>
      </p>
    </Link>
  );
}

/**
 * Library-wide passage search (§1.9.5).
 *
 * "Every mention of X across all 618 books", which the chunk index gives as a
 * by-product of the same build. The three modes are not cosmetic: `keyword`
 * skips the semantic relevance floor entirely, because an exact term match *is*
 * the answer there and the floor would suppress precisely the rare-word hits
 * being looked for.
 */
export function PassageSearchPage() {
  const [params, setParams] = useSearchParams();
  const [draft, setDraft] = useState(params.get('q') || '');
  const [mode, setMode] = useState<PassageMode>(
    (params.get('mode') as PassageMode) || 'hybrid',
  );
  const [results, setResults] = useState<Passage[]>([]);
  const [searched, setSearched] = useState(false);

  const { data: status } = usePassageIndexStatus();
  const { mutate: search, isPending } = usePassageSearch();

  const run = useCallback(
    (query: string, searchMode: PassageMode) => {
      if (!query.trim()) return;
      setSearched(true);
      search(
        { query, mode: searchMode, limit: 30 },
        { onSuccess: (data) => setResults(data.results) },
      );
    },
    [search],
  );

  // Run whatever is in the URL on arrival, so a passage search is linkable.
  useEffect(() => {
    const q = params.get('q');
    if (q && status?.available) run(q, mode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status?.available]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setParams({ q: draft, mode }, { replace: true });
    run(draft, mode);
  };

  const chooseMode = (next: PassageMode) => {
    setMode(next);
    if (draft.trim()) {
      setParams({ q: draft, mode: next }, { replace: true });
      run(draft, next);
    }
  };

  if (status && !status.available) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-16 text-center">
        <Sparkles size={32} className="mx-auto mb-3 text-slate-300 dark:text-slate-600" />
        <h1 className="mb-2 text-lg font-bold text-slate-700 dark:text-slate-300">
          Passage search is not available
        </h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          The passage index has not been built yet. Run{' '}
          <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs dark:bg-slate-800">
            python scripts/build_passage_index.py
          </code>{' '}
          to index your library&rsquo;s full text.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-6">
      <h1 className="flex items-center gap-2 text-xl font-bold text-slate-900 dark:text-white">
        <Sparkles size={20} className="text-primary-500" />
        Passage search
      </h1>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
        Search inside the text of{' '}
        {status?.book_count ? `${status.book_count} indexed books` : 'your library'}
        {status?.count ? ` · ${status.count.toLocaleString()} passages` : ''}.
      </p>

      <form onSubmit={submit} className="mt-4 flex gap-2">
        <div className="relative flex-1">
          <Search
            size={15}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
          />
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="A phrase, an idea, or an exact term…"
            className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-9 pr-3 text-sm text-slate-700 placeholder:text-slate-400 focus:border-primary-400 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
          />
        </div>
        <button
          type="submit"
          disabled={!draft.trim() || isPending}
          className="rounded-lg bg-primary-600 px-4 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-40"
        >
          Search
        </button>
      </form>

      <div className="mt-2 flex flex-wrap gap-1.5">
        {MODES.map((m) => (
          <button
            key={m.id}
            onClick={() => chooseMode(m.id)}
            title={m.hint}
            className={`rounded-md px-2 py-1 text-xs font-medium transition-colors ${
              mode === m.id
                ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
                : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800'
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>

      <div className="mt-5">
        {isPending ? (
          <div className="flex justify-center py-10">
            <Spinner size={26} />
          </div>
        ) : results.length > 0 ? (
          <>
            <p className="mb-2 text-xs text-slate-400">
              {results.length} passage{results.length === 1 ? '' : 's'}
            </p>
            <div className="space-y-2.5">
              {results.map((passage) => (
                <ResultRow key={passage.chunk_id} passage={passage} />
              ))}
            </div>
          </>
        ) : searched ? (
          <div className="rounded-lg border border-dashed border-slate-300 p-10 text-center dark:border-slate-700">
            <p className="text-sm text-slate-500">No passages matched.</p>
            <p className="mt-1 text-xs text-slate-400">
              {mode === 'hybrid' || mode === 'semantic'
                ? 'Nothing in the indexed books is close enough in meaning. Try “Exact words” for a literal term.'
                : 'That term does not appear in the indexed text.'}
            </p>
          </div>
        ) : null}
      </div>
    </div>
  );
}
