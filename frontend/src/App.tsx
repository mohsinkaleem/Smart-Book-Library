import { useState, useEffect, useCallback, lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Header } from './components/layout/Header';
import { Sidebar } from './components/layout/Sidebar';
import { SearchBar } from './components/search/SearchBar';
import { HomePage } from './pages/HomePage';
import { KeyboardShortcutsDialog } from './components/common/KeyboardShortcutsDialog';
import { ErrorBoundary } from './components/common/ErrorBoundary';
import { Spinner } from './components/common/Spinner';

/* Split per route, because the library page was paying for the readers.
 *
 * Everything lived in one 1.2 MB entry chunk: react-pdf and pdf.js, Recharts
 * for a dashboard most visits never open, the duplicate and review screens.
 * The grid needs none of it, and it is the page every visit starts on.
 * `react-reader` was already pulled out — EpubReader imports it dynamically —
 * which is why the EPUB half of the reader is not in that figure either. */
const BookPage = lazy(() => import('./pages/BookPage').then((m) => ({ default: m.BookPage })));
const SettingsPage = lazy(() => import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })));
const ReviewPage = lazy(() => import('./pages/ReviewPage').then((m) => ({ default: m.ReviewPage })));
const Dashboard = lazy(() => import('./components/stats/Dashboard').then((m) => ({ default: m.Dashboard })));
const ReadingView = lazy(() => import('./components/reading/ReadingView').then((m) => ({ default: m.ReadingView })));
const EpubReader = lazy(() => import('./components/reading/EpubReader').then((m) => ({ default: m.EpubReader })));
const PdfReader = lazy(() => import('./components/reading/PdfReader').then((m) => ({ default: m.PdfReader })));
const ReaderRoute = lazy(() => import('./components/reading/ReaderRoute').then((m) => ({ default: m.ReaderRoute })));
const DuplicatesPage = lazy(() => import('./pages/DuplicatesPage').then((m) => ({ default: m.DuplicatesPage })));
const PassageSearchPage = lazy(() => import('./pages/PassageSearchPage').then((m) => ({ default: m.PassageSearchPage })));
import { useLocalStorage } from './hooks/useLocalStorage';
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts';
import { useScrollToTop } from './hooks/useScrollToTop';
import { cycleTheme } from './hooks/useTheme';
import { useLibraryParams } from './hooks/useLibraryParams';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppShell />
      </BrowserRouter>
    </QueryClientProvider>
  );
}

/**
 * Each route body gets its own boundary, so one bad page is not a blank app,
 * and its own Suspense, so a lazily loaded route shows a spinner in the
 * content area rather than blanking the shell around it.
 */
function Page({ className, children }: { className: string; children: React.ReactNode }) {
  return (
    <main className={className}>
      <ErrorBoundary>
        <Suspense
          fallback={
            <div className="flex h-full items-center justify-center p-12">
              <Spinner />
            </div>
          }
        >
          {children}
        </Suspense>
      </ErrorBoundary>
    </main>
  );
}

function AppShell() {
  // Open by default on a desktop-width viewport, closed on a phone, where it
  // is a drawer over the grid rather than a column beside it. Lazy, so the
  // width is only read when nothing is stored yet.
  const [sidebarOpen, setSidebarOpen] = useLocalStorage(
    'sidebarOpen',
    () => typeof window === 'undefined' || window.innerWidth >= 768,
  );
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [pageCount, setPageCount] = useState(1);
  const location = useLocation();

  const {
    searchQuery, searchMode, page, sort, order, filters, view,
    setSearchQuery, setSearchMode, setFilter, clearFilters, setPage, setSort, setView,
  } = useLibraryParams();

  // The reader routes run `useReaderKeyboard` on the same window; leaving the
  // global handler live meant Escape fired twice (history went somewhere
  // unpredictable), `t` toggled both the library sidebar and the EPUB TOC,
  // and `d`/`1`/`2` fired inside a reader where they mean nothing.
  const inReader =
    location.pathname.startsWith('/reader/') || location.pathname.startsWith('/read/');

  useKeyboardShortcuts({
    onToggleView: setView,
    onToggleSidebar: () => setSidebarOpen(!sidebarOpen),
    // `d` used to flip a boolean; it steps through the four themes now.
    onCycleTheme: cycleTheme,
    onShowHelp: () => setShortcutsOpen(true),
    // j/k were documented and rendered in the shortcuts dialog while calling
    // `undefined?.()`.
    onNextPage: () => setPage(Math.min(page + 1, pageCount)),
    onPrevPage: () => setPage(Math.max(1, page - 1)),
    currentView: view,
    enabled: !inReader,
  });

  useScrollToTop();

  // Applying a filter from the drawer should reveal the result it produced.
  // At `md` and up the sidebar is a permanent column and must stay put.
  const dismissSidebarOnMobile = useCallback(() => {
    if (typeof window !== 'undefined' && window.innerWidth < 768) {
      setSidebarOpen(false);
    }
  }, [setSidebarOpen]);

  // Listen for keyboard shortcut dialog event from Header button
  useEffect(() => {
    const handler = () => setShortcutsOpen(true);
    window.addEventListener('show-shortcuts', handler);
    return () => window.removeEventListener('show-shortcuts', handler);
  }, []);

  return (
    <div className="flex h-screen flex-col">
      {/* No library chrome over a book. The readers have their own toolbar and
          their own back button, and the global header put a search box above
          the page you were reading: typing in it navigated out of the book,
          mid-page, with no way back to where you were. It also spent 56px of
          height on controls — grid/list, theme, filters — that mean nothing
          while reading. */}
      {!inReader && (
        <Header
          view={view}
          onViewChange={setView}
          sidebarOpen={sidebarOpen}
          onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
        >
          <SearchBar
            value={searchQuery}
            onChange={setSearchQuery}
            mode={searchMode}
            onModeChange={setSearchMode}
          />
        </Header>
      )}

      <div className="flex flex-1 overflow-hidden">
        <Routes>
          <Route
            path="/"
            element={
              <>
                <Sidebar
                  filters={filters}
                  onFilterChange={setFilter}
                  onClearFilters={clearFilters}
                  collapsed={!sidebarOpen}
                  searchQuery={searchQuery}
                  onDismiss={dismissSidebarOnMobile}
                />
                <Page className="flex-1 overflow-y-auto">
                  <HomePage
                    view={view}
                    searchQuery={searchQuery}
                    searchMode={searchMode}
                    filters={filters}
                    page={page}
                    sort={sort}
                    order={order}
                    onFilterChange={setFilter}
                    onPageChange={setPage}
                    onSortChange={setSort}
                    onPageCountChange={setPageCount}
                  />
                </Page>
              </>
            }
          />
          <Route path="/books/:id" element={<Page className="flex-1 overflow-y-auto"><BookPage /></Page>} />
          <Route path="/reading/:id" element={<Page className="flex-1 overflow-hidden"><ReadingView /></Page>} />
          <Route path="/reader/epub/:id" element={<Page className="flex-1 overflow-hidden"><EpubReader /></Page>} />
          <Route path="/reader/pdf/:id" element={<Page className="flex-1 overflow-hidden"><PdfReader /></Page>} />
          {/* Deep links from passage cards. The server emits `/read/{id}?page=…`
              because the reader route is not something the API should know. */}
          <Route path="/read/:id" element={<Page className="flex-1 overflow-hidden"><ReaderRoute /></Page>} />
          <Route path="/passages" element={<Page className="flex-1 overflow-y-auto"><PassageSearchPage /></Page>} />
          <Route path="/duplicates" element={<Page className="flex-1 overflow-y-auto"><DuplicatesPage /></Page>} />
          <Route path="/stats" element={<Page className="flex-1 overflow-y-auto"><Dashboard /></Page>} />
          <Route path="/review" element={<Page className="flex-1 overflow-y-auto"><ReviewPage /></Page>} />
          <Route path="/settings" element={<Page className="flex-1 overflow-y-auto"><SettingsPage /></Page>} />
        </Routes>
      </div>

      <KeyboardShortcutsDialog open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
    </div>
  );
}
