/** Book API hooks using TanStack Query. */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { get, patch, post } from './client';
import type { Book, PaginatedResponse, FilterFacets, StatsData, Suggestion, CompareMatch } from './types';

interface BookListParams {
  /** Filters arrive as a `Record<string, string>` straight from the URL. */
  [key: string]: unknown;
  page?: number;
  per_page?: number;
  sort?: string;
  order?: string;
  file_type?: string;
  category?: string;
  theme?: string;
  language?: string;
  reading_status?: string;
  has_cover?: boolean;
  year_min?: number;
  year_max?: number;
  rating_min?: number;
  favorite?: boolean;
  author?: string;
  tag?: string;
  search?: string;
}

function buildParams(params: Record<string, unknown>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') {
      sp.set(k, String(v));
    }
  }
  return sp.toString();
}

export function useBooks(params: BookListParams, enabled = true) {
  const qs = buildParams(params as Record<string, unknown>);
  return useQuery<PaginatedResponse<Book>>({
    queryKey: ['books', qs],
    queryFn: () => get(`/api/books?${qs}`),
    enabled,
  });
}

export function useBook(id: string) {
  return useQuery<Book>({
    queryKey: ['book', id],
    queryFn: () => get(`/api/books/${id}`),
    enabled: !!id,
  });
}

export function useSimilarBooks(id: string, limit = 8) {
  return useQuery<Book[]>({
    queryKey: ['similar', id],
    queryFn: () => get(`/api/books/${id}/similar?limit=${limit}`),
    enabled: !!id,
  });
}

export function useBookText(id: string) {
  return useQuery<{ id: string; title: string; text: string }>({
    queryKey: ['bookText', id],
    queryFn: () => get(`/api/reading/${id}/text`),
    enabled: !!id,
  });
}

export function useUpdateBook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, fields }: { id: string; fields: Record<string, unknown> }) =>
      patch<Book>(`/api/books/${id}`, fields),
    onSuccess: (_data, { id }) => {
      qc.invalidateQueries({ queryKey: ['book', id] });
      qc.invalidateQueries({ queryKey: ['books'] });
    },
  });
}

export function useFilters(params?: Record<string, string>) {
  const qs = params ? buildParams(params as Record<string, unknown>) : '';
  return useQuery<FilterFacets>({
    queryKey: ['filters', qs],
    queryFn: () => get(`/api/filters${qs ? `?${qs}` : ''}`),
    staleTime: 10_000,       // revalidate more often since facets are reactive
    placeholderData: (prev) => prev,  // keep previous data while loading to avoid flicker
  });
}

export function useStats() {
  return useQuery<StatsData>({
    queryKey: ['stats'],
    queryFn: () => get('/api/stats'),
  });
}

/** Books opened and not finished, most recently opened first. */
export function useContinueReading(limit = 8) {
  return useQuery<Book[]>({
    queryKey: ['continueReading', limit],
    queryFn: () => get(`/api/books/continue-reading?limit=${limit}`),
  });
}

/** Files on disk that the pipeline has not catalogued yet. */
export function useUnprocessed() {
  return useQuery<{ unprocessed: number; total_files: number; error?: string }>({
    queryKey: ['unprocessed'],
    queryFn: () => get('/api/pipeline/unprocessed'),
    staleTime: 60_000,
  });
}

/** Whether the Analysis buttons will do anything, and why not when they won't. */
export function useLlmStatus() {
  return useQuery<{
    available: boolean;
    model?: string;
    model_installed?: boolean;
    reason?: string;
    base_url?: string;
  }>({
    queryKey: ['llmStatus'],
    queryFn: () => get('/api/reading/llm-status'),
    staleTime: 30_000,
  });
}

interface SearchParams {
  /** Filters arrive as a `Record<string, string>` straight from the URL. */
  [key: string]: unknown;
  q: string;
  mode?: string;
  page?: number;
  per_page?: number;
  file_type?: string;
  category?: string;
  theme?: string;
  language?: string;
  reading_status?: string;
  favorite?: boolean;
  has_cover?: boolean;
  has_description?: boolean;
  year_min?: number;
  year_max?: number;
  author?: string;
  tag?: string;
}

export function useSearch(params: SearchParams, enabled = true) {
  const qs = buildParams(params as unknown as Record<string, unknown>);
  return useQuery<PaginatedResponse<Book>>({
    queryKey: ['search', qs],
    queryFn: () => get(`/api/search?${qs}`),
    enabled: enabled && !!params.q,
  });
}

interface PagedBooksParams {
  searchQuery: string;
  searchMode: string;
  filters: Record<string, string>;
  page: number;
  perPage: number;
  sort: string;
  order: string;
}

/**
 * One page of books, from `/api/search` when searching and `/api/books`
 * otherwise.
 *
 * `HomePage` used to pick between `useSearch(...)` and `useBooks(...)` with a
 * ternary — two `rules-of-hooks` violations that only worked because both
 * branches happened to call the same number of hooks internally. Both run
 * unconditionally now; `enabled` decides which one actually fetches.
 */
export function usePagedBooks({
  searchQuery, searchMode, filters, page, perPage, sort, order,
}: PagedBooksParams) {
  const searching = !!searchQuery;

  const searchResult = useSearch(
    { q: searchQuery, mode: searchMode, page, per_page: perPage, ...filters },
    searching,
  );
  const listResult = useBooks(
    { page, per_page: perPage, sort, order, ...filters, search: searchQuery || undefined },
    !searching,
  );

  return searching ? searchResult : listResult;
}

export function useSuggestions(q: string) {
  return useQuery<Suggestion[]>({
    queryKey: ['suggest', q],
    queryFn: () => get(`/api/search/suggest?q=${encodeURIComponent(q)}`),
    enabled: q.length >= 2,
  });
}

export function useCompare() {
  return useMutation({
    mutationFn: (body: { text: string; book_id?: string; limit?: number }) =>
      post<{ matches: CompareMatch[] }>('/api/reading/compare', body),
  });
}

export function usePipelineStatus() {
  return useQuery({
    queryKey: ['pipelineStatus'],
    queryFn: () => get<Record<string, unknown>>('/api/pipeline/status'),
    refetchInterval: (query) => {
      const data = query.state.data;
      return data && (data as Record<string, unknown>).status === 'running' ? 2000 : false;
    },
  });
}
