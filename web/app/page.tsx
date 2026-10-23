import Link from "next/link";
import { api } from "@/lib/api";
import { compact, dateTime, num, SOURCE_LABEL } from "@/lib/labels";
import { resolveRange } from "@/lib/range";
import type { Overview } from "@/lib/types";

type SP = Promise<{ from?: string; to?: string }>;

export default async function OverviewPage({ searchParams }: { searchParams: SP }) {
  const sp = await searchParams;
  const range = resolveRange(sp);
  const o = await api<Overview>("/api/overview", { params: { from: range.from, to: range.to } });
  const st = o.by_status;
  const sources = Object.entries(o.by_source).sort((a, b) => b[1] - a[1]);
  const maxSource = Math.max(1, ...sources.map(([, c]) => c));
  const maxOp = Math.max(1, ...o.top_operators.map((x) => x.count));
  const q = `from=${range.from}&to=${range.to}`;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Ümumi baxış</h1>
          <p>
            {range.from === range.to ? range.from : `${range.from} — ${range.to}`} · yeni tapıntılar dövrə görə,
            status sayları bütün baza üzrə
          </p>
        </div>
      </div>

      <div className="kpis">
        <div className="kpi alert">
          <div className="kpi-label">Yeni tapıntılar</div>
          <div className="kpi-value">{num(o.new)}</div>
          <div className="kpi-sub">seçilmiş dövr · tarixi idxal {num(o.imported)} ayrıca</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">Təsdiqlənib</div>
          <div className="kpi-value">{num(st.confirmed ?? 0)}</div>
          <div className="kpi-sub">aktiv qanunsuz</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">Şikayət olunub</div>
          <div className="kpi-value">{num(st.reported ?? 0)}</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">Bloklanıb</div>
          <div className="kpi-value">{num(st.blocked ?? 0)}</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">Yoxlama gözləyir</div>
          <div className="kpi-value">{num(o.needs_review)}</div>
          <div className="kpi-sub">
            <Link href={`/tapintilar?review=true&${q}`}>növbəyə bax</Link>
          </div>
        </div>
        <div className="kpi alert">
          <div className="kpi-label">Brend imitasiyası</div>
          <div className="kpi-value">{num(o.impersonation)}</div>
          <div className="kpi-sub">
            <Link href={`/tapintilar?impersonation=true&${q}`}>siyahı</Link>
          </div>
        </div>
      </div>

      <div className="cols section">
        <section>
          <h2>Mənbə üzrə yeni tapıntılar</h2>
          {sources.length === 0 ? (
            <p className="muted">
              Bu dövrdə kollektorlar yeni tapıntı qeydə almayıb. Tarixi idxal ({num(o.imported)}) burada sayılmır —{" "}
              <Link href="/tapintilar?tag=imported">idxal olunmuş qeydlər</Link>.
            </p>
          ) : (
            <table className="t">
              <thead>
                <tr>
                  <th>Mənbə</th>
                  <th className="num">Say</th>
                  <th style={{ width: "45%" }} />
                </tr>
              </thead>
              <tbody>
                {sources.map(([s, c]) => (
                  <tr key={s}>
                    <td>
                      <Link href={`/tapintilar?source=${s}&in_range=true&${q}`}>{SOURCE_LABEL[s] ?? s}</Link>
                    </td>
                    <td className="num">{num(c)}</td>
                    <td>
                      <div className="bar">
                        <span style={{ width: `${(c / maxSource) * 100}%` }} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section>
          <h2>Ən çox rast gəlinən operatorlar</h2>
          <table className="t">
            <thead>
              <tr>
                <th>Operator</th>
                <th className="num">Tapıntı</th>
                <th style={{ width: "40%" }} />
              </tr>
            </thead>
            <tbody>
              {o.top_operators.map((x) => (
                <tr key={x.operator}>
                  <td>{x.operator}</td>
                  <td className="num">{compact(x.count)}</td>
                  <td>
                    <div className="bar signal">
                      <span style={{ width: `${(x.count / maxOp) * 100}%` }} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>

      <section className="section">
        <h2>Kollektorların vəziyyəti</h2>
        {o.collectors.length === 0 ? (
          <p className="muted">Hələ heç bir kollektor işləməyib.</p>
        ) : (
          <table className="t">
            <thead>
              <tr>
                <th>Kollektor</th>
                <th>Son işə düşmə</th>
                <th>Status</th>
                <th className="num">Tapıldı</th>
                <th className="num">Xəta</th>
                <th className="num hide-sm">Müddət</th>
              </tr>
            </thead>
            <tbody>
              {o.collectors.map((c) => (
                <tr key={c.collector}>
                  <td className="mono">{c.collector}</td>
                  <td>{dateTime(c.started_at)}</td>
                  <td className={c.status === "failed" ? "signal" : c.status === "partial" ? "" : "muted"}>{c.status}</td>
                  <td className="num">{num(c.items_found)}</td>
                  <td className="num">{num(c.errors)}</td>
                  <td className="num hide-sm">{c.duration_ms ? `${Math.round(c.duration_ms / 1000)} s` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
