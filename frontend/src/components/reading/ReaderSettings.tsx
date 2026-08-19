import { useEffect, useRef } from 'react';
import { Settings2 } from 'lucide-react';
import {
  EPUB_FONTS,
  READING_THEMES,
  READING_THEME_META,
  type EpubFontId,
  type EpubTypography,
  type ReadingTheme,
} from './readingTheme';

interface ReaderSettingsProps {
  open: boolean;
  onToggle: () => void;
  onClose: () => void;
  theme: ReadingTheme;
  onThemeChange: (theme: ReadingTheme) => void;
  /** Omitted for the PDF reader, which has no text to typeset. */
  typography?: EpubTypography;
  onTypographyChange?: (typography: EpubTypography) => void;
}

/**
 * Page appearance: reading theme, and for EPUB the typography that
 * `handleRendition` used to hardcode to `Georgia, serif` / `line-height: 1.8`.
 */
export function ReaderSettings({
  open, onToggle, onClose, theme, onThemeChange, typography, onTypographyChange,
}: ReaderSettingsProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, onClose]);

  const setTypography = (patch: Partial<EpubTypography>) => {
    if (typography && onTypographyChange) onTypographyChange({ ...typography, ...patch });
  };

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={onToggle}
        aria-expanded={open}
        aria-label="Page appearance"
        title="Page appearance"
        className={`rounded p-1.5 transition-colors ${
          open
            ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
            : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'
        }`}
      >
        <Settings2 size={16} />
      </button>

      {open && (
        <div className="absolute right-0 top-full z-40 mt-1 w-64 rounded-lg border border-slate-200 bg-white p-3 shadow-lg dark:border-slate-600 dark:bg-slate-800">
          <p className="mb-2 text-xs font-semibold text-slate-500">Page theme</p>
          <div className="grid grid-cols-5 gap-1">
            {READING_THEMES.map((id) => {
              const meta = id === 'auto' ? null : READING_THEME_META[id];
              return (
                <button
                  key={id}
                  onClick={() => onThemeChange(id)}
                  title={meta ? `${meta.label} — ${meta.hint}` : 'Follow the app theme'}
                  className={`flex flex-col items-center gap-1 rounded-md p-1.5 text-[10px] transition-colors ${
                    theme === id
                      ? 'bg-primary-100 font-medium text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
                      : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'
                  }`}
                >
                  <span
                    className="flex h-6 w-6 items-center justify-center rounded ring-1 ring-slate-300 dark:ring-slate-500"
                    style={{ background: meta ? meta.swatch[0] : 'linear-gradient(135deg,#fff 50%,#14181f 50%)' }}
                  >
                    <span className="text-[9px] font-bold" style={{ color: meta ? meta.swatch[1] : '#64748b' }}>
                      A
                    </span>
                  </span>
                  {meta ? meta.label : 'Auto'}
                </button>
              );
            })}
          </div>

          {typography && onTypographyChange && (
            <>
              <p className="mb-2 mt-4 text-xs font-semibold text-slate-500">Typeface</p>
              <div className="grid grid-cols-4 gap-1">
                {EPUB_FONTS.map((font) => (
                  <button
                    key={font.id}
                    onClick={() => setTypography({ font: font.id as EpubFontId })}
                    style={{ fontFamily: font.stack }}
                    className={`rounded-md px-1 py-1.5 text-[11px] transition-colors ${
                      typography.font === font.id
                        ? 'bg-primary-100 font-medium text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
                        : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'
                    }`}
                  >
                    {font.label}
                  </button>
                ))}
              </div>

              <label className="mt-4 block text-xs font-semibold text-slate-500">
                Line height
                <span className="ml-2 font-normal tabular-nums text-slate-400">
                  {typography.lineHeight.toFixed(1)}
                </span>
                <input
                  type="range"
                  min={1.2}
                  max={2.4}
                  step={0.1}
                  value={typography.lineHeight}
                  onChange={(e) => setTypography({ lineHeight: Number(e.target.value) })}
                  className="mt-1 w-full accent-primary-600"
                />
              </label>

              <label className="mt-3 block text-xs font-semibold text-slate-500">
                Margins
                <span className="ml-2 font-normal tabular-nums text-slate-400">
                  {typography.margin}%
                </span>
                <input
                  type="range"
                  min={0}
                  max={22}
                  step={1}
                  value={typography.margin}
                  onChange={(e) => setTypography({ margin: Number(e.target.value) })}
                  className="mt-1 w-full accent-primary-600"
                />
              </label>
            </>
          )}
        </div>
      )}
    </div>
  );
}
