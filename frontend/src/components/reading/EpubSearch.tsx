import { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronUp, Search, X } from 'lucide-react';
import type { EpubRendition } from './EpubReader';

interface EpubHit {
  cfi: string;
  excerpt: string;
}

/** epub.js's per-section search result. */
interface RawResult {
  cfi: string;
  excerpt: string;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type SpineItem = any;

const MAX_HITS = 300;

/**
 * Search every section of the spine.
 *
 * `book.search()` does not exist on epub.js's Book — searching is per *spine
 * item*, and each item has to be `load`ed before `find` will see its text and
 * `unload`ed afterwards or the whole book ends up resident. Walking the spine
 * is what "search the book" actually means here.
 */
async function searchSpine(
  rendition: EpubRendition,
  needle: string,
  onProgress: (done: number, total: number) => void,
  cancelled: () => boolean,
): Promise<EpubHit[]> {
  const book = rendition.book;
  if (!book) return [];
  await book.ready;

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const spine = (book as any).spine;
  const items: SpineItem[] = spine?.spineItems ?? [];
  const hits: EpubHit[] = [];

  for (let i = 0; i < items.length; i++) {
    if (cancelled()) return hits;
    const item = items[i];
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      await item.load((book as any).load.bind(book));
      const found: RawResult[] = item.find(needle) ?? [];
      for (const result of found) {
        hits.push({ cfi: result.cfi, excerpt: (result.excerpt || '').trim() });
        if (hits.length >= MAX_HITS) { item.unload(); return hits; }
      }
    } catch {
      /* a section that will not load is skipped, not fatal */
    } finally {
      try { item.unload(); } catch { /* never loaded */ }
    }
    onProgress(i + 1, items.length);
    // Yield so a long book does not freeze the frame.
    await new Promise((r) => setTimeout(r, 0));
  }
  return hits;
}

interface EpubSearchProps {
  rendition: EpubRendition | null;
  onNavigate: (cfi: string) => void;
  onClose: () => void;
}

export function EpubSearch({ rendition, onNavigate, onClose }: EpubSearchProps) {
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<EpubHit[]>([]);
  const [active, setActive] = useState(0);
  const [searching, setSearching] = useState(false);
  const [progress, setProgress] = useState<[number, number]>([0, 0]);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  useEffect(() => {
    const needle = query.trim();
    if (!rendition || needle.length < 2) {
      setHits([]);
      setSearching(false);
      return;
    }

    // Captured by the closures below, so a scan whose query has since
    // changed drops its results instead of overwriting newer ones.
    let cancelled = false;

    const timer = setTimeout(() => {
      setSearching(true);
      setProgress([0, 0]);
      searchSpine(
        rendition, needle,
        (done, total) => { if (!cancelled) setProgress([done, total]); },
        () => cancelled,
      )
        .then((found) => {
          if (cancelled) return;
          setHits(found);
          setActive(0);
          if (found.length) onNavigate(found[0].cfi);
        })
        .finally(() => { if (!cancelled) setSearching(false); });
    }, 400);

    return () => { clearTimeout(timer); cancelled = true; };
  // `onNavigate` is a stable callback from the reader.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, rendition]);

  const step = useCallback((delta: number) => {
    if (!hits.length) return;
    const next = (active + delta + hits.length) % hits.length;
    setActive(next);
    onNavigate(hits[next].cfi);
  }, [active, hits, onNavigate]);

  return (
    <div className="border-b border-slate-200 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-800">
      <div className="flex items-center gap-2">
        <Search size={14} className="shrink-0 text-slate-400" />
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') { e.preventDefault(); step(e.shiftKey ? -1 : 1); }
            if (e.key === 'Escape') { e.preventDefault(); onClose(); }
          }}
          placeholder="Search in this book…"
          aria-label="Search in this book"
          className="min-w-0 flex-1 rounded border border-slate-200 bg-transparent px-2 py-1 text-sm dark:border-slate-600"
        />
        <span className="shrink-0 tabular-nums text-xs text-slate-400">
          {searching
            ? `scanning ${progress[0]}/${progress[1]}`
            : hits.length
              ? `${active + 1} / ${hits.length}${hits.length >= MAX_HITS ? '+' : ''}`
              : query.trim().length >= 2 ? 'no matches' : ''}
        </span>
        <button onClick={() => step(-1)} disabled={!hits.length} aria-label="Previous match"
                className="rounded p-1 text-slate-500 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-slate-700">
          <ChevronUp size={14} />
        </button>
        <button onClick={() => step(1)} disabled={!hits.length} aria-label="Next match"
                className="rounded p-1 text-slate-500 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-slate-700">
          <ChevronDown size={14} />
        </button>
        <button onClick={onClose} aria-label="Close search"
                className="rounded p-1 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700">
          <X size={14} />
        </button>
      </div>

      {hits.length > 0 && (
        <ul className="mt-2 max-h-40 overflow-y-auto rounded border border-slate-100 dark:border-slate-700">
          {hits.map((hit, i) => (
            <li key={`${hit.cfi}-${i}`}>
              <button
                onClick={() => { setActive(i); onNavigate(hit.cfi); }}
                className={`block w-full px-2 py-1.5 text-left text-xs transition-colors ${
                  i === active
                    ? 'bg-primary-50 dark:bg-primary-900/30'
                    : 'hover:bg-slate-50 dark:hover:bg-slate-700/50'
                }`}
              >
                <span className="line-clamp-2 text-slate-600 dark:text-slate-300">{hit.excerpt}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
