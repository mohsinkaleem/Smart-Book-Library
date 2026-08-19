import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowLeft, MessageSquarePlus, Send, Trash2, MessagesSquare,
} from 'lucide-react';
import {
  streamThreadReply,
  useCreateThread,
  useDeleteThread,
  useThread,
  useThreads,
} from '../../api/threads';
import { useLlmStatus } from '../../api/books';
import { Spinner } from '../common/Spinner';
import { MIN_SELECTION_CHARS } from './selection';

interface ThreadPanelProps {
  bookId: string;
  selectedText: string;
  surroundingText: string;
  page?: number | null;
  cfi?: string;
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const minutes = Math.round((Date.now() - then) / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/**
 * Passage-scoped conversations (§4.2).
 *
 * The two gaps the roadmap lists separately — "no follow-up" and "nothing is
 * saved" — are one feature, because what makes a follow-up answerable is the
 * same thing that makes it worth keeping: a frame that outlives the request.
 * The passage and the retrieved context are pinned server-side at creation and
 * replayed into every turn, so "why?" refers to something the model can still
 * see.
 */
export function ThreadPanel({
  bookId, selectedText, surroundingText, page, cfi,
}: ThreadPanelProps) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [streaming, setStreaming] = useState('');
  const [error, setError] = useState('');
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  const { data: llm } = useLlmStatus();
  const { data: list, isLoading } = useThreads(bookId);
  const { data: thread, refetch } = useThread(openId);
  const { mutate: create, isPending: creating } = useCreateThread(bookId);
  const { mutate: remove } = useDeleteThread(bookId);

  const busy = streaming !== '' || creating;

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' });
  }, [thread?.messages?.length, streaming]);

  // A stream left running after the panel closes writes into a dead component
  // and, worse, keeps Ollama generating for a reader who has moved on.
  useEffect(() => () => abortRef.current?.abort(), []);

  const send = useCallback(
    async (threadId: string, content: string) => {
      setError('');
      setStreaming(' ');
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      let collected = '';
      try {
        await streamThreadReply(
          threadId,
          content,
          (token) => {
            collected += token;
            setStreaming(collected);
          },
          controller.signal,
        );
      } catch (err) {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : 'The model did not answer');
        }
      } finally {
        setStreaming('');
        // Both turns are stored server-side, so the transcript comes back from
        // the server rather than being stitched together from the stream.
        if (!controller.signal.aborted) void refetch();
      }
    },
    [refetch],
  );

  const startThread = useCallback(() => {
    if (selectedText.length < MIN_SELECTION_CHARS) return;
    create(
      {
        book_id: bookId,
        passage: selectedText,
        surrounding: surroundingText,
        page: page ?? null,
        cfi: cfi ?? '',
        retrieve: true,
      },
      { onSuccess: (created) => setOpenId(created.id) },
    );
  }, [bookId, selectedText, surroundingText, page, cfi, create]);

  if (llm && !llm.available) {
    return (
      <div className="rounded-lg bg-slate-100 p-3 text-xs text-slate-500 dark:bg-slate-700/50 dark:text-slate-400">
        <p className="mb-1 font-medium text-slate-600 dark:text-slate-300">
          Conversations need a local model
        </p>
        <p>{llm.reason || 'Ollama is not reachable.'}</p>
      </div>
    );
  }

  // ── One open thread ──────────────────────────────────────────────────────
  if (openId && thread) {
    return (
      <div className="flex h-full flex-col">
        <div className="mb-2 flex items-center gap-2">
          <button
            onClick={() => setOpenId(null)}
            className="flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-700"
          >
            <ArrowLeft size={12} /> All threads
          </button>
          <button
            onClick={() => {
              remove(thread.id);
              setOpenId(null);
            }}
            aria-label="Delete thread"
            className="ml-auto rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-900/30"
          >
            <Trash2 size={13} />
          </button>
        </div>

        <div className="mb-3 rounded-lg bg-yellow-50 p-2.5 text-xs text-yellow-900 dark:bg-yellow-900/20 dark:text-yellow-200">
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-yellow-700 dark:text-yellow-400">
            Pinned passage{thread.page ? ` · p. ${thread.page}` : ''}
          </p>
          <p className="line-clamp-3 italic">{thread.passage}</p>
          {thread.context && (
            <p className="mt-1.5 text-[10px] text-yellow-700/80 dark:text-yellow-400/80">
              Grounded in retrieved passages from your library.
            </p>
          )}
        </div>

        <div className="min-h-0 flex-1 space-y-2 overflow-y-auto">
          {(thread.messages ?? []).map((message) => (
            <div
              key={message.id}
              className={`rounded-lg p-2.5 text-xs leading-relaxed ${
                message.role === 'user'
                  ? 'ml-4 bg-primary-50 text-primary-900 dark:bg-primary-900/30 dark:text-primary-100'
                  : 'mr-2 bg-white text-slate-700 shadow-sm ring-1 ring-slate-100 dark:bg-slate-700 dark:text-slate-200 dark:ring-slate-600'
              }`}
            >
              <p className="whitespace-pre-wrap">{message.content}</p>
            </div>
          ))}

          {streaming && (
            <div className="mr-2 rounded-lg bg-white p-2.5 text-xs leading-relaxed text-slate-700 shadow-sm ring-1 ring-slate-100 dark:bg-slate-700 dark:text-slate-200 dark:ring-slate-600">
              {streaming.trim() ? (
                <p className="whitespace-pre-wrap">{streaming}</p>
              ) : (
                <Spinner size={14} />
              )}
            </div>
          )}

          {error && (
            <p className="rounded-lg bg-red-50 p-2 text-xs text-red-600 dark:bg-red-900/20 dark:text-red-400">
              {error}
            </p>
          )}
          <div ref={endRef} />
        </div>

        <form
          className="mt-2 flex gap-1.5"
          onSubmit={(e) => {
            e.preventDefault();
            const content = draft.trim();
            if (!content || busy) return;
            setDraft('');
            void send(thread.id, content);
          }}
        >
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Ask a follow-up…"
            disabled={busy}
            className="flex-1 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-700 placeholder:text-slate-400 focus:border-primary-400 focus:outline-none disabled:opacity-60 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-200"
          />
          <button
            type="submit"
            disabled={busy || !draft.trim()}
            aria-label="Send"
            className="rounded-md bg-primary-600 px-2.5 text-white hover:bg-primary-700 disabled:opacity-40"
          >
            <Send size={13} />
          </button>
        </form>
      </div>
    );
  }

  // ── The list ─────────────────────────────────────────────────────────────
  const threads = list?.threads ?? [];

  return (
    <div className="space-y-3">
      <button
        onClick={startThread}
        disabled={selectedText.length < MIN_SELECTION_CHARS || creating}
        className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-primary-600 px-3 py-2 text-xs font-medium text-white hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-40"
      >
        <MessageSquarePlus size={13} />
        {creating ? 'Starting…' : 'New thread on selection'}
      </button>

      {selectedText.length < MIN_SELECTION_CHARS && (
        <p className="text-center text-[11px] text-slate-400">
          Select a passage in the book to start a thread about it.
        </p>
      )}

      {isLoading ? (
        <div className="flex justify-center py-4">
          <Spinner size={18} />
        </div>
      ) : threads.length === 0 ? (
        <div className="rounded-lg bg-slate-100 p-4 text-center text-xs text-slate-500 dark:bg-slate-700/50 dark:text-slate-400">
          <MessagesSquare size={22} className="mx-auto mb-2 opacity-50" />
          <p className="font-medium">No threads in this book yet</p>
          <p className="mt-1">
            A thread keeps the passage and its retrieved context pinned, so
            follow-up questions carry their own context.
          </p>
        </div>
      ) : (
        <div className="space-y-1.5">
          {threads.map((item) => (
            <button
              key={item.id}
              onClick={() => setOpenId(item.id)}
              className="block w-full rounded-lg bg-white p-2.5 text-left shadow-sm ring-1 ring-slate-100 transition-shadow hover:shadow dark:bg-slate-700 dark:ring-slate-600"
            >
              <p className="truncate text-xs font-medium text-slate-700 dark:text-slate-200">
                {item.title || 'Untitled thread'}
              </p>
              <p className="mt-0.5 flex items-center gap-1.5 text-[10px] text-slate-400">
                {item.page ? <span>p. {item.page}</span> : null}
                <span>
                  {item.message_count ?? 0} message
                  {(item.message_count ?? 0) === 1 ? '' : 's'}
                </span>
                <span>· {relativeTime(item.updated_at)}</span>
              </p>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
