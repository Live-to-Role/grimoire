import { useEffect, useState } from 'react';
import { Loader2, Pause, Play } from 'lucide-react';
import { useQueueStatus } from '../hooks/useQueueStatus';
import { useProcessingControls } from '../hooks/useProcessingControls';
import { useIdleTimer } from '../hooks/useIdleTimer';

/**
 * Global, always-visible processing status + "I'm working" toggle.
 * Rendered once in App.tsx (inside the QueryClientProvider). Fixed bottom-right,
 * offset above the mobile bottom nav. Expands to show an idle prompt after the
 * idle threshold when processing is paused.
 */
export function ProcessingStatusWidget() {
  const { data: status } = useQueueStatus();
  const { pause, resume } = useProcessingControls();
  const isIdle = useIdleTimer();
  const [dismissed, setDismissed] = useState(false);

  // Once the user is active again, allow the prompt to appear on the next idle.
  useEffect(() => {
    if (!isIdle) setDismissed(false);
  }, [isIdle]);

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
    ? `${status.pending} queued`
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
            {paused ? "I'm working" : 'Processing'}
          </p>
          <p className="truncate text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            {detail}
          </p>
        </div>

        <button
          role="switch"
          aria-checked={paused}
          aria-label='Toggle "I&apos;m working" mode'
          onClick={onToggle}
          disabled={pause.isPending || resume.isPending}
          className="relative h-6 w-11 shrink-0 rounded-full transition-colors disabled:opacity-50"
          style={{ backgroundColor: paused ? 'var(--color-accent)' : 'var(--color-border)' }}
        >
          <span
            className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
              paused ? 'left-5' : 'left-0.5'
            }`}
          />
        </button>
      </div>
    </div>
  );
}
