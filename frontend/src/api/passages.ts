/** Passage search over the chunk index (Part 1). */
import { useMutation, useQuery } from '@tanstack/react-query';
import { get, post } from './client';
import type {
  ConceptThread,
  Passage,
  PassageIndexStatus,
  StanceGroups,
} from './types';

export type PassageScope = 'book' | 'catalog' | 'category' | 'author';
export type PassageMode = 'hybrid' | 'semantic' | 'keyword';

export interface PassageSearchRequest {
  /** A short search phrase. Encoded *with* bge's retrieval prefix. */
  query?: string;
  /** A passage of prose. Encoded *without* it — the two are not interchangeable. */
  text?: string;
  scope?: PassageScope;
  book_id?: string;
  exclude_book?: string;
  limit?: number;
  mode?: PassageMode;
  rerank?: boolean;
}

interface PassageSearchResponse {
  results: Passage[];
  scope: string;
  reranked: boolean;
}

/**
 * Whether passage features will work at all.
 *
 * Every passage panel gates on this so an unbuilt index reads as "not indexed
 * yet" rather than as "no matches" — those look identical in an empty list and
 * mean completely different things.
 */
export function usePassageIndexStatus() {
  return useQuery<PassageIndexStatus>({
    queryKey: ['passage-status'],
    queryFn: () => get('/api/passages/status'),
    staleTime: 5 * 60_000,
  });
}

export function usePassageSearch() {
  return useMutation({
    mutationFn: (body: PassageSearchRequest) =>
      post<PassageSearchResponse>('/api/passages/search', body),
  });
}

/**
 * Passages resembling a selection.
 *
 * `scope: 'book'` is §1.9.1 — "elsewhere in this book" — which was
 * structurally impossible before the chunk index: the old compare endpoint
 * skipped the current book outright, and there was only one vector per book to
 * match against anyway.
 */
export function useSimilarPassages() {
  return useMutation({
    mutationFn: (body: {
      text: string;
      book_id?: string;
      scope?: PassageScope;
      limit?: number;
    }) => post<{ results: Passage[]; scope: string }>('/api/passages/similar', body),
  });
}

export function usePassage(chunkId: number | null, span = 1) {
  return useQuery<Passage & { neighbours: Passage[] }>({
    queryKey: ['passage', chunkId, span],
    queryFn: () => get(`/api/passages/${chunkId}?span=${span}`),
    enabled: chunkId !== null,
  });
}

/** Recurring concepts within one book (§1.9.4). */
export function useConceptThreads(bookId: string, enabled = true) {
  return useQuery<{ threads: ConceptThread[]; message?: string }>({
    queryKey: ['concept-threads', bookId],
    queryFn: () => get(`/api/books/${encodeURIComponent(bookId)}/threads`),
    enabled: enabled && !!bookId,
    staleTime: 10 * 60_000,
  });
}

/** Supports / complicates / contradicts (§1.9.3). Needs the LLM. */
export function useStance() {
  return useMutation({
    mutationFn: (body: { text: string; book_id?: string; limit?: number }) =>
      post<{ groups: StanceGroups; passages: Passage[]; message?: string }>(
        '/api/passages/stance',
        body,
      ),
  });
}
