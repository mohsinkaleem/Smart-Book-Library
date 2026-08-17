import { useState } from 'react';
import { AlertCircle, Cpu, FileStack, Play } from 'lucide-react';
import { useUnprocessed, usePipelineStatus } from '../api/books';
import { post } from '../api/client';
import { Spinner } from '../components/common/Spinner';

interface TaskState {
  status?: string;
  message?: string;
  progress?: number;
  total?: number;
  error?: string;
}

export function SettingsPage() {
  const { data: pipelineStatus } = usePipelineStatus();
  const { data: unprocessed, refetch: refetchUnprocessed } = useUnprocessed();
  const [message, setMessage] = useState('');

  const task = (pipelineStatus ?? {}) as TaskState;
  const isRunning = task.status === 'running';

  const runPipeline = async () => {
    try {
      await post('/api/pipeline/run', { max_books: 0 });
      setMessage('Pipeline started...');
    } catch {
      setMessage('Failed to start pipeline');
    }
  };

  const runEmbeddings = async () => {
    try {
      await post('/api/pipeline/generate-embeddings', {});
      setMessage('Embedding generation started...');
    } catch {
      setMessage('Failed to start embedding generation');
    }
  };

  const pending = unprocessed?.unprocessed ?? 0;

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Settings</h1>

      {/* Pipeline */}
      <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200/60 dark:bg-slate-800 dark:ring-slate-700">
        <h2 className="mb-4 text-lg font-bold text-slate-900 dark:text-white">Pipeline</h2>

        {/* How much there is to do.
            `GET /api/pipeline/unprocessed` reported this correctly and no page
            displayed it, so "Process New Books" gave no hint whether there was
            anything to process. */}
        {unprocessed && !unprocessed.error && (
          <div
            className={`mb-4 flex items-start gap-3 rounded-lg p-4 text-sm ${
              pending > 0
                ? 'bg-amber-50 text-amber-800 dark:bg-amber-900/20 dark:text-amber-200'
                : 'bg-slate-50 text-slate-600 dark:bg-slate-700/40 dark:text-slate-300'
            }`}
          >
            <FileStack size={16} className="mt-0.5 shrink-0" />
            <div>
              {pending > 0 ? (
                <p>
                  <strong className="tabular-nums">{pending}</strong> of{' '}
                  <span className="tabular-nums">{unprocessed.total_files}</span> files on disk are
                  not in the catalog yet.
                </p>
              ) : (
                <p>
                  All <span className="tabular-nums">{unprocessed.total_files}</span> files on disk
                  are catalogued.
                </p>
              )}
            </div>
          </div>
        )}

        {/* Live progress. `task_tracker` has reported `progress`/`total`/`message`
            per book all along; the page showed a spinner and a string. */}
        {isRunning && (
          <div className="mb-4 rounded-lg bg-blue-50 p-4 text-sm text-blue-700 dark:bg-blue-900/20 dark:text-blue-300">
            <div className="flex items-center gap-3">
              <Spinner size={16} />
              <span className="flex-1 truncate">{task.message || 'Running...'}</span>
              {!!task.total && (
                <span className="shrink-0 tabular-nums font-medium">
                  {task.progress ?? 0} / {task.total}
                </span>
              )}
            </div>
            {!!task.total && (
              <div
                className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-blue-200/60 dark:bg-blue-900/50"
                role="progressbar"
                aria-valuenow={task.progress ?? 0}
                aria-valuemin={0}
                aria-valuemax={task.total}
                aria-label="Pipeline progress"
              >
                <div
                  className="h-full rounded-full bg-blue-500 transition-[width] duration-500"
                  style={{ width: `${Math.min(100, ((task.progress ?? 0) / task.total) * 100)}%` }}
                />
              </div>
            )}
          </div>
        )}

        {task.status === 'failed' && (
          <div className="mb-4 flex items-start gap-3 rounded-lg bg-red-50 p-4 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-300">
            <AlertCircle size={16} className="mt-0.5 shrink-0" />
            <span className="min-w-0 break-words">{task.error || 'The pipeline run failed.'}</span>
          </div>
        )}

        {task.status === 'completed' && !isRunning && task.message && (
          <p className="mb-4 rounded-lg bg-emerald-50 p-4 text-sm text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300">
            {task.message}
          </p>
        )}

        <div className="flex flex-wrap gap-3">
          <button
            onClick={runPipeline}
            disabled={isRunning}
            className="flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
          >
            <Play size={16} />
            Process New Books
            {pending > 0 && (
              <span className="rounded-full bg-white/20 px-1.5 py-0.5 text-xs tabular-nums">
                {pending}
              </span>
            )}
          </button>
          <button
            onClick={runEmbeddings}
            disabled={isRunning}
            className="flex items-center gap-2 rounded-lg bg-slate-100 px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-200 disabled:opacity-50 dark:bg-slate-700 dark:text-slate-300"
          >
            <Cpu size={16} /> Generate Embeddings
          </button>
          <button
            onClick={() => refetchUnprocessed()}
            className="rounded-lg px-3 py-2.5 text-sm font-medium text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700"
          >
            Rescan
          </button>
        </div>

        {message && <p className="mt-3 text-sm text-slate-500">{message}</p>}
      </div>

      {/* Info */}
      <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200/60 dark:bg-slate-800 dark:ring-slate-700">
        <h2 className="mb-4 text-lg font-bold text-slate-900 dark:text-white">About</h2>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          Smart Book Library — a local-first web application for browsing, exploring, and searching
          your personal book collection.
        </p>
        <p className="mt-2 text-xs text-slate-400">
          Built with FastAPI + React + SQLite. Supports PDF and EPUB files with embeddings-based
          semantic search. See <code className="font-mono">/api/health</code> for the running
          version.
        </p>
      </div>
    </div>
  );
}
