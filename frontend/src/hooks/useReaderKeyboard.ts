import { useEffect, useCallback, useRef } from 'react';

export interface ReaderKeyboardActions {
  onNextPage?: () => void;
  onPrevPage?: () => void;
  onFirstPage?: () => void;
  onLastPage?: () => void;
  onZoomIn?: () => void;
  onZoomOut?: () => void;
  onZoomReset?: () => void;
  onToggleFullscreen?: () => void;
  onToggleSidebar?: () => void;
  onGoBack?: () => void;
  onToggleToc?: () => void;
  /**
   * Scroll the page by a line or a screen. When set, ↑/↓, Space and
   * PageUp/PageDown scroll through it and only ←/→ and j/k jump pages.
   *
   * Scroll mode used to bind ↓ and Space to "next page" like paginated mode
   * did, so the keys a reader scrolls with leapt a whole page instead — and
   * the EPUB reader, which has no page to jump to in scroll mode, swallowed
   * them outright.
   */
  onScrollBy?: (direction: 1 | -1, unit: 'line' | 'screen') => void;
  /** Disable arrow/page shortcuts (e.g. when user is typing in sidebar) */
  disabled?: boolean;
}

/**
 * Keyboard shortcuts for the book reader views.
 *
 * Navigation (paginated; see `onScrollBy` for scroll mode):
 *   ArrowRight / ArrowDown / j / PageDown / Space  → next page
 *   ArrowLeft  / ArrowUp   / k / PageUp            → prev page
 *   Home                                            → first page
 *   End                                             → last page
 *
 * Zoom:
 *   +/= (with or without Ctrl)  → zoom in
 *   -   (with or without Ctrl)  → zoom out
 *   0   (Ctrl)                  → reset zoom
 *
 * Toggles:
 *   f        → fullscreen
 *   s        → sidebar (LLM panel)
 *   t        → table of contents
 *   Escape   → go back / exit fullscreen
 */
export function useReaderKeyboard(actions: ReaderKeyboardActions) {
  const actionsRef = useRef(actions);
  useEffect(() => {
    actionsRef.current = actions;
  });

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    const a = actionsRef.current;
    if (a.disabled) return;

    const target = e.target as HTMLElement;
    const isInput =
      target.tagName === 'INPUT' ||
      target.tagName === 'TEXTAREA' ||
      target.tagName === 'SELECT' ||
      target.isContentEditable;

    // Escape always works
    if (e.key === 'Escape') {
      e.preventDefault();
      a.onGoBack?.();
      return;
    }

    if (isInput) return;

    // Scrolling, when the reader scrolls rather than flips.
    if (a.onScrollBy) {
      const scroll: Record<string, [1 | -1, 'line' | 'screen']> = {
        ArrowDown: [1, 'line'],
        ArrowUp: [-1, 'line'],
        PageDown: [1, 'screen'],
        PageUp: [-1, 'screen'],
        ' ': [e.shiftKey ? -1 : 1, 'screen'],
      };
      const hit = scroll[e.key];
      if (hit) {
        e.preventDefault();
        a.onScrollBy(...hit);
        return;
      }
    }

    // Navigation
    switch (e.key) {
      case 'ArrowRight':
      case 'ArrowDown':
      case 'PageDown':
        e.preventDefault();
        a.onNextPage?.();
        return;
      case ' ':
        // Space: next page unless shift held (shift+space = prev)
        e.preventDefault();
        if (e.shiftKey) a.onPrevPage?.();
        else a.onNextPage?.();
        return;
      case 'ArrowLeft':
      case 'ArrowUp':
      case 'PageUp':
        e.preventDefault();
        a.onPrevPage?.();
        return;
      case 'Home':
        e.preventDefault();
        a.onFirstPage?.();
        return;
      case 'End':
        e.preventDefault();
        a.onLastPage?.();
        return;
    }

    // j / k vim navigation
    if (e.key === 'j' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      a.onNextPage?.();
      return;
    }
    if (e.key === 'k' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      a.onPrevPage?.();
      return;
    }

    // Zoom
    if ((e.key === '=' || e.key === '+') && !e.metaKey) {
      e.preventDefault();
      a.onZoomIn?.();
      return;
    }
    if (e.key === '-' && !e.metaKey) {
      e.preventDefault();
      a.onZoomOut?.();
      return;
    }
    if (e.key === '0' && e.ctrlKey) {
      e.preventDefault();
      a.onZoomReset?.();
      return;
    }

    // Toggles
    if (e.key === 'f' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      a.onToggleFullscreen?.();
      return;
    }
    if (e.key === 's' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      a.onToggleSidebar?.();
      return;
    }
    if (e.key === 't' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      a.onToggleToc?.();
      return;
    }
  }, []);

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);
}
