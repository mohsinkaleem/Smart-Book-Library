import clsx from 'clsx';

const colors: Record<string, string> = {
  'Computer Science & Programming': 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  'Data Science & Machine Learning': 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
  'History & Civilization': 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200',
  'Islamic Studies': 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200',
  'Religion & Spirituality': 'bg-teal-100 text-teal-800 dark:bg-teal-900 dark:text-teal-200',
  'Business & Economics': 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200',
  'Philosophy & Ethics': 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-200',
  'Science & Nature': 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  'Literature & Fiction': 'bg-rose-100 text-rose-800 dark:bg-rose-900 dark:text-rose-200',
  'Self-Help & Personal Development': 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
};

export function Badge({ label, className }: { label: string; className?: string }) {
  const color = colors[label] || 'bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-300';
  return (
    <span className={clsx('inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium', color, className)}>
      {label}
    </span>
  );
}
