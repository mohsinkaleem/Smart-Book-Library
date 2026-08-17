import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

/**
 * `README.md` listed `common/ErrorBoundary` in the component tree. It did not
 * exist — a render error anywhere took the whole page to a blank screen.
 */
interface Props {
  children: ReactNode;
  /** Shown instead of the default panel. */
  fallback?: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Render error:', error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    if (this.props.fallback) return this.props.fallback;

    return (
      <ErrorState
        title="Something went wrong"
        message={this.state.error.message}
        onRetry={() => this.setState({ error: null })}
      />
    );
  }
}

interface ErrorStateProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
}

/** The shared "this failed" panel, used for query errors too. */
export function ErrorState({ title = 'Something went wrong', message, onRetry }: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      <div className="rounded-full bg-red-50 p-3 text-red-500 dark:bg-red-900/20">
        <AlertTriangle size={24} />
      </div>
      <h2 className="text-base font-bold text-slate-800 dark:text-slate-200">{title}</h2>
      {message && (
        <p className="max-w-md text-sm text-slate-500 dark:text-slate-400">{message}</p>
      )}
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-1 inline-flex items-center gap-1.5 rounded-lg bg-primary-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-primary-700"
        >
          <RefreshCw size={14} /> Try again
        </button>
      )}
    </div>
  );
}
