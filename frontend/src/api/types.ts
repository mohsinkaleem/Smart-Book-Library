/** TypeScript types mirroring BookRecord. */
export interface Book {
  id: string;
  file_path: string;
  file_name: string;
  file_type: 'pdf' | 'epub' | 'mobi';
  size: number;
  title: string;
  // Served by the API all along (it is in `LIST_COLUMNS`) and missing from
  // this type, so nothing could render it.
  subtitle: string;
  original_title_meta: string;
  authors: string[];
  publisher: string;
  publication_year: number | null;
  language: string;
  page_count: number | null;
  isbn_10: string;
  isbn_13: string;
  description: string;
  summary: string;
  themes: string[];
  categories: string[];
  keywords: string[];
  cover_path: string;
  cover_url: string | null;
  text_excerpt: string;
  has_text: boolean;
  ocr_required: boolean;
  api_sources: string[];
  date_added: string;
  last_opened: string | null;
  reading_status: 'not_started' | 'in_progress' | 'finished' | 'abandoned';
  progress_percent: number;
  /** EPUB CFI or PDF page number; written and read only by the readers. */
  reader_position: string;
  user_rating: number | null;
  user_tags: string[];
  favorite: boolean;
  duplicate_of: string | null;
  processing_errors: string[];
  last_processed: string;
  author_primary: string;
  has_cover: boolean;
  has_description: boolean;
  has_embeddings?: boolean;
  similarity_score?: number;
  _score?: number;
  match_type?: 'fts' | 'semantic' | 'hybrid';
  /**
   * Why this book matched, from `/api/search`. Matched terms are wrapped in
   * ``…``; see `SnippetText`.
   */
  snippet?: string;
  /** Which index produced the snippet. */
  match_field?: 'text' | 'metadata';
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface FilterFacets {
  categories: FacetItem[];
  themes: FacetItem[];
  authors: FacetItem[];
  languages: FacetItem[];
  file_types: FacetItem[];
  years: { min: number | null; max: number | null };
  reading_statuses: FacetItem[];
  tags: FacetItem[];
  total_matching?: number;
}

export interface FacetItem {
  name: string;
  count: number;
}

export interface StatsData {
  total_books: number;
  total_size_bytes: number;
  by_type: Record<string, number>;
  by_status: Record<string, number>;
  with_cover: number;
  with_description: number;
  with_embeddings: number;
  duplicates: number;
  avg_rating: number | null;
  categories: FacetItem[];
  themes: FacetItem[];
  year_histogram: { year: number; count: number }[];
  recently_processed: { id: string; title: string; author: string; cover_url: string | null }[];
}

export interface CompareMatch {
  book_id: string;
  title: string;
  author: string;
  excerpt: string;
  similarity: number;
  cover_url: string | null;
  /**
   * True when `excerpt` is the passage that actually matched, from the chunk
   * index. False when it is the book's opening prose, which is all the
   * book-level fallback can offer for a book the index has not reached.
   * The card says which, rather than presenting both as the same thing.
   */
  is_passage?: boolean;
  chunk_id?: number;
  page_start?: number | null;
  page_end?: number | null;
  spine_index?: number | null;
  section?: string;
  /** Reader URL for the passage; absent on a book-level fallback match. */
  deep_link?: string;
}

/** One retrieved passage from the chunk index (Part 1). */
export interface Passage {
  chunk_id: number;
  book_id: string;
  chunk_idx: number;
  text: string;
  /** Cosine against the query — comparable between queries. */
  score: number;
  /** Reciprocal Rank Fusion value; decides ordering and nothing else. */
  rrf: number;
  page_start: number | null;
  page_end: number | null;
  spine_index: number | null;
  anchor_text: string;
  section: string;
  /** Which retrieval system proposed it. */
  matched: 'both' | 'semantic' | 'keyword';
  title: string;
  author: string;
  year: number | null;
  cover_url: string | null;
  file_type: string;
  deep_link: string;
}

export interface PassageIndexStatus {
  available: boolean;
  built?: boolean;
  count?: number;
  book_count?: number;
  model_id?: string;
  built_at?: string;
  chunk_chars?: number;
  chunk_overlap?: number;
}

export interface ConceptThread {
  strength: number;
  section: string;
  passages: (Passage & { is_match?: boolean })[];
}

export interface StanceGroups {
  supports: (Passage & { why: string })[];
  complicates: (Passage & { why: string })[];
  contradicts: (Passage & { why: string })[];
  unsorted: (Passage & { why: string })[];
}

/** A passage-scoped LLM conversation (§4.2). */
export interface LLMThread {
  id: string;
  book_id: string;
  title: string;
  passage: string;
  surrounding: string;
  context: string;
  page: number | null;
  cfi: string;
  created_at: string;
  updated_at: string;
  message_count?: number;
  messages?: LLMMessage[];
}

export interface LLMMessage {
  id: string;
  thread_id: string;
  role: 'user' | 'assistant';
  content: string;
  action: string;
  created_at: string;
}

export interface ReadingSessionStats {
  total_seconds: number;
  total_pages: number;
  sessions: number;
  window_days: number;
  window_seconds: number;
  window_pages: number;
  window_books: number;
  pages_per_week: number;
  current_streak: number;
  longest_streak: number;
  daily: { date: string; seconds: number; pages: number; books: number }[];
}

export interface DuplicateGroup {
  canonical_id: string;
  canonical: Book | null;
  orphaned: boolean;
  copies: Book[];
}

export interface Suggestion {
  id: string;
  title: string;
  author: string;
}

export type AnnotationKind = 'highlight' | 'bookmark' | 'note';

export interface Annotation {
  id: string;
  book_id: string;
  file_path: string | null;
  kind: AnnotationKind;
  /** The selected passage. */
  text: string;
  /** The reader's own commentary on it. */
  note: string;
  color: string;
  /** PDF anchor. Null for EPUBs. */
  page: number | null;
  /** EPUB anchor. Empty for PDFs. */
  cfi: string;
  /** Short needle used to relocate the highlight when the anchor drifts. */
  anchor_text: string;
  created_at: string;
  updated_at: string;
}
