import { useEffect, useState } from 'react';
import { X, BookOpen, Highlighter, Keyboard, Sparkles, MessagesSquare } from 'lucide-react';
import { useCompare } from '../../api/books';
import { LLMPanel } from './LLMPanel';
import { SimilarPassages } from './SimilarPassages';
import { AnnotationsPanel } from './AnnotationsPanel';
import { PassagePanel } from './PassagePanel';
import { ThreadPanel } from './ThreadPanel';
import { MIN_COMPARE_CHARS } from './selection';
import type { Annotation, CompareMatch, Passage } from '../../api/types';

export type SidebarTab = 'analysis' | 'passages' | 'threads' | 'annotations' | 'shortcuts';

interface ReaderSidebarProps {
  bookId: string;
  bookTitle: string;
  selectedText: string;
  /** Prose around the selection, forwarded to the model as context. */
  surroundingText: string;
  tab: SidebarTab;
  onTabChange: (tab: SidebarTab) => void;
  onNavigateToAnnotation: (annotation: Annotation) => void;
  /** Jump to a passage inside the book currently open (§1.9.1). */
  onNavigateToPassage: (passage: Passage) => void;
  /** Where the reader is, so a new thread records its anchor. */
  page?: number | null;
  cfi?: string;
  onClose: () => void;
}

const READER_SHORTCUTS = [
  { keys: ['→', '↓', 'J', 'Space'], label: 'Next page' },
  { keys: ['←', '↑', 'K'], label: 'Previous page' },
  { keys: ['Home'], label: 'First page' },
  { keys: ['End'], label: 'Last page' },
  { keys: ['/'], label: 'Search in this book' },
  { keys: ['B'], label: 'Bookmark here' },
  { keys: ['+', '='], label: 'Zoom in / larger font' },
  { keys: ['-'], label: 'Zoom out / smaller font' },
  { keys: ['C'], label: 'Toggle continuous scroll' },
  { keys: ['F'], label: 'Toggle fullscreen' },
  { keys: ['S'], label: 'Toggle sidebar' },
  { keys: ['T'], label: 'Toggle contents' },
  { keys: ['Esc'], label: 'Go back' },
];

const TABS: { id: SidebarTab; label: string; icon: typeof BookOpen }[] = [
  { id: 'analysis', label: 'Analysis', icon: BookOpen },
  { id: 'passages', label: 'Passages', icon: Sparkles },
  { id: 'threads', label: 'Threads', icon: MessagesSquare },
  { id: 'annotations', label: 'Marks', icon: Highlighter },
  { id: 'shortcuts', label: 'Keys', icon: Keyboard },
];

export function ReaderSidebar({
  bookId, bookTitle, selectedText, surroundingText, tab, onTabChange,
  onNavigateToAnnotation, onNavigateToPassage, page, cfi, onClose,
}: ReaderSidebarProps) {
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
    if (selectedText.length < MIN_COMPARE_CHARS) return;
    compare(
      { text: selectedText, book_id: bookId, limit: 5 },
      { onSuccess: (data) => setMatches(data.matches) },
    );
  }, [selectedText, bookId, compare]);

  return (
    <div className="flex h-full w-96 shrink-0 flex-col border-l border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/50">
      <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-2.5 dark:border-slate-700">
        <div className="flex flex-wrap gap-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => onTabChange(t.id)}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                tab === t.id
                  ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
                  : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'
              }`}
            >
              <t.icon size={12} /> {t.label}
            </button>
          ))}
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

      <div className="flex-1 overflow-y-auto p-4">
        {tab === 'analysis' && (
          <div className="space-y-4">
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
                  Highlight any passage in the book, then choose Ask or Compare from the
                  toolbar that appears over it.
                </p>
              </div>
            )}

            <SimilarPassages matches={matches} />
            <LLMPanel
              selectedText={selectedText}
              bookId={bookId}
              bookTitle={bookTitle}
              surrounding={surroundingText}
            />
          </div>
        )}

        {tab === 'passages' && (
          <PassagePanel
            bookId={bookId}
            selectedText={selectedText}
            onNavigate={onNavigateToPassage}
          />
        )}

        {tab === 'threads' && (
          <ThreadPanel
            bookId={bookId}
            selectedText={selectedText}
            surroundingText={surroundingText}
            page={page}
            cfi={cfi}
          />
        )}

        {tab === 'annotations' && (
          <AnnotationsPanel bookId={bookId} onNavigate={onNavigateToAnnotation} />
        )}

        {tab === 'shortcuts' && (
          <div>
            <h3 className="mb-3 text-sm font-bold text-slate-700 dark:text-slate-300">
              Reader Keyboard Shortcuts
            </h3>
            <div className="space-y-2">
              {READER_SHORTCUTS.map((s) => (
                <div
                  key={s.label}
                  className="flex items-center justify-between rounded-md bg-white px-3 py-2 text-sm dark:bg-slate-700"
                >
                  <span className="text-slate-600 dark:text-slate-300">{s.label}</span>
                  <div className="flex flex-wrap gap-1">
                    {s.keys.map((k) => (
                      <kbd
                        key={k}
                        className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs font-medium text-slate-600 dark:bg-slate-600 dark:text-slate-300"
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
