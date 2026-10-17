import clsx from 'clsx';

/**
 * Category pill.
 *
 * The keys here are `catalog.taxonomy.CANONICAL_CATEGORIES` verbatim. They
 * used to be an older, shorter vocabulary — 'Islamic Studies', 'Computer
 * Science & Programming', 'History & Civilization' — and the pipeline had
 * since been constrained to a different seventeen. Only two names overlapped,
 * so fifteen of the seventeen categories fell through to the grey default and
 * the colour coding carried no information at all.
 *
 * Related fields sit on neighbouring hues (the two computing categories are
 * blue/violet, the two faith ones emerald/teal) so a grid reads as groups
 * rather than confetti. Theme variables are deliberately not used: `paper`
 * and `dim` retint `slate` and `primary` only, and these pills are meant to
 * stay identifiable across all four themes.
 */
const colors: Record<string, string> = {
  'Computer Science': 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  'Data Science & ML': 'bg-violet-100 text-violet-800 dark:bg-violet-900 dark:text-violet-200',
  'Mathematics & Physics': 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-200',
  'Security & Hacking': 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
  'Islam & Islamic Studies': 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200',
  'Religion & Philosophy': 'bg-teal-100 text-teal-800 dark:bg-teal-900 dark:text-teal-200',
  'History': 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200',
  'Politics & Geopolitics': 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200',
  'Economics & Finance': 'bg-lime-100 text-lime-800 dark:bg-lime-900 dark:text-lime-200',
  'Psychology & Self-Help': 'bg-fuchsia-100 text-fuchsia-800 dark:bg-fuchsia-900 dark:text-fuchsia-200',
  'Literature & Fiction': 'bg-rose-100 text-rose-800 dark:bg-rose-900 dark:text-rose-200',
  'Gender & Society': 'bg-pink-100 text-pink-800 dark:bg-pink-900 dark:text-pink-200',
  'Science & Nature': 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  'Health & Wellness': 'bg-cyan-100 text-cyan-800 dark:bg-cyan-900 dark:text-cyan-200',
  'Language & Communication': 'bg-sky-100 text-sky-800 dark:bg-sky-900 dark:text-sky-200',
  'Biography & Memoir': 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
  'Education & Reference': 'bg-stone-200 text-stone-700 dark:bg-stone-700 dark:text-stone-200',
};

export function Badge({ label, className }: { label: string; className?: string }) {
  const color = colors[label] || 'bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-300';
  return (
    <span
      // `max-w-full truncate` rather than letting it wrap: 'Islam & Islamic
      // Studies' in a grid cell wrapped to three lines, which made every card
      // in the row a different height and squeezed the footer.
      title={label}
      className={clsx(
        'inline-flex max-w-full items-center truncate whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium',
        color,
        className,
      )}
    >
      {label}
    </span>
  );
}
