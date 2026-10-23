import { api } from "@/lib/api";
import { dateTime, num } from "@/lib/labels";

interface Run {
  id: number; collector: string; started_at: string; finished_at: string | null; status: string;
  items_found: number; items_new: number; items_updated: number; errors: number; duration_ms: number | null;
  error_log: string | null;
}

export default async function RunsPage() {
  const runs = await api<Run[]>("/api/runs", { params: { limit: 200 } });
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Kollektorlar</h1>
          <p>Hər işə düşmə: tapılan, yeni, yenilənən, xətalar və müddət</p>
        </div>
      </div>
      {runs.length === 0 ? (
        <p className="muted">Hələ işə düşmə yoxdur. Zənginləşdirmə: <span className="mono">radar enrich</span></p>
      ) : (
        <div className="table-wrap">
          <table className="t">
            <thead>
              <tr>
                <th>Kollektor</th><th>Başladı</th><th>Status</th><th className="num">Tapıldı</th>
                <th className="num">Yeni</th><th className="num">Yeniləndi</th><th className="num">Xəta</th>
                <th className="num">Müddət</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id}>
                  <td className="mono">{r.collector}</td>
                  <td className="num" style={{ textAlign: "left" }}>{dateTime(r.started_at)}</td>
                  <td className={r.status === "failed" ? "signal" : undefined}>
                    {r.status}
                    {r.error_log ? (
                      <details>
                        <summary className="muted" style={{ fontSize: 12 }}>xətalar</summary>
                        <pre className="json" style={{ maxWidth: 520 }}>{r.error_log}</pre>
                      </details>
                    ) : null}
                  </td>
                  <td className="num">{num(r.items_found)}</td>
                  <td className="num">{num(r.items_new)}</td>
                  <td className="num">{num(r.items_updated)}</td>
                  <td className="num">{num(r.errors)}</td>
                  <td className="num">{r.duration_ms ? `${(r.duration_ms / 1000).toFixed(1)} s` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
