import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { X, Loader2, Trash2 } from 'lucide-react';
import { createTag, updateTag, deleteTag, type Tag, type TagCreate, type TagUpdate } from '../api/tags';
import { useFocusTrap } from '../hooks/useFocusTrap';

interface TagManagerProps {
  tag?: Tag | null;
  onClose: () => void;
}

const COLOR_PRESETS = [
  '#ef4444', // red
  '#f97316', // orange
  '#eab308', // yellow
  '#22c55e', // green
  '#14b8a6', // teal
  '#3b82f6', // blue
  '#8b5cf6', // violet
  '#ec4899', // pink
  '#6b7280', // gray
  '#000000', // black
];

const CATEGORY_OPTIONS = [
  { value: '', label: 'No Category' },
  { value: 'genre', label: 'Genre' },
  { value: 'theme', label: 'Theme' },
  { value: 'setting', label: 'Setting' },
  { value: 'mechanic', label: 'Mechanic' },
  { value: 'content', label: 'Content Warning' },
  { value: 'status', label: 'Status' },
  { value: 'custom', label: 'Custom' },
];

export function TagManager({ tag, onClose }: TagManagerProps) {
  const queryClient = useQueryClient();
  const focusTrapRef = useFocusTrap<HTMLDivElement>({ enabled: true, restoreFocus: true });
  const isEditing = !!tag;

  const [form, setForm] = useState({
    name: tag?.name || '',
    category: tag?.category || '',
    color: tag?.color || '#3b82f6',
  });
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: (data: TagCreate) => createTag(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tags'] });
      onClose();
    },
    onError: (err: Error) => {
      setError(err.message || 'Failed to create tag');
    },
  });

  const updateMutation = useMutation({
    mutationFn: (data: TagUpdate) => updateTag(tag!.id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tags'] });
      onClose();
    },
    onError: (err: Error) => {
      setError(err.message || 'Failed to update tag');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteTag(tag!.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tags'] });
      onClose();
    },
    onError: (err: Error) => {
      setError(err.message || 'Failed to delete tag');
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!form.name.trim()) {
      setError('Name is required');
      return;
    }

    const data = {
      name: form.name.trim(),
      category: form.category || null,
      color: form.color || null,
    };

    if (isEditing) {
      updateMutation.mutate(data);
    } else {
      createMutation.mutate(data);
    }
  };

  const handleDelete = () => {
    deleteMutation.mutate();
  };

  const isPending = createMutation.isPending || updateMutation.isPending || deleteMutation.isPending;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="tag-manager-title"
      onClick={(e) => e.target === e.currentTarget && !isPending && onClose()}
    >
      <div
        ref={focusTrapRef}
        className="w-full max-w-md rounded-xl bg-white shadow-2xl"
      >
        <header className="flex items-center justify-between border-b border-neutral-200 px-6 py-4">
          <h2 id="tag-manager-title" className="text-lg font-semibold text-neutral-900">
            {isEditing ? 'Edit Tag' : 'Create Tag'}
          </h2>
          <button
            onClick={onClose}
            disabled={isPending}
            aria-label="Close"
            className="rounded-lg p-2 text-neutral-500 hover:bg-neutral-100 disabled:opacity-50"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </header>

        {showDeleteConfirm ? (
          <div className="p-6">
            <p className="text-sm text-neutral-700">
              Are you sure you want to delete the tag <strong>{tag?.name}</strong>? 
              This will remove the tag from all products.
            </p>
            <div className="mt-4 flex gap-3">
              <button
                onClick={handleDelete}
                disabled={isPending}
                className="flex-1 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                {deleteMutation.isPending ? (
                  <Loader2 className="mx-auto h-4 w-4 animate-spin" />
                ) : (
                  'Delete'
                )}
              </button>
              <button
                onClick={() => setShowDeleteConfirm(false)}
                disabled={isPending}
                className="flex-1 rounded-lg border border-neutral-300 bg-white px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="p-6">
            {error && (
              <div className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
                {error}
              </div>
            )}

            <div className="space-y-4">
              <div>
                <label htmlFor="tag-name" className="block text-sm font-medium text-neutral-700">
                  Name <span className="text-red-500">*</span>
                </label>
                <input
                  id="tag-name"
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="e.g., Horror, Solo-friendly"
                  className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  autoFocus
                />
              </div>

              <div>
                <label htmlFor="tag-category" className="block text-sm font-medium text-neutral-700">
                  Category
                </label>
                <select
                  id="tag-category"
                  value={form.category}
                  onChange={(e) => setForm({ ...form, category: e.target.value })}
                  className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                >
                  {CATEGORY_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-neutral-700">Color</label>
                <div className="mt-2 flex flex-wrap gap-2">
                  {COLOR_PRESETS.map((color) => (
                    <button
                      key={color}
                      type="button"
                      onClick={() => setForm({ ...form, color })}
                      className={`h-8 w-8 rounded-full border-2 transition-transform hover:scale-110 ${
                        form.color === color ? 'border-neutral-900 ring-2 ring-neutral-400' : 'border-transparent'
                      }`}
                      style={{ backgroundColor: color }}
                      aria-label={`Select color ${color}`}
                    />
                  ))}
                </div>
              </div>
            </div>

            <div className="mt-6 flex gap-3">
              <button
                type="submit"
                disabled={isPending}
                className="flex-1 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
              >
                {(createMutation.isPending || updateMutation.isPending) ? (
                  <Loader2 className="mx-auto h-4 w-4 animate-spin" />
                ) : isEditing ? (
                  'Save Changes'
                ) : (
                  'Create Tag'
                )}
              </button>
              {isEditing && (
                <button
                  type="button"
                  onClick={() => setShowDeleteConfirm(true)}
                  disabled={isPending}
                  className="rounded-lg border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
                  aria-label="Delete tag"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              )}
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
