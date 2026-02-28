import { useState, useRef, useEffect } from 'react';
import { Search, X } from 'lucide-react';
import { useDebounce } from '../../hooks/useDebounce';
import { useSuggestions } from '../../api/books';
import clsx from 'clsx';

interface SearchBarProps {
  value: string;
  onChange: (v: string) => void;
  mode: string;
  onModeChange: (m: string) => void;
}

export function SearchBar({ value, onChange, mode, onModeChange }: SearchBarProps) {
  const [focused, setFocused] = useState(false);
  const [local, setLocal] = useState(value);
  const debounced = useDebounce(local, 300);
  const inputRef = useRef<HTMLInputElement>(null);
  const { data: suggestions } = useSuggestions(debounced);

  useEffect(() => { onChange(debounced); }, [debounced, onChange]);
  useEffect(() => { setLocal(value); }, [value]);

  // Keyboard shortcut: / to focus
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === '/' && document.activeElement?.tagName !== 'INPUT') {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  return (
    <div className="relative">
      <div className="flex items-center gap-2">
        <div className={clsx(
          'flex flex-1 items-center rounded-xl bg-white shadow-sm ring-1 transition-all dark:bg-slate-800',
          focused ? 'ring-primary-400 shadow-md max-w-[600px]' : 'ring-slate-200 dark:ring-slate-700 max-w-[500px]',
        )}>
          <Search size={18} className="ml-3 shrink-0 text-slate-400" />
          <input
            ref={inputRef}
            type="text"
            placeholder="Search books... (press /)"
            value={local}
            onChange={(e) => setLocal(e.target.value)}
            onFocus={() => setFocused(true)}
            onBlur={() => setTimeout(() => setFocused(false), 200)}
            className="w-full bg-transparent px-3 py-2.5 text-sm outline-none placeholder:text-slate-400"
          />
          {local && (
            <button onClick={() => { setLocal(''); onChange(''); }} className="mr-2 text-slate-400 hover:text-slate-600">
              <X size={16} />
            </button>
          )}
        </div>
        {/* Mode toggle */}
        <div className="flex rounded-lg bg-slate-100 p-0.5 dark:bg-slate-700/50">
          {['text', 'semantic', 'hybrid'].map((m) => (
            <button
              key={m}
              onClick={() => onModeChange(m)}
              className={clsx(
                'rounded-md px-2.5 py-1.5 text-xs font-medium capitalize transition-colors',
                mode === m
                  ? 'bg-white text-primary-700 shadow-sm dark:bg-slate-600 dark:text-primary-300'
                  : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200',
              )}
            >
              {m}
            </button>
          ))}
        </div>
      </div>
      {/* Suggestions dropdown */}
      {focused && suggestions && suggestions.length > 0 && local.length >= 2 && (
        <div className="absolute top-12 left-0 z-50 w-full max-w-[400px] overflow-hidden rounded-lg bg-white shadow-lg ring-1 ring-slate-200 dark:bg-slate-800 dark:ring-slate-700">
          {suggestions.map((s) => (
            <button
              key={s.id}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-700"
              onMouseDown={() => { setLocal(s.title); onChange(s.title); }}
            >
              <Search size={14} className="shrink-0 text-slate-400" />
              <span className="truncate font-medium">{s.title}</span>
              <span className="ml-auto truncate text-xs text-slate-400">{s.author}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
