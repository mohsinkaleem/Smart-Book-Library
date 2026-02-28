import { useState, useCallback } from 'react';
import { MessageSquare, Lightbulb, FileText, GitCompare, AlertTriangle, Link2 } from 'lucide-react';
import { Spinner } from '../common/Spinner';

interface LLMPanelProps {
  selectedText: string;
  bookId: string;
  bookTitle: string;
}

const actions = [
  { id: 'explain', label: 'Explain', icon: Lightbulb },
  { id: 'summarize', label: 'Summarize', icon: FileText },
  { id: 'compare', label: 'Compare', icon: GitCompare },
  { id: 'critique', label: 'Critique', icon: AlertTriangle },
  { id: 'related', label: 'Related', icon: Link2 },
];

export function LLMPanel({ selectedText, bookId, bookTitle: _bookTitle }: LLMPanelProps) {
  const [response, setResponse] = useState('');
  const [loading, setLoading] = useState(false);
  const [, setActiveAction] = useState<string | null>(null);

  const runAction = useCallback(async (action: string) => {
    if (!selectedText) return;
    setActiveAction(action);
    setResponse('');
    setLoading(true);

    try {
      const res = await fetch('/api/reading/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: selectedText, book_id: bookId, action }),
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
    } catch (err) {
      setResponse('Error: LLM is not available. Make sure Ollama is running.');
    } finally {
      setLoading(false);
    }
  }, [selectedText, bookId]);

  return (
    <div>
      <h4 className="mb-2 flex items-center gap-1 text-xs font-semibold text-slate-500">
        <MessageSquare size={12} /> LLM Analysis
      </h4>

      <div className="mb-3 flex flex-wrap gap-1.5">
        {actions.map((a) => (
          <button
            key={a.id}
            onClick={() => runAction(a.id)}
            disabled={!selectedText || loading}
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
