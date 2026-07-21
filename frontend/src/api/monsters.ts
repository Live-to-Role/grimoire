import api from './client';

export interface MonsterAttack {
  name: string;
  bonus: number | null;
  damage_dice: string | null;
  damage_avg: number | null;
}

export interface MonsterEntry {
  id: number;
  product_id: number;
  product_title: string | null;
  name: string;
  page_number: number | null;
  system_profile: string;
  raw_text: string;
  ac: number | null;
  hd_dice: string | null;
  hd_value: number | null;
  hp_avg: number | null;
  attacks: MonsterAttack[];
  move: string | null;
  special_abilities: string[];
  environments: string[];
  extraction_confidence: number | null;
  flags: string[];
  review_status: 'pending' | 'confirmed' | 'rejected';
}

export interface MonsterFilters {
  environment?: string;
  system_profile?: string;
  product_ids?: number[];
  review_status?: string;
  q?: string;
  hd_min?: number;
  hd_max?: number;
  page?: number;
  per_page?: number;
}

export interface TierMetrics {
  tier: string;
  ac: number;
  attacks: { name: string; hit_chance: number | null; dpr: number | null }[];
  total_dpr: number;
}

export interface MonsterMetrics {
  hp_avg: number | null;
  tiers: TierMetrics[];
}

export async function listMonsters(filters: MonsterFilters) {
  const { data } = await api.get<{ items: MonsterEntry[]; total: number }>('/monsters', {
    params: filters,
    // FastAPI's list[int] expects repeated bare keys (product_ids=1&product_ids=2);
    // axios would otherwise emit product_ids[]=1 and the param would be dropped.
    paramsSerializer: { indexes: null },
  });
  return data;
}

export async function listEnvironments() {
  const { data } = await api.get<{ environments: string[] }>('/monsters/environments');
  return data.environments;
}

export async function getMetrics(entryId: number) {
  const { data } = await api.get<MonsterMetrics>(`/monsters/${entryId}/metrics`);
  return data;
}

export interface MonsterAttackInput {
  name: string;
  bonus: number | null;
  damage_dice: string | null;
}

export interface MonsterEntryInput {
  product_id: number;
  name: string;
  system_profile: string;
  page_number?: number | null;
  raw_text?: string | null;
  ac?: number | null;
  hd_dice?: string | null;
  attacks?: MonsterAttackInput[];
  move?: string | null;
  special_abilities?: string[];
  environments?: string[];
}

export async function createMonster(input: MonsterEntryInput) {
  const { data } = await api.post<MonsterEntry>('/monsters', input);
  return data;
}

export async function deleteMonster(entryId: number) {
  await api.delete(`/monsters/${entryId}`);
}

// Partial<MonsterEntryInput> rather than Partial<MonsterEntry>: derived fields
// (hd_value, hp_avg, damage_avg, flags) are server-computed and must never be
// sent. A key present with value null now clears that field server-side.
export async function patchMonster(
  entryId: number,
  patch: Partial<MonsterEntryInput> & { review_status?: string },
) {
  const { data } = await api.patch<MonsterEntry>(`/monsters/${entryId}`, patch);
  return data;
}

export async function rollRandom(params: {
  count: number;
  environment?: string;
  system_profile?: string;
  hd_min?: number;
  hd_max?: number;
  product_ids?: number[];
}) {
  const { data } = await api.post<{ items: MonsterEntry[] }>('/monsters/random', params);
  return data.items;
}

export interface BestiaryBook {
  product_id: number;
  title: string | null;
  count: number;
}

export interface FavoriteConfig {
  product_ids?: number[];
  environment?: string;
  system_profile?: string;
  hd_min?: number;
  hd_max?: number;
  q?: string;
  table_size?: number;
}

export interface BestiaryFavorite {
  id: number;
  name: string;
  config: FavoriteConfig;
}

export interface ExtractResult {
  queued: boolean;
  message: string;
  counts?: Record<string, number>;
  warning?: string;
}

export async function bulkSetStatus(ids: number[], reviewStatus: string) {
  const { data } = await api.post<{ updated: number }>('/monsters/bulk-status', {
    ids,
    review_status: reviewStatus,
  });
  return data.updated;
}

export async function listBooks(reviewStatus = 'confirmed') {
  const { data } = await api.get<{ books: BestiaryBook[] }>('/monsters/books', {
    params: { review_status: reviewStatus },
  });
  return data.books;
}

export async function listFavorites() {
  const { data } = await api.get<{ favorites: BestiaryFavorite[] }>('/monsters/favorites');
  return data.favorites;
}

export async function createFavorite(name: string, config: FavoriteConfig) {
  const { data } = await api.post<BestiaryFavorite>('/monsters/favorites', { name, config });
  return data;
}

export async function updateFavorite(
  id: number,
  patch: { name?: string; config?: FavoriteConfig },
) {
  const { data } = await api.patch<BestiaryFavorite>(`/monsters/favorites/${id}`, patch);
  return data;
}

export async function deleteFavorite(id: number) {
  await api.delete(`/monsters/favorites/${id}`);
}

export async function queueExtraction(productId: number, systemProfile: string) {
  const { data } = await api.post<ExtractResult>(
    `/monsters/extract/${productId}`,
    { system_profile: systemProfile },
  );
  return data;
}
