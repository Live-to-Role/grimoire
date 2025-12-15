import api from './client';
import type { Product, ProductListResponse } from '../types/product';

export interface ProductFilters {
  page?: number;
  per_page?: number;
  sort?: 'title' | 'created_at' | 'updated_at' | 'last_opened_at' | 'file_name';
  order?: 'asc' | 'desc';
  search?: string;
  game_system?: string;
  product_type?: string;
  genre?: string;
  author?: string;
  publisher?: string;
  tags?: string;
  collection?: number;
  has_cover?: boolean;
  publication_year_min?: string;
  publication_year_max?: string;
  level_min?: string;
  level_max?: string;
  party_size_min?: string;
  party_size_max?: string;
  estimated_runtime?: string;
}

export async function getProducts(filters: ProductFilters = {}): Promise<ProductListResponse> {
  const params = new URLSearchParams();
  
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      params.append(key, String(value));
    }
  });

  const response = await api.get<ProductListResponse>(`/products?${params.toString()}`);
  return response.data;
}

export async function getProduct(id: number): Promise<Product> {
  const response = await api.get<Product>(`/products/${id}`);
  return response.data;
}

export async function updateProduct(id: number, data: Partial<Product>): Promise<Product> {
  const response = await api.patch<Product>(`/products/${id}`, data);
  return response.data;
}

export function getCoverUrl(productId: number): string {
  return `/api/v1/products/${productId}/cover`;
}

export function getPdfUrl(productId: number): string {
  return `/api/v1/products/${productId}/pdf`;
}

export interface ContributionStatus {
  has_contribution: boolean;
  product_id: number;
  contribution_id?: number;
  status?: 'pending' | 'submitted' | 'accepted' | 'rejected' | 'failed';
  created_at?: string;
  submitted_at?: string | null;
  error_message?: string | null;
}

export async function contributeProduct(productId: number): Promise<{
  success: boolean;
  queued?: boolean;
  contribution_id?: number;
  status?: string;
  submitted?: boolean;
  reason?: string;
  message?: string;
}> {
  const response = await api.post(`/contributions/product/${productId}`);
  return response.data;
}

export async function getContributionStatus(productId: number): Promise<ContributionStatus> {
  const response = await api.get<ContributionStatus>(`/contributions/product/${productId}/status`);
  return response.data;
}

export async function updateProductAndContribute(
  id: number,
  data: Partial<Product>,
): Promise<Product> {
  const response = await api.patch<Product>(`/products/${id}?send_to_codex=true`, data);
  return response.data;
}
