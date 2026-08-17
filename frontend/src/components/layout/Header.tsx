import { Link, useLocation } from 'react-router-dom';
import { BookOpen, BarChart3, Settings, LayoutGrid, List, PanelLeftClose, PanelLeft, Keyboard, ClipboardCheck } from 'lucide-react';
import clsx from 'clsx';
import { ThemePicker } from './ThemePicker';

interface HeaderProps {
  view: 'grid' | 'list';
  onViewChange: (v: 'grid' | 'list') => void;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  children?: React.ReactNode; // search bar
}

export function Header({ view, onViewChange, sidebarOpen, onToggleSidebar, children }: HeaderProps) {
  const location = useLocation();

  return (
    <header className="sticky top-0 z-40 flex h-14 items-center gap-4 border-b border-slate-200 bg-white/95 px-4 backdrop-blur dark:border-slate-700 dark:bg-slate-900/95">
      <button
        onClick={onToggleSidebar}
        aria-label={sidebarOpen ? 'Hide filters sidebar' : 'Show filters sidebar'}
        aria-pressed={sidebarOpen}
        title="Toggle sidebar (t)"
        className="text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
      >
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
              aria-label="Grid view"
              aria-pressed={view === 'grid'}
              title="Grid view (1)"
              className={clsx('rounded-md p-1.5 transition-colors', view === 'grid' ? 'bg-white shadow-sm dark:bg-slate-600' : 'text-slate-500 hover:text-slate-700')}
            >
              <LayoutGrid size={16} />
            </button>
            <button
              onClick={() => onViewChange('list')}
              aria-label="List view"
              aria-pressed={view === 'list'}
              title="List view (2)"
              className={clsx('rounded-md p-1.5 transition-colors', view === 'list' ? 'bg-white shadow-sm dark:bg-slate-600' : 'text-slate-500 hover:text-slate-700')}
            >
              <List size={16} />
            </button>
          </div>
        )}
        <Link to="/review" title="Review queue (g r)" aria-label="Review queue" className={clsx(
          'rounded-lg p-2 transition-colors',
          location.pathname === '/review' ? 'bg-primary-50 text-primary-600 dark:bg-primary-900/30' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700',
        )}>
          <ClipboardCheck size={18} />
        </Link>
        <Link to="/stats" title="Statistics (g s)" aria-label="Statistics" className={clsx(
          'rounded-lg p-2 transition-colors',
          location.pathname === '/stats' ? 'bg-primary-50 text-primary-600 dark:bg-primary-900/30' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700',
        )}>
          <BarChart3 size={18} />
        </Link>
        <Link to="/settings" title="Settings (g p)" aria-label="Settings" className={clsx(
          'rounded-lg p-2 transition-colors',
          location.pathname === '/settings' ? 'bg-primary-50 text-primary-600 dark:bg-primary-900/30' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700',
        )}>
          <Settings size={18} />
        </Link>
        {/* Shared with the `d` shortcut — this used to be a local
            `useLocalStorage('darkMode')` copy that went stale the moment the
            shortcut fired. */}
        <ThemePicker />
        <button
          onClick={() => { window.dispatchEvent(new CustomEvent('show-shortcuts')); }}
          aria-label="Keyboard shortcuts"
          className="hidden rounded-lg p-2 text-slate-500 hover:bg-slate-100 sm:inline-flex dark:hover:bg-slate-700"
          title="Keyboard shortcuts (?)"
        >
          <Keyboard size={18} />
        </button>
      </div>
    </header>
  );
}
