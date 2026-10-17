import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams, Link } from 'react-router-dom';
import {
  ArrowLeft,
  Bookmark,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  List,
  Maximize2,
  Minimize2,
  PanelRightClose,
  PanelRightOpen,
  ScrollText,
  Search,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';

import { useBook } from '../../api/books';
import { useAnnotations, useCreateAnnotation } from '../../api/annotations';
import { useReaderKeyboard } from '../../hooks/useReaderKeyboard';
import { useReadingProgress } from '../../hooks/useReadingProgress';
import { useReadingSession } from '../../hooks/useReadingSession';
import { useEpubLocations } from '../../hooks/useEpubLocations';
import { useLocalStorage } from '../../hooks/useLocalStorage';
import { useTheme } from '../../hooks/useTheme';
import { Spinner } from '../common/Spinner';
import { ErrorState } from '../common/ErrorBoundary';
import { ReaderSidebar, type SidebarTab } from './ReaderSidebar';
import { SelectionToolbar } from './SelectionToolbar';
import { ReaderSettings } from './ReaderSettings';
import { EpubSearch } from './EpubSearch';
import { readSelection, clearSelection, type ReaderSelection } from './selection';
import {
  DEFAULT_TYPOGRAPHY,
  epubThemeStyles,
  resolveReadingTheme,
  type EpubTypography,
  type ReadingTheme,
} from './readingTheme';
import { HIGHLIGHT_COLORS } from './SelectionToolbar';
import type { Annotation, Passage } from '../../api/types';

/** The shape of epub.js's `relocated` payload that we actually read. */
interface EpubLocation {
  start?: { cfi?: string; index?: number; percentage?: number };
}

interface EpubContents {
  window?: Window;
  /** epub.js's range → CFI conversion, scoped to this section. */
  cfiFromRange?: (range: Range) => string;
}

export interface EpubRendition {
  themes: {
    default: (styles: Record<string, Record<string, string>>) => void;
    fontSize: (size: string) => void;
  };
  annotations?: {
    add: (
      type: string, cfi: string, data?: object, cb?: () => void,
      className?: string, styles?: Record<string, string>,
    ) => void;
    remove: (cfi: string, type: string) => void;
  };
  on: (event: string, cb: (...args: unknown[]) => void) => void;
  getContents?: () => EpubContents[] | EpubContents;
  display: (target?: string) => Promise<void>;
  next: () => void;
  prev: () => void;
  book?: {
    spine?: {
      length?: number;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      get?: (target: number | string) => any;
    };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ready?: Promise<any>;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    spine_?: any;
    /** Present once `useEpubLocations` has generated or loaded the index. */
    locations?: {
      length?: () => number;
      load?: (saved: string) => void;
      save?: () => string;
      generate?: (chars: number) => Promise<unknown>;
      locationFromCfi?: (cfi: string) => number;
    };
  };
}

function swatch(color: string): string {
  return HIGHLIGHT_COLORS.find((c) => c.id === color)?.swatch ?? '#fde68a';
}

/**
 * How long the paragraph a retrieved passage landed on stays marked.
 *
 * Long enough to find without looking for it, short enough that it cannot be
 * mistaken for a highlight the reader saved. Matches the PDF reader.
 */
const PASSAGE_FLASH_MS = 9000;

/**
 * How many 250 ms turns to spend searching a *rendered* section for a
 * passage's anchor text, and how long to wait for one to render at all.
 *
 * Twelve turns of 250 ms was the whole budget, counted from the jump, so it
 * expired 3.3 seconds in — before a cold EPUB has put a single character in
 * its iframe. See `goToSpine`.
 */
const ANCHOR_ATTEMPTS = 12;
const ANCHOR_DEADLINE_MS = 30_000;

export function EpubReader() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: book, isLoading, isError, error, refetch } = useBook(id || '');
  const [appTheme] = useTheme();

  const [location, setLocation] = useState<string | number>(0);
  const [fullscreen, setFullscreen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>('analysis');
  const [selection, setSelection] = useState<ReaderSelection | null>(null);
  const [selectedText, setSelectedText] = useState('');
  const [surroundingText, setSurroundingText] = useState('');
  const [selectedCfi, setSelectedCfi] = useState('');
  const [showToc, setShowToc] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [fontSize, setFontSize] = useLocalStorage('reader.epub.fontSize', 100);
  const [readingTheme, setReadingTheme] = useLocalStorage<ReadingTheme>('reader.theme', 'paper');
  const [typography, setTypography] =
    useLocalStorage<EpubTypography>('reader.epub.typography', DEFAULT_TYPOGRAPHY);
  // Scroll is the default and the choice sticks; see the PDF reader.
  const [continuous, setContinuousStored] = useLocalStorage('reader.epub.continuous', true);
  const continuousRef = useRef(continuous);
  continuousRef.current = continuous;
  const toggleContinuous = useCallback(
    () => setContinuousStored(!continuousRef.current), [setContinuousStored]);
  const [percent, setPercent] = useState(0);
  // Exact position, once the locations index exists. 0 until then, and the
  // spine ratio carries the progress bar in the meantime.
  const [locationIndex, setLocationIndex] = useState(0);
  const [epubBook, setEpubBook] = useState<EpubRendition['book'] | null>(null);
  // Set on the first relocation — i.e. once there is text on screen. The
  // locations walk is deferred until then so it cannot delay the first paint.
  const [hasRendered, setHasRendered] = useState(false);
  const bookRef = useRef<EpubRendition['book'] | null>(null);

  const [searchParams, setSearchParams] = useSearchParams();
  const spineParam = searchParams.get('spine');
  const deepLinkSpine = spineParam === null ? null : Number(spineParam);
  const deepLinkAnchor = searchParams.get('anchor') || '';
  const deepLinkHandled = useRef(false);

  const recordProgress = useReadingProgress(book);
  useReadingSession(id || '');
  const { total: locationTotal, generating: locationsBuilding } =
    useEpubLocations(id || '', epubBook, hasRendered);
  const recordRef = useRef(recordProgress);
  recordRef.current = recordProgress;
  // The reader reports its opening position immediately, which would
  // overwrite the saved CFI with the cover before we ever restore it.
  const restored = useRef(false);

  const { data: annotationData } = useAnnotations(id || '');
  const { mutate: createAnnotation } = useCreateAnnotation(id || '');

  const theme = resolveReadingTheme(readingTheme, appTheme);
  const themeStyles = useMemo(
    () => epubThemeStyles(theme, typography), [theme, typography]);

  // Resume where the book was left. The EPUB location was component state and
  // nothing persisted it, so every open started at the cover.
  useEffect(() => {
    if (restored.current || !book) return;
    restored.current = true;
    // A deep link is an explicit destination and outranks the saved position.
    if (deepLinkSpine !== null) return;
    if (book.reader_position) setLocation(book.reader_position);
  }, [book, deepLinkSpine]);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [ReaderComponent, setReaderComponent] = useState<React.ComponentType<any> | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const renditionRef = useRef<EpubRendition | null>(null);

  // `getRendition` is handed to the reader once and captures whatever the
  // render it was created in saw. Read live values through refs instead, or
  // the rendition applies a frozen 100% font size and a frozen theme.
  const fontSizeRef = useRef(fontSize);
  fontSizeRef.current = fontSize;
  const themeStylesRef = useRef(themeStyles);
  themeStylesRef.current = themeStyles;

  // Dynamically import react-reader.
  //
  // This was a `useState(() => …)` initialiser, which StrictMode runs twice —
  // so the module was imported twice on every mount.
  useEffect(() => {
    let cancelled = false;
    import('react-reader')
      .then((mod) => { if (!cancelled) setReaderComponent(() => mod.ReactReader); })
      .catch(() => { if (!cancelled) setLoadError('Failed to load EPUB reader library'); });
    return () => { cancelled = true; };
  }, []);

  // Re-apply theme and typography to a live rendition. Without this, changing
  // the typeface only took effect after a remount.
  useEffect(() => {
    renditionRef.current?.themes.default(themeStyles);
  }, [themeStyles]);

  useEffect(() => {
    renditionRef.current?.themes.fontSize(`${fontSize}%`);
  }, [fontSize]);

  // Repaint stored highlights onto the rendition. epub.js keeps its own
  // annotation registry per rendition, so this runs on every remount (the
  // paginated/scrolled toggle remounts) as well as on every change.
  useEffect(() => {
    const rendition = renditionRef.current;
    const annotations = annotationData?.annotations ?? [];
    if (!rendition?.annotations) return;

    const painted: string[] = [];
    for (const a of annotations) {
      if (a.kind !== 'highlight' || !a.cfi) continue;
      try {
        rendition.annotations.add(
          'highlight', a.cfi, { id: a.id }, undefined, 'epub-highlight',
          { fill: swatch(a.color), 'fill-opacity': '0.35', 'mix-blend-mode': 'multiply' },
        );
        painted.push(a.cfi);
      } catch {
        // A CFI that no longer resolves — the book was re-encoded, or the
        // spine shifted. `anchor_text` is the fallback and the sidebar can
        // still show the passage; only the in-page tint is lost.
      }
    }
    return () => {
      for (const cfi of painted) {
        try { rendition.annotations?.remove(cfi, 'highlight'); } catch { /* already gone */ }
      }
    };
  }, [annotationData, ReaderComponent, continuous]);

  const flipNext = useCallback(() => renditionRef.current?.next(), []);
  const flipPrev = useCallback(() => renditionRef.current?.prev(), []);

  /**
   * Scroll mode's ↑/↓ and Space. epub.js's continuous manager scrolls its own
   * `.epub-container`, not the window, so the keys have to be pointed at it.
   */
  const scrollBy = useCallback((direction: 1 | -1, unit: 'line' | 'screen') => {
    const el = document.querySelector<HTMLElement>('.epub-container');
    if (!el) return;
    const step = unit === 'line' ? 80 : el.clientHeight * 0.9;
    el.scrollBy({ top: direction * step, behavior: 'smooth' });
  }, []);

  const increaseFontSize = useCallback(
    () => setFontSize(Math.min(200, fontSize + 10)), [fontSize, setFontSize]);
  const decreaseFontSize = useCallback(
    () => setFontSize(Math.max(60, fontSize - 10)), [fontSize, setFontSize]);
  const resetFontSize = useCallback(() => setFontSize(100), [setFontSize]);

  /**
   * Selection inside the rendered iframe, or the parent as a fallback.
   *
   * `cfi` is supplied by epub.js's own `selected` event. The fallback mouseup
   * listener has no such argument, so the CFI is derived from the range —
   * without it a highlight made through that path would be stored with an
   * empty anchor and could never be repainted or navigated back to.
   */
  const captureSelection = useCallback((win?: Window | null, cfi?: string) => {
    const target = win ?? window;
    const found = readSelection(target);
    if (!found) return;
    setSelection(found);
    setSelectedText(found.text);
    setSurroundingText(found.surrounding);
    setSelectedCfi(cfi || cfiFromSelection(renditionRef.current, target));
  }, []);

  const handleRendition = useCallback((rendition: EpubRendition) => {
    renditionRef.current = rendition;
    // Hand the book to `useEpubLocations`; it owns generating and caching the
    // index, which is what turns the spine ratio into an exact page number.
    //
    // Guarded, and via a ref: a bare `setState` here re-renders the reader
    // from inside its own `getRendition` callback, and react-reader responds
    // by tearing the rendition down and building a new one — which calls this
    // again. The EPUB was being fetched three times per open.
    if (bookRef.current !== rendition.book) {
      bookRef.current = rendition.book ?? null;
      setEpubBook(rendition.book ?? null);
    }
    // Whatever the reader had set before this rendition was created — not the
    // initial values this callback used to close over.
    rendition.themes.default(themeStylesRef.current);
    rendition.themes.fontSize(`${fontSizeRef.current}%`);

    // Listen for text selection inside the epub iframe.
    //
    // The selection lives in the iframe's own window, so the parent
    // `window.getSelection()` this used to call was always empty — which is
    // why selecting text in an EPUB never opened the analysis sidebar. epub.js
    // hands us the `contents` for the section the selection happened in, and
    // the CFI for the range, which is the anchor a highlight is stored against.
    rendition.on('selected', (...args: unknown[]) => {
      const cfi = typeof args[0] === 'string' ? args[0] : '';
      const contents = args[1] as EpubContents | undefined;
      captureSelection(contents?.window, cfi);
    });

    // Keys pressed inside the book reach the reader's shortcuts.
    //
    // Clicking into the text puts focus in epub.js's iframe, whose key events
    // never reach this window — so after the first click Space, Esc, S, F and
    // the rest did nothing until the reader clicked the toolbar. epub.js
    // relays the iframe's DOM events through the rendition; this re-raises
    // them here, and hands a `preventDefault` back so a key a shortcut
    // handled does not also scroll the iframe.
    rendition.on('keydown', (...args: unknown[]) => {
      const e = args[0] as KeyboardEvent | undefined;
      if (!e?.key) return;
      const relayed = new KeyboardEvent('keydown', {
        key: e.key, code: e.code, shiftKey: e.shiftKey, ctrlKey: e.ctrlKey,
        metaKey: e.metaKey, altKey: e.altKey, cancelable: true,
      });
      window.dispatchEvent(relayed);
      if (relayed.defaultPrevented) e.preventDefault();
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
      // Same reason as `bookRef`: this fires on every relocation, and an
      // unconditional setState here would re-render the reader on every page
      // turn for a flag that only ever goes false → true once.
      setHasRendered((already) => already || true);
      // `locationFromCfi` is a binary search over the cached index, so it is
      // cheap enough to run on every relocation — but it returns -1 until the
      // index exists, which must not be shown as "page 0".
      try {
        const found = rendition.book?.locations?.locationFromCfi?.(cfi);
        if (typeof found === 'number' && found >= 0) setLocationIndex(found + 1);
      } catch {
        /* no locations index yet */
      }
      recordRef.current(pct, cfi);
      // A relocation means the selection has scrolled away from its toolbar.
      setSelection(null);
    });
  }, [captureSelection]);

  const openSidebar = useCallback((tab: SidebarTab) => {
    setSidebarTab(tab);
    setSidebarOpen(true);
    setSelection(null);
  }, []);

  const addHighlight = useCallback((color: string) => {
    if (!selectedText) return;
    createAnnotation({
      book_id: id || '', kind: 'highlight', text: selectedText, color, cfi: selectedCfi,
    });
    setSelection(null);
    clearSelection(currentFrameWindow());
  }, [createAnnotation, id, selectedCfi, selectedText]);

  const addNote = useCallback(() => {
    if (!selectedText) return;
    createAnnotation({
      book_id: id || '', kind: 'note', text: selectedText, color: 'yellow', cfi: selectedCfi,
    });
    openSidebar('annotations');
    clearSelection(currentFrameWindow());
  }, [createAnnotation, id, openSidebar, selectedCfi, selectedText]);

  const addBookmark = useCallback(() => {
    createAnnotation({
      book_id: id || '',
      kind: 'bookmark',
      text: '',
      note: `${Math.round(percent)}% through`,
      cfi: typeof location === 'string' ? location : '',
    });
  }, [createAnnotation, id, location, percent]);

  const goToCfi = useCallback((cfi: string) => {
    if (!cfi) return;
    // Navigation goes through the `location` prop and nowhere else.
    //
    // Calling `rendition.display(cfi)` here as well raced react-reader's own
    // call for the same target: epub.js rendered the section but left the
    // paginated column offset pointing at the other display's result, so a
    // search hit or a bookmark navigated to a *blank page* with the text
    // sitting just off-screen in a 10,000px-wide strip.
    setLocation(cfi);
  }, []);

  const navigateToAnnotation = useCallback((annotation: Annotation) => {
    goToCfi(annotation.cfi);
  }, [goToCfi]);

  /**
   * Navigate to a spine item, then locate `anchorText` inside it.
   *
   * §1.5 chose this over a CFI deliberately: generating a true CFI offline, in
   * the indexer, is painful, so a chunk stores its spine index and the first
   * ~60 characters of its text instead. Displaying the section is exact;
   * finding the anchor within it is best-effort, and a miss simply leaves the
   * reader at the top of the right chapter rather than nowhere.
   *
   * Navigation goes through `location` and nowhere else. Calling
   * `rendition.display()` here as well is the bug §2.2 records: epub.js
   * rendered the section but left the paginated column offset pointing at the
   * other call's result, and every jump landed on a blank page.
   */
  /**
   * Mark the paragraph the jump landed on, then put it back.
   *
   * Scrolling a passage into view and leaving it unmarked asks the reader to
   * find, in the middle of a rendered chapter, the paragraph the search had
   * already located. The styles go on inline and are restored verbatim
   * afterwards: this is inside epub.js's iframe, whose document is replaced
   * on every relocation, so a class would need a stylesheet injected into a
   * document that is about to be thrown away.
   */
  const flashElement = useCallback((element: HTMLElement | null) => {
    if (!element) return;
    const previous = element.getAttribute('style') || '';
    element.style.transition = 'background-color 400ms ease-out';
    element.style.backgroundColor = 'rgba(129, 140, 248, 0.35)';
    element.style.borderRadius = '3px';
    window.setTimeout(() => {
      if (previous) element.setAttribute('style', previous);
      else element.removeAttribute('style');
    }, PASSAGE_FLASH_MS);
  }, []);

  const goToSpine = useCallback((spineIndex: number, anchorText: string): boolean => {
    const rendition = renditionRef.current;
    const href = rendition?.book?.spine?.get?.(spineIndex)?.href;
    // Not "this book has no such section" — far more often "the spine has not
    // been parsed yet". Saying which is the caller's problem, so this reports
    // whether the jump happened rather than failing silently.
    if (!href) return false;
    setLocation(href);

    if (!anchorText) return true;
    // The section has to render before its text can be searched, and epub.js
    // offers no "rendered" promise for a `location` change — so this waits for
    // the relocation to land, then gives up rather than polling forever.
    //
    // **Only turns that had something to search count against the budget.**
    // Counting every turn meant the budget was really a timeout, and a cold
    // EPUB — the first one opened, with the file still arriving and epub.js
    // still laying out columns — spent all of it staring at an empty iframe
    // and gave up a second before the text appeared. Measured in the browser:
    // the document was empty for the first ~15 s and the old 3.3 s budget
    // never saw a single character of it. The deadline is what stops this
    // polling forever, and it is generous because the cost of one more turn
    // is a `querySelector` on a document that is already in memory.
    const needle = anchorText.slice(0, 40).trim();
    const deadline = Date.now() + ANCHOR_DEADLINE_MS;
    let attempts = 0;
    const findIt = () => {
      const doc = currentFrameWindow()?.document;
      const ready = !!doc?.body && (doc.body.textContent || '').trim().length > 0;
      if (ready && doc) {
        attempts += 1;
        const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
        let node: Node | null = walker.nextNode();
        while (node) {
          if ((node.textContent || '').includes(needle)) {
            const element = node.parentElement as HTMLElement | null;
            element?.scrollIntoView({ behavior: 'smooth', block: 'center' });
            flashElement(element);
            return;
          }
          node = walker.nextNode();
        }
      }
      if (attempts < ANCHOR_ATTEMPTS && Date.now() < deadline) {
        window.setTimeout(findIt, 250);
      }
    };
    window.setTimeout(findIt, 350);
    return true;
  }, [flashElement]);

  const navigateToPassage = useCallback((passage: Passage) => {
    if (passage.spine_index !== null && passage.spine_index !== undefined) {
      goToSpine(passage.spine_index, passage.anchor_text);
    }
  }, [goToSpine]);

  // Arriving on a deep link: /read/{id}?spine=12&chunk=…
  //
  // Deferred until the rendition exists, and handled once. The params are
  // cleared afterwards so a later in-reader navigation is not undone by a
  // stale URL on the next render.
  useEffect(() => {
    if (deepLinkHandled.current || deepLinkSpine === null) return;

    // Retried until the jump lands, not attempted once and abandoned.
    //
    // The effect used to fire on the first render where a rendition existed
    // and mark itself handled whatever happened — but a rendition exists
    // before its book's spine is parsed, so `spine.get()` returned nothing,
    // the jump was dropped, and the deep link left the reader wherever they
    // had been last time. There is no event for "spine ready", and the whole
    // check is a property lookup, so this asks again until it is.
    let timer = 0;
    const deadline = Date.now() + ANCHOR_DEADLINE_MS;
    const attempt = () => {
      if (goToSpine(deepLinkSpine, deepLinkAnchor)) {
        deepLinkHandled.current = true;
        // Cleared only once the jump has happened: a reload before that
        // should still be able to use them.
        const next = new URLSearchParams(searchParams);
        next.delete('spine');
        next.delete('chunk');
        next.delete('anchor');
        setSearchParams(next, { replace: true });
        return;
      }
      if (Date.now() < deadline) timer = window.setTimeout(attempt, 250);
    };
    attempt();
    return () => window.clearTimeout(timer);
  }, [deepLinkSpine, deepLinkAnchor, goToSpine, searchParams, setSearchParams, epubBook]);

  // Single-key toggles specific to this reader.
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
      if (e.key === 'c') { e.preventDefault(); toggleContinuous(); }
      if (e.key === 'b') { e.preventDefault(); addBookmark(); }
      if (e.key === '/') { e.preventDefault(); setSearchOpen(true); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [addBookmark, toggleContinuous]);

  useReaderKeyboard({
    onNextPage: continuous ? undefined : flipNext,
    onPrevPage: continuous ? undefined : flipPrev,
    onZoomIn: increaseFontSize,
    onZoomOut: decreaseFontSize,
    onZoomReset: resetFontSize,
    onToggleFullscreen: () => setFullscreen((f) => !f),
    onToggleSidebar: () => setSidebarOpen((s) => !s),
    onToggleToc: () => setShowToc((t) => !t),
    onScrollBy: continuous ? scrollBy : undefined,
    onGoBack: () => {
      if (searchOpen) setSearchOpen(false);
      else if (fullscreen) setFullscreen(false);
      else navigate(`/books/${id}`);
    },
    disabled: false,
  });

  // Belt-and-braces selection listener on the rendered iframe.
  //
  // This used to poll for `.ReactReader iframe` — a selector react-reader
  // never renders (the iframe sits inside `.epub-view`), so the interval ran
  // for the lifetime of the component without ever matching and the listener
  // was never attached. It catches selections epub.js's own `selected` event
  // misses, notably in scrolled-doc mode.
  useEffect(() => {
    let detach: (() => void) | undefined;
    const interval = setInterval(() => {
      const iframe = document.querySelector('.epub-view iframe') as HTMLIFrameElement | null;
      const doc = iframe?.contentDocument;
      if (!doc) return;
      const onMouseUp = () => captureSelection(iframe.contentWindow);
      doc.addEventListener('mouseup', onMouseUp);
      detach = () => doc.removeEventListener('mouseup', onMouseUp);
      clearInterval(interval);
    }, 500);
    return () => {
      clearInterval(interval);
      detach?.();
    };
  }, [continuous, ReaderComponent, captureSelection]);

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
          <Link to={`/books/${id}`} className="mt-4 inline-flex items-center gap-1.5 text-sm text-primary-600 hover:underline">
            <ArrowLeft size={16} /> Back to Book
          </Link>
        </div>
      </div>
    );
  }

  // The `.epub` extension is load-bearing: epub.js reads it to decide between
  // opening an archive and crawling an unpacked directory.
  const epubUrl = `/api/books/${id}/file.epub`;

  const iconButton = 'rounded p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700';
  const activeButton =
    'rounded p-1.5 bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300';

  return (
    <div className={`flex ${fullscreen ? 'fixed inset-0 z-50 bg-white dark:bg-slate-900' : 'h-full'}`}>
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
            onClick={() => setSearchOpen((s) => !s)}
            className={searchOpen ? activeButton : iconButton}
            title="Search in this book (/)"
            aria-label="Search in this book"
          >
            <Search size={16} />
          </button>

          {!continuous && (
            <div className="flex items-center gap-1">
              <button onClick={flipPrev} className={iconButton} title="Previous page (←)">
                <ChevronLeft size={16} />
              </button>
              <button onClick={flipNext} className={iconButton} title="Next page (→)">
                <ChevronRight size={16} />
              </button>
            </div>
          )}

          <div className="mx-1 hidden h-4 w-px bg-slate-200 dark:bg-slate-700 sm:block" />

          <div className="flex items-center gap-1">
            <button onClick={decreaseFontSize} className={iconButton} title="Decrease font (-)">
              <ZoomOut size={15} />
            </button>
            <span className="min-w-10 text-center text-xs tabular-nums text-slate-400">{fontSize}%</span>
            <button onClick={increaseFontSize} className={iconButton} title="Increase font (+)">
              <ZoomIn size={15} />
            </button>
          </div>

          <div className="flex-1" />

          <button
            onClick={() => toggleContinuous()}
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

          <button onClick={addBookmark} className={iconButton} title="Bookmark this spot (B)"
                  aria-label="Bookmark this spot">
            <Bookmark size={15} />
          </button>
          <ReaderSettings
            open={settingsOpen}
            onToggle={() => setSettingsOpen((s) => !s)}
            onClose={() => setSettingsOpen(false)}
            theme={readingTheme}
            onThemeChange={setReadingTheme}
            typography={typography}
            onTypographyChange={setTypography}
          />
          <button
            onClick={() => setShowToc(!showToc)}
            className={showToc ? activeButton : iconButton}
            title="Table of contents (T)"
          >
            <List size={16} />
          </button>
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
          <EpubSearch
            rendition={renditionRef.current}
            onNavigate={goToCfi}
            onClose={() => setSearchOpen(false)}
          />
        )}

        {/* EPUB Renderer — key forces remount when flow mode changes */}
        <div className="relative flex-1 overflow-hidden" onMouseUp={() => captureSelection(window)}>
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
              // react-reader flips pages on ←/→ keyup by itself, on top of
              // `useReaderKeyboard`'s keydown — one press turned two pages.
              // A handler of our own switches its binding off.
              handleKeyPress={ignoreKey}
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
            {percent > 0 && <span className="tabular-nums"> · {Math.round(percent)}%</span>}
            {locationTotal > 0 && locationIndex > 0 ? (
              <span className="tabular-nums text-slate-400">
                {' · '}page {locationIndex} of {locationTotal}
              </span>
            ) : locationsBuilding ? (
              <span className="text-slate-400"> · indexing pages…</span>
            ) : null}
          </span>
          <span className="hidden text-[10px] sm:inline">
            {continuous ? '↑↓ Space Scroll' : '← → Navigate'}
            &nbsp;·&nbsp; / Search &nbsp;·&nbsp; B Bookmark &nbsp;·&nbsp; +/- Font &nbsp;·&nbsp; C
            Mode &nbsp;·&nbsp; F Fullscreen &nbsp;·&nbsp; S Sidebar &nbsp;·&nbsp; T TOC
          </span>
          <span>Font: {fontSize}%</span>
        </div>
      </div>

      {selection && (
        <SelectionToolbar
          text={selection.text}
          rect={selection.rect}
          onHighlight={addHighlight}
          onNote={addNote}
          onAsk={() => openSidebar('analysis')}
          // Compare is the passage panel, not the Analysis tab. It used to
          // open Analysis, whose "Similar in Other Books" is the *book*-level
          // comparison: one vector per book, cards that link to a book's
          // detail page, and no way back to the paragraph that matched. The
          // reader had asked about a paragraph, so the answer is paragraphs —
          // and those carry a page or a section and jump to it.
          onCompare={() => openSidebar('passages')}
          onDismiss={() => setSelection(null)}
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
          cfi={typeof location === 'string' ? location : ''}
          onClose={() => setSidebarOpen(false)}
        />
      )}
    </div>
  );
}

/**
 * The CFI for the current selection in `win`, via the epub.js `Contents` that
 * owns that window. Empty when the selection is not inside a rendered section.
 */
function cfiFromSelection(rendition: EpubRendition | null, win: Window): string {
  try {
    const raw = rendition?.getContents?.();
    if (!raw) return '';
    const all = Array.isArray(raw) ? raw : [raw];
    const contents = all.find((c) => c.window === win) ?? all[0];
    const selection = win.getSelection();
    const range = selection?.rangeCount ? selection.getRangeAt(0) : null;
    if (!range || !contents?.cfiFromRange) return '';
    return contents.cfiFromRange(range) || '';
  } catch {
    return '';
  }
}

/** Swallows react-reader's built-in arrow-key paging; see its use. */
function ignoreKey(): void {}

/** The window of the currently rendered EPUB section, for clearing selections. */
function currentFrameWindow(): Window | null {
  const iframe = document.querySelector('.epub-view iframe') as HTMLIFrameElement | null;
  return iframe?.contentWindow ?? null;
}
