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
  Clock,
  FileText,
  Search,
  Check,
  ExternalLink,
  History,
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
  duration_minutes: number | null;
  status: string;
  summary: string | null;
  notes: string | null;
}

interface CampaignProduct {
  id: number;
  title: string;
  game_system: string | null;
  product_type: string | null;
}

interface CampaignDetail extends Campaign {
  products: CampaignProduct[];
  sessions: Session[];
  notes: string | null;
}

interface SessionFormData {
  title: string;
  scheduled_date: string;
  actual_date: string;
  duration_minutes: number | null;
  status: string;
  summary: string;
  notes: string;
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
  const [editingSession, setEditingSession] = useState<Session | null>(null);
  const [showProductPicker, setShowProductPicker] = useState(false);
  const [productSearch, setProductSearch] = useState('');
  const [sessionFormData, setSessionFormData] = useState<SessionFormData>({
    title: '',
    scheduled_date: '',
    actual_date: '',
    duration_minutes: null,
    status: 'planned',
    summary: '',
    notes: '',
  });

  const { data: campaignsData, isLoading } = useQuery({
    queryKey: ['campaigns'],
    queryFn: async () => {
      const res = await apiClient.get<{ campaigns: Campaign[] }>('/campaigns');
      return res.data;
    },
  });

  const { data: campaignDetail } = useQuery({
    queryKey: ['campaign-detail', selectedCampaign?.id],
    queryFn: async () => {
      if (!selectedCampaign) return null;
      const res = await apiClient.get<CampaignDetail>(
        `/campaigns/${selectedCampaign.id}`
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

  const updateSessionMutation = useMutation({
    mutationFn: async ({ campaignId, sessionId, data }: { campaignId: number; sessionId: number; data: Record<string, unknown> }) => {
      await apiClient.put(`/campaigns/${campaignId}/sessions/${sessionId}`, data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sessions', selectedCampaign?.id] });
      setEditingSession(null);
      resetSessionForm();
    },
  });

  const deleteSessionMutation = useMutation({
    mutationFn: async ({ campaignId, sessionId }: { campaignId: number; sessionId: number }) => {
      await apiClient.delete(`/campaigns/${campaignId}/sessions/${sessionId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sessions', selectedCampaign?.id] });
      queryClient.invalidateQueries({ queryKey: ['campaigns'] });
      setEditingSession(null);
      resetSessionForm();
    },
  });

  const removeProductMutation = useMutation({
    mutationFn: async ({ campaignId, productId }: { campaignId: number; productId: number }) => {
      await apiClient.delete(`/campaigns/${campaignId}/products/${productId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['campaign-detail', selectedCampaign?.id] });
    },
  });

  const handleRemoveProduct = (productId: number) => {
    if (selectedCampaign && confirm('Remove this product from the campaign?')) {
      removeProductMutation.mutate({
        campaignId: selectedCampaign.id,
        productId,
      });
    }
  };

  const addProductMutation = useMutation({
    mutationFn: async ({ campaignId, productId }: { campaignId: number; productId: number }) => {
      await apiClient.post(`/campaigns/${campaignId}/products/${productId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['campaign-detail', selectedCampaign?.id] });
    },
  });

  const { data: searchResults } = useQuery({
    queryKey: ['product-search', productSearch],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (productSearch) params.set('search', productSearch);
      params.set('limit', '20');
      const res = await apiClient.get<{ products: Array<{ id: number; title: string; file_name: string; game_system: string | null; product_type: string | null }> }>(
        `/products?${params.toString()}`
      );
      return res.data.products;
    },
    enabled: showProductPicker,
  });

  const handleAddProduct = (productId: number) => {
    if (selectedCampaign) {
      addProductMutation.mutate({
        campaignId: selectedCampaign.id,
        productId,
      });
    }
  };

  const isProductInCampaign = (productId: number) => {
    return campaignDetail?.products?.some(p => p.id === productId) || false;
  };

  const resetForm = () => {
    setFormData({
      name: '',
      description: '',
      game_system: '',
      status: 'active',
      player_count: null,
    });
  };

  const resetSessionForm = () => {
    setSessionFormData({
      title: '',
      scheduled_date: '',
      actual_date: '',
      duration_minutes: null,
      status: 'planned',
      summary: '',
      notes: '',
    });
  };

  const openSessionModal = (session: Session) => {
    setEditingSession(session);
    setSessionFormData({
      title: session.title || '',
      scheduled_date: session.scheduled_date ? session.scheduled_date.split('T')[0] : '',
      actual_date: session.actual_date ? session.actual_date.split('T')[0] : '',
      duration_minutes: session.duration_minutes,
      status: session.status,
      summary: session.summary || '',
      notes: session.notes || '',
    });
  };

  const getPreviousSession = (currentSession: Session): Session | null => {
    if (!campaignDetail?.sessions) return null;
    const sortedSessions = [...campaignDetail.sessions].sort((a, b) => a.session_number - b.session_number);
    const currentIndex = sortedSessions.findIndex(s => s.id === currentSession.id);
    if (currentIndex > 0) {
      return sortedSessions[currentIndex - 1];
    }
    return null;
  };

  const openProductPdf = (productId: number) => {
    window.open(`/api/v1/products/${productId}/pdf`, '_blank');
  };

  const openAllCampaignPdfs = () => {
    if (campaignDetail?.products) {
      campaignDetail.products.forEach((product, index) => {
        setTimeout(() => openProductPdf(product.id), index * 200);
      });
    }
  };

  const handleSessionSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (editingSession && selectedCampaign) {
      const data: Record<string, unknown> = {
        title: sessionFormData.title || null,
        status: sessionFormData.status,
        summary: sessionFormData.summary || null,
        notes: sessionFormData.notes || null,
        duration_minutes: sessionFormData.duration_minutes,
      };
      if (sessionFormData.scheduled_date) {
        data.scheduled_date = sessionFormData.scheduled_date;
      }
      if (sessionFormData.actual_date) {
        data.actual_date = sessionFormData.actual_date;
      }
      updateSessionMutation.mutate({
        campaignId: selectedCampaign.id,
        sessionId: editingSession.id,
        data,
      });
    }
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

            {/* Products Section */}
            <div className="rounded-xl border border-neutral-200 bg-white mb-6">
              <div className="border-b border-neutral-200 px-4 py-3 flex items-center justify-between">
                <h2 className="font-semibold text-neutral-900">
                  Products ({campaignDetail?.products?.length || 0})
                </h2>
                <div className="flex items-center gap-2">
                  {campaignDetail?.products && campaignDetail.products.length > 0 && (
                    <button
                      onClick={openAllCampaignPdfs}
                      className="rounded-lg border border-neutral-300 bg-white px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
                      title="Open all PDFs in new tabs"
                    >
                      <ExternalLink className="h-4 w-4 inline mr-1" />
                      Open All
                    </button>
                  )}
                  <button
                    onClick={() => setShowProductPicker(true)}
                    className="rounded-lg bg-purple-600 px-3 py-1.5 text-sm text-white hover:bg-purple-700"
                  >
                    <Plus className="h-4 w-4 inline mr-1" />
                    Add Product
                  </button>
                </div>
              </div>
              <div className="divide-y divide-neutral-100">
                {campaignDetail?.products && campaignDetail.products.length > 0 ? (
                  campaignDetail.products.map((product: CampaignProduct) => (
                    <div
                      key={product.id}
                      className="px-4 py-3 flex items-center justify-between hover:bg-neutral-50 group"
                    >
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-neutral-900 truncate">
                          {product.title}
                        </p>
                        <div className="flex items-center gap-2 mt-0.5 text-sm text-neutral-500">
                          {product.game_system && (
                            <span>{product.game_system}</span>
                          )}
                          {product.product_type && (
                            <span className="capitalize">{product.product_type}</span>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => openProductPdf(product.id)}
                          className="p-1 text-neutral-400 hover:text-purple-600 opacity-0 group-hover:opacity-100 transition-opacity"
                          title="Open PDF"
                        >
                          <ExternalLink className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => handleRemoveProduct(product.id)}
                          className="p-1 text-neutral-400 hover:text-red-600"
                          title="Remove from campaign"
                        >
                          <X className="h-4 w-4" />
                        </button>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="px-4 py-8 text-center text-neutral-500">
                    <BookOpen className="mx-auto h-8 w-8 text-neutral-300 mb-2" />
                    <p>No products linked yet</p>
                    <button
                      onClick={() => setShowProductPicker(true)}
                      className="mt-2 text-sm text-purple-600 hover:text-purple-700"
                    >
                      Add your first product
                    </button>
                  </div>
                )}
              </div>
            </div>

            {/* Sessions Section */}
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
                {campaignDetail?.sessions && campaignDetail.sessions.length > 0 ? (
                  campaignDetail.sessions.map((session: Session) => (
                    <button
                      key={session.id}
                      onClick={() => openSessionModal(session)}
                      className="w-full px-4 py-3 flex items-center justify-between hover:bg-neutral-50 text-left"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="font-medium text-neutral-900">
                            Session {session.session_number}
                            {session.title && `: ${session.title}`}
                          </p>
                          <span
                            className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                              session.status === 'completed'
                                ? 'bg-green-100 text-green-700'
                                : session.status === 'cancelled'
                                ? 'bg-red-100 text-red-700'
                                : 'bg-blue-100 text-blue-700'
                            }`}
                          >
                            {session.status}
                          </span>
                        </div>
                        <div className="flex items-center gap-3 mt-1 text-sm text-neutral-500">
                          {session.scheduled_date && (
                            <span className="flex items-center gap-1">
                              <Calendar className="h-3 w-3" />
                              {new Date(session.scheduled_date).toLocaleDateString()}
                            </span>
                          )}
                          {session.duration_minutes && (
                            <span className="flex items-center gap-1">
                              <Clock className="h-3 w-3" />
                              {session.duration_minutes} min
                            </span>
                          )}
                          {session.summary && (
                            <span className="flex items-center gap-1">
                              <FileText className="h-3 w-3" />
                              Has summary
                            </span>
                          )}
                        </div>
                      </div>
                      <ChevronRight className="h-4 w-4 text-neutral-400 flex-shrink-0" />
                    </button>
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

      {/* Session Edit Modal */}
      {editingSession && selectedCampaign && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-2xl rounded-xl bg-white p-6 shadow-xl max-h-[90vh] overflow-y-auto">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-neutral-900">
                Edit Session {editingSession.session_number}
              </h2>
              <button
                onClick={() => {
                  setEditingSession(null);
                  resetSessionForm();
                }}
                className="text-neutral-400 hover:text-neutral-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Previous Session Summary */}
            {(() => {
              const prevSession = getPreviousSession(editingSession);
              if (prevSession && prevSession.summary) {
                return (
                  <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <History className="h-4 w-4 text-amber-600" />
                      <h3 className="text-sm font-medium text-amber-800">
                        Previous Session: {prevSession.title || `Session ${prevSession.session_number}`}
                      </h3>
                    </div>
                    <p className="text-sm text-amber-700 whitespace-pre-wrap">
                      {prevSession.summary}
                    </p>
                  </div>
                );
              }
              return null;
            })()}

            <form onSubmit={handleSessionSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-neutral-700">
                  Session Title
                </label>
                <input
                  type="text"
                  value={sessionFormData.title}
                  onChange={(e) => setSessionFormData({ ...sessionFormData, title: e.target.value })}
                  className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  placeholder="e.g., The Goblin Ambush"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-neutral-700">
                    Scheduled Date
                  </label>
                  <input
                    type="date"
                    value={sessionFormData.scheduled_date}
                    onChange={(e) => setSessionFormData({ ...sessionFormData, scheduled_date: e.target.value })}
                    className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-neutral-700">
                    Actual Date
                  </label>
                  <input
                    type="date"
                    value={sessionFormData.actual_date}
                    onChange={(e) => setSessionFormData({ ...sessionFormData, actual_date: e.target.value })}
                    className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-neutral-700">
                    Duration (minutes)
                  </label>
                  <input
                    type="number"
                    value={sessionFormData.duration_minutes || ''}
                    onChange={(e) => setSessionFormData({
                      ...sessionFormData,
                      duration_minutes: e.target.value ? parseInt(e.target.value) : null,
                    })}
                    min={0}
                    className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                    placeholder="e.g., 180"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-neutral-700">
                    Status
                  </label>
                  <select
                    value={sessionFormData.status}
                    onChange={(e) => setSessionFormData({ ...sessionFormData, status: e.target.value })}
                    className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  >
                    <option value="planned">Planned</option>
                    <option value="completed">Completed</option>
                    <option value="cancelled">Cancelled</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-neutral-700">
                  Summary
                </label>
                <textarea
                  value={sessionFormData.summary}
                  onChange={(e) => setSessionFormData({ ...sessionFormData, summary: e.target.value })}
                  rows={3}
                  className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  placeholder="What happened in this session..."
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-neutral-700">
                  Notes
                </label>
                <textarea
                  value={sessionFormData.notes}
                  onChange={(e) => setSessionFormData({ ...sessionFormData, notes: e.target.value })}
                  rows={4}
                  className="mt-1 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  placeholder="Prep notes, reminders, follow-ups..."
                />
              </div>

              <div className="flex justify-between pt-4">
                <button
                  type="button"
                  onClick={() => {
                    if (confirm('Delete this session?')) {
                      deleteSessionMutation.mutate({
                        campaignId: selectedCampaign.id,
                        sessionId: editingSession.id,
                      });
                    }
                  }}
                  disabled={deleteSessionMutation.isPending}
                  className="rounded-lg border border-red-300 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
                >
                  {deleteSessionMutation.isPending ? 'Deleting...' : 'Delete Session'}
                </button>
                <div className="flex gap-3">
                  <button
                    type="button"
                    onClick={() => {
                      setEditingSession(null);
                      resetSessionForm();
                    }}
                    className="rounded-lg border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={updateSessionMutation.isPending}
                    className="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
                  >
                    {updateSessionMutation.isPending ? 'Saving...' : 'Save Changes'}
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Product Picker Modal */}
      {showProductPicker && selectedCampaign && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-xl max-h-[80vh] flex flex-col">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-neutral-900">
                Add Products to Campaign
              </h2>
              <button
                onClick={() => {
                  setShowProductPicker(false);
                  setProductSearch('');
                }}
                className="text-neutral-400 hover:text-neutral-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="relative mb-4">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-neutral-400" />
              <input
                type="text"
                value={productSearch}
                onChange={(e) => setProductSearch(e.target.value)}
                placeholder="Search products..."
                className="w-full rounded-lg border border-neutral-300 pl-10 pr-3 py-2 text-sm focus:border-purple-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
              />
            </div>

            <div className="flex-1 overflow-y-auto divide-y divide-neutral-100 border border-neutral-200 rounded-lg">
              {searchResults && searchResults.length > 0 ? (
                searchResults.map((product) => {
                  const inCampaign = isProductInCampaign(product.id);
                  return (
                    <div
                      key={product.id}
                      className={`px-4 py-3 flex items-center justify-between ${
                        inCampaign ? 'bg-purple-50' : 'hover:bg-neutral-50'
                      }`}
                    >
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-neutral-900 truncate">
                          {product.title || product.file_name}
                        </p>
                        <div className="flex items-center gap-2 mt-0.5 text-sm text-neutral-500">
                          {product.game_system && (
                            <span>{product.game_system}</span>
                          )}
                          {product.product_type && (
                            <span className="capitalize">{product.product_type}</span>
                          )}
                        </div>
                      </div>
                      {inCampaign ? (
                        <button
                          onClick={() => handleRemoveProduct(product.id)}
                          className="ml-2 flex items-center gap-1 rounded-lg bg-purple-100 px-3 py-1.5 text-sm font-medium text-purple-700"
                        >
                          <Check className="h-4 w-4" />
                          Added
                        </button>
                      ) : (
                        <button
                          onClick={() => handleAddProduct(product.id)}
                          disabled={addProductMutation.isPending}
                          className="ml-2 rounded-lg bg-purple-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
                        >
                          Add
                        </button>
                      )}
                    </div>
                  );
                })
              ) : (
                <div className="px-4 py-8 text-center text-neutral-500">
                  {productSearch ? 'No products found' : 'Search for products to add'}
                </div>
              )}
            </div>

            <div className="mt-4 flex justify-end">
              <button
                onClick={() => {
                  setShowProductPicker(false);
                  setProductSearch('');
                }}
                className="rounded-lg bg-neutral-100 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-200"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
