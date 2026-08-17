/** Fetch wrapper with base URL. */
const BASE_URL = '';
const TIMEOUT_MS = 30_000;

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  // Nothing aborted these before, so a hung server left the query spinning
  // until the browser gave up.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const res = await fetch(`${BASE_URL}${path}`, {
      ...options,
      signal: controller.signal,
      headers: {
        // Only on requests that actually carry a body — a GET declaring
        // `Content-Type: application/json` is meaningless.
        ...(options?.body ? { 'Content-Type': 'application/json' } : {}),
        Accept: 'application/json',
        ...options?.headers,
      },
    });

    if (!res.ok) {
      throw new ApiError(res.status, await errorMessage(res));
    }
    return (await res.json()) as T;
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError(0, 'Request timed out');
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/** Prefer the API's `{"detail": …}`, fall back to the raw body. */
async function errorMessage(res: Response): Promise<string> {
  const text = await res.text();
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed.detail === 'string') return parsed.detail;
  } catch {
    /* not JSON */
  }
  return text || res.statusText;
}

export function get<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function patch<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: 'PATCH', body: JSON.stringify(body) });
}

export function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: 'POST', body: JSON.stringify(body) });
}

/**
 * A PATCH that survives the page going away.
 *
 * The readers save their position on a debounce, so a tab closed mid-timer
 * would lose it. `keepalive` lets the browser finish the request after the
 * document is gone; `sendBeacon` cannot be used because it only issues POSTs.
 * Fire-and-forget by design — there is nothing left to show an error to.
 */
export function patchKeepalive(path: string, body: unknown): void {
  try {
    void fetch(`${BASE_URL}${path}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
      headers: { 'Content-Type': 'application/json' },
      keepalive: true,
    }).catch(() => {});
  } catch {
    /* the page is unloading; there is nowhere to report this */
  }
}
