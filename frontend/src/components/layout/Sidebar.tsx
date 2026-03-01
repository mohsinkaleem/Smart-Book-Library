import { useState, useMemo } from 'react';
import { useFilters } from '../../api/books';
import { ChevronDown, ChevronRight, BookOpen } from 'lucide-react';
import clsx from 'clsx';

interface SidebarProps {
  filters: Record<string, string>;
  onFilterChange: (key: string, value: string) => void;
  onClearFilters: () => void;
  collapsed: boolean;
  searchQuery?: string;
}

function FilterSection({ title, children, defaultOpen = true }: { title: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-b border-slate-100 py-3 dark:border-slate-700/50">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center justify-between text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
        {title}
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </button>
      {open && <div className="mt-2 space-y-1">{children}</div>}
    </div>
  );
}

function FilterRadio({ label, value: _value, selected, count, onChange }: {
  label: string; value: string; selected: boolean; count?: number; onChange: () => void;
}) {
  const isEmpty = count === 0;
  return (
    <button
      onClick={onChange}
      className={clsx(
        'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs transition-colors',
        selected
          ? 'bg-primary-50 text-primary-700 font-medium dark:bg-primary-900/30 dark:text-primary-300'
          : isEmpty
            ? 'text-slate-300 dark:text-slate-600 cursor-default'
            : 'text-slate-600 hover:bg-slate-50 dark:text-slate-400 dark:hover:bg-slate-700/50',
      )}
      disabled={isEmpty && !selected}
    >
      <span className="truncate flex-1 text-left">{label}</span>
      {count !== undefined && (
        <span className={clsx(
          'shrink-0 tabular-nums text-[10px] min-w-[20px] text-right transition-all',
          selected ? 'text-primary-500 font-semibold' : isEmpty ? 'text-slate-300 dark:text-slate-600' : 'text-slate-400',
        )}>
          {count}
        </span>
      )}
    </button>
  );
}

export function Sidebar({ filters, onFilterChange, onClearFilters, collapsed, searchQuery }: SidebarProps) {
  // Build params for reactive facet query: include search + all active filters
  const facetParams = useMemo(() => {
    const params: Record<string, string> = {};
    if (searchQuery) params.search = searchQuery;
    // Pass all active filters so counts react to each other
    Object.entries(filters).forEach(([key, value]) => {
      if (value) params[key] = value;
    });
    return params;
  }, [filters, searchQuery]);

  const { data: facets, isFetching } = useFilters(facetParams);

  if (collapsed) return null;

  return (
    <aside className="h-full w-64 shrink-0 overflow-y-auto border-r border-slate-200 bg-white px-4 py-4 dark:border-slate-700 dark:bg-slate-800/50">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-bold text-slate-900 dark:text-white">
          <BookOpen size={18} className="text-primary-500" /> Filters
        </h2>
        {isFetching && (
          <div className="h-3 w-3 animate-spin rounded-full border-2 border-primary-400 border-t-transparent" />
        )}
      </div>
      {facets?.total_matching !== undefined && (searchQuery || Object.values(filters).some(Boolean)) && (
        <div className="mb-3 rounded-md bg-primary-50 px-2.5 py-1.5 text-xs font-medium text-primary-700 dark:bg-primary-900/30 dark:text-primary-300">
          {facets.total_matching} book{facets.total_matching !== 1 ? 's' : ''} matching
        </div>
      )}

      {/* Categories */}
      <FilterSection title="Categories">
        <FilterRadio label="All" value="" selected={!filters.category} onChange={() => onFilterChange('category', '')} />
        {facets?.categories.slice(0, 15).map((c) => (
          <FilterRadio
            key={c.name} label={c.name} value={c.name} count={c.count}
            selected={filters.category === c.name}
            onChange={() => onFilterChange('category', filters.category === c.name ? '' : c.name)}
          />
        ))}
      </FilterSection>

      {/* File Type */}
      <FilterSection title="File Type">
        <FilterRadio label="All" value="" selected={!filters.file_type} onChange={() => onFilterChange('file_type', '')} />
        {facets?.file_types.map((ft) => (
          <FilterRadio
            key={ft.name} label={ft.name.toUpperCase()} value={ft.name} count={ft.count}
            selected={filters.file_type === ft.name}
            onChange={() => onFilterChange('file_type', filters.file_type === ft.name ? '' : ft.name)}
          />
        ))}
      </FilterSection>

      {/* Reading Status */}
      <FilterSection title="Status" defaultOpen={false}>
        <FilterRadio label="All" value="" selected={!filters.reading_status} onChange={() => onFilterChange('reading_status', '')} />
        {facets?.reading_statuses.map((rs) => (
          <FilterRadio
            key={rs.name} label={rs.name.replace('_', ' ')} value={rs.name} count={rs.count}
            selected={filters.reading_status === rs.name}
            onChange={() => onFilterChange('reading_status', filters.reading_status === rs.name ? '' : rs.name)}
          />
        ))}
      </FilterSection>

      {/* Language */}
      <FilterSection title="Language" defaultOpen={false}>
        <FilterRadio label="All" value="" selected={!filters.language} onChange={() => onFilterChange('language', '')} />
        {facets?.languages.slice(0, 10).map((l) => (
          <FilterRadio
            key={l.name} label={l.name || 'Unknown'} value={l.name} count={l.count}
            selected={filters.language === l.name}
            onChange={() => onFilterChange('language', filters.language === l.name ? '' : l.name)}
          />
        ))}
      </FilterSection>

      {/* Quick filters */}
      <FilterSection title="Quick Filters">
        <FilterRadio
          label="Favorites" value="fav"
          selected={filters.favorite === 'true'}
          onChange={() => onFilterChange('favorite', filters.favorite === 'true' ? '' : 'true')}
        />
        <FilterRadio
          label="Has Cover" value="cover"
          selected={filters.has_cover === 'true'}
          onChange={() => onFilterChange('has_cover', filters.has_cover === 'true' ? '' : 'true')}
        />
        <FilterRadio
          label="Has Description" value="desc"
          selected={filters.has_description === 'true'}
          onChange={() => onFilterChange('has_description', filters.has_description === 'true' ? '' : 'true')}
        />
      </FilterSection>

      {/* Themes */}
      <FilterSection title="Themes" defaultOpen={false}>
        <FilterRadio label="All" value="" selected={!filters.theme} onChange={() => onFilterChange('theme', '')} />
        {facets?.themes.slice(0, 12).map((t) => (
          <FilterRadio
            key={t.name} label={t.name} value={t.name} count={t.count}
            selected={filters.theme === t.name}
            onChange={() => onFilterChange('theme', filters.theme === t.name ? '' : t.name)}
          />
        ))}
      </FilterSection>

      {/* Year range */}
      {facets?.years?.min && (
        <FilterSection title="Year Range" defaultOpen={false}>
          <div className="flex items-center gap-2 px-2">
            <input
              type="number"
              placeholder={String(facets.years.min)}
              value={filters.year_min || ''}
              onChange={(e) => onFilterChange('year_min', e.target.value)}
              className="w-20 rounded border border-slate-200 bg-slate-50 px-2 py-1 text-xs dark:border-slate-600 dark:bg-slate-700"
            />
            <span className="text-xs text-slate-400">—</span>
            <input
              type="number"
              placeholder={String(facets.years.max)}
              value={filters.year_max || ''}
              onChange={(e) => onFilterChange('year_max', e.target.value)}
              className="w-20 rounded border border-slate-200 bg-slate-50 px-2 py-1 text-xs dark:border-slate-600 dark:bg-slate-700"
            />
          </div>
        </FilterSection>
      )}

      {/* Clear all */}
      {Object.values(filters).some(Boolean) && (
        <button onClick={onClearFilters} className="mt-4 w-full rounded-lg bg-slate-100 py-2 text-xs font-medium text-slate-600 hover:bg-slate-200 dark:bg-slate-700 dark:text-slate-300 dark:hover:bg-slate-600">
          Clear all filters
        </button>
      )}
    </aside>
  );
}
