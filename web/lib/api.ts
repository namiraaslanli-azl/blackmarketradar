// Server-side API client. The browser never talks to the API directly.
const API_URL = process.env.API_URL ?? "http://localhost:8000";
const API_TOKEN = process.env.API_TOKEN ?? "";

export type Params = Record<string, string | string[] | number | boolean | undefined | null>;

export function qs(params: Params): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    for (const item of Array.isArray(v) ? v : [v]) sp.append(k, String(item));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export async function api<T>(path: string, init?: RequestInit & { params?: Params }): Promise<T> {
  const res = await fetch(`${API_URL}${path}${init?.params ? qs(init.params) : ""}`, {
    ...init,
    headers: { "content-type": "application/json", "x-api-token": API_TOKEN, ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`API ${res.status} ${path}`);
  return res.json() as Promise<T>;
}

export function apiRaw(path: string): Promise<Response> {
  return fetch(`${API_URL}${path}`, { headers: { "x-api-token": API_TOKEN }, cache: "no-store" });
}
