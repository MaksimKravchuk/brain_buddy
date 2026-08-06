/**
 * Minimal cookie-jar fetch for Node integration runs.
 *
 * On iOS the NSURLSession cookie jar handles the session cookie natively;
 * in Node nothing does, so this shim captures Set-Cookie responses and
 * replays them — proving the API client itself is transport-agnostic.
 */

export function createCookieFetch(baseFetch: typeof fetch = fetch): typeof fetch {
  const jar = new Map<string, string>();

  const cookieFetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const headers = new Headers(init?.headers);
    if (jar.size > 0) {
      headers.set(
        "Cookie",
        [...jar.entries()].map(([name, value]) => `${name}=${value}`).join("; "),
      );
    }
    const response = await baseFetch(input, { ...init, headers });
    const setCookies = response.headers.getSetCookie?.() ?? [];
    for (const line of setCookies) {
      const [pair] = line.split(";");
      const eq = pair.indexOf("=");
      if (eq > 0) {
        const name = pair.slice(0, eq).trim();
        const value = pair.slice(eq + 1).trim();
        if (value) {
          jar.set(name, value);
        } else {
          jar.delete(name);
        }
      }
    }
    return response;
  }) as typeof fetch;

  return cookieFetch;
}
