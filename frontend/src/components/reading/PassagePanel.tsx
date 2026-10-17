import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { BookOpen, CornerDownRight, Layers, Search, Sparkles } from 'lucide-react';
import { useSimilarPassages, usePassageIndexStatus } from '../../api/passages';
import { MIN_COMPARE_CHARS } from './selection';
import { passageLocation, SIMILARITY_HINT } from './passageLocation';
import { Spinner } from '../common/Spinner';
import type { Passage } from '../../api/types';

interface PassagePanelProps {
  bookId: string;
  selectedText: string;
  /** Jump to a passage inside the book currently open. */
  onNavigate: (passage: Passage) => void;
}

type Tab = 'book' | 'catalog';

const TABS: { id: Tab; label: string; icon: typeof BookOpen }[] = [
  { id: 'book', label: 'This book', icon: Layers },
  { id: 'catalog', label: 'Library', icon: Search },
];

/**
 * How a passage was found.
 *
 * Worth showing rather than hiding behind one number: a hit both systems
 * proposed is the strongest kind there is, and a keyword-only hit is a
 * different claim — it shares the words, not necessarily the argument.
 */
function MatchBadge({ matched }: { matched: Passage['matched'] }) {
  const styles: Record<Passage['matched'], string> = {
    both: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
    semantic: 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300',
    keyword: 'bg-slate-200 text-slate-600 dark:bg-slate-600 dark:text-slate-300',
  };
  const labels: Record<Passage['matched'], string> = {
    both: 'meaning + words',
    semantic: 'meaning',
    keyword: 'words',
  };
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${styles[matched]}`}>
      {labels[matched]}
    </span>
  );
}

function PassageCard({
  passage,
  inThisBook,
  onNavigate,
}: {
  passage: Passage;
  inThisBook: boolean;
  onNavigate: (p: Passage) => void;
}) {
  const location = passageLocation(passage);

  const body = (
    <>
      <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
        <span
          title={SIMILARITY_HINT}
          className="rounded bg-primary-100 px-1.5 py-0.5 text-[10px] font-bold text-primary-700 dark:bg-primary-900/50 dark:text-primary-300"
        >
          {Math.round(passage.score * 100)}%
        </span>
        <MatchBadge matched={passage.matched} />
        {location && (
          <span className="text-[10px] font-medium text-slate-400">{location}</span>
        )}
      </div>

      {!inThisBook && (
        <p className="mb-1 truncate text-xs font-semibold text-slate-700 dark:text-slate-300">
          {passage.title}
          {passage.author ? (
            <span className="font-normal text-slate-400"> · {passage.author}</span>
          ) : null}
        </p>
      )}

      {passage.section && (
        <p className="mb-1 truncate text-[10px] uppercase tracking-wide text-slate-400">
          {passage.section}
        </p>
      )}

      <p className="line-clamp-4 text-xs leading-relaxed text-slate-600 dark:text-slate-300">
        {passage.text}
      </p>
    </>
  );

  const shell =
    'block w-full rounded-lg bg-white p-3 text-left shadow-sm ring-1 ring-slate-100 transition-shadow hover:shadow dark:bg-slate-700 dark:ring-slate-600';

  // Inside the current book, jumping is a reader action rather than a
  // navigation — a Link would remount the reader and lose the rendered pages.
  return inThisBook ? (
    <button type="button" onClick={() => onNavigate(passage)} className={shell}>
      {body}
      <span className="mt-2 flex items-center gap-1 text-[10px] font-medium text-primary-600 dark:text-primary-400">
        <CornerDownRight size={11} /> Jump to {location || 'passage'}
      </span>
    </button>
  ) : (
    <Link to={passage.deep_link} className={shell}>
      {body}
      <span className="mt-2 flex items-center gap-1 text-[10px] font-medium text-primary-600 dark:text-primary-400">
        <BookOpen size={11} /> Open at {location || 'this passage'}
      </span>
    </Link>
  );
}

/**
 * "Elsewhere in this book" and real cross-book passage matches (§1.9.1, §1.9.2).
 *
 * The in-book tab is the feature the passage index exists for and the one that
 * was structurally impossible before it: the old compare endpoint skipped the
 * current book outright, and there was one vector per book to match against
 * anyway. It is also the cheapest query in the system — one contiguous slice
 * of the matrix, measured at 0.008 ms.
 */
export function PassagePanel({ bookId, selectedText, onNavigate }: PassagePanelProps) {
  const [tab, setTab] = useState<Tab>('book');
  // Results carry the selection they answer. Clearing them synchronously at the
  // top of the effect would be a cascading render for something a comparison
  // already tells us — and would blank the panel for a frame on every reselect.
  const [results, setResults] =
    useState<{ key: string; book: Passage[]; catalog: Passage[] }>({
      key: '', book: [], catalog: [],
    });
  const { data: status } = usePassageIndexStatus();
  const { mutate: search, isPending } = useSimilarPassages();

  const enabled = status?.available && selectedText.length >= MIN_COMPARE_CHARS;

  useEffect(() => {
    if (!enabled) return;
    for (const scope of ['book', 'catalog'] as Tab[]) {
      search(
        { text: selectedText, book_id: bookId, scope, limit: 6 },
        {
          onSuccess: (data) =>
            setResults((prev) => ({
              // A reply for a selection the reader has moved on from is
              // discarded rather than merged into the current one.
              ...(prev.key === selectedText ? prev : { key: selectedText, book: [], catalog: [] }),
              key: selectedText,
              [scope]: data.results,
            })),
        },
      );
    }
  }, [selectedText, bookId, enabled, search]);

  // An unbuilt index and "no matches" look identical in an empty list and mean
  // entirely different things. Say which.
  if (status && !status.available) {
    return (
      <div className="rounded-lg bg-slate-100 p-3 text-xs text-slate-500 dark:bg-slate-700/50 dark:text-slate-400">
        <p className="mb-1 font-medium text-slate-600 dark:text-slate-300">
          Passage search is not available
        </p>
        <p>
          The passage index has not been built. Run{' '}
          <code className="rounded bg-slate-200 px-1 py-0.5 font-mono text-[10px] dark:bg-slate-600">
            python scripts/build_passage_index.py
          </code>{' '}
          to enable it.
        </p>
      </div>
    );
  }

  if (!selectedText) return null;

  const current = results.key === selectedText ? results[tab] : [];
  const indexedBooks = status?.book_count ?? 0;

  return (
    <div>
      <div className="mb-2 flex items-center gap-1">
        <Sparkles size={12} className="text-primary-500" />
        <h4 className="text-xs font-semibold text-slate-500">Similar passages</h4>
        <div className="ml-auto flex gap-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors ${
                tab === t.id
                  ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
                  : 'text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'
              }`}
            >
              <t.icon size={10} /> {t.label}
            </button>
          ))}
        </div>
      </div>

      {isPending && current.length === 0 ? (
        <div className="flex justify-center py-4">
          <Spinner size={18} />
        </div>
      ) : current.length === 0 ? (
        <p className="rounded-lg bg-slate-100 p-3 text-xs text-slate-500 dark:bg-slate-700/50 dark:text-slate-400">
          {tab === 'book'
            ? 'Nothing else in this book resembles the selection closely enough.'
            : `No close match across the ${indexedBooks} indexed book${
                indexedBooks === 1 ? '' : 's'
              }.`}
        </p>
      ) : (
        <div className="space-y-2">
          {current.map((passage) => (
            <PassageCard
              key={passage.chunk_id}
              passage={passage}
              inThisBook={tab === 'book'}
              onNavigate={onNavigate}
            />
          ))}
        </div>
      )}
    </div>
  );
}
