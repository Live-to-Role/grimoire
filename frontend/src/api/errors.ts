import type { AxiosError } from 'axios';

/**
 * Whether a failed request means the API is not accepting requests yet.
 *
 * The browser never talks to the API directly — nginx proxies it in Docker,
 * Vite's dev server proxies it in a native install — so a backend that has not
 * finished starting comes back as a *reply from the proxy*, not as a dead
 * connection. nginx answers 502; Vite answers 500 with an empty body. Both
 * otherwise read as "the server returned 500", which sounds like a bug in
 * Grimoire rather than "it is still booting, wait".
 *
 * The API takes up to a minute on a cold start, which is exactly when a new
 * user is clicking around, so this is a common case rather than an edge one.
 */
export function isBackendStarting(error: unknown): boolean {
  const axiosError = error as AxiosError<{ detail?: string }>;
  const response = axiosError?.response;

  // Request sent, nothing came back at all.
  if (!response) return Boolean(axiosError?.request);

  // Proxy could not reach the API.
  if (response.status === 502 || response.status === 503 || response.status === 504) {
    return true;
  }

  // Vite's dev proxy reports an unreachable target as a bodyless 500. A real
  // FastAPI 500 carries a `detail`, so the empty body is what separates them.
  return response.status === 500 && !response.data?.detail;
}

export const BACKEND_STARTING_MESSAGE =
  'The Grimoire API is not responding yet. It can take up to a minute to start — ' +
  'wait a few seconds and try again.';

/**
 * Turn a failed request into something the user (or a bug report) can act on,
 * preferring the API's own `detail` over a bare status code.
 */
export function describeApiError(error: unknown, fallback: string): string {
  const axiosError = error as AxiosError<{ detail?: string }>;

  if (isBackendStarting(error)) return BACKEND_STARTING_MESSAGE;

  if (axiosError?.response) {
    const detail = axiosError.response.data?.detail;
    if (detail) return detail;
    return `The server returned ${axiosError.response.status} ${axiosError.response.statusText}.`;
  }

  return axiosError?.message || fallback;
}
