import { useEffect, useRef } from 'react';
import { X, Keyboard } from 'lucide-react';
import { SHORTCUTS } from '../../hooks/useKeyboardShortcuts';

interface KeyboardShortcutsDialogProps {
  open: boolean;
  onClose: () => void;
}

export function KeyboardShortcutsDialog({ open, onClose }: KeyboardShortcutsDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' || e.key === '?') {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  const categories = [...new Set(SHORTCUTS.map((s) => s.category))];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={onClose}>
      <div
        ref={dialogRef}
        className="mx-4 w-full max-w-lg rounded-2xl bg-white shadow-2xl ring-1 ring-slate-200 dark:bg-slate-800 dark:ring-slate-700"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-slate-200 px-6 py-4 dark:border-slate-700">
          <Keyboard size={20} className="text-primary-500" />
          <h2 className="flex-1 text-lg font-bold text-slate-900 dark:text-white">Keyboard Shortcuts</h2>
          <button onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700">
            <X size={18} />
          </button>
        </div>

        <div className="max-h-[60vh] overflow-y-auto px-6 py-4">
          {categories.map((cat) => (
            <div key={cat} className="mb-4 last:mb-0">
              <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-400">{cat}</h3>
              <div className="space-y-1.5">
                {SHORTCUTS.filter((s) => s.category === cat).map((s) => (
                  <div key={s.key} className="flex items-center justify-between rounded-lg px-2 py-1.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-700/50">
                    <span className="text-slate-700 dark:text-slate-300">{s.label}</span>
                    <div className="flex gap-1">
                      {s.key.split(' ').map((k, i) => (
                        <span key={i}>
                          {i > 0 && <span className="mx-0.5 text-xs text-slate-400">then</span>}
                          <kbd className="inline-block min-w-6 rounded-md border border-slate-200 bg-slate-100 px-1.5 py-0.5 text-center text-xs font-mono font-semibold text-slate-600 shadow-sm dark:border-slate-600 dark:bg-slate-700 dark:text-slate-300">
                            {k}
                          </kbd>
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="border-t border-slate-200 px-6 py-3 dark:border-slate-700">
          <p className="text-center text-xs text-slate-400">
            Press <kbd className="mx-0.5 rounded border border-slate-200 bg-slate-100 px-1 py-0.5 text-[10px] font-mono dark:border-slate-600 dark:bg-slate-700">?</kbd> or <kbd className="mx-0.5 rounded border border-slate-200 bg-slate-100 px-1 py-0.5 text-[10px] font-mono dark:border-slate-600 dark:bg-slate-700">Esc</kbd> to close
          </p>
        </div>
      </div>
    </div>
  );
}
