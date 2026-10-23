import { api } from "@/lib/api";
import { addKeyword, addWhitelist, deleteKeyword, deleteWhitelist } from "./actions";

interface Kw { id: number; term: string; kind: string; lang: string | null; active: boolean }
interface Wl { id: number; kind: string; value: string; owner: string; note: string | null }

const KIND_LABEL: Record<string, string> = {
  generic: "Ümumi", brand: "Brend", promo: "Promo / bonus", game: "Oyun", payment: "Ödəniş",
};

export default async function SettingsPage() {
  const [kws, wl] = await Promise.all([api<Kw[]>("/api/settings/keywords"), api<Wl[]>("/api/settings/whitelist")]);
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
    </>
  );
}
