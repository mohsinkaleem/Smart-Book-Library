import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Header } from './components/layout/Header';
import { Sidebar } from './components/layout/Sidebar';
import { SearchBar } from './components/search/SearchBar';
import { HomePage } from './pages/HomePage';
import { BookPage } from './pages/BookPage';
import { SettingsPage } from './pages/SettingsPage';
import { ReviewPage } from './pages/ReviewPage';
import { Dashboard } from './components/stats/Dashboard';
import { ReadingView } from './components/reading/ReadingView';
import { KeyboardShortcutsDialog } from './components/common/KeyboardShortcutsDialog';
import { ErrorBoundary } from './components/common/ErrorBoundary';
import { EpubReader } from './components/reading/EpubReader';
import { PdfReader } from './components/reading/PdfReader';
import { ReaderRoute } from './components/reading/ReaderRoute';
import { DuplicatesPage } from './pages/DuplicatesPage';
import { PassageSearchPage } from './pages/PassageSearchPage';
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

/** Each route body gets its own boundary, so one bad page is not a blank app. */
function Page({ className, children }: { className: string; children: React.ReactNode }) {
  return (
    <main className={className}>
      <ErrorBoundary>{children}</ErrorBoundary>
    </main>
  );
}

function AppShell() {
  const [view, setView] = useLocalStorage<'grid' | 'list'>('bookView', 'grid');
  const [sidebarOpen, setSidebarOpen] = useLocalStorage('sidebarOpen', true);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [pageCount, setPageCount] = useState(1);
  const location = useLocation();

  const {
    searchQuery, searchMode, page, sort, order, filters,
    setSearchQuery, setSearchMode, setFilter, clearFilters, setPage, setSort,
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

  // Listen for keyboard shortcut dialog event from Header button
  useEffect(() => {
    const handler = () => setShortcutsOpen(true);
    window.addEventListener('show-shortcuts', handler);
    return () => window.removeEventListener('show-shortcuts', handler);
  }, []);

  return (
    <div className="flex h-screen flex-col">
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
