import { useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Plus, Tag, X } from 'lucide-react';
import { useFilters } from '../../api/books';

interface TagEditorProps {
  tags: string[];
  onChange: (tags: string[]) => void;
  disabled?: boolean;
}

/** Tags are stored lowercase and trimmed, so `Sufism` and `sufism ` are one tag. */
function normalise(raw: string): string {
  return raw.trim().toLowerCase().replace(/\s+/g, ' ');
}

/**
 * Add and remove a book's tags.
 *
 * `user_tags` was stored, indexed, faceted in the sidebar and exposed as a
 * `tag` filter — with nothing anywhere in the UI that could put a tag on a
 * book. The facet list was permanently empty and the filter permanently
 * unusable.
 *
 * Existing tags are offered as suggestions, because a tag vocabulary that
 * drifts into `sufi`/`sufism`/`Sufism` filters nothing useful.
 */
export function TagEditor({ tags, onChange, disabled }: TagEditorProps) {
  const [draft, setDraft] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const { data: facets } = useFilters();

  const suggestions = useMemo(() => {
    const typed = normalise(draft);
    return (facets?.tags ?? [])
      .filter((t) => !tags.includes(t.name) && (!typed || t.name.includes(typed)))
      .slice(0, 6);
  }, [facets?.tags, tags, draft]);

  const add = (raw: string) => {
    const tag = normalise(raw);
    if (!tag || tags.includes(tag)) {
      setDraft('');
      return;
    }
    onChange([...tags, tag]);
    setDraft('');
    inputRef.current?.focus();
  };

  const remove = (tag: string) => onChange(tags.filter((t) => t !== tag));

  return (
    <section>
      <h2 className="mb-2 flex items-center gap-1.5 text-sm font-bold uppercase tracking-wider text-slate-500">
        <Tag size={13} /> Tags
      </h2>

      <div className="flex flex-wrap items-center gap-1.5">
        {tags.map((tag) => (
          <span
            key={tag}
            className="inline-flex items-center gap-1 rounded-md bg-primary-50 py-1 pl-2 pr-1 text-xs font-medium text-primary-700 dark:bg-primary-900/30 dark:text-primary-300"
          >
            {/* Straight to the filtered library — the whole point of tagging. */}
            <Link to={`/?tag=${encodeURIComponent(tag)}`} className="hover:underline">
              {tag}
            </Link>
            <button
              onClick={() => remove(tag)}
              disabled={disabled}
              aria-label={`Remove tag ${tag}`}
              className="rounded p-0.5 text-primary-400 hover:bg-primary-100 hover:text-primary-700 disabled:opacity-50 dark:hover:bg-primary-900/50"
            >
              <X size={11} />
            </button>
          </span>
        ))}

        <form
          onSubmit={(e) => {
            e.preventDefault();
            add(draft);
          }}
          className="flex items-center"
        >
          <input
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              // Backspace on an empty field removes the last tag, the way
              // every other tag input behaves.
              if (e.key === 'Backspace' && !draft && tags.length) {
                e.preventDefault();
                remove(tags[tags.length - 1]);
              }
            }}
            disabled={disabled}
            placeholder="Add a tag…"
            aria-label="Add a tag"
            className="w-28 rounded-md border border-dashed border-slate-300 bg-transparent px-2 py-1 text-xs outline-none placeholder:text-slate-400 focus:border-solid focus:border-primary-400 disabled:opacity-50 dark:border-slate-600"
          />
          {draft.trim() && (
            <button
              type="submit"
              aria-label={`Add tag ${normalise(draft)}`}
              className="ml-1 rounded p-1 text-primary-600 hover:bg-primary-50 dark:text-primary-400 dark:hover:bg-primary-900/30"
            >
              <Plus size={13} />
            </button>
          )}
        </form>
      </div>

      {suggestions.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-slate-400">Existing:</span>
          {suggestions.map((t) => (
            <button
              key={t.name}
              onClick={() => add(t.name)}
              disabled={disabled}
              className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600 hover:bg-slate-200 disabled:opacity-50 dark:bg-slate-700 dark:text-slate-300 dark:hover:bg-slate-600"
            >
              {t.name}
              <span className="ml-1 text-slate-400">{t.count}</span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
