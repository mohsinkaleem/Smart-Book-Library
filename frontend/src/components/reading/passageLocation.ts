import type { Passage } from '../../api/types';

/**
 * Where a passage sits, in whichever way its format can say it.
 *
 * Its own module rather than an export beside a component: mixing the two
 * breaks React Fast Refresh for the whole file, and this is imported from both
 * the reader panel and the passage-search page.
 */
export function passageLocation(passage: Passage): string {
  if (passage.page_start) {
    return passage.page_end && passage.page_end !== passage.page_start
      ? `pp. ${passage.page_start}–${passage.page_end}`
      : `p. ${passage.page_start}`;
  }
  if (passage.spine_index !== null && passage.spine_index !== undefined) {
    return `Section ${passage.spine_index + 1}`;
  }
  return '';
}
