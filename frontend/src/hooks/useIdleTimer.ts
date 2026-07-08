import { useEffect, useRef, useState } from 'react';

export const IDLE_PROMPT_MINUTES = 30;

/**
 * Returns true after `idleMinutes` with no tracked activity
 * (mousemove / keydown / click / tab becoming visible again).
 * Any activity resets the timer and flips the result back to false.
 */
export function useIdleTimer(idleMinutes: number = IDLE_PROMPT_MINUTES): boolean {
  const [isIdle, setIsIdle] = useState(false);
  const timerRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    const idleMs = idleMinutes * 60 * 1000;

    const reset = () => {
      setIsIdle(false);
      if (timerRef.current !== undefined) {
        window.clearTimeout(timerRef.current);
      }
      timerRef.current = window.setTimeout(() => setIsIdle(true), idleMs);
    };

    const events: (keyof WindowEventMap)[] = ['mousemove', 'keydown', 'click'];
    events.forEach((e) => window.addEventListener(e, reset, { passive: true }));

    const onVisibility = () => {
      if (document.visibilityState === 'visible') reset();
    };
    document.addEventListener('visibilitychange', onVisibility);

    reset(); // start the countdown

    return () => {
      events.forEach((e) => window.removeEventListener(e, reset));
      document.removeEventListener('visibilitychange', onVisibility);
      if (timerRef.current !== undefined) {
        window.clearTimeout(timerRef.current);
      }
    };
  }, [idleMinutes]);

  return isIdle;
}
