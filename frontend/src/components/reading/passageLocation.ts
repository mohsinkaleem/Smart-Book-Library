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

/**
 * Why the number on a passage card is not the thing that ordered the page.
 *
 * The badge shows the cosine, which is comparable between queries and is the
 * only figure that means anything to a reader. The ordering comes from the
 * fusion of the semantic and keyword ranks, so a card can sit above another
 * with a slightly higher percentage — which reads as a bug unless the card
 * says otherwise.
 */
export const SIMILARITY_HINT =
  'Similarity to your selection. Results are ordered by a fusion of semantic and '
  + 'keyword rank, so a slightly lower percentage can still rank higher.';
