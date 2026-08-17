import { useState, useRef, useEffect, useCallback } from 'react';
import { Search, X, Sparkles, Type, Blend, ArrowRight } from 'lucide-react';
import { useDebounce } from '../../hooks/useDebounce';
import { useSuggestions } from '../../api/books';
import clsx from 'clsx';

interface SearchBarProps {
  value: string;
  onChange: (v: string) => void;
  mode: string;
  onModeChange: (m: string) => void;
}

const MODE_INFO: Record<string, { icon: typeof Search; label: string; desc: string }> = {
  text: { icon: Type, label: 'Text', desc: 'Keyword search over metadata and book text' },
  semantic: { icon: Sparkles, label: 'Semantic', desc: 'AI meaning-based search' },
  hybrid: { icon: Blend, label: 'Hybrid', desc: 'Combined text + semantic (default)' },
};

const SUGGESTIONS_ID = 'search-suggestions';
const optionId = (idx: number) => `${SUGGESTIONS_ID}-option-${idx}`;

export function SearchBar({ value, onChange, mode, onModeChange }: SearchBarProps) {
  const [focused, setFocused] = useState(false);
  const [local, setLocal] = useState(value);
  const [selectedIdx, setSelectedIdx] = useState(-1);
  const debounced = useDebounce(local, 250);
  const inputRef = useRef<HTMLInputElement>(null);
  const { data: suggestions } = useSuggestions(debounced);

  useEffect(() => { onChange(debounced); }, [debounced, onChange]);
  useEffect(() => { setLocal(value); }, [value]);
  // Reset selection when suggestions change
  useEffect(() => { setSelectedIdx(-1); }, [suggestions]);

  // Keyboard shortcut: / to focus
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === '/' && document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA') {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const showDropdown = focused && local.length >= 2 && suggestions && suggestions.length > 0;

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (!showDropdown || !suggestions) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIdx((prev) => Math.min(prev + 1, suggestions.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIdx((prev) => Math.max(prev - 1, -1));
    } else if (e.key === 'Enter' && selectedIdx >= 0) {
      e.preventDefault();
      const s = suggestions[selectedIdx];
      setLocal(s.title);
      onChange(s.title);
      setFocused(false);
      inputRef.current?.blur();
    } else if (e.key === 'Escape') {
      setFocused(false);
      inputRef.current?.blur();
    }
  }, [showDropdown, suggestions, selectedIdx, onChange]);

  // Highlight matching text in suggestion
  const highlightMatch = (text: string, query: string) => {
    if (!query.trim()) return text;
    const terms = query.trim().split(/\s+/).filter(Boolean);
    const regex = new RegExp(`(${terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'gi');
    const parts = text.split(regex);
    return parts.map((part, i) =>
      regex.test(part) ? <mark key={i} className="bg-primary-100 text-primary-800 rounded-sm px-0.5 dark:bg-primary-900/50 dark:text-primary-200">{part}</mark> : part
    );
  };

  return (
    <div className="relative">
      <div className="flex items-center gap-2">
        <div className={clsx(
          'flex flex-1 items-center rounded-xl bg-white shadow-sm ring-1 transition-all dark:bg-slate-800',
          focused ? 'ring-primary-400 shadow-md max-w-[600px]' : 'ring-slate-200 dark:ring-slate-700 max-w-[500px]',
        )}>
          <Search size={18} className="ml-3 shrink-0 text-slate-400" />
          {/* The dropdown implements full keyboard navigation and announced
              none of it: no combobox role, no listbox, no active option. */}
          <input
            ref={inputRef}
            type="text"
            placeholder={`Search books${mode === 'semantic' ? ' by meaning' : mode === 'hybrid' ? ' (text + AI)' : ''}... (press /)`}
            value={local}
            onChange={(e) => setLocal(e.target.value)}
            onFocus={() => setFocused(true)}
            onBlur={() => setTimeout(() => setFocused(false), 200)}
            onKeyDown={handleKeyDown}
            role="combobox"
            aria-label="Search books"
            aria-expanded={!!showDropdown}
            aria-controls={SUGGESTIONS_ID}
            aria-autocomplete="list"
            aria-activedescendant={
              showDropdown && selectedIdx >= 0 ? optionId(selectedIdx) : undefined
            }
            className="w-full bg-transparent px-3 py-2.5 text-sm outline-none placeholder:text-slate-400"
          />
          {local && (
            <button onClick={() => { setLocal(''); onChange(''); }} className="mr-2 text-slate-400 hover:text-slate-600">
              <X size={16} />
            </button>
          )}
          {!focused && !local && (
            <kbd className="mr-3 hidden rounded border border-slate-200 px-1.5 py-0.5 text-[10px] font-medium text-slate-400 dark:border-slate-600 sm:inline-block">/</kbd>
          )}
        </div>
        {/* Mode toggle */}
        <div className="flex rounded-lg bg-slate-100 p-0.5 dark:bg-slate-700/50">
          {(['text', 'semantic', 'hybrid'] as const).map((m) => {
            const info = MODE_INFO[m];
            const Icon = info.icon;
            return (
              <button
                key={m}
                onClick={() => onModeChange(m)}
                title={info.desc}
                className={clsx(
                  'flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-medium capitalize transition-colors',
                  mode === m
                    ? 'bg-white text-primary-700 shadow-sm dark:bg-slate-600 dark:text-primary-300'
                    : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200',
                )}
              >
                <Icon size={12} />
                <span className="hidden sm:inline">{info.label}</span>
              </button>
            );
          })}
        </div>
      </div>
      {/* Suggestions dropdown */}
      {showDropdown && (
        <div className="absolute top-12 left-0 z-50 w-full max-w-[500px] overflow-hidden rounded-lg bg-white shadow-lg ring-1 ring-slate-200 dark:bg-slate-800 dark:ring-slate-700">
          <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            Suggestions
          </div>
          <ul id={SUGGESTIONS_ID} role="listbox" aria-label="Search suggestions">
            {suggestions!.map((s, idx) => (
              <li
                key={s.id}
                id={optionId(idx)}
                role="option"
                aria-selected={idx === selectedIdx}
                onMouseDown={() => { setLocal(s.title); onChange(s.title); }}
                onMouseEnter={() => setSelectedIdx(idx)}
                className={clsx(
                  'flex w-full cursor-pointer items-center gap-2.5 px-3 py-2 text-left text-sm transition-colors',
                  idx === selectedIdx
                    ? 'bg-primary-50 dark:bg-primary-900/20'
                    : 'hover:bg-slate-50 dark:hover:bg-slate-700',
                )}
              >
                <Search size={14} className="shrink-0 text-slate-400" />
                <div className="flex-1 min-w-0">
                  <span className="truncate font-medium block">{highlightMatch(s.title, local)}</span>
                </div>
                <span className="ml-auto shrink-0 truncate max-w-[150px] text-xs text-slate-400">{s.author}</span>
                {idx === selectedIdx && <ArrowRight size={12} className="shrink-0 text-primary-400" />}
              </li>
            ))}
          </ul>
          {local.length >= 2 && (
            <div className="border-t border-slate-100 px-3 py-2 text-[11px] text-slate-400 dark:border-slate-700">
              Press <kbd className="rounded border border-slate-200 px-1 text-[10px] dark:border-slate-600">Enter</kbd> to search
              {' · '}
              <kbd className="rounded border border-slate-200 px-1 text-[10px] dark:border-slate-600">↑↓</kbd> to navigate
            </div>
          )}
        </div>
      )}
    </div>
  );
}
