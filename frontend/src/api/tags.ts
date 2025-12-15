import apiClient from './client';

export interface Tag {
  id: number;
  name: string;
  category: string | null;
  color: string | null;
  created_at: string;
  product_count: number;
}

export interface TagCreate {
  name: string;
  category?: string | null;
  color?: string | null;
}

export interface TagUpdate {
  name?: string;
  category?: string | null;
  color?: string | null;
}

export async function getTags(category?: string): Promise<Tag[]> {
  const params = category ? { category } : {};
  const res = await apiClient.get<Tag[]>('/tags', { params });
  return res.data;
}

export async function getTag(id: number): Promise<Tag> {
  const res = await apiClient.get<Tag>(`/tags/${id}`);
  return res.data;
}

export async function createTag(data: TagCreate): Promise<Tag> {
  const res = await apiClient.post<Tag>('/tags', data);
  return res.data;
}

export async function updateTag(id: number, data: TagUpdate): Promise<Tag> {
  const res = await apiClient.patch<Tag>(`/tags/${id}`, data);
  return res.data;
}

export async function deleteTag(id: number): Promise<void> {
  await apiClient.delete(`/tags/${id}`);
}

export async function addTagToProduct(productId: number, tagId: number): Promise<void> {
  await apiClient.post(`/products/${productId}/tags?tag_id=${tagId}`);
}

export async function removeTagFromProduct(productId: number, tagId: number): Promise<void> {
  await apiClient.delete(`/products/${productId}/tags/${tagId}`);
}
