import { useState, useCallback, useEffect } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Header } from './components/layout/Header';
import { Sidebar } from './components/layout/Sidebar';
import { SearchBar } from './components/search/SearchBar';
import { HomePage } from './pages/HomePage';
import { BookPage } from './pages/BookPage';
import { ReadingPage } from './pages/ReadingPage';
import { StatsPage } from './pages/StatsPage';
import { SettingsPage } from './pages/SettingsPage';
import { KeyboardShortcutsDialog } from './components/common/KeyboardShortcutsDialog';
import { EpubReader, PdfReader } from './components/reading/BookReader';
import { useLocalStorage } from './hooks/useLocalStorage';
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts';
import { useScrollToTop } from './hooks/useScrollToTop';

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

function AppShell() {
  const [view, setView] = useLocalStorage<'grid' | 'list'>('bookView', 'grid');
  const [sidebarOpen, setSidebarOpen] = useLocalStorage('sidebarOpen', true);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchMode, setSearchMode] = useState('text');
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [shortcutsOpen, setShortcutsOpen] = useState(false);

  const handleFilterChange = useCallback((key: string, value: string) => {
    setFilters((prev) => {
      const next = { ...prev };
      if (value) {
        next[key] = value;
      } else {
        delete next[key];
      }
      return next;
    });
  }, []);

  const handleClearFilters = useCallback(() => setFilters({}), []);

  const toggleDark = useCallback(() => {
    const isDark = document.documentElement.classList.contains('dark');
    document.documentElement.classList.toggle('dark', !isDark);
    localStorage.setItem('darkMode', JSON.stringify(!isDark));
  }, []);

  useKeyboardShortcuts({
    onToggleView: setView,
    onToggleSidebar: () => setSidebarOpen(!sidebarOpen),
    onToggleDark: toggleDark,
    onShowHelp: () => setShortcutsOpen(true),
    currentView: view,
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
                  onFilterChange={handleFilterChange}
                  onClearFilters={handleClearFilters}
                  collapsed={!sidebarOpen}
                  searchQuery={searchQuery}
                />
                <main className="flex-1 overflow-y-auto">
                  <HomePage
                    view={view}
                    searchQuery={searchQuery}
                    searchMode={searchMode}
                    filters={filters}
                    onFilterChange={handleFilterChange}
                  />
                </main>
              </>
            }
          />
          <Route path="/books/:id" element={<main className="flex-1 overflow-y-auto"><BookPage /></main>} />
          <Route path="/reading/:id" element={<main className="flex-1 overflow-hidden"><ReadingPage /></main>} />
          <Route path="/reader/epub/:id" element={<main className="flex-1 overflow-hidden"><EpubReader /></main>} />
          <Route path="/reader/pdf/:id" element={<main className="flex-1 overflow-hidden"><PdfReader /></main>} />
          <Route path="/stats" element={<main className="flex-1 overflow-y-auto"><StatsPage /></main>} />
          <Route path="/settings" element={<main className="flex-1 overflow-y-auto"><SettingsPage /></main>} />
        </Routes>
      </div>

      <KeyboardShortcutsDialog open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
    </div>
  );
}
