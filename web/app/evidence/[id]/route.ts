import { apiRaw } from "@/lib/api";

// Streams evidence files through the web server so the API token never reaches the browser.
export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) return new Response("not found", { status: 404 });
  const res = await apiRaw(`/api/evidence/${id}`);
  if (!res.ok) return new Response("not found", { status: res.status });
  const headers = new Headers();
  for (const h of ["content-type", "x-evidence-sha256"]) {
    const v = res.headers.get(h);
    if (v) headers.set(h, v);
  }
  headers.set("cache-control", "private, max-age=3600");
  // captured HTML must never execute in our origin
  headers.set("content-security-policy", "sandbox; default-src 'none'; img-src 'self'");
  return new Response(res.body, { status: 200, headers });
}
