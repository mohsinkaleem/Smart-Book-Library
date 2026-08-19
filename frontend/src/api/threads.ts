/** Passage-scoped LLM threads and reading sessions (§4.2, Part 5). */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { get, patch, post } from './client';
import type { LLMThread, ReadingSessionStats } from './types';

export function useThreads(bookId: string) {
  return useQuery<{ threads: LLMThread[]; total: number }>({
    queryKey: ['threads', bookId],
    queryFn: () => get(`/api/threads?book_id=${encodeURIComponent(bookId)}`),
    enabled: !!bookId,
  });
}

export function useThread(threadId: string | null) {
  return useQuery<LLMThread>({
    queryKey: ['thread', threadId],
    queryFn: () => get(`/api/threads/${threadId}`),
    enabled: !!threadId,
  });
}

export interface ThreadDraft {
  book_id: string;
  passage?: string;
  surrounding?: string;
  title?: string;
  page?: number | null;
  cfi?: string;
  /** Retrieve and pin related passages at creation. */
  retrieve?: boolean;
}

export function useCreateThread(bookId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (draft: ThreadDraft) => post<LLMThread>('/api/threads', draft),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['threads', bookId] }),
  });
}

export function useRenameThread(bookId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      patch<LLMThread>(`/api/threads/${id}`, { title }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['threads', bookId] });
      qc.invalidateQueries({ queryKey: ['thread', vars.id] });
    },
  });
}

export function useDeleteThread(bookId: string) {
  const qc = useQueryClient();
  return useMutation({
    // DELETE answers 204 with no body, which the JSON-parsing wrapper cannot
    // handle — same reason `useDeleteAnnotation` goes direct.
    mutationFn: async (id: string) => {
      const res = await fetch(`/api/threads/${id}`, { method: 'DELETE' });
      if (!res.ok && res.status !== 404) throw new Error('Failed to delete thread');
      return id;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['threads', bookId] }),
  });
}

/**
 * Send a follow-up and stream the reply.
 *
 * Not a react-query mutation: the value arrives token by token over SSE, and
 * both turns are persisted server-side, so the caller re-fetches the thread
 * when the stream ends rather than trying to reconcile a streamed string with
 * a cached list.
 */
export async function streamThreadReply(
  threadId: string,
  content: string,
  onToken: (token: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`/api/threads/${threadId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, action: 'ask' }),
    signal,
  });

  if (!res.ok || !res.body) {
    const detail = await res.text().catch(() => '');
    throw new Error(detail || `Request failed (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line. Splitting on '\n' alone
    // would cut a multi-line frame in half.
    const frames = buffer.split('\n\n');
    buffer = frames.pop() ?? '';
    for (const frame of frames) {
      const line = frame.split('\n').find((l) => l.startsWith('data: '));
      if (!line) continue;
      const payload = line.slice(6);
      if (payload === '[DONE]') return;
      try {
        const parsed = JSON.parse(payload) as { token?: string };
        if (parsed.token) onToken(parsed.token);
      } catch {
        /* a partial frame; the next read completes it */
      }
    }
  }
}

// ── Reading sessions ───────────────────────────────────────────────────────

export function useSessionStats(days = 30) {
  return useQuery<ReadingSessionStats>({
    queryKey: ['session-stats', days],
    queryFn: () => get(`/api/sessions/stats?days=${days}`),
    staleTime: 60_000,
  });
}

/**
 * Tell the server this book is being read right now.
 *
 * Fire-and-forget: a dropped heartbeat costs at most one interval of recorded
 * time, and there is nothing useful to show the reader when one fails.
 */
export function sendHeartbeat(bookId: string, page?: number | null): void {
  void fetch('/api/sessions/heartbeat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ book_id: bookId, page: page ?? null }),
    keepalive: true,
  }).catch(() => {});
}
