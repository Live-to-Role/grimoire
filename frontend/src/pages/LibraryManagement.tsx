import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  Brain,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  ExternalLink,
  FileText,
  Filter,
  HardDrive,
  Info,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  Trash2,
  Wand2,
  X,
} from 'lucide-react';
import apiClient from '../api/client';
import { useQueueStatus } from '../hooks/useQueueStatus';
import { useProcessingControls } from '../hooks/useProcessingControls';

interface LibraryStats {
  total_products: number;
  total_size_bytes: number;
  total_size_mb: number;
  total_size_gb: number;
  duplicates: number;
  missing: number;
  excluded: number;
  processing: {
    covers_extracted: number;
    text_extracted: number;
    ai_identified: number;
    ai_identify_failed?: number;
  };
}

interface DuplicateGroup {
  file_hash: string;
  canonical: {
    id: number;
    title: string;
    file_path: string;
    file_size: number;
  };
  duplicates: Array<{
    id: number;
    title: string;
    file_path: string;
    file_size: number;
  }>;
  duplicate_count: number;
  wasted_space_bytes: number;
}

interface DuplicateStats {
  total_products: number;
  duplicate_count: number;
  unique_duplicate_groups: number;
  wasted_space_bytes: number;
  wasted_space_mb: number;
  revision_candidates: number;
}

interface RevisionGroup {
  normalized_stem: string;
  newer: { id: number; title: string; file_name: string; file_path: string } | null;
  older: { id: number; title: string; file_name: string; file_path: string }[];
}

interface ExclusionRule {
  id: number;
  rule_type: string;
  pattern: string;
  description: string | null;
  enabled: boolean;
  is_default: boolean;
  priority: number;
  files_excluded: number;
  last_matched_at: string | null;
  created_at: string;
}

interface ScanStatus {
  id: number;
  status: string;
  current_phase: string | null;
  current_file: string | null;
  progress: {
    total_files: number;
    processed_files: number;
    percent: number;
  };
  results: {
    new_products: number;
    updated_products: number;
    duplicates_found: number;
    excluded_files: number;
    errors: number;
  };
  started_at: string | null;
  completed_at: string | null;
  is_running: boolean;
}

type TabType = 'overview' | 'duplicates' | 'exclusions' | 'processing' | 'scan';

interface CostEstimate {
  provider: string;
  model: string;
  item_count: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number;
  is_free: boolean;
  products_with_text: number;
  products_without_text: number;
}

interface AIProviders {
  providers: {
    openai: boolean;
    anthropic: boolean;
    ollama: boolean;
  };
  any_available: boolean;
}

export function LibraryManagement() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<TabType>('overview');
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [selectedDuplicates, setSelectedDuplicates] = useState<Set<number>>(new Set());
  const [deleteFiles, setDeleteFiles] = useState(false);
  const [showAddRule, setShowAddRule] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState<{ type: 'selected' | 'group'; hash?: string } | null>(null);
  const [duplicateView, setDuplicateView] = useState<'hash' | 'revision'>('hash');
  const [newRule, setNewRule] = useState({
    rule_type: 'folder_name',
    pattern: '',
    description: '',
  });
  const [showCostConfirm, setShowCostConfirm] = useState<{
    type: 'identify';
    estimate: CostEstimate | null;
    provider: string;
  } | null>(null);
  const [selectedProvider, setSelectedProvider] = useState<string>('ollama');
  const [showPrivacyNotice, setShowPrivacyNotice] = useState(false);

  const { data: queueStatus } = useQueueStatus();
  const { resume } = useProcessingControls();

  const { data: stats } = useQuery({
    queryKey: ['library-management-stats'],
    queryFn: async () => {
      const res = await apiClient.get<LibraryStats>('/library/stats');
      return res.data;
    },
    refetchInterval: activeTab === 'processing' ? 5000 : false, // Refresh every 5s on processing tab
  });

  const { data: duplicateStats } = useQuery({
    queryKey: ['duplicate-stats'],
    queryFn: async () => {
      const res = await apiClient.get<DuplicateStats>('/duplicates/stats');
      return res.data;
    },
  });

  const { data: duplicateGroups } = useQuery({
    queryKey: ['duplicate-groups'],
    queryFn: async () => {
      const res = await apiClient.get<{ groups: DuplicateGroup[] }>('/duplicates');
      return res.data;
    },
    enabled: activeTab === 'duplicates',
  });

  const { data: exclusionRules } = useQuery({
    queryKey: ['exclusion-rules'],
    queryFn: async () => {
      const res = await apiClient.get<{ rules: ExclusionRule[] }>('/exclusions');
      return res.data;
    },
    enabled: activeTab === 'exclusions',
  });

  const { data: scanStatus, refetch: refetchScanStatus } = useQuery({
    queryKey: ['scan-status'],
    queryFn: async () => {
      const res = await apiClient.get<ScanStatus>('/library/scan/status');
      return res.data;
    },
    refetchInterval: (data) => (data?.state?.data?.is_running ? 2000 : false),
  });

  const { data: aiProviders } = useQuery<AIProviders>({
    queryKey: ['ai-providers'],
    queryFn: async () => {
      const res = await apiClient.get<AIProviders>('/ai/providers');
      return res.data;
    },
    enabled: activeTab === 'processing',
  });

  const { data: extractionStats } = useQuery({
    queryKey: ['text-extraction-stats'],
    queryFn: async () => {
      const res = await apiClient.get('/queue/text-extraction/stats');
      return res.data;
    },
    enabled: activeTab === 'processing',
    refetchInterval: 10000, // Refresh every 10 seconds
  });

  const { data: ftsStats } = useQuery({
    queryKey: ['fts-stats'],
    queryFn: async () => {
      const res = await apiClient.get('/queue/fts/stats');
      return res.data;
    },
    enabled: activeTab === 'processing',
    refetchInterval: 10000,
  });

  const rebuildFtsMutation = useMutation({
    mutationFn: async () => {
      const res = await apiClient.post('/queue/fts/rebuild-all');
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['fts-stats'] });
    },
  });

  const { data: embeddingStats } = useQuery({
    queryKey: ['embedding-stats'],
    queryFn: async () => {
      const res = await apiClient.get('/semantic/status');
      return res.data;
    },
    enabled: activeTab === 'processing',
    refetchInterval: 10000,
  });

  const embedAllMutation = useMutation({
    mutationFn: async () => {
      const res = await apiClient.post('/semantic/embed-all');
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['embedding-stats'] });
    },
  });

  const { data: appSettings } = useQuery({
    queryKey: ['app-settings'],
    queryFn: async () => {
      const res = await apiClient.get('/settings');
      return res.data;
    },
  });

  const updateSettingMutation = useMutation({
    mutationFn: async ({ key, value }: { key: string; value: unknown }) => {
      await apiClient.patch('/settings', { [key]: value });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['app-settings'] });
      queryClient.invalidateQueries({ queryKey: ['semantic-search-status'] });
    },
  });

  const scanMutation = useMutation({
    mutationFn: async () => {
      await apiClient.post('/library/scan');
    },
    onSuccess: () => {
      refetchScanStatus();
    },
  });

  const scanDuplicatesMutation = useMutation({
    mutationFn: async () => {
      await apiClient.post('/duplicates/scan?scan_type=all');
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['duplicate-stats'] });
      queryClient.invalidateQueries({ queryKey: ['duplicate-groups'] });
      queryClient.invalidateQueries({ queryKey: ['revision-groups'] });
    },
  });

  const { data: revisionGroups } = useQuery<RevisionGroup[]>({
    queryKey: ['revision-groups'],
    queryFn: async () => {
      const res = await apiClient.get<RevisionGroup[]>('/duplicates?type=revision');
      return res.data;
    },
  });

  const confirmRevisionMutation = useMutation({
    mutationFn: (productId: number) => apiClient.post(`/duplicates/${productId}/confirm-revision`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['revision-groups'] });
      queryClient.invalidateQueries({ queryKey: ['duplicate-stats'] });
      queryClient.invalidateQueries({ queryKey: ['products'] });
    },
  });

  const dismissRevisionMutation = useMutation({
    mutationFn: (productId: number) => apiClient.post(`/duplicates/${productId}/dismiss-revision`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['revision-groups'] });
      queryClient.invalidateQueries({ queryKey: ['duplicate-stats'] });
    },
  });

  const toggleRuleMutation = useMutation({
    mutationFn: async ({ id, enabled }: { id: number; enabled: boolean }) => {
      await apiClient.put(`/exclusions/${id}`, { enabled });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['exclusion-rules'] });
    },
  });

  const deleteRuleMutation = useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/exclusions/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['exclusion-rules'] });
    },
  });

  const createRuleMutation = useMutation({
    mutationFn: async (data: typeof newRule) => {
      await apiClient.post('/exclusions', data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['exclusion-rules'] });
      setShowAddRule(false);
      setNewRule({ rule_type: 'folder_name', pattern: '', description: '' });
    },
  });

  const bulkDeleteMutation = useMutation({
    mutationFn: async ({ productIds, deleteFiles }: { productIds: number[]; deleteFiles: boolean }) => {
      const res = await apiClient.post('/duplicates/bulk-delete', {
        product_ids: productIds,
        delete_files: deleteFiles,
      });
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['duplicate-groups'] });
      queryClient.invalidateQueries({ queryKey: ['duplicate-stats'] });
      queryClient.invalidateQueries({ queryKey: ['library-management-stats'] });
      setSelectedDuplicates(new Set());
      setShowDeleteConfirm(null);
    },
  });

  const deleteGroupMutation = useMutation({
    mutationFn: async ({ hash, deleteFiles }: { hash: string; deleteFiles: boolean }) => {
      const res = await apiClient.post(`/duplicates/group/${encodeURIComponent(hash)}/delete-duplicates?delete_files=${deleteFiles}`);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['duplicate-groups'] });
      queryClient.invalidateQueries({ queryKey: ['duplicate-stats'] });
      queryClient.invalidateQueries({ queryKey: ['library-management-stats'] });
      setShowDeleteConfirm(null);
    },
  });

  const queueAllForExtractionMutation = useMutation({
    mutationFn: async () => {
      const res = await apiClient.post('/queue/text-extraction/queue-all');
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['library-management-stats'] });
      queryClient.invalidateQueries({ queryKey: ['text-extraction-stats'] });
    },
  });

  const identifyAllMutation = useMutation({
    mutationFn: async (provider: string) => {
      const res = await apiClient.post('/ai/identify-all', {}, {
        params: { provider },
      });
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['library-management-stats'] });
      setShowCostConfirm(null);
    },
  });

  const estimateCostMutation = useMutation({
    mutationFn: async (provider: string) => {
      // Get all products without AI identification that have text extracted
      const res = await apiClient.get('/products', {
        params: { text_extracted: true, ai_identified: false, per_page: 10000 },
      });
      const productIds = res.data.items.map((p: { id: number }) => p.id);

      if (productIds.length === 0) {
        return null;
      }

      const costRes = await apiClient.post<CostEstimate>('/ai/estimate-cost', {
        product_ids: productIds,
        provider,
        task_type: 'identify',
      });
      return costRes.data;
    },
  });

  const toggleDuplicateSelection = (id: number) => {
    const newSelected = new Set(selectedDuplicates);
    if (newSelected.has(id)) {
      newSelected.delete(id);
    } else {
      newSelected.add(id);
    }
    setSelectedDuplicates(newSelected);
  };

  const selectAllInGroup = (group: DuplicateGroup) => {
    const newSelected = new Set(selectedDuplicates);
    group.duplicates.forEach(dup => newSelected.add(dup.id));
    setSelectedDuplicates(newSelected);
  };

  const deselectAllInGroup = (group: DuplicateGroup) => {
    const newSelected = new Set(selectedDuplicates);
    group.duplicates.forEach(dup => newSelected.delete(dup.id));
    setSelectedDuplicates(newSelected);
  };

  const selectAllDuplicates = () => {
    if (!duplicateGroups?.groups) return;
    const allIds = duplicateGroups.groups.flatMap(g => g.duplicates.map(d => d.id));
    setSelectedDuplicates(new Set(allIds));
  };

  const getSelectedSize = () => {
    if (!duplicateGroups?.groups) return 0;
    let size = 0;
    duplicateGroups.groups.forEach(group => {
      group.duplicates.forEach(dup => {
        if (selectedDuplicates.has(dup.id)) {
          size += dup.file_size;
        }
      });
    });
    return size;
  };

  const formatBytes = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  };

  const toggleGroup = (hash: string) => {
    const newExpanded = new Set(expandedGroups);
    if (newExpanded.has(hash)) {
      newExpanded.delete(hash);
    } else {
      newExpanded.add(hash);
    }
    setExpandedGroups(newExpanded);
  };

  const tabs = [
    { id: 'overview' as const, label: 'Overview', icon: HardDrive },
    { id: 'duplicates' as const, label: 'Duplicates', icon: Copy },
    { id: 'exclusions' as const, label: 'Exclusion Rules', icon: Filter },
    { id: 'processing' as const, label: 'Processing', icon: Wand2 },
    { id: 'scan' as const, label: 'Scan', icon: RefreshCw },
  ];

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="border-b px-6 py-5" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
        <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text-primary)' }}>Library Management</h1>
        <p className="text-base mt-1" style={{ color: 'var(--color-text-secondary)' }}>
          Manage duplicates, exclusion rules, and library scanning
        </p>
      </header>

      {/* Tabs */}
      <div className="border-b px-6" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
        <nav className="flex gap-6" style={{ height: '48px' }}>
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 border-b-2 px-1 text-lg font-medium transition-colors ${
                activeTab === tab.id
                  ? 'border-current'
                  : 'border-transparent'
              }`}
              style={{
                color: activeTab === tab.id ? 'var(--color-accent)' : 'var(--color-text-secondary)',
              }}
            >
              <tab.icon className="h-5 w-5" />
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      <main className="flex-1 overflow-auto p-6">
        {/* Overview Tab */}
        {activeTab === 'overview' && stats && (
          <div className="space-y-6">
            <div className="grid grid-cols-4 gap-4">
              <div className="rounded-xl border p-5" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
                <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>Total Products</p>
                <p className="text-2xl font-bold" style={{ color: 'var(--color-text-primary)' }}>{stats.total_products}</p>
              </div>
              <div className="rounded-xl border p-5" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
                <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>Total Size</p>
                <p className="text-2xl font-bold" style={{ color: 'var(--color-text-primary)' }}>{stats.total_size_gb} GB</p>
              </div>
              <div className="rounded-xl border p-5" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
                <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>Duplicates</p>
                <p className="text-2xl font-bold text-amber-600">{stats.duplicates}</p>
              </div>
              <div className="rounded-xl border p-5" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
                <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>Missing Files</p>
                <p className="text-2xl font-bold text-red-600">{stats.missing}</p>
              </div>
            </div>

            <div className="rounded-xl border p-6" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
              <h2 className="mb-4 text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>Processing Status</h2>
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-base" style={{ color: 'var(--color-text-secondary)' }}>Covers Extracted</span>
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-32 rounded-full" style={{ backgroundColor: 'var(--color-border)' }}>
                      <div
                        className="h-2 rounded-full bg-green-500"
                        style={{
                          width: `${(stats.processing.covers_extracted / stats.total_products) * 100}%`,
                        }}
                      />
                    </div>
                    <span className="text-base" style={{ color: 'var(--color-text-secondary)' }}>
                      {stats.processing.covers_extracted}/{stats.total_products}
                    </span>
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-base" style={{ color: 'var(--color-text-secondary)' }}>Text Extracted</span>
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-32 rounded-full" style={{ backgroundColor: 'var(--color-border)' }}>
                      <div
                        className="h-2 rounded-full bg-blue-500"
                        style={{
                          width: `${(stats.processing.text_extracted / stats.total_products) * 100}%`,
                        }}
                      />
                    </div>
                    <span className="text-base" style={{ color: 'var(--color-text-secondary)' }}>
                      {stats.processing.text_extracted}/{stats.total_products}
                    </span>
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-base" style={{ color: 'var(--color-text-secondary)' }}>AI Identified</span>
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-32 rounded-full" style={{ backgroundColor: 'var(--color-border)' }}>
                      <div
                        className="h-2 rounded-full transition-all"
                        style={{
                          backgroundColor: 'var(--color-accent)',
                          width: `${(stats.processing.ai_identified / stats.total_products) * 100}%`,
                        }}
                      />
                    </div>
                    <span className="text-base" style={{ color: 'var(--color-text-secondary)' }}>
                      {stats.processing.ai_identified}/{stats.total_products}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {duplicateStats && duplicateStats.wasted_space_mb > 0 && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="h-5 w-5 text-amber-600" />
                  <div>
                    <p className="font-medium text-amber-800">
                      {duplicateStats.duplicate_count} duplicate files detected
                    </p>
                    <p className="text-sm text-amber-700">
                      {duplicateStats.wasted_space_mb} MB could be saved by removing duplicates
                    </p>
                    <button
                      onClick={() => setActiveTab('duplicates')}
                      className="mt-2 text-sm font-medium text-amber-700 hover:text-amber-800"
                    >
                      View duplicates →
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Duplicates Tab */}
        {activeTab === 'duplicates' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>Duplicate Files</h2>
                {duplicateStats && (
                  <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>
                    {duplicateStats.unique_duplicate_groups} groups, {duplicateStats.wasted_space_mb} MB wasted
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => scanDuplicatesMutation.mutate()}
                  disabled={scanDuplicatesMutation.isPending}
                  className="inline-flex items-center gap-2 rounded-md border px-4 text-base font-medium disabled:opacity-50"
                  style={{ minHeight: '44px', borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)', color: 'var(--color-text-secondary)' }}
                >
                  <RefreshCw className={`h-4 w-4 ${scanDuplicatesMutation.isPending ? 'animate-spin' : ''}`} />
                  Re-scan
                </button>
                {duplicateGroups?.groups && duplicateGroups.groups.length > 0 && (
                  <button
                    onClick={selectAllDuplicates}
                    className="inline-flex items-center gap-2 rounded-md border px-4 text-base font-medium"
                    style={{ minHeight: '44px', borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)', color: 'var(--color-text-secondary)' }}
                  >
                    Select All
                  </button>
                )}
              </div>
            </div>

            {/* Sub-filter tabs */}
            <div className="flex gap-2">
              <button
                onClick={() => setDuplicateView('hash')}
                className="rounded-md border px-4 py-1.5 text-sm font-medium"
                style={{
                  background: duplicateView === 'hash' ? 'var(--color-primary)' : 'var(--color-surface)',
                  color: duplicateView === 'hash' ? 'var(--color-on-primary)' : 'var(--color-text)',
                  borderColor: 'var(--color-border)',
                }}
              >
                Duplicates {duplicateStats?.unique_duplicate_groups ? `(${duplicateStats.unique_duplicate_groups})` : ''}
              </button>
              <button
                onClick={() => setDuplicateView('revision')}
                className="rounded-md border px-4 py-1.5 text-sm font-medium"
                style={{
                  background: duplicateView === 'revision' ? 'var(--color-primary)' : 'var(--color-surface)',
                  color: duplicateView === 'revision' ? 'var(--color-on-primary)' : 'var(--color-text)',
                  borderColor: 'var(--color-border)',
                }}
              >
                Revisions {duplicateStats?.revision_candidates ? `(${duplicateStats.revision_candidates})` : ''}
              </button>
            </div>

            {/* Revisions View */}
            {duplicateView === 'revision' && (
              <div className="space-y-3">
                {!revisionGroups || revisionGroups.length === 0 ? (
                  <p style={{ color: 'var(--color-text-secondary)' }}>No revision candidates found.</p>
                ) : (
                  revisionGroups.map((group) => (
                    <div
                      key={group.normalized_stem}
                      className="rounded-lg border p-4"
                      style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface)' }}
                    >
                      <h4 className="mb-2 font-medium" style={{ color: 'var(--color-text)' }}>
                        {group.newer?.title || group.normalized_stem}
                      </h4>
                      {group.newer && (
                        <div className="mb-2 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                          <strong>Newer:</strong> {group.newer.file_name}
                        </div>
                      )}
                      {group.older.map((old) => (
                        <div
                          key={old.id}
                          className="flex items-center justify-between border-t py-2"
                          style={{ borderColor: 'var(--color-border)' }}
                        >
                          <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                            Older: {old.file_name}
                          </span>
                          <div className="flex gap-2">
                            <button
                              onClick={() => confirmRevisionMutation.mutate(old.id)}
                              disabled={confirmRevisionMutation.isPending}
                              className="rounded border-none px-3 py-1 text-sm text-white"
                              style={{ background: 'var(--color-success)' }}
                            >
                              Confirm
                            </button>
                            <button
                              onClick={() => dismissRevisionMutation.mutate(old.id)}
                              disabled={dismissRevisionMutation.isPending}
                              className="rounded border px-3 py-1 text-sm"
                              style={{ borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
                            >
                              Dismiss
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  ))
                )}
              </div>
            )}

            {/* Bulk Actions Bar */}
            {duplicateView === 'hash' && selectedDuplicates.size > 0 && (
              <div className="flex items-center justify-between rounded-md border p-4" style={{ borderColor: 'var(--color-accent)', backgroundColor: 'var(--color-accent-light)' }}>
                <div className="flex items-center gap-3">
                  <span className="text-base font-medium" style={{ color: 'var(--color-text-primary)' }}>
                    {selectedDuplicates.size} selected ({formatBytes(getSelectedSize())})
                  </span>
                  <button
                    onClick={() => setSelectedDuplicates(new Set())}
                    className="text-base"
                    style={{ color: 'var(--color-accent)' }}
                  >
                    Clear selection
                  </button>
                </div>
                <div className="flex items-center gap-2">
                  <label className="flex items-center gap-2 text-base" style={{ color: 'var(--color-accent)' }}>
                    <input
                      type="checkbox"
                      checked={deleteFiles}
                      onChange={(e) => setDeleteFiles(e.target.checked)}
                      className="rounded"
                    />
                    Delete files from disk
                  </label>
                  <button
                    onClick={() => setShowDeleteConfirm({ type: 'selected' })}
                    className="inline-flex items-center gap-2 rounded-md bg-red-600 px-4 text-base font-medium text-white hover:bg-red-700"
                    style={{ minHeight: '44px' }}
                  >
                    <Trash2 className="h-4 w-4" />
                    Delete Selected
                  </button>
                </div>
              </div>
            )}

            {duplicateView === 'hash' && duplicateGroups?.groups && duplicateGroups.groups.length > 0 ? (
              <div className="space-y-2">
                {duplicateGroups.groups.map((group) => (
                  <div
                    key={group.file_hash}
                    className="rounded-md border"
                    style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}
                  >
                    <button
                      onClick={() => toggleGroup(group.file_hash)}
                      className="flex w-full items-center justify-between p-4 text-left"
                      style={{ minHeight: '56px' }}
                    >
                      <div className="flex items-center gap-3">
                        {expandedGroups.has(group.file_hash) ? (
                          <ChevronDown className="h-4 w-4" style={{ color: 'var(--color-text-secondary)' }} />
                        ) : (
                          <ChevronRight className="h-4 w-4" style={{ color: 'var(--color-text-secondary)' }} />
                        )}
                        <div>
                          <p className="text-base font-medium" style={{ color: 'var(--color-text-primary)' }}>
                            {group.canonical.title}
                          </p>
                          <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                            {group.duplicate_count + 1} copies · {formatBytes(group.wasted_space_bytes)} wasted
                          </p>
                        </div>
                      </div>
                      <span className="rounded-full bg-amber-100 px-2 py-1 text-xs font-medium text-amber-700">
                        {group.duplicate_count} duplicates
                      </span>
                    </button>

                    {expandedGroups.has(group.file_hash) && (
                      <div className="border-t p-4" style={{ borderColor: 'var(--color-border)' }}>
                        <div className="mb-3 flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => selectAllInGroup(group)}
                              className="text-sm"
                              style={{ color: 'var(--color-accent)' }}
                            >
                              Select all in group
                            </button>
                            <span style={{ color: 'var(--color-border)' }}>|</span>
                            <button
                              onClick={() => deselectAllInGroup(group)}
                              className="text-sm"
                              style={{ color: 'var(--color-text-secondary)' }}
                            >
                              Deselect
                            </button>
                          </div>
                          <button
                            onClick={() => setShowDeleteConfirm({ type: 'group', hash: group.file_hash })}
                            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-sm font-medium text-red-600 hover:bg-red-50"
                          >
                            <Trash2 className="h-3 w-3" />
                            Remove all duplicates
                          </button>
                        </div>
                        <div className="space-y-2">
                          <div className="flex items-center gap-2 rounded-md bg-green-50 p-3" style={{ minHeight: '56px' }}>
                            <Check className="h-4 w-4 text-green-600" />
                            <div className="flex-1 min-w-0">
                              <p className="text-base font-medium text-green-800">
                                {group.canonical.title} (Keep)
                              </p>
                              <p className="text-sm text-green-600 truncate">
                                {group.canonical.file_path}
                              </p>
                            </div>
                            <span className="text-sm text-green-600">
                              {formatBytes(group.canonical.file_size)}
                            </span>
                          </div>

                          {group.duplicates.map((dup) => (
                            <div
                              key={dup.id}
                              className={`flex items-center gap-2 rounded-md p-3 cursor-pointer transition-colors ${
                                selectedDuplicates.has(dup.id)
                                  ? 'border'
                                  : ''
                              }`}
                              style={{
                                minHeight: '56px',
                                backgroundColor: selectedDuplicates.has(dup.id) ? 'var(--color-accent-light)' : 'var(--color-surface-raised)',
                                borderColor: selectedDuplicates.has(dup.id) ? 'var(--color-accent)' : undefined,
                              }}
                              onClick={() => toggleDuplicateSelection(dup.id)}
                            >
                              <input
                                type="checkbox"
                                checked={selectedDuplicates.has(dup.id)}
                                onChange={() => toggleDuplicateSelection(dup.id)}
                                onClick={(e) => e.stopPropagation()}
                                className="rounded"
                              />
                              <Copy className="h-4 w-4" style={{ color: 'var(--color-text-secondary)' }} />
                              <div className="flex-1 min-w-0">
                                <p className="text-base font-medium" style={{ color: 'var(--color-text-secondary)' }}>
                                  {dup.title}
                                </p>
                                <p className="text-sm truncate" style={{ color: 'var(--color-text-secondary)' }}>
                                  {dup.file_path}
                                </p>
                              </div>
                              <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                                {formatBytes(dup.file_size)}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : duplicateView === 'hash' ? (
              <div className="rounded-xl border p-8 text-center" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
                <Copy className="mx-auto h-12 w-12" style={{ color: 'var(--color-border)' }} />
                <p className="mt-2 text-base" style={{ color: 'var(--color-text-secondary)' }}>No duplicates found</p>
              </div>
            ) : null}
          </div>
        )}

        {/* Exclusions Tab */}
        {activeTab === 'exclusions' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>Exclusion Rules</h2>
                <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>
                  Files matching these rules will be skipped during scanning
                </p>
              </div>
              <button
                onClick={() => setShowAddRule(true)}
                className="inline-flex items-center gap-2 rounded-md px-4 text-base font-medium text-white"
                style={{ minHeight: '44px', backgroundColor: 'var(--color-accent)' }}
              >
                Add Rule
              </button>
            </div>

            {exclusionRules?.rules && exclusionRules.rules.length > 0 ? (
              <div className="rounded-xl border divide-y" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
                {exclusionRules.rules.map((rule) => (
                  <div key={rule.id} className="flex items-center justify-between p-4" style={{ minHeight: '56px', borderColor: 'var(--color-border)' }}>
                    <div className="flex items-center gap-4">
                      <button
                        onClick={() =>
                          toggleRuleMutation.mutate({ id: rule.id, enabled: !rule.enabled })
                        }
                        className="relative h-6 w-11 rounded-full transition-colors"
                        style={{ backgroundColor: rule.enabled ? 'var(--color-accent)' : 'var(--color-border)' }}
                      >
                        <span
                          className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
                            rule.enabled ? 'left-5' : 'left-0.5'
                          }`}
                        />
                      </button>
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="rounded-md px-2 py-0.5 text-xs font-medium" style={{ backgroundColor: 'var(--color-surface-raised)', color: 'var(--color-text-secondary)' }}>
                            {rule.rule_type}
                          </span>
                          <code className="text-base font-mono" style={{ color: 'var(--color-text-primary)' }}>{rule.pattern}</code>
                          {rule.is_default && (
                            <span className="rounded-md bg-blue-100 px-2 py-0.5 text-xs text-blue-700">
                              default
                            </span>
                          )}
                        </div>
                        {rule.description && (
                          <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>{rule.description}</p>
                        )}
                        <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                          {rule.files_excluded} files excluded
                        </p>
                      </div>
                    </div>
                    {!rule.is_default && (
                      <button
                        onClick={() => {
                          if (confirm('Delete this rule?')) {
                            deleteRuleMutation.mutate(rule.id);
                          }
                        }}
                        className="rounded-md p-2 hover:bg-red-50 hover:text-red-600"
                        style={{ color: 'var(--color-text-secondary)' }}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-xl border p-8 text-center" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
                <Filter className="mx-auto h-12 w-12" style={{ color: 'var(--color-border)' }} />
                <p className="mt-2 text-base" style={{ color: 'var(--color-text-secondary)' }}>No exclusion rules</p>
              </div>
            )}

            {/* Add Rule Modal */}
            {showAddRule && (
              <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
                <div className="w-full max-w-md rounded-xl p-6 shadow-xl" style={{ backgroundColor: 'var(--color-surface)' }}>
                  <div className="mb-4 flex items-center justify-between">
                    <h2 className="text-2xl font-semibold" style={{ color: 'var(--color-text-primary)' }}>Add Exclusion Rule</h2>
                    <button
                      onClick={() => setShowAddRule(false)}
                      style={{ color: 'var(--color-text-secondary)' }}
                    >
                      <X className="h-5 w-5" />
                    </button>
                  </div>

                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      createRuleMutation.mutate(newRule);
                    }}
                    className="space-y-4"
                  >
                    <div>
                      <label className="block text-lg font-medium" style={{ color: 'var(--color-text-secondary)' }}>
                        Rule Type
                      </label>
                      <select
                        value={newRule.rule_type}
                        onChange={(e) => setNewRule({ ...newRule, rule_type: e.target.value })}
                        className="mt-1 w-full rounded-md border px-3 text-base"
                        style={{ height: '48px', borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)', color: 'var(--color-text-primary)' }}
                      >
                        <option value="folder_name">Folder Name</option>
                        <option value="folder_path">Folder Path</option>
                        <option value="filename">Filename Pattern</option>
                        <option value="size_min">Minimum Size (bytes)</option>
                        <option value="size_max">Maximum Size (bytes)</option>
                        <option value="regex">Regex Pattern</option>
                      </select>
                    </div>

                    <div>
                      <label className="block text-lg font-medium" style={{ color: 'var(--color-text-secondary)' }}>
                        Pattern
                      </label>
                      <input
                        type="text"
                        value={newRule.pattern}
                        onChange={(e) => setNewRule({ ...newRule, pattern: e.target.value })}
                        required
                        placeholder={
                          newRule.rule_type === 'folder_name'
                            ? '__MACOSX'
                            : newRule.rule_type === 'filename'
                            ? '*.tmp'
                            : newRule.rule_type.startsWith('size')
                            ? '10240'
                            : ''
                        }
                        className="mt-1 w-full rounded-md border px-3 text-base"
                        style={{ height: '48px', borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)', color: 'var(--color-text-primary)' }}
                      />
                    </div>

                    <div>
                      <label className="block text-lg font-medium" style={{ color: 'var(--color-text-secondary)' }}>
                        Description
                      </label>
                      <input
                        type="text"
                        value={newRule.description}
                        onChange={(e) => setNewRule({ ...newRule, description: e.target.value })}
                        placeholder="Optional description"
                        className="mt-1 w-full rounded-md border px-3 text-base"
                        style={{ height: '48px', borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)', color: 'var(--color-text-primary)' }}
                      />
                    </div>

                    <div className="flex justify-end gap-3 pt-4">
                      <button
                        type="button"
                        onClick={() => setShowAddRule(false)}
                        className="rounded-md border px-4 text-base font-medium"
                        style={{ minHeight: '44px', borderColor: 'var(--color-border)', color: 'var(--color-text-secondary)' }}
                      >
                        Cancel
                      </button>
                      <button
                        type="submit"
                        disabled={createRuleMutation.isPending}
                        className="rounded-md px-4 text-base font-medium text-white disabled:opacity-50"
                        style={{ minHeight: '44px', backgroundColor: 'var(--color-accent)' }}
                      >
                        Add Rule
                      </button>
                    </div>
                  </form>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Processing Tab */}
        {activeTab === 'processing' && stats && (
          <div className="space-y-6">
            {/* Processing Settings */}
            <div className="rounded-xl border p-6" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
              <h2 className="text-lg font-semibold mb-4" style={{ color: 'var(--color-text-primary)' }}>Processing Settings</h2>

              <div className="grid gap-6 md:grid-cols-2">
                {/* Batch Size */}
                <div>
                  <label className="block text-lg font-medium mb-2" style={{ color: 'var(--color-text-secondary)' }}>
                    Batch Size
                  </label>
                  <select
                    value={appSettings?.extraction_batch_size || 100}
                    onChange={(e) => updateSettingMutation.mutate({
                      key: 'extraction_batch_size',
                      value: parseInt(e.target.value),
                    })}
                    className="w-full rounded-md border px-3 text-base"
                    style={{ height: '48px', borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)', color: 'var(--color-text-primary)' }}
                  >
                    <option value={50}>50 - More responsive, slower overall</option>
                    <option value={100}>100 - Balanced (recommended)</option>
                    <option value={200}>200 - Faster processing</option>
                    <option value={300}>300 - For powerful systems</option>
                    <option value={400}>400 - High performance</option>
                    <option value={500}>500 - Maximum batch</option>
                    <option value={10000}>Everything - Process all at once</option>
                  </select>
                  <p className="mt-1 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                    Smaller batches are more responsive but slower. Larger batches are faster but may use more memory.
                  </p>
                </div>

                {/* Continue on Close */}
                <div>
                  <label className="block text-lg font-medium mb-2" style={{ color: 'var(--color-text-secondary)' }}>
                    Continue Processing When Browser Closes
                  </label>
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => updateSettingMutation.mutate({
                        key: 'continue_on_close',
                        value: true,
                      })}
                      className="px-4 rounded-md text-base font-medium"
                      style={{
                        minHeight: '44px',
                        backgroundColor: (appSettings?.continue_on_close ?? true) ? 'var(--color-accent)' : 'var(--color-surface-raised)',
                        color: (appSettings?.continue_on_close ?? true) ? 'white' : 'var(--color-text-secondary)',
                      }}
                    >
                      Yes
                    </button>
                    <button
                      onClick={() => updateSettingMutation.mutate({
                        key: 'continue_on_close',
                        value: false,
                      })}
                      className="px-4 rounded-md text-base font-medium"
                      style={{
                        minHeight: '44px',
                        backgroundColor: appSettings?.continue_on_close === false ? 'var(--color-accent)' : 'var(--color-surface-raised)',
                        color: appSettings?.continue_on_close === false ? 'white' : 'var(--color-text-secondary)',
                      }}
                    >
                      No
                    </button>
                  </div>
                  <p className="mt-1 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                    If enabled, queue processing continues even if you close the browser.
                  </p>
                </div>
              </div>

              {/* Auto-processing during scan */}
              <div className="mt-6 pt-6 border-t" style={{ borderColor: 'var(--color-border)' }}>
                <h3 className="text-base font-medium mb-3" style={{ color: 'var(--color-text-primary)' }}>Auto-Processing During Library Scan</h3>
                <div className="space-y-3">
                  <label className="flex items-center gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={appSettings?.auto_extract_text_on_scan ?? false}
                      onChange={(e) => updateSettingMutation.mutate({
                        key: 'auto_extract_text_on_scan',
                        value: e.target.checked,
                      })}
                      className="h-4 w-4 rounded"
                    />
                    <div>
                      <span className="text-base font-medium" style={{ color: 'var(--color-text-primary)' }}>Auto-extract text on scan</span>
                      <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                        Automatically queue new products for text extraction when scanning library
                      </p>
                    </div>
                  </label>

                  <label className="flex items-center gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={appSettings?.auto_identify_on_scan ?? false}
                      onChange={(e) => updateSettingMutation.mutate({
                        key: 'auto_identify_on_scan',
                        value: e.target.checked,
                      })}
                      disabled={!appSettings?.auto_extract_text_on_scan}
                      className="h-4 w-4 rounded disabled:opacity-50"
                    />
                    <div className={!appSettings?.auto_extract_text_on_scan ? 'opacity-50' : ''}>
                      <span className="text-base font-medium" style={{ color: 'var(--color-text-primary)' }}>Auto-identify with AI on scan</span>
                      <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                        Automatically identify products after text extraction
                      </p>
                    </div>
                  </label>

                  {/* Provider Selection for Auto-Identify */}
                  {appSettings?.auto_identify_on_scan && appSettings?.auto_extract_text_on_scan && (
                    <div className="ml-7 mt-2 space-y-2">
                      <p className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>AI Provider for auto-identification:</p>
                      <div className="flex flex-wrap gap-2">
                        <button
                          onClick={() => updateSettingMutation.mutate({
                            key: 'auto_identify_provider',
                            value: 'ollama',
                          })}
                          className="inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium"
                          style={{
                            backgroundColor: (appSettings?.auto_identify_provider || 'ollama') === 'ollama' ? 'var(--color-accent)' : 'var(--color-surface-raised)',
                            color: (appSettings?.auto_identify_provider || 'ollama') === 'ollama' ? 'white' : 'var(--color-text-secondary)',
                          }}
                        >
                          Ollama
                          <span className="rounded px-1" style={{
                            backgroundColor: (appSettings?.auto_identify_provider || 'ollama') === 'ollama' ? 'var(--color-accent-hover)' : undefined,
                            color: (appSettings?.auto_identify_provider || 'ollama') === 'ollama' ? 'white' : undefined,
                          }}>{(appSettings?.auto_identify_provider || 'ollama') === 'ollama' ? 'Free' : ''}</span>
                          {(appSettings?.auto_identify_provider || 'ollama') !== 'ollama' && (
                            <span className="rounded px-1 bg-green-100 text-green-700">Free</span>
                          )}
                        </button>
                        <button
                          onClick={() => updateSettingMutation.mutate({
                            key: 'auto_identify_provider',
                            value: 'openai',
                          })}
                          disabled={!aiProviders?.providers.openai}
                          className="inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                          style={{
                            backgroundColor: appSettings?.auto_identify_provider === 'openai' ? 'var(--color-accent)' : 'var(--color-surface-raised)',
                            color: appSettings?.auto_identify_provider === 'openai' ? 'white' : 'var(--color-text-secondary)',
                          }}
                        >
                          OpenAI
                          {appSettings?.auto_identify_provider === 'openai' ? (
                            <span className="rounded px-1" style={{ backgroundColor: 'var(--color-accent-hover)', color: 'white' }}>Paid</span>
                          ) : (
                            <span className="rounded px-1 bg-amber-100 text-amber-700">Paid</span>
                          )}
                        </button>
                        <button
                          onClick={() => updateSettingMutation.mutate({
                            key: 'auto_identify_provider',
                            value: 'anthropic',
                          })}
                          disabled={!aiProviders?.providers.anthropic}
                          className="inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                          style={{
                            backgroundColor: appSettings?.auto_identify_provider === 'anthropic' ? 'var(--color-accent)' : 'var(--color-surface-raised)',
                            color: appSettings?.auto_identify_provider === 'anthropic' ? 'white' : 'var(--color-text-secondary)',
                          }}
                        >
                          Anthropic
                          {appSettings?.auto_identify_provider === 'anthropic' ? (
                            <span className="rounded px-1" style={{ backgroundColor: 'var(--color-accent-hover)', color: 'white' }}>Paid</span>
                          ) : (
                            <span className="rounded px-1 bg-amber-100 text-amber-700">Paid</span>
                          )}
                        </button>
                      </div>
                      {(appSettings?.auto_identify_provider === 'openai' || appSettings?.auto_identify_provider === 'anthropic') && (
                        <div className="rounded-md bg-amber-50 p-2 mt-2">
                          <p className="text-xs text-amber-800">
                            <AlertTriangle className="inline h-3 w-3 mr-1" />
                            <strong>Cost warning:</strong> Using {appSettings.auto_identify_provider} will incur API costs for each new product scanned.
                            Estimated ~$0.002-0.01 per product depending on text length.
                          </p>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {appSettings?.auto_extract_text_on_scan && (
                  <div className="mt-3 rounded-md bg-blue-50 p-3">
                    <p className="text-sm text-blue-800">
                      <Info className="inline h-4 w-4 mr-1" />
                      New products will be automatically queued for processing when you scan your library.
                      {appSettings?.auto_identify_on_scan && (
                        <>
                          {' '}AI identification will use {' '}
                          <strong>
                            {appSettings?.auto_identify_provider === 'openai' ? 'OpenAI' :
                             appSettings?.auto_identify_provider === 'anthropic' ? 'Anthropic' : 'Ollama'}
                          </strong>
                          {(appSettings?.auto_identify_provider || 'ollama') === 'ollama' ? ' (local, free)' : ' (cloud, paid)'}.
                        </>
                      )}
                    </p>
                  </div>
                )}
              </div>
            </div>

            {/* Queue Status */}
            {extractionStats && (extractionStats.queue_pending > 0 || extractionStats.queue_processing > 0) && (
              <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    {queueStatus?.paused ? (
                      <Pause className="h-5 w-5 text-blue-600" />
                    ) : (
                      <Loader2 className="h-5 w-5 animate-spin text-blue-600" />
                    )}
                    <div>
                      <p className="font-medium text-blue-900">
                        Queue: {extractionStats.queue_pending} pending, {extractionStats.queue_processing} processing
                      </p>
                      <p className="text-sm text-blue-700">
                        {queueStatus?.paused
                          ? 'Background processing is paused ("I\'m working"). Resume to start.'
                          : 'Processing in the background.'}
                      </p>
                    </div>
                  </div>
                  {queueStatus?.paused && (
                    <button
                      onClick={() => resume.mutate()}
                      disabled={resume.isPending}
                      className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 text-base font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                      style={{ minHeight: '44px' }}
                    >
                      {resume.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Play className="h-4 w-4" />
                      )}
                      Resume
                    </button>
                  )}
                </div>
              </div>
            )}

            {/* Text Extraction Section */}
            <div className="rounded-xl border p-6" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="text-lg font-semibold flex items-center gap-2" style={{ color: 'var(--color-text-primary)' }}>
                    <FileText className="h-5 w-5 text-blue-600" />
                    Text Extraction
                  </h2>
                  <p className="mt-1 text-base" style={{ color: 'var(--color-text-secondary)' }}>
                    Extract text from PDFs to enable searching and AI identification.
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-2xl font-bold" style={{ color: 'var(--color-text-primary)' }}>
                    {stats.processing.text_extracted} / {stats.total_products}
                  </p>
                  <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>products extracted</p>
                </div>
              </div>

              <div className="mt-4">
                <div className="h-2 rounded-full" style={{ backgroundColor: 'var(--color-border)' }}>
                  <div
                    className="h-2 rounded-full bg-blue-500 transition-all"
                    style={{
                      width: `${(stats.processing.text_extracted / stats.total_products) * 100}%`,
                    }}
                  />
                </div>
              </div>

              {stats.total_products - stats.processing.text_extracted > 0 && (
                <div className="mt-4 flex items-center justify-between rounded-md bg-blue-50 p-4">
                  <div>
                    <p className="font-medium text-blue-900">
                      {stats.total_products - stats.processing.text_extracted} products need text extraction
                    </p>
                    <p className="text-sm text-blue-700">
                      Products will be queued and processed in the background. You can also queue individual products from the library.
                    </p>
                  </div>
                  <button
                    onClick={() => queueAllForExtractionMutation.mutate()}
                    disabled={queueAllForExtractionMutation.isPending}
                    className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 text-base font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                    style={{ minHeight: '44px' }}
                  >
                    {queueAllForExtractionMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <FileText className="h-4 w-4" />
                    )}
                    Queue All for Extraction
                  </button>
                </div>
              )}

              {queueAllForExtractionMutation.isSuccess && (
                <div className="mt-4 rounded-md bg-green-50 p-4 text-green-800">
                  <p className="font-medium">Products queued for extraction!</p>
                  <p className="text-sm">
                    Queued {queueAllForExtractionMutation.data?.created || 0} products.
                    {queueAllForExtractionMutation.data?.skipped > 0 && ` ${queueAllForExtractionMutation.data.skipped} already queued.`}
                  </p>
                </div>
              )}
            </div>

            {/* Full-Text Search Indexing Section */}
            <div className="rounded-xl border p-6" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="text-lg font-semibold flex items-center gap-2" style={{ color: 'var(--color-text-primary)' }}>
                    <Wand2 className="h-5 w-5 text-green-600" />
                    Full-Text Search Index
                  </h2>
                  <p className="mt-1 text-base" style={{ color: 'var(--color-text-secondary)' }}>
                    Build search indexes for fast content search (e.g., "encounter table with kobolds").
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-2xl font-bold" style={{ color: 'var(--color-text-primary)' }}>
                    {ftsStats?.indexed || 0} / {ftsStats?.total_with_text || 0}
                  </p>
                  <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>products indexed</p>
                </div>
              </div>

              <div className="mt-4">
                <div className="h-2 rounded-full" style={{ backgroundColor: 'var(--color-border)' }}>
                  <div
                    className="h-2 rounded-full bg-green-500 transition-all"
                    style={{
                      width: `${ftsStats?.total_with_text ? (ftsStats.indexed / ftsStats.total_with_text) * 100 : 0}%`,
                    }}
                  />
                </div>
              </div>

              {ftsStats && ftsStats.need_indexing > 0 && (
                <div className="mt-4 flex items-center justify-between rounded-md bg-green-50 p-4">
                  <div>
                    <p className="font-medium text-green-900">
                      {ftsStats.need_indexing} products need FTS indexing
                    </p>
                    <p className="text-sm text-green-700">
                      Indexing enables fast full-text search across all extracted content.
                    </p>
                  </div>
                  <button
                    onClick={() => rebuildFtsMutation.mutate()}
                    disabled={rebuildFtsMutation.isPending}
                    className="inline-flex items-center gap-2 rounded-md bg-green-600 px-4 text-base font-medium text-white hover:bg-green-700 disabled:opacity-50"
                    style={{ minHeight: '44px' }}
                  >
                    {rebuildFtsMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Wand2 className="h-4 w-4" />
                    )}
                    Build Search Index
                  </button>
                </div>
              )}

              {rebuildFtsMutation.isSuccess && (
                <div className="mt-4 rounded-md bg-green-50 p-4 text-green-800">
                  <p className="font-medium">FTS indexing queued!</p>
                  <p className="text-sm">
                    Queued {rebuildFtsMutation.data?.created || 0} products for indexing.
                  </p>
                </div>
              )}

              {ftsStats?.indexed > 0 && ftsStats?.need_indexing === 0 && (
                <div className="mt-4 rounded-md bg-green-50 p-4 text-green-800">
                  <p className="font-medium">All products indexed!</p>
                  <p className="text-sm">
                    Full-text search is available for {ftsStats.indexed} products.
                  </p>
                </div>
              )}
            </div>

            {/* Semantic Search / Embeddings Section */}
            <div className="rounded-xl border p-6" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="text-lg font-semibold flex items-center gap-2" style={{ color: 'var(--color-text-primary)' }}>
                    <Brain className="h-5 w-5 text-indigo-600" />
                    Semantic Search (AI Embeddings)
                  </h2>
                  <p className="mt-1 text-base" style={{ color: 'var(--color-text-secondary)' }}>
                    Enable natural language search like "swamp adventures for level 3 parties".
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-2xl font-bold" style={{ color: 'var(--color-text-primary)' }}>
                    {embeddingStats?.embedded_products || 0} / {embeddingStats?.total_products || 0}
                  </p>
                  <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>products embedded</p>
                </div>
              </div>

              <div className="mt-4">
                <div className="h-2 rounded-full" style={{ backgroundColor: 'var(--color-border)' }}>
                  <div
                    className="h-2 rounded-full bg-indigo-500 transition-all"
                    style={{
                      width: `${embeddingStats?.coverage_percent || 0}%`,
                    }}
                  />
                </div>
              </div>

              <div className="mt-4 rounded-md p-4" style={{ backgroundColor: 'var(--color-surface-raised)' }}>
                <label className="block text-sm font-medium mb-2" style={{ color: 'var(--color-text-primary)' }}>
                  Search Provider
                </label>
                <p className="text-xs mb-2" style={{ color: 'var(--color-text-secondary)' }}>
                  Choose which provider embeds your search queries. This is separate from the provider used for product identification.
                </p>
                <p className="text-xs mb-2 font-medium" style={{ color: 'var(--color-warning, #b45309)' }}>
                  ⚠ Changing providers requires re-embedding all products, as each provider produces different vector formats.
                  Existing embeddings from a different provider will not be used in search results until re-embedded.
                </p>
                <select
                  value={appSettings?.semantic_search_provider || 'none'}
                  onChange={(e) => updateSettingMutation.mutate({ key: 'semantic_search_provider', value: e.target.value })}
                  className="rounded-md px-3 py-2 text-sm"
                  style={{
                    backgroundColor: 'var(--color-bg)',
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-text-primary)',
                  }}
                >
                  <option value="none">Disabled</option>
                  {embeddingStats?.providers?.ollama && <option value="ollama">Ollama</option>}
                  {embeddingStats?.providers?.openai && <option value="openai">OpenAI</option>}
                  {embeddingStats?.providers?.local && <option value="local">Local (sentence-transformers)</option>}
                </select>
              </div>

              {embeddingStats && embeddingStats.not_embedded > 0 && (
                <div className="mt-4 flex items-center justify-between rounded-md bg-indigo-50 p-4">
                  <div>
                    <p className="font-medium text-indigo-900">
                      {embeddingStats.not_embedded} products need embeddings
                    </p>
                    <p className="text-sm text-indigo-700">
                      Uses local AI (free), Ollama, or OpenAI for embedding generation.
                    </p>
                  </div>
                  <button
                    onClick={() => embedAllMutation.mutate()}
                    disabled={embedAllMutation.isPending || !embeddingStats.provider_available}
                    className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-4 text-base font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                    style={{ minHeight: '44px' }}
                  >
                    {embedAllMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <RefreshCw className="h-4 w-4" />
                    )}
                    Generate Embeddings
                  </button>
                </div>
              )}

              {embeddingStats && !embeddingStats.provider_available && (
                <div className="mt-4 flex items-start gap-3 rounded-md bg-amber-50 border border-amber-200 p-4">
                  <AlertTriangle className="h-5 w-5 text-amber-600 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="font-medium text-amber-800">No embedding provider available</p>
                    <p className="text-sm text-amber-700 mt-1">
                      Install <code className="bg-amber-100 px-1 rounded">sentence-transformers</code> for free local embeddings,
                      set <code className="bg-amber-100 px-1 rounded">OLLAMA_BASE_URL</code> with an embedding model,
                      or set <code className="bg-amber-100 px-1 rounded">OPENAI_API_KEY</code> for cloud embeddings.
                    </p>
                  </div>
                </div>
              )}

              {embeddingStats?.queue && embeddingStats.queue.failed > 0 && (
                <div className="mt-4 flex items-start gap-3 rounded-lg bg-red-50 border border-red-200 p-4">
                  <AlertTriangle className="h-5 w-5 text-red-600 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="font-medium text-red-800">
                      {embeddingStats.queue.failed} embedding task{embeddingStats.queue.failed !== 1 ? 's' : ''} failed
                    </p>
                    {embeddingStats.queue.last_error && (
                      <p className="text-sm text-red-700 mt-1">
                        Last error: {embeddingStats.queue.last_error}
                      </p>
                    )}
                  </div>
                </div>
              )}

              {embeddingStats?.queue && (embeddingStats.queue.pending > 0 || embeddingStats.queue.processing > 0) && (
                <div className="mt-4 flex items-center gap-3 rounded-lg bg-blue-50 border border-blue-200 p-4">
                  <Loader2 className="h-5 w-5 text-blue-600 animate-spin flex-shrink-0" />
                  <div>
                    <p className="font-medium text-blue-800">
                      Embedding in progress
                    </p>
                    <p className="text-sm text-blue-700">
                      {embeddingStats.queue.processing > 0 && `${embeddingStats.queue.processing} processing`}
                      {embeddingStats.queue.processing > 0 && embeddingStats.queue.pending > 0 && ', '}
                      {embeddingStats.queue.pending > 0 && `${embeddingStats.queue.pending} pending`}
                    </p>
                  </div>
                </div>
              )}

              {embedAllMutation.isError && (
                <div className="mt-4 rounded-md bg-red-50 border border-red-200 p-4 text-red-800">
                  <p className="font-medium">Failed to queue embeddings</p>
                  <p className="text-sm mt-1">
                    {(embedAllMutation.error as Error)?.message || 'Unknown error'}
                  </p>
                </div>
              )}

              {embedAllMutation.isSuccess && (
                <div className="mt-4 rounded-md bg-indigo-50 p-4 text-indigo-800">
                  <p className="font-medium">Embedding generation queued!</p>
                  <p className="text-sm">
                    Queued {embedAllMutation.data?.queued || 0} products for embedding.
                  </p>
                </div>
              )}

              {embeddingStats?.embedded_products > 0 && embeddingStats?.not_embedded === 0 && (
                <div className="mt-4 rounded-md bg-indigo-50 p-4 text-indigo-800">
                  <p className="font-medium">All products have embeddings!</p>
                  <p className="text-sm">
                    Semantic search is available for {embeddingStats.embedded_products} products.
                  </p>
                </div>
              )}

              <div className="mt-4 rounded-md p-4" style={{ backgroundColor: 'var(--color-surface-raised)' }}>
                <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>
                  <strong>Embedding providers</strong> generate vector representations for semantic search.
                  <strong> AI query</strong> uses Anthropic or OpenAI to interpret natural language searches.
                </p>
                {embeddingStats?.providers && (
                  <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                    <span className="font-medium" style={{ color: 'var(--color-text-secondary)' }}>Embeddings:</span>
                    <span className={embeddingStats.providers.local ? 'text-green-600' : ''} style={!embeddingStats.providers.local ? { color: 'var(--color-text-secondary)' } : undefined}>
                      Local: {embeddingStats.providers.local ? '✓ Available' : '✗ Not installed'}
                    </span>
                    <span className={embeddingStats.providers.ollama ? 'text-green-600' : ''} style={!embeddingStats.providers.ollama ? { color: 'var(--color-text-secondary)' } : undefined}>
                      Ollama: {embeddingStats.providers.ollama ? '✓ Available' : '✗ Not configured'}
                    </span>
                    <span className={embeddingStats.providers.openai ? 'text-green-600' : ''} style={!embeddingStats.providers.openai ? { color: 'var(--color-text-secondary)' } : undefined}>
                      OpenAI: {embeddingStats.providers.openai ? '✓ Configured' : '✗ No API key'}
                    </span>
                  </div>
                )}
                <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                  <span className="font-medium" style={{ color: 'var(--color-text-secondary)' }}>AI Query:</span>
                  <span className={embeddingStats?.anthropic_available ? 'text-green-600' : ''} style={!embeddingStats?.anthropic_available ? { color: 'var(--color-text-secondary)' } : undefined}>
                    Anthropic: {embeddingStats?.anthropic_available ? '✓ Configured' : '✗ No API key'}
                  </span>
                  <span className={embeddingStats?.providers?.openai ? 'text-green-600' : ''} style={!embeddingStats?.providers?.openai ? { color: 'var(--color-text-secondary)' } : undefined}>
                    OpenAI: {embeddingStats?.providers?.openai ? '✓ Configured' : '✗ No API key'}
                  </span>
                </div>
              </div>
            </div>

            {/* AI Identification Section */}
            <div className="rounded-xl border p-6" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="text-lg font-semibold flex items-center gap-2" style={{ color: 'var(--color-text-primary)' }}>
                    <Wand2 className="h-5 w-5" style={{ color: 'var(--color-accent)' }} />
                    AI Identification
                  </h2>
                  <p className="mt-1 text-base" style={{ color: 'var(--color-text-secondary)' }}>
                    Use AI to identify game system, publisher, and product type.
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-2xl font-bold" style={{ color: 'var(--color-text-primary)' }}>
                    {stats.processing.ai_identified} / {stats.total_products}
                  </p>
                  <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>products identified</p>
                </div>
              </div>

              <div className="mt-4">
                <div className="h-2 rounded-full" style={{ backgroundColor: 'var(--color-border)' }}>
                  <div
                    className="h-2 rounded-full transition-all"
                    style={{
                      backgroundColor: 'var(--color-accent)',
                      width: `${(stats.processing.ai_identified / stats.total_products) * 100}%`,
                    }}
                  />
                </div>
              </div>

              {/* Provider Selection */}
              <div className="mt-4 rounded-md border p-4" style={{ borderColor: 'var(--color-border)' }}>
                <h3 className="font-medium mb-3" style={{ color: 'var(--color-text-primary)' }}>AI Provider</h3>
                <div className="space-y-2">
                  <label className="flex items-center gap-3 cursor-pointer">
                    <input
                      type="radio"
                      name="provider"
                      value="ollama"
                      checked={selectedProvider === 'ollama'}
                      onChange={(e) => setSelectedProvider(e.target.value)}
                    />
                    <div className="flex-1">
                      <span className="font-medium" style={{ color: 'var(--color-text-primary)' }}>Ollama (Local)</span>
                      <span className="ml-2 rounded-md bg-green-100 px-2 py-0.5 text-xs text-green-700">Free</span>
                      {aiProviders?.providers.ollama && (
                        <span className="ml-2 text-xs text-green-600">● Connected</span>
                      )}
                    </div>
                  </label>
                  <label className="flex items-center gap-3 cursor-pointer">
                    <input
                      type="radio"
                      name="provider"
                      value="openai"
                      checked={selectedProvider === 'openai'}
                      onChange={(e) => setSelectedProvider(e.target.value)}
                      disabled={!aiProviders?.providers.openai}
                    />
                    <div className="flex-1">
                      <span className="font-medium" style={{ color: aiProviders?.providers.openai ? 'var(--color-text-primary)' : 'var(--color-text-secondary)' }}>
                        OpenAI (Cloud)
                      </span>
                      <span className="ml-2 rounded-md bg-amber-100 px-2 py-0.5 text-xs text-amber-700">Paid</span>
                      {!aiProviders?.providers.openai && (
                        <span className="ml-2 text-xs" style={{ color: 'var(--color-text-secondary)' }}>Not configured</span>
                      )}
                    </div>
                  </label>
                  <label className="flex items-center gap-3 cursor-pointer">
                    <input
                      type="radio"
                      name="provider"
                      value="anthropic"
                      checked={selectedProvider === 'anthropic'}
                      onChange={(e) => setSelectedProvider(e.target.value)}
                      disabled={!aiProviders?.providers.anthropic}
                    />
                    <div className="flex-1">
                      <span className="font-medium" style={{ color: aiProviders?.providers.anthropic ? 'var(--color-text-primary)' : 'var(--color-text-secondary)' }}>
                        Anthropic (Cloud)
                      </span>
                      <span className="ml-2 rounded-md bg-amber-100 px-2 py-0.5 text-xs text-amber-700">Paid</span>
                      {!aiProviders?.providers.anthropic && (
                        <span className="ml-2 text-xs" style={{ color: 'var(--color-text-secondary)' }}>Not configured</span>
                      )}
                    </div>
                  </label>
                </div>

                <button
                  onClick={() => setShowPrivacyNotice(true)}
                  className="mt-3 inline-flex items-center gap-1 text-base"
                  style={{ color: 'var(--color-text-secondary)' }}
                >
                  <Info className="h-4 w-4" />
                  View AI privacy information
                </button>
              </div>

              {/* Identify Button */}
              {(stats.processing.text_extracted - stats.processing.ai_identified) > 0 && (
                <div className="mt-4 flex items-center justify-between rounded-md p-4" style={{ backgroundColor: 'var(--color-accent-light)' }}>
                  <div>
                    <p className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
                      {stats.processing.text_extracted - stats.processing.ai_identified} products not yet identified
                      {(stats.processing.ai_identify_failed || 0) > 0 && (
                        <span className="text-sm font-normal" style={{ color: 'var(--color-text-secondary)' }}>
                          {' '}({stats.processing.ai_identify_failed} previously failed — may succeed with different provider)
                        </span>
                      )}
                    </p>
                    <p className="text-sm" style={{ color: 'var(--color-accent)' }}>
                      {selectedProvider === 'ollama'
                        ? 'Using Ollama (free, local processing)'
                        : `Using ${selectedProvider} (cloud, see cost estimate)`}
                    </p>
                  </div>
                  <button
                    onClick={async () => {
                      if (selectedProvider === 'ollama') {
                        identifyAllMutation.mutate(selectedProvider);
                      } else {
                        const estimate = await estimateCostMutation.mutateAsync(selectedProvider);
                        if (estimate) {
                          setShowCostConfirm({ type: 'identify', estimate, provider: selectedProvider });
                        }
                      }
                    }}
                    disabled={identifyAllMutation.isPending || estimateCostMutation.isPending}
                    className="inline-flex items-center gap-2 rounded-md px-4 text-base font-medium text-white disabled:opacity-50"
                    style={{ minHeight: '44px', backgroundColor: 'var(--color-accent)' }}
                  >
                    {(identifyAllMutation.isPending || estimateCostMutation.isPending) ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Wand2 className="h-4 w-4" />
                    )}
                    {selectedProvider === 'ollama' ? 'Identify All' : 'Estimate Cost & Identify'}
                  </button>
                </div>
              )}

              {stats.processing.text_extracted === 0 && (
                <div className="mt-4 rounded-md bg-amber-50 p-4">
                  <p className="text-amber-800">
                    <AlertTriangle className="inline h-4 w-4 mr-1" />
                    Text must be extracted before AI identification. Extract text first.
                  </p>
                </div>
              )}

              {identifyAllMutation.isSuccess && (
                <div className="mt-4 rounded-md bg-green-50 p-4 text-green-800">
                  <p className="font-medium">AI identification queued!</p>
                  <p className="text-sm">
                    Queued {identifyAllMutation.data?.queued || 0} products for identification.
                    {identifyAllMutation.data?.already_queued > 0 && ` ${identifyAllMutation.data.already_queued} already in queue.`}
                    {identifyAllMutation.data?.previously_failed > 0 && ` ${identifyAllMutation.data.previously_failed} previously failed (skipped).`}
                  </p>
                  <p className="text-sm mt-1">
                    Click "Process Batch Now" to start processing, or items will be processed in the background.
                  </p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Scan Tab */}
        {activeTab === 'scan' && (
          <div className="space-y-6">
            <div className="rounded-xl border p-6" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
              <h2 className="mb-4 text-lg font-semibold" style={{ color: 'var(--color-text-primary)' }}>Library Scan</h2>

              {scanStatus?.is_running ? (
                <div className="space-y-4">
                  <div className="flex items-center gap-3">
                    <RefreshCw className="h-5 w-5 animate-spin" style={{ color: 'var(--color-accent)' }} />
                    <div>
                      <p className="font-medium text-base" style={{ color: 'var(--color-text-primary)' }}>
                        {scanStatus.current_phase || 'Scanning...'}
                      </p>
                      {scanStatus.current_file && (
                        <p className="text-sm truncate max-w-md" style={{ color: 'var(--color-text-secondary)' }}>
                          {scanStatus.current_file}
                        </p>
                      )}
                    </div>
                  </div>

                  <div>
                    <div className="mb-1 flex justify-between text-base">
                      <span style={{ color: 'var(--color-text-secondary)' }}>Progress</span>
                      <span style={{ color: 'var(--color-text-secondary)' }}>{scanStatus.progress.percent}%</span>
                    </div>
                    <div className="h-2 rounded-full" style={{ backgroundColor: 'var(--color-border)' }}>
                      <div
                        className="h-2 rounded-full transition-all"
                        style={{ backgroundColor: 'var(--color-accent)', width: `${scanStatus.progress.percent}%` }}
                      />
                    </div>
                    <p className="mt-1 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                      {scanStatus.progress.processed_files} / {scanStatus.progress.total_files} files
                    </p>
                  </div>

                  <div className="grid grid-cols-4 gap-4 text-center">
                    <div>
                      <p className="text-2xl font-semibold text-green-600">
                        {scanStatus.results.new_products}
                      </p>
                      <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>New</p>
                    </div>
                    <div>
                      <p className="text-2xl font-semibold text-blue-600">
                        {scanStatus.results.updated_products}
                      </p>
                      <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Updated</p>
                    </div>
                    <div>
                      <p className="text-2xl font-semibold text-amber-600">
                        {scanStatus.results.duplicates_found}
                      </p>
                      <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Duplicates</p>
                    </div>
                    <div>
                      <p className="text-2xl font-semibold" style={{ color: 'var(--color-text-secondary)' }}>
                        {scanStatus.results.excluded_files}
                      </p>
                      <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Excluded</p>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="text-center py-8">
                  <HardDrive className="mx-auto h-12 w-12" style={{ color: 'var(--color-border)' }} />
                  <p className="mt-2 text-base" style={{ color: 'var(--color-text-secondary)' }}>
                    {scanStatus?.status === 'complete'
                      ? 'Last scan completed successfully'
                      : 'Ready to scan library'}
                  </p>
                  {scanStatus?.completed_at && (
                    <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                      Last scan: {new Date(scanStatus.completed_at).toLocaleString()}
                    </p>
                  )}
                  <button
                    onClick={() => scanMutation.mutate()}
                    disabled={scanMutation.isPending}
                    className="mt-4 inline-flex items-center gap-2 rounded-md px-6 text-base font-medium text-white disabled:opacity-50"
                    style={{ minHeight: '44px', backgroundColor: 'var(--color-accent)' }}
                  >
                    <Play className="h-4 w-4" />
                    Start Scan
                  </button>
                </div>
              )}
            </div>

            {scanStatus && !scanStatus.is_running && scanStatus.status === 'complete' && (
              <div className="rounded-xl border p-6" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface)' }}>
                <h3 className="mb-4 font-semibold text-lg" style={{ color: 'var(--color-text-primary)' }}>Last Scan Results</h3>
                <div className="grid grid-cols-5 gap-4">
                  <div className="text-center">
                    <p className="text-2xl font-bold text-green-600">
                      {scanStatus.results.new_products}
                    </p>
                    <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>New Products</p>
                  </div>
                  <div className="text-center">
                    <p className="text-2xl font-bold text-blue-600">
                      {scanStatus.results.updated_products}
                    </p>
                    <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>Updated</p>
                  </div>
                  <div className="text-center">
                    <p className="text-2xl font-bold text-amber-600">
                      {scanStatus.results.duplicates_found}
                    </p>
                    <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>Duplicates</p>
                  </div>
                  <div className="text-center">
                    <p className="text-2xl font-bold" style={{ color: 'var(--color-text-secondary)' }}>
                      {scanStatus.results.excluded_files}
                    </p>
                    <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>Excluded</p>
                  </div>
                  <div className="text-center">
                    <p className="text-2xl font-bold text-red-600">
                      {scanStatus.results.errors}
                    </p>
                    <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>Errors</p>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </main>

      {/* Cost Confirmation Modal */}
      {showCostConfirm && showCostConfirm.estimate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-md rounded-xl p-6 shadow-xl" style={{ backgroundColor: 'var(--color-surface)' }}>
            <div className="mb-4 flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full" style={{ backgroundColor: 'var(--color-accent-light)' }}>
                <Wand2 className="h-5 w-5" style={{ color: 'var(--color-accent)' }} />
              </div>
              <div>
                <h2 className="text-2xl font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                  AI Processing Cost Estimate
                </h2>
                <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>
                  {showCostConfirm.estimate.item_count} products to identify
                </p>
              </div>
            </div>

            <div className="mb-4 space-y-2 rounded-md p-4" style={{ backgroundColor: 'var(--color-surface-raised)' }}>
              <div className="flex justify-between text-base">
                <span style={{ color: 'var(--color-text-secondary)' }}>Provider</span>
                <span className="font-medium" style={{ color: 'var(--color-text-primary)' }}>{showCostConfirm.estimate.provider}</span>
              </div>
              <div className="flex justify-between text-base">
                <span style={{ color: 'var(--color-text-secondary)' }}>Model</span>
                <span className="font-medium" style={{ color: 'var(--color-text-primary)' }}>{showCostConfirm.estimate.model}</span>
              </div>
              <div className="flex justify-between text-base">
                <span style={{ color: 'var(--color-text-secondary)' }}>Estimated tokens</span>
                <span className="font-medium" style={{ color: 'var(--color-text-primary)' }}>
                  ~{showCostConfirm.estimate.total_input_tokens.toLocaleString()} input
                </span>
              </div>
              <div className="border-t pt-2 mt-2" style={{ borderColor: 'var(--color-border)' }}>
                <div className="flex justify-between">
                  <span className="font-medium" style={{ color: 'var(--color-text-primary)' }}>Estimated cost</span>
                  <span className="font-bold text-lg" style={{ color: 'var(--color-text-primary)' }}>
                    ${showCostConfirm.estimate.total_cost_usd.toFixed(4)} USD
                  </span>
                </div>
              </div>
            </div>

            <div className="mb-4 rounded-md bg-blue-50 p-3">
              <p className="text-lg text-blue-800">
                <Info className="inline h-4 w-4 mr-1" />
                Your PDF text will be sent to {showCostConfirm.provider}'s API for processing.
                Data is not used for AI training.
              </p>
            </div>

            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowCostConfirm(null)}
                className="rounded-md border px-4 text-base font-medium"
                style={{ minHeight: '44px', borderColor: 'var(--color-border)', color: 'var(--color-text-secondary)' }}
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  identifyAllMutation.mutate(showCostConfirm.provider);
                }}
                disabled={identifyAllMutation.isPending}
                className="inline-flex items-center gap-2 rounded-md px-4 text-base font-medium text-white disabled:opacity-50"
                style={{ minHeight: '44px', backgroundColor: 'var(--color-accent)' }}
              >
                {identifyAllMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Wand2 className="h-4 w-4" />
                )}
                Proceed (${showCostConfirm.estimate.total_cost_usd.toFixed(4)})
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Privacy Notice Modal */}
      {showPrivacyNotice && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-lg rounded-xl p-6 shadow-xl" style={{ backgroundColor: 'var(--color-surface)' }}>
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-2xl font-semibold flex items-center gap-2" style={{ color: 'var(--color-text-primary)' }}>
                <Info className="h-5 w-5 text-blue-600" />
                AI Privacy Information
              </h2>
              <button
                onClick={() => setShowPrivacyNotice(false)}
                style={{ color: 'var(--color-text-secondary)' }}
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-4">
              <div className="rounded-md bg-green-50 p-4">
                <h3 className="font-medium text-green-900">Ollama (Local)</h3>
                <p className="mt-1 text-lg text-green-800">
                  All processing happens on your computer. No data leaves your machine.
                  This is the most private option.
                </p>
              </div>

              <div className="rounded-md bg-amber-50 p-4">
                <h3 className="font-medium text-amber-900">Cloud Providers (OpenAI, Anthropic)</h3>
                <p className="mt-1 text-lg text-amber-800">
                  When using cloud AI providers:
                </p>
                <ul className="mt-2 text-lg text-amber-800 list-disc list-inside space-y-1">
                  <li>Your PDF text is sent to the provider's API for processing</li>
                  <li>Text is <strong>NOT</strong> used to train AI models</li>
                  <li>Data is typically deleted within 30 days</li>
                </ul>
              </div>

              <div className="text-base" style={{ color: 'var(--color-text-secondary)' }}>
                <p className="font-medium mb-2">Provider Data Policies:</p>
                <div className="space-y-1">
                  <a
                    href="https://openai.com/policies/api-data-usage-policies"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 text-blue-600 hover:text-blue-800"
                  >
                    OpenAI API Data Usage Policy
                    <ExternalLink className="h-3 w-3" />
                  </a>
                  <a
                    href="https://www.anthropic.com/legal/privacy"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 text-blue-600 hover:text-blue-800"
                  >
                    Anthropic Privacy Policy
                    <ExternalLink className="h-3 w-3" />
                  </a>
                </div>
              </div>
            </div>

            <div className="mt-6 flex justify-end">
              <button
                onClick={() => setShowPrivacyNotice(false)}
                className="rounded-md px-4 text-base font-medium"
                style={{ minHeight: '44px', backgroundColor: 'var(--color-surface-raised)', color: 'var(--color-text-secondary)' }}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-md rounded-xl p-6 shadow-xl" style={{ backgroundColor: 'var(--color-surface)' }}>
            <div className="mb-4 flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-red-100">
                <AlertTriangle className="h-5 w-5 text-red-600" />
              </div>
              <div>
                <h2 className="text-2xl font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                  {showDeleteConfirm.type === 'selected' ? 'Delete Selected Duplicates' : 'Delete All Duplicates in Group'}
                </h2>
                <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>
                  {showDeleteConfirm.type === 'selected'
                    ? `${selectedDuplicates.size} files (${formatBytes(getSelectedSize())})`
                    : 'All duplicate copies will be removed'}
                </p>
              </div>
            </div>

            <div className="mb-4 rounded-md bg-amber-50 p-3">
              <p className="text-lg text-amber-800">
                {deleteFiles
                  ? '⚠️ Files will be permanently deleted from disk. This cannot be undone.'
                  : 'Only database records will be removed. Files will remain on disk.'}
              </p>
            </div>

            <div className="mb-4">
              <label className="flex items-center gap-2 text-base" style={{ color: 'var(--color-text-secondary)' }}>
                <input
                  type="checkbox"
                  checked={deleteFiles}
                  onChange={(e) => setDeleteFiles(e.target.checked)}
                  className="rounded border-red-300 text-red-600 focus:ring-red-500"
                />
                Also delete files from disk
              </label>
            </div>

            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowDeleteConfirm(null)}
                className="rounded-md border px-4 text-base font-medium"
                style={{ minHeight: '44px', borderColor: 'var(--color-border)', color: 'var(--color-text-secondary)' }}
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  if (showDeleteConfirm.type === 'selected') {
                    bulkDeleteMutation.mutate({
                      productIds: Array.from(selectedDuplicates),
                      deleteFiles,
                    });
                  } else if (showDeleteConfirm.hash) {
                    deleteGroupMutation.mutate({
                      hash: showDeleteConfirm.hash,
                      deleteFiles,
                    });
                  }
                }}
                disabled={bulkDeleteMutation.isPending || deleteGroupMutation.isPending}
                className="inline-flex items-center gap-2 rounded-md bg-red-600 px-4 text-base font-medium text-white hover:bg-red-700 disabled:opacity-50"
                style={{ minHeight: '44px' }}
              >
                {(bulkDeleteMutation.isPending || deleteGroupMutation.isPending) ? (
                  <RefreshCw className="h-4 w-4 animate-spin" />
                ) : (
                  <Trash2 className="h-4 w-4" />
                )}
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
