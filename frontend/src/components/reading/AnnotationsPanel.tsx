import { useState } from 'react';
import { Bookmark, Highlighter, StickyNote, Trash2, Pencil, Check, X } from 'lucide-react';
import {
  useAnnotations,
  useDeleteAnnotation,
  useUpdateAnnotation,
} from '../../api/annotations';
import { HIGHLIGHT_COLORS } from './SelectionToolbar';
import { Spinner } from '../common/Spinner';
import type { Annotation, AnnotationKind } from '../../api/types';

const KIND_ICON: Record<AnnotationKind, typeof Highlighter> = {
  highlight: Highlighter,
  bookmark: Bookmark,
  note: StickyNote,
};

const FILTERS: { id: 'all' | AnnotationKind; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'highlight', label: 'Highlights' },
  { id: 'note', label: 'Notes' },
  { id: 'bookmark', label: 'Bookmarks' },
];

function swatch(color: string): string {
  return HIGHLIGHT_COLORS.find((c) => c.id === color)?.swatch ?? '#fde68a';
}

interface AnnotationsPanelProps {
  bookId: string;
  /** Jump the reader to an annotation's anchor. */
  onNavigate: (annotation: Annotation) => void;
}

/**
 * The reader's own marks on this book, in reading order.
 *
 * Nothing in the catalog stored these before — no highlights, no bookmarks,
 * no margin notes — which made "smart library" mean "library that reads you
 * metadata".
 */
export function AnnotationsPanel({ bookId, onNavigate }: AnnotationsPanelProps) {
  const { data, isLoading } = useAnnotations(bookId);
  const { mutate: remove } = useDeleteAnnotation(bookId);
  const { mutate: update } = useUpdateAnnotation(bookId);
  const [filter, setFilter] = useState<'all' | AnnotationKind>('all');
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState('');

  const all = data?.annotations ?? [];
  const shown = filter === 'all' ? all : all.filter((a) => a.kind === filter);

  if (isLoading) {
    return (
      <div className="flex justify-center py-8">
        <Spinner size={20} />
      </div>
    );
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-1">
        {FILTERS.map((f) => {
          const count = f.id === 'all' ? all.length : all.filter((a) => a.kind === f.id).length;
          return (
            <button
              key={f.id}
              onClick={() => setFilter(f.id)}
              className={`rounded-md px-2 py-1 text-xs font-medium transition-colors ${
                filter === f.id
                  ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
                  : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'
              }`}
            >
              {f.label} <span className="tabular-nums opacity-60">{count}</span>
            </button>
          );
        })}
      </div>

      {shown.length === 0 ? (
        <div className="rounded-lg bg-slate-100 p-4 text-center text-sm text-slate-500 dark:bg-slate-700/50 dark:text-slate-400">
          <Highlighter size={22} className="mx-auto mb-2 opacity-50" />
          <p className="font-medium">Nothing marked yet</p>
          <p className="mt-1 text-xs">
            Select a passage to highlight it or attach a note, or press B to bookmark
            where you are.
          </p>
        </div>
      ) : (
        <ul className="space-y-2">
          {shown.map((a) => {
            const Icon = KIND_ICON[a.kind];
            const isEditing = editing === a.id;
            return (
              <li
                key={a.id}
                className="group rounded-lg bg-white p-3 text-xs shadow-sm ring-1 ring-slate-100 dark:bg-slate-700 dark:ring-slate-600"
              >
                <div className="flex items-center gap-1.5">
                  <Icon size={12} className="shrink-0 text-slate-400" />
                  <button
                    onClick={() => onNavigate(a)}
                    className="font-medium text-primary-600 hover:underline dark:text-primary-400"
                  >
                    {a.page ? `Page ${a.page}` : a.cfi ? 'Go to location' : 'Unanchored'}
                  </button>
                  {a.kind === 'highlight' && (
                    <span
                      className="h-2.5 w-2.5 rounded-full ring-1 ring-slate-300 dark:ring-slate-500"
                      style={{ backgroundColor: swatch(a.color) }}
                    />
                  )}
                  <div className="ml-auto flex gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                    <button
                      onClick={() => { setEditing(a.id); setDraft(a.note); }}
                      aria-label="Edit note"
                      className="rounded p-1 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-600"
                    >
                      <Pencil size={12} />
                    </button>
                    <button
                      onClick={() => remove(a.id)}
                      aria-label="Delete annotation"
                      className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/30"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>

                {a.text && (
                  <p
                    className="mt-1.5 line-clamp-4 border-l-2 pl-2 italic text-slate-600 dark:text-slate-300"
                    style={{ borderColor: swatch(a.color) }}
                  >
                    {a.text}
                  </p>
                )}

                {isEditing ? (
                  <div className="mt-2">
                    <textarea
                      autoFocus
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      rows={3}
                      placeholder="Your note…"
                      className="w-full rounded border border-slate-200 bg-transparent p-2 text-xs dark:border-slate-500"
                    />
                    <div className="mt-1 flex justify-end gap-1">
                      <button
                        onClick={() => setEditing(null)}
                        className="flex items-center gap-1 rounded px-2 py-1 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-600"
                      >
                        <X size={12} /> Cancel
                      </button>
                      <button
                        onClick={() => {
                          update({ id: a.id, fields: { note: draft } });
                          setEditing(null);
                        }}
                        className="flex items-center gap-1 rounded bg-primary-600 px-2 py-1 font-medium text-white hover:bg-primary-700"
                      >
                        <Check size={12} /> Save
                      </button>
                    </div>
                  </div>
                ) : (
                  a.note && (
                    <p className="mt-1.5 whitespace-pre-wrap text-slate-500 dark:text-slate-400">
                      {a.note}
                    </p>
                  )
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
