/** Review queue API hooks. */
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { get, post } from './client';
import type { Book, PaginatedResponse } from './types';

/** Which question a record is waiting on.
 *  `review`       — a human's judgement would change something.
 *  `unidentified` — no provider had this book; nothing to confirm, but a
 *                   title read off the cover is still worth pinning. */
export type ReviewBucket = 'review' | 'unidentified';

export interface ReviewQueue<T> extends PaginatedResponse<T> {
  bucket: ReviewBucket;
  counts: Record<ReviewBucket, number>;
}

export interface ReviewBook extends Book {
  /** How sure we are *which book this is*, derived from `field_sources`.
   *  Distinct from `match_score`, which only scores an API candidate and is
   *  null for a record identified from the file's own metadata. Drives the
   *  queue order. */
  identity_confidence: number;
  match_score: number | null;
  /** Where enrichment ended up: verified | borderline | rejected | unmatched
   *  | no_evidence | deferred, or '' when the stage never ran. */
  enrichment_status: string;
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

export function useReviewQueue(page = 1, perPage = 25, bucket: ReviewBucket = 'review') {
  return useQuery<ReviewQueue<ReviewBook>>({
    queryKey: ['review-queue', page, perPage, bucket],
    queryFn: () =>
      get(`/api/review/queue?page=${page}&per_page=${perPage}&bucket=${bucket}`),
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
