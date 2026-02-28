import { X } from 'lucide-react';

interface FilterChipProps {
  label: string;
  value: string;
  onRemove: () => void;
}

export function FilterChip({ label, value, onRemove }: FilterChipProps) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-primary-100 px-3 py-1 text-xs font-medium text-primary-800 dark:bg-primary-900 dark:text-primary-200">
      <span className="text-primary-500">{label}:</span> {value}
      <button onClick={onRemove} className="ml-0.5 hover:text-primary-600">
        <X size={12} />
      </button>
    </span>
  );
}
