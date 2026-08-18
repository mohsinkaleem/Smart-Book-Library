/** Review queue API hooks. */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { get, post } from './client';
import type { Book, PaginatedResponse } from './types';

export interface ReviewBook extends Book {
  /** How sure we are *which book this is*, derived from `field_sources`.
   *  Distinct from `match_score`, which only scores an API candidate and is
   *  null for a record identified from the file's own metadata. Drives the
   *  queue order. */
  identity_confidence: number;
  match_score: number | null;
  review_reasons: string[];
  field_sources: Record<string, { source: string; confidence: number; at: string }>;
  rejected_candidates: {
    provider: string;
    title: string;
    authors: string[];
    score: number;
    reason: string;
  }[];
}

export function useReviewQueue(page = 1, perPage = 25) {
  return useQuery<PaginatedResponse<ReviewBook>>({
    queryKey: ['review-queue', page, perPage],
    queryFn: () => get(`/api/review/queue?page=${page}&per_page=${perPage}`),
  });
}

export function usePinField() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, field, value }: { id: string; field: string; value: unknown }) =>
      post(`/api/review/${id}/pin`, { field, value }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['review-queue'] });
      qc.invalidateQueries({ queryKey: ['books'] });
    },
  });
}

export function useResolveReview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, resolution }: { id: string; resolution?: string }) =>
      post(`/api/review/${id}/resolve`, { resolution: resolution ?? 'confirmed' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['review-queue'] });
      qc.invalidateQueries({ queryKey: ['books'] });
    },
  });
}
