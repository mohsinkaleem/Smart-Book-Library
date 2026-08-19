import { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronUp, Search, X } from 'lucide-react';
import type { PDFDocumentProxy } from 'pdfjs-dist';

export interface SearchHit {
  page: number;
  /** The matched text with a little either side, for the results list. */
  snippet: string;
  /** Offset of the match within `snippet`, so the list can bold it. */
  offset: number;
}

/** Characters of context shown either side of a hit. */
const CONTEXT = 45;
/** Pages scanned before yielding, so a 600-page search never blocks paint. */
const PAGE_BATCH = 10;
const MAX_HITS = 300;

/**
 * Scan every page's text layer for `needle`.
 *
 * `getTextContent` returns positioned runs, not a paragraph — joining them
 * with a space is what makes a phrase that spans two runs findable at all,
 * and it is why the offsets here locate a hit *within the joined page text*
 * rather than in the original PDF content stream.
 */
async function scan(
  doc: PDFDocumentProxy,
  needle: string,
  onProgress: (page: number) => void,
  cancelled: () => boolean,
): Promise<SearchHit[]> {
  const query = needle.toLowerCase();
  const hits: SearchHit[] = [];

  for (let page = 1; page <= doc.numPages; page++) {
    if (cancelled()) return hits;

    let text = '';
    try {
      const content = await doc.getPage(page).then((p) => p.getTextContent());
      text = content.items
        .map((item) => ('str' in item ? item.str : ''))
        .join(' ')
        .replace(/\s+/g, ' ');
    } catch {
      continue;   // an unreadable page is not a reason to abandon the search
    }

    const haystack = text.toLowerCase();
    let from = 0;
    for (;;) {
      const at = haystack.indexOf(query, from);
      if (at === -1) break;
      const start = Math.max(0, at - CONTEXT);
      hits.push({
        page,
        snippet:
          (start > 0 ? '…' : '') +
          text.slice(start, at + query.length + CONTEXT) +
          (at + query.length + CONTEXT < text.length ? '…' : ''),
        offset: at - start + (start > 0 ? 1 : 0),
      });
      if (hits.length >= MAX_HITS) return hits;
      from = at + query.length;
    }

    if (page % PAGE_BATCH === 0) {
      onProgress(page);
      await new Promise((r) => setTimeout(r, 0));
    }
  }
  return hits;
}

interface PdfSearchProps {
  doc: PDFDocumentProxy | null;
  onNavigate: (page: number) => void;
  /** The active needle, lifted so the page renderer can highlight matches. */
  onQueryChange: (query: string) => void;
  onClose: () => void;
}

/**
 * In-document search.
 *
 * Neither reader had any — on a 600-page technical PDF that is table stakes,
 * and its absence is why the only way to find a remembered passage was to
 * scroll for it.
 */
export function PdfSearch({ doc, onNavigate, onQueryChange, onClose }: PdfSearchProps) {
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [active, setActive] = useState(0);
  const [searching, setSearching] = useState(false);
  const [scanned, setScanned] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  // Debounced so typing "constitution" is one scan, not twelve.
  useEffect(() => {
    const needle = query.trim();
    onQueryChange(needle);
    if (!doc || needle.length < 2) {
      setHits([]);
      setSearching(false);
      return;
    }

    // Captured by the closures below, so a scan whose query has since
    // changed drops its results instead of overwriting newer ones.
    let cancelled = false;

    const timer = setTimeout(() => {
      setSearching(true);
      setScanned(0);
      scan(doc, needle, (page) => { if (!cancelled) setScanned(page); }, () => cancelled)
        .then((found) => {
          if (cancelled) return;
          setHits(found);
          setActive(0);
          if (found.length) onNavigate(found[0].page);
        })
        .finally(() => { if (!cancelled) setSearching(false); });
    }, 350);

    return () => {
      clearTimeout(timer);
      cancelled = true;      // cancels an in-flight scan
    };
  // `onNavigate` and `onQueryChange` are stable callbacks from the reader.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, doc]);

  const step = useCallback((delta: number) => {
    if (!hits.length) return;
    const next = (active + delta + hits.length) % hits.length;
    setActive(next);
    onNavigate(hits[next].page);
  }, [active, hits, onNavigate]);

  const close = useCallback(() => {
    onQueryChange('');
    onClose();
  }, [onClose, onQueryChange]);

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
            if (e.key === 'Escape') { e.preventDefault(); close(); }
          }}
          placeholder="Search in this book…"
          aria-label="Search in this book"
          className="min-w-0 flex-1 rounded border border-slate-200 bg-transparent px-2 py-1 text-sm dark:border-slate-600"
        />
        <span className="shrink-0 tabular-nums text-xs text-slate-400">
          {searching
            ? `scanning ${scanned}/${doc?.numPages ?? 0}`
            : hits.length
              ? `${active + 1} / ${hits.length}${hits.length >= MAX_HITS ? '+' : ''}`
              : query.trim().length >= 2 ? 'no matches' : ''}
        </span>
        <button
          onClick={() => step(-1)}
          disabled={!hits.length}
          aria-label="Previous match"
          className="rounded p-1 text-slate-500 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-slate-700"
        >
          <ChevronUp size={14} />
        </button>
        <button
          onClick={() => step(1)}
          disabled={!hits.length}
          aria-label="Next match"
          className="rounded p-1 text-slate-500 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-slate-700"
        >
          <ChevronDown size={14} />
        </button>
        <button
          onClick={close}
          aria-label="Close search"
          className="rounded p-1 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700"
        >
          <X size={14} />
        </button>
      </div>

      {hits.length > 0 && (
        <ul className="mt-2 max-h-40 overflow-y-auto rounded border border-slate-100 dark:border-slate-700">
          {hits.map((hit, i) => (
            <li key={`${hit.page}-${i}`}>
              <button
                onClick={() => { setActive(i); onNavigate(hit.page); }}
                className={`flex w-full gap-2 px-2 py-1.5 text-left text-xs transition-colors ${
                  i === active
                    ? 'bg-primary-50 dark:bg-primary-900/30'
                    : 'hover:bg-slate-50 dark:hover:bg-slate-700/50'
                }`}
              >
                <span className="shrink-0 tabular-nums text-slate-400">p{hit.page}</span>
                <span className="line-clamp-1 text-slate-600 dark:text-slate-300">
                  {hit.snippet.slice(0, hit.offset)}
                  <mark className="bg-yellow-200 text-slate-900 dark:bg-yellow-500/40 dark:text-yellow-100">
                    {hit.snippet.slice(hit.offset, hit.offset + query.trim().length)}
                  </mark>
                  {hit.snippet.slice(hit.offset + query.trim().length)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
