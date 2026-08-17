import { useSyncExternalStore } from 'react';

/**
 * One source of truth for the theme.
 *
 * There used to be two, and only two *themes*: `App.toggleDark` read the DOM
 * class, flipped it and wrote localStorage directly (bound to the `d`
 * shortcut), while `Header` kept its own `useLocalStorage('darkMode')` state
 * seeded once from the DOM. Pressing `d` flipped the theme without telling the
 * Header, so its sun/moon icon went stale and the next click toggled from the
 * stale value.
 *
 * The store lives outside React so every subscriber sees the same value, and
 * the DOM is written in exactly one place.
 *
 * ## How a theme is applied
 *
 * Two attributes, because the two do different jobs:
 *
 * - `data-theme` selects a palette. `index.css` redefines Tailwind's colour
 *   variables under `[data-theme="paper"]` / `[data-theme="dim"]`, so every
 *   existing `bg-slate-800` / `text-slate-500` utility retints without a
 *   single component changing.
 * - `.dark` drives the `dark:` variant. It is present for the *dark-family*
 *   themes (`dark`, `dim`) and absent for the light-family ones (`light`,
 *   `paper`), so a component's existing light/dark pairing keeps working and
 *   only the hues move.
 */
export const THEMES = ['light', 'dark', 'paper', 'dim'] as const;

export type Theme = (typeof THEMES)[number];

export interface ThemeMeta {
  label: string;
  /** Shown under the label in the picker. */
  hint: string;
  /** Whether the `dark:` variant applies. */
  dark: boolean;
  /** Two swatches for the picker: background, then foreground. */
  swatch: [string, string];
}

export const THEME_META: Record<Theme, ThemeMeta> = {
  light: { label: 'Light', hint: 'Cool grey, default', dark: false, swatch: ['#f8fafc', '#0f172a'] },
  paper: { label: 'Paper', hint: 'Warm, easy on the eyes', dark: false, swatch: ['#f5eddc', '#43392d'] },
  dark: { label: 'Dark', hint: 'High contrast slate', dark: true, swatch: ['#0f172a', '#f1f5f9'] },
  dim: { label: 'Dim', hint: 'Softer dark, less glare', dark: true, swatch: ['#1a1f26', '#adbac7'] },
};

const STORAGE_KEY = 'theme';
/** Pre-multi-theme key, still on disk for anyone who used the old toggle. */
const LEGACY_KEY = 'darkMode';

const listeners = new Set<() => void>();

function isTheme(value: unknown): value is Theme {
  return typeof value === 'string' && (THEMES as readonly string[]).includes(value);
}

/**
 * The theme `index.html` already committed to before first paint.
 *
 * Reading the DOM rather than storage keeps this hook and the inline script
 * from ever disagreeing — the script is the one that ran first.
 */
function readInitial(): Theme {
  if (typeof document === 'undefined') return 'light';
  const attr = document.documentElement.dataset.theme;
  if (isTheme(attr)) return attr;
  return document.documentElement.classList.contains('dark') ? 'dark' : 'light';
}

let current: Theme = readInitial();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setTheme(next: Theme): void {
  if (!isTheme(next) || next === current) return;
  current = next;
  const root = document.documentElement;
  root.dataset.theme = next;
  root.classList.toggle('dark', THEME_META[next].dark);
  // Native controls — scrollbars, date pickers, form widgets — take their
  // own light/dark cue from this, not from the class.
  root.style.colorScheme = THEME_META[next].dark ? 'dark' : 'light';
  try {
    localStorage.setItem(STORAGE_KEY, next);
    localStorage.removeItem(LEGACY_KEY);
  } catch {
    /* private mode — the attribute still applies for this session */
  }
  listeners.forEach((l) => l());
}

/** Advance to the next theme. Bound to `d`, which used to be a binary toggle. */
export function cycleTheme(): void {
  setTheme(THEMES[(THEMES.indexOf(current) + 1) % THEMES.length]);
}

export function useTheme(): [Theme, (next: Theme) => void, () => void] {
  const theme = useSyncExternalStore(subscribe, () => current, () => 'light' as Theme);
  return [theme, setTheme, cycleTheme];
}
