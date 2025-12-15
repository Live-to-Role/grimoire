import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Save, Database, Sparkles, Check, AlertCircle, FolderOpen, Plus, Trash2, Star, Copy, X } from 'lucide-react';
import apiClient from '../api/client';

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
  const [showDuplicateModal, setShowDuplicateModal] = useState(false);
  const [duplicatePreview, setDuplicatePreview] = useState<DuplicatePreview | null>(null);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [isResolving, setIsResolving] = useState(false);
  const [deleteFiles, setDeleteFiles] = useState(false);

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
      <header className="border-b border-neutral-200 bg-white px-6 py-4">
        <h1 className="text-2xl font-bold text-neutral-900">Settings</h1>
      </header>

      <main className="flex-1 overflow-auto p-6">
        <div className="mx-auto max-w-2xl space-y-8">
          {/* Library Folders */}
          <section className="rounded-xl border border-neutral-200 bg-white p-6">
            <div className="mb-4 flex items-center gap-3">
              <FolderOpen className="h-6 w-6 text-amber-500" />
              <div>
                <h2 className="text-lg font-semibold text-neutral-900">Library Folders</h2>
                <p className="text-sm text-neutral-500">
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
                    className={`flex items-center justify-between rounded-lg border p-3 ${
                      folder.is_source_of_truth
                        ? 'border-amber-300 bg-amber-50'
                        : 'border-neutral-200 bg-neutral-50'
                    }`}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-neutral-900 truncate">
                          {folder.label || folder.path}
                        </span>
                        {folder.label && (
                          <span className="text-xs text-neutral-500 truncate">
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
                      <p className="text-xs text-neutral-500">
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
                          className="h-4 w-4 rounded border-neutral-300 text-purple-600 focus:ring-purple-500"
                        />
                        <span className="text-xs text-neutral-500">Enabled</span>
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
                <div className="rounded-lg border border-dashed border-neutral-300 bg-neutral-50 p-4 text-center">
                  <FolderOpen className="mx-auto h-8 w-8 text-neutral-300" />
                  <p className="mt-2 text-sm text-neutral-500">No library folders configured</p>
                </div>
              )}
            </div>

            {/* Add new folder */}
            <div className="border-t border-neutral-200 pt-4">
              <p className="mb-2 text-sm font-medium text-neutral-700">Add Library Folder</p>
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
                  placeholder="/path/to/pdfs"
                  className="flex-1 rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                />
                <input
                  type="text"
                  value={newFolderLabel}
                  onChange={(e) => setNewFolderLabel(e.target.value)}
                  placeholder="Label (optional)"
                  className="w-40 rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
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
                  className="inline-flex items-center gap-1 rounded-lg bg-purple-600 px-3 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
                >
                  <Plus className="h-4 w-4" />
                  Add
                </button>
              </div>
              <p className="mt-2 text-xs text-neutral-500">
                Enter the path to a folder containing PDF files. The folder must be accessible to the application.
              </p>
            </div>

            {/* Duplicate Resolution */}
            <div className="border-t border-neutral-200 pt-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-neutral-700">Duplicate Management</p>
                  <p className="text-xs text-neutral-500">
                    Resolve duplicate files using source of truth rules
                  </p>
                </div>
                <button
                  onClick={loadDuplicatePreview}
                  disabled={isLoadingPreview}
                  className="inline-flex items-center gap-2 rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
                >
                  <Copy className="h-4 w-4" />
                  {isLoadingPreview ? 'Loading...' : 'Resolve Duplicates'}
                </button>
              </div>
            </div>
          </section>

          {/* Codex Settings */}
          <section className="rounded-xl border border-neutral-200 bg-white p-6">
            <div className="mb-4 flex items-center gap-3">
              <Database className="h-6 w-6 text-blue-500" />
              <div>
                <h2 className="text-lg font-semibold text-neutral-900">Codex Integration</h2>
                <p className="text-sm text-neutral-500">
                  Connect to the community TTRPG metadata database
                </p>
              </div>
            </div>

            <div className="mb-4 rounded-lg border border-neutral-200 bg-neutral-50 p-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-neutral-600">Status</span>
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
                <p className="mt-1 text-xs text-neutral-500">{codexStatus.base_url}</p>
              )}
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-neutral-700">
                  Codex API Key
                </label>
                <p className="mb-1 text-xs text-neutral-500">
                  Required to contribute identifications back to Codex
                </p>
                <input
                  type="password"
                  value={settings.codex_api_key || ''}
                  onChange={(e) => setSettings({ ...settings, codex_api_key: e.target.value })}
                  placeholder="Enter your Codex API key"
                  className="w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                />
              </div>

              <label className="flex items-center gap-3">
                <input
                  type="checkbox"
                  checked={settings.codex_contribute_enabled || false}
                  onChange={(e) =>
                    setSettings({ ...settings, codex_contribute_enabled: e.target.checked })
                  }
                  className="h-4 w-4 rounded border-neutral-300 text-purple-600 focus:ring-purple-500"
                />
                <div>
                  <span className="text-sm font-medium text-neutral-700">
                    Contribute to Codex
                  </span>
                  <p className="text-xs text-neutral-500">
                    Share new product identifications with the community
                  </p>
                </div>
              </label>
            </div>
          </section>

          {/* AI Settings */}
          <section className="rounded-xl border border-neutral-200 bg-white p-6">
            <div className="mb-4 flex items-center gap-3">
              <Sparkles className="h-6 w-6 text-purple-500" />
              <div>
                <h2 className="text-lg font-semibold text-neutral-900">AI Providers</h2>
                <p className="text-sm text-neutral-500">
                  Configure AI services for product identification
                </p>
              </div>
            </div>

            <div className="mb-4 rounded-lg border border-neutral-200 bg-neutral-50 p-3">
              <p className="text-sm text-neutral-600">Available providers:</p>
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
                <label className="block text-sm font-medium text-neutral-700">
                  Default Provider
                </label>
                <select
                  value={settings.default_ai_provider || 'anthropic'}
                  onChange={(e) =>
                    setSettings({ ...settings, default_ai_provider: e.target.value })
                  }
                  className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                >
                  <option value="anthropic">Anthropic (Claude)</option>
                  <option value="openai">OpenAI (GPT)</option>
                  <option value="ollama">Ollama (Local)</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-neutral-700">
                  OpenAI API Key
                </label>
                <input
                  type="password"
                  value={settings.openai_api_key || ''}
                  onChange={(e) => setSettings({ ...settings, openai_api_key: e.target.value })}
                  placeholder="sk-..."
                  className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-neutral-700">
                  Anthropic API Key
                </label>
                <input
                  type="password"
                  value={settings.anthropic_api_key || ''}
                  onChange={(e) =>
                    setSettings({ ...settings, anthropic_api_key: e.target.value })
                  }
                  placeholder="sk-ant-..."
                  className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-neutral-700">
                  Ollama Base URL
                </label>
                <input
                  type="text"
                  value={settings.ollama_base_url || ''}
                  onChange={(e) => setSettings({ ...settings, ollama_base_url: e.target.value })}
                  placeholder="http://localhost:11434"
                  className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                />
              </div>
            </div>
          </section>
        </div>
      </main>

      <footer className="border-t border-neutral-200 bg-white px-6 py-4">
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
            className="inline-flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
          >
            <Save className="h-4 w-4" />
            {saveStatus === 'saving' ? 'Saving...' : 'Save Settings'}
          </button>
        </div>
      </footer>

      {/* Duplicate Resolution Modal */}
      {showDuplicateModal && duplicatePreview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="mx-4 max-h-[80vh] w-full max-w-2xl overflow-hidden rounded-xl bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-neutral-200 px-6 py-4">
              <h2 className="text-lg font-semibold text-neutral-900">Resolve Duplicates</h2>
              <button
                onClick={() => {
                  setShowDuplicateModal(false);
                  setDuplicatePreview(null);
                }}
                className="p-1 text-neutral-400 hover:text-neutral-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="max-h-[60vh] overflow-auto p-6">
              {duplicatePreview.total_duplicates === 0 ? (
                <div className="text-center py-8">
                  <Check className="mx-auto h-12 w-12 text-green-500" />
                  <p className="mt-2 text-lg font-medium text-neutral-900">No duplicates found</p>
                  <p className="text-sm text-neutral-500">Your library is clean!</p>
                </div>
              ) : (
                <>
                  {/* Summary */}
                  <div className="mb-6 rounded-lg bg-neutral-50 p-4">
                    <div className="grid grid-cols-3 gap-4 text-center">
                      <div>
                        <p className="text-2xl font-bold text-neutral-900">{duplicatePreview.total_groups}</p>
                        <p className="text-xs text-neutral-500">Duplicate Groups</p>
                      </div>
                      <div>
                        <p className="text-2xl font-bold text-neutral-900">{duplicatePreview.total_duplicates}</p>
                        <p className="text-xs text-neutral-500">Files to Remove</p>
                      </div>
                      <div>
                        <p className="text-2xl font-bold text-amber-600">{duplicatePreview.total_space_mb} MB</p>
                        <p className="text-xs text-neutral-500">Space to Free</p>
                      </div>
                    </div>
                    {duplicatePreview.has_source_of_truth && (
                      <p className="mt-3 text-center text-sm text-neutral-600">
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
                    <p className="text-sm font-medium text-neutral-700">Preview (first 10 groups):</p>
                    {duplicatePreview.groups.slice(0, 10).map((group) => (
                      <div key={group.file_hash} className="rounded-lg border border-neutral-200 p-3">
                        <div className="flex items-start justify-between">
                          <div className="flex-1 min-w-0">
                            <p className="font-medium text-neutral-900 truncate">{group.keep.title}</p>
                            <p className="text-xs text-green-600">
                              Keep ({group.keep_reason === 'source_of_truth' ? 'source of truth' : 'newest'})
                            </p>
                          </div>
                          <span className="ml-2 text-xs text-neutral-500">
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
                      <p className="text-center text-sm text-neutral-500">
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
                        className="mt-0.5 h-4 w-4 rounded border-neutral-300 text-amber-600 focus:ring-amber-500"
                      />
                      <div>
                        <span className="text-sm font-medium text-amber-800">
                          Also delete files from disk
                        </span>
                        <p className="text-xs text-amber-700">
                          If unchecked, only database records will be removed. Files will remain on disk.
                        </p>
                      </div>
                    </label>
                  </div>
                </>
              )}
            </div>

            <div className="flex items-center justify-end gap-3 border-t border-neutral-200 px-6 py-4">
              <button
                onClick={() => {
                  setShowDuplicateModal(false);
                  setDuplicatePreview(null);
                }}
                className="rounded-lg border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
              >
                Cancel
              </button>
              {duplicatePreview.total_duplicates > 0 && (
                <button
                  onClick={executeDuplicateResolution}
                  disabled={isResolving}
                  className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
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
