import { useMutation, useQueryClient } from '@tanstack/react-query';
import apiClient from '../api/client';
import type { QueueStats } from './useQueueStatus';

interface OptimisticContext {
  prev?: QueueStats;
}

/**
 * Pause = stop background processing (POST /queue/pause) — "Grimoire Paused".
 * Resume = start it again (POST /queue/resume) — "Grimoire Working".
 * Both optimistically flip `paused` in the ['queue-stats'] cache so the toggle
 * feels instant, roll back on error, and re-sync on settle.
 */
export function useProcessingControls() {
  const queryClient = useQueryClient();

  const buildOptions = (endpoint: string, nextPaused: boolean) => ({
    mutationFn: async () => {
      await apiClient.post(endpoint);
    },
    onMutate: async (): Promise<OptimisticContext> => {
      await queryClient.cancelQueries({ queryKey: ['queue-stats'] });
      const prev = queryClient.getQueryData<QueueStats>(['queue-stats']);
      if (prev) {
        queryClient.setQueryData<QueueStats>(['queue-stats'], { ...prev, paused: nextPaused });
      }
      return { prev };
    },
    onError: (_err: Error, _vars: void, context: OptimisticContext | undefined) => {
      if (context?.prev) {
        queryClient.setQueryData(['queue-stats'], context.prev);
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['queue-stats'] });
    },
  });

  const pause = useMutation<void, Error, void, OptimisticContext>(
    buildOptions('/queue/pause', true),
  );
  const resume = useMutation<void, Error, void, OptimisticContext>(
    buildOptions('/queue/resume', false),
  );

  return { pause, resume };
}
