import { useState, useCallback } from 'react';
import { FileText, BookOpen } from 'lucide-react';
import clsx from 'clsx';

interface BookCoverProps {
  coverUrl: string | null;
  title: string;
  fileType: string;
  className?: string;
}

function hashColor(str: string): string {
  let hash = 0;
  for (let i = 0; i < str.length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash);
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue}, 35%, 25%)`;
}

function hashAccentColor(str: string): string {
  let hash = 0;
  for (let i = 0; i < str.length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash);
  const hue = (Math.abs(hash) + 40) % 360;
  return `hsl(${hue}, 30%, 35%)`;
}

/**
 * Detect if an image is unusable as a cover:
 * - Extreme aspect ratio (spine scans, thin strips like 39x1200)
 * - Nothing on the page at all (a corrupt or empty image)
 * - Too small to be a real cover
 *
 * The content test measures *ink* — how much of the image differs from its own
 * background — and not uniformity. This used to reject anything more than 90%
 * one colour, which is right for a downloaded jacket and wrong for the page-1
 * renders the pipeline now produces as a last-resort cover: a title page is
 * mostly margin by design. Measured over this catalog, the old rule threw away
 * the title pages of The Kite Runner, Mein Kampf and The Holy Bible.
 *
 * The thresholds mirror `catalog/covers.py`, which applies the same test
 * server-side at extraction time. This one is the backstop for covers that
 * predate it or came from elsewhere, so it is deliberately the more forgiving
 * of the two: a blank page scores 0.0000 here and the sparsest real title page
 * in the library 0.0039.
 */
const MIN_COVER_PX = 50;
const COVER_ASPECT_MIN = 0.25;
const COVER_ASPECT_MAX = 4;
const INK_SAMPLE_W = 160;
const INK_SAMPLE_H = 220;
const INK_GREY_DELTA = 16;
const MIN_INK_FRACTION = 0.001;

function isUnusableCover(img: HTMLImageElement): boolean {
  const w = img.naturalWidth;
  const h = img.naturalHeight;

  if (w < MIN_COVER_PX || h < MIN_COVER_PX) return true;

  const ratio = w / h;
  if (ratio < COVER_ASPECT_MIN || ratio > COVER_ASPECT_MAX) return true;

  try {
    const canvas = document.createElement('canvas');
    canvas.width = INK_SAMPLE_W;
    canvas.height = INK_SAMPLE_H;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) return false;
    ctx.drawImage(img, 0, 0, INK_SAMPLE_W, INK_SAMPLE_H);
    const { data } = ctx.getImageData(0, 0, INK_SAMPLE_W, INK_SAMPLE_H);

    // Modal grey level, not a corner pixel: a page scanned at an angle, or a
    // jacket with a border, has a corner that is not the background.
    const histogram = new Uint32Array(256);
    for (let i = 0; i < data.length; i += 4) {
      const grey = (data[i] * 299 + data[i + 1] * 587 + data[i + 2] * 114) / 1000;
      histogram[grey | 0]++;
    }
    let background = 0;
    for (let v = 1; v < 256; v++) if (histogram[v] > histogram[background]) background = v;

    const total = INK_SAMPLE_W * INK_SAMPLE_H;
    let within = 0;
    const lo = Math.max(0, background - INK_GREY_DELTA);
    const hi = Math.min(255, background + INK_GREY_DELTA);
    for (let v = lo; v <= hi; v++) within += histogram[v];
    if (1 - within / total < MIN_INK_FRACTION) return true;
  } catch {
    // canvas tainted by CORS — can't sample, fall through
  }

  return false;
}

export function BookCover({ coverUrl, title, fileType, className }: BookCoverProps) {
  const [showFallback, setShowFallback] = useState(false);

  const handleImageLoad = useCallback((e: React.SyntheticEvent<HTMLImageElement>) => {
    const img = e.target as HTMLImageElement;
    if (isUnusableCover(img)) {
      setShowFallback(true);
    }
  }, []);

  const handleImageError = useCallback(() => {
    setShowFallback(true);
  }, []);

  // The inset ring matters more than it looks: a rendered page-1 cover is a
  // white page on a white card, and without an edge it reads as a hole in the
  // grid rather than as a book.
  if (coverUrl && !showFallback) {
    return (
      <div className={clsx('relative overflow-hidden rounded-lg bg-slate-200 ring-1 ring-inset ring-slate-900/10 dark:bg-slate-700 dark:ring-white/10', className)}>
        <img
          src={coverUrl}
          alt={title}
          loading="lazy"
          className="h-full w-full object-cover"
          onLoad={handleImageLoad}
          onError={handleImageError}
        />
      </div>
    );
  }

  const bg = hashColor(title);
  const accent = hashAccentColor(title);
  const Icon = fileType === 'epub' ? BookOpen : FileText;
  return (
    <div
      className={clsx('flex items-center justify-center overflow-hidden rounded-lg', className)}
      style={{ background: `linear-gradient(135deg, ${bg} 0%, ${accent} 100%)` }}
      // The gradient is keyed to the title, so it is stable per book and the
      // placeholder is still a recognisable shape in a grid.
      role="img"
      aria-label={title ? `${title} (no cover)` : 'No cover'}
    >
      {/* Icon only. This used to print the title and the file type inside the
          placeholder, and every caller already renders both right beside it —
          so a cover-less card said its title twice and its type twice, and at
          thumbnail sizes the inner copy was unreadable anyway. */}
      {/* Sized from the container's width only — the placeholder is used at
          everything from a 32px row thumbnail to a full detail-page cover,
          and width is the one dimension every caller states. */}
      <div className="flex aspect-square w-[34%] max-w-16 items-center justify-center rounded-full bg-white/10 text-white/90">
        <Icon className="h-1/2 w-1/2" />
      </div>
    </div>
  );
}
