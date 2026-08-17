import { useEffect } from 'react';
import { usePagedBooks, useUpdateBook } from '../api/books';
import { BookGrid } from '../components/books/BookGrid';
import { BookList } from '../components/books/BookList';
import { ContinueReading } from '../components/books/ContinueReading';
import { SortSelector } from '../components/search/SortSelector';
import { FilterChip } from '../components/search/FilterChip';
import { EmptyState } from '../components/common/EmptyState';
import { ErrorState } from '../components/common/ErrorBoundary';
import { Spinner } from '../components/common/Spinner';
import { ChevronLeft, ChevronRight } from 'lucide-react';

interface HomePageProps {
  view: 'grid' | 'list';
  searchQuery: string;
  searchMode: string;
  filters: Record<string, string>;
  page: number;
  sort: string;
  order: string;
  onFilterChange: (key: string, value: string) => void;
  onPageChange: (page: number) => void;
  onSortChange: (sort: string, order: string) => void;
  onPageCountChange: (pages: number) => void;
}

// Was 48 in grid / 100 in list, so toggling views deep in pagination could
// land you past the last page. One page size, one meaning for `page`.
const PER_PAGE = 48;

export function HomePage({
  view, searchQuery, searchMode, filters, page, sort, order,
  onFilterChange, onPageChange, onSortChange, onPageCountChange,
}: HomePageProps) {
  const updateBook = useUpdateBook();

  const booksQuery = usePagedBooks({
    searchQuery, searchMode, filters, page, perPage: PER_PAGE, sort, order,
  });

  const pages = booksQuery.data?.pages ?? 1;
  useEffect(() => { onPageCountChange(pages); }, [pages, onPageCountChange]);

  const handleFavorite = (id: string, fav: boolean) => {
    updateBook.mutate({ id, fields: { favorite: fav } });
  };

  const handlePageChange = (newPage: number) => {
    onPageChange(newPage);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const activeFilters = Object.entries(filters).filter(([, v]) => v);

  return (
    <div className="flex flex-col gap-4 p-4 md:p-6">
      {/* Only on the unfiltered library — a shelf of unrelated books above a
          filtered result set reads as part of the results. */}
      {!searchQuery && activeFilters.length === 0 && page === 1 && <ContinueReading />}

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
        {/* `/api/search` has no `sort` parameter — results come back ranked by
            relevance, so the control would be inert while searching. */}
        {searchQuery ? (
          <span className="text-xs text-slate-400">Sorted by relevance</span>
        ) : (
          <SortSelector sort={sort} order={order} onChange={onSortChange} />
        )}
      </div>

      {/* Content */}
      {booksQuery.isLoading ? (
        <div className="flex items-center justify-center py-20"><Spinner size={32} /></div>
      ) : booksQuery.isError ? (
        // A failed fetch used to leave `data` undefined, so the length check
        // below was false and the page silently rendered an empty grid.
        <ErrorState
          title="Couldn't load your library"
          message={(booksQuery.error as Error)?.message}
          onRetry={() => booksQuery.refetch()}
        />
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
                aria-label="Previous page"
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
                aria-label="Next page"
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
