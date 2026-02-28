
import { useSearchParams } from 'react-router-dom';
import { useBooks, useSearch, useUpdateBook } from '../api/books';
import { BookGrid } from '../components/books/BookGrid';
import { BookList } from '../components/books/BookList';
import { SortSelector } from '../components/search/SortSelector';
import { FilterChip } from '../components/search/FilterChip';
import { EmptyState } from '../components/common/EmptyState';
import { Spinner } from '../components/common/Spinner';
import { ChevronLeft, ChevronRight } from 'lucide-react';

interface HomePageProps {
  view: 'grid' | 'list';
  searchQuery: string;
  searchMode: string;
  filters: Record<string, string>;
  onFilterChange: (key: string, value: string) => void;
}

export function HomePage({ view, searchQuery, searchMode, filters, onFilterChange }: HomePageProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const page = parseInt(searchParams.get('page') || '1');
  const sort = searchParams.get('sort') || 'title';
  const order = searchParams.get('order') || 'asc';
  const perPage = view === 'grid' ? 48 : 100;
  const updateBook = useUpdateBook();

  // Build params
  const queryParams = {
    page,
    per_page: perPage,
    sort,
    order,
    ...Object.fromEntries(Object.entries(filters).filter(([_, v]) => v)),
    ...(searchQuery ? { search: searchQuery } : {}),
  };

  // Use search API if searching, otherwise regular books API
  const booksQuery = searchQuery
    ? useSearch({ q: searchQuery, mode: searchMode, page, per_page: perPage, ...Object.fromEntries(Object.entries(filters).filter(([_, v]) => v)) })
    : useBooks(queryParams);

  const handleSortChange = (newSort: string, newOrder: string) => {
    const params = new URLSearchParams(searchParams);
    params.set('sort', newSort);
    params.set('order', newOrder);
    params.set('page', '1');
    setSearchParams(params);
  };

  const handlePageChange = (newPage: number) => {
    const params = new URLSearchParams(searchParams);
    params.set('page', String(newPage));
    setSearchParams(params);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleFavorite = (id: string, fav: boolean) => {
    updateBook.mutate({ id, fields: { favorite: fav } });
  };

  // Active filters display
  const activeFilters = Object.entries(filters).filter(([_, v]) => v);

  return (
    <div className="flex flex-col gap-4 p-4 md:p-6">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-2">
          {activeFilters.map(([key, value]) => (
            <FilterChip
              key={key}
              label={key.replace('_', ' ')}
              value={value === 'true' ? 'Yes' : value}
              onRemove={() => onFilterChange(key, '')}
            />
          ))}
          {booksQuery.data && (
            <span className="text-sm text-slate-500">
              {booksQuery.data.total} book{booksQuery.data.total !== 1 ? 's' : ''}
            </span>
          )}
        </div>
        <SortSelector sort={sort} order={order} onChange={handleSortChange} />
      </div>

      {/* Content */}
      {booksQuery.isLoading ? (
        <div className="flex items-center justify-center py-20"><Spinner size={32} /></div>
      ) : booksQuery.data?.items.length === 0 ? (
        <EmptyState
          message={searchQuery ? `No results for "${searchQuery}"` : 'No books match your filters'}
          actionLabel={activeFilters.length > 0 ? 'Clear filters' : undefined}
          onAction={() => activeFilters.forEach(([k]) => onFilterChange(k, ''))}
        />
      ) : (
        <>
          {view === 'grid' ? (
            <BookGrid books={booksQuery.data?.items || []} onFavorite={handleFavorite} />
          ) : (
            <BookList books={booksQuery.data?.items || []} />
          )}

          {/* Pagination */}
          {booksQuery.data && booksQuery.data.pages > 1 && (
            <div className="flex items-center justify-center gap-4 py-4">
              <button
                onClick={() => handlePageChange(page - 1)}
                disabled={page <= 1}
                className="flex items-center gap-1 rounded-lg bg-white px-3 py-2 text-sm font-medium text-slate-600 shadow-sm ring-1 ring-slate-200 hover:bg-slate-50 disabled:opacity-50 dark:bg-slate-700 dark:text-slate-300 dark:ring-slate-600"
              >
                <ChevronLeft size={16} /> Previous
              </button>
              <span className="text-sm text-slate-500">
                Page {page} of {booksQuery.data.pages}
              </span>
              <button
                onClick={() => handlePageChange(page + 1)}
                disabled={page >= booksQuery.data.pages}
                className="flex items-center gap-1 rounded-lg bg-white px-3 py-2 text-sm font-medium text-slate-600 shadow-sm ring-1 ring-slate-200 hover:bg-slate-50 disabled:opacity-50 dark:bg-slate-700 dark:text-slate-300 dark:ring-slate-600"
              >
                Next <ChevronRight size={16} />
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
