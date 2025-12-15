import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Plus,
  Calendar,
  Users,
  BookOpen,
  Edit2,
  Trash2,
  ChevronRight,
  X,
} from 'lucide-react';
import apiClient from '../api/client';

interface Campaign {
  id: number;
  name: string;
  description: string | null;
  game_system: string | null;
  status: string;
  start_date: string | null;
  player_count: number | null;
  session_count: number;
  created_at: string;
  updated_at: string;
}

interface Session {
  id: number;
  campaign_id: number;
  session_number: number;
  title: string | null;
  scheduled_date: string | null;
  actual_date: string | null;
  status: string;
  summary: string | null;
}

interface CampaignFormData {
  name: string;
  description: string;
  game_system: string;
  status: string;
  player_count: number | null;
}

export function Campaigns() {
  const queryClient = useQueryClient();
  const [selectedCampaign, setSelectedCampaign] = useState<Campaign | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingCampaign, setEditingCampaign] = useState<Campaign | null>(null);
  const [formData, setFormData] = useState<CampaignFormData>({
    name: '',
    description: '',
    game_system: '',
    status: 'active',
    player_count: null,
  });

  const { data: campaignsData, isLoading } = useQuery({
    queryKey: ['campaigns'],
    queryFn: async () => {
      const res = await apiClient.get<{ campaigns: Campaign[] }>('/campaigns');
      return res.data;
    },
  });

  const { data: sessionsData } = useQuery({
    queryKey: ['sessions', selectedCampaign?.id],
    queryFn: async () => {
      if (!selectedCampaign) return null;
      const res = await apiClient.get<{ sessions: Session[] }>(
        `/campaigns/${selectedCampaign.id}/sessions`
      );
      return res.data;
    },
    enabled: !!selectedCampaign,
  });

  const createMutation = useMutation({
    mutationFn: async (data: CampaignFormData) => {
      await apiClient.post('/campaigns', data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['campaigns'] });
      setShowCreateModal(false);
      resetForm();
    },
  });

  const updateMutation = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: Partial<CampaignFormData> }) => {
      await apiClient.put(`/campaigns/${id}`, data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['campaigns'] });
      setEditingCampaign(null);
      resetForm();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/campaigns/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['campaigns'] });
      if (selectedCampaign?.id === deleteMutation.variables) {
        setSelectedCampaign(null);
      }
    },
  });

  const createSessionMutation = useMutation({
    mutationFn: async (campaignId: number) => {
      await apiClient.post(`/campaigns/${campaignId}/sessions`, {});
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sessions', selectedCampaign?.id] });
      queryClient.invalidateQueries({ queryKey: ['campaigns'] });
    },
  });

  const resetForm = () => {
    setFormData({
      name: '',
      description: '',
      game_system: '',
      status: 'active',
      player_count: null,
    });
  };

  const openEditModal = (campaign: Campaign) => {
    setEditingCampaign(campaign);
    setFormData({
      name: campaign.name,
      description: campaign.description || '',
      game_system: campaign.game_system || '',
      status: campaign.status,
      player_count: campaign.player_count,
    });
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (editingCampaign) {
      updateMutation.mutate({ id: editingCampaign.id, data: formData });
    } else {
      createMutation.mutate(formData);
    }
  };

  const campaigns = campaignsData?.campaigns || [];

  return (
    <div className="flex h-full">
      {/* Campaign List */}
      <div className="w-80 border-r border-neutral-200 bg-white flex flex-col">
        <div className="border-b border-neutral-200 p-4">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-lg font-semibold text-neutral-900">Campaigns</h2>
            <button
              onClick={() => setShowCreateModal(true)}
              className="rounded-lg bg-purple-600 p-2 text-white hover:bg-purple-700"
            >
              <Plus className="h-4 w-4" />
            </button>
          </div>
          <p className="text-sm text-neutral-500">
            {campaigns.length} campaign{campaigns.length !== 1 ? 's' : ''}
          </p>
        </div>

        <div className="flex-1 overflow-y-auto p-2">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-purple-600 border-t-transparent" />
            </div>
          ) : campaigns.length === 0 ? (
            <div className="text-center py-8">
              <BookOpen className="mx-auto h-12 w-12 text-neutral-300" />
              <p className="mt-2 text-sm text-neutral-500">No campaigns yet</p>
              <button
                onClick={() => setShowCreateModal(true)}
                className="mt-2 text-sm text-purple-600 hover:text-purple-700"
              >
                Create your first campaign
              </button>
            </div>
          ) : (
            <div className="space-y-1">
              {campaigns.map((campaign) => (
                <button
                  key={campaign.id}
                  onClick={() => setSelectedCampaign(campaign)}
                  className={`w-full rounded-lg p-3 text-left transition-colors ${
                    selectedCampaign?.id === campaign.id
                      ? 'bg-purple-100 border border-purple-200'
                      : 'hover:bg-neutral-50 border border-transparent'
                  }`}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <h3 className="font-medium text-neutral-900 truncate">
                        {campaign.name}
                      </h3>
                      {campaign.game_system && (
                        <p className="text-xs text-neutral-500 mt-0.5">
                          {campaign.game_system}
                        </p>
                      )}
                    </div>
                    <span
                      className={`ml-2 rounded-full px-2 py-0.5 text-xs font-medium ${
                        campaign.status === 'active'
                          ? 'bg-green-100 text-green-700'
                          : campaign.status === 'completed'
                          ? 'bg-blue-100 text-blue-700'
                          : 'bg-neutral-100 text-neutral-600'
                      }`}
                    >
                      {campaign.status}
                    </span>
                  </div>
                  <div className="mt-2 flex items-center gap-3 text-xs text-neutral-500">
                    <span className="flex items-center gap-1">
                      <Calendar className="h-3 w-3" />
                      {campaign.session_count} sessions
                    </span>
                    {campaign.player_count && (
                      <span className="flex items-center gap-1">
                        <Users className="h-3 w-3" />
                        {campaign.player_count} players
                      </span>
                    )}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Campaign Detail */}
      <div className="flex-1 bg-neutral-50 overflow-y-auto">
        {selectedCampaign ? (
          <div className="p-6">
            <div className="mb-6 flex items-start justify-between">
              <div>
                <h1 className="text-2xl font-bold text-neutral-900">
                  {selectedCampaign.name}
                </h1>
                {selectedCampaign.game_system && (
                  <p className="text-neutral-500">{selectedCampaign.game_system}</p>
                )}
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => openEditModal(selectedCampaign)}
                  className="rounded-lg border border-neutral-200 bg-white p-2 text-neutral-600 hover:bg-neutral-50"
                >
                  <Edit2 className="h-4 w-4" />
                </button>
                <button
                  onClick={() => {
                    if (confirm('Delete this campaign?')) {
                      deleteMutation.mutate(selectedCampaign.id);
                    }
                  }}
                  className="rounded-lg border border-neutral-200 bg-white p-2 text-red-600 hover:bg-red-50"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>

            {selectedCampaign.description && (
              <p className="mb-6 text-neutral-600">{selectedCampaign.description}</p>
            )}

            <div className="grid grid-cols-3 gap-4 mb-8">
              <div className="rounded-lg border border-neutral-200 bg-white p-4">
                <p className="text-sm text-neutral-500">Status</p>
                <p className="text-lg font-semibold text-neutral-900 capitalize">
                  {selectedCampaign.status}
                </p>
              </div>
              <div className="rounded-lg border border-neutral-200 bg-white p-4">
                <p className="text-sm text-neutral-500">Sessions</p>
                <p className="text-lg font-semibold text-neutral-900">
                  {selectedCampaign.session_count}
                </p>
              </div>
              <div className="rounded-lg border border-neutral-200 bg-white p-4">
                <p className="text-sm text-neutral-500">Players</p>
                <p className="text-lg font-semibold text-neutral-900">
                  {selectedCampaign.player_count || '—'}
                </p>
              </div>
            </div>

            <div className="rounded-xl border border-neutral-200 bg-white">
              <div className="border-b border-neutral-200 px-4 py-3 flex items-center justify-between">
                <h2 className="font-semibold text-neutral-900">Sessions</h2>
                <button
                  onClick={() => selectedCampaign && createSessionMutation.mutate(selectedCampaign.id)}
                  disabled={createSessionMutation.isPending}
                  className="rounded-lg bg-purple-600 px-3 py-1.5 text-sm text-white hover:bg-purple-700 disabled:opacity-50"
                >
                  <Plus className="h-4 w-4 inline mr-1" />
                  {createSessionMutation.isPending ? 'Adding...' : 'Add Session'}
                </button>
              </div>
              <div className="divide-y divide-neutral-100">
                {sessionsData?.sessions && sessionsData.sessions.length > 0 ? (
                  sessionsData.sessions.map((session) => (
                    <div
                      key={session.id}
                      className="px-4 py-3 flex items-center justify-between hover:bg-neutral-50"
                    >
                      <div>
                        <p className="font-medium text-neutral-900">
                          Session {session.session_number}
                          {session.title && `: ${session.title}`}
                        </p>
                        {session.scheduled_date && (
                          <p className="text-sm text-neutral-500">
                            {new Date(session.scheduled_date).toLocaleDateString()}
                          </p>
                        )}
                      </div>
                      <ChevronRight className="h-4 w-4 text-neutral-400" />
                    </div>
                  ))
                ) : (
                  <div className="px-4 py-8 text-center text-neutral-500">
                    No sessions yet
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <BookOpen className="mx-auto h-16 w-16 text-neutral-300" />
              <p className="mt-4 text-neutral-500">Select a campaign to view details</p>
            </div>
          </div>
        )}
      </div>

      {/* Create/Edit Modal */}
      {(showCreateModal || editingCampaign) && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-neutral-900">
                {editingCampaign ? 'Edit Campaign' : 'New Campaign'}
              </h2>
              <button
                onClick={() => {
                  setShowCreateModal(false);
                  setEditingCampaign(null);
                  resetForm();
                }}
                className="text-neutral-400 hover:text-neutral-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-neutral-700">
                  Campaign Name *
                </label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  required
                  className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  placeholder="e.g., Curse of Strahd"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-neutral-700">
                  Game System
                </label>
                <input
                  type="text"
                  value={formData.game_system}
                  onChange={(e) => setFormData({ ...formData, game_system: e.target.value })}
                  className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  placeholder="e.g., D&D 5e"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-neutral-700">
                  Description
                </label>
                <textarea
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  rows={3}
                  className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  placeholder="Brief description of the campaign..."
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-neutral-700">
                    Status
                  </label>
                  <select
                    value={formData.status}
                    onChange={(e) => setFormData({ ...formData, status: e.target.value })}
                    className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  >
                    <option value="planning">Planning</option>
                    <option value="active">Active</option>
                    <option value="paused">Paused</option>
                    <option value="completed">Completed</option>
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-neutral-700">
                    Player Count
                  </label>
                  <input
                    type="number"
                    value={formData.player_count || ''}
                    onChange={(e) =>
                      setFormData({
                        ...formData,
                        player_count: e.target.value ? parseInt(e.target.value) : null,
                      })
                    }
                    min={1}
                    className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  />
                </div>
              </div>

              <div className="flex justify-end gap-3 pt-4">
                <button
                  type="button"
                  onClick={() => {
                    setShowCreateModal(false);
                    setEditingCampaign(null);
                    resetForm();
                  }}
                  className="rounded-lg border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createMutation.isPending || updateMutation.isPending}
                  className="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
                >
                  {editingCampaign ? 'Save Changes' : 'Create Campaign'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
