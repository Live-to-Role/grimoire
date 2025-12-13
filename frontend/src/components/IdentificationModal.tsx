import { useState } from 'react';
import { X, Check, AlertTriangle, Sparkles, Database, Edit3 } from 'lucide-react';

interface IdentificationData {
  source: string;
  confidence: number;
  needs_confirmation: boolean;
  title: string | null;
  publisher: string | null;
  game_system: string | null;
  product_type: string | null;
  publication_year: number | null;
  level_range_min: number | null;
  level_range_max: number | null;
  description: string | null;
  codex_product_id: string | null;
  suggestions?: Array<{
    id: string;
    title: string;
    publisher: string | null;
    game_system: string | null;
  }>;
}

interface IdentificationModalProps {
  productId: number;
  productTitle: string;
  identification: IdentificationData;
  onConfirm: (data: Record<string, unknown>) => void;
  onReject: () => void;
  onClose: () => void;
}

export function IdentificationModal({
  productTitle,
  identification,
  onConfirm,
  onReject,
  onClose,
}: IdentificationModalProps) {
  const [editedData, setEditedData] = useState({
    title: identification.title || '',
    publisher: identification.publisher || '',
    game_system: identification.game_system || '',
    product_type: identification.product_type || '',
    publication_year: identification.publication_year?.toString() || '',
    level_range_min: identification.level_range_min?.toString() || '',
    level_range_max: identification.level_range_max?.toString() || '',
  });

  const [isEditing, setIsEditing] = useState(false);

  const handleConfirm = () => {
    const data: Record<string, unknown> = {
      title: editedData.title || null,
      publisher: editedData.publisher || null,
      game_system: editedData.game_system || null,
      product_type: editedData.product_type || null,
      publication_year: editedData.publication_year ? parseInt(editedData.publication_year) : null,
      level_range_min: editedData.level_range_min ? parseInt(editedData.level_range_min) : null,
      level_range_max: editedData.level_range_max ? parseInt(editedData.level_range_max) : null,
    };
    onConfirm(data);
  };

  const selectSuggestion = (suggestion: NonNullable<IdentificationData['suggestions']>[number]) => {
    setEditedData({
      ...editedData,
      title: suggestion.title,
      publisher: suggestion.publisher || '',
      game_system: suggestion.game_system || '',
    });
  };

  const getSourceIcon = () => {
    switch (identification.source) {
      case 'codex_hash':
      case 'codex_title':
        return <Database className="h-5 w-5 text-blue-500" />;
      case 'ai':
        return <Sparkles className="h-5 w-5 text-purple-500" />;
      default:
        return <Edit3 className="h-5 w-5 text-neutral-500" />;
    }
  };

  const getSourceLabel = () => {
    switch (identification.source) {
      case 'codex_hash':
        return 'Codex (exact match)';
      case 'codex_title':
        return 'Codex (title match)';
      case 'ai':
        return 'AI Identification';
      default:
        return 'Manual';
    }
  };

  const confidenceColor = identification.confidence >= 0.9
    ? 'text-green-600'
    : identification.confidence >= 0.7
    ? 'text-amber-600'
    : 'text-red-600';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-lg rounded-xl bg-white shadow-2xl">
        <header className="flex items-center justify-between border-b border-neutral-200 px-6 py-4">
          <div className="flex items-center gap-3">
            {getSourceIcon()}
            <div>
              <h2 className="text-lg font-semibold text-neutral-900">Confirm Identification</h2>
              <p className="text-sm text-neutral-500">{getSourceLabel()}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-neutral-500 hover:bg-neutral-100"
          >
            <X className="h-5 w-5" />
          </button>
        </header>

        <div className="p-6">
          {identification.needs_confirmation && (
            <div className="mb-4 flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
              <AlertTriangle className="h-5 w-5 shrink-0 text-amber-500" />
              <div className="text-sm text-amber-700">
                <p className="font-medium">Confirmation Required</p>
                <p>
                  Confidence: <span className={confidenceColor}>{Math.round(identification.confidence * 100)}%</span>.
                  Please verify this identification is correct.
                </p>
              </div>
            </div>
          )}

          <div className="mb-4">
            <p className="text-sm text-neutral-500">Original filename:</p>
            <p className="font-medium text-neutral-700">{productTitle}</p>
          </div>

          {isEditing ? (
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-neutral-700">Title</label>
                <input
                  type="text"
                  value={editedData.title}
                  onChange={(e) => setEditedData({ ...editedData, title: e.target.value })}
                  className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-neutral-700">Publisher</label>
                  <input
                    type="text"
                    value={editedData.publisher}
                    onChange={(e) => setEditedData({ ...editedData, publisher: e.target.value })}
                    className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-neutral-700">Game System</label>
                  <input
                    type="text"
                    value={editedData.game_system}
                    onChange={(e) => setEditedData({ ...editedData, game_system: e.target.value })}
                    className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-neutral-700">Product Type</label>
                  <input
                    type="text"
                    value={editedData.product_type}
                    onChange={(e) => setEditedData({ ...editedData, product_type: e.target.value })}
                    className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-neutral-700">Year</label>
                  <input
                    type="number"
                    value={editedData.publication_year}
                    onChange={(e) => setEditedData({ ...editedData, publication_year: e.target.value })}
                    className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-neutral-700">Min Level</label>
                  <input
                    type="number"
                    value={editedData.level_range_min}
                    onChange={(e) => setEditedData({ ...editedData, level_range_min: e.target.value })}
                    className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-neutral-700">Max Level</label>
                  <input
                    type="number"
                    value={editedData.level_range_max}
                    onChange={(e) => setEditedData({ ...editedData, level_range_max: e.target.value })}
                    className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  />
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-2 rounded-lg border border-neutral-200 bg-neutral-50 p-4">
              <div className="flex justify-between">
                <span className="text-sm text-neutral-500">Title</span>
                <span className="font-medium">{editedData.title || '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-neutral-500">Publisher</span>
                <span className="font-medium">{editedData.publisher || '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-neutral-500">Game System</span>
                <span className="font-medium">{editedData.game_system || '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm text-neutral-500">Type</span>
                <span className="font-medium">{editedData.product_type || '—'}</span>
              </div>
              {editedData.publication_year && (
                <div className="flex justify-between">
                  <span className="text-sm text-neutral-500">Year</span>
                  <span className="font-medium">{editedData.publication_year}</span>
                </div>
              )}
              {(editedData.level_range_min || editedData.level_range_max) && (
                <div className="flex justify-between">
                  <span className="text-sm text-neutral-500">Level Range</span>
                  <span className="font-medium">
                    {editedData.level_range_min || '?'} - {editedData.level_range_max || '?'}
                  </span>
                </div>
              )}
            </div>
          )}

          {identification.suggestions && identification.suggestions.length > 0 && (
            <div className="mt-4">
              <p className="mb-2 text-sm font-medium text-neutral-700">Alternative matches:</p>
              <div className="space-y-2">
                {identification.suggestions.map((suggestion) => (
                  <button
                    key={suggestion.id}
                    onClick={() => selectSuggestion(suggestion)}
                    className="w-full rounded-lg border border-neutral-200 p-3 text-left hover:border-purple-300 hover:bg-purple-50"
                  >
                    <p className="font-medium">{suggestion.title}</p>
                    <p className="text-sm text-neutral-500">
                      {suggestion.publisher} • {suggestion.game_system}
                    </p>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        <footer className="flex items-center justify-between border-t border-neutral-200 px-6 py-4">
          <button
            onClick={() => setIsEditing(!isEditing)}
            className="text-sm text-purple-600 hover:text-purple-700"
          >
            {isEditing ? 'View Summary' : 'Edit Details'}
          </button>
          <div className="flex gap-3">
            <button
              onClick={onReject}
              className="rounded-lg border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
            >
              Reject
            </button>
            <button
              onClick={handleConfirm}
              className="inline-flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700"
            >
              <Check className="h-4 w-4" />
              Confirm & Apply
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
