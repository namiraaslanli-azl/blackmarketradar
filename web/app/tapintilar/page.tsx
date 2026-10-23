import Link from "next/link";
import { api, qs } from "@/lib/api";
import { compact, day, num, SOURCE_LABEL, STATUS_LABEL } from "@/lib/labels";
import { resolveRange } from "@/lib/range";
import type { FindingRow } from "@/lib/types";
import Status from "@/components/Status";

type SP = Promise<Record<string, string | undefined>>;
const LIMIT = 50;

function reach(f: FindingRow): string {
  const v = f.views ?? f.subscribers ?? f.followers;
  if (v === null || v === undefined) return "—";
  const unit = f.views ? "bax." : f.subscribers ? "abunə" : "izl.";
  return `${compact(v)} ${unit}`;
}

export default async function FindingsPage({ searchParams }: { searchParams: SP }) {
  const sp = await searchParams;
  const range = resolveRange(sp);
  const page = Number(sp.page ?? 1);
  const data = await api<{ total: number; items: FindingRow[] }>("/api/findings", {
    params: {
      source: sp.source, status: sp.status, q: sp.q, review: sp.review, impersonation: sp.impersonation, tag: sp.tag,
      in_range: sp.in_range, from: range.from, to: range.to, sort: sp.sort ?? "-last_seen", page, limit: LIMIT,
    },
  });
  const keep = { ...sp };
  const pageHref = (p: number) => `/tapintilar${qs({ ...keep, page: p })}`;
  const pages = Math.max(1, Math.ceil(data.total / LIMIT));

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Tapıntılar</h1>
          <p>
            {num(data.total)} nəticə
            {sp.in_range === "true" ? ` · ${range.from} — ${range.to} arası ilk dəfə görülənlər` : " · bütün dövr"}
          </p>
        </div>
      </div>

      <form className="filters" method="get">
        <input type="hidden" name="from" value={range.from} />
        <input type="hidden" name="to" value={range.to} />
        <input type="search" name="q" defaultValue={sp.q} placeholder="Domen, promo kod, kanal, açar söz…  ( / )" />
        <select name="source" defaultValue={sp.source ?? ""} aria-label="Mənbə">
          <option value="">Bütün mənbələr</option>
          {Object.entries(SOURCE_LABEL).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
        <select name="status" defaultValue={sp.status ?? ""} aria-label="Status">
          <option value="">Bütün statuslar</option>
          {Object.entries(STATUS_LABEL).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
        <select name="review" defaultValue={sp.review ?? ""} aria-label="Yoxlama">
          <option value="">Yoxlama: hamısı</option>
          <option value="true">Yoxlama gözləyir</option>
        </select>
        <select name="in_range" defaultValue={sp.in_range ?? ""} aria-label="Dövr">
          <option value="">Bütün dövr</option>
          <option value="true">Yalnız seçilmiş dövr</option>
        </select>
        <button className="btn" type="submit">Göstər</button>
        <Link className="btn ghost" href={`/tapintilar?from=${range.from}&to=${range.to}`}>Sıfırla</Link>
      </form>

      <div className="table-wrap">
        <table className="t">
          <thead>
            <tr>
              <th>ID</th>
              <th>Mənbə</th>
              <th>Obyekt</th>
              <th className="hide-sm">Operator</th>
              <th>Status</th>
              <th className="hide-sm">Kateqoriya / teqlər</th>
              <th className="num hide-sm">Əhatə</th>
              <th className="num">Son görülüb</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((f) => (
              <tr key={f.id}>
                <td className="mono">
                  <Link href={`/tapintilar/${f.id}${qs({ from: range.from, to: range.to })}`}>{f.id}</Link>
                </td>
                <td className="muted" style={{ whiteSpace: "nowrap" }}>{SOURCE_LABEL[f.source] ?? f.source}</td>
                <td className="url">
                  <div className="mono trunc" title={f.url}>
                    {f.source === "organic_domain" ? f.host : f.handle ? `@${f.handle}` : f.url.replace(/^https?:\/\/(www\.)?/, "")}
                  </div>
                  {f.title || f.text ? <div className="muted trunc" style={{ fontSize: 12 }}>{f.title ?? f.text}</div> : null}
                </td>
                <td className="hide-sm">{f.operator ?? <span className="faint">—</span>}</td>
                <td>
                  <Status s={f.status} />
                  {f.needs_review ? <div className="muted" style={{ fontSize: 11.5 }}>yoxlanmalı</div> : null}
                </td>
                <td className="hide-sm" style={{ maxWidth: 280 }}>
                  {f.category ? (
                    <div style={{ fontSize: 12.5 }}>
                      {f.category}
                      {f.category_suggested ? <span className="faint"> · təklif</span> : null}
                    </div>
                  ) : null}
                  {f.is_impersonation ? <span className="chip hot">imitasiya</span> : null}
                  {f.tags.filter((t) => !t.startsWith("pattern:") && t !== "historical").slice(0, 3).map((t) => (
                    <span key={t} className="chip">{t}</span>
                  ))}
                </td>
                <td className="num hide-sm">{reach(f)}</td>
                <td className="num">{day(f.last_seen)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="pager">
        <span>
          Səhifə {page} / {pages}
        </span>
        <span style={{ display: "flex", gap: 12 }}>
          {page > 1 ? <Link href={pageHref(page - 1)}>← Əvvəlki</Link> : <span className="faint">← Əvvəlki</span>}
          {page < pages ? <Link href={pageHref(page + 1)}>Növbəti →</Link> : <span className="faint">Növbəti →</span>}
        </span>
      </div>
    </>
  );
}
