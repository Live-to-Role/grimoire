import { useState } from 'react';
import { X } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createMonster, patchMonster,
  type MonsterEntry, type MonsterAttackInput, type MonsterEntryInput,
} from '../api/monsters';
import { getProducts } from '../api/products';

export type EntryModalMode = 'create' | 'edit' | 'duplicate';

export interface MonsterEntryModalProps {
  mode: EntryModalMode;
  entry: MonsterEntry | null;
  onClose: () => void;
  onCreated: (entry: MonsterEntry) => void;
  onSaved: () => void;
}

const PROFILE_OPTIONS = [
  { value: 'dcc', label: 'DCC' },
  { value: 'osr', label: 'Generic OSR' },
];

interface FormState {
  productId: number | null;
  productLabel: string;
  systemProfile: string;
  name: string;
  pageNumber: string;
  ac: string;
  hdDice: string;
  move: string;
  attacks: MonsterAttackInput[];
  specialAbilities: string;
  environments: string;
  rawText: string;
}

function initialState(mode: EntryModalMode, entry: MonsterEntry | null): FormState {
  if (mode === 'create' || !entry) {
    return {
      productId: null, productLabel: '', systemProfile: 'dcc', name: '',
      pageNumber: '', ac: '', hdDice: '', move: '', attacks: [],
      specialAbilities: '', environments: '', rawText: '',
    };
  }
  const shared = {
    productId: entry.product_id,
    productLabel: entry.product_title ?? `Book ${entry.product_id}`,
    systemProfile: entry.system_profile,
    pageNumber: entry.page_number === null ? '' : String(entry.page_number),
    rawText: entry.raw_text,
  };
  if (mode === 'duplicate') {
    // Book, page, profile and raw_text carry over — that shared context is the
    // whole point of duplicating. Stats are cleared because a split entry's
    // numbers belong to a different creature. The " (copy)" suffix makes an
    // unedited save obvious in the list.
    return {
      ...shared,
      name: `${entry.name} (copy)`,
      ac: '', hdDice: '', move: '', attacks: [],
      specialAbilities: '', environments: '',
    };
  }
  return {
    ...shared,
    name: entry.name,
    ac: entry.ac === null ? '' : String(entry.ac),
    hdDice: entry.hd_dice ?? '',
    move: entry.move ?? '',
    attacks: entry.attacks.map((a) => ({
      name: a.name, bonus: a.bonus, damage_dice: a.damage_dice,
    })),
    specialAbilities: entry.special_abilities.join('\n'),
    environments: entry.environments.join(', '),
  };
}

// '' means "clear this field", not "0". Number('') is 0, which would silently
// write AC 0 — the bug the old inline editor worked around by refusing blanks.
function numOrNull(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === '') return null;
  const parsed = Number(trimmed);
  return Number.isNaN(parsed) ? null : parsed;
}

function strOrNull(raw: string): string | null {
  const trimmed = raw.trim();
  return trimmed === '' ? null : trimmed;
}

function splitList(raw: string, separator: RegExp): string[] {
  return raw.split(separator).map((s) => s.trim()).filter((s) => s.length > 0);
}

const inputClass = 'px-2 py-1 rounded border bg-transparent';
const borderStyle = { borderColor: 'var(--color-border)' };

export function MonsterEntryModal({
  mode, entry, onClose, onCreated, onSaved,
}: MonsterEntryModalProps) {
  const [form, setForm] = useState<FormState>(() => initialState(mode, entry));
  const [bookSearch, setBookSearch] = useState('');
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  // search_mode 'name': the user is naming a book, not searching its contents.
  // Deliberately NOT /monsters/books — creating the first entry for a book is a
  // valid case, and that endpoint only lists books that already have entries.
  const { data: bookResults } = useQuery({
    queryKey: ['entry-modal-book-search', bookSearch],
    queryFn: () => getProducts({ search: bookSearch, search_mode: 'name', per_page: 10 }),
    enabled: bookSearch.trim().length >= 2,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['monsters'] });
    queryClient.invalidateQueries({ queryKey: ['monster-books'] });
    queryClient.invalidateQueries({ queryKey: ['monster-environments'] });
    queryClient.invalidateQueries({ queryKey: ['monster-metrics'] });
  };

  const saveMutation = useMutation({
    mutationFn: async () => {
      const payload: MonsterEntryInput = {
        product_id: form.productId!,
        name: form.name.trim(),
        system_profile: form.systemProfile,
        page_number: numOrNull(form.pageNumber),
        ac: numOrNull(form.ac),
        hd_dice: strOrNull(form.hdDice),
        move: strOrNull(form.move),
        attacks: form.attacks.map((a) => ({
          name: a.name.trim() || 'attack',
          bonus: a.bonus,
          damage_dice: a.damage_dice,
        })),
        special_abilities: splitList(form.specialAbilities, /\n/),
        environments: splitList(form.environments, /,/),
      };
      if (mode === 'edit' && entry) {
        // raw_text and system_profile are not editable: raw_text is provenance,
        // and system_profile selects the armor tiers the metrics are computed
        // against, so changing it would silently invalidate every shown number.
        const { product_id, system_profile, raw_text, ...editable } = payload;
        return patchMonster(entry.id, editable);
      }
      return createMonster({ ...payload, raw_text: form.rawText || null });
    },
    onSuccess: (result) => {
      invalidate();
      if (mode === 'edit') onSaved();
      else onCreated(result as MonsterEntry);
    },
    onError: (err: any) =>
      setError(err?.response?.data?.detail ?? 'Failed to save entry'),
  });

  const submit = () => {
    setError(null);
    if (!form.name.trim()) { setError('Name is required'); return; }
    if (mode !== 'edit' && form.productId === null) { setError('Pick a book'); return; }
    saveMutation.mutate();
  };

  const addAttack = () =>
    set('attacks', [...form.attacks, { name: '', bonus: null, damage_dice: null }]);
  const removeAttack = (index: number) =>
    set('attacks', form.attacks.filter((_, i) => i !== index));
  const updateAttack = (index: number, patch: Partial<MonsterAttackInput>) =>
    set('attacks', form.attacks.map((a, i) => (i === index ? { ...a, ...patch } : a)));

  const title = mode === 'create' ? 'Add entry'
    : mode === 'duplicate' ? 'Duplicate entry' : 'Edit entry';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/50" />
      <div
        className="relative w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-lg shadow-2xl p-4"
        style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)',
                 color: 'var(--color-text-primary)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>

        {mode === 'edit' ? (
          <p className="text-sm opacity-70 mb-3">
            {form.productLabel} · {PROFILE_OPTIONS.find((p) => p.value === form.systemProfile)?.label
              ?? form.systemProfile}
          </p>
        ) : (
          <div className="mb-3 space-y-1">
            <label className="block text-sm opacity-80">Book</label>
            {form.productId !== null ? (
              <div className="flex items-center gap-2 text-sm">
                <span>{form.productLabel}</span>
                <button className="opacity-70 underline"
                  onClick={() => { set('productId', null); set('productLabel', ''); }}>
                  change
                </button>
              </div>
            ) : (
              <>
                <input className={`${inputClass} w-full`} style={borderStyle}
                  placeholder="Search your library… (min 2 chars)"
                  value={bookSearch} onChange={(e) => setBookSearch(e.target.value)} />
                {(bookResults?.items ?? []).map((p) => (
                  <button key={p.id}
                    className="block w-full text-left text-sm px-2 py-1 rounded hover:opacity-80"
                    onClick={() => {
                      set('productId', p.id);
                      set('productLabel', p.title ?? p.file_name);
                    }}>
                    {p.title ?? p.file_name}
                  </button>
                ))}
              </>
            )}
            <div className="flex gap-2 items-center pt-1">
              <label className="text-sm opacity-80">System</label>
              <select className={inputClass} style={borderStyle} value={form.systemProfile}
                onChange={(e) => set('systemProfile', e.target.value)}>
                {PROFILE_OPTIONS.map((p) => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 mb-3">
          <label className="text-sm">Name
            <input className={`${inputClass} w-full`} style={borderStyle}
              value={form.name} onChange={(e) => set('name', e.target.value)} />
          </label>
          <label className="text-sm">Page
            <input type="number" className={`${inputClass} w-full`} style={borderStyle}
              value={form.pageNumber} onChange={(e) => set('pageNumber', e.target.value)} />
          </label>
          <label className="text-sm">AC
            <input type="number" className={`${inputClass} w-full`} style={borderStyle}
              value={form.ac} onChange={(e) => set('ac', e.target.value)} />
          </label>
          <label className="text-sm">HD
            <input className={`${inputClass} w-full`} style={borderStyle} placeholder="3d8+3"
              value={form.hdDice} onChange={(e) => set('hdDice', e.target.value)} />
          </label>
          <label className="text-sm col-span-2">Move
            <input className={`${inputClass} w-full`} style={borderStyle} placeholder="30'"
              value={form.move} onChange={(e) => set('move', e.target.value)} />
          </label>
        </div>

        <div className="mb-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-sm opacity-80">Attacks</span>
            <button className="text-sm px-2 py-0.5 rounded border" style={borderStyle}
              onClick={addAttack}>Add attack</button>
          </div>
          {form.attacks.length === 0 && (
            <p className="text-xs opacity-60">No attacks — the entry will be flagged “no_attacks”.</p>
          )}
          {form.attacks.map((atk, i) => (
            <div key={i} className="flex gap-2 items-center mb-1">
              <input className={`${inputClass} flex-1`} style={borderStyle} placeholder="claw"
                value={atk.name} onChange={(e) => updateAttack(i, { name: e.target.value })} />
              <input type="number" className={`${inputClass} w-20`} style={borderStyle}
                placeholder="+bonus"
                value={atk.bonus === null ? '' : String(atk.bonus)}
                onChange={(e) => updateAttack(i, { bonus: numOrNull(e.target.value) })} />
              <input className={`${inputClass} w-40`} style={borderStyle} placeholder="1d4"
                value={atk.damage_dice ?? ''}
                onChange={(e) => updateAttack(i, { damage_dice: strOrNull(e.target.value) })} />
              <button className="opacity-60 px-1" aria-label="Remove attack"
                onClick={() => removeAttack(i)}>×</button>
            </div>
          ))}
          <p className="text-xs opacity-60">
            Freeform damage such as “1d3 plus stun” is fine — it just yields no average.
          </p>
        </div>

        <label className="block text-sm mb-3">Special abilities (one per line)
          <textarea className={`${inputClass} w-full h-20`} style={borderStyle}
            value={form.specialAbilities}
            onChange={(e) => set('specialAbilities', e.target.value)} />
        </label>

        <label className="block text-sm mb-3">Environments (comma separated)
          <input className={`${inputClass} w-full`} style={borderStyle} placeholder="forest, swamp"
            value={form.environments} onChange={(e) => set('environments', e.target.value)} />
        </label>

        {mode !== 'edit' && (
          <label className="block text-sm mb-3">Source excerpt (optional)
            <textarea className={`${inputClass} w-full h-24 font-mono text-xs`} style={borderStyle}
              value={form.rawText} onChange={(e) => set('rawText', e.target.value)} />
          </label>
        )}

        {error && <p className="text-sm mb-2" style={{ color: 'var(--color-danger)' }}>{error}</p>}

        <div className="flex gap-2 justify-end">
          <button className="px-3 py-1 rounded border opacity-80" style={borderStyle}
            onClick={onClose}>Cancel</button>
          <button className="px-3 py-1 rounded border" style={borderStyle}
            disabled={saveMutation.isPending} onClick={submit}>
            {saveMutation.isPending ? 'Saving…' : mode === 'edit' ? 'Save changes' : 'Create entry'}
          </button>
        </div>
      </div>
    </div>
  );
}
