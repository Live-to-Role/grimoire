export interface ProcessingStatus {
  cover_extracted: boolean;
  text_extracted: boolean;
  deep_indexed: boolean;
  ai_identified: boolean;
}

export interface RunStatus {
  status: 'want_to_run' | 'running' | 'completed' | null;
  rating: number | null;
  difficulty: 'easier' | 'as_written' | 'harder' | null;
  completed_at: string | null;
}

export interface RunNote {
  id: number;
  product_id: number;
  campaign_id: number | null;
  note_type: 'prep_tip' | 'modification' | 'warning' | 'review';
  title: string;
  content: string;
  spoiler_level: 'none' | 'minor' | 'major' | 'endgame';
  shared_to_codex: boolean;
  codex_note_id: string | null;
  visibility: 'private' | 'anonymous' | 'public';
  created_at: string;
  updated_at: string;
}

export interface Tag {
  id: number;
  name: string;
  category: string | null;
  color: string | null;
  created_at: string;
  product_count: number;
}

export interface Product {
  id: number;
  file_path: string;
  file_name: string;
  file_size: number;
  title: string | null;
  publisher: string | null;
  publication_year: number | null;
  game_system: string | null;
  product_type: string | null;
  level_range_min: number | null;
  level_range_max: number | null;
  party_size_min: number | null;
  party_size_max: number | null;
  estimated_runtime: string | null;
  page_count: number | null;
  cover_url: string | null;
  tags: Tag[];
  processing_status: ProcessingStatus;
  run_status: RunStatus | null;
  created_at: string;
  updated_at: string;
  last_opened_at: string | null;
}

export interface ProductListResponse {
  items: Product[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}
