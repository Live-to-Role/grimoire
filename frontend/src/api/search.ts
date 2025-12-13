import apiClient from './client';
import type { Product } from '../types/product';

export interface SearchResult extends Product {
  snippets?: Array<{
    line: number;
    snippet: string;
  }>;
}

export interface SearchResponse {
  results: SearchResult[];
  total: number;
  query_time_ms: number;
  content_search: boolean;
}

export interface SearchParams {
  q: string;
  game_system?: string;
  product_type?: string;
  search_content?: boolean;
  limit?: number;
}

export async function searchProducts(params: SearchParams): Promise<SearchResponse> {
  const searchParams = new URLSearchParams();
  searchParams.set('q', params.q);
  if (params.game_system) searchParams.set('game_system', params.game_system);
  if (params.product_type) searchParams.set('product_type', params.product_type);
  if (params.search_content) searchParams.set('search_content', 'true');
  if (params.limit) searchParams.set('limit', params.limit.toString());

  const response = await apiClient.get<SearchResponse>(`/search?${searchParams.toString()}`);
  return response.data;
}

export async function getProductText(productId: number): Promise<{ markdown: string; char_count: number }> {
  const response = await apiClient.get(`/products/${productId}/text`);
  return response.data;
}
