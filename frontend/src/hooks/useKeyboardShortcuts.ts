import { useEffect, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';

export interface ShortcutDef {
  key: string;
  label: string;
  category: string;
}

export const SHORTCUTS: ShortcutDef[] = [
  { key: '/', label: 'Focus search', category: 'Navigation' },
  { key: 'g h', label: 'Go to Home', category: 'Navigation' },
  { key: 'g s', label: 'Go to Stats', category: 'Navigation' },
  { key: 'g p', label: 'Go to Settings', category: 'Navigation' },
  { key: 'Escape', label: 'Go back / close', category: 'Navigation' },
  { key: '1', label: 'Grid view', category: 'View' },
  { key: '2', label: 'List view', category: 'View' },
  { key: 't', label: 'Toggle sidebar', category: 'View' },
  { key: 'd', label: 'Toggle dark/light mode', category: 'View' },
  { key: 'j', label: 'Next page', category: 'Pagination' },
  { key: 'k', label: 'Previous page', category: 'Pagination' },
  { key: '?', label: 'Show keyboard shortcuts', category: 'Help' },
];

interface ShortcutHandlers {
  onToggleView?: (v: 'grid' | 'list') => void;
  onToggleSidebar?: () => void;
  onToggleDark?: () => void;
  onShowHelp?: () => void;
  onNextPage?: () => void;
  onPrevPage?: () => void;
  currentView?: 'grid' | 'list';
}

export function useKeyboardShortcuts(handlers: ShortcutHandlers) {
  const navigate = useNavigate();
  const location = useLocation();

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    const target = e.target as HTMLElement;
    const isInput = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable;
    
    // Always allow Escape
    if (e.key === 'Escape') {
      if (isInput) {
        (target as HTMLInputElement).blur();
        return;
      }
      // Go back
      if (location.pathname !== '/') {
        e.preventDefault();
        navigate(-1);
      }
      return;
    }

    // Skip if user is typing in an input
    if (isInput) return;

    // ? — show shortcuts help
    if (e.key === '?' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      handlers.onShowHelp?.();
      return;
    }

    // d — toggle dark mode
    if (e.key === 'd' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      handlers.onToggleDark?.();
      return;
    }

    // t — toggle sidebar
    if (e.key === 't' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      handlers.onToggleSidebar?.();
      return;
    }

    // 1 — grid view, 2 — list view
    if (e.key === '1' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      handlers.onToggleView?.('grid');
      return;
    }
    if (e.key === '2' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      handlers.onToggleView?.('list');
      return;
    }

    // j/k — page navigation
    if (e.key === 'j' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      handlers.onNextPage?.();
      return;
    }
    if (e.key === 'k' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      handlers.onPrevPage?.();
      return;
    }
  }, [handlers, navigate, location.pathname]);

  // Handle "g" prefix shortcuts (g+h, g+s, g+p)
  useEffect(() => {
    let gPressed = false;
    let gTimer: ReturnType<typeof setTimeout>;

    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const isInput = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable;
      if (isInput) return;

      if (e.key === 'g' && !e.ctrlKey && !e.metaKey && !gPressed) {
        gPressed = true;
        gTimer = setTimeout(() => { gPressed = false; }, 500);
        return;
      }

      if (gPressed) {
        gPressed = false;
        clearTimeout(gTimer);
        if (e.key === 'h') { e.preventDefault(); navigate('/'); }
        if (e.key === 's') { e.preventDefault(); navigate('/stats'); }
        if (e.key === 'p') { e.preventDefault(); navigate('/settings'); }
      }
    };

    window.addEventListener('keydown', handler);
    return () => {
      window.removeEventListener('keydown', handler);
      clearTimeout(gTimer);
    };
  }, [navigate]);

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);
}
