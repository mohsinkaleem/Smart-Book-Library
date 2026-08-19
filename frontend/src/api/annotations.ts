/** Highlights, bookmarks and margin notes. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { get, patch, post } from './client';
import type { Annotation, AnnotationKind } from './types';

export interface AnnotationDraft {
  book_id: string;
  kind?: AnnotationKind;
  text?: string;
  note?: string;
  color?: string;
  page?: number | null;
  cfi?: string;
  anchor_text?: string;
}

/** Every annotation in one book, in reading order. */
export function useAnnotations(bookId: string) {
  return useQuery<{ annotations: Annotation[]; total: number }>({
    queryKey: ['annotations', bookId],
    queryFn: () => get(`/api/annotations?book_id=${encodeURIComponent(bookId)}`),
    enabled: !!bookId,
  });
}

export function useCreateAnnotation(bookId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (draft: AnnotationDraft) => post<Annotation>('/api/annotations', draft),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['annotations', bookId] }),
  });
}

export function useUpdateAnnotation(bookId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, fields }: { id: string; fields: Partial<Annotation> }) =>
      patch<Annotation>(`/api/annotations/${id}`, fields),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['annotations', bookId] }),
  });
}

export function useDeleteAnnotation(bookId: string) {
  const qc = useQueryClient();
  return useMutation({
    // `client.request` parses JSON, and DELETE answers 204 with no body —
    // so this one call goes direct rather than through the wrapper.
    mutationFn: async (id: string) => {
      const res = await fetch(`/api/annotations/${id}`, { method: 'DELETE' });
      if (!res.ok && res.status !== 404) throw new Error('Failed to delete annotation');
      return id;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['annotations', bookId] }),
  });
}
