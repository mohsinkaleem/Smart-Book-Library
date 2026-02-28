import { useState } from 'react';
import { usePipelineStatus } from '../api/books';
import { post } from '../api/client';
import { Spinner } from '../components/common/Spinner';
import { Play, Cpu } from 'lucide-react';

export function SettingsPage() {
  const { data: pipelineStatus } = usePipelineStatus();
  const [message, setMessage] = useState('');
  const isRunning = pipelineStatus?.status === 'running';

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

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Settings</h1>

      {/* Pipeline */}
      <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200/60 dark:bg-slate-800 dark:ring-slate-700">
        <h2 className="mb-4 text-lg font-bold text-slate-900 dark:text-white">Pipeline</h2>

        {isRunning && (
          <div className="mb-4 flex items-center gap-3 rounded-lg bg-blue-50 p-4 text-sm text-blue-700 dark:bg-blue-900/20 dark:text-blue-300">
            <Spinner size={16} />
            <span>{(pipelineStatus as Record<string, unknown>)?.message as string || 'Running...'}</span>
          </div>
        )}

        <div className="flex flex-wrap gap-3">
          <button
            onClick={runPipeline}
            disabled={isRunning}
            className="flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
          >
            <Play size={16} /> Process New Books
          </button>
          <button
            onClick={runEmbeddings}
            disabled={isRunning}
            className="flex items-center gap-2 rounded-lg bg-slate-100 px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-200 disabled:opacity-50 dark:bg-slate-700 dark:text-slate-300"
          >
            <Cpu size={16} /> Generate Embeddings
          </button>
        </div>

        {message && <p className="mt-3 text-sm text-slate-500">{message}</p>}
      </div>

      {/* Info */}
      <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200/60 dark:bg-slate-800 dark:ring-slate-700">
        <h2 className="mb-4 text-lg font-bold text-slate-900 dark:text-white">About</h2>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          Smart Book Library v1.0 — A local-first web application for browsing, exploring, and searching your personal book collection.
        </p>
        <p className="mt-2 text-xs text-slate-400">
          Built with FastAPI + React + SQLite. Supports PDF and EPUB files with embeddings-based semantic search.
        </p>
      </div>
    </div>
  );
}
