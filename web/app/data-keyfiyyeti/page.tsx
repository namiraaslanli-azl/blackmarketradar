import { api } from "@/lib/api";
import { dateTime, num, SOURCE_LABEL } from "@/lib/labels";

interface Batch {
  id: number; kind: string; filename: string; sha256: string; started_at: string;
  report: Record<string, any>;
}
interface Quality {
  total_findings: number; by_source: Record<string, number>; by_status: Record<string, number>;
  domains: Record<string, number>; with_operator: number; needs_review: number;
  needs_review_reasons: Record<string, number>; derived_findings: number; links: Record<string, number>;
}

const FIX_LABEL: Record<string, string> = {
  url_repaired: "Pozulmuş URL düzəldildi (/https://…, %2F)",
  url_scheme_added: "URL-ə https:// əlavə edildi",
  landing_not_url_kept_raw: "Meta landing URL deyil — xam dəyər saxlanıldı",
  link_rebuilt_from_username: "Telegram linki istifadəçi adından quruldu",
  fixed_excel_formula_username: "Excel formulu (=+…) t.me/+… linkinə çevrildi",
};
const REASON_LABEL: Record<string, string> = {
  derived_from_ad_landing: "Reklam landingindən yaranmış (tətbiq / hesab / domen)",
  derived_from_text: "Mətndəki linkdən yaranmış",
  derived_from_redirect: "Yönləndirmə hədəfi",
  telegram_unverified: "Telegram — yoxlanılmayıb",
  play_store_unverified: "Play Store — yoxlanılmayıb",
  licensed_brand_mentioned_check: "Lisenziyalı brend adı çəkilir",
  metadata_missing: "Metadata boşdur",
  moved_from_app_store_sheet: "“App store” vərəqindən domenə köçürülüb",
};

export default async function QualityPage() {
  const [batches, q] = await Promise.all([api<Batch[]>("/api/imports"), api<Quality>("/api/quality")]);
  const d = q.domains;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Data keyfiyyəti</h1>
          <p>İdxal nəticələri, təkrarların silinməsi, zənginləşdirmə və yoxlanmalı qeydlər</p>
        </div>
      </div>

      <div className="kpis">
        <div className="kpi"><div className="kpi-label">Unikal tapıntı</div><div className="kpi-value">{num(q.total_findings)}</div></div>
        <div className="kpi"><div className="kpi-label">Domen</div><div className="kpi-value">{num(d.total)}</div></div>
        <div className="kpi"><div className="kpi-label">Zənginləşdirilib</div><div className="kpi-value">{num(d.network_enriched)}</div><div className="kpi-sub">{num(d.awaiting_network_enrichment)} gözləyir</div></div>
        <div className="kpi"><div className="kpi-label">Operator təyin edilib</div><div className="kpi-value">{num(q.with_operator)}</div></div>
        <div className="kpi"><div className="kpi-label">Əlaqəli yeni obyekt</div><div className="kpi-value">{num(q.derived_findings)}</div></div>
        <div className="kpi alert"><div className="kpi-label">Yoxlanmalı</div><div className="kpi-value">{num(q.needs_review)}</div></div>
      </div>

      <div className="cols section">
        <section>
          <h2>İdxallar</h2>
          {batches.map((b) => {
            const r = b.report;
            return (
              <div key={b.id} style={{ borderTop: "1px solid var(--rule)", padding: "12px 0" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                  <strong className="mono">{b.filename}</strong>
                  <span className="muted">#{b.id} · {b.kind} · {dateTime(b.started_at)}</span>
                </div>
                <table className="t" style={{ marginTop: 8 }}>
                  <tbody>
                    <tr><td>Oxunan sətir</td><td className="num">{num(r.rows_read)}</td></tr>
                    <tr><td>Yeni yaradılan</td><td className="num">{num(r.created)}</td></tr>
                    <tr><td>Mövcud qeydlə birləşdirilən</td><td className="num">{num(r.merged_into_existing)}</td></tr>
                    {"duplicates_in_file" in r ? (
                      <tr><td>Silinən təkrarlar (fayl daxilində, normallaşdırılmış host)</td><td className="num">{num(r.duplicates_in_file)}</td></tr>
                    ) : null}
                    {"duplicates_merged_before_export" in r ? (
                      <tr><td>Eksportdan əvvəl birləşdirilmiş sətirlər</td><td className="num">{num(r.duplicates_merged_before_export)}</td></tr>
                    ) : null}
                    <tr><td>Keçərsiz URL (atlanıb)</td><td className="num">{num(r.skipped_invalid_url?.length ?? r.skipped_invalid_url ?? 0)}</td></tr>
                    {Object.entries(r.fixes ?? {}).map(([k, v]) => (
                      <tr key={k}><td className="muted">{FIX_LABEL[k] ?? k}</td><td className="num">{num(v as number)}</td></tr>
                    ))}
                  </tbody>
                </table>
                {r.duplicate_groups?.length ? (
                  <details style={{ marginTop: 8 }}>
                    <summary className="muted">Təkrar qruplar ({r.duplicate_groups.length})</summary>
                    <ul className="mono" style={{ fontSize: 12 }}>
                      {r.duplicate_groups.map((g: { key: string; rows: string[] }) => (
                        <li key={g.key}>{g.key} ← {g.rows.join(", ")}</li>
                      ))}
                    </ul>
                  </details>
                ) : null}
              </div>
            );
          })}
        </section>

        <section>
          <h2>Yoxlanmalı qeydlər</h2>
          <table className="t">
            <tbody>
              {Object.entries(q.needs_review_reasons).map(([k, v]) => (
                <tr key={k}>
                  <td>{REASON_LABEL[k] ?? k}</td>
                  <td className="num">{num(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h2 className="section">Domen zənginləşdirmə</h2>
          <table className="t">
            <tbody>
              <tr><td>Hesabatda əl ilə doldurulmuş (hostinq / registrator / abuse)</td><td className="num">{num(d.manual_enrichment_from_workbook)}</td></tr>
              <tr><td>Avtomatik zənginləşdirilmiş (RDAP, DNS, Cloudflare, ekran görüntüsü)</td><td className="num">{num(d.network_enriched)}</td></tr>
              <tr><td>Kateqoriya — hesabatdan</td><td className="num">{num(d.category_from_workbook)}</td></tr>
              <tr><td>Kateqoriya — qaydalarla təklif</td><td className="num">{num(d.category_suggested)}</td></tr>
              <tr><td>Brend imitasiyası</td><td className="num signal">{num(d.impersonation)}</td></tr>
            </tbody>
          </table>

          <h2 className="section">Mənbə üzrə</h2>
          <table className="t">
            <tbody>
              {Object.entries(q.by_source).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
                <tr key={k}><td>{SOURCE_LABEL[k] ?? k}</td><td className="num">{num(v)}</td></tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </>
  );
}
