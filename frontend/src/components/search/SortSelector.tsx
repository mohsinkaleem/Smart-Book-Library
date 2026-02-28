import { ArrowUpDown } from 'lucide-react';
import clsx from 'clsx';

interface SortSelectorProps {
  sort: string;
  order: string;
  onChange: (sort: string, order: string) => void;
}

const sortOptions = [
  { value: 'title', label: 'Title' },
  { value: 'author', label: 'Author' },
  { value: 'date_added', label: 'Date Added' },
  { value: 'year', label: 'Year' },
  { value: 'size', label: 'Size' },
  { value: 'pages', label: 'Pages' },
  { value: 'rating', label: 'Rating' },
];

export function SortSelector({ sort, order, onChange }: SortSelectorProps) {
  return (
    <div className="flex items-center gap-2">
      <select
        value={sort}
        onChange={(e) => onChange(e.target.value, order)}
        className="rounded-lg border-0 bg-slate-100 py-1.5 pl-3 pr-8 text-xs font-medium text-slate-700 ring-1 ring-inset ring-slate-200 focus:ring-2 focus:ring-primary-500 dark:bg-slate-700 dark:text-slate-300 dark:ring-slate-600"
      >
        {sortOptions.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
      <button
        onClick={() => onChange(sort, order === 'asc' ? 'desc' : 'asc')}
        className={clsx(
          'rounded-lg p-1.5 text-slate-500 ring-1 ring-slate-200 transition-colors hover:bg-slate-100 dark:ring-slate-600 dark:hover:bg-slate-700',
          order === 'desc' && 'rotate-180',
        )}
      >
        <ArrowUpDown size={14} />
      </button>
    </div>
  );
}
