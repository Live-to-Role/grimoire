import client from './client';

export interface GalleryTag {
  id: number;
  name: string;
  color: string | null;
  is_builtin: boolean;
}

export interface GalleryProduct {
  id: number;
  title: string;
  file_name: string;
  product_type: string | null;
  image_count: number;
  images_extracted: boolean;
  cover_extracted: boolean;
  page_count: number | null;
  publisher: string | null;
  created_at: string | null;
  tags: GalleryTag[];
}

export interface GalleryResponse {
  items: GalleryProduct[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface GalleryFilters {
  page?: number;
  page_size?: number;
  tag_id?: number;
  collection_id?: number;
  sort?: 'created_at' | 'title' | 'image_count';
  order?: 'asc' | 'desc';
  search?: string;
}

export interface ProductImage {
  filename: string;
  page: number;
  width: number;
  height: number;
  original_format: string;
  file_size: number;
  url: string;
}

export interface ProductImagesResponse {
  images: ProductImage[];
  image_count: number;
  total_pages: number;
}

export async function getGalleryProducts(filters: GalleryFilters = {}): Promise<GalleryResponse> {
  const params = new URLSearchParams();
  if (filters.page) params.set('page', String(filters.page));
  if (filters.page_size) params.set('page_size', String(filters.page_size));
  if (filters.tag_id) params.set('tag_id', String(filters.tag_id));
  if (filters.collection_id) params.set('collection_id', String(filters.collection_id));
  if (filters.sort) params.set('sort', filters.sort);
  if (filters.order) params.set('order', filters.order);
  if (filters.search) params.set('search', filters.search);

  const { data } = await client.get(`/gallery?${params.toString()}`);
  return data;
}

export async function getProductImages(productId: number): Promise<ProductImagesResponse> {
  const { data } = await client.get(`/products/${productId}/images`);
  return data;
}

export function getImageUrl(productId: number, filename: string): string {
  return `/api/v1/products/${productId}/images/${filename}`;
}
