import { useEffect, useRef, useState } from 'react';
import { Check, Palette } from 'lucide-react';
import clsx from 'clsx';
import { THEMES, THEME_META, useTheme } from '../../hooks/useTheme';

/**
 * Theme menu.
 *
 * Replaces the sun/moon button, which could only express two of the four
 * themes. `d` still cycles them without opening this.
 */
export function ThemePicker() {
  const [theme, applyTheme] = useTheme();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: PointerEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      // Stop the global handler seeing this Escape and navigating back.
      e.stopPropagation();
      setOpen(false);
      buttonRef.current?.focus();
    };
    document.addEventListener('pointerdown', onPointerDown);
    // Capture phase: `useKeyboardShortcuts` listens on `window`, which would
    // otherwise fire first and take us to the previous route.
    document.addEventListener('keydown', onKeyDown, true);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown, true);
    };
  }, [open]);

  const meta = THEME_META[theme];

  return (
    <div className="relative" ref={containerRef}>
      <button
        ref={buttonRef}
        onClick={() => setOpen((o) => !o)}
        aria-label={`Theme: ${meta.label}`}
        aria-haspopup="menu"
        aria-expanded={open}
        title="Change theme (d cycles)"
        className="flex items-center gap-1.5 rounded-lg p-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700"
      >
        <Palette size={18} />
        <span
          aria-hidden="true"
          className="h-3.5 w-3.5 rounded-full ring-1 ring-slate-300 dark:ring-slate-600"
          style={{ background: meta.swatch[0] }}
        />
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Theme"
          className="absolute right-0 top-11 z-50 w-56 overflow-hidden rounded-xl bg-white p-1 shadow-lg ring-1 ring-slate-200 dark:bg-slate-800 dark:ring-slate-700"
        >
          {THEMES.map((name) => {
            const t = THEME_META[name];
            const selected = name === theme;
            return (
              <button
                key={name}
                role="menuitemradio"
                aria-checked={selected}
                onClick={() => {
                  applyTheme(name);
                  setOpen(false);
                }}
                className={clsx(
                  'flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors',
                  selected
                    ? 'bg-primary-50 dark:bg-primary-900/30'
                    : 'hover:bg-slate-50 dark:hover:bg-slate-700',
                )}
              >
                <span
                  aria-hidden="true"
                  className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ring-1 ring-slate-300 dark:ring-slate-600"
                  style={{ background: t.swatch[0], color: t.swatch[1] }}
                >
                  Aa
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium text-slate-800 dark:text-slate-200">
                    {t.label}
                  </span>
                  <span className="block truncate text-[11px] text-slate-500">{t.hint}</span>
                </span>
                {selected && <Check size={14} className="shrink-0 text-primary-600 dark:text-primary-300" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
