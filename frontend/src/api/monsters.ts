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
  product_id?: number;
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

export async function patchMonster(entryId: number, patch: Partial<MonsterEntry>) {
  const { data } = await api.patch<MonsterEntry>(`/monsters/${entryId}`, patch);
  return data;
}

export async function rollRandom(params: {
  count: number;
  environment?: string;
  system_profile?: string;
  hd_min?: number;
  hd_max?: number;
  product_id?: number;
}) {
  const { data } = await api.post<{ items: MonsterEntry[] }>('/monsters/random', params);
  return data.items;
}

export async function queueExtraction(productId: number, systemProfile: string) {
  const { data } = await api.post<{ queued: boolean; message: string }>(
    `/monsters/extract/${productId}`,
    { system_profile: systemProfile },
  );
  return data;
}
