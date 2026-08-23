import { useState } from 'react';
import { Loader2, Pause, Play } from 'lucide-react';
import { useQueueStatus } from '../hooks/useQueueStatus';
import { useProcessingControls } from '../hooks/useProcessingControls';
import { useIdleTimer } from '../hooks/useIdleTimer';

/**
 * Global, always-visible processing status + background-processing toggle.
 * Rendered once in App.tsx (inside the QueryClientProvider). Fixed bottom-right,
 * offset above the mobile bottom nav. Expands to show an idle prompt after the
 * idle threshold when processing is paused.
 */
export function ProcessingStatusWidget() {
  const { data: status } = useQueueStatus();
  const { pause, resume } = useProcessingControls();
  const isIdle = useIdleTimer();
  const [dismissed, setDismissed] = useState(false);

  // When the user becomes active again, allow the prompt to reappear after the
  // next full idle interval. Adjusting state during render (guarded by the
  // previous value) is React's documented alternative to a setState-in-effect.
  const [wasIdle, setWasIdle] = useState(isIdle);
  if (wasIdle !== isIdle) {
    setWasIdle(isIdle);
    if (!isIdle) setDismissed(false);
  }

  if (!status) return null;

  const paused = status.paused;
  const showPrompt = isIdle && paused && !dismissed;

  const onToggle = () => {
    if (paused) {
      resume.mutate();
    } else {
      pause.mutate();
    }
  };

  const detail = paused
    ? `${status.pending} queued · nothing running`
    : `${status.processing} processing · ${status.pending} queued`;

  return (
    <div
      className="fixed right-4 bottom-16 lg:bottom-4 z-40 w-64 rounded-xl border shadow-lg"
      style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
    >
      {showPrompt && (
        <div className="border-b p-3" style={{ borderColor: 'var(--color-border)' }}>
          <p className="text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
            You&apos;ve been idle — start background processing?
          </p>
          <div className="mt-2 flex gap-2">
            <button
              onClick={() => {
                resume.mutate();
                setDismissed(true);
              }}
              className="rounded-md px-3 py-1.5 text-sm font-medium text-white"
              style={{ backgroundColor: 'var(--color-accent)' }}
            >
              Start
            </button>
            <button
              onClick={() => setDismissed(true)}
              className="rounded-md border px-3 py-1.5 text-sm font-medium"
              style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-secondary)' }}
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      <div className="flex items-center gap-3 p-3">
        {paused ? (
          <Pause className="h-5 w-5" style={{ color: 'var(--color-text-secondary)' }} />
        ) : status.processing > 0 ? (
          <Loader2 className="h-5 w-5 animate-spin" style={{ color: 'var(--color-accent)' }} />
        ) : (
          <Play className="h-5 w-5" style={{ color: 'var(--color-accent)' }} />
        )}

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium" style={{ color: 'var(--color-text-primary)' }}>
            {paused ? 'Grimoire Paused' : 'Grimoire Working'}
          </p>
          <p className="truncate text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            {detail}
          </p>
        </div>

        <button
          role="switch"
          aria-checked={!paused}
          aria-label="Toggle background processing"
          onClick={onToggle}
          disabled={pause.isPending || resume.isPending}
          className="relative h-6 w-11 shrink-0 rounded-full transition-colors disabled:opacity-50"
          style={{ backgroundColor: paused ? 'var(--color-border)' : 'var(--color-accent)' }}
        >
          <span
            className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
              paused ? 'left-0.5' : 'left-5'
            }`}
          />
        </button>
      </div>
    </div>
  );
}
