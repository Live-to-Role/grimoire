import { useQuery } from '@tanstack/react-query';
import apiClient from '../api/client';

export interface QueueStats {
  pending: number;
  processing: number;
  completed: number;
  failed: number;
  total: number;
  pending_by_type?: Record<string, number>;
  paused: boolean;
}

/**
 * Single source of truth for queue status. Polls GET /queue/stats every 5s.
 * Shares the ['queue-stats'] query key so all consumers dedupe to one request.
 */
export function useQueueStatus() {
  return useQuery<QueueStats>({
    queryKey: ['queue-stats'],
    queryFn: async () => {
      const res = await apiClient.get<QueueStats>('/queue/stats');
      return res.data;
    },
    refetchInterval: 5000,
  });
}
