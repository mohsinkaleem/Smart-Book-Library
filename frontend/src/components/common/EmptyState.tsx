import { BookOpen } from 'lucide-react';

export function EmptyState({ message = 'No books found', actionLabel, onAction }: {
  message?: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-slate-400">
      <BookOpen size={48} className="mb-4" />
      <p className="text-lg font-medium">{message}</p>
      {actionLabel && onAction && (
        <button onClick={onAction} className="mt-4 rounded-lg bg-primary-600 px-4 py-2 text-sm text-white hover:bg-primary-700">
          {actionLabel}
        </button>
      )}
    </div>
  );
}
