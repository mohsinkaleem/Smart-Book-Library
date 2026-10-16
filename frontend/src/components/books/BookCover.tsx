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
 * - Extreme aspect ratio (spine scans, thin strips like 39×1200)
 * - Mostly a solid color (corrupted/blank cover)
 * - Too small to be a real cover
 */
function isUnusableCover(img: HTMLImageElement): boolean {
  const w = img.naturalWidth;
  const h = img.naturalHeight;

  // Too small to be a real cover (< 50px in either dimension)
  if (w < 50 || h < 50) return true;

  // Extreme aspect ratio: real covers are roughly 1:1.2 to 1:1.8
  // Reject if width/height ratio is outside ~1:4 to 4:1
  const ratio = w / h;
  if (ratio < 0.25 || ratio > 4) return true;

  // Check if it's mostly a solid color via canvas sampling
  try {
    const canvas = document.createElement('canvas');
    const size = 20;
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');
    if (!ctx) return false;
    ctx.drawImage(img, 0, 0, size, size);
    const data = ctx.getImageData(0, 0, size, size).data;
    const r0 = data[0], g0 = data[1], b0 = data[2];
    let uniformCount = 0;
    const total = size * size;
    for (let i = 0; i < data.length; i += 4) {
      const dr = Math.abs(data[i] - r0);
      const dg = Math.abs(data[i + 1] - g0);
      const db = Math.abs(data[i + 2] - b0);
      if (dr < 25 && dg < 25 && db < 25) uniformCount++;
    }
    if (uniformCount / total > 0.9) return true;
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

  if (coverUrl && !showFallback) {
    return (
      <div className={clsx('relative overflow-hidden rounded-lg bg-slate-200 dark:bg-slate-700', className)}>
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
