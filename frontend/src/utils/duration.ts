/**
 * "3h 42m", or "42m", or "—". Hours matter, seconds never do.
 *
 * Its own module for the same reason as `passageLocation`: a non-component
 * export beside a component disables Fast Refresh for that file.
 */
export function formatDuration(seconds: number): string {
  if (!seconds) return '—';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  if (hours && minutes) return `${hours}h ${minutes}m`;
  if (hours) return `${hours}h`;
  return `${minutes}m`;
}
