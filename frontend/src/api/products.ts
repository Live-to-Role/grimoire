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
  tags?: string;
  collection?: number;
  has_cover?: boolean;
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
