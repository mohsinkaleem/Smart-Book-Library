import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams, Link } from 'react-router-dom';
import {
  ArrowLeft,
  Bookmark,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Download,
  List,
  Maximize2,
  Minimize2,
  MoveHorizontal,
  PanelRightClose,
  PanelRightOpen,
  Images,
  ScrollText,
  Search,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import { Document, Page, pdfjs } from 'react-pdf';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';
import pdfWorkerSrc from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

import { useBook } from '../../api/books';
import { useAnnotations, useCreateAnnotation } from '../../api/annotations';
import { useReaderKeyboard } from '../../hooks/useReaderKeyboard';
import { useReadingProgress } from '../../hooks/useReadingProgress';
import { useReadingSession } from '../../hooks/useReadingSession';
import { useLocalStorage } from '../../hooks/useLocalStorage';
import { useTheme } from '../../hooks/useTheme';
import { Spinner } from '../common/Spinner';
import { ErrorState } from '../common/ErrorBoundary';
import { ReaderSidebar, type SidebarTab } from './ReaderSidebar';
import { SelectionToolbar } from './SelectionToolbar';
import { PdfOutline } from './PdfOutline';
import { PdfThumbnails } from './PdfThumbnails';
import { PdfSearch } from './PdfSearch';
import { ReaderSettings } from './ReaderSettings';
import { readSelection, clearSelection, type ReaderSelection } from './selection';
import {
  mapHighlightsToRuns,
  renderRun,
  type PageHighlight,
  type RunMarks,
} from './pdfHighlight';
import {
  READING_THEME_META,
  resolveReadingTheme,
  type ReadingTheme,
} from './readingTheme';
import type { Annotation, Passage } from '../../api/types';

// Configure PDF.js worker.
//
// This used to point at `//unpkg.com/pdfjs-dist@…`, so a "local-first" app
// silently failed to open a PDF offline or on a locked-down network — and the
// protocol-relative URL broke under `file://` as well. Vite bundles the worker
// from the installed package instead.
pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerSrc;

/**
 * How many pages either side of the viewport stay rendered in continuous mode.
 *
 * This is the fix for the leak: `renderedRange` used to take `Math.min` /
 * `Math.max` against its previous value on every scroll, so it only ever grew.
 * Scrolling a 600-page PDF end to end left 600 live canvases in memory — at
 * roughly 3 MB each on a retina display, well past a gigabyte. The range is
 * now recomputed as a window around the visible page, so pages behind you are
 * unmounted and their canvases freed.
 */
const WINDOW_BEFORE = 2;
const WINDOW_AFTER = 5;

/** A4 at 72 dpi — the placeholder height for a page that is not rendered. */
const ESTIMATED_PAGE_HEIGHT = 842;

type ZoomMode = 'manual' | 'width' | 'page';

export function PdfReader() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: book, isLoading, isError, error, refetch } = useBook(id || '');
  const [appTheme] = useTheme();

  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [numPages, setNumPages] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [scale, setScale] = useState(1.2);
  const [zoomMode, setZoomMode] = useLocalStorage<ZoomMode>('reader.pdf.zoomMode', 'manual');
  const [fullscreen, setFullscreen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>('analysis');
  const [outlineOpen, setOutlineOpen] = useState(false);
  const [thumbsOpen, setThumbsOpen] = useLocalStorage('reader.pdf.thumbnails', false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [readingTheme, setReadingTheme] = useLocalStorage<ReadingTheme>('reader.theme', 'auto');
  const [selection, setSelection] = useState<ReaderSelection | null>(null);
  const [selectedText, setSelectedText] = useState('');
  const [surroundingText, setSurroundingText] = useState('');
  const [pageInputValue, setPageInputValue] = useState('1');
  const [continuous, setContinuous] = useState(false);
  const [renderedRange, setRenderedRange] = useState<[number, number]>([1, 5]);

  // Which text runs each page's highlights cover, resolved once per page from
  // react-pdf's `onGetTextSuccess`. Doing this per run instead would mean
  // guessing from a run's text alone, which cannot tell one occurrence of a
  // word from another — see `pdfHighlight`.
  const [runMarks, setRunMarks] = useState<Map<number, RunMarks>>(new Map());

  const [searchParams, setSearchParams] = useSearchParams();
  const deepLinkPage = Number(searchParams.get('page')) || 0;
  const deepLinkHandled = useRef(false);

  const containerRef = useRef<HTMLDivElement>(null);
  const pageSlotRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const observerRef = useRef<IntersectionObserver | null>(null);
  const restored = useRef(false);
  const pendingScroll = useRef<number | null>(null);

  const pdfUrl = `/api/books/${id}/file`;
  const recordProgress = useReadingProgress(book);
  useReadingSession(id || '', currentPage);
  const { data: annotationData } = useAnnotations(id || '');
  const { mutate: createAnnotation } = useCreateAnnotation(id || '');

  const theme = resolveReadingTheme(readingTheme, appTheme);
  const themeMeta = READING_THEME_META[theme];

  /** Highlights bucketed by page, so a page renderer looks up rather than scans. */
  const highlightsByPage = useMemo(() => {
    const map = new Map<number, PageHighlight[]>();
    for (const a of annotationData?.annotations ?? []) {
      if (a.kind !== 'highlight' || a.page === null || !a.text) continue;
      const list = map.get(a.page) ?? [];
      list.push({ id: a.id, color: a.color, text: a.text });
      map.set(a.page, list);
    }
    return map;
  }, [annotationData]);

  useEffect(() => setPageInputValue(String(currentPage)), [currentPage]);

  // Report position on every page change. `numPages` guards the very first
  // renders, where the ratio would be 1/0.
  useEffect(() => {
    if (!numPages || !restored.current) return;
    recordProgress((currentPage / numPages) * 100, String(currentPage));
  }, [currentPage, numPages, recordProgress]);

  // Resume where the book was left. Runs once, after the document reports its
  // length — the page used to reset to 1 on every open.
  //
  // A deep link is an explicit destination and outranks the saved position.
  // Both effects fire on the same render when `numPages` lands, so this defers
  // rather than relying on declaration order to settle which one wins.
  useEffect(() => {
    if (restored.current || !numPages || !book) return;
    restored.current = true;
    if (deepLinkPage) return;
    const saved = parseInt(book.reader_position || '', 10);
    if (Number.isFinite(saved) && saved > 1 && saved <= numPages) {
      setCurrentPage(saved);
      setRenderedRange([Math.max(1, saved - WINDOW_BEFORE), Math.min(numPages, saved + WINDOW_AFTER)]);
    }
  }, [numPages, book]);

  // ── Fit-to-width / fit-to-page ────────────────────────────────────────────
  //
  // Zoom used to be manual only, so opening a wide technical PDF on a laptop
  // meant hunting for the percentage that made it fit.
  useEffect(() => {
    if (zoomMode === 'manual' || !doc) return;
    let cancelled = false;

    const fit = async () => {
      const el = containerRef.current;
      if (!el) return;
      try {
        const viewport = await doc.getPage(currentPage).then((p) => p.getViewport({ scale: 1 }));
        if (cancelled) return;
        // Leave room for the scrollbar and the page's own drop shadow.
        const byWidth = (el.clientWidth - 48) / viewport.width;
        const byHeight = (el.clientHeight - 48) / viewport.height;
        const next = zoomMode === 'width' ? byWidth : Math.min(byWidth, byHeight);
        setScale(Math.max(0.2, Math.min(4, +next.toFixed(3))));
      } catch {
        /* a page that will not report a viewport keeps the current scale */
      }
    };

    fit();
    const observer = new ResizeObserver(fit);
    if (containerRef.current) observer.observe(containerRef.current);
    return () => { cancelled = true; observer.disconnect(); };
  }, [zoomMode, doc, currentPage]);

  const registerSlot = useCallback((el: HTMLDivElement | null, pageNum: number) => {
    if (el) {
      pageSlotRefs.current.set(pageNum, el);
      observerRef.current?.observe(el);
      // A scroll requested before the target slot existed, replayed now.
      if (pendingScroll.current === pageNum) {
        pendingScroll.current = null;
        requestAnimationFrame(() => el.scrollIntoView({ behavior: 'smooth', block: 'start' }));
      }
    } else {
      const prev = pageSlotRefs.current.get(pageNum);
      if (prev) observerRef.current?.unobserve(prev);
      pageSlotRefs.current.delete(pageNum);
    }
  }, []);

  // Continuous mode: track the topmost visible page and keep a *window* of
  // pages rendered around it. See `WINDOW_BEFORE` for why this replaces the
  // previous ever-growing range.
  useEffect(() => {
    if (!continuous || numPages === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        let topPage: number | null = null;
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const page = Number(entry.target.getAttribute('data-page'));
          if (page && (topPage === null || page < topPage)) topPage = page;
        });
        if (topPage === null) return;
        const top: number = topPage;
        setCurrentPage(top);
        setPageInputValue(String(top));
        setRenderedRange([
          Math.max(1, top - WINDOW_BEFORE),
          Math.min(numPages, top + WINDOW_AFTER),
        ]);
      },
      { rootMargin: '600px 0px', threshold: 0.05 },
    );
    observerRef.current = observer;
    pageSlotRefs.current.forEach((el) => observer.observe(el));
    return () => {
      observer.disconnect();
      observerRef.current = null;
    };
  }, [continuous, numPages]);

  // When switching to continuous, scroll to the page that was being read.
  useEffect(() => {
    if (!continuous) return;
    const p = currentPage;
    setRenderedRange([Math.max(1, p - WINDOW_BEFORE), Math.min(numPages, p + WINDOW_AFTER)]);
    requestAnimationFrame(() => {
      pageSlotRefs.current.get(p)?.scrollIntoView({ behavior: 'instant', block: 'start' });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [continuous]);

  const goToPage = useCallback(
    (page: number) => {
      const p = Math.max(1, Math.min(page, numPages || 1));
      if (continuous) {
        setRenderedRange([
          Math.max(1, p - WINDOW_BEFORE),
          Math.min(numPages, p + WINDOW_AFTER),
        ]);
        const slot = pageSlotRefs.current.get(p);
        if (slot) {
          requestAnimationFrame(() => slot.scrollIntoView({ behavior: 'smooth', block: 'start' }));
        } else {
          // The window above will mount it on the next render; `registerSlot`
          // replays the scroll then. Without this, jumping from page 3 to
          // page 400 scrolled to nothing.
          pendingScroll.current = p;
        }
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

  const setManualScale = useCallback((update: (s: number) => number) => {
    setZoomMode('manual');
    setScale((s) => update(s));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const zoomIn = useCallback(
    () => setManualScale((s) => Math.min(4, +(s + 0.2).toFixed(2))), [setManualScale]);
  const zoomOut = useCallback(
    () => setManualScale((s) => Math.max(0.2, +(s - 0.2).toFixed(2))), [setManualScale]);
  const zoomReset = useCallback(() => setManualScale(() => 1.2), [setManualScale]);

  // ── Selection ─────────────────────────────────────────────────────────────
  //
  // The selection no longer yanks the sidebar open. It raises a toolbar over
  // the selection, and the reader decides from there.
  const handleTextSelection = useCallback(() => {
    const found = readSelection(window);
    if (!found) return;
    setSelection(found);
    setSelectedText(found.text);
    setSurroundingText(found.surrounding);
  }, []);

  const dismissToolbar = useCallback(() => setSelection(null), []);

  const openSidebar = useCallback((tab: SidebarTab) => {
    setSidebarTab(tab);
    setSidebarOpen(true);
    setSelection(null);
  }, []);

  const addHighlight = useCallback((color: string) => {
    if (!selectedText) return;
    createAnnotation({
      book_id: id || '',
      kind: 'highlight',
      text: selectedText,
      color,
      page: currentPage,
    });
    setSelection(null);
    clearSelection(window);
  }, [createAnnotation, currentPage, id, selectedText]);

  const addNote = useCallback(() => {
    if (!selectedText) return;
    createAnnotation({
      book_id: id || '',
      kind: 'note',
      text: selectedText,
      color: 'yellow',
      page: currentPage,
    });
    openSidebar('annotations');
    clearSelection(window);
  }, [createAnnotation, currentPage, id, openSidebar, selectedText]);

  const addBookmark = useCallback(() => {
    createAnnotation({
      book_id: id || '',
      kind: 'bookmark',
      text: '',
      note: `Page ${currentPage}`,
      page: currentPage,
    });
  }, [createAnnotation, currentPage, id]);

  const navigateToAnnotation = useCallback((annotation: Annotation) => {
    if (annotation.page) goToPage(annotation.page);
  }, [goToPage]);

  /** Jump to a retrieved passage inside this book (§1.9.1). */
  const navigateToPassage = useCallback((passage: Passage) => {
    if (passage.page_start) goToPage(passage.page_start);
  }, [goToPage]);

  // Arriving on a deep link from a passage card elsewhere in the library.
  //
  // Deferred until the document reports its page count, because `goToPage`
  // clamps against `numPages` and would otherwise pin every deep link to page
  // 1. Handled once, and the params are cleared afterwards so a later
  // in-reader navigation is not undone by a stale URL on the next render.
  useEffect(() => {
    if (deepLinkHandled.current || !numPages || !deepLinkPage) return;
    deepLinkHandled.current = true;
    goToPage(deepLinkPage);
    const next = new URLSearchParams(searchParams);
    next.delete('page');
    next.delete('chunk');
    setSearchParams(next, { replace: true });
  }, [numPages, deepLinkPage, goToPage, searchParams, setSearchParams]);

  const handlePageInput = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter') {
        const val = parseInt(pageInputValue, 10);
        if (!isNaN(val)) goToPage(val);
      }
    },
    [pageInputValue, goToPage],
  );

  // Single-key toggles that are specific to this reader.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
        return;
      }
      if ((e.key === 'f' || e.key === 'F') && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        setSearchOpen(true);
        return;
      }
      if (e.ctrlKey || e.metaKey) return;
      if (e.key === 'c') { e.preventDefault(); setContinuous((c) => !c); }
      if (e.key === 'p') { e.preventDefault(); setThumbsOpen(!thumbsOpen); }
      if (e.key === 'b') { e.preventDefault(); addBookmark(); }
      if (e.key === '/') { e.preventDefault(); setSearchOpen(true); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [addBookmark, thumbsOpen, setThumbsOpen]);

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
    onToggleToc: () => setOutlineOpen((o) => !o),
    onGoBack: () => {
      if (searchOpen) setSearchOpen(false);
      else if (fullscreen) setFullscreen(false);
      else navigate(`/books/${id}`);
    },
    disabled: false,
  });

  /** Resolve this page's highlight spans once its text content is available. */
  const resolveRuns = useCallback(
    (pageNum: number, items: { str: string }[]) => {
      const highlights = highlightsByPage.get(pageNum) ?? [];
      const marks = mapHighlightsToRuns(items, highlights);
      setRunMarks((prev) => {
        const existing = prev.get(pageNum);
        // Bail out when nothing changed, or every text-content callback would
        // schedule a render and re-trigger the next one.
        if (!existing?.size && !marks.size) return prev;
        const next = new Map(prev);
        next.set(pageNum, marks);
        return next;
      });
    },
    [highlightsByPage],
  );

  // A page's resolved spans are stale the moment its highlights change, and
  // the text-content callback will not fire again on its own.
  useEffect(() => setRunMarks(new Map()), [highlightsByPage]);

  /**
   * The text-layer renderer for one page.
   *
   * Rebuilt per page so each closes over only its own marks.
   */
  const textRendererFor = useCallback(
    (pageNum: number) => {
      const marks = runMarks.get(pageNum);
      if (!marks?.size && !searchQuery) return undefined;
      return ({ str, itemIndex }: { str: string; itemIndex: number }) =>
        renderRun(str, marks?.get(itemIndex), searchQuery);
    },
    [runMarks, searchQuery],
  );

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

  const iconButton = 'rounded p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700';
  const activeButton =
    'rounded p-1.5 bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300';

  const renderPage = (pageNum: number) => (
    <Page
      pageNumber={pageNum}
      scale={scale}
      className="shadow-xl"
      renderTextLayer
      renderAnnotationLayer
      onGetTextSuccess={({ items }) => resolveRuns(pageNum, items as { str: string }[])}
      customTextRenderer={textRendererFor(pageNum)}
    />
  );

  return (
    <div
      className={`flex ${fullscreen ? 'fixed inset-0 z-50 bg-white dark:bg-slate-900' : 'h-[calc(100vh-56px)]'}`}
    >
      {/* Page thumbnails (§2.1) */}
      {thumbsOpen && (
        <PdfThumbnails
          doc={doc}
          numPages={numPages}
          currentPage={currentPage}
          onNavigate={goToPage}
        />
      )}

      {/* Outline / table of contents */}
      {outlineOpen && (
        <aside className="hidden w-64 shrink-0 flex-col overflow-y-auto border-r border-slate-200 bg-slate-50 p-2 dark:border-slate-700 dark:bg-slate-800/50 md:flex">
          <p className="px-1.5 pb-2 text-xs font-semibold text-slate-500">Contents</p>
          <PdfOutline doc={doc} currentPage={currentPage} onNavigate={goToPage} />
        </aside>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Toolbar */}
        <div className="flex items-center gap-2 border-b border-slate-200 bg-white px-3 py-1.5 dark:border-slate-700 dark:bg-slate-800">
          <Link
            to={`/books/${id}`}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-700"
          >
            <ArrowLeft size={16} />
            <span className="hidden max-w-48 truncate sm:inline">{book.title}</span>
          </Link>

          <div className="mx-1 hidden h-4 w-px bg-slate-200 dark:bg-slate-700 sm:block" />

          <button
            onClick={() => setOutlineOpen((o) => !o)}
            className={outlineOpen ? activeButton : iconButton}
            title="Table of contents (T)"
            aria-label="Table of contents"
          >
            <List size={16} />
          </button>
          <button
            onClick={() => setThumbsOpen(!thumbsOpen)}
            className={thumbsOpen ? activeButton : iconButton}
            title="Page thumbnails (P)"
            aria-label="Page thumbnails"
          >
            <Images size={16} />
          </button>
          <button
            onClick={() => setSearchOpen((s) => !s)}
            className={searchOpen ? activeButton : iconButton}
            title="Search in this book (/)"
            aria-label="Search in this book"
          >
            <Search size={16} />
          </button>

          <div className="mx-1 hidden h-4 w-px bg-slate-200 dark:bg-slate-700 sm:block" />

          <div className="flex items-center gap-1">
            <button onClick={prevPage} disabled={currentPage <= 1}
                    className={`${iconButton} disabled:opacity-30`} title="Previous page (←)">
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
                aria-label="Page number"
                className="w-10 rounded border border-slate-200 bg-transparent px-1.5 py-0.5 text-center text-xs tabular-nums dark:border-slate-600"
              />
              <span>/ {numPages}</span>
            </div>
            <button onClick={nextPage} disabled={currentPage >= numPages}
                    className={`${iconButton} disabled:opacity-30`} title="Next page (→)">
              <ChevronRight size={16} />
            </button>
          </div>

          <div className="mx-1 hidden h-4 w-px bg-slate-200 dark:bg-slate-700 sm:block" />

          <div className="flex items-center gap-1">
            <button onClick={zoomOut} className={iconButton} title="Zoom out (-)">
              <ZoomOut size={15} />
            </button>
            <span className="min-w-10 text-center text-xs tabular-nums text-slate-400">
              {Math.round(scale * 100)}%
            </span>
            <button onClick={zoomIn} className={iconButton} title="Zoom in (+)">
              <ZoomIn size={15} />
            </button>
            <button
              onClick={() => setZoomMode(zoomMode === 'width' ? 'manual' : 'width')}
              className={zoomMode === 'width' ? activeButton : iconButton}
              title="Fit width"
              aria-label="Fit width"
            >
              <MoveHorizontal size={15} />
            </button>
            <button
              onClick={() => setZoomMode(zoomMode === 'page' ? 'manual' : 'page')}
              className={zoomMode === 'page' ? activeButton : iconButton}
              title="Fit page"
              aria-label="Fit page"
            >
              <Minimize2 size={15} />
            </button>
          </div>

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

          <div className="flex-1" />

          <button onClick={addBookmark} className={iconButton} title="Bookmark this page (B)"
                  aria-label="Bookmark this page">
            <Bookmark size={15} />
          </button>
          <ReaderSettings
            open={settingsOpen}
            onToggle={() => setSettingsOpen((s) => !s)}
            onClose={() => setSettingsOpen(false)}
            theme={readingTheme}
            onThemeChange={setReadingTheme}
          />
          <a href={pdfUrl} download={book.file_name} className={iconButton} title="Download">
            <Download size={15} />
          </a>
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className={sidebarOpen ? activeButton : iconButton}
            title={sidebarOpen ? 'Close sidebar (S)' : 'Open sidebar (S)'}
          >
            {sidebarOpen ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}
          </button>
          <button onClick={() => setFullscreen(!fullscreen)} className={iconButton}
                  title={fullscreen ? 'Exit fullscreen (F)' : 'Fullscreen (F)'}>
            {fullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
          </button>
        </div>

        {searchOpen && (
          <PdfSearch
            doc={doc}
            onNavigate={goToPage}
            onQueryChange={setSearchQuery}
            onClose={() => setSearchOpen(false)}
          />
        )}

        {/* PDF canvas */}
        <div
          ref={containerRef}
          className="flex-1 overflow-auto"
          style={{ background: themeMeta.pdfBackground }}
          onMouseUp={handleTextSelection}
        >
          <div
            className={`flex min-h-full py-4 ${continuous ? 'flex-col items-center' : 'items-start justify-center'}`}
            // The filter lands on the wrapper, not the page, so the canvas and
            // its text layer are tinted as one — otherwise `invert` on the
            // canvas alone would leave highlights and search marks inverted
            // relative to the ink they sit on.
            style={{ filter: themeMeta.pdfFilter }}
          >
            <Document
              file={pdfUrl}
              onLoadSuccess={(loaded: PDFDocumentProxy) => {
                setDoc(loaded);
                setNumPages(loaded.numPages);
                setRenderedRange([1, Math.min(1 + WINDOW_AFTER, loaded.numPages)]);
              }}
              loading={
                <div className="flex items-center gap-3 p-12 text-slate-500">
                  <Spinner size={20} /> Loading PDF...
                </div>
              }
              error={
                <div className="p-12 text-center text-red-500">
                  <p className="font-medium">Failed to load PDF</p>
                  <a href={pdfUrl} download className="mt-2 inline-block text-sm text-primary-600 hover:underline">
                    Download instead
                  </a>
                </div>
              }
            >
              {continuous ? (
                Array.from({ length: numPages }, (_, i) => i + 1).map((pageNum) => {
                  const inRange = pageNum >= renderedRange[0] && pageNum <= renderedRange[1];
                  const estimatedH = Math.round(ESTIMATED_PAGE_HEIGHT * scale + 16);
                  return (
                    <div
                      key={pageNum}
                      ref={(el) => registerSlot(el as HTMLDivElement | null, pageNum)}
                      data-page={pageNum}
                      className="mb-4 flex w-full justify-center"
                      style={{ minHeight: inRange ? undefined : estimatedH }}
                    >
                      {inRange && renderPage(pageNum)}
                    </div>
                  );
                })
              ) : (
                renderPage(currentPage)
              )}
            </Document>
          </div>
        </div>

        {/* Bottom bar */}
        <div className="flex items-center justify-between border-t border-slate-200 bg-white px-4 py-1.5 text-xs text-slate-400 dark:border-slate-700 dark:bg-slate-800">
          <span>
            Page {currentPage} of {numPages}{continuous ? ' · scroll' : ''}
            {numPages > 0 && (
              <span className="ml-2 tabular-nums">· {Math.round((currentPage / numPages) * 100)}%</span>
            )}
          </span>
          <span className="hidden text-[10px] sm:inline">
            {continuous ? '↑↓ Scroll · J/K page jump' : '← → Navigate'}
            &nbsp;·&nbsp; / Search &nbsp;·&nbsp; B Bookmark &nbsp;·&nbsp; C Mode &nbsp;·&nbsp; T
            Contents &nbsp;·&nbsp; F Fullscreen &nbsp;·&nbsp; S Sidebar
          </span>
          <span>{book.file_type.toUpperCase()}</span>
        </div>
      </div>

      {selection && (
        <SelectionToolbar
          text={selection.text}
          rect={selection.rect}
          onHighlight={addHighlight}
          onNote={addNote}
          onAsk={() => openSidebar('analysis')}
          onCompare={() => openSidebar('analysis')}
          onDismiss={dismissToolbar}
        />
      )}

      {sidebarOpen && (
        <ReaderSidebar
          bookId={id || ''}
          bookTitle={book.title}
          selectedText={selectedText}
          surroundingText={surroundingText}
          tab={sidebarTab}
          onTabChange={setSidebarTab}
          onNavigateToAnnotation={navigateToAnnotation}
          onNavigateToPassage={navigateToPassage}
          page={currentPage}
          onClose={() => setSidebarOpen(false)}
        />
      )}
    </div>
  );
}
