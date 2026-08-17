import { useState, useCallback, useRef, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Maximize2,
  Minimize2,
  ChevronLeft,
  ChevronRight,
  ZoomIn,
  ZoomOut,
  PanelRightOpen,
  PanelRightClose,
  Download,
  List,
  ScrollText,
  BookOpen,
} from 'lucide-react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';
import pdfWorkerSrc from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { useBook } from '../../api/books';
import { useReaderKeyboard } from '../../hooks/useReaderKeyboard';
import { useReadingProgress } from '../../hooks/useReadingProgress';
import { Spinner } from '../common/Spinner';
import { ErrorState } from '../common/ErrorBoundary';
import { ReaderSidebar } from './ReaderSidebar';

// Configure PDF.js worker.
//
// This used to point at `//unpkg.com/pdfjs-dist@…`, so a "local-first" app
// silently failed to open a PDF offline or on a locked-down network — and the
// protocol-relative URL broke under `file://` as well. Vite bundles the worker
// from the installed package instead.
pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerSrc;

/* ==========================================================================
   PDF READER
   ========================================================================== */

export function PdfReader() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: book, isLoading, isError, error, refetch } = useBook(id || '');

  const [numPages, setNumPages] = useState<number>(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [scale, setScale] = useState(1.2);
  const [fullscreen, setFullscreen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [selectedText, setSelectedText] = useState('');
  const [pageInputValue, setPageInputValue] = useState('1');
  const [continuous, setContinuous] = useState(false);
  // [min, max] page numbers to actually render in continuous mode
  const [renderedRange, setRenderedRange] = useState<[number, number]>([1, 5]);

  const containerRef = useRef<HTMLDivElement>(null);
  const pageSlotRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const observerRef = useRef<IntersectionObserver | null>(null);
  const restored = useRef(false);

  const pdfUrl = `/api/books/${id}/file`;
  const recordProgress = useReadingProgress(book);

  // Sync page input when currentPage changes
  useEffect(() => {
    setPageInputValue(String(currentPage));
  }, [currentPage]);

  // Report position on every page change. `numPages` guards the very first
  // renders, where the ratio would be 1/0.
  useEffect(() => {
    if (!numPages || !restored.current) return;
    recordProgress((currentPage / numPages) * 100, String(currentPage));
  }, [currentPage, numPages, recordProgress]);

  // Resume where the book was left. Runs once, after the document reports its
  // length — the page used to reset to 1 on every open.
  useEffect(() => {
    if (restored.current || !numPages || !book) return;
    restored.current = true;
    const saved = parseInt(book.reader_position || '', 10);
    if (Number.isFinite(saved) && saved > 1 && saved <= numPages) {
      setCurrentPage(saved);
      setRenderedRange([Math.max(1, saved - 2), Math.min(numPages, saved + 5)]);
    }
  }, [numPages, book]);

  // Register / unregister a page slot with the IntersectionObserver
  const registerSlot = useCallback((el: HTMLDivElement | null, pageNum: number) => {
    if (el) {
      pageSlotRefs.current.set(pageNum, el);
      observerRef.current?.observe(el);
    } else {
      const prev = pageSlotRefs.current.get(pageNum);
      if (prev) observerRef.current?.unobserve(prev);
      pageSlotRefs.current.delete(pageNum);
    }
  }, []);

  // Set up IntersectionObserver for continuous scroll mode
  useEffect(() => {
    if (!continuous || numPages === 0) return;
    setRenderedRange([1, Math.min(5, numPages)]);

    const observer = new IntersectionObserver(
      (entries) => {
        // Find the first (topmost) intersecting page
        let topPage: number | null = null;
        const toRender: number[] = [];
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const page = Number(entry.target.getAttribute('data-page'));
          if (page && (topPage === null || page < topPage)) topPage = page;
          // pre-render nearby pages
          for (let p = Math.max(1, page - 2); p <= Math.min(numPages, page + 5); p++)
            toRender.push(p);
        });
        if (topPage !== null) {
          setCurrentPage(topPage);
          setPageInputValue(String(topPage));
        }
        if (toRender.length) {
          const min = Math.min(...toRender);
          const max = Math.max(...toRender);
          setRenderedRange((prev) => [
            Math.min(prev[0], min),
            Math.max(prev[1], max),
          ]);
        }
      },
      { rootMargin: '600px 0px', threshold: 0.05 },
    );
    observerRef.current = observer;
    // Observe already-mounted slots
    pageSlotRefs.current.forEach((el) => observer.observe(el));
    return () => {
      observer.disconnect();
      observerRef.current = null;
    };
  }, [continuous, numPages]);

  // When switching to continuous, scroll to current page
  useEffect(() => {
    if (!continuous) return;
    const p = currentPage;
    setRenderedRange([Math.max(1, p - 2), Math.min(numPages, p + 5)]);
    requestAnimationFrame(() => {
      pageSlotRefs.current.get(p)?.scrollIntoView({ behavior: 'instant', block: 'start' });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [continuous]);

  // 'C' key — toggle continuous mode
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const isInput = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA';
      if (e.key === 'c' && !e.ctrlKey && !e.metaKey && !isInput) {
        e.preventDefault();
        setContinuous((c) => !c);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const goToPage = useCallback(
    (page: number) => {
      const p = Math.max(1, Math.min(page, numPages || 1));
      if (continuous) {
        // ensure target is within rendered range then scroll
        setRenderedRange((prev) => [
          Math.min(prev[0], Math.max(1, p - 2)),
          Math.max(prev[1], Math.min(numPages, p + 5)),
        ]);
        requestAnimationFrame(() => {
          pageSlotRefs.current.get(p)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
      } else {
        setCurrentPage(p);
        setPageInputValue(String(p));
        containerRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
      }
    },
    [numPages, continuous],
  );

  const nextPage = useCallback(() => goToPage(currentPage + 1), [currentPage, goToPage]);
  const prevPage = useCallback(() => goToPage(currentPage - 1), [currentPage, goToPage]);

  const zoomIn = useCallback(() => setScale((s) => Math.min(3, +(s + 0.2).toFixed(1))), []);
  const zoomOut = useCallback(() => setScale((s) => Math.max(0.4, +(s - 0.2).toFixed(1))), []);
  const zoomReset = useCallback(() => setScale(1.2), []);

  const handleTextSelection = useCallback(() => {
    const sel = window.getSelection()?.toString().trim();
    if (sel && sel.length > 10) {
      setSelectedText(sel);
      setSidebarOpen(true);
    }
  }, []);

  const handlePageInput = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter') {
        const val = parseInt(pageInputValue, 10);
        if (!isNaN(val)) goToPage(val);
      }
    },
    [pageInputValue, goToPage],
  );

  // Keyboard shortcuts
  useReaderKeyboard({
    onNextPage: nextPage,
    onPrevPage: prevPage,
    onFirstPage: () => goToPage(1),
    onLastPage: () => goToPage(numPages),
    onZoomIn: zoomIn,
    onZoomOut: zoomOut,
    onZoomReset: zoomReset,
    onToggleFullscreen: () => setFullscreen((f) => !f),
    onToggleSidebar: () => setSidebarOpen((s) => !s),
    onGoBack: () => {
      if (fullscreen) setFullscreen(false);
      else navigate(`/books/${id}`);
    },
    disabled: false,
  });

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner size={32} />
      </div>
    );
  }

  // "Book not found" used to cover a failed request too.
  if (isError) {
    return (
      <ErrorState
        title="Couldn't load this book"
        message={(error as Error)?.message}
        onRetry={() => refetch()}
      />
    );
  }

  if (!book) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-slate-500">Book not found</p>
      </div>
    );
  }

  return (
    <div
      className={`flex ${fullscreen ? 'fixed inset-0 z-50 bg-white dark:bg-slate-900' : 'h-[calc(100vh-56px)]'}`}
    >
      {/* Main reader area */}
      <div className="flex flex-1 flex-col">
        {/* Toolbar */}
        <div className="flex items-center gap-2 border-b border-slate-200 bg-white px-3 py-1.5 dark:border-slate-700 dark:bg-slate-800">
          {/* Back */}
          <Link
            to={`/books/${id}`}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-700"
          >
            <ArrowLeft size={16} />
            <span className="hidden sm:inline max-w-48 truncate">{book.title}</span>
          </Link>

          <div className="mx-1 hidden h-4 w-px bg-slate-200 dark:bg-slate-700 sm:block" />

          {/* Page navigation */}
          <div className="flex items-center gap-1">
            <button
              onClick={prevPage}
              disabled={currentPage <= 1}
              className="rounded p-1.5 text-slate-500 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-slate-700"
              title="Previous page (←)"
            >
              <ChevronLeft size={16} />
            </button>

            <div className="flex items-center gap-1 text-xs text-slate-500">
              <input
                type="text"
                value={pageInputValue}
                onChange={(e) => setPageInputValue(e.target.value)}
                onKeyDown={handlePageInput}
                onBlur={() => {
                  const val = parseInt(pageInputValue, 10);
                  if (!isNaN(val)) goToPage(val);
                  else setPageInputValue(String(currentPage));
                }}
                className="w-10 rounded border border-slate-200 bg-transparent px-1.5 py-0.5 text-center text-xs tabular-nums dark:border-slate-600"
              />
              <span>/ {numPages}</span>
            </div>

            <button
              onClick={nextPage}
              disabled={currentPage >= numPages}
              className="rounded p-1.5 text-slate-500 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-slate-700"
              title="Next page (→)"
            >
              <ChevronRight size={16} />
            </button>
          </div>

          <div className="mx-1 hidden h-4 w-px bg-slate-200 dark:bg-slate-700 sm:block" />

          {/* Zoom */}
          <div className="flex items-center gap-1">
            <button
              onClick={zoomOut}
              className="rounded p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700"
              title="Zoom out (-)"
            >
              <ZoomOut size={15} />
            </button>
            <span className="min-w-10 text-center text-xs tabular-nums text-slate-400">
              {Math.round(scale * 100)}%
            </span>
            <button
              onClick={zoomIn}
              className="rounded p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700"
              title="Zoom in (+)"
            >
              <ZoomIn size={15} />
            </button>
          </div>

          {/* Continuous / paginated toggle */}
          <button
            onClick={() => setContinuous((c) => !c)}
            className={`flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition-colors ${
              continuous
                ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
                : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'
            }`}
            title={continuous ? 'Switch to paginated view (C)' : 'Switch to continuous scroll (C)'}
          >
            {continuous ? <ScrollText size={15} /> : <BookOpen size={15} />}
            <span className="hidden md:inline">{continuous ? 'Scroll' : 'Pages'}</span>
          </button>

          {/* Spacer */}
          <div className="flex-1" />

          {/* Right actions */}
          <a
            href={pdfUrl}
            download={book.file_name}
            className="rounded p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700"
            title="Download"
          >
            <Download size={15} />
          </a>
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className={`rounded p-1.5 transition-colors ${
              sidebarOpen
                ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
                : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'
            }`}
            title={sidebarOpen ? 'Close sidebar (S)' : 'Open sidebar (S)'}
          >
            {sidebarOpen ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}
          </button>
          <button
            onClick={() => setFullscreen(!fullscreen)}
            className="rounded p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700"
            title={fullscreen ? 'Exit fullscreen (F)' : 'Fullscreen (F)'}
          >
            {fullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
          </button>
        </div>

        {/* PDF canvas */}
        <div
          ref={containerRef}
          className="flex-1 overflow-auto bg-slate-200 dark:bg-slate-950"
          onMouseUp={handleTextSelection}
        >
          <div className={`flex min-h-full py-4 ${continuous ? 'flex-col items-center' : 'items-start justify-center'}`}>
            <Document
              file={pdfUrl}
              onLoadSuccess={({ numPages: n }) => {
                setNumPages(n);
                setRenderedRange([1, Math.min(5, n)]);
              }}
              loading={
                <div className="flex items-center gap-3 p-12 text-slate-500">
                  <Spinner size={20} /> Loading PDF...
                </div>
              }
              error={
                <div className="p-12 text-center text-red-500">
                  <p className="font-medium">Failed to load PDF</p>
                  <a
                    href={pdfUrl}
                    download
                    className="mt-2 inline-block text-sm text-primary-600 hover:underline"
                  >
                    Download instead
                  </a>
                </div>
              }
            >
              {continuous ? (
                // Continuous scroll: virtualized — only render pages within renderedRange
                Array.from({ length: numPages }, (_, i) => i + 1).map((pageNum) => {
                  const inRange = pageNum >= renderedRange[0] && pageNum <= renderedRange[1];
                  const estimatedH = Math.round(842 * scale + 16);
                  return (
                    <div
                      key={pageNum}
                      ref={(el) => registerSlot(el as HTMLDivElement | null, pageNum)}
                      data-page={pageNum}
                      className="mb-4 flex w-full justify-center"
                      style={{ minHeight: inRange ? undefined : estimatedH }}
                    >
                      {inRange && (
                        <Page
                          pageNumber={pageNum}
                          scale={scale}
                          className="shadow-xl"
                          renderTextLayer
                          renderAnnotationLayer
                        />
                      )}
                    </div>
                  );
                })
              ) : (
                <Page
                  pageNumber={currentPage}
                  scale={scale}
                  className="shadow-xl"
                  renderTextLayer={true}
                  renderAnnotationLayer={true}
                />
              )}
            </Document>
          </div>
        </div>

        {/* Bottom bar with page indicator */}
        <div className="flex items-center justify-between border-t border-slate-200 bg-white px-4 py-1.5 text-xs text-slate-400 dark:border-slate-700 dark:bg-slate-800">
          <span>
            Page {currentPage} of {numPages}{continuous ? ' · scroll' : ''}
            {numPages > 0 && (
              <span className="ml-2 tabular-nums">
                · {Math.round((currentPage / numPages) * 100)}%
              </span>
            )}
          </span>
          <span className="hidden text-[10px] sm:inline">
            {continuous
              ? '↑↓ Scroll &nbsp;·&nbsp; J/K page jump &nbsp;·&nbsp; C toggle mode &nbsp;·&nbsp; +/- Zoom'
              : '← → Navigate &nbsp;·&nbsp; +/- Zoom &nbsp;·&nbsp; C Scroll mode'}
            &nbsp;·&nbsp; F Fullscreen &nbsp;·&nbsp; S Sidebar
          </span>
          <span>{book.file_type.toUpperCase()}</span>
        </div>
      </div>

      {/* Sidebar */}
      {sidebarOpen && (
        <ReaderSidebar
          bookId={id || ''}
          bookTitle={book.title}
          selectedText={selectedText}
          onClose={() => setSidebarOpen(false)}
        />
      )}
    </div>
  );
}

/* ==========================================================================
   EPUB READER
   ========================================================================== */

export function EpubReader() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: book, isLoading, isError, error, refetch } = useBook(id || '');

  const [location, setLocation] = useState<string | number>(0);
  const [fullscreen, setFullscreen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [selectedText, setSelectedText] = useState('');
  const [showToc, setShowToc] = useState(false);
  const [fontSize, setFontSize] = useState(100);
  const [continuous, setContinuous] = useState(false);
  const [percent, setPercent] = useState(0);

  const recordProgress = useReadingProgress(book);
  const recordRef = useRef(recordProgress);
  recordRef.current = recordProgress;
  // The reader reports its opening position immediately, which would
  // overwrite the saved CFI with the cover before we ever restore it.
  const restored = useRef(false);

  // Resume where the book was left. The EPUB location was component state and
  // nothing persisted it, so every open started at the cover.
  useEffect(() => {
    if (restored.current || !book) return;
    restored.current = true;
    if (book.reader_position) setLocation(book.reader_position);
  }, [book]);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [ReaderComponent, setReaderComponent] = useState<React.ComponentType<any> | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const renditionRef = useRef<any>(null);
  // `getRendition` is handed to the reader once and captures whatever the
  // render it was created in saw. Read the live values through a ref instead,
  // or the rendition applies a frozen 100% font size and tests a frozen
  // `sidebarOpen`.
  const fontSizeRef = useRef(fontSize);
  fontSizeRef.current = fontSize;

  // Dynamically import react-reader.
  //
  // This was a `useState(() => …)` initialiser, which StrictMode runs twice —
  // so the module was imported twice on every mount.
  useEffect(() => {
    let cancelled = false;
    import('react-reader')
      .then((mod) => {
        if (!cancelled) setReaderComponent(() => mod.ReactReader);
      })
      .catch(() => {
        if (!cancelled) setLoadError('Failed to load EPUB reader library');
      });
    return () => { cancelled = true; };
  }, []);

  const flipNext = useCallback(() => {
    renditionRef.current?.next();
  }, []);

  const flipPrev = useCallback(() => {
    renditionRef.current?.prev();
  }, []);

  const increaseFontSize = useCallback(() => {
    setFontSize((s) => {
      const next = Math.min(200, s + 10);
      renditionRef.current?.themes.fontSize(`${next}%`);
      return next;
    });
  }, []);

  const decreaseFontSize = useCallback(() => {
    setFontSize((s) => {
      const next = Math.max(60, s - 10);
      renditionRef.current?.themes.fontSize(`${next}%`);
      return next;
    });
  }, []);

  const resetFontSize = useCallback(() => {
    setFontSize(100);
    renditionRef.current?.themes.fontSize('100%');
  }, []);

  // Text selection from EPUB
  const handleTextSelection = useCallback(() => {
    const sel = window.getSelection()?.toString().trim();
    if (sel && sel.length > 10) {
      setSelectedText(sel);
      setSidebarOpen(true);
    }
  }, []);

  interface EpubContents {
    window?: Window;
  }

  /** The shape of epub.js's `relocated` payload that we actually read. */
  interface EpubLocation {
    start?: { cfi?: string; index?: number; percentage?: number };
  }

  interface Rendition {
    themes: {
      default: (styles: Record<string, Record<string, string>>) => void;
      fontSize: (size: string) => void;
    };
    on: (event: string, cb: (...args: unknown[]) => void) => void;
    book?: { spine?: { length?: number } };
  }

  const handleRendition = useCallback((rendition: Rendition) => {
    renditionRef.current = rendition;
    rendition.themes.default({
      body: {
        'font-family': 'Georgia, serif !important',
        'line-height': '1.8 !important',
      },
      p: {
        'margin-bottom': '0.8em !important',
      },
      '::selection': {
        'background-color': '#c7d2fe !important',
      },
    });
    // Whatever the user had set before this rendition was created — not the
    // initial 100% this callback used to close over.
    rendition.themes.fontSize(`${fontSizeRef.current}%`);

    // Listen for text selection inside the epub iframe.
    //
    // The selection lives in the iframe's own window, so the parent
    // `window.getSelection()` this used to call was always empty — which is
    // why selecting text in an EPUB never opened the analysis sidebar. epub.js
    // hands us the `contents` for the section the selection happened in.
    rendition.on('selected', (...args: unknown[]) => {
      const contents = args[1] as EpubContents | undefined;
      const sel = (contents?.window ?? window).getSelection()?.toString().trim();
      if (sel && sel.length > 10) {
        setSelectedText(sel);
        setSidebarOpen(true);
      }
    });

    // Position and progress on every relocation.
    //
    // `start.percentage` is only meaningful once epub.js has generated its
    // locations index, which is a full pass over the book and too slow to do
    // on open. The spine ratio — which chapter of how many — is available
    // immediately and close enough for a progress bar; the exact percentage
    // takes over if and when epub.js fills it in.
    rendition.on('relocated', (...args: unknown[]) => {
      const loc = args[0] as EpubLocation | undefined;
      const cfi = loc?.start?.cfi;
      if (!cfi) return;

      const exact = loc?.start?.percentage ?? 0;
      const spineLength = rendition.book?.spine?.length ?? 0;
      const index = loc?.start?.index ?? 0;
      const pct = exact > 0
        ? exact * 100
        : spineLength > 0
          ? ((index + 1) / spineLength) * 100
          : 0;

      setPercent(pct);
      recordRef.current(pct, cfi);
    });
  }, []);

  // 'C' key — toggle continuous scroll mode for EPUB
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const isInput = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA';
      if (e.key === 'c' && !e.ctrlKey && !e.metaKey && !isInput) {
        e.preventDefault();
        setContinuous((c) => !c);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  // Keyboard shortcuts
  useReaderKeyboard({
    onNextPage: continuous ? undefined : flipNext,
    onPrevPage: continuous ? undefined : flipPrev,
    onZoomIn: increaseFontSize,
    onZoomOut: decreaseFontSize,
    onZoomReset: resetFontSize,
    onToggleFullscreen: () => setFullscreen((f) => !f),
    onToggleSidebar: () => setSidebarOpen((s) => !s),
    onToggleToc: () => setShowToc((t) => !t),
    onGoBack: () => {
      if (fullscreen) setFullscreen(false);
      else navigate(`/books/${id}`);
    },
    disabled: false,
  });

  // Belt-and-braces selection listener on the rendered iframe.
  //
  // This used to poll for `.ReactReader iframe` — a selector react-reader
  // never renders (the iframe sits inside `.epub-view`), so the interval span
  // the lifetime of the component without ever matching, and the listener was
  // never attached.
  useEffect(() => {
    let detach: (() => void) | undefined;
    const interval = setInterval(() => {
      const iframe = document.querySelector('.epub-view iframe') as HTMLIFrameElement | null;
      const doc = iframe?.contentDocument;
      if (!doc) return;
      const onMouseUp = () => {
        const sel = (iframe.contentWindow ?? window).getSelection()?.toString().trim();
        if (sel && sel.length > 10) {
          setSelectedText(sel);
          setSidebarOpen(true);
        }
      };
      doc.addEventListener('mouseup', onMouseUp);
      detach = () => doc.removeEventListener('mouseup', onMouseUp);
      clearInterval(interval);
    }, 500);
    return () => {
      clearInterval(interval);
      detach?.();
    };
  }, [continuous, ReaderComponent]);

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner size={32} />
      </div>
    );
  }

  // "Book not found" used to cover a failed request too.
  if (isError) {
    return (
      <ErrorState
        title="Couldn't load this book"
        message={(error as Error)?.message}
        onRetry={() => refetch()}
      />
    );
  }

  if (!book) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-slate-500">Book not found</p>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-center">
          <p className="text-red-500">{loadError}</p>
          <Link
            to={`/books/${id}`}
            className="mt-4 inline-flex items-center gap-1.5 text-sm text-primary-600 hover:underline"
          >
            <ArrowLeft size={16} /> Back to Book
          </Link>
        </div>
      </div>
    );
  }

  // The `.epub` extension is load-bearing: epub.js reads it to decide between
  // opening an archive and crawling an unpacked directory.
  const epubUrl = `/api/books/${id}/file.epub`;

  return (
    <div
      className={`flex ${fullscreen ? 'fixed inset-0 z-50 bg-white dark:bg-slate-900' : 'h-[calc(100vh-56px)]'}`}
    >
      {/* Main reader area */}
      <div className="flex flex-1 flex-col">
        {/* Toolbar */}
        <div className="flex items-center gap-2 border-b border-slate-200 bg-white px-3 py-1.5 dark:border-slate-700 dark:bg-slate-800">
          <Link
            to={`/books/${id}`}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-700"
          >
            <ArrowLeft size={16} />
            <span className="hidden sm:inline max-w-48 truncate">{book.title}</span>
          </Link>

          <div className="mx-1 hidden h-4 w-px bg-slate-200 dark:bg-slate-700 sm:block" />

          {/* Page nav — hidden in continuous mode */}
          {!continuous && (
            <div className="flex items-center gap-1">
              <button
                onClick={flipPrev}
                className="rounded p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700"
                title="Previous page (←)"
              >
                <ChevronLeft size={16} />
              </button>
              <button
                onClick={flipNext}
                className="rounded p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700"
                title="Next page (→)"
              >
                <ChevronRight size={16} />
              </button>
            </div>
          )}

          {!continuous && <div className="mx-1 hidden h-4 w-px bg-slate-200 dark:bg-slate-700 sm:block" />}

          {/* Font size */}
          <div className="flex items-center gap-1">
            <button
              onClick={decreaseFontSize}
              className="rounded p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700"
              title="Decrease font (-)"
            >
              <ZoomOut size={15} />
            </button>
            <span className="min-w-10 text-center text-xs tabular-nums text-slate-400">{fontSize}%</span>
            <button
              onClick={increaseFontSize}
              className="rounded p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700"
              title="Increase font (+)"
            >
              <ZoomIn size={15} />
            </button>
          </div>

          {/* Spacer */}
          <div className="flex-1" />

          {/* Continuous / paginated toggle */}
          <button
            onClick={() => setContinuous((c) => !c)}
            className={`flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition-colors ${
              continuous
                ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
                : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'
            }`}
            title={continuous ? 'Switch to paginated view (C)' : 'Switch to continuous scroll (C)'}
          >
            {continuous ? <ScrollText size={15} /> : <BookOpen size={15} />}
            <span className="hidden md:inline">{continuous ? 'Scroll' : 'Pages'}</span>
          </button>

          {/* Right actions */}
          <button
            onClick={() => setShowToc(!showToc)}
            className={`rounded p-1.5 transition-colors ${
              showToc
                ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
                : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'
            }`}
            title="Table of contents (T)"
          >
            <List size={16} />
          </button>
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className={`rounded p-1.5 transition-colors ${
              sidebarOpen
                ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
                : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'
            }`}
            title={sidebarOpen ? 'Close sidebar (S)' : 'Open sidebar (S)'}
          >
            {sidebarOpen ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}
          </button>
          <button
            onClick={() => setFullscreen(!fullscreen)}
            className="rounded p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700"
            title={fullscreen ? 'Exit fullscreen (F)' : 'Fullscreen (F)'}
          >
            {fullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
          </button>
        </div>

        {/* EPUB Renderer — key forces remount when flow mode changes */}
        <div className="relative flex-1 overflow-hidden" onMouseUp={handleTextSelection}>
          {ReaderComponent ? (
            <ReaderComponent
              key={`epub-${continuous ? 'scroll' : 'page'}`}
              url={epubUrl}
              location={location}
              locationChanged={(epubcfi: string) => setLocation(epubcfi)}
              title={book.title}
              showToc={showToc}
              epubOptions={{
                flow: continuous ? 'scrolled-doc' : 'paginated',
                manager: continuous ? 'continuous' : 'default',
              }}
              getRendition={handleRendition}
            />
          ) : (
            <div className="flex h-full items-center justify-center">
              <Spinner size={24} />
              <span className="ml-3 text-sm text-slate-500">Loading reader...</span>
            </div>
          )}
        </div>

        {/* Bottom bar */}
        <div className="flex items-center justify-between border-t border-slate-200 bg-white px-4 py-1.5 text-xs text-slate-400 dark:border-slate-700 dark:bg-slate-800">
          <span>
            EPUB{continuous ? ' · scroll' : ''}
            {percent > 0 && <span className="ml-2 tabular-nums">· {Math.round(percent)}%</span>}
          </span>
          <span className="hidden text-[10px] sm:inline">
            {continuous
              ? '+/- Font &nbsp;·&nbsp; C toggle mode'
              : '← → Navigate &nbsp;·&nbsp; +/- Font &nbsp;·&nbsp; C Scroll mode'}
            &nbsp;·&nbsp; F Fullscreen &nbsp;·&nbsp; S Sidebar &nbsp;·&nbsp; T TOC
          </span>
          <span>Font: {fontSize}%</span>
        </div>
      </div>

      {/* Sidebar */}
      {sidebarOpen && (
        <ReaderSidebar
          bookId={id || ''}
          bookTitle={book.title}
          selectedText={selectedText}
          onClose={() => setSidebarOpen(false)}
        />
      )}
    </div>
  );
}
