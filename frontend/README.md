# Frontend — BookShelf

React + TypeScript SPA for the Smart Book Library. Built with Vite and
Tailwind, served in production by the FastAPI app from `dist/`.

## Commands

```bash
npm install
npm run dev      # Vite dev server on :5173, proxying /api to :8000
npm run build    # tsc -b && vite build → dist/
npm run lint     # eslint (must pass — it is the only automated check here)
npm run preview  # serve the production build locally
```

The dev server expects the API on `http://127.0.0.1:8000` — start it with
`python main.py` from the repository root. `npm run build` output is what
`python main.py` serves, so rebuild after changing anything under `src/`.

## Layout

| Path              | What lives there                                                     |
| ----------------- | -------------------------------------------------------------------- |
| `src/api/`        | Typed fetch client and TanStack Query hooks                          |
| `src/components/` | `books/`, `common/`, `detail/`, `layout/`, `reading/`, `search/`, `stats/` |
| `src/hooks/`      | `useLibraryParams` (URL state), `useTheme`, `useReadingProgress`, keyboard shortcuts |
| `src/pages/`      | Route-level components                                                |
| `src/utils/`      | Formatting helpers                                                    |

## Conventions worth knowing

- **Browsing state lives in the URL.** The search query, search mode, filters,
  page, sort and order are all query parameters, managed by
  `useLibraryParams`. Anything that changes the result set resets `page`. Do
  not add a second copy of this state in React.
- **Theme has one owner.** `useTheme` is an external store shared by
  `ThemePicker` and the `d` shortcut. Never write `document.documentElement`'s
  `data-theme` attribute, its `dark` class, or the `theme` localStorage key
  directly. The inline script in `index.html` applies the theme before first
  paint and must stay in sync with the hook — the hook reads its result back
  off the DOM rather than re-deriving it.
- **Themes are palettes, not components.** A theme redefines Tailwind's colour
  variables under `[data-theme="…"]` in `index.css`; components keep using
  `bg-white` / `bg-slate-800` / `text-slate-500` and retint for free. Add a
  theme by adding a block there and an entry to `THEME_META` — never by adding
  a `data-theme` branch inside a component. Light-family themes leave `.dark`
  off, dark-family themes turn it on, so existing `dark:` pairings keep
  working.
- **The PDF worker is bundled**, not fetched from a CDN — the app must work
  offline.
- **Reader routes disable the global shortcuts** (`useKeyboardShortcuts`
  takes `enabled`), because `useReaderKeyboard` binds several of the same keys.
- **The readers own reading progress.** `useReadingProgress` stamps
  `last_opened` on open and debounces `progress_percent` / `reader_position`
  on every page turn, flushing on unmount and `pagehide`. Nothing else should
  write those three fields.
