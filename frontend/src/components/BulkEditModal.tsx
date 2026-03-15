import { useState, useCallback } from 'react';
import { X } from 'lucide-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { bulkUpdateProducts, type BulkUpdateFields } from '../api/products';
import type { Product } from '../types/product';

interface BulkEditModalProps {
  selectedProducts: Product[];
  onClose: () => void;
  onComplete: () => void;
}

interface FieldState {
  value: string;
  touched: boolean;
  clear: boolean;
}

const FIELD_LABELS: Record<string, string> = {
  game_system: 'Game System',
  product_type: 'Product Type',
  genre: 'Genre',
  publisher: 'Publisher',
  author: 'Author',
  publication_year: 'Publication Year',
  setting: 'Setting',
  series: 'Series',
  estimated_runtime: 'Estimated Runtime',
  format: 'Format',
};

const LEFT_FIELDS = ['game_system', 'product_type', 'genre', 'publisher', 'author'];
const RIGHT_FIELDS = ['publication_year', 'setting', 'series', 'estimated_runtime', 'format'];
const CONTENT_TYPES = ['Map', 'Stock Art', 'Token', 'Handout', 'Portrait', 'Scene', 'Item', 'Texture'];

function createInitialState(): Record<string, FieldState> {
  const state: Record<string, FieldState> = {};
  for (const key of [...LEFT_FIELDS, ...RIGHT_FIELDS]) {
    state[key] = { value: '', touched: false, clear: false };
  }
  return state;
}

export function BulkEditModal({ selectedProducts, onClose, onComplete }: BulkEditModalProps) {
  const [fieldStates, setFieldStates] = useState<Record<string, FieldState>>(createInitialState);
  const [view, setView] = useState<'edit' | 'preview'>('edit');
  const [imageContentToggle, setImageContentToggle] = useState<'unchanged' | 'yes' | 'no'>('unchanged');
  const [contentType, setContentType] = useState<string>('');
  const [reExtract, setReExtract] = useState(false);
  const queryClient = useQueryClient();

  const updateField = useCallback((key: string, value: string) => {
    setFieldStates(prev => ({
      ...prev,
      [key]: { ...prev[key], value, touched: true, clear: false },
    }));
  }, []);

  const toggleClear = useCallback((key: string) => {
    setFieldStates(prev => ({
      ...prev,
      [key]: { ...prev[key], clear: !prev[key].clear, touched: true, value: '' },
    }));
  }, []);

  const changedFields = Object.entries(fieldStates).filter(
    ([, state]) => state.touched && (state.value !== '' || state.clear)
  );

  const hasChanges = changedFields.length > 0 || imageContentToggle !== 'unchanged';
  const needsContentType = imageContentToggle === 'yes' && !contentType;

  const mutation = useMutation({
    mutationFn: () => {
      const fields: BulkUpdateFields = {};
      for (const [key, state] of Object.entries(fieldStates)) {
        if (!state.touched) continue;
        if (state.clear) {
          if (key === 'publication_year') {
            (fields as any)[key] = null;
          } else {
            (fields as any)[key] = '';
          }
        } else if (state.value !== '') {
          if (key === 'publication_year') {
            (fields as any)[key] = parseInt(state.value, 10);
          } else {
            (fields as any)[key] = state.value;
          }
        }
      }
      if (imageContentToggle === 'yes') {
        fields.is_image_content = true;
        fields.content_type = contentType;
        fields.re_extract = reExtract;
      } else if (imageContentToggle === 'no') {
        fields.is_image_content = false;
      }
      return bulkUpdateProducts(
        selectedProducts.map(p => p.id),
        fields,
      );
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['products'] });
      queryClient.invalidateQueries({ queryKey: ['filters'] });
      queryClient.invalidateQueries({ queryKey: ['gallery'] });
      onComplete();
      onClose();
    },
  });

  const renderField = (key: string) => {
    const state = fieldStates[key];
    const isYear = key === 'publication_year';
    const isDisabledByReclassify = key === 'product_type' && imageContentToggle === 'yes';

    return (
      <div key={key} className="flex flex-col gap-1">
        <label className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>
          {FIELD_LABELS[key]}
          {isDisabledByReclassify && (
            <span className="text-xs ml-1" style={{ color: 'var(--color-text-tertiary)' }}>
              (set by Content Type)
            </span>
          )}
        </label>
        <div className="flex items-center gap-2">
          <input
            type={isYear ? 'number' : 'text'}
            value={state.value}
            onChange={(e) => updateField(key, e.target.value)}
            disabled={state.clear || isDisabledByReclassify}
            placeholder={state.clear ? '(will be cleared)' : isDisabledByReclassify ? '(set by content type)' : ''}
            className="input flex-1"
            style={{
              height: '40px',
              opacity: (state.clear || isDisabledByReclassify) ? 0.5 : 1,
            }}
          />
          <label className="flex items-center gap-1 text-xs whitespace-nowrap cursor-pointer" style={{ color: 'var(--color-text-secondary)' }}>
            <input
              type="checkbox"
              checked={state.clear}
              onChange={() => toggleClear(key)}
              className="accent-[var(--color-danger)]"
            />
            Clear
          </label>
        </div>
      </div>
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onClose}>
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50" />

      {/* Modal */}
      <div
        className="relative w-full max-w-2xl max-h-[80vh] overflow-y-auto rounded-lg shadow-2xl"
        style={{
          backgroundColor: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="sticky top-0 z-10 flex items-center justify-between px-6 py-4 border-b"
          style={{
            backgroundColor: 'var(--color-surface)',
            borderColor: 'var(--color-border)',
          }}
        >
          <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>
            {view === 'edit' ? `Edit ${selectedProducts.length} Products` : 'Preview Changes'}
          </h2>
          <button
            onClick={onClose}
            className="rounded-md p-1 transition-colors"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4">
          {view === 'edit' ? (
            <>
              <p className="mb-4 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                Only fields you fill in or mark as "Clear" will be changed. All other fields remain unchanged.
              </p>

              {/* Reclassification section */}
              <div
                className="mb-6 pb-4 border-b"
                style={{ borderColor: 'var(--color-border)' }}
              >
                <div className="flex items-center gap-4">
                  <div className="flex flex-col gap-1">
                    <label className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>
                      Image Content
                    </label>
                    <select
                      value={imageContentToggle}
                      onChange={(e) => {
                        const val = e.target.value as 'unchanged' | 'yes' | 'no';
                        setImageContentToggle(val);
                        if (val !== 'yes') {
                          setContentType('');
                          setReExtract(false);
                        }
                      }}
                      className="input"
                      style={{ height: '40px', minWidth: '140px' }}
                    >
                      <option value="unchanged">Unchanged</option>
                      <option value="yes">Yes</option>
                      <option value="no">No</option>
                    </select>
                  </div>

                  {imageContentToggle === 'yes' && (
                    <div className="flex flex-col gap-1">
                      <label className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>
                        Content Type
                      </label>
                      <select
                        value={contentType}
                        onChange={(e) => setContentType(e.target.value)}
                        className="input"
                        style={{ height: '40px', minWidth: '160px' }}
                      >
                        <option value="">Select type...</option>
                        {CONTENT_TYPES.map(t => (
                          <option key={t} value={t}>{t}</option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>
              </div>

              {/* Field grid */}
              <div className="grid grid-cols-2 gap-x-6 gap-y-4">
                <div className="flex flex-col gap-4">
                  {LEFT_FIELDS.map(renderField)}
                </div>
                <div className="flex flex-col gap-4">
                  {RIGHT_FIELDS.map(renderField)}
                </div>
              </div>
            </>
          ) : (
            <>
              {/* Changes summary */}
              <div className="mb-4">
                <h3 className="text-sm font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>
                  Changes to apply:
                </h3>
                <ul className="space-y-1">
                  {imageContentToggle === 'yes' && (
                    <li className="text-sm font-medium" style={{ color: 'var(--color-accent)' }}>
                      {selectedProducts.length} products &rarr; Image Content ({contentType})
                    </li>
                  )}
                  {imageContentToggle === 'no' && (
                    <li className="text-sm font-medium" style={{ color: 'var(--color-danger)' }}>
                      {selectedProducts.length} products &rarr; Regular (extracted images will be deleted)
                    </li>
                  )}
                  {changedFields.map(([key, state]) => (
                    <li key={key} className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                      {state.clear
                        ? `Clear ${FIELD_LABELS[key]}`
                        : `Set ${FIELD_LABELS[key]} to "${state.value}"`}
                    </li>
                  ))}
                </ul>
              </div>

              {/* Re-extract option */}
              {imageContentToggle === 'yes' && (
                <div
                  className="mb-4 p-3 rounded-md"
                  style={{
                    backgroundColor: 'var(--color-surface-raised)',
                    border: '1px solid var(--color-border)',
                  }}
                >
                  <label className="flex items-center gap-2 text-sm cursor-pointer" style={{ color: 'var(--color-text-secondary)' }}>
                    <input
                      type="checkbox"
                      checked={reExtract}
                      onChange={(e) => setReExtract(e.target.checked)}
                    />
                    Re-extract images for products that already have them
                  </label>
                </div>
              )}

              {/* Affected products */}
              <div>
                <h3 className="text-sm font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>
                  Apply to {selectedProducts.length} products:
                </h3>
                <div
                  className="max-h-[200px] overflow-y-auto rounded-md p-3"
                  style={{
                    backgroundColor: 'var(--color-surface-raised)',
                    border: '1px solid var(--color-border)',
                  }}
                >
                  <ul className="space-y-1">
                    {selectedProducts.map(p => (
                      <li key={p.id} className="text-sm truncate" style={{ color: 'var(--color-text-secondary)' }}>
                        {p.title || p.file_name}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>

              {mutation.isError && (
                <div
                  className="mt-4 rounded-md p-3 text-sm"
                  style={{
                    backgroundColor: 'rgba(224, 49, 49, 0.1)',
                    color: 'var(--color-danger)',
                  }}
                >
                  Error: {(mutation.error as Error)?.message || 'Failed to update products'}
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div
          className="sticky bottom-0 flex items-center justify-end gap-3 px-6 py-4 border-t"
          style={{
            backgroundColor: 'var(--color-surface)',
            borderColor: 'var(--color-border)',
          }}
        >
          {view === 'edit' ? (
            <>
              <button
                onClick={onClose}
                className="rounded-md px-4 py-2 text-sm font-medium"
                style={{
                  color: 'var(--color-text-secondary)',
                  border: '1px solid var(--color-border)',
                }}
              >
                Cancel
              </button>
              <button
                onClick={() => setView('preview')}
                disabled={!hasChanges || needsContentType}
                className="rounded-md px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
                style={{ backgroundColor: 'var(--color-accent)' }}
              >
                Preview Changes
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => setView('edit')}
                className="rounded-md px-4 py-2 text-sm font-medium"
                style={{
                  color: 'var(--color-text-secondary)',
                  border: '1px solid var(--color-border)',
                }}
              >
                Back
              </button>
              <button
                onClick={() => mutation.mutate()}
                disabled={mutation.isPending}
                className="rounded-md px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
                style={{ backgroundColor: 'var(--color-accent)' }}
              >
                {mutation.isPending ? 'Applying...' : 'Apply Changes'}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
