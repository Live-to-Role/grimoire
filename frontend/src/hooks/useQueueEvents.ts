import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

interface QueueEvent {
  type:
    | "task_completed"
    | "task_failed"
    | "batch_complete"
    | "stats_update";
  id?: number;
  task_type?: string;
  product_id?: number;
  error?: string;
  succeeded?: number;
  failed?: number;
  total?: number;
}

/**
 * Hook that connects to the queue SSE endpoint and invalidates
 * React Query caches when events arrive. Falls back to polling
 * if SSE is unavailable.
 */
export function useQueueEvents() {
  const queryClient = useQueryClient();
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const es = new EventSource("/api/v1/queue/events");
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const data: QueueEvent = JSON.parse(event.data);

        // Invalidate queue stats on any event
        queryClient.invalidateQueries({ queryKey: ["queue-stats"] });

        // On task completion, also invalidate the specific product
        if (
          data.type === "task_completed" &&
          data.product_id
        ) {
          queryClient.invalidateQueries({
            queryKey: ["product", data.product_id],
          });

          // If a cover was extracted, invalidate product list for thumbnail
          if (data.task_type === "cover") {
            queryClient.invalidateQueries({ queryKey: ["products"] });
          }
        }

        // On batch complete, invalidate queue items list
        if (data.type === "batch_complete") {
          queryClient.invalidateQueries({ queryKey: ["queue-items"] });
        }
      } catch {
        // Ignore parse errors
      }
    };

    es.onerror = () => {
      // SSE disconnected — React Query polling will take over as fallback
      es.close();
    };

    return () => {
      es.close();
    };
  }, [queryClient]);
}
