import Link from "next/link";
import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import { compact, dateTime, day, SOURCE_LABEL } from "@/lib/labels";
import type { FindingDetail } from "@/lib/types";
import Status from "@/components/Status";

const LINK_LABEL: Record<string, string> = {
  operator: "Operator", favicon_hash: "Favicon hash", redirect: "Yönləndirmə", promo_code: "Promo kod",
  payment_method: "Ödəniş üsulu", telegram_link: "Telegram link", app_package: "Tətbiq paketi", landing: "Landing",
  ad_cluster: "Kampaniya klasteri", mentions_domain: "Mətndə domen", linked_account: "Əlaqəli hesab",
};

function Row({ k, children }: { k: string; children: React.ReactNode }) {
  if (children === null || children === undefined || children === "") return null;
  return (
    <>
      <dt>{k}</dt>
      <dd>{children}</dd>
    </>
  );
}

export default async function FindingPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let f: FindingDetail;
  try {
    f = await api<FindingDetail>(`/api/findings/${encodeURIComponent(id)}`);
  } catch {
    notFound();
  }
  const net = f.enrichment?.network;
  const manual = f.enrichment?.manual;
  const shot = f.evidence.find((e) => e.kind === "screenshot");

  return (
    <>
      <div className="page-head">
        <div>
          <p className="mono" style={{ margin: 0 }}>
            <Link href="/tapintilar">Tapıntılar</Link> / {f.id}
          </p>
          <h1 className="mono" style={{ fontSize: 20, marginTop: 6, overflowWrap: "anywhere" }}>
            {f.source === "organic_domain" ? f.host : f.handle ? `@${f.handle}` : f.url}
          </h1>
          <p>
            {SOURCE_LABEL[f.source] ?? f.source} · <Status s={f.status} /> · ilk dəfə {day(f.first_seen)}, son{" "}
            {day(f.last_seen)}
          </p>
        </div>
      </div>
      {f.is_impersonation ? <div className="notice">Azerlotereya / lisenziyalı brendin imitasiyası ehtimalı.</div> : null}
      {f.needs_review ? (
        <div className="notice">Yoxlanmalıdır: {f.review_reasons.join(", ") || "—"}</div>
      ) : null}

      <div className="cols">
        <section>
          <h2>Məlumat</h2>
          <dl className="dl">
            <Row k="URL">
              <a className="mono" href={f.url} target="_blank" rel="noreferrer noopener">{f.url}</a>
            </Row>
            <Row k="Operator">{f.operator}</Row>
            <Row k="Başlıq">{f.title}</Row>
            <Row k="Mətn">{f.text}</Row>
            <Row k="Reklamçı">{f.advertiser}</Row>
            <Row k="Landing">
              {f.landing_url ? <span className="mono">{f.landing_url}</span> : f.landing_raw ? <span className="muted">{f.landing_raw} (URL deyil)</span> : null}
            </Row>
            <Row k="Kateqoriya">
              {f.category ? `${f.category}${f.category_suggested ? " (avtomatik təklif)" : ""}` : null}
            </Row>
            <Row k="Təsir mexanizmi">{f.suggested_action}</Row>
            <Row k="Orijinal status">
              {[f.original_status, f.complaint_status].filter(Boolean).join(" · ") || null}
            </Row>
            <Row k="Canlıdır">{f.is_live === null ? "bilinmir" : f.is_live ? "bəli" : "xeyr"}</Row>
            <Row k="Əhatə">
              {[f.views && `${compact(f.views)} baxış`, f.subscribers && `${compact(f.subscribers)} abunəçi`,
                f.followers && `${compact(f.followers)} izləyici`, f.likes && `${compact(f.likes)} bəyənmə`]
                .filter(Boolean).join(" · ") || null}
            </Row>
            <Row k="Açar sözlər">
              {f.matched_keywords.length ? f.matched_keywords.map((k) => <span key={k} className="chip">{k}</span>) : null}
            </Row>
            <Row k="Teqlər">{f.tags.length ? f.tags.map((t) => <span key={t} className="chip">{t}</span>) : null}</Row>
          </dl>

          <div className="section">
            <h2>Əlaqələr</h2>
            {f.links.length === 0 ? (
              <p className="muted">Əlaqə yoxdur.</p>
            ) : (
              <table className="t">
                <thead>
                  <tr><th>Növ</th><th>Dəyər / obyekt</th><th>Status</th></tr>
                </thead>
                <tbody>
                  {f.links.map((l, i) => (
                    <tr key={i}>
                      <td className="muted" style={{ whiteSpace: "nowrap" }}>
                        {LINK_LABEL[l.type] ?? l.type}{l.direction === "in" ? " ←" : ""}
                      </td>
                      <td className="mono" style={{ overflowWrap: "anywhere" }}>
                        {l.finding ? <Link href={`/tapintilar/${l.finding.id}`}>{l.finding.url}</Link> : l.value}
                      </td>
                      <td>{l.finding ? <Status s={l.finding.status} /> : null}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </section>

        <section>
          <h2>Sübut</h2>
          {shot ? (
            <a href={`/evidence/${shot.id}`} target="_blank" rel="noreferrer">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img className="shot" src={`/evidence/${shot.id}`} alt={`Ekran görüntüsü ${f.host ?? f.url}`} />
            </a>
          ) : (
            <p className="muted">Ekran görüntüsü hələ yoxdur — zənginləşdirmə işindən sonra görünəcək.</p>
          )}
          {f.evidence.length ? (
            <table className="t" style={{ marginTop: 12 }}>
              <thead>
                <tr><th>Növ</th><th>Tarix</th><th>SHA-256</th></tr>
              </thead>
              <tbody>
                {f.evidence.map((e) => (
                  <tr key={e.id}>
                    <td><a href={`/evidence/${e.id}`} target="_blank" rel="noreferrer">{e.kind}</a></td>
                    <td className="num">{dateTime(e.captured_at)}</td>
                    <td className="mono trunc" style={{ maxWidth: 160 }} title={e.sha256}>{e.sha256}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}

          <div className="section">
            <h2>Hostinq və qeydiyyat</h2>
            <dl className="dl">
              <Row k="Registrator">{net?.abuse?.registrar_name ?? manual?.hosting_registrar}</Row>
              <Row k="Hostinq">{net?.abuse?.hosting_name}</Row>
              <Row k="IP">{net?.hosting?.ip ? <span className="mono">{net.hosting.ip}</span> : null}</Row>
              <Row k="Cloudflare">
                {net ? (net.cloudflare?.is_cloudflare ? `bəli (${net.cloudflare.evidence.join(", ")})` : "xeyr") : manual?.cloudflare}
              </Row>
              <Row k="Abuse (hostinq)">{net?.abuse?.hosting ?? manual?.abuse_email}</Row>
              <Row k="Abuse (registrator)">{net?.abuse?.registrar}</Row>
              <Row k="Son URL">{net?.http?.final_url ? <span className="mono">{net.http.final_url}</span> : null}</Row>
              <Row k="Yönləndirmə zənciri">
                {net?.http?.chain?.length > 1
                  ? net.http.chain.map((h: { url: string; status: number | null }, i: number) => (
                      <div key={i} className="mono" style={{ fontSize: 12 }}>{h.status ?? "×"} {h.url}</div>
                    ))
                  : null}
              </Row>
              <Row k="Yoxlanılıb">{f.enriched_at ? dateTime(f.enriched_at) : f.source === "organic_domain" ? "gözləyir" : null}</Row>
            </dl>
          </div>

          <div className="section">
            <h2>Tarixçə</h2>
            <table className="t">
              <tbody>
                {f.events.map((e, i) => (
                  <tr key={i}>
                    <td className="num" style={{ width: 140 }}>{dateTime(e.at)}</td>
                    <td>{e.kind}</td>
                    <td className="muted mono trunc" style={{ maxWidth: 200 }}>{e.actor}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <details className="section">
            <summary className="muted">Xam məlumat (JSON)</summary>
            <pre className="json">{JSON.stringify(f.raw, null, 2)}</pre>
          </details>
        </section>
      </div>
    </>
  );
}
