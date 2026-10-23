import { api } from "@/lib/api";
import { dateTime, num } from "@/lib/labels";
import { runCollector, toggleCollector } from "./actions";

interface Run {
  id: number; collector: string; started_at: string; finished_at: string | null; status: string;
  items_found: number; items_new: number; items_updated: number; errors: number; duration_ms: number | null;
  error_log: string | null;
}
interface CollectorRow {
  name: string; title: string; schedule: string; enabled: boolean; missing: string[];
  last_run: { status: string; started_at: string; items_found: number; items_new: number; errors: number } | null;
  week: { found: number; new: number; errors: number };
}

const STATUS_AZ: Record<string, string> = {
  ok: "uğurlu", partial: "qismən", failed: "xəta", skipped: "atlandı", running: "işləyir",
};

function state(c: CollectorRow): { text: string; cls?: string } {
  if (c.missing.length) return { text: `gözləyir: ${c.missing.join(", ")}`, cls: "muted" };
  if (!c.enabled) return { text: "söndürülüb", cls: "faint" };
  if (c.last_run?.status === "failed") return { text: "son işə düşmə xəta ilə", cls: "signal" };
  return { text: "aktiv" };
}

export default async function CollectorsPage() {
  const [collectors, runs] = await Promise.all([
    api<CollectorRow[]>("/api/collectors"),
    api<Run[]>("/api/runs", { params: { limit: 150 } }),
  ]);
  const weekNew = collectors.reduce((a, c) => a + c.week.new, 0);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Kollektorlar</h1>
          <p>Son 7 gündə {num(weekNew)} yeni tapıntı · cədvəl Bakı vaxtı ilə (cron: dəqiqə saat)</p>
        </div>
      </div>

      <div className="table-wrap">
        <table className="t">
          <thead>
            <tr>
              <th>Kollektor</th>
              <th>Vəziyyət</th>
              <th className="hide-sm">Cədvəl</th>
              <th>Son işə düşmə</th>
              <th className="num">7 gün: yeni</th>
              <th className="num hide-sm">tapıldı</th>
              <th className="num hide-sm">xəta</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {collectors.map((c) => {
              const st = state(c);
              return (
                <tr key={c.name}>
                  <td>
                    <div>{c.title}</div>
                    <div className="mono muted" style={{ fontSize: 11.5 }}>{c.name}</div>
                  </td>
                  <td className={st.cls} style={{ maxWidth: 260 }}>{st.text}</td>
                  <td className="mono hide-sm">{c.schedule}</td>
                  <td>
                    {c.last_run ? (
                      <>
                        <div>{dateTime(c.last_run.started_at)}</div>
                        <div className={c.last_run.status === "failed" ? "signal" : "muted"} style={{ fontSize: 12 }}>
                          {STATUS_AZ[c.last_run.status] ?? c.last_run.status} · {num(c.last_run.items_new)} yeni
                        </div>
                      </>
                    ) : (
                      <span className="faint">—</span>
                    )}
                  </td>
                  <td className="num">{num(c.week.new)}</td>
                  <td className="num hide-sm">{num(c.week.found)}</td>
                  <td className={`num hide-sm${c.week.errors ? " signal" : ""}`}>{num(c.week.errors)}</td>
                  <td style={{ whiteSpace: "nowrap", textAlign: "right" }}>
                    <form action={runCollector} style={{ display: "inline" }}>
                      <input type="hidden" name="name" value={c.name} />
                      <button className="btn ghost" type="submit" disabled={c.missing.length > 0}>İndi işə sal</button>
                    </form>{" "}
                    <form action={toggleCollector} style={{ display: "inline" }}>
                      <input type="hidden" name="name" value={c.name} />
                      <input type="hidden" name="enabled" value={String(!c.enabled)} />
                      <button className="btn link" type="submit">{c.enabled ? "söndür" : "yandır"}</button>
                    </form>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <section className="section">
        <h2>İşə düşmə jurnalı</h2>
        {runs.length === 0 ? (
          <p className="muted">Hələ işə düşmə yoxdur.</p>
        ) : (
          <div className="table-wrap">
            <table className="t">
              <thead>
                <tr>
                  <th>Kollektor</th><th>Başladı</th><th>Status</th><th className="num">Tapıldı</th>
                  <th className="num">Yeni</th><th className="num hide-sm">Yeniləndi</th><th className="num">Xəta</th>
                  <th className="num hide-sm">Müddət</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id}>
                    <td className="mono">{r.collector}</td>
                    <td>{dateTime(r.started_at)}</td>
                    <td className={r.status === "failed" ? "signal" : r.status === "skipped" ? "muted" : undefined}>
                      {STATUS_AZ[r.status] ?? r.status}
                      {r.error_log ? (
                        <details>
                          <summary className="muted" style={{ fontSize: 12 }}>təfərrüat</summary>
                          <pre className="json" style={{ maxWidth: 520 }}>{r.error_log}</pre>
                        </details>
                      ) : null}
                    </td>
                    <td className="num">{num(r.items_found)}</td>
                    <td className="num">{num(r.items_new)}</td>
                    <td className="num hide-sm">{num(r.items_updated)}</td>
                    <td className="num">{num(r.errors)}</td>
                    <td className="num hide-sm">{r.duration_ms ? `${(r.duration_ms / 1000).toFixed(1)} s` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
