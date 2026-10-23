// Azerbaijani UI vocabulary in one place.
export const SOURCE_LABEL: Record<string, string> = {
  organic_domain: "Domen",
  meta_ad: "Meta reklamı",
  tiktok_post: "TikTok post",
  tiktok_account: "TikTok hesab",
  instagram_post: "Instagram post",
  instagram_account: "Instagram hesab",
  facebook_post: "Facebook post",
  facebook_page: "Facebook səhifə",
  telegram_channel: "Telegram kanal",
  telegram_post: "Telegram post",
  play_store_app: "Play Store",
  app_store_app: "App Store",
};

export const STATUS_LABEL: Record<string, string> = {
  new: "Yeni",
  confirmed: "Təsdiqlənib",
  false_positive: "Yanlış",
  reported: "Şikayət olunub",
  blocked: "Bloklanıb",
};

export const NAV = [
  { href: "/", label: "Ümumi baxış", key: "o" },
  { href: "/tapintilar", label: "Tapıntılar", key: "t" },
  { href: "/data-keyfiyyeti", label: "Data keyfiyyəti", key: "d" },
  { href: "/kollektorlar", label: "Kollektorlar", key: "k" },
  { href: "/ayarlar", label: "Ayarlar", key: "a" },
];

const nf = new Intl.NumberFormat("az-AZ");
export const num = (n: number | null | undefined) => (n === null || n === undefined ? "—" : nf.format(n));

export function compact(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (n >= 10_000) return `${Math.round(n / 1000)}k`;
  return nf.format(n);
}

export function day(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("az-AZ", { timeZone: "Asia/Baku", day: "2-digit", month: "2-digit", year: "numeric" });
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("az-AZ", {
    timeZone: "Asia/Baku", day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}
