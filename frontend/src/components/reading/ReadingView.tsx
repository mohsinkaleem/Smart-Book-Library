import { useState, useCallback, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ArrowLeft, ZoomIn, ZoomOut, BookOpen, Info, Copy, Check, ChevronRight } from 'lucide-react';
import { useBook, useBookText, useCompare } from '../../api/books';
import { Spinner } from '../common/Spinner';
import { LLMPanel } from './LLMPanel';
import type { CompareMatch } from '../../api/types';

function formatTextToParagraphs(text: string): string[] {
  return text
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter((p) => p.length > 0);
}

export function ReadingView() {
  const { id } = useParams<{ id: string }>();
  const { data: book } = useBook(id || '');
  const { data: textData, isLoading } = useBookText(id || '');
  const [fontSize, setFontSize] = useState(16);
  const [selectedText, setSelectedText] = useState('');
  const [showPanel, setShowPanel] = useState(false);
  const [copied, setCopied] = useState(false);
  const compareMutation = useCompare();
  const [matches, setMatches] = useState<CompareMatch[]>([]);

  const paragraphs = useMemo(() => {
    if (!textData?.text) return [];
    return formatTextToParagraphs(textData.text);
  }, [textData?.text]);

  const handleTextSelect = useCallback(() => {
    const sel = window.getSelection()?.toString().trim();
    if (sel && sel.length > 10) {
      setSelectedText(sel);
      setShowPanel(true);
      compareMutation.mutate(
        { text: sel, book_id: id, limit: 5 },
        { onSuccess: (data) => setMatches(data.matches) },
      );
    }
  }, [id, compareMutation]);

  const handleCopyText = useCallback(async () => {
    if (textData?.text) {
      await navigator.clipboard.writeText(textData.text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [textData?.text]);

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-center">
          <Spinner size={32} />
          <p className="mt-3 text-sm text-slate-500">Loading text...</p>
        </div>
      </div>
    );
  }

  if (!textData || !textData.text) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="max-w-md text-center">
          <BookOpen size={48} className="mx-auto mb-4 text-slate-300 dark:text-slate-600" />
          <h2 className="mb-2 text-lg font-bold text-slate-700 dark:text-slate-300">No Text Available</h2>
          <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">
            This book doesn't have extracted text. It may be a scanned PDF that requires OCR processing.
          </p>
          {id && (
            <Link
              to={`/books/${id}`}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
            >
              <ArrowLeft size={16} /> Back to Book
            </Link>
          )}
        </div>
      </div>
    );
  }

  const isExcerpt = (textData.text.length || 0) >= 4900;

  return (
    <div className="flex h-[calc(100vh-56px)]">
      {/* Text Panel */}
      <div className="flex flex-1 flex-col">
        {/* Toolbar */}
        <div className="flex items-center gap-3 border-b border-slate-200 bg-white px-4 py-2 dark:border-slate-700 dark:bg-slate-800">
          <Link
            to={`/books/${id}`}
            className="flex items-center gap-1.5 rounded-md px-2 py-1 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-700"
          >
            <ArrowLeft size={16} />
            <span className="hidden sm:inline max-w-50 truncate">{textData.title}</span>
          </Link>

          {book && (
            <div className="hidden items-center gap-2 text-xs text-slate-400 md:flex">
              <ChevronRight size={12} />
              <span>{book.file_type.toUpperCase()}</span>
              {book.page_count && <span>· {book.page_count} pages</span>}
              <span>· {(textData.text.length / 1000).toFixed(1)}k chars</span>
            </div>
          )}

          <div className="ml-auto flex items-center gap-1">
            <button
              onClick={handleCopyText}
              className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700"
              title="Copy text"
            >
              {copied ? <Check size={14} className="text-emerald-500" /> : <Copy size={14} />}
              <span className="hidden sm:inline">{copied ? 'Copied' : 'Copy'}</span>
            </button>

            <div className="mx-1 h-4 w-px bg-slate-200 dark:bg-slate-700" />

            <button
              onClick={() => setFontSize(Math.max(12, fontSize - 2))}
              className="rounded p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700"
              title="Decrease font size"
            >
              <ZoomOut size={15} />
            </button>
            <span className="min-w-8 text-center text-xs tabular-nums text-slate-400">{fontSize}</span>
            <button
              onClick={() => setFontSize(Math.min(28, fontSize + 2))}
              className="rounded p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700"
              title="Increase font size"
            >
              <ZoomIn size={15} />
            </button>
          </div>
        </div>

        {/* Excerpt notice */}
        {isExcerpt && (
          <div className="flex items-center gap-2 border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-700 dark:border-amber-900/50 dark:bg-amber-900/20 dark:text-amber-400">
            <Info size={14} className="shrink-0" />
            <span>
              Showing a text excerpt (~{(textData.text.length / 1000).toFixed(0)}k chars). Full book text requires opening the original file.
            </span>
          </div>
        )}

        {/* Text content */}
        <div
          className="flex-1 overflow-y-auto bg-white px-6 py-8 md:px-12 lg:px-20 dark:bg-slate-900"
          onMouseUp={handleTextSelect}
          style={{ fontSize: `${fontSize}px`, lineHeight: '1.8' }}
        >
          <div className="mx-auto max-w-3xl">
            <h1 className="mb-6 border-b border-slate-200 pb-4 text-center font-serif text-2xl font-bold text-slate-800 dark:border-slate-700 dark:text-slate-200">
              {textData.title}
            </h1>
            {book?.authors?.length ? (
              <p className="mb-8 text-center text-sm text-slate-500 dark:text-slate-400">
                {book.authors.join(', ')}
              </p>
            ) : null}

            <div className="space-y-4 font-serif text-slate-800 dark:text-slate-200 selection:bg-primary-200 dark:selection:bg-primary-800">
              {paragraphs.map((para, i) => (
                <p key={i} className="text-justify leading-relaxed">
                  {para}
                </p>
              ))}
            </div>

            {isExcerpt && (
              <div className="mt-12 flex flex-col items-center gap-3 border-t border-dashed border-slate-300 pt-8 dark:border-slate-700">
                <div className="flex items-center gap-2 text-sm text-slate-400">
                  <span className="h-px w-8 bg-slate-300 dark:bg-slate-600" />
                  <span>End of excerpt</span>
                  <span className="h-px w-8 bg-slate-300 dark:bg-slate-600" />
                </div>
                <p className="max-w-sm text-center text-xs text-slate-400 dark:text-slate-500">
                  This is a preview of the book's text content. Open the original {book?.file_type?.toUpperCase() || 'file'} for the complete text.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Analysis Sidebar */}
      {showPanel && (
        <div className="w-96 shrink-0 overflow-y-auto border-l border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/50">
          <div className="p-4">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-900 dark:text-white">Analysis</h3>
              <button
                onClick={() => setShowPanel(false)}
                className="rounded px-2 py-0.5 text-xs text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-700"
              >
                Close
              </button>
            </div>

            {selectedText && (
              <div className="mb-4 rounded-lg bg-yellow-50 p-3 text-sm text-yellow-900 dark:bg-yellow-900/20 dark:text-yellow-200">
                <p className="mb-1 text-xs font-semibold text-yellow-700 dark:text-yellow-400">Selected Text</p>
                <p className="line-clamp-4 italic">"{selectedText}"</p>
              </div>
            )}

            {matches.length > 0 && (
              <div className="mb-4">
                <h4 className="mb-2 text-xs font-semibold text-slate-500">Similar in Other Books</h4>
                <div className="space-y-2">
                  {matches.map((m) => (
                    <Link
                      key={m.book_id}
                      to={`/books/${m.book_id}`}
                      className="block rounded-lg bg-white p-3 text-xs shadow-sm ring-1 ring-slate-100 transition-shadow hover:shadow dark:bg-slate-700 dark:ring-slate-600"
                    >
                      <div className="flex items-center gap-2">
                        <span className="rounded bg-primary-100 px-1.5 py-0.5 font-bold text-primary-700 dark:bg-primary-900/50 dark:text-primary-300">
                          {m.similarity}%
                        </span>
                        <span className="truncate font-medium text-slate-700 dark:text-slate-300">
                          {m.title}
                        </span>
                      </div>
                      {m.excerpt && (
                        <p className="mt-1.5 line-clamp-2 text-slate-500 dark:text-slate-400">
                          {m.excerpt}
                        </p>
                      )}
                    </Link>
                  ))}
                </div>
              </div>
            )}

            <LLMPanel selectedText={selectedText} bookId={id || ''} bookTitle={textData.title} />
          </div>
        </div>
      )}
    </div>
  );
}
