import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  listMonsters, listEnvironments, getMetrics, patchMonster, rollRandom, queueExtraction,
  type MonsterEntry, type MonsterFilters,
} from '../api/monsters';
import { getProducts } from '../api/products';

const TABLE_SIZES = [4, 6, 8, 10, 12, 20];

function cite(entry: MonsterEntry): string {
  return `${entry.name} — ${entry.product_title ?? 'Unknown book'}, p. ${entry.page_number ?? '?'}`;
}

export function Bestiary() {
  const [filters, setFilters] = useState<MonsterFilters>({ review_status: 'confirmed' });
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [rolled, setRolled] = useState<MonsterEntry[]>([]);
  const [tableSize, setTableSize] = useState(8);
  const [showExtract, setShowExtract] = useState(false);
  const [productSearch, setProductSearch] = useState('');
  const [extractProfile, setExtractProfile] = useState<'dcc' | 'osr'>('dcc');
  const [extractMessage, setExtractMessage] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data: environments = [] } = useQuery({
    queryKey: ['monster-environments'],
    queryFn: listEnvironments,
  });
  const { data, isLoading } = useQuery({
    queryKey: ['monsters', filters],
    queryFn: () => listMonsters(filters),
  });
  const { data: metrics } = useQuery({
    queryKey: ['monster-metrics', expandedId],
    queryFn: () => getMetrics(expandedId!),
    enabled: expandedId !== null,
  });
  const { data: productResults } = useQuery({
    queryKey: ['bestiary-product-search', productSearch],
    queryFn: () => getProducts({ search: productSearch, per_page: 10 }),
    enabled: showExtract && productSearch.length >= 2,
  });

  const patchMutation = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: Partial<MonsterEntry> }) =>
      patchMonster(id, patch),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['monsters'] }),
  });
  const extractMutation = useMutation({
    mutationFn: ({ productId, profile }: { productId: number; profile: string }) =>
      queueExtraction(productId, profile),
    onSuccess: (result) => setExtractMessage(result.message),
    onError: (err: any) =>
      setExtractMessage(err?.response?.data?.detail ?? 'Failed to queue extraction'),
  });

  const setFilter = (patch: Partial<MonsterFilters>) =>
    setFilters((prev) => ({ ...prev, ...patch }));

  const roll = async (count: number) => {
    setRolled(await rollRandom({
      count,
      environment: filters.environment,
      system_profile: filters.system_profile,
      hd_min: filters.hd_min,
      hd_max: filters.hd_max,
    }));
  };

  const reviewMode = filters.review_status === 'pending';
  const items = data?.items ?? [];

  return (
    <div className="h-full overflow-y-auto p-4" style={{ color: 'var(--color-text-primary)' }}>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold">Bestiary</h1>
        <button className="px-3 py-1.5 rounded border" style={{ borderColor: 'var(--color-border)' }}
          onClick={() => { setShowExtract(!showExtract); setExtractMessage(null); }}>
          Extract from book…
        </button>
      </div>

      {showExtract && (
        <div className="mb-4 p-3 rounded border" style={{ borderColor: 'var(--color-border)' }}>
          <div className="flex gap-2 items-center flex-wrap">
            <input className="px-2 py-1 rounded border flex-1 min-w-[200px] bg-transparent"
              style={{ borderColor: 'var(--color-border)' }}
              placeholder="Search your library… (min 2 chars)"
              value={productSearch} onChange={(e) => setProductSearch(e.target.value)} />
            <select value={extractProfile} className="px-2 py-1 rounded border bg-transparent"
              style={{ borderColor: 'var(--color-border)' }}
              onChange={(e) => setExtractProfile(e.target.value as 'dcc' | 'osr')}>
              <option value="dcc">DCC</option>
              <option value="osr">Generic OSR</option>
            </select>
          </div>
          {(productResults?.items ?? []).map((p) => (
            <div key={p.id} className="flex items-center justify-between py-1 text-sm">
              <span>{p.title ?? p.file_name}</span>
              <button className="px-2 py-0.5 rounded border" style={{ borderColor: 'var(--color-border)' }}
                disabled={extractMutation.isPending}
                onClick={() => extractMutation.mutate({ productId: p.id, profile: extractProfile })}>
                Extract monsters
              </button>
            </div>
          ))}
          {extractMessage && <p className="text-sm mt-2 opacity-80">{extractMessage}</p>}
        </div>
      )}

      <div className="flex gap-2 items-end flex-wrap mb-4">
        <select className="px-2 py-1 rounded border bg-transparent" style={{ borderColor: 'var(--color-border)' }}
          value={filters.environment ?? ''}
          onChange={(e) => setFilter({ environment: e.target.value || undefined })}>
          <option value="">All environments</option>
          {environments.map((env) => <option key={env} value={env}>{env}</option>)}
        </select>
        <select className="px-2 py-1 rounded border bg-transparent" style={{ borderColor: 'var(--color-border)' }}
          value={filters.system_profile ?? ''}
          onChange={(e) => setFilter({ system_profile: e.target.value || undefined })}>
          <option value="">All systems</option>
          <option value="dcc">DCC</option>
          <option value="osr">OSR</option>
        </select>
        <input type="number" className="w-20 px-2 py-1 rounded border bg-transparent"
          style={{ borderColor: 'var(--color-border)' }} placeholder="HD min"
          value={filters.hd_min ?? ''}
          onChange={(e) => setFilter({ hd_min: e.target.value ? Number(e.target.value) : undefined })} />
        <input type="number" className="w-20 px-2 py-1 rounded border bg-transparent"
          style={{ borderColor: 'var(--color-border)' }} placeholder="HD max"
          value={filters.hd_max ?? ''}
          onChange={(e) => setFilter({ hd_max: e.target.value ? Number(e.target.value) : undefined })} />
        <input className="px-2 py-1 rounded border bg-transparent flex-1 min-w-[160px]"
          style={{ borderColor: 'var(--color-border)' }} placeholder="Search name…"
          value={filters.q ?? ''}
          onChange={(e) => setFilter({ q: e.target.value || undefined })} />
        <button className="px-3 py-1 rounded border" style={{ borderColor: 'var(--color-border)' }}
          onClick={() => setFilter({ review_status: reviewMode ? 'confirmed' : 'pending' })}>
          {reviewMode ? 'Show confirmed' : 'Review pending'}
        </button>
      </div>

      {!reviewMode && (
        <div className="flex gap-2 items-center mb-4">
          <button className="px-3 py-1 rounded border" style={{ borderColor: 'var(--color-border)' }}
            onClick={() => roll(3)}>Roll 3 random</button>
          <select className="px-2 py-1 rounded border bg-transparent" style={{ borderColor: 'var(--color-border)' }}
            value={tableSize} onChange={(e) => setTableSize(Number(e.target.value))}>
            {TABLE_SIZES.map((n) => <option key={n} value={n}>d{n}</option>)}
          </select>
          <button className="px-3 py-1 rounded border" style={{ borderColor: 'var(--color-border)' }}
            onClick={() => roll(tableSize)}>Generate d{tableSize} table</button>
          {rolled.length > 0 && (
            <button className="px-2 py-1 text-sm opacity-70" onClick={() => setRolled([])}>Clear</button>
          )}
        </div>
      )}

      {rolled.length > 0 && !reviewMode && (
        <table className="mb-4 text-sm w-full max-w-2xl">
          <tbody>
            {rolled.map((entry, i) => (
              <tr key={`${entry.id}-${i}`} className="border-b" style={{ borderColor: 'var(--color-border)' }}>
                <td className="py-1 pr-3 w-8 font-mono">{i + 1}</td>
                <td className="py-1">{cite(entry)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {isLoading && <p className="opacity-70">Loading…</p>}
      {!isLoading && items.length === 0 && (
        <p className="opacity-70">
          {reviewMode
            ? 'No pending entries. Queue an extraction with "Extract from book…" above.'
            : 'No confirmed monsters yet. Extract a bestiary, then confirm entries in Review pending.'}
        </p>
      )}

      <div className="space-y-2">
        {items.map((entry) => (
          <div key={entry.id} className="rounded border p-3" style={{ borderColor: 'var(--color-border)' }}>
            <div className="flex items-center justify-between cursor-pointer"
              onClick={() => setExpandedId(expandedId === entry.id ? null : entry.id)}>
              <div>
                <span className="font-medium">{entry.name}</span>
                <span className="opacity-70 text-sm ml-2">
                  {entry.product_title ?? 'Unknown book'}, p. {entry.page_number ?? '?'}
                </span>
              </div>
              <div className="text-sm opacity-80 flex gap-3">
                <span>AC {entry.ac ?? '?'}</span>
                <span>HD {entry.hd_dice ?? '?'}</span>
                {entry.environments.map((env) => (
                  <span key={env} className="px-1.5 rounded text-xs border"
                    style={{ borderColor: 'var(--color-border)' }}>{env}</span>
                ))}
              </div>
            </div>

            {reviewMode && (
              <div className="mt-2 space-y-2">
                {entry.flags.length > 0 && (
                  <div className="flex gap-1">
                    {entry.flags.map((flag) => (
                      <span key={flag} className="text-xs px-1.5 rounded"
                        style={{ backgroundColor: 'var(--color-danger)', color: '#fff' }}>
                        {flag}
                      </span>
                    ))}
                  </div>
                )}
                <pre className="text-xs p-2 rounded overflow-x-auto border whitespace-pre-wrap"
                  style={{ borderColor: 'var(--color-border)' }}>{entry.raw_text}</pre>
                <div className="flex gap-2 items-center text-sm">
                  <label>Name <input className="px-1 border rounded bg-transparent"
                    style={{ borderColor: 'var(--color-border)' }} defaultValue={entry.name}
                    onBlur={(e) => e.target.value !== entry.name &&
                      patchMutation.mutate({ id: entry.id, patch: { name: e.target.value } })} /></label>
                  <label>AC <input type="number" className="w-16 px-1 border rounded bg-transparent"
                    style={{ borderColor: 'var(--color-border)' }} defaultValue={entry.ac ?? ''}
                    onBlur={(e) => e.target.value !== String(entry.ac ?? '') &&
                      patchMutation.mutate({ id: entry.id, patch: { ac: Number(e.target.value) } })} /></label>
                  <label>HD <input className="w-20 px-1 border rounded bg-transparent"
                    style={{ borderColor: 'var(--color-border)' }} defaultValue={entry.hd_dice ?? ''}
                    onBlur={(e) => e.target.value !== (entry.hd_dice ?? '') &&
                      patchMutation.mutate({ id: entry.id, patch: { hd_dice: e.target.value } })} /></label>
                  <button className="px-2 py-0.5 rounded border ml-auto"
                    style={{ borderColor: 'var(--color-border)' }}
                    onClick={() => patchMutation.mutate({ id: entry.id, patch: { review_status: 'confirmed' } })}>
                    Confirm
                  </button>
                  <button className="px-2 py-0.5 rounded border opacity-70"
                    style={{ borderColor: 'var(--color-border)' }}
                    onClick={() => patchMutation.mutate({ id: entry.id, patch: { review_status: 'rejected' } })}>
                    Reject
                  </button>
                </div>
              </div>
            )}

            {expandedId === entry.id && metrics && (
              <div className="mt-3 text-sm">
                <p className="mb-1">Average HP: {metrics.hp_avg ?? '?'}</p>
                <table className="w-full max-w-md">
                  <thead>
                    <tr className="text-left opacity-70">
                      <th className="pr-3">vs.</th><th className="pr-3">AC</th>
                      <th className="pr-3">Hit %</th><th>Dmg/round</th>
                    </tr>
                  </thead>
                  <tbody>
                    {metrics.tiers.map((tier) => (
                      <tr key={tier.tier}>
                        <td className="pr-3">{tier.tier}</td>
                        <td className="pr-3">{tier.ac}</td>
                        <td className="pr-3">
                          {tier.attacks.length > 0 && tier.attacks[0].hit_chance !== null
                            ? `${Math.round(tier.attacks[0].hit_chance * 100)}%` : '—'}
                        </td>
                        <td>{tier.total_dpr}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {entry.special_abilities.length > 0 && (
                  <p className="mt-2 opacity-80">
                    Special (not in the math): {entry.special_abilities.join(', ')}
                  </p>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
