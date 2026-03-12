import apiClient from './client';

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

export async function semanticSearch(query: string, topK: number = 20): Promise<SemanticSearchResponse> {
  const response = await apiClient.post<SemanticSearchResponse>('/semantic/search', {
    query,
    top_k: topK,
    threshold: 0.3,
  });
  return response.data;
}

export async function updateSemanticSearchProvider(provider: string): Promise<void> {
  await apiClient.patch('/settings', { semantic_search_provider: provider });
}
