import { useState, useCallback } from 'react';
import { MessageSquare, Lightbulb, FileText, GitCompare, AlertTriangle, Link2, PlugZap } from 'lucide-react';
import { useLlmStatus } from '../../api/books';
import { Spinner } from '../common/Spinner';

interface LLMPanelProps {
  selectedText: string;
  bookId: string;
  /** Kept for callers; the server looks the title up from `bookId`. */
  bookTitle?: string;
  /**
   * Prose around the selection. The model used to see the passage and
   * nothing else, which loses the argument the passage belongs to.
   */
  surrounding?: string;
}

const actions = [
  { id: 'explain', label: 'Explain', icon: Lightbulb },
  { id: 'summarize', label: 'Summarize', icon: FileText },
  { id: 'compare', label: 'Compare', icon: GitCompare },
  { id: 'critique', label: 'Critique', icon: AlertTriangle },
  { id: 'related', label: 'Related', icon: Link2 },
];

export function LLMPanel({ selectedText, bookId, surrounding }: LLMPanelProps) {
  const [response, setResponse] = useState('');
  const [loading, setLoading] = useState(false);
  // `GET /api/reading/llm-status` existed and nothing called it: the buttons
  // were offered unconditionally and only failed on click, with an error
  // string where the answer should have been.
  const { data: llm, isLoading: llmLoading } = useLlmStatus();
  const ready = !!llm?.available && llm.model_installed !== false;

  const runAction = useCallback(async (action: string) => {
    if (!selectedText) return;
    setResponse('');
    setLoading(true);

    try {
      const res = await fetch('/api/reading/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: selectedText, book_id: bookId, action, surrounding }),
      });

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          // Parse SSE events
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const data = line.slice(6);
              if (data === '[DONE]') break;
              try {
                const parsed = JSON.parse(data);
                if (parsed.token) {
                  setResponse((prev) => prev + parsed.token);
                }
              } catch { /* skip */ }
            }
          }
        }
      }
    } catch {
      setResponse('Error: LLM is not available. Make sure Ollama is running.');
    } finally {
      setLoading(false);
    }
  }, [selectedText, bookId, surrounding]);

  return (
    <div>
      <h4 className="mb-2 flex items-center gap-1 text-xs font-semibold text-slate-500">
        <MessageSquare size={12} /> LLM Analysis
        {llm?.model && ready && (
          <span className="ml-auto font-mono text-[10px] font-normal text-slate-400">
            {llm.model}
          </span>
        )}
      </h4>

      {!llmLoading && !ready && (
        <div className="mb-3 flex items-start gap-2 rounded-lg bg-slate-100 p-3 text-xs text-slate-500 dark:bg-slate-700/50 dark:text-slate-400">
          <PlugZap size={14} className="mt-px shrink-0" />
          <div>
            <p className="font-medium text-slate-600 dark:text-slate-300">Analysis is unavailable</p>
            {llm?.model_installed === false ? (
              <p className="mt-0.5">
                Ollama is running but <code className="font-mono">{llm.model}</code> is not pulled —
                run <code className="font-mono">ollama pull {llm.model}</code>.
              </p>
            ) : (
              <p className="mt-0.5">
                No LLM answered at{' '}
                <code className="font-mono">{llm?.base_url || 'localhost:11434'}</code>. Start
                Ollama to enable this.
              </p>
            )}
          </div>
        </div>
      )}

      <div className="mb-3 flex flex-wrap gap-1.5">
        {actions.map((a) => (
          <button
            key={a.id}
            onClick={() => runAction(a.id)}
            disabled={!selectedText || loading || !ready}
            title={!ready ? 'No LLM available' : undefined}
            className="flex items-center gap-1 rounded-md bg-white px-2.5 py-1.5 text-xs font-medium text-slate-600 shadow-sm ring-1 ring-slate-200 transition-colors hover:bg-primary-50 hover:text-primary-700 disabled:opacity-50 dark:bg-slate-700 dark:text-slate-300 dark:ring-slate-600 dark:hover:bg-primary-900/30"
          >
            <a.icon size={12} />
            {a.label}
          </button>
        ))}
      </div>

      {/* Response */}
      {(loading || response) && (
        <div className="rounded-lg bg-white p-3 text-sm shadow-sm dark:bg-slate-700">
          {loading && !response && (
            <div className="flex items-center gap-2 text-slate-500">
              <Spinner size={16} /> Analyzing...
            </div>
          )}
          <div className="whitespace-pre-wrap text-slate-700 dark:text-slate-300">{response}</div>
          {loading && response && <span className="inline-block h-3 w-1 animate-pulse bg-primary-500" />}
        </div>
      )}
    </div>
  );
}
