import { useCallback, useEffect, useRef, useState } from 'react';
import { Page } from 'react-pdf';
import type { PDFDocumentProxy } from 'pdfjs-dist';

interface PdfThumbnailsProps {
  doc: PDFDocumentProxy | null;
  numPages: number;
  currentPage: number;
  onNavigate: (page: number) => void;
}

/** Rendered width of one thumbnail, in CSS pixels. */
const THUMB_WIDTH = 104;

/**
 * How many thumbnails either side of the visible strip stay rendered.
 *
 * The same lesson as `WINDOW_BEFORE`/`WINDOW_AFTER` in `PdfReader`, and the
 * reason this strip is windowed at all: a thumbnail is still a canvas, and
 * mounting 1,454 of them is the `renderedRange` leak again in miniature —
 * smaller canvases, four times as many of them.
 */
const OVERSCAN = 6;

/**
 * A page-thumbnail strip for PDF navigation (§2.1).
 *
 * Virtualised on scroll position rather than with an IntersectionObserver per
 * slot: every row is exactly the same height here, so the visible range is
 * arithmetic, and 1,454 observers to compute a number that `scrollTop / rowHeight`
 * already gives is a lot of machinery for nothing.
 */
export function PdfThumbnails({ doc, numPages, currentPage, onNavigate }: PdfThumbnailsProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [range, setRange] = useState<[number, number]>([1, 20]);
  const [rowHeight, setRowHeight] = useState(160);

  /**
   * Measure a real row as it attaches. Page aspect ratios differ between
   * documents, and a hard-coded row height makes the scrollbar lie by a factor
   * that grows with the page count.
   *
   * A callback ref rather than an effect: measuring belongs to the moment the
   * node exists, and setting state from an effect body to describe the DOM you
   * just rendered is the cascading-render pattern. The 4px guard terminates it
   * — a measurement within a few pixels of what is stored is not worth a
   * re-render.
   */
  const measureRow = useCallback(
    (node: HTMLDivElement | null) => {
      if (!node) return;
      const measured = node.getBoundingClientRect().height;
      if (measured && Math.abs(measured - rowHeight) > 4) setRowHeight(measured);
    },
    [rowHeight],
  );

  const recompute = useCallback(
    () => {
      const el = scrollRef.current;
      if (!el) return;
      const first = Math.floor(el.scrollTop / rowHeight) + 1;
      const visible = Math.ceil(el.clientHeight / rowHeight);
      setRange([
        Math.max(1, first - OVERSCAN),
        Math.min(numPages, first + visible + OVERSCAN),
      ]);
    },
    [numPages, rowHeight],
  );

  useEffect(() => {
    recompute();
  }, [recompute, numPages]);

  // Follow the reader. Scrolling the strip to the current page is the whole
  // point of having one — otherwise it is a second thing to keep in sync by
  // hand.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const target = (currentPage - 1) * rowHeight;
    if (target < el.scrollTop || target > el.scrollTop + el.clientHeight - rowHeight) {
      el.scrollTo({ top: Math.max(0, target - el.clientHeight / 3), behavior: 'smooth' });
    }
  }, [currentPage, rowHeight]);

  if (!doc || !numPages) return null;

  const [from, to] = range;
  const pages: number[] = [];
  for (let p = from; p <= to; p += 1) pages.push(p);

  return (
    <div className="flex w-32 shrink-0 flex-col border-r border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/50">
      <div className="border-b border-slate-200 px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-400 dark:border-slate-700">
        Pages
      </div>
      <div ref={scrollRef} onScroll={recompute} className="flex-1 overflow-y-auto">
        {/* One spacer of the full height, so the scrollbar reflects the whole
            document rather than only the pages currently mounted. */}
        <div style={{ height: numPages * rowHeight, position: 'relative' }}>
          {pages.map((page) => (
            <div
              key={page}
              ref={page === from ? measureRow : undefined}
              style={{
                position: 'absolute',
                top: (page - 1) * rowHeight,
                height: rowHeight,
                width: '100%',
              }}
              className="flex flex-col items-center justify-start px-2 py-1"
            >
              <button
                type="button"
                onClick={() => onNavigate(page)}
                aria-label={`Go to page ${page}`}
                aria-current={page === currentPage ? 'page' : undefined}
                className={`overflow-hidden rounded border-2 bg-white transition-colors ${
                  page === currentPage
                    ? 'border-primary-500 shadow'
                    : 'border-transparent hover:border-slate-300 dark:hover:border-slate-500'
                }`}
              >
                <Page
                  // The strip lives outside the reader's `<Document>`, so the
                  // proxy is passed directly rather than taken from context.
                  pdf={doc}
                  pageNumber={page}
                  width={THUMB_WIDTH}
                  renderTextLayer={false}
                  renderAnnotationLayer={false}
                  loading={
                    <div
                      style={{ width: THUMB_WIDTH, height: THUMB_WIDTH * 1.41 }}
                      className="bg-slate-100 dark:bg-slate-700"
                    />
                  }
                />
              </button>
              <span
                className={`mt-0.5 text-[10px] tabular-nums ${
                  page === currentPage
                    ? 'font-bold text-primary-600 dark:text-primary-400'
                    : 'text-slate-400'
                }`}
              >
                {page}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
