import { Link, useLocation } from 'react-router-dom';
import { BookOpen, BarChart3, Settings, LayoutGrid, List, PanelLeftClose, PanelLeft, Moon, Sun, Keyboard, ClipboardCheck } from 'lucide-react';
import clsx from 'clsx';
import { useLocalStorage } from '../../hooks/useLocalStorage';

interface HeaderProps {
  view: 'grid' | 'list';
  onViewChange: (v: 'grid' | 'list') => void;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  children?: React.ReactNode; // search bar
}

export function Header({ view, onViewChange, sidebarOpen, onToggleSidebar, children }: HeaderProps) {
  const location = useLocation();
  const [dark, setDark] = useLocalStorage('darkMode', () => {
    // Sync with the actual DOM state on first render
    return document.documentElement.classList.contains('dark');
  });

  const toggleDark = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle('dark', next);
  };

  return (
    <header className="sticky top-0 z-40 flex h-14 items-center gap-4 border-b border-slate-200 bg-white/95 px-4 backdrop-blur dark:border-slate-700 dark:bg-slate-900/95">
      <button onClick={onToggleSidebar} className="text-slate-500 hover:text-slate-700 dark:hover:text-slate-300">
        {sidebarOpen ? <PanelLeftClose size={20} /> : <PanelLeft size={20} />}
      </button>

      <Link to="/" className="flex items-center gap-2 text-lg font-bold text-slate-900 dark:text-white">
        <BookOpen size={22} className="text-primary-500" />
        <span className="hidden sm:inline">BookShelf</span>
      </Link>

      {/* Center: search bar slot */}
      <div className="flex flex-1 justify-center">{children}</div>

      {/* Right side */}
      <div className="flex items-center gap-2">
        {location.pathname === '/' && (
          <div className="flex rounded-lg bg-slate-100 p-0.5 dark:bg-slate-700">
            <button
              onClick={() => onViewChange('grid')}
              className={clsx('rounded-md p-1.5 transition-colors', view === 'grid' ? 'bg-white shadow-sm dark:bg-slate-600' : 'text-slate-500 hover:text-slate-700')}
            >
              <LayoutGrid size={16} />
            </button>
            <button
              onClick={() => onViewChange('list')}
              className={clsx('rounded-md p-1.5 transition-colors', view === 'list' ? 'bg-white shadow-sm dark:bg-slate-600' : 'text-slate-500 hover:text-slate-700')}
            >
              <List size={16} />
            </button>
          </div>
        )}
        <Link to="/review" title="Review queue" className={clsx(
          'rounded-lg p-2 transition-colors',
          location.pathname === '/review' ? 'bg-primary-50 text-primary-600 dark:bg-primary-900/30' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700',
        )}>
          <ClipboardCheck size={18} />
        </Link>
        <Link to="/stats" className={clsx(
          'rounded-lg p-2 transition-colors',
          location.pathname === '/stats' ? 'bg-primary-50 text-primary-600 dark:bg-primary-900/30' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700',
        )}>
          <BarChart3 size={18} />
        </Link>
        <Link to="/settings" className={clsx(
          'rounded-lg p-2 transition-colors',
          location.pathname === '/settings' ? 'bg-primary-50 text-primary-600 dark:bg-primary-900/30' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700',
        )}>
          <Settings size={18} />
        </Link>
        <button onClick={toggleDark} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700" title="Toggle dark mode (d)">
          {dark ? <Sun size={18} /> : <Moon size={18} />}
        </button>
        <button
          onClick={() => { window.dispatchEvent(new CustomEvent('show-shortcuts')); }}
          className="hidden rounded-lg p-2 text-slate-500 hover:bg-slate-100 sm:inline-flex dark:hover:bg-slate-700"
          title="Keyboard shortcuts (?)"
        >
          <Keyboard size={18} />
        </button>
      </div>
    </header>
  );
}
