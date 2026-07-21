import { useState, useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
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
  FolderPlus,
  ChevronDown,
  Play,
  CheckCircle,
  Bookmark,
  Star,
  Plus,
  Upload,
  Database,
  Tag,
  Check,
  FolderOpen,
  Skull,
} from 'lucide-react';
import apiClient from '../api/client';
import type { Product, RunNote } from '../types/product';
import { getProductText } from '../api/search';
import { getCoverUrl, updateProduct, contributeProduct, getContributionStatus, updateProductAndContribute } from '../api/products';
import { getCollections, addProductToCollection, removeProductFromCollection, type Collection } from '../api/collections';
import { getTags, addTagToProduct, removeTagFromProduct, type Tag as TagType } from '../api/tags';
import { PDFViewer } from './PDFViewer';
import { ComboboxWithAdd } from './ComboboxWithAdd';
import { useFocusTrap } from '../hooks/useFocusTrap';
import { queueExtraction } from '../api/monsters';

interface LibraryStats {
  total_products: number;
  total_pages: number;
  total_size_bytes: number;
  by_system: Record<string, number>;
  by_type: Record<string, number>;
  by_genre: Record<string, number>;
  by_author: Record<string, number>;
  by_publisher: Record<string, number>;
}

interface ProductDetailProps {
  product: Product;
  onClose: () => void;
}

export function ProductDetail({ product, onClose }: ProductDetailProps) {
  const queryClient = useQueryClient();
  const focusTrapRef = useFocusTrap<HTMLDivElement>({ enabled: true, restoreFocus: true });
  const [activeTab, setActiveTab] = useState<'info' | 'text' | 'extract' | 'export' | 'notes'>('info');
  const [textContent, setTextContent] = useState<string | null>(null);
  const [textLoading, setTextLoading] = useState(false);
  const [textError, setTextError] = useState<string | null>(null);
  const [showPdfViewer, setShowPdfViewer] = useState(false);
  const [extractedContent, setExtractedContent] = useState<Record<string, unknown[]> | null>(null);
  const [localProduct, setLocalProduct] = useState(product);
  const [isEditing, setIsEditing] = useState(false);
  const [showCampaignMenu, setShowCampaignMenu] = useState(false);
  const [showRunStatusMenu, setShowRunStatusMenu] = useState(false);
  const [showCollectionMenu, setShowCollectionMenu] = useState(false);
  const [showTagMenu, setShowTagMenu] = useState(false);
  const [showNoteEditor, setShowNoteEditor] = useState(false);
  const [editingNote, setEditingNote] = useState<RunNote | null>(null);
  const [bestiaryProfile, setBestiaryProfile] = useState<'dcc' | 'osr'>('dcc');
  const [bestiaryMessage, setBestiaryMessage] = useState<string | null>(null);

  const { data: libraryStats } = useQuery({
    queryKey: ['library-stats'],
    queryFn: async () => {
      const res = await apiClient.get<LibraryStats>('/folders/library/stats');
      return res.data;
    },
  });

  const { data: failedQueueItems } = useQuery({
    queryKey: ['queue-errors', product.id],
    queryFn: async () => {
      const response = await apiClient.get('/queue', {
        params: { status: 'failed', limit: 10 },
      });
      // Filter to this product's items client-side
      return (response.data.items || []).filter(
        (item: any) => item.product_id === product.id
      );
    },
  });
  const [noteForm, setNoteForm] = useState({
    note_type: 'prep_tip' as 'prep_tip' | 'modification' | 'warning' | 'review',
    title: '',
    content: '',
    spoiler_level: 'none' as 'none' | 'minor' | 'major' | 'endgame',
    visibility: 'private' as 'private' | 'anonymous' | 'public',
  });
  const [editForm, setEditForm] = useState({
    title: product.title || '',
    author: product.author || '',
    publisher: product.publisher || '',
    description: product.description || '',
    game_system: product.game_system || '',
    product_type: product.product_type || '',
    genre: product.genre || '',
    setting: product.setting || '',
    publication_year: product.publication_year?.toString() || '',
    page_count: product.page_count?.toString() || '',
    level_range_min: product.level_range_min?.toString() || '',
    level_range_max: product.level_range_max?.toString() || '',
    party_size_min: product.party_size_min?.toString() || '',
    party_size_max: product.party_size_max?.toString() || '',
    estimated_runtime: product.estimated_runtime || '',
    series: product.series || '',
    series_order: product.series_order || '',
    format: product.format || '',
    isbn: product.isbn || '',
    dtrpg_url: product.dtrpg_url || '',
    itch_url: product.itch_url || '',
    themes: product.themes || '',
    content_warnings: product.content_warnings || '',
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

  const bestiaryMutation = useMutation({
    mutationFn: () => queueExtraction(product.id, bestiaryProfile),
    onSuccess: (result) =>
      setBestiaryMessage(result.warning ? `${result.message} — ${result.warning}` : result.message),
    onError: (err: any) =>
      setBestiaryMessage(err?.response?.data?.detail ?? 'Failed to queue bestiary extraction'),
  });

  // Metadata is a hint for the default only — the backend guard decides what
  // is actually allowed.
  useEffect(() => {
    const system = (localProduct.game_system ?? '').toLowerCase();
    if (system.includes('dungeon crawl classics') || system.includes('dcc')) {
      setBestiaryProfile('dcc');
    } else if (
      system.includes('old-school') || system.includes('ose') ||
      system.includes('b/x') || system.includes('advanced dungeons')
    ) {
      setBestiaryProfile('osr');
    }
  }, [localProduct.game_system]);

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

  const updateAndContributeMutation = useMutation({
    mutationFn: async (data: Parameters<typeof updateProduct>[1]) => {
      return updateProductAndContribute(product.id, data);
    },
    onSuccess: (updatedProduct) => {
      setLocalProduct(prev => ({ ...prev, ...updatedProduct }));
      setIsEditing(false);
      queryClient.invalidateQueries({ queryKey: ['products'] });
      queryClient.invalidateQueries({ queryKey: ['contribution-status', product.id] });
    },
  });

  const contributeMutation = useMutation({
    mutationFn: async () => {
      return contributeProduct(product.id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['contribution-status', product.id] });
    },
  });

  const { data: contributionStatus } = useQuery({
    queryKey: ['contribution-status', product.id],
    queryFn: () => getContributionStatus(product.id),
  });

  const { data: campaignsData } = useQuery({
    queryKey: ['campaigns'],
    queryFn: async () => {
      const res = await apiClient.get<{ campaigns: Array<{ id: number; name: string; game_system: string | null }> }>('/campaigns');
      return res.data.campaigns;
    },
    enabled: showCampaignMenu,
  });

  const { data: collectionsData } = useQuery({
    queryKey: ['collections'],
    queryFn: getCollections,
    enabled: showCollectionMenu,
  });

  const { data: allTags } = useQuery({
    queryKey: ['tags'],
    queryFn: () => getTags(),
    enabled: showTagMenu,
  });

  const { data: productCollections } = useQuery({
    queryKey: ['product-collections', product.id],
    queryFn: async () => {
      const res = await apiClient.get<{ collection_ids: number[] }>(`/products/${product.id}/collections`);
      return res.data.collection_ids;
    },
    enabled: showCollectionMenu,
  });

  const addToCollectionMutation = useMutation({
    mutationFn: async (collectionId: number) => {
      await addProductToCollection(collectionId, product.id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['product-collections', product.id] });
      queryClient.invalidateQueries({ queryKey: ['collections'] });
    },
  });

  const removeFromCollectionMutation = useMutation({
    mutationFn: async (collectionId: number) => {
      await removeProductFromCollection(collectionId, product.id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['product-collections', product.id] });
      queryClient.invalidateQueries({ queryKey: ['collections'] });
    },
  });

  const addTagMutation = useMutation({
    mutationFn: async (tagId: number) => {
      await addTagToProduct(product.id, tagId);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['products'] });
      queryClient.invalidateQueries({ queryKey: ['tags'] });
    },
  });

  const removeTagMutation = useMutation({
    mutationFn: async (tagId: number) => {
      await removeTagFromProduct(product.id, tagId);
    },
    onSuccess: (_, tagId) => {
      setLocalProduct(prev => ({
        ...prev,
        tags: prev.tags?.filter(t => t.id !== tagId) || [],
      }));
      queryClient.invalidateQueries({ queryKey: ['products'] });
      queryClient.invalidateQueries({ queryKey: ['tags'] });
    },
  });

  const handleAddTag = (tag: TagType) => {
    addTagMutation.mutate(tag.id, {
      onSuccess: () => {
        setLocalProduct(prev => ({
          ...prev,
          tags: [...(prev.tags || []), { 
            id: tag.id, 
            name: tag.name, 
            category: tag.category, 
            color: tag.color,
            created_at: tag.created_at,
            product_count: tag.product_count,
          }],
        }));
      },
    });
  };

  const handleToggleCollection = (collection: Collection) => {
    const isInCollection = productCollections?.includes(collection.id);
    if (isInCollection) {
      removeFromCollectionMutation.mutate(collection.id);
    } else {
      addToCollectionMutation.mutate(collection.id);
    }
  };

  const addToCampaignMutation = useMutation({
    mutationFn: async (campaignId: number) => {
      await apiClient.post(`/campaigns/${campaignId}/products/${product.id}`);
    },
    onSuccess: () => {
      setShowCampaignMenu(false);
    },
  });

  const createCampaignWithProductMutation = useMutation({
    mutationFn: async () => {
      const res = await apiClient.post<{ id: number }>('/campaigns', {
        name: product.title || product.file_name || 'New Campaign',
        game_system: product.game_system || '',
        status: 'active',
      });
      await apiClient.post(`/campaigns/${res.data.id}/products/${product.id}`);
      return res.data;
    },
    onSuccess: () => {
      setShowCampaignMenu(false);
      queryClient.invalidateQueries({ queryKey: ['campaigns'] });
    },
  });

  const updateRunStatusMutation = useMutation({
    mutationFn: async (params: { run_status?: string; run_rating?: number; run_difficulty?: string }) => {
      const searchParams = new URLSearchParams();
      if (params.run_status !== undefined) searchParams.set('run_status', params.run_status);
      if (params.run_rating !== undefined) searchParams.set('run_rating', params.run_rating.toString());
      if (params.run_difficulty !== undefined) searchParams.set('run_difficulty', params.run_difficulty);
      const res = await apiClient.put(`/products/${product.id}/run-status?${searchParams.toString()}`);
      return res.data;
    },
    onSuccess: (data) => {
      setLocalProduct(prev => ({
        ...prev,
        run_status: data.run_status ? {
          status: data.run_status,
          rating: data.run_rating,
          difficulty: data.run_difficulty,
          completed_at: data.run_completed_at,
        } : null,
      }));
      setShowRunStatusMenu(false);
      queryClient.invalidateQueries({ queryKey: ['products'] });
    },
  });

  const clearRunStatusMutation = useMutation({
    mutationFn: async () => {
      const res = await apiClient.delete(`/products/${product.id}/run-status`);
      return res.data;
    },
    onSuccess: () => {
      setLocalProduct(prev => ({ ...prev, run_status: null }));
      setShowRunStatusMenu(false);
      queryClient.invalidateQueries({ queryKey: ['products'] });
    },
  });

  const { data: runNotes, refetch: refetchNotes } = useQuery({
    queryKey: ['run-notes', product.id],
    queryFn: async () => {
      const res = await apiClient.get<RunNote[]>(`/products/${product.id}/run-notes`);
      return res.data;
    },
    enabled: activeTab === 'notes',
  });

  const createNoteMutation = useMutation({
    mutationFn: async (data: typeof noteForm) => {
      const res = await apiClient.post(`/products/${product.id}/run-notes`, data);
      return res.data;
    },
    onSuccess: () => {
      refetchNotes();
      setShowNoteEditor(false);
      resetNoteForm();
    },
  });

  const updateNoteMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: Partial<typeof noteForm> }) => {
      const res = await apiClient.put(`/run-notes/${id}`, data);
      return res.data;
    },
    onSuccess: () => {
      refetchNotes();
      setShowNoteEditor(false);
      setEditingNote(null);
      resetNoteForm();
    },
  });

  const deleteNoteMutation = useMutation({
    mutationFn: async (id: number) => {
      const res = await apiClient.delete(`/run-notes/${id}`);
      return res.data;
    },
    onSuccess: () => {
      refetchNotes();
    },
  });

  const resetNoteForm = () => {
    setNoteForm({
      note_type: 'prep_tip',
      title: '',
      content: '',
      spoiler_level: 'none',
      visibility: 'private',
    });
  };

  const openNoteEditor = (note?: RunNote) => {
    if (note) {
      setEditingNote(note);
      setNoteForm({
        note_type: note.note_type,
        title: note.title,
        content: note.content,
        spoiler_level: note.spoiler_level,
        visibility: note.visibility,
      });
    } else {
      setEditingNote(null);
      resetNoteForm();
    }
    setShowNoteEditor(true);
  };

  const handleNoteSave = () => {
    if (editingNote) {
      updateNoteMutation.mutate({ id: editingNote.id, data: noteForm });
    } else {
      createNoteMutation.mutate(noteForm);
    }
  };

  const buildEditData = () => {
    const data: Record<string, unknown> = {};
    if (editForm.title) data.title = editForm.title;
    if (editForm.author) data.author = editForm.author;
    if (editForm.publisher) data.publisher = editForm.publisher;
    if (editForm.description) data.description = editForm.description;
    if (editForm.game_system) data.game_system = editForm.game_system;
    if (editForm.product_type) data.product_type = editForm.product_type;
    if (editForm.genre) data.genre = editForm.genre;
    if (editForm.setting) data.setting = editForm.setting;
    if (editForm.publication_year) data.publication_year = parseInt(editForm.publication_year);
    if (editForm.page_count) data.page_count = parseInt(editForm.page_count);
    if (editForm.level_range_min) data.level_range_min = parseInt(editForm.level_range_min);
    if (editForm.level_range_max) data.level_range_max = parseInt(editForm.level_range_max);
    if (editForm.party_size_min) data.party_size_min = parseInt(editForm.party_size_min);
    if (editForm.party_size_max) data.party_size_max = parseInt(editForm.party_size_max);
    if (editForm.estimated_runtime) data.estimated_runtime = editForm.estimated_runtime;
    if (editForm.series) data.series = editForm.series;
    if (editForm.series_order) data.series_order = editForm.series_order;
    if (editForm.format) data.format = editForm.format;
    if (editForm.isbn) data.isbn = editForm.isbn;
    if (editForm.dtrpg_url) data.dtrpg_url = editForm.dtrpg_url;
    if (editForm.itch_url) data.itch_url = editForm.itch_url;
    if (editForm.themes) data.themes = editForm.themes;
    if (editForm.content_warnings) data.content_warnings = editForm.content_warnings;
    return data;
  };

  const handleSaveEdit = () => {
    updateMutation.mutate(buildEditData());
  };

  const handleSaveAndContribute = () => {
    updateAndContributeMutation.mutate(buildEditData());
  };

  const handleCancelEdit = () => {
    setEditForm({
      title: localProduct.title || '',
      author: localProduct.author || '',
      publisher: localProduct.publisher || '',
      description: localProduct.description || '',
      game_system: localProduct.game_system || '',
      product_type: localProduct.product_type || '',
      genre: localProduct.genre || '',
      setting: localProduct.setting || '',
      publication_year: localProduct.publication_year?.toString() || '',
      page_count: localProduct.page_count?.toString() || '',
      level_range_min: localProduct.level_range_min?.toString() || '',
      level_range_max: localProduct.level_range_max?.toString() || '',
      party_size_min: localProduct.party_size_min?.toString() || '',
      party_size_max: localProduct.party_size_max?.toString() || '',
      estimated_runtime: localProduct.estimated_runtime || '',
      series: localProduct.series || '',
      series_order: localProduct.series_order || '',
      format: localProduct.format || '',
      isbn: localProduct.isbn || '',
      dtrpg_url: localProduct.dtrpg_url || '',
      itch_url: localProduct.itch_url || '',
      themes: localProduct.themes || '',
      content_warnings: localProduct.content_warnings || '',
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

  const handleTabChange = (tab: 'info' | 'text' | 'extract' | 'export' | 'notes') => {
    setActiveTab(tab);
    if (tab === 'text') {
      loadText();
    }
  };

  const openPdf = () => {
    window.open(`/api/v1/products/${product.id}/pdf`, '_blank');
  };

  const openFolder = async () => {
    try {
      await apiClient.post(`/api/v1/products/${product.id}/open-folder`);
    } catch {
      // silently fail — folder may not exist
    }
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
        className="flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-lg shadow-lg"
        style={{ backgroundColor: 'var(--color-surface)' }}
      >
        <header className="flex items-center justify-between border-b px-6 py-4" style={{ borderColor: 'var(--color-border)' }}>
          <h2 id="product-detail-title" className="text-2xl font-semibold font-display truncate" style={{ color: 'var(--color-text-primary)' }}>{product.title}</h2>
          <button
            onClick={onClose}
            aria-label="Close product details"
            className="flex items-center justify-center rounded-md transition-colors"
            style={{ width: '44px', height: '44px', color: 'var(--color-text-secondary)' }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-surface-raised)')}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </header>

        <div className="flex border-b" role="tablist" aria-label="Product information tabs" style={{ borderColor: 'var(--color-border)' }}>
          <button
            onClick={() => handleTabChange('info')}
            role="tab"
            aria-selected={activeTab === 'info'}
            aria-controls="panel-info"
            id="tab-info"
            className={`px-6 py-3 text-lg font-medium min-h-[48px] ${
              activeTab === 'info'
                ? 'border-b-2'
                : ''
            }`}
            style={activeTab === 'info' ? { borderColor: 'var(--color-accent)', color: 'var(--color-accent)' } : { color: 'var(--color-text-secondary)' }}
          >
            Details
          </button>
          <button
            onClick={() => handleTabChange('text')}
            role="tab"
            aria-selected={activeTab === 'text'}
            aria-controls="panel-text"
            id="tab-text"
            className={`px-6 py-3 text-lg font-medium min-h-[48px] ${
              activeTab === 'text'
                ? 'border-b-2'
                : ''
            }`}
            style={activeTab === 'text' ? { borderColor: 'var(--color-accent)', color: 'var(--color-accent)' } : { color: 'var(--color-text-secondary)' }}
          >
            Extracted Text
          </button>
          <button
            onClick={() => handleTabChange('extract')}
            role="tab"
            aria-selected={activeTab === 'extract'}
            aria-controls="panel-extract"
            id="tab-extract"
            className={`px-6 py-3 text-lg font-medium min-h-[48px] ${
              activeTab === 'extract'
                ? 'border-b-2'
                : ''
            }`}
            style={activeTab === 'extract' ? { borderColor: 'var(--color-accent)', color: 'var(--color-accent)' } : { color: 'var(--color-text-secondary)' }}
          >
            Extract Content
          </button>
          <button
            onClick={() => handleTabChange('export')}
            role="tab"
            aria-selected={activeTab === 'export'}
            aria-controls="panel-export"
            id="tab-export"
            className={`px-6 py-3 text-lg font-medium min-h-[48px] ${
              activeTab === 'export'
                ? 'border-b-2'
                : ''
            }`}
            style={activeTab === 'export' ? { borderColor: 'var(--color-accent)', color: 'var(--color-accent)' } : { color: 'var(--color-text-secondary)' }}
          >
            Export
          </button>
          <button
            onClick={() => handleTabChange('notes')}
            role="tab"
            aria-selected={activeTab === 'notes'}
            aria-controls="panel-notes"
            id="tab-notes"
            className={`px-6 py-3 text-lg font-medium min-h-[48px] ${
              activeTab === 'notes'
                ? 'border-b-2'
                : ''
            }`}
            style={activeTab === 'notes' ? { borderColor: 'var(--color-accent)', color: 'var(--color-accent)' } : { color: 'var(--color-text-secondary)' }}
          >
            GM Notes
            {runNotes && runNotes.length > 0 && (
              <span className="ml-1.5 rounded-md px-2 py-0.5 text-xs" style={{ backgroundColor: 'var(--color-accent-light)', color: 'var(--color-accent)' }}>
                {runNotes.length}
              </span>
            )}
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
                  className="rounded-lg object-cover shadow-sm"
                  style={{ width: '120px', height: '160px' }}
                  onError={(e) => {
                    (e.target as HTMLImageElement).src = '/placeholder-cover.png';
                  }}
                />
              </div>

              <div className="flex-1 space-y-4">
                {isEditing ? (
                  <div className="space-y-4 max-h-[60vh] overflow-y-auto pr-2">
                    {/* Basic Info */}
                    <div className="space-y-3">
                      <h4 className="text-base font-semibold uppercase tracking-wide" style={{ color: 'var(--color-text-secondary)' }}>Basic Info</h4>
                      <div>
                        <label className="block text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>Title</label>
                        <input
                          type="text"
                          value={editForm.title}
                          onChange={(e) => setEditForm({ ...editForm, title: e.target.value })}
                          className="mt-1 w-full rounded-md border px-3 py-2 text-lg focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" style={{ borderColor: 'var(--color-border)', minHeight: '48px', fontSize: '18px' }}
                        />
                      </div>
                      <div>
                        <label className="block text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>Description</label>
                        <textarea
                          value={editForm.description}
                          onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                          rows={3}
                          className="mt-1 w-full rounded-md border px-3 py-2 text-lg focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" style={{ borderColor: 'var(--color-border)', minHeight: '48px', fontSize: '18px' }}
                          placeholder="Brief description of this product..."
                        />
                      </div>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>Author</label>
                          <input
                            type="text"
                            value={editForm.author}
                            onChange={(e) => setEditForm({ ...editForm, author: e.target.value })}
                            className="mt-1 w-full rounded-md border px-3 py-2 text-lg focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" style={{ borderColor: 'var(--color-border)', minHeight: '48px', fontSize: '18px' }}
                          />
                        </div>
                        <div>
                          <label className="block text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>Publisher</label>
                          <input
                            type="text"
                            value={editForm.publisher}
                            onChange={(e) => setEditForm({ ...editForm, publisher: e.target.value })}
                            className="mt-1 w-full rounded-md border px-3 py-2 text-lg focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" style={{ borderColor: 'var(--color-border)', minHeight: '48px', fontSize: '18px' }}
                          />
                        </div>
                      </div>
                      <div className="grid grid-cols-3 gap-4">
                        <div>
                          <label className="block text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>Year</label>
                          <input
                            type="number"
                            value={editForm.publication_year}
                            onChange={(e) => setEditForm({ ...editForm, publication_year: e.target.value })}
                            className="mt-1 w-full rounded-md border px-3 py-2 text-lg focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" style={{ borderColor: 'var(--color-border)', minHeight: '48px', fontSize: '18px' }}
                          />
                        </div>
                        <div>
                          <label className="block text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>Page Count</label>
                          <input
                            type="number"
                            value={editForm.page_count}
                            onChange={(e) => setEditForm({ ...editForm, page_count: e.target.value })}
                            className="mt-1 w-full rounded-md border px-3 py-2 text-lg focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" style={{ borderColor: 'var(--color-border)', minHeight: '48px', fontSize: '18px' }}
                          />
                        </div>
                        <div>
                          <label className="block text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>Format</label>
                          <select
                            value={editForm.format}
                            onChange={(e) => setEditForm({ ...editForm, format: e.target.value })}
                            className="mt-1 w-full rounded-md border px-3 py-2 text-lg focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" style={{ borderColor: 'var(--color-border)', minHeight: '48px', fontSize: '18px' }}
                          >
                            <option value="">Select...</option>
                            <option value="pdf">PDF</option>
                            <option value="print">Print</option>
                            <option value="both">Both</option>
                          </select>
                        </div>
                      </div>
                    </div>

                    {/* Classification */}
                    <div className="space-y-3 border-t pt-4" style={{ borderColor: 'var(--color-border)' }}>
                      <h4 className="text-base font-semibold uppercase tracking-wide" style={{ color: 'var(--color-text-secondary)' }}>Classification</h4>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>Game System</label>
                          <ComboboxWithAdd
                            value={editForm.game_system}
                            onChange={(value) => setEditForm({ ...editForm, game_system: value })}
                            options={libraryStats ? Object.keys(libraryStats.by_system).sort() : []}
                            placeholder="Select or add game system..."
                            className="mt-1"
                          />
                        </div>
                        <div>
                          <label className="block text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>Product Type</label>
                          <select
                            value={editForm.product_type}
                            onChange={(e) => setEditForm({ ...editForm, product_type: e.target.value })}
                            className="mt-1 w-full rounded-md border px-3 py-2 text-lg focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" style={{ borderColor: 'var(--color-border)', minHeight: '48px', fontSize: '18px' }}
                          >
                            <option value="">Select...</option>
                            <option value="adventure">Adventure</option>
                            <option value="sourcebook">Sourcebook</option>
                            <option value="supplement">Supplement</option>
                            <option value="bestiary">Bestiary</option>
                            <option value="core_rules">Core Rules</option>
                            <option value="tools">Tools</option>
                            <option value="magazine">Magazine</option>
                            <option value="screen">Screen</option>
                            <option value="other">Other</option>
                          </select>
                        </div>
                      </div>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>Genre</label>
                          <input
                            type="text"
                            value={editForm.genre}
                            onChange={(e) => setEditForm({ ...editForm, genre: e.target.value })}
                            className="mt-1 w-full rounded-md border px-3 py-2 text-lg focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" style={{ borderColor: 'var(--color-border)', minHeight: '48px', fontSize: '18px' }}
                            placeholder="e.g., Fantasy, Sci-Fi, Horror"
                          />
                        </div>
                        <div>
                          <label className="block text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>Setting</label>
                          <input
                            type="text"
                            value={editForm.setting}
                            onChange={(e) => setEditForm({ ...editForm, setting: e.target.value })}
                            className="mt-1 w-full rounded-md border px-3 py-2 text-lg focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" style={{ borderColor: 'var(--color-border)', minHeight: '48px', fontSize: '18px' }}
                            placeholder="e.g., Forgotten Realms, Eberron"
                          />
                        </div>
                      </div>
                    </div>

                    {/* Adventure Details */}
                    <div className="space-y-3 border-t pt-4" style={{ borderColor: 'var(--color-border)' }}>
                      <h4 className="text-base font-semibold uppercase tracking-wide" style={{ color: 'var(--color-text-secondary)' }}>Adventure Details</h4>
                      <div className="grid grid-cols-4 gap-4">
                        <div>
                          <label className="block text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>Min Level</label>
                          <input
                            type="number"
                            value={editForm.level_range_min}
                            onChange={(e) => setEditForm({ ...editForm, level_range_min: e.target.value })}
                            className="mt-1 w-full rounded-md border px-3 py-2 text-lg focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" style={{ borderColor: 'var(--color-border)', minHeight: '48px', fontSize: '18px' }}
                          />
                        </div>
                        <div>
                          <label className="block text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>Max Level</label>
                          <input
                            type="number"
                            value={editForm.level_range_max}
                            onChange={(e) => setEditForm({ ...editForm, level_range_max: e.target.value })}
                            className="mt-1 w-full rounded-md border px-3 py-2 text-lg focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" style={{ borderColor: 'var(--color-border)', minHeight: '48px', fontSize: '18px' }}
                          />
                        </div>
                        <div>
                          <label className="block text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>Min Party</label>
                          <input
                            type="number"
                            value={editForm.party_size_min}
                            onChange={(e) => setEditForm({ ...editForm, party_size_min: e.target.value })}
                            className="mt-1 w-full rounded-md border px-3 py-2 text-lg focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" style={{ borderColor: 'var(--color-border)', minHeight: '48px', fontSize: '18px' }}
                          />
                        </div>
                        <div>
                          <label className="block text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>Max Party</label>
                          <input
                            type="number"
                            value={editForm.party_size_max}
                            onChange={(e) => setEditForm({ ...editForm, party_size_max: e.target.value })}
                            className="mt-1 w-full rounded-md border px-3 py-2 text-lg focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" style={{ borderColor: 'var(--color-border)', minHeight: '48px', fontSize: '18px' }}
                          />
                        </div>
                      </div>
                      <div>
                        <label className="block text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>Estimated Runtime</label>
                        <select
                          value={editForm.estimated_runtime}
                          onChange={(e) => setEditForm({ ...editForm, estimated_runtime: e.target.value })}
                          className="mt-1 w-full rounded-md border px-3 py-2 text-lg focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" style={{ borderColor: 'var(--color-border)', minHeight: '48px', fontSize: '18px' }}
                        >
                          <option value="">Select...</option>
                          <option value="one-shot">One-shot (1 session)</option>
                          <option value="2-3 sessions">Short (2-3 sessions)</option>
                          <option value="4-6 sessions">Medium (4-6 sessions)</option>
                          <option value="campaign">Campaign (7+ sessions)</option>
                        </select>
                      </div>
                    </div>

                    {/* Series Info */}
                    <div className="space-y-3 border-t pt-4" style={{ borderColor: 'var(--color-border)' }}>
                      <h4 className="text-base font-semibold uppercase tracking-wide" style={{ color: 'var(--color-text-secondary)' }}>Series</h4>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>Series Name</label>
                          <input
                            type="text"
                            value={editForm.series}
                            onChange={(e) => setEditForm({ ...editForm, series: e.target.value })}
                            className="mt-1 w-full rounded-md border px-3 py-2 text-lg focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" style={{ borderColor: 'var(--color-border)', minHeight: '48px', fontSize: '18px' }}
                            placeholder="e.g., Slavers Series"
                          />
                        </div>
                        <div>
                          <label className="block text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>Series Code/Order</label>
                          <input
                            type="text"
                            value={editForm.series_order}
                            onChange={(e) => setEditForm({ ...editForm, series_order: e.target.value })}
                            className="mt-1 w-full rounded-md border px-3 py-2 text-lg focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" style={{ borderColor: 'var(--color-border)', minHeight: '48px', fontSize: '18px' }}
                            placeholder="e.g., A1, REF4, 1"
                          />
                        </div>
                      </div>
                    </div>

                    {/* Marketplace Links */}
                    <div className="space-y-3 border-t pt-4" style={{ borderColor: 'var(--color-border)' }}>
                      <h4 className="text-base font-semibold uppercase tracking-wide" style={{ color: 'var(--color-text-secondary)' }}>Marketplace Links</h4>
                      <div>
                        <label className="block text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>DriveThruRPG URL</label>
                        <input
                          type="url"
                          value={editForm.dtrpg_url}
                          onChange={(e) => setEditForm({ ...editForm, dtrpg_url: e.target.value })}
                          className="mt-1 w-full rounded-md border px-3 py-2 text-lg focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" style={{ borderColor: 'var(--color-border)', minHeight: '48px', fontSize: '18px' }}
                          placeholder="https://www.drivethrurpg.com/product/..."
                        />
                      </div>
                      <div>
                        <label className="block text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>Itch.io URL</label>
                        <input
                          type="url"
                          value={editForm.itch_url}
                          onChange={(e) => setEditForm({ ...editForm, itch_url: e.target.value })}
                          className="mt-1 w-full rounded-md border px-3 py-2 text-lg focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" style={{ borderColor: 'var(--color-border)', minHeight: '48px', fontSize: '18px' }}
                          placeholder="https://example.itch.io/product"
                        />
                      </div>
                      <div>
                        <label className="block text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>ISBN</label>
                        <input
                          type="text"
                          value={editForm.isbn}
                          onChange={(e) => setEditForm({ ...editForm, isbn: e.target.value })}
                          className="mt-1 w-full rounded-md border px-3 py-2 text-lg focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" style={{ borderColor: 'var(--color-border)', minHeight: '48px', fontSize: '18px' }}
                        />
                      </div>
                    </div>

                    {/* Metadata */}
                    <div className="space-y-3 border-t pt-4" style={{ borderColor: 'var(--color-border)' }}>
                      <h4 className="text-base font-semibold uppercase tracking-wide" style={{ color: 'var(--color-text-secondary)' }}>Metadata</h4>
                      <div>
                        <label className="block text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>Themes</label>
                        <input
                          type="text"
                          value={editForm.themes}
                          onChange={(e) => setEditForm({ ...editForm, themes: e.target.value })}
                          className="mt-1 w-full rounded-md border px-3 py-2 text-lg focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" style={{ borderColor: 'var(--color-border)', minHeight: '48px', fontSize: '18px' }}
                          placeholder="horror, exploration, mystery (comma separated)"
                        />
                      </div>
                      <div>
                        <label className="block text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>Content Warnings</label>
                        <input
                          type="text"
                          value={editForm.content_warnings}
                          onChange={(e) => setEditForm({ ...editForm, content_warnings: e.target.value })}
                          className="mt-1 w-full rounded-md border px-3 py-2 text-lg focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500" style={{ borderColor: 'var(--color-border)', minHeight: '48px', fontSize: '18px' }}
                          placeholder="violence, body horror (comma separated)"
                        />
                      </div>
                    </div>

                    <div className="flex flex-wrap gap-3 pt-4 border-t" style={{ borderColor: 'var(--color-border)' }}>
                      <button
                        onClick={handleSaveEdit}
                        disabled={updateMutation.isPending || updateAndContributeMutation.isPending}
                        className="inline-flex items-center gap-2 rounded-md px-4 py-2 text-base font-medium disabled:opacity-50 transition-colors"
                        style={{ backgroundColor: 'var(--color-accent)', color: '#fff' }}
                        onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-accent-hover)')}
                        onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-accent)')}
                      >
                        {updateMutation.isPending ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Save className="h-4 w-4" />
                        )}
                        Save Changes
                      </button>
                      <button
                        onClick={handleSaveAndContribute}
                        disabled={updateMutation.isPending || updateAndContributeMutation.isPending}
                        className="inline-flex items-center gap-2 rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
                        title="Save changes and contribute to the Codex community database"
                      >
                        {updateAndContributeMutation.isPending ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Upload className="h-4 w-4" />
                        )}
                        Save & Send to Codex
                      </button>
                      <button
                        onClick={handleCancelEdit}
                        disabled={updateMutation.isPending || updateAndContributeMutation.isPending}
                        className="inline-flex items-center gap-2 rounded-md border px-4 py-2 text-base font-medium disabled:opacity-50 transition-colors"
                        style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)', color: 'var(--color-text-secondary)' }}
                        onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-surface-raised)')}
                        onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-surface)')}
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
                          <Book className="h-4 w-4" style={{ color: 'var(--color-text-secondary)' }} />
                          <div>
                            <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>Game System</p>
                            <p className="text-lg font-medium" style={{ color: 'var(--color-text-primary)' }}>{localProduct.game_system}</p>
                          </div>
                        </div>
                      )}

                      {localProduct.product_type && (
                        <div className="flex items-center gap-2">
                          <FileText className="h-4 w-4" style={{ color: 'var(--color-text-secondary)' }} />
                          <div>
                            <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>Type</p>
                            <p className="text-lg font-medium" style={{ color: 'var(--color-text-primary)' }}>{localProduct.product_type}</p>
                          </div>
                        </div>
                      )}

                      {localProduct.publisher && (
                        <div className="flex items-center gap-2">
                          <Users className="h-4 w-4" style={{ color: 'var(--color-text-secondary)' }} />
                          <div>
                            <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>Publisher</p>
                            <p className="text-lg font-medium" style={{ color: 'var(--color-text-primary)' }}>{localProduct.publisher}</p>
                          </div>
                        </div>
                      )}

                      {localProduct.publication_year && (
                        <div className="flex items-center gap-2">
                          <Calendar className="h-4 w-4" style={{ color: 'var(--color-text-secondary)' }} />
                          <div>
                            <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>Year</p>
                            <p className="text-lg font-medium" style={{ color: 'var(--color-text-primary)' }}>{localProduct.publication_year}</p>
                          </div>
                        </div>
                      )}

                      {localProduct.page_count && (
                        <div className="flex items-center gap-2">
                          <FileText className="h-4 w-4" style={{ color: 'var(--color-text-secondary)' }} />
                          <div>
                            <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>Pages</p>
                            <p className="text-lg font-medium" style={{ color: 'var(--color-text-primary)' }}>{localProduct.page_count}</p>
                          </div>
                        </div>
                      )}

                      {(localProduct.level_range_min || localProduct.level_range_max) && (
                        <div className="flex items-center gap-2">
                          <Clock className="h-4 w-4" style={{ color: 'var(--color-text-secondary)' }} />
                          <div>
                            <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>Level Range</p>
                            <p className="text-lg font-medium" style={{ color: 'var(--color-text-primary)' }}>
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

                    <div className="flex flex-wrap gap-3 pt-4">
                      <button
                        onClick={() => setShowPdfViewer(true)}
                        className="inline-flex items-center gap-2 rounded-md px-4 py-2 text-base font-medium transition-colors"
                        style={{ backgroundColor: 'var(--color-accent)', color: '#fff' }}
                        onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-accent-hover)')}
                        onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-accent)')}
                      >
                        <Eye className="h-4 w-4" />
                        View PDF
                      </button>
                      <button
                        onClick={openPdf}
                        className="inline-flex items-center gap-2 rounded-md border px-4 py-2 text-base font-medium transition-colors"
                        style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)', color: 'var(--color-text-secondary)' }}
                        onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-surface-raised)')}
                        onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-surface)')}
                      >
                        <ExternalLink className="h-4 w-4" />
                        Open in New Tab
                      </button>
                      <button
                        onClick={openFolder}
                        className="inline-flex items-center gap-2 rounded-md border px-4 py-2 text-base font-medium transition-colors"
                        style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)', color: 'var(--color-text-secondary)' }}
                        onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-surface-raised)')}
                        onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-surface)')}
                      >
                        <FolderOpen className="h-4 w-4" />
                        View in Folder
                      </button>
                      <button
                        onClick={() => setIsEditing(true)}
                        className="inline-flex items-center gap-2 rounded-md border px-4 py-2 text-base font-medium transition-colors"
                        style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)', color: 'var(--color-text-secondary)' }}
                        onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-surface-raised)')}
                        onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-surface)')}
                      >
                        <Edit3 className="h-4 w-4" />
                        Edit
                      </button>
                      
                      {/* Contribute to Codex Button */}
                      {contributionStatus?.has_contribution ? (
                        <div 
                          className={`inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium ${
                            contributionStatus.status === 'submitted' || contributionStatus.status === 'accepted'
                              ? 'bg-green-50 text-green-700 border border-green-200'
                              : contributionStatus.status === 'pending'
                              ? 'bg-amber-50 text-amber-700 border border-amber-200'
                              : contributionStatus.status === 'failed' || contributionStatus.status === 'rejected'
                              ? 'bg-red-50 text-red-700 border border-red-200'
                              : 'bg-neutral-50 text-neutral-700 border border-neutral-200'
                          }`}
                          title={contributionStatus.error_message || `Status: ${contributionStatus.status}`}
                        >
                          <Database className="h-4 w-4" />
                          {contributionStatus.status === 'submitted' || contributionStatus.status === 'accepted'
                            ? 'Sent to Codex'
                            : contributionStatus.status === 'pending'
                            ? 'Pending...'
                            : contributionStatus.status === 'failed'
                            ? 'Failed'
                            : contributionStatus.status === 'rejected'
                            ? 'Rejected'
                            : 'In Queue'}
                        </div>
                      ) : (
                        <button
                          onClick={() => contributeMutation.mutate()}
                          disabled={contributeMutation.isPending || !localProduct.title}
                          className="inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 px-4 py-2 text-sm font-medium text-amber-700 hover:bg-amber-100 disabled:opacity-50"
                          title={!localProduct.title ? 'Product needs a title to contribute' : 'Share this product with the Codex community database'}
                        >
                          {contributeMutation.isPending ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <Upload className="h-4 w-4" />
                          )}
                          Contribute to Codex
                        </button>
                      )}

                      {/* Add to Campaign Dropdown */}
                      <div className="relative">
                        <button
                          onClick={() => setShowCampaignMenu(!showCampaignMenu)}
                          className="inline-flex items-center gap-2 rounded-md border px-4 py-2 text-base font-medium transition-colors"
                          style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)', color: 'var(--color-text-secondary)' }}
                          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-surface-raised)')}
                          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-surface)')}
                        >
                          <FolderPlus className="h-4 w-4" />
                          Add to Campaign
                          <ChevronDown className="h-4 w-4" />
                        </button>
                        
                        {showCampaignMenu && (
                          <div className="absolute right-0 top-full mt-1 w-64 rounded-md border shadow-sm z-10" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
                            <div className="p-2">
                              <button
                                onClick={() => createCampaignWithProductMutation.mutate()}
                                disabled={createCampaignWithProductMutation.isPending}
                                className="w-full flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-left hover:bg-purple-50 text-purple-700 font-medium"
                              >
                                <FolderPlus className="h-4 w-4" />
                                Create New Campaign
                              </button>
                            </div>
                            {campaignsData && campaignsData.length > 0 && (
                              <>
                                <div className="border-t border-neutral-100 px-3 py-1">
                                  <p className="text-xs text-neutral-500 uppercase tracking-wide">Existing Campaigns</p>
                                </div>
                                <div className="max-h-48 overflow-y-auto p-2">
                                  {campaignsData.map((campaign) => (
                                    <button
                                      key={campaign.id}
                                      onClick={() => addToCampaignMutation.mutate(campaign.id)}
                                      disabled={addToCampaignMutation.isPending}
                                      className="w-full flex items-center justify-between rounded-md px-3 py-2 text-sm text-left transition-colors" style={{ color: 'var(--color-text-primary)' }}
                                      onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-surface-raised)')}
                                      onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                                    >
                                      <div>
                                        <p className="font-medium" style={{ color: 'var(--color-text-primary)' }}>{campaign.name}</p>
                                        {campaign.game_system && (
                                          <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>{campaign.game_system}</p>
                                        )}
                                      </div>
                                      {addToCampaignMutation.isPending && addToCampaignMutation.variables === campaign.id && (
                                        <Loader2 className="h-4 w-4 animate-spin" style={{ color: 'var(--color-accent)' }} />
                                      )}
                                    </button>
                                  ))}
                                </div>
                              </>
                            )}
                            {campaignsData && campaignsData.length === 0 && (
                              <div className="p-3 text-center text-sm text-neutral-500">
                                No campaigns yet
                              </div>
                            )}
                          </div>
                        )}
                      </div>

                      {/* Add to Collection Dropdown */}
                      <div className="relative">
                        <button
                          onClick={() => setShowCollectionMenu(!showCollectionMenu)}
                          className="inline-flex items-center gap-2 rounded-md border px-4 py-2 text-base font-medium transition-colors"
                          style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)', color: 'var(--color-text-secondary)' }}
                          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-surface-raised)')}
                          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-surface)')}
                        >
                          <FolderPlus className="h-4 w-4" />
                          Collections
                          <ChevronDown className="h-4 w-4" />
                        </button>
                        
                        {showCollectionMenu && (
                          <div className="absolute right-0 top-full mt-1 w-64 rounded-md border shadow-sm z-10" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
                            {collectionsData && collectionsData.length > 0 ? (
                              <div className="max-h-64 overflow-y-auto p-2">
                                {collectionsData.map((collection) => {
                                  const isInCollection = productCollections?.includes(collection.id);
                                  return (
                                    <button
                                      key={collection.id}
                                      onClick={() => handleToggleCollection(collection)}
                                      disabled={addToCollectionMutation.isPending || removeFromCollectionMutation.isPending}
                                      className="w-full flex items-center justify-between rounded-md px-3 py-2 text-sm text-left transition-colors" style={{ color: 'var(--color-text-primary)' }}
                                      onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-surface-raised)')}
                                      onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                                    >
                                      <div className="flex items-center gap-2">
                                        <FolderPlus
                                          className="h-4 w-4"
                                          style={{ color: collection.color || undefined }}
                                        />
                                        <span className="font-medium text-neutral-900">{collection.name}</span>
                                      </div>
                                      {isInCollection && (
                                        <Check className="h-4 w-4 text-green-600" />
                                      )}
                                    </button>
                                  );
                                })}
                              </div>
                            ) : (
                              <div className="p-3 text-center text-sm text-neutral-500">
                                No collections yet. Create one from the sidebar.
                              </div>
                            )}
                          </div>
                        )}
                      </div>

                      {/* Manage Tags Dropdown */}
                      <div className="relative">
                        <button
                          onClick={() => setShowTagMenu(!showTagMenu)}
                          className="inline-flex items-center gap-2 rounded-md border px-4 py-2 text-base font-medium transition-colors"
                          style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)', color: 'var(--color-text-secondary)' }}
                          onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-surface-raised)')}
                          onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-surface)')}
                        >
                          <Tag className="h-4 w-4" />
                          Tags
                          <ChevronDown className="h-4 w-4" />
                        </button>
                        
                        {showTagMenu && (
                          <div className="absolute right-0 top-full mt-1 w-72 rounded-md border shadow-sm z-10" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
                            {/* Current tags */}
                            {localProduct.tags && localProduct.tags.length > 0 && (
                              <div className="p-3 border-b border-neutral-100">
                                <p className="text-xs text-neutral-500 uppercase tracking-wide mb-2">Current Tags</p>
                                <div className="flex flex-wrap gap-1.5">
                                  {localProduct.tags.map((tag) => (
                                    <span
                                      key={tag.id}
                                      className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium"
                                      style={{
                                        backgroundColor: tag.color ? `${tag.color}20` : '#e5e7eb',
                                        color: tag.color || '#374151',
                                      }}
                                    >
                                      {tag.name}
                                      <button
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          removeTagMutation.mutate(tag.id);
                                        }}
                                        className="ml-0.5 rounded-full p-0.5 hover:bg-black/10"
                                        aria-label={`Remove ${tag.name}`}
                                      >
                                        <X className="h-3 w-3" />
                                      </button>
                                    </span>
                                  ))}
                                </div>
                              </div>
                            )}
                            
                            {/* Available tags to add */}
                            <div className="p-2">
                              <p className="px-2 py-1 text-xs text-neutral-500 uppercase tracking-wide">Add Tags</p>
                              {allTags && allTags.length > 0 ? (
                                <div className="max-h-48 overflow-y-auto">
                                  {allTags
                                    .filter(tag => !localProduct.tags?.some(t => t.id === tag.id))
                                    .map((tag) => (
                                      <button
                                        key={tag.id}
                                        onClick={() => handleAddTag(tag)}
                                        disabled={addTagMutation.isPending}
                                        className="w-full flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-left hover:bg-neutral-50"
                                      >
                                        <span
                                          className="h-3 w-3 rounded-full"
                                          style={{ backgroundColor: tag.color || '#6b7280' }}
                                        />
                                        <span>{tag.name}</span>
                                        {tag.category && (
                                          <span className="text-xs text-neutral-400">({tag.category})</span>
                                        )}
                                      </button>
                                    ))}
                                  {allTags.filter(tag => !localProduct.tags?.some(t => t.id === tag.id)).length === 0 && (
                                    <p className="px-3 py-2 text-sm text-neutral-500">All tags applied</p>
                                  )}
                                </div>
                              ) : (
                                <p className="px-3 py-2 text-sm text-neutral-500">
                                  No tags yet. Create one from the sidebar.
                                </p>
                              )}
                            </div>
                          </div>
                        )}
                      </div>

                      {/* Run Status Dropdown */}
                      <div className="relative">
                        <button
                          onClick={() => setShowRunStatusMenu(!showRunStatusMenu)}
                          className={`inline-flex items-center gap-2 rounded-lg border px-4 py-2 text-sm font-medium ${
                            localProduct.run_status?.status === 'completed'
                              ? 'border-green-300 bg-green-50 text-green-700'
                              : localProduct.run_status?.status === 'running'
                              ? 'border-blue-300 bg-blue-50 text-blue-700'
                              : localProduct.run_status?.status === 'want_to_run'
                              ? 'border-amber-300 bg-amber-50 text-amber-700'
                              : 'border-neutral-300 bg-white text-neutral-700 hover:bg-neutral-50'
                          }`}
                        >
                          {localProduct.run_status?.status === 'completed' ? (
                            <CheckCircle className="h-4 w-4" />
                          ) : localProduct.run_status?.status === 'running' ? (
                            <Play className="h-4 w-4" />
                          ) : localProduct.run_status?.status === 'want_to_run' ? (
                            <Bookmark className="h-4 w-4" />
                          ) : (
                            <Play className="h-4 w-4" />
                          )}
                          {localProduct.run_status?.status === 'completed'
                            ? 'Completed'
                            : localProduct.run_status?.status === 'running'
                            ? 'Running'
                            : localProduct.run_status?.status === 'want_to_run'
                            ? 'Want to Run'
                            : 'Run Status'}
                          <ChevronDown className="h-4 w-4" />
                        </button>

                        {showRunStatusMenu && (
                          <div className="absolute right-0 top-full mt-1 w-72 rounded-md border shadow-sm z-10" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
                            <div className="p-2 space-y-1">
                              <p className="px-2 py-1 text-xs text-neutral-500 uppercase tracking-wide">Status</p>
                              <button
                                onClick={() => updateRunStatusMutation.mutate({ run_status: 'want_to_run' })}
                                className={`w-full flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-left ${
                                  localProduct.run_status?.status === 'want_to_run' ? 'bg-amber-50 text-amber-700' : 'hover:bg-neutral-50'
                                }`}
                              >
                                <Bookmark className="h-4 w-4" />
                                Want to Run
                              </button>
                              <button
                                onClick={() => updateRunStatusMutation.mutate({ run_status: 'running' })}
                                className={`w-full flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-left ${
                                  localProduct.run_status?.status === 'running' ? 'bg-blue-50 text-blue-700' : 'hover:bg-neutral-50'
                                }`}
                              >
                                <Play className="h-4 w-4" />
                                Currently Running
                              </button>
                              <button
                                onClick={() => updateRunStatusMutation.mutate({ run_status: 'completed' })}
                                className={`w-full flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-left ${
                                  localProduct.run_status?.status === 'completed' ? 'bg-green-50 text-green-700' : 'hover:bg-neutral-50'
                                }`}
                              >
                                <CheckCircle className="h-4 w-4" />
                                Completed
                              </button>
                            </div>

                            {localProduct.run_status?.status === 'completed' && (
                              <>
                                <div className="border-t border-neutral-100 p-2 space-y-1">
                                  <p className="px-2 py-1 text-xs text-neutral-500 uppercase tracking-wide">Rating</p>
                                  <div className="flex gap-1 px-2">
                                    {[1, 2, 3, 4, 5].map((rating) => (
                                      <button
                                        key={rating}
                                        onClick={() => updateRunStatusMutation.mutate({ run_rating: rating })}
                                        className={`p-1 rounded ${
                                          localProduct.run_status?.rating && localProduct.run_status.rating >= rating
                                            ? 'text-amber-500'
                                            : 'text-neutral-300 hover:text-amber-400'
                                        }`}
                                      >
                                        <Star className="h-5 w-5 fill-current" />
                                      </button>
                                    ))}
                                  </div>
                                </div>

                                <div className="border-t border-neutral-100 p-2 space-y-1">
                                  <p className="px-2 py-1 text-xs text-neutral-500 uppercase tracking-wide">Difficulty</p>
                                  <div className="flex gap-1 px-2">
                                    {(['easier', 'as_written', 'harder'] as const).map((diff) => (
                                      <button
                                        key={diff}
                                        onClick={() => updateRunStatusMutation.mutate({ run_difficulty: diff })}
                                        className={`px-3 py-1.5 rounded-lg text-xs font-medium ${
                                          localProduct.run_status?.difficulty === diff
                                            ? 'bg-purple-100 text-purple-700'
                                            : 'bg-neutral-100 text-neutral-600 hover:bg-neutral-200'
                                        }`}
                                      >
                                        {diff === 'easier' ? 'Easier' : diff === 'as_written' ? 'As Written' : 'Harder'}
                                      </button>
                                    ))}
                                  </div>
                                </div>
                              </>
                            )}

                            {localProduct.run_status && (
                              <div className="border-t border-neutral-100 p-2">
                                <button
                                  onClick={() => clearRunStatusMutation.mutate()}
                                  disabled={clearRunStatusMutation.isPending}
                                  className="w-full flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm text-red-600 hover:bg-red-50"
                                >
                                  Clear Run Status
                                </button>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
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
                {failedQueueItems && failedQueueItems.length > 0 && (
                  <div className="flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full bg-red-500" />
                    <span className="text-sm text-red-600">
                      {failedQueueItems.length} failed task{failedQueueItems.length > 1 ? 's' : ''}
                    </span>
                  </div>
                )}
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
                {localProduct.processing_status?.text_extracted && (
                  <div className="flex items-center gap-2">
                    <select
                      value={bestiaryProfile}
                      onChange={(e) => setBestiaryProfile(e.target.value as 'dcc' | 'osr')}
                      className="rounded border border-neutral-300 px-2 py-1.5 text-sm"
                    >
                      <option value="dcc">DCC</option>
                      <option value="osr">OSR</option>
                    </select>
                    <button
                      onClick={() => { setBestiaryMessage(null); bestiaryMutation.mutate(); }}
                      disabled={bestiaryMutation.isPending}
                      className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
                    >
                      {bestiaryMutation.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Skull className="h-4 w-4" />
                      )}
                      Extract as Bestiary
                    </button>
                  </div>
                )}
              </div>

              {bestiaryMessage && (
                <div className="mb-4 rounded-lg border p-3 text-sm"
                  style={{ borderColor: 'var(--color-border)' }}>
                  {bestiaryMessage}
                </div>
              )}

              {failedQueueItems && failedQueueItems.length > 0 && (
                <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3">
                  <p className="text-sm font-medium text-red-800 mb-2">Processing Errors</p>
                  {failedQueueItems.map((item: any) => (
                    <div key={item.id} className="flex items-start justify-between gap-2 mb-1 last:mb-0">
                      <div className="flex-1">
                        <span className="text-xs font-medium text-red-700">{item.task_type}:</span>
                        <span className="ml-1 text-xs text-red-600">{item.error_message}</span>
                      </div>
                      <button
                        onClick={() => navigator.clipboard.writeText(item.error_message || '')}
                        className="shrink-0 text-xs text-red-500 hover:text-red-700 underline"
                      >
                        Copy
                      </button>
                    </div>
                  ))}
                </div>
              )}

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
                <div className="prose max-w-prose mx-auto">
                  <pre className="whitespace-pre-wrap text-lg leading-relaxed" style={{ fontFamily: 'var(--font-serif)', color: 'var(--color-text-primary)' }}>
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
                <h3 className="text-lg font-semibold mb-2" style={{ color: 'var(--color-text-primary)' }}>Extract Structured Content</h3>
                <p className="text-sm mb-4" style={{ color: 'var(--color-text-secondary)' }}>
                  Use AI to extract monsters, spells, magic items, and NPCs from this product.
                </p>
                <button
                  onClick={() => extractMutation.mutate({ monsters: true, spells: true, items: true, npcs: true })}
                  disabled={extractMutation.isPending || !localProduct.processing_status?.text_extracted}
                  className="inline-flex items-center gap-2 rounded-md px-4 py-2 text-base font-medium disabled:opacity-50 transition-colors"
                  style={{ backgroundColor: 'var(--color-accent)', color: '#fff' }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-accent-hover)')}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-accent)')}
                >
                  {extractMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Wand2 className="h-4 w-4" />
                  )}
                  Extract All Content
                </button>
                {!localProduct.processing_status?.text_extracted && (
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
                    <div className="rounded-md border p-4" style={{ borderColor: 'var(--color-border)' }}>
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
                    <div className="rounded-md border p-4" style={{ borderColor: 'var(--color-border)' }}>
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
                    <div className="rounded-md border p-4" style={{ borderColor: 'var(--color-border)' }}>
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
                    <div className="rounded-md border p-4" style={{ borderColor: 'var(--color-border)' }}>
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
              <h3 className="text-lg font-semibold mb-2" style={{ color: 'var(--color-text-primary)' }}>Export Content</h3>
              <p className="text-sm mb-6" style={{ color: 'var(--color-text-secondary)' }}>
                Export extracted content to various formats for use in other tools.
              </p>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="rounded-md border p-4" style={{ borderColor: 'var(--color-border)' }}>
                  <h4 className="font-medium mb-1" style={{ color: 'var(--color-text-primary)' }}>Foundry VTT</h4>
                  <p className="text-sm mb-3" style={{ color: 'var(--color-text-secondary)' }}>
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

                <div className="rounded-md border p-4" style={{ borderColor: 'var(--color-border)' }}>
                  <h4 className="font-medium mb-1" style={{ color: 'var(--color-text-primary)' }}>Obsidian Markdown</h4>
                  <p className="text-sm mb-3" style={{ color: 'var(--color-text-secondary)' }}>
                    Export content as Obsidian-compatible markdown with YAML frontmatter.
                  </p>
                  <button
                    onClick={() => exportObsidianMutation.mutate()}
                    disabled={exportObsidianMutation.isPending || !product.processing_status?.text_extracted}
                    className="inline-flex items-center gap-2 rounded-md px-4 py-2 text-base font-medium disabled:opacity-50 transition-colors"
                    style={{ backgroundColor: 'var(--color-accent)', color: '#fff' }}
                    onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-accent-hover)')}
                    onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-accent)')}
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
          ) : activeTab === 'notes' ? (
            <div
              role="tabpanel"
              id="panel-notes"
              aria-labelledby="tab-notes"
              className="p-6"
            >
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>GM Notes</h3>
                <button
                  onClick={() => openNoteEditor()}
                  className="inline-flex items-center gap-2 rounded-md px-4 py-2 text-base font-medium transition-colors"
                  style={{ backgroundColor: 'var(--color-accent)', color: '#fff' }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-accent-hover)')}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-accent)')}
                >
                  <Plus className="h-4 w-4" />
                  Add Note
                </button>
              </div>

              <p className="text-sm mb-6" style={{ color: 'var(--color-text-secondary)' }}>
                Record your prep tips, modifications, warnings, and reviews for this adventure.
              </p>

              {runNotes && runNotes.length > 0 ? (
                <div className="space-y-4">
                  {runNotes.map((note) => (
                    <div key={note.id} className="rounded-lg border border-neutral-200 p-4">
                      <div className="flex items-start justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                            note.note_type === 'prep_tip' ? 'bg-blue-100 text-blue-700' :
                            note.note_type === 'modification' ? 'bg-purple-100 text-purple-700' :
                            note.note_type === 'warning' ? 'bg-amber-100 text-amber-700' :
                            'bg-green-100 text-green-700'
                          }`}>
                            {note.note_type === 'prep_tip' ? 'Prep Tip' :
                             note.note_type === 'modification' ? 'Modification' :
                             note.note_type === 'warning' ? 'Warning' : 'Review'}
                          </span>
                          {note.spoiler_level !== 'none' && (
                            <span className="px-2 py-0.5 rounded text-xs bg-red-100 text-red-700">
                              {note.spoiler_level} spoilers
                            </span>
                          )}
                          {note.shared_to_codex && (
                            <span className="px-2 py-0.5 rounded text-xs bg-neutral-100 text-neutral-600">
                              Shared
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => openNoteEditor(note)}
                            className="p-1 text-neutral-400 hover:text-purple-600"
                            title="Edit note"
                          >
                            <Edit3 className="h-4 w-4" />
                          </button>
                          <button
                            onClick={() => {
                              if (confirm('Delete this note?')) {
                                deleteNoteMutation.mutate(note.id);
                              }
                            }}
                            className="p-1 text-neutral-400 hover:text-red-600"
                            title="Delete note"
                          >
                            <X className="h-4 w-4" />
                          </button>
                        </div>
                      </div>
                      <h4 className="font-medium mb-1" style={{ color: 'var(--color-text-primary)' }}>{note.title}</h4>
                      <p className="text-sm text-neutral-600 whitespace-pre-wrap">{note.content}</p>
                      <p className="text-xs text-neutral-400 mt-2">
                        {new Date(note.created_at).toLocaleDateString()}
                      </p>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-12 text-neutral-500">
                  <FileText className="mx-auto h-12 w-12 text-neutral-300 mb-3" />
                  <p className="font-medium">No notes yet</p>
                  <p className="text-sm mt-1">Add your first GM note for this adventure</p>
                </div>
              )}

              {/* Note Editor Modal */}
              {showNoteEditor && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
                  <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-xl max-h-[90vh] overflow-y-auto">
                    <div className="flex items-center justify-between mb-4">
                      <h3 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                        {editingNote ? 'Edit Note' : 'Add Note'}
                      </h3>
                      <button
                        onClick={() => {
                          setShowNoteEditor(false);
                          setEditingNote(null);
                          resetNoteForm();
                        }}
                        className="text-neutral-400 hover:text-neutral-600"
                      >
                        <X className="h-5 w-5" />
                      </button>
                    </div>

                    <div className="space-y-4">
                      <div>
                        <label className="block text-sm font-medium text-neutral-700 mb-1">Type</label>
                        <select
                          value={noteForm.note_type}
                          onChange={(e) => setNoteForm({ ...noteForm, note_type: e.target.value as typeof noteForm.note_type })}
                          className="w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm"
                        >
                          <option value="prep_tip">Prep Tip</option>
                          <option value="modification">Modification</option>
                          <option value="warning">Warning</option>
                          <option value="review">Review</option>
                        </select>
                      </div>

                      <div>
                        <label className="block text-sm font-medium text-neutral-700 mb-1">Title</label>
                        <input
                          type="text"
                          value={noteForm.title}
                          onChange={(e) => setNoteForm({ ...noteForm, title: e.target.value })}
                          className="w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm"
                          placeholder="Brief title for your note"
                        />
                      </div>

                      <div>
                        <label className="block text-sm font-medium text-neutral-700 mb-1">Content</label>
                        <textarea
                          value={noteForm.content}
                          onChange={(e) => setNoteForm({ ...noteForm, content: e.target.value })}
                          rows={6}
                          className="w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm"
                          placeholder="Your note content..."
                        />
                      </div>

                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-sm font-medium text-neutral-700 mb-1">Spoiler Level</label>
                          <select
                            value={noteForm.spoiler_level}
                            onChange={(e) => setNoteForm({ ...noteForm, spoiler_level: e.target.value as typeof noteForm.spoiler_level })}
                            className="w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm"
                          >
                            <option value="none">None</option>
                            <option value="minor">Minor</option>
                            <option value="major">Major</option>
                            <option value="endgame">Endgame</option>
                          </select>
                        </div>

                        <div>
                          <label className="block text-sm font-medium text-neutral-700 mb-1">Visibility</label>
                          <select
                            value={noteForm.visibility}
                            onChange={(e) => setNoteForm({ ...noteForm, visibility: e.target.value as typeof noteForm.visibility })}
                            className="w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm"
                          >
                            <option value="private">Private</option>
                            <option value="anonymous">Anonymous (for sharing)</option>
                            <option value="public">Public (for sharing)</option>
                          </select>
                        </div>
                      </div>

                      <div className="flex justify-end gap-3 pt-4">
                        <button
                          onClick={() => {
                            setShowNoteEditor(false);
                            setEditingNote(null);
                            resetNoteForm();
                          }}
                          className="rounded-lg border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
                        >
                          Cancel
                        </button>
                        <button
                          onClick={handleNoteSave}
                          disabled={!noteForm.title || !noteForm.content || createNoteMutation.isPending || updateNoteMutation.isPending}
                          className="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
                        >
                          {createNoteMutation.isPending || updateNoteMutation.isPending ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : editingNote ? 'Update' : 'Save'}
                        </button>
                      </div>
                    </div>
                  </div>
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
