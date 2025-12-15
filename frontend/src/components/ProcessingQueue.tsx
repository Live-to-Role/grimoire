import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  X,
  Loader2,
  CheckCircle,
  XCircle,
  Clock,
  Trash2,
  RefreshCw,
  RotateCcw,
  ImageOff,
} from 'lucide-react';
import api from '../api/client';

interface QueueStats {
  pending: number;
  processing: number;
  completed: number;
  failed: number;
  total: number;
}

interface QueueItem {
  id: number;
  product_id: number;
  product_name: string | null;
  task_type: string;
  status: string;
  priority: number;
  attempts: number;
  max_attempts: number;
  error_message: string | null;
  estimated_cost: number | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

interface ProcessingQueueProps {
  onClose: () => void;
}

const statusIcons: Record<string, React.ReactNode> = {
  pending: <Clock className="h-4 w-4 text-amber-500" />,
  processing: <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />,
  completed: <CheckCircle className="h-4 w-4 text-green-500" />,
  failed: <XCircle className="h-4 w-4 text-red-500" />,
};

const taskTypeLabels: Record<string, string> = {
  extract: 'Text Extraction',
  identify: 'AI Identification',
  suggest_tags: 'Tag Suggestions',
};

export function ProcessingQueue({ onClose }: ProcessingQueueProps) {
  const [filter, setFilter] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data: stats, isLoading: statsLoading } = useQuery<QueueStats>({
    queryKey: ['queue-stats'],
    queryFn: async () => {
      const response = await api.get('/queue/stats');
      return response.data;
    },
    refetchInterval: 3000,
  });

  const { data: queueData, isLoading: queueLoading } = useQuery<{ items: QueueItem[]; total: number }>({
    queryKey: ['queue-items', filter],
    queryFn: async () => {
      const params = filter ? { status: filter } : {};
      const response = await api.get('/queue', { params });
      return response.data;
    },
    refetchInterval: 3000,
  });

  const cancelMutation = useMutation({
    mutationFn: async (itemId: number) => {
      await api.delete(`/queue/${itemId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['queue-items'] });
      queryClient.invalidateQueries({ queryKey: ['queue-stats'] });
    },
  });

  const clearMutation = useMutation({
    mutationFn: async (status: string) => {
      await api.delete('/queue', { params: { status } });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['queue-items'] });
      queryClient.invalidateQueries({ queryKey: ['queue-stats'] });
    },
  });

  const retryMutation = useMutation({
    mutationFn: async (itemId: number) => {
      await api.post(`/queue/${itemId}/retry`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['queue-items'] });
      queryClient.invalidateQueries({ queryKey: ['queue-stats'] });
    },
  });

  const retryAllMutation = useMutation({
    mutationFn: async () => {
      await api.post('/queue/retry-all-failed');
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['queue-items'] });
      queryClient.invalidateQueries({ queryKey: ['queue-stats'] });
    },
  });

  const dismissMutation = useMutation({
    mutationFn: async ({ itemId, markAsArt }: { itemId: number; markAsArt: boolean }) => {
      await api.post(`/queue/${itemId}/dismiss`, null, { params: { mark_as_art: markAsArt } });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['queue-items'] });
      queryClient.invalidateQueries({ queryKey: ['queue-stats'] });
    },
  });

  const formatTime = (dateStr: string | null) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleTimeString();
  };

  const getProgress = () => {
    if (!stats || stats.total === 0) return 0;
    return Math.round((stats.completed / stats.total) * 100);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="flex h-[80vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl">
        <header className="flex items-center justify-between border-b border-neutral-200 px-6 py-4">
          <h2 className="text-xl font-semibold text-neutral-900">Processing Queue</h2>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-neutral-500 hover:bg-neutral-100"
          >
            <X className="h-5 w-5" />
          </button>
        </header>

        {/* Stats Bar */}
        <div className="border-b border-neutral-200 bg-neutral-50 px-6 py-4">
          {statsLoading ? (
            <div className="flex items-center gap-2 text-neutral-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading stats...
            </div>
          ) : stats ? (
            <div className="space-y-3">
              <div className="flex items-center gap-6">
                <button
                  onClick={() => setFilter(null)}
                  className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium ${
                    filter === null ? 'bg-purple-100 text-purple-700' : 'text-neutral-600 hover:bg-neutral-100'
                  }`}
                >
                  All ({stats.total})
                </button>
                <button
                  onClick={() => setFilter('pending')}
                  className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium ${
                    filter === 'pending' ? 'bg-amber-100 text-amber-700' : 'text-neutral-600 hover:bg-neutral-100'
                  }`}
                >
                  <Clock className="h-4 w-4" />
                  Pending ({stats.pending})
                </button>
                <button
                  onClick={() => setFilter('processing')}
                  className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium ${
                    filter === 'processing' ? 'bg-blue-100 text-blue-700' : 'text-neutral-600 hover:bg-neutral-100'
                  }`}
                >
                  <Loader2 className="h-4 w-4" />
                  Processing ({stats.processing})
                </button>
                <button
                  onClick={() => setFilter('completed')}
                  className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium ${
                    filter === 'completed' ? 'bg-green-100 text-green-700' : 'text-neutral-600 hover:bg-neutral-100'
                  }`}
                >
                  <CheckCircle className="h-4 w-4" />
                  Completed ({stats.completed})
                </button>
                <button
                  onClick={() => setFilter('failed')}
                  className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium ${
                    filter === 'failed' ? 'bg-red-100 text-red-700' : 'text-neutral-600 hover:bg-neutral-100'
                  }`}
                >
                  <XCircle className="h-4 w-4" />
                  Failed ({stats.failed})
                </button>
              </div>

              {/* Progress bar */}
              {stats.total > 0 && (
                <div className="space-y-1">
                  <div className="flex justify-between text-xs text-neutral-500">
                    <span>Progress</span>
                    <span>{getProgress()}%</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-neutral-200">
                    <div
                      className="h-full bg-gradient-to-r from-purple-500 to-purple-600 transition-all duration-300"
                      style={{ width: `${getProgress()}%` }}
                    />
                  </div>
                </div>
              )}
            </div>
          ) : null}
        </div>

        {/* Queue Items */}
        <div className="flex-1 overflow-auto">
          {queueLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-purple-600" />
            </div>
          ) : queueData?.items.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-neutral-500">
              <Clock className="h-12 w-12 mb-4 opacity-50" />
              <p>No items in queue</p>
            </div>
          ) : (
            <table className="w-full">
              <thead className="bg-neutral-50 text-left text-xs font-medium uppercase tracking-wider text-neutral-500">
                <tr>
                  <th className="px-6 py-3">Status</th>
                  <th className="px-6 py-3">Product</th>
                  <th className="px-6 py-3">Task</th>
                  <th className="px-6 py-3">Attempts</th>
                  <th className="px-6 py-3">Created</th>
                  <th className="px-6 py-3">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {queueData?.items.map((item) => (
                  <tr key={item.id} className="hover:bg-neutral-50">
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        {statusIcons[item.status] || statusIcons.pending}
                        <span className="text-sm capitalize">{item.status}</span>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <span className="text-sm font-medium text-neutral-900 truncate max-w-xs block">
                        {item.product_name || `Product #${item.product_id}`}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span className="text-sm text-neutral-600">
                        {taskTypeLabels[item.task_type] || item.task_type}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span className="text-sm text-neutral-500">
                        {item.attempts}/{item.max_attempts}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span className="text-sm text-neutral-500">
                        {formatTime(item.created_at)}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-1">
                        {item.status === 'pending' && (
                          <button
                            onClick={() => cancelMutation.mutate(item.id)}
                            disabled={cancelMutation.isPending}
                            className="rounded p-1 text-neutral-400 hover:bg-red-50 hover:text-red-600"
                            title="Cancel"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        )}
                        {item.status === 'failed' && (
                          <>
                            <button
                              onClick={() => retryMutation.mutate(item.id)}
                              disabled={retryMutation.isPending}
                              className="rounded p-1 text-neutral-400 hover:bg-blue-50 hover:text-blue-600"
                              title="Retry"
                            >
                              <RotateCcw className="h-4 w-4" />
                            </button>
                            <button
                              onClick={() => dismissMutation.mutate({ itemId: item.id, markAsArt: true })}
                              disabled={dismissMutation.isPending}
                              className="rounded p-1 text-neutral-400 hover:bg-purple-50 hover:text-purple-600"
                              title="Dismiss & mark as Art/Maps"
                            >
                              <ImageOff className="h-4 w-4" />
                            </button>
                          </>
                        )}
                        {item.error_message && (
                          <span
                            className="ml-2 text-xs text-red-500 cursor-help"
                            title={item.error_message}
                          >
                            Error
                          </span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Footer Actions */}
        <footer className="flex items-center justify-between border-t border-neutral-200 px-6 py-4">
          <div className="flex gap-2">
            {stats && stats.completed > 0 && (
              <button
                onClick={() => clearMutation.mutate('completed')}
                disabled={clearMutation.isPending}
                className="inline-flex items-center gap-2 rounded-lg border border-neutral-300 px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
              >
                <Trash2 className="h-4 w-4" />
                Clear Completed
              </button>
            )}
            {stats && stats.failed > 0 && (
              <>
                <button
                  onClick={() => retryAllMutation.mutate()}
                  disabled={retryAllMutation.isPending}
                  className="inline-flex items-center gap-2 rounded-lg border border-blue-300 px-3 py-2 text-sm font-medium text-blue-700 hover:bg-blue-50"
                >
                  <RotateCcw className="h-4 w-4" />
                  Retry All Failed
                </button>
                <button
                  onClick={() => clearMutation.mutate('failed')}
                  disabled={clearMutation.isPending}
                  className="inline-flex items-center gap-2 rounded-lg border border-red-300 px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-50"
                >
                  <Trash2 className="h-4 w-4" />
                  Clear Failed
                </button>
              </>
            )}
          </div>
          <button
            onClick={() => {
              queryClient.invalidateQueries({ queryKey: ['queue-items'] });
              queryClient.invalidateQueries({ queryKey: ['queue-stats'] });
            }}
            className="inline-flex items-center gap-2 rounded-lg bg-neutral-100 px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-200"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
        </footer>
      </div>
    </div>
  );
}
