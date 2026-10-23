import { api } from "@/lib/api";
import { dateTime } from "@/lib/labels";
import { addKeyword, addTarget, addWhitelist, deleteKeyword, deleteTarget, deleteWhitelist } from "./actions";

interface Kw { id: number; term: string; kind: string; lang: string | null; active: boolean }
interface Wl { id: number; kind: string; value: string; owner: string; note: string | null }
interface Target { id: number; kind: string; value: string; note: string | null; last_collected_at: string | null }

const TARGET_LABEL: Record<string, string> = {
  meta_page: "Meta reklamçı səhifəsi (ID)", tiktok_account: "TikTok hesabı", instagram_account: "Instagram hesabı",
  facebook_page: "Facebook səhifəsi", telegram_channel: "Telegram kanalı", hashtag: "Hashtag",
};

const KIND_LABEL: Record<string, string> = {
  generic: "Ümumi", brand: "Brend", promo: "Promo / bonus", game: "Oyun", payment: "Ödəniş",
};

export default async function SettingsPage() {
  const [kws, wl, targets] = await Promise.all([
    api<Kw[]>("/api/settings/keywords"),
    api<Wl[]>("/api/settings/whitelist"),
    api<Target[]>("/api/settings/targets"),
  ]);
  const grouped = Object.entries(
    kws.reduce<Record<string, Kw[]>>((acc, k) => ((acc[k.kind] ??= []).push(k), acc), {}),
  );

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Ayarlar</h1>
          <p>Bütün kollektorlar və qaydalar bu siyahılardan oxuyur</p>
        </div>
      </div>

      <div className="cols">
        <section>
          <h2>Açar sözlər · {kws.length}</h2>
          <form action={addKeyword} className="filters">
            <input className="field" name="term" placeholder="yeni açar söz" required minLength={2} style={{ flex: 1 }} />
            <select name="kind" className="field" defaultValue="generic">
              {Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <select name="lang" className="field" defaultValue="az">
              {["az", "ru", "tr", "en", ""].map((l) => <option key={l} value={l}>{l || "—"}</option>)}
            </select>
            <button className="btn" type="submit">Əlavə et</button>
          </form>
          {grouped.map(([kind, items]) => (
            <div key={kind} style={{ padding: "10px 0", borderBottom: "1px solid var(--rule)" }}>
              <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>{KIND_LABEL[kind] ?? kind} · {items.length}</div>
              {items.map((k) => (
                <form key={k.id} action={deleteKeyword} style={{ display: "inline" }}>
                  <input type="hidden" name="id" value={k.id} />
                  <span className="chip" style={{ color: "var(--ink-2)" }}>
                    {k.term}
                    <button className="btn link" type="submit" aria-label={`${k.term} sil`} style={{ marginLeft: 6, textDecoration: "none" }}>×</button>
                  </span>
                </form>
              ))}
            </div>
          ))}
        </section>

        <section>
          <h2>Lisenziyalı ağ siyahı</h2>
          <p className="muted" style={{ marginTop: 0 }}>
            Bu siyahıda olmayan hər hansı qumar / mərc reklamı qanunsuz sayılır.
          </p>
          <form action={addWhitelist} className="filters">
            <select name="kind" className="field" defaultValue="domain">
              <option value="domain">Domen</option>
              <option value="handle">Hesab / kanal</option>
              <option value="app">Tətbiq paketi</option>
              <option value="brand">Brend adı</option>
            </select>
            <input className="field" name="value" placeholder="misal: misli.az" required minLength={2} style={{ flex: 1 }} />
            <select name="owner" className="field" defaultValue="Azerlotereya">
              <option>Azerlotereya</option>
              <option>Topaz</option>
              <option>TFC</option>
            </select>
            <button className="btn" type="submit">Əlavə et</button>
          </form>
          <table className="t">
            <thead>
              <tr><th>Sahib</th><th>Növ</th><th>Dəyər</th><th /></tr>
            </thead>
            <tbody>
              {wl.map((w) => (
                <tr key={w.id}>
                  <td>{w.owner}</td>
                  <td className="muted">{w.kind}</td>
                  <td className="mono">{w.value}</td>
                  <td style={{ textAlign: "right" }}>
                    <form action={deleteWhitelist}>
                      <input type="hidden" name="id" value={w.id} />
                      <button className="btn link" type="submit">sil</button>
                    </form>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>

      <section className="section">
        <h2>İzlənilən hesablar · {targets.length}</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          Kollektorlar bu hesabları hər dəfə yoxlayır. Təsdiqlənmiş hesablar avtomatik izlənir; bura əlavə olaraq
          bildiyiniz hesabları yazın. Link və ya @ad yazmaq olar.
        </p>
        <form action={addTarget} className="filters">
          <select name="kind" className="field" defaultValue="tiktok_account">
            {Object.entries(TARGET_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <input className="field" name="value" placeholder="misal: https://www.tiktok.com/@kod_satisi" required minLength={2} style={{ flex: 1 }} />
          <input className="field" name="note" placeholder="qeyd (istəyə bağlı)" />
          <button className="btn" type="submit">Əlavə et</button>
        </form>
        <div className="table-wrap">
          <table className="t">
            <thead>
              <tr><th>Növ</th><th>Hesab</th><th className="hide-sm">Qeyd</th><th>Son yoxlama</th><th /></tr>
            </thead>
            <tbody>
              {targets.map((t) => (
                <tr key={t.id}>
                  <td className="muted">{TARGET_LABEL[t.kind] ?? t.kind}</td>
                  <td className="mono">{t.value}</td>
                  <td className="muted hide-sm">{t.note}</td>
                  <td>{t.last_collected_at ? dateTime(t.last_collected_at) : <span className="faint">hələ yox</span>}</td>
                  <td style={{ textAlign: "right" }}>
                    <form action={deleteTarget}>
                      <input type="hidden" name="id" value={t.id} />
                      <button className="btn link" type="submit">sil</button>
                    </form>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
