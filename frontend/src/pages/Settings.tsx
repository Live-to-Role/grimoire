import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Save, Database, Sparkles, Check, AlertCircle, FolderOpen, Plus, Trash2, Star, Copy, X, RefreshCw, Upload } from 'lucide-react';
import apiClient from '../api/client';
import { FolderBrowserModal } from '../components/FolderBrowserModal';
import { useThemeContext } from '../contexts/ThemeContext';

interface CodexStatus {
  available: boolean;
  mock_mode: boolean;
  base_url: string;
}

interface AIProviders {
  providers: Record<string, boolean>;
  any_available: boolean;
}

interface SettingsData {
  codex_api_key?: string;
  codex_contribute_enabled?: boolean;
  default_ai_provider?: string;
  openai_api_key?: string;
  anthropic_api_key?: string;
  ollama_base_url?: string;
}

interface WatchedFolder {
  id: number;
  path: string;
  label: string;
  enabled: boolean;
  is_source_of_truth: boolean;
  last_scanned_at: string | null;
  created_at: string;
  product_count: number;
}

interface DuplicatePreview {
  success: boolean;
  has_source_of_truth: boolean;
  source_of_truth_folder: string | null;
  source_of_truth_folder_id: number | null;
  groups: Array<{
    file_hash: string;
    keep: {
      id: number;
      title: string;
      file_path: string;
      file_size: number;
      folder_id: number;
    };
    keep_reason: string;
    delete: Array<{
      id: number;
      title: string;
      file_path: string;
      file_size: number;
      folder_id: number;
    }>;
    space_freed_bytes: number;
  }>;
  total_groups: number;
  total_duplicates: number;
  total_space_bytes: number;
  total_space_mb: number;
}

export function Settings() {
  const queryClient = useQueryClient();
  const { theme, setTheme } = useThemeContext();
  const [settings, setSettings] = useState<SettingsData>({
    codex_api_key: '',
    codex_contribute_enabled: false,
    default_ai_provider: 'anthropic',
    openai_api_key: '',
    anthropic_api_key: '',
    ollama_base_url: 'http://localhost:11434',
  });
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [newFolderPath, setNewFolderPath] = useState('');
  const [newFolderLabel, setNewFolderLabel] = useState('');
  const [folderError, setFolderError] = useState<string | null>(null);
  const [showBrowseModal, setShowBrowseModal] = useState(false);
  const [showDuplicateModal, setShowDuplicateModal] = useState(false);
  const [duplicatePreview, setDuplicatePreview] = useState<DuplicatePreview | null>(null);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [isResolving, setIsResolving] = useState(false);
  const [deleteFiles, setDeleteFiles] = useState(false);
  const [syncResult, setSyncResult] = useState<{ message: string; type: 'success' | 'error' } | null>(null);

  const syncFromCodexMutation = useMutation({
    mutationFn: async () => {
      const res = await apiClient.post('/settings/codex/sync', {
        overwrite_existing: false,
        only_unidentified: true,
      });
      return res.data;
    },
    onSuccess: (data) => {
      setSyncResult({
        message: `Synced ${data.synced} products (${data.skipped} skipped, ${data.failed} failed)`,
        type: data.synced > 0 || data.failed === 0 ? 'success' : 'error',
      });
      queryClient.invalidateQueries({ queryKey: ['products'] });
      setTimeout(() => setSyncResult(null), 5000);
    },
    onError: () => {
      setSyncResult({ message: 'Failed to sync with Codex', type: 'error' });
      setTimeout(() => setSyncResult(null), 5000);
    },
  });

  const syncContributionsMutation = useMutation({
    mutationFn: async () => {
      const res = await apiClient.post('/settings/codex/sync-contributions');
      return res.data;
    },
    onSuccess: (data) => {
      setSyncResult({
        message: data.success
          ? `Submitted ${data.submitted} contributions (${data.failed} failed)`
          : data.reason || 'Nothing to sync',
        type: data.success ? 'success' : 'error',
      });
      setTimeout(() => setSyncResult(null), 5000);
    },
    onError: () => {
      setSyncResult({ message: 'Failed to sync contributions', type: 'error' });
      setTimeout(() => setSyncResult(null), 5000);
    },
  });

  const { data: codexStatus } = useQuery({
    queryKey: ['codex-status'],
    queryFn: async () => {
      const res = await apiClient.get<CodexStatus>('/ai/codex/status');
      return res.data;
    },
  });

  const { data: aiProviders } = useQuery({
    queryKey: ['ai-providers'],
    queryFn: async () => {
      const res = await apiClient.get<AIProviders>('/ai/providers');
      return res.data;
    },
  });

  const { data: savedSettings } = useQuery({
    queryKey: ['settings'],
    queryFn: async () => {
      const res = await apiClient.get<SettingsData>('/settings');
      return res.data;
    },
  });

  const { data: watchedFolders, refetch: refetchFolders } = useQuery({
    queryKey: ['watched-folders'],
    queryFn: async () => {
      const res = await apiClient.get<WatchedFolder[]>('/folders');
      return res.data;
    },
  });

  const addFolderMutation = useMutation({
    mutationFn: async ({ path, label }: { path: string; label: string }) => {
      const res = await apiClient.post('/folders', { path, label });
      return res.data;
    },
    onSuccess: () => {
      setNewFolderPath('');
      setNewFolderLabel('');
      setFolderError(null);
      refetchFolders();
    },
    onError: (error: any) => {
      setFolderError(error.response?.data?.detail || 'Failed to add folder');
    },
  });

  const deleteFolderMutation = useMutation({
    mutationFn: async (folderId: number) => {
      await apiClient.delete(`/folders/${folderId}`);
    },
    onSuccess: () => {
      refetchFolders();
    },
  });

  const toggleFolderMutation = useMutation({
    mutationFn: async ({ id, enabled }: { id: number; enabled: boolean }) => {
      await apiClient.patch(`/folders/${id}`, { enabled });
    },
    onSuccess: () => {
      refetchFolders();
    },
  });

  const setSourceOfTruthMutation = useMutation({
    mutationFn: async ({ id, isSourceOfTruth }: { id: number; isSourceOfTruth: boolean }) => {
      await apiClient.patch(`/folders/${id}`, { is_source_of_truth: isSourceOfTruth });
    },
    onSuccess: () => {
      refetchFolders();
    },
  });

  const loadDuplicatePreview = async () => {
    setIsLoadingPreview(true);
    try {
      const res = await apiClient.get<DuplicatePreview>('/duplicates/resolve/preview');
      setDuplicatePreview(res.data);
      setShowDuplicateModal(true);
    } catch (error) {
      console.error('Failed to load duplicate preview:', error);
    } finally {
      setIsLoadingPreview(false);
    }
  };

  const executeDuplicateResolution = async () => {
    setIsResolving(true);
    try {
      await apiClient.post('/duplicates/resolve/execute', { delete_files: deleteFiles });
      setShowDuplicateModal(false);
      setDuplicatePreview(null);
      refetchFolders();
    } catch (error) {
      console.error('Failed to resolve duplicates:', error);
    } finally {
      setIsResolving(false);
    }
  };

  useEffect(() => {
    if (savedSettings) {
      setSettings((prev) => ({ ...prev, ...savedSettings }));
    }
  }, [savedSettings]);

  const saveMutation = useMutation({
    mutationFn: async (data: SettingsData) => {
      await apiClient.put('/settings', data);
    },
    onSuccess: () => {
      setSaveStatus('saved');
      queryClient.invalidateQueries({ queryKey: ['settings'] });
      queryClient.invalidateQueries({ queryKey: ['ai-providers'] });
      setTimeout(() => setSaveStatus('idle'), 2000);
    },
    onError: () => {
      setSaveStatus('error');
      setTimeout(() => setSaveStatus('idle'), 3000);
    },
  });

  const handleSave = () => {
    setSaveStatus('saving');
    saveMutation.mutate(settings);
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="px-6 py-4" style={{ backgroundColor: 'var(--color-surface)', borderBottom: '1px solid var(--color-border)' }}>
        <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text-primary)' }}>Settings</h1>
      </header>

      <main className="flex-1 overflow-auto px-6 py-6">
        <div className="mx-auto max-w-2xl space-y-8">
          {/* Library Folders */}
          <section className="rounded-lg p-6" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <div className="mb-4 flex items-center gap-3">
              <FolderOpen className="h-6 w-6 text-amber-500" />
              <div>
                <h2 className="text-xl font-semibold" style={{ color: 'var(--color-text-primary)' }}>Library Folders</h2>
                <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>
                  Configure folders containing your PDF library
                </p>
              </div>
            </div>

            {/* Existing folders */}
            <div className="mb-4 space-y-2">
              {watchedFolders && watchedFolders.length > 0 ? (
                watchedFolders.map((folder) => (
                  <div
                    key={folder.id}
                    className={`flex items-center justify-between rounded-lg p-3 ${
                      folder.is_source_of_truth
                        ? 'border-amber-300 bg-amber-50'
                        : ''
                    }`}
                    style={folder.is_source_of_truth ? { border: '1px solid' } : { backgroundColor: 'var(--color-surface-raised)', border: '1px solid var(--color-border)' }}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium truncate" style={{ color: 'var(--color-text-primary)' }}>
                          {folder.label || folder.path}
                        </span>
                        {folder.label && (
                          <span className="text-base truncate" style={{ color: 'var(--color-text-secondary)' }}>
                            ({folder.path})
                          </span>
                        )}
                        {folder.is_source_of_truth && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
                            <Star className="h-3 w-3 fill-amber-500" />
                            Source of Truth
                          </span>
                        )}
                      </div>
                      <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>
                        {folder.product_count} products
                        {folder.last_scanned_at && (
                          <> · Last scanned {new Date(folder.last_scanned_at).toLocaleDateString()}</>
                        )}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 ml-2">
                      <button
                        onClick={() =>
                          setSourceOfTruthMutation.mutate({
                            id: folder.id,
                            isSourceOfTruth: !folder.is_source_of_truth,
                          })
                        }
                        className={`p-1 ${
                          folder.is_source_of_truth
                            ? 'text-amber-500 hover:text-amber-600'
                            : 'text-neutral-400 hover:text-amber-500'
                        }`}
                        title={folder.is_source_of_truth ? 'Remove as source of truth' : 'Set as source of truth'}
                      >
                        <Star className={`h-4 w-4 ${folder.is_source_of_truth ? 'fill-amber-500' : ''}`} />
                      </button>
                      <label className="flex items-center gap-1">
                        <input
                          type="checkbox"
                          checked={folder.enabled}
                          onChange={(e) =>
                            toggleFolderMutation.mutate({ id: folder.id, enabled: e.target.checked })
                          }
                          className="h-4 w-4 rounded"
                          style={{ accentColor: 'var(--color-accent)' }}
                        />
                        <span className="text-base" style={{ color: 'var(--color-text-secondary)' }}>Enabled</span>
                      </label>
                      <button
                        onClick={() => {
                          if (confirm('Remove this folder from your library?')) {
                            deleteFolderMutation.mutate(folder.id);
                          }
                        }}
                        className="p-1 text-neutral-400 hover:text-red-600"
                        title="Remove folder"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                ))
              ) : (
                <div className="rounded-lg border border-dashed p-4 text-center" style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-surface-raised)' }}>
                  <FolderOpen className="mx-auto h-8 w-8" style={{ color: 'var(--color-text-secondary)' }} />
                  <p className="mt-2 text-base" style={{ color: 'var(--color-text-secondary)' }}>No library folders configured</p>
                </div>
              )}
            </div>

            {/* Add new folder */}
            <div className="pt-4" style={{ borderTop: '1px solid var(--color-border)' }}>
              <p className="mb-2 text-lg font-medium" style={{ color: 'var(--color-text-primary)' }}>Add Library Folder</p>
              {folderError && (
                <div className="mb-2 rounded-lg bg-red-50 p-2 text-sm text-red-600">
                  {folderError}
                </div>
              )}
              <div className="flex gap-2">
                <input
                  type="text"
                  value={newFolderPath}
                  onChange={(e) => setNewFolderPath(e.target.value)}
                  placeholder="/path/to/pdfs or //server/share"
                  className="input flex-1 rounded-lg px-3"
                  style={{ height: '48px', fontSize: '18px', backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                />
                <button
                  onClick={() => setShowBrowseModal(true)}
                  type="button"
                  className="inline-flex items-center gap-1 rounded-lg px-3 text-base font-medium"
                  style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)', minHeight: '44px' }}
                >
                  <FolderOpen className="h-4 w-4" />
                  Browse
                </button>
                <input
                  type="text"
                  value={newFolderLabel}
                  onChange={(e) => setNewFolderLabel(e.target.value)}
                  placeholder="Label (optional)"
                  className="input w-40 rounded-lg px-3"
                  style={{ height: '48px', fontSize: '18px', backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                />
                <button
                  onClick={() => {
                    if (newFolderPath.trim()) {
                      addFolderMutation.mutate({
                        path: newFolderPath.trim(),
                        label: newFolderLabel.trim() || newFolderPath.trim().split('/').pop() || 'Library',
                      });
                    }
                  }}
                  disabled={!newFolderPath.trim() || addFolderMutation.isPending}
                  className="inline-flex items-center gap-1 rounded-lg px-3 text-base font-medium text-white disabled:opacity-50"
                  style={{ backgroundColor: 'var(--color-accent)', minHeight: '44px' }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-accent-hover)')}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-accent)')}
                >
                  <Plus className="h-4 w-4" />
                  Add
                </button>
              </div>
              <p className="mt-2 text-base" style={{ color: 'var(--color-text-secondary)' }}>
                Network drives supported — use a mapped drive letter (e.g. Z:\RPGs) or a UNC path (e.g. \\server\share). On Linux, mount the share first (e.g. /mnt/nas/rpgs). The folder must be accessible to the application.
              </p>
            </div>

            {/* Duplicate Resolution */}
            <div className="pt-4" style={{ borderTop: '1px solid var(--color-border)' }}>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-lg font-medium" style={{ color: 'var(--color-text-primary)' }}>Duplicate Management</p>
                  <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>
                    Resolve duplicate files using source of truth rules
                  </p>
                </div>
                <button
                  onClick={loadDuplicatePreview}
                  disabled={isLoadingPreview}
                  className="inline-flex items-center gap-2 rounded-lg px-3 text-base font-medium disabled:opacity-50"
                  style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)', minHeight: '44px' }}
                >
                  <Copy className="h-4 w-4" />
                  {isLoadingPreview ? 'Loading...' : 'Resolve Duplicates'}
                </button>
              </div>
            </div>
          </section>

          {/* Codex Settings */}
          <section className="rounded-lg p-6" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <div className="mb-4 flex items-center gap-3">
              <Database className="h-6 w-6 text-blue-500" />
              <div>
                <h2 className="text-xl font-semibold" style={{ color: 'var(--color-text-primary)' }}>Codex Integration</h2>
                <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>
                  Connect to the community TTRPG metadata database
                </p>
              </div>
            </div>

            <div className="mb-4 rounded-lg p-3" style={{ backgroundColor: 'var(--color-surface-raised)', border: '1px solid var(--color-border)' }}>
              <div className="flex items-center justify-between">
                <span className="text-base" style={{ color: 'var(--color-text-secondary)' }}>Status</span>
                {codexStatus?.available ? (
                  <span className="inline-flex items-center gap-1 text-sm text-green-600">
                    <Check className="h-4 w-4" />
                    {codexStatus.mock_mode ? 'Mock Mode' : 'Connected'}
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-sm text-amber-600">
                    <AlertCircle className="h-4 w-4" />
                    Unavailable
                  </span>
                )}
              </div>
              {codexStatus?.base_url && (
                <p className="mt-1 text-base" style={{ color: 'var(--color-text-secondary)' }}>{codexStatus.base_url}</p>
              )}
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-lg font-medium" style={{ color: 'var(--color-text-primary)' }}>
                  Codex API Key
                </label>
                <p className="mb-1 text-base" style={{ color: 'var(--color-text-secondary)' }}>
                  Required to contribute identifications back to Codex
                </p>
                <input
                  type="password"
                  value={settings.codex_api_key || ''}
                  onChange={(e) => setSettings({ ...settings, codex_api_key: e.target.value })}
                  placeholder="Enter your Codex API key"
                  className="input w-full rounded-lg px-3"
                  style={{ height: '48px', fontSize: '18px', backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                />
              </div>

              <label className="flex items-center gap-3">
                <input
                  type="checkbox"
                  checked={settings.codex_contribute_enabled || false}
                  onChange={(e) =>
                    setSettings({ ...settings, codex_contribute_enabled: e.target.checked })
                  }
                  className="h-4 w-4 rounded"
                  style={{ accentColor: 'var(--color-accent)' }}
                />
                <div>
                  <span className="text-lg font-medium" style={{ color: 'var(--color-text-primary)' }}>
                    Contribute to Codex
                  </span>
                  <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>
                    Share new product identifications with the community
                  </p>
                </div>
              </label>
            </div>

            {/* Sync Actions */}
            {codexStatus?.available && !codexStatus?.mock_mode && (
              <div className="border-t border-neutral-200 pt-4">
                <p className="mb-3 text-sm font-medium text-neutral-700">Sync Actions</p>
                {syncResult && (
                  <div
                    className={`mb-3 rounded-lg p-2 text-sm ${
                      syncResult.type === 'success'
                        ? 'bg-green-50 text-green-700'
                        : 'bg-red-50 text-red-600'
                    }`}
                  >
                    {syncResult.message}
                  </div>
                )}
                <div className="flex gap-2">
                  <button
                    onClick={() => syncFromCodexMutation.mutate()}
                    disabled={syncFromCodexMutation.isPending}
                    className="inline-flex items-center gap-2 rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
                  >
                    <RefreshCw className={`h-4 w-4 ${syncFromCodexMutation.isPending ? 'animate-spin' : ''}`} />
                    {syncFromCodexMutation.isPending ? 'Syncing...' : 'Sync from Codex'}
                  </button>
                  <button
                    onClick={() => syncContributionsMutation.mutate()}
                    disabled={syncContributionsMutation.isPending || !settings.codex_contribute_enabled}
                    className="inline-flex items-center gap-2 rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
                    title={!settings.codex_contribute_enabled ? 'Enable "Contribute to Codex" first' : ''}
                  >
                    <Upload className={`h-4 w-4 ${syncContributionsMutation.isPending ? 'animate-spin' : ''}`} />
                    {syncContributionsMutation.isPending ? 'Submitting...' : 'Push Contributions'}
                  </button>
                </div>
                <p className="mt-2 text-xs text-neutral-500">
                  "Sync from Codex" pulls metadata for unidentified products. "Push Contributions" sends your edits to the community database.
                </p>
              </div>
            )}
          </section>

          {/* AI Settings */}
          <section className="rounded-lg p-6" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <div className="mb-4 flex items-center gap-3">
              <Sparkles className="h-6 w-6 text-purple-500" />
              <div>
                <h2 className="text-xl font-semibold" style={{ color: 'var(--color-text-primary)' }}>AI Providers</h2>
                <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>
                  Configure AI services for product identification
                </p>
              </div>
            </div>

            <div className="mb-4 rounded-lg p-3" style={{ backgroundColor: 'var(--color-surface-raised)', border: '1px solid var(--color-border)' }}>
              <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>Available providers:</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {aiProviders?.providers &&
                  Object.entries(aiProviders.providers).map(([provider, available]) => (
                    <span
                      key={provider}
                      className={`rounded-full px-2 py-1 text-xs font-medium ${
                        available
                          ? 'bg-green-100 text-green-700'
                          : 'bg-neutral-200 text-neutral-500'
                      }`}
                    >
                      {provider}
                    </span>
                  ))}
              </div>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-lg font-medium" style={{ color: 'var(--color-text-primary)' }}>
                  Default Provider
                </label>
                <select
                  value={settings.default_ai_provider || 'anthropic'}
                  onChange={(e) =>
                    setSettings({ ...settings, default_ai_provider: e.target.value })
                  }
                  className="input mt-1 w-full rounded-lg px-3"
                  style={{ height: '48px', fontSize: '18px', backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                >
                  <option value="anthropic">Anthropic (Claude)</option>
                  <option value="openai">OpenAI (GPT)</option>
                  <option value="ollama">Ollama (Local)</option>
                </select>
              </div>

              <div>
                <label className="block text-lg font-medium" style={{ color: 'var(--color-text-primary)' }}>
                  OpenAI API Key
                </label>
                <input
                  type="password"
                  value={settings.openai_api_key || ''}
                  onChange={(e) => setSettings({ ...settings, openai_api_key: e.target.value })}
                  placeholder="sk-..."
                  className="input mt-1 w-full rounded-lg px-3"
                  style={{ height: '48px', fontSize: '18px', backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                />
              </div>

              <div>
                <label className="block text-lg font-medium" style={{ color: 'var(--color-text-primary)' }}>
                  Anthropic API Key
                </label>
                <input
                  type="password"
                  value={settings.anthropic_api_key || ''}
                  onChange={(e) =>
                    setSettings({ ...settings, anthropic_api_key: e.target.value })
                  }
                  placeholder="sk-ant-..."
                  className="input mt-1 w-full rounded-lg px-3"
                  style={{ height: '48px', fontSize: '18px', backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                />
              </div>

              <div>
                <label className="block text-lg font-medium" style={{ color: 'var(--color-text-primary)' }}>
                  Ollama Base URL
                </label>
                <input
                  type="text"
                  value={settings.ollama_base_url || ''}
                  onChange={(e) => setSettings({ ...settings, ollama_base_url: e.target.value })}
                  placeholder="http://localhost:11434"
                  className="input mt-1 w-full rounded-lg px-3"
                  style={{ height: '48px', fontSize: '18px', backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)', color: 'var(--color-text-primary)' }}
                />
              </div>
            </div>
          </section>

          {/* Appearance */}
          <section className="rounded-lg p-6" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <div className="mb-4">
              <h2 className="text-xl font-semibold" style={{ color: 'var(--color-text-primary)' }}>Appearance</h2>
              <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>Choose your preferred color theme</p>
            </div>
            <div className="flex rounded-lg overflow-hidden" style={{ border: '1px solid var(--color-border)' }}>
              {(['light', 'dark', 'system'] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setTheme(t)}
                  className="flex-1 px-4 py-3 text-base font-medium capitalize transition-colors"
                  style={{
                    backgroundColor: theme === t ? 'var(--color-accent-light)' : 'transparent',
                    color: theme === t ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                    minHeight: '48px',
                  }}
                >
                  {t}
                </button>
              ))}
            </div>
          </section>
        </div>
      </main>

      <footer className="px-6 py-4" style={{ backgroundColor: 'var(--color-surface)', borderTop: '1px solid var(--color-border)' }}>
        <div className="mx-auto flex max-w-2xl items-center justify-end gap-3">
          {saveStatus === 'saved' && (
            <span className="text-sm text-green-600">Settings saved!</span>
          )}
          {saveStatus === 'error' && (
            <span className="text-sm text-red-600">Failed to save settings</span>
          )}
          <button
            onClick={handleSave}
            disabled={saveStatus === 'saving'}
            className="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-base font-medium text-white disabled:opacity-50"
            style={{ backgroundColor: 'var(--color-accent)', minHeight: '44px' }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-accent-hover)')}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-accent)')}
          >
            <Save className="h-4 w-4" />
            {saveStatus === 'saving' ? 'Saving...' : 'Save Settings'}
          </button>
        </div>
      </footer>

      {/* Folder Browser Modal */}
      <FolderBrowserModal
        isOpen={showBrowseModal}
        onClose={() => setShowBrowseModal(false)}
        onSelect={(path) => setNewFolderPath(path)}
      />

      {/* Duplicate Resolution Modal */}
      {showDuplicateModal && duplicatePreview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="mx-4 max-h-[80vh] w-full max-w-2xl overflow-hidden rounded-lg shadow-xl" style={{ backgroundColor: 'var(--color-surface)' }}>
            <div className="flex items-center justify-between px-6 py-4" style={{ borderBottom: '1px solid var(--color-border)' }}>
              <h2 className="text-xl font-semibold" style={{ color: 'var(--color-text-primary)' }}>Resolve Duplicates</h2>
              <button
                onClick={() => {
                  setShowDuplicateModal(false);
                  setDuplicatePreview(null);
                }}
                className="p-1"
                style={{ color: 'var(--color-text-secondary)' }}
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="max-h-[60vh] overflow-auto p-6">
              {duplicatePreview.total_duplicates === 0 ? (
                <div className="text-center py-8">
                  <Check className="mx-auto h-12 w-12 text-green-500" />
                  <p className="mt-2 text-lg font-medium" style={{ color: 'var(--color-text-primary)' }}>No duplicates found</p>
                  <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>Your library is clean!</p>
                </div>
              ) : (
                <>
                  {/* Summary */}
                  <div className="mb-6 rounded-lg p-4" style={{ backgroundColor: 'var(--color-surface-raised)' }}>
                    <div className="grid grid-cols-3 gap-4 text-center">
                      <div>
                        <p className="text-2xl font-bold" style={{ color: 'var(--color-text-primary)' }}>{duplicatePreview.total_groups}</p>
                        <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>Duplicate Groups</p>
                      </div>
                      <div>
                        <p className="text-2xl font-bold" style={{ color: 'var(--color-text-primary)' }}>{duplicatePreview.total_duplicates}</p>
                        <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>Files to Remove</p>
                      </div>
                      <div>
                        <p className="text-2xl font-bold text-amber-600">{duplicatePreview.total_space_mb} MB</p>
                        <p className="text-base" style={{ color: 'var(--color-text-secondary)' }}>Space to Free</p>
                      </div>
                    </div>
                    {duplicatePreview.has_source_of_truth && (
                      <p className="mt-3 text-center text-base" style={{ color: 'var(--color-text-secondary)' }}>
                        Source of truth: <span className="font-medium">{duplicatePreview.source_of_truth_folder}</span>
                      </p>
                    )}
                    {!duplicatePreview.has_source_of_truth && (
                      <p className="mt-3 text-center text-sm text-amber-600">
                        No source of truth set. Will keep newest version of each duplicate.
                      </p>
                    )}
                  </div>

                  {/* Preview list */}
                  <div className="space-y-3">
                    <p className="text-lg font-medium" style={{ color: 'var(--color-text-primary)' }}>Preview (first 10 groups):</p>
                    {duplicatePreview.groups.slice(0, 10).map((group) => (
                      <div key={group.file_hash} className="rounded-lg p-3" style={{ border: '1px solid var(--color-border)' }}>
                        <div className="flex items-start justify-between">
                          <div className="flex-1 min-w-0">
                            <p className="font-medium truncate" style={{ color: 'var(--color-text-primary)' }}>{group.keep.title}</p>
                            <p className="text-xs text-green-600">
                              Keep ({group.keep_reason === 'source_of_truth' ? 'source of truth' : 'newest'})
                            </p>
                          </div>
                          <span className="ml-2 text-base" style={{ color: 'var(--color-text-secondary)' }}>
                            {Math.round(group.space_freed_bytes / 1024 / 1024)} MB freed
                          </span>
                        </div>
                        <div className="mt-2 space-y-1">
                          {group.delete.map((item) => (
                            <p key={item.id} className="text-xs text-red-600 truncate">
                              Remove: {item.file_path}
                            </p>
                          ))}
                        </div>
                      </div>
                    ))}
                    {duplicatePreview.groups.length > 10 && (
                      <p className="text-center text-base" style={{ color: 'var(--color-text-secondary)' }}>
                        ...and {duplicatePreview.groups.length - 10} more groups
                      </p>
                    )}
                  </div>

                  {/* Options */}
                  <div className="mt-6 rounded-lg border border-amber-200 bg-amber-50 p-4">
                    <label className="flex items-start gap-3">
                      <input
                        type="checkbox"
                        checked={deleteFiles}
                        onChange={(e) => setDeleteFiles(e.target.checked)}
                        className="mt-0.5 h-4 w-4 rounded"
                        style={{ accentColor: 'var(--color-accent)' }}
                      />
                      <div>
                        <span className="text-lg font-medium text-amber-800">
                          Also delete files from disk
                        </span>
                        <p className="text-base text-amber-700">
                          If unchecked, only database records will be removed. Files will remain on disk.
                        </p>
                      </div>
                    </label>
                  </div>
                </>
              )}
            </div>

            <div className="flex items-center justify-end gap-3 px-6 py-4" style={{ borderTop: '1px solid var(--color-border)' }}>
              <button
                onClick={() => {
                  setShowDuplicateModal(false);
                  setDuplicatePreview(null);
                }}
                className="rounded-lg px-4 py-2 text-base font-medium"
                style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)', minHeight: '44px' }}
              >
                Cancel
              </button>
              {duplicatePreview.total_duplicates > 0 && (
                <button
                  onClick={executeDuplicateResolution}
                  disabled={isResolving}
                  className="rounded-lg bg-red-600 px-4 py-2 text-base font-medium text-white hover:bg-red-700 disabled:opacity-50"
                  style={{ minHeight: '44px' }}
                >
                  {isResolving ? 'Resolving...' : `Remove ${duplicatePreview.total_duplicates} Duplicates`}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
