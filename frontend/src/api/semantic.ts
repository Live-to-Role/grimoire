import apiClient from './client';
import type { ProductFilters } from './products';

export interface SemanticSearchStatus {
  enabled: boolean;
  provider: string;
  has_embeddings: boolean;
  embedded_count: number;
}

export interface SemanticSearchResponse {
  query: string;
  results: any[];
  total_matches: number;
}

export async function getSemanticSearchStatus(): Promise<SemanticSearchStatus> {
  const response = await apiClient.get<SemanticSearchStatus>('/semantic/search-status');
  return response.data;
}

export async function semanticSearch(
  query: string,
  topK: number = 20,
  filters: Partial<ProductFilters> = {},
): Promise<SemanticSearchResponse> {
  const response = await apiClient.post<SemanticSearchResponse>('/semantic/search', {
    query,
    top_k: topK,
    threshold: 0.3,
    hybrid: true,
    game_system: filters.game_system || undefined,
    product_type: filters.product_type || undefined,
    genre: filters.genre || undefined,
    publisher: filters.publisher || undefined,
    author: filters.author || undefined,
    level_min: filters.level_min ? Number(filters.level_min) : undefined,
    level_max: filters.level_max ? Number(filters.level_max) : undefined,
    tags: filters.tags || undefined,
    collection: filters.collection || undefined,
  });
  return response.data;
}

export async function updateSemanticSearchProvider(provider: string): Promise<void> {
  await apiClient.patch('/settings', { semantic_search_provider: provider });
}
