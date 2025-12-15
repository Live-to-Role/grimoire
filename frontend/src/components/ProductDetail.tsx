import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  X,
  FileText,
  Book,
  Calendar,
  Users,
  Clock,
  ExternalLink,
  Eye,
  Download,
  Wand2,
  Loader2,
  Sparkles,
  Edit3,
  Save,
} from 'lucide-react';
import apiClient from '../api/client';
import type { Product } from '../types/product';
import { getProductText } from '../api/search';
import { getCoverUrl, updateProduct } from '../api/products';
import { PDFViewer } from './PDFViewer';
import { useFocusTrap } from '../hooks/useFocusTrap';

interface ProductDetailProps {
  product: Product;
  onClose: () => void;
}

export function ProductDetail({ product, onClose }: ProductDetailProps) {
  const queryClient = useQueryClient();
  const focusTrapRef = useFocusTrap<HTMLDivElement>({ enabled: true, restoreFocus: true });
  const [activeTab, setActiveTab] = useState<'info' | 'text' | 'extract' | 'export'>('info');
  const [textContent, setTextContent] = useState<string | null>(null);
  const [textLoading, setTextLoading] = useState(false);
  const [textError, setTextError] = useState<string | null>(null);
  const [showPdfViewer, setShowPdfViewer] = useState(false);
  const [extractedContent, setExtractedContent] = useState<Record<string, unknown[]> | null>(null);
  const [localProduct, setLocalProduct] = useState(product);
  const [isEditing, setIsEditing] = useState(false);
  const [editForm, setEditForm] = useState({
    title: product.title || '',
    publisher: product.publisher || '',
    game_system: product.game_system || '',
    product_type: product.product_type || '',
    publication_year: product.publication_year?.toString() || '',
    level_range_min: product.level_range_min?.toString() || '',
    level_range_max: product.level_range_max?.toString() || '',
  });

  const extractTextMutation = useMutation({
    mutationFn: async () => {
      const res = await apiClient.post(`/products/${product.id}/extract`, {}, {
        params: { use_marker: false },
      });
      return res.data;
    },
    onSuccess: () => {
      setLocalProduct(prev => ({
        ...prev,
        processing_status: { ...prev.processing_status, text_extracted: true },
      }));
      setTextError(null);
      queryClient.invalidateQueries({ queryKey: ['products'] });
      loadText();
    },
  });

  const identifyMutation = useMutation({
    mutationFn: async () => {
      const res = await apiClient.post(`/ai/identify/${product.id}`, {
        provider: 'ollama',
        apply: true,
      });
      return res.data;
    },
    onSuccess: (data) => {
      if (data.applied && data.identification) {
        setLocalProduct(prev => ({
          ...prev,
          title: data.identification.title || prev.title,
          publisher: data.identification.publisher || prev.publisher,
          game_system: data.identification.game_system || prev.game_system,
          product_type: data.identification.product_type || prev.product_type,
          processing_status: { ...prev.processing_status, ai_identified: true },
        }));
        queryClient.invalidateQueries({ queryKey: ['products'] });
      }
    },
  });

  const extractMutation = useMutation({
    mutationFn: async (types: { monsters?: boolean; spells?: boolean; items?: boolean; npcs?: boolean }) => {
      const res = await apiClient.post(`/structured/all/${product.id}`, {}, {
        params: types,
      });
      return res.data;
    },
    onSuccess: (data) => {
      setExtractedContent(data);
    },
  });

  const exportFoundryMutation = useMutation({
    mutationFn: async () => {
      const res = await apiClient.post(`/export/foundry/${product.id}`, {});
      return res.data;
    },
    onSuccess: (data) => {
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${product.title || 'export'}-foundry.json`;
      a.click();
      URL.revokeObjectURL(url);
    },
  });

  const exportObsidianMutation = useMutation({
    mutationFn: async () => {
      const res = await apiClient.post(`/export/obsidian/${product.id}`, {});
      return res.data;
    },
    onSuccess: (data) => {
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${product.title || 'export'}-obsidian.json`;
      a.click();
      URL.revokeObjectURL(url);
    },
  });

  const updateMutation = useMutation({
    mutationFn: async (data: Parameters<typeof updateProduct>[1]) => {
      return updateProduct(product.id, data);
    },
    onSuccess: (updatedProduct) => {
      setLocalProduct(prev => ({ ...prev, ...updatedProduct }));
      setIsEditing(false);
      queryClient.invalidateQueries({ queryKey: ['products'] });
    },
  });

  const handleSaveEdit = () => {
    const data: Record<string, unknown> = {};
    if (editForm.title) data.title = editForm.title;
    if (editForm.publisher) data.publisher = editForm.publisher;
    if (editForm.game_system) data.game_system = editForm.game_system;
    if (editForm.product_type) data.product_type = editForm.product_type;
    if (editForm.publication_year) data.publication_year = parseInt(editForm.publication_year);
    if (editForm.level_range_min) data.level_range_min = parseInt(editForm.level_range_min);
    if (editForm.level_range_max) data.level_range_max = parseInt(editForm.level_range_max);
    updateMutation.mutate(data);
  };

  const handleCancelEdit = () => {
    setEditForm({
      title: localProduct.title || '',
      publisher: localProduct.publisher || '',
      game_system: localProduct.game_system || '',
      product_type: localProduct.product_type || '',
      publication_year: localProduct.publication_year?.toString() || '',
      level_range_min: localProduct.level_range_min?.toString() || '',
      level_range_max: localProduct.level_range_max?.toString() || '',
    });
    setIsEditing(false);
  };

  const loadText = async () => {
    if (textContent) return;
    setTextLoading(true);
    setTextError(null);
    try {
      const data = await getProductText(product.id);
      setTextContent(data.markdown);
    } catch {
      setTextError('Text not available for this product.');
    } finally {
      setTextLoading(false);
    }
  };

  const handleTabChange = (tab: 'info' | 'text' | 'extract' | 'export') => {
    setActiveTab(tab);
    if (tab === 'text') {
      loadText();
    }
  };

  const openPdf = () => {
    window.open(`/api/v1/products/${product.id}/pdf`, '_blank');
  };

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="product-detail-title"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div 
        ref={focusTrapRef}
        className="flex h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl"
      >
        <header className="flex items-center justify-between border-b border-neutral-200 px-6 py-4">
          <h2 id="product-detail-title" className="text-xl font-semibold text-neutral-900 truncate">{product.title}</h2>
          <button
            onClick={onClose}
            aria-label="Close product details"
            className="rounded-lg p-2 text-neutral-500 hover:bg-neutral-100"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </header>

        <div className="flex border-b border-neutral-200" role="tablist" aria-label="Product information tabs">
          <button
            onClick={() => handleTabChange('info')}
            role="tab"
            aria-selected={activeTab === 'info'}
            aria-controls="panel-info"
            id="tab-info"
            className={`px-6 py-3 text-sm font-medium ${
              activeTab === 'info'
                ? 'border-b-2 border-purple-600 text-purple-600'
                : 'text-neutral-600 hover:text-neutral-900'
            }`}
          >
            Details
          </button>
          <button
            onClick={() => handleTabChange('text')}
            role="tab"
            aria-selected={activeTab === 'text'}
            aria-controls="panel-text"
            id="tab-text"
            className={`px-6 py-3 text-sm font-medium ${
              activeTab === 'text'
                ? 'border-b-2 border-purple-600 text-purple-600'
                : 'text-neutral-600 hover:text-neutral-900'
            }`}
          >
            Extracted Text
          </button>
          <button
            onClick={() => handleTabChange('extract')}
            role="tab"
            aria-selected={activeTab === 'extract'}
            aria-controls="panel-extract"
            id="tab-extract"
            className={`px-6 py-3 text-sm font-medium ${
              activeTab === 'extract'
                ? 'border-b-2 border-purple-600 text-purple-600'
                : 'text-neutral-600 hover:text-neutral-900'
            }`}
          >
            Extract Content
          </button>
          <button
            onClick={() => handleTabChange('export')}
            role="tab"
            aria-selected={activeTab === 'export'}
            aria-controls="panel-export"
            id="tab-export"
            className={`px-6 py-3 text-sm font-medium ${
              activeTab === 'export'
                ? 'border-b-2 border-purple-600 text-purple-600'
                : 'text-neutral-600 hover:text-neutral-900'
            }`}
          >
            Export
          </button>
        </div>

        <div className="flex-1 overflow-auto">
          {activeTab === 'info' ? (
            <div
              role="tabpanel"
              id="panel-info"
              aria-labelledby="tab-info"
              className="flex flex-col gap-6 p-6 md:flex-row"
            >
              <div className="shrink-0">
                <img
                  src={getCoverUrl(product.id)}
                  alt={product.title || 'Product cover'}
                  className="h-64 w-44 rounded-lg object-cover shadow-lg"
                  onError={(e) => {
                    (e.target as HTMLImageElement).src = '/placeholder-cover.png';
                  }}
                />
              </div>

              <div className="flex-1 space-y-4">
                {isEditing ? (
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm font-medium text-neutral-700">Title</label>
                      <input
                        type="text"
                        value={editForm.title}
                        onChange={(e) => setEditForm({ ...editForm, title: e.target.value })}
                        className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-sm font-medium text-neutral-700">Game System</label>
                        <input
                          type="text"
                          value={editForm.game_system}
                          onChange={(e) => setEditForm({ ...editForm, game_system: e.target.value })}
                          className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-neutral-700">Product Type</label>
                        <input
                          type="text"
                          value={editForm.product_type}
                          onChange={(e) => setEditForm({ ...editForm, product_type: e.target.value })}
                          className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                        />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-sm font-medium text-neutral-700">Publisher</label>
                        <input
                          type="text"
                          value={editForm.publisher}
                          onChange={(e) => setEditForm({ ...editForm, publisher: e.target.value })}
                          className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-neutral-700">Year</label>
                        <input
                          type="number"
                          value={editForm.publication_year}
                          onChange={(e) => setEditForm({ ...editForm, publication_year: e.target.value })}
                          className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                        />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-sm font-medium text-neutral-700">Min Level</label>
                        <input
                          type="number"
                          value={editForm.level_range_min}
                          onChange={(e) => setEditForm({ ...editForm, level_range_min: e.target.value })}
                          className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-neutral-700">Max Level</label>
                        <input
                          type="number"
                          value={editForm.level_range_max}
                          onChange={(e) => setEditForm({ ...editForm, level_range_max: e.target.value })}
                          className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                        />
                      </div>
                    </div>
                    <div className="flex gap-3 pt-4">
                      <button
                        onClick={handleSaveEdit}
                        disabled={updateMutation.isPending}
                        className="inline-flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
                      >
                        {updateMutation.isPending ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Save className="h-4 w-4" />
                        )}
                        Save Changes
                      </button>
                      <button
                        onClick={handleCancelEdit}
                        disabled={updateMutation.isPending}
                        className="inline-flex items-center gap-2 rounded-lg border border-neutral-300 bg-white px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="grid grid-cols-2 gap-4">
                      {localProduct.game_system && (
                        <div className="flex items-center gap-2">
                          <Book className="h-4 w-4 text-neutral-400" />
                          <div>
                            <p className="text-xs text-neutral-500">Game System</p>
                            <p className="font-medium">{localProduct.game_system}</p>
                          </div>
                        </div>
                      )}

                      {localProduct.product_type && (
                        <div className="flex items-center gap-2">
                          <FileText className="h-4 w-4 text-neutral-400" />
                          <div>
                            <p className="text-xs text-neutral-500">Type</p>
                            <p className="font-medium">{localProduct.product_type}</p>
                          </div>
                        </div>
                      )}

                      {localProduct.publisher && (
                        <div className="flex items-center gap-2">
                          <Users className="h-4 w-4 text-neutral-400" />
                          <div>
                            <p className="text-xs text-neutral-500">Publisher</p>
                            <p className="font-medium">{localProduct.publisher}</p>
                          </div>
                        </div>
                      )}

                      {localProduct.publication_year && (
                        <div className="flex items-center gap-2">
                          <Calendar className="h-4 w-4 text-neutral-400" />
                          <div>
                            <p className="text-xs text-neutral-500">Year</p>
                            <p className="font-medium">{localProduct.publication_year}</p>
                          </div>
                        </div>
                      )}

                      {localProduct.page_count && (
                        <div className="flex items-center gap-2">
                          <FileText className="h-4 w-4 text-neutral-400" />
                          <div>
                            <p className="text-xs text-neutral-500">Pages</p>
                            <p className="font-medium">{localProduct.page_count}</p>
                          </div>
                        </div>
                      )}

                      {(localProduct.level_range_min || localProduct.level_range_max) && (
                        <div className="flex items-center gap-2">
                          <Clock className="h-4 w-4 text-neutral-400" />
                          <div>
                            <p className="text-xs text-neutral-500">Level Range</p>
                            <p className="font-medium">
                              {localProduct.level_range_min || '?'} - {localProduct.level_range_max || '?'}
                            </p>
                          </div>
                        </div>
                      )}
                    </div>

                    {localProduct.tags && localProduct.tags.length > 0 && (
                      <div>
                        <p className="text-xs text-neutral-500 mb-2">Tags</p>
                        <div className="flex flex-wrap gap-2">
                          {localProduct.tags.map((tag) => (
                            <span
                              key={tag.id}
                              className="rounded-full px-3 py-1 text-xs font-medium"
                              style={{
                                backgroundColor: tag.color ? `${tag.color}20` : '#e5e7eb',
                                color: tag.color || '#374151',
                              }}
                            >
                              {tag.name}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="flex gap-3 pt-4">
                      <button
                        onClick={() => setShowPdfViewer(true)}
                        className="inline-flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700"
                      >
                        <Eye className="h-4 w-4" />
                        View PDF
                      </button>
                      <button
                        onClick={openPdf}
                        className="inline-flex items-center gap-2 rounded-lg border border-neutral-300 bg-white px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
                      >
                        <ExternalLink className="h-4 w-4" />
                        Open in New Tab
                      </button>
                      <button
                        onClick={() => setIsEditing(true)}
                        className="inline-flex items-center gap-2 rounded-lg border border-neutral-300 bg-white px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
                      >
                        <Edit3 className="h-4 w-4" />
                        Edit
                      </button>
                    </div>
                  </>
                )}
              </div>
            </div>
          ) : activeTab === 'text' ? (
            <div 
              role="tabpanel"
              id="panel-text"
              aria-labelledby="tab-text"
              className="p-6"
            >
              {/* Processing Status Bar */}
              <div className="mb-4 flex items-center gap-4 rounded-lg border border-neutral-200 p-3">
                <div className="flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${localProduct.processing_status?.text_extracted ? 'bg-green-500' : 'bg-neutral-300'}`} />
                  <span className="text-sm text-neutral-600">Text Extracted</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${localProduct.processing_status?.ai_identified ? 'bg-green-500' : 'bg-neutral-300'}`} />
                  <span className="text-sm text-neutral-600">AI Identified</span>
                </div>
                <div className="flex-1" />
                {!localProduct.processing_status?.text_extracted && (
                  <button
                    onClick={() => extractTextMutation.mutate()}
                    disabled={extractTextMutation.isPending}
                    className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                  >
                    {extractTextMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <FileText className="h-4 w-4" />
                    )}
                    Extract Text
                  </button>
                )}
                {localProduct.processing_status?.text_extracted && !localProduct.processing_status?.ai_identified && (
                  <button
                    onClick={() => identifyMutation.mutate()}
                    disabled={identifyMutation.isPending}
                    className="inline-flex items-center gap-2 rounded-lg bg-purple-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
                  >
                    {identifyMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Sparkles className="h-4 w-4" />
                    )}
                    AI Identify
                  </button>
                )}
              </div>

              {/* Extraction in progress */}
              {extractTextMutation.isPending && (
                <div className="mb-4 rounded-lg bg-blue-50 p-4 text-blue-800">
                  <div className="flex items-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    <span>Extracting text from PDF... This may take a moment.</span>
                  </div>
                </div>
              )}

              {/* Identification result */}
              {identifyMutation.isSuccess && identifyMutation.data?.applied && (
                <div className="mb-4 rounded-lg bg-green-50 p-4 text-green-800">
                  <p className="font-medium">AI Identification Complete!</p>
                  <p className="text-sm mt-1">
                    Identified as: {identifyMutation.data.identification?.title || 'Unknown'}
                    {identifyMutation.data.identification?.game_system && ` (${identifyMutation.data.identification.game_system})`}
                  </p>
                </div>
              )}

              {textLoading ? (
                <div className="flex items-center justify-center py-12">
                  <div className="h-8 w-8 animate-spin rounded-full border-4 border-purple-200 border-t-purple-600" />
                </div>
              ) : textError && !extractTextMutation.isPending ? (
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-center">
                  <p className="text-amber-700 mb-3">{textError}</p>
                  {!localProduct.processing_status?.text_extracted && (
                    <button
                      onClick={() => extractTextMutation.mutate()}
                      disabled={extractTextMutation.isPending}
                      className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                    >
                      {extractTextMutation.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <FileText className="h-4 w-4" />
                      )}
                      Extract Text Now
                    </button>
                  )}
                </div>
              ) : textContent ? (
                <div className="prose prose-sm max-w-none">
                  <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-neutral-700">
                    {textContent}
                  </pre>
                </div>
              ) : null}
            </div>
          ) : activeTab === 'extract' ? (
            <div
              role="tabpanel"
              id="panel-extract"
              aria-labelledby="tab-extract"
              className="p-6"
            >
              <div className="mb-6">
                <h3 className="text-lg font-semibold text-neutral-900 mb-2">Extract Structured Content</h3>
                <p className="text-sm text-neutral-500 mb-4">
                  Use AI to extract monsters, spells, magic items, and NPCs from this product.
                </p>
                <button
                  onClick={() => extractMutation.mutate({ monsters: true, spells: true, items: true, npcs: true })}
                  disabled={extractMutation.isPending || !product.processing_status?.text_extracted}
                  className="inline-flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
                >
                  {extractMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Wand2 className="h-4 w-4" />
                  )}
                  Extract All Content
                </button>
                {!product.processing_status?.text_extracted && (
                  <p className="mt-2 text-sm text-amber-600">
                    Text must be extracted first. Add this product to the processing queue.
                  </p>
                )}
              </div>

              {extractMutation.isError && (
                <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-4 text-red-700">
                  Extraction failed. Make sure an AI provider is configured in Settings.
                </div>
              )}

              {extractedContent && (
                <div className="space-y-4">
                  {extractedContent.monsters && (extractedContent.monsters as unknown[]).length > 0 && (
                    <div className="rounded-lg border border-neutral-200 p-4">
                      <h4 className="font-medium text-neutral-900 mb-2">
                        Monsters ({(extractedContent.monsters as unknown[]).length})
                      </h4>
                      <div className="space-y-2">
                        {(extractedContent.monsters as Array<{ name: string; cr?: string }>).slice(0, 5).map((m, i) => (
                          <div key={i} className="text-sm text-neutral-600">
                            {m.name} {m.cr && <span className="text-neutral-400">CR {m.cr}</span>}
                          </div>
                        ))}
                        {(extractedContent.monsters as unknown[]).length > 5 && (
                          <p className="text-xs text-neutral-400">...and {(extractedContent.monsters as unknown[]).length - 5} more</p>
                        )}
                      </div>
                    </div>
                  )}

                  {extractedContent.spells && (extractedContent.spells as unknown[]).length > 0 && (
                    <div className="rounded-lg border border-neutral-200 p-4">
                      <h4 className="font-medium text-neutral-900 mb-2">
                        Spells ({(extractedContent.spells as unknown[]).length})
                      </h4>
                      <div className="space-y-2">
                        {(extractedContent.spells as Array<{ name: string; level?: number }>).slice(0, 5).map((s, i) => (
                          <div key={i} className="text-sm text-neutral-600">
                            {s.name} {s.level !== undefined && <span className="text-neutral-400">Level {s.level}</span>}
                          </div>
                        ))}
                        {(extractedContent.spells as unknown[]).length > 5 && (
                          <p className="text-xs text-neutral-400">...and {(extractedContent.spells as unknown[]).length - 5} more</p>
                        )}
                      </div>
                    </div>
                  )}

                  {extractedContent.magic_items && (extractedContent.magic_items as unknown[]).length > 0 && (
                    <div className="rounded-lg border border-neutral-200 p-4">
                      <h4 className="font-medium text-neutral-900 mb-2">
                        Magic Items ({(extractedContent.magic_items as unknown[]).length})
                      </h4>
                      <div className="space-y-2">
                        {(extractedContent.magic_items as Array<{ name: string; rarity?: string }>).slice(0, 5).map((item, i) => (
                          <div key={i} className="text-sm text-neutral-600">
                            {item.name} {item.rarity && <span className="text-neutral-400">({item.rarity})</span>}
                          </div>
                        ))}
                        {(extractedContent.magic_items as unknown[]).length > 5 && (
                          <p className="text-xs text-neutral-400">...and {(extractedContent.magic_items as unknown[]).length - 5} more</p>
                        )}
                      </div>
                    </div>
                  )}

                  {extractedContent.npcs && (extractedContent.npcs as unknown[]).length > 0 && (
                    <div className="rounded-lg border border-neutral-200 p-4">
                      <h4 className="font-medium text-neutral-900 mb-2">
                        NPCs ({(extractedContent.npcs as unknown[]).length})
                      </h4>
                      <div className="space-y-2">
                        {(extractedContent.npcs as Array<{ name: string; role?: string }>).slice(0, 5).map((npc, i) => (
                          <div key={i} className="text-sm text-neutral-600">
                            {npc.name} {npc.role && <span className="text-neutral-400">- {npc.role}</span>}
                          </div>
                        ))}
                        {(extractedContent.npcs as unknown[]).length > 5 && (
                          <p className="text-xs text-neutral-400">...and {(extractedContent.npcs as unknown[]).length - 5} more</p>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          ) : activeTab === 'export' ? (
            <div
              role="tabpanel"
              id="panel-export"
              aria-labelledby="tab-export"
              className="p-6"
            >
              <h3 className="text-lg font-semibold text-neutral-900 mb-2">Export Content</h3>
              <p className="text-sm text-neutral-500 mb-6">
                Export extracted content to various formats for use in other tools.
              </p>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="rounded-lg border border-neutral-200 p-4">
                  <h4 className="font-medium text-neutral-900 mb-1">Foundry VTT</h4>
                  <p className="text-sm text-neutral-500 mb-3">
                    Export monsters, spells, and items to Foundry VTT compendium format.
                  </p>
                  <button
                    onClick={() => exportFoundryMutation.mutate()}
                    disabled={exportFoundryMutation.isPending || !product.processing_status?.text_extracted}
                    className="inline-flex items-center gap-2 rounded-lg bg-orange-600 px-4 py-2 text-sm font-medium text-white hover:bg-orange-700 disabled:opacity-50"
                  >
                    {exportFoundryMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Download className="h-4 w-4" />
                    )}
                    Export to Foundry
                  </button>
                </div>

                <div className="rounded-lg border border-neutral-200 p-4">
                  <h4 className="font-medium text-neutral-900 mb-1">Obsidian Markdown</h4>
                  <p className="text-sm text-neutral-500 mb-3">
                    Export content as Obsidian-compatible markdown with YAML frontmatter.
                  </p>
                  <button
                    onClick={() => exportObsidianMutation.mutate()}
                    disabled={exportObsidianMutation.isPending || !product.processing_status?.text_extracted}
                    className="inline-flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
                  >
                    {exportObsidianMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Download className="h-4 w-4" />
                    )}
                    Export to Obsidian
                  </button>
                </div>
              </div>

              {!product.processing_status?.text_extracted && (
                <p className="mt-4 text-sm text-amber-600">
                  Text must be extracted first before exporting. Add this product to the processing queue.
                </p>
              )}

              {(exportFoundryMutation.isError || exportObsidianMutation.isError) && (
                <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-4 text-red-700">
                  Export failed. Make sure an AI provider is configured in Settings.
                </div>
              )}
            </div>
          ) : null}
        </div>
      </div>

      {showPdfViewer && (
        <PDFViewer
          fileUrl={`/api/v1/products/${product.id}/pdf`}
          fileName={product.file_name || product.title || 'document.pdf'}
          onClose={() => setShowPdfViewer(false)}
        />
      )}
    </div>
  );
}
