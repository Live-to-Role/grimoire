import apiClient from './client';

export interface Collection {
  id: number;
  name: string;
  description: string | null;
  color: string | null;
  icon: string | null;
  sort_order: number;
  created_at: string;
  updated_at: string;
  product_count: number;
}

export interface CollectionCreate {
  name: string;
  description?: string | null;
  color?: string | null;
  icon?: string | null;
}

export interface CollectionUpdate {
  name?: string;
  description?: string | null;
  color?: string | null;
  icon?: string | null;
  sort_order?: number;
}

export async function getCollections(): Promise<Collection[]> {
  const res = await apiClient.get<Collection[]>('/collections');
  return res.data;
}

export async function getCollection(id: number): Promise<Collection> {
  const res = await apiClient.get<Collection>(`/collections/${id}`);
  return res.data;
}

export async function createCollection(data: CollectionCreate): Promise<Collection> {
  const res = await apiClient.post<Collection>('/collections', data);
  return res.data;
}

export async function updateCollection(id: number, data: CollectionUpdate): Promise<Collection> {
  const res = await apiClient.patch<Collection>(`/collections/${id}`, data);
  return res.data;
}

export async function deleteCollection(id: number): Promise<void> {
  await apiClient.delete(`/collections/${id}`);
}

export async function addProductToCollection(collectionId: number, productId: number): Promise<void> {
  await apiClient.post(`/collections/${collectionId}/products`, { product_id: productId });
}

export async function removeProductFromCollection(collectionId: number, productId: number): Promise<void> {
  await apiClient.delete(`/collections/${collectionId}/products/${productId}`);
}
