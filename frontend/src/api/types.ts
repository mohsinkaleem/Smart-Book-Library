/** TypeScript types mirroring BookRecord. */
export interface Book {
  id: string;
  file_path: string;
  file_name: string;
  file_type: 'pdf' | 'epub' | 'mobi';
  size: number;
  title: string;
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
}

export interface Suggestion {
  id: string;
  title: string;
  author: string;
}
