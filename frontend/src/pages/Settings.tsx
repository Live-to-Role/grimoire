import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Save, Database, Sparkles, Check, AlertCircle, FolderOpen, Plus, Trash2 } from 'lucide-react';
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
  last_scanned_at: string | null;
  created_at: string;
  product_count: number;
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
                    className="flex items-center justify-between rounded-lg border border-neutral-200 bg-neutral-50 p-3"
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
                      </div>
                      <p className="text-xs text-neutral-500">
                        {folder.product_count} products
                        {folder.last_scanned_at && (
                          <> · Last scanned {new Date(folder.last_scanned_at).toLocaleDateString()}</>
                        )}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 ml-2">
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
    </div>
  );
}
