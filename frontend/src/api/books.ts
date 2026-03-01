/** Book API hooks using TanStack Query. */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { get, patch, post } from './client';
import type { Book, PaginatedResponse, FilterFacets, StatsData, Suggestion, CompareMatch } from './types';

interface BookListParams {
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

export function useBooks(params: BookListParams) {
  const qs = buildParams(params as Record<string, unknown>);
  return useQuery<PaginatedResponse<Book>>({
    queryKey: ['books', qs],
    queryFn: () => get(`/api/books?${qs}`),
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

interface SearchParams {
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

export function useSearch(params: SearchParams) {
  const qs = buildParams(params as unknown as Record<string, unknown>);
  return useQuery<PaginatedResponse<Book>>({
    queryKey: ['search', qs],
    queryFn: () => get(`/api/search?${qs}`),
    enabled: !!params.q,
  });
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
