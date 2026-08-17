import { useEffect, useState } from 'react';
import { X, BookOpen, Keyboard } from 'lucide-react';
import { useCompare } from '../../api/books';
import { LLMPanel } from './LLMPanel';
import { SimilarPassages } from './SimilarPassages';
import type { CompareMatch } from '../../api/types';

interface ReaderSidebarProps {
  bookId: string;
  bookTitle: string;
  selectedText: string;
  onClose: () => void;
}

const READER_SHORTCUTS = [
  { keys: ['→', '↓', 'J', 'Space'], label: 'Next page' },
  { keys: ['←', '↑', 'K'], label: 'Previous page' },
  { keys: ['Home'], label: 'First page' },
  { keys: ['End'], label: 'Last page' },
  { keys: ['+', '='], label: 'Zoom in / larger font' },
  { keys: ['-'], label: 'Zoom out / smaller font' },
  { keys: ['C'], label: 'Toggle continuous scroll' },
  { keys: ['F'], label: 'Toggle fullscreen' },
  { keys: ['S'], label: 'Toggle sidebar' },
  { keys: ['T'], label: 'Toggle TOC' },
  { keys: ['Esc'], label: 'Go back' },
];

export function ReaderSidebar({ bookId, bookTitle, selectedText, onClose }: ReaderSidebarProps) {
  const [tab, setTab] = useState<'analysis' | 'shortcuts'>('analysis');
  const { mutate: compare } = useCompare();
  const [matches, setMatches] = useState<CompareMatch[]>([]);

  // Auto-compare whenever the selection changes.
  //
  // This was a `useState(() => …)` — an initialiser, not an effect, so it ran
  // exactly once and never again. On that single run `selectedText` was still
  // empty (the sidebar opens *because* text was selected, but the prop lands
  // on the following render), so the comparison fired with nothing and the
  // "Similar in Other Books" panel stayed permanently empty in both readers.
  useEffect(() => {
    if (selectedText.length < 15) return;
    compare(
      { text: selectedText, book_id: bookId, limit: 5 },
      { onSuccess: (data) => setMatches(data.matches) },
    );
  }, [selectedText, bookId, compare]);

  return (
    <div className="flex h-full w-96 shrink-0 flex-col border-l border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/50">
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-2.5 dark:border-slate-700">
        <div className="flex gap-1">
          <button
            onClick={() => setTab('analysis')}
            className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
              tab === 'analysis'
                ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
                : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'
            }`}
          >
            <BookOpen size={12} /> Analysis
          </button>
          <button
            onClick={() => setTab('shortcuts')}
            className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
              tab === 'shortcuts'
                ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
                : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'
            }`}
          >
            <Keyboard size={12} /> Shortcuts
          </button>
        </div>
        <button
          onClick={onClose}
          aria-label="Close sidebar"
          className="ml-auto rounded p-1 text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700"
          title="Close sidebar (S)"
        >
          <X size={16} />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        {tab === 'analysis' ? (
          <div className="space-y-4">
            {/* Selected text */}
            {selectedText ? (
              <div className="rounded-lg bg-yellow-50 p-3 text-sm text-yellow-900 dark:bg-yellow-900/20 dark:text-yellow-200">
                <p className="mb-1 text-xs font-semibold text-yellow-700 dark:text-yellow-400">
                  Selected Text
                </p>
                <p className="line-clamp-6 italic">"{selectedText}"</p>
              </div>
            ) : (
              <div className="rounded-lg bg-slate-100 p-4 text-center text-sm text-slate-500 dark:bg-slate-700/50 dark:text-slate-400">
                <BookOpen size={24} className="mx-auto mb-2 opacity-50" />
                <p className="font-medium">Select text to analyze</p>
                <p className="mt-1 text-xs">
                  Highlight any passage in the book to compare with other books, get explanations, summaries, and more.
                </p>
              </div>
            )}

            {/* Similar passages from other books */}
            <SimilarPassages matches={matches} />

            {/* LLM Analysis */}
            <LLMPanel selectedText={selectedText} bookId={bookId} bookTitle={bookTitle} />
          </div>
        ) : (
          /* Shortcuts tab */
          <div>
            <h3 className="mb-3 text-sm font-bold text-slate-700 dark:text-slate-300">Reader Keyboard Shortcuts</h3>
            <div className="space-y-2">
              {READER_SHORTCUTS.map((s) => (
                <div key={s.label} className="flex items-center justify-between rounded-md bg-white px-3 py-2 text-sm dark:bg-slate-700">
                  <span className="text-slate-600 dark:text-slate-300">{s.label}</span>
                  <div className="flex gap-1">
                    {s.keys.map((k) => (
                      <kbd
                        key={k}
                        className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-mono font-medium text-slate-600 dark:bg-slate-600 dark:text-slate-300"
                      >
                        {k}
                      </kbd>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
