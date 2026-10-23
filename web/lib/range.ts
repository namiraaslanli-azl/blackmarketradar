// Global date range lives in the URL (?from=YYYY-MM-DD&to=YYYY-MM-DD), Baku time.
export type RangeKey = "today" | "yesterday" | "7d" | "30d" | "custom";

export function bakuToday(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Baku" }).format(new Date());
}

function shift(isoDay: string, days: number): string {
  const d = new Date(`${isoDay}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export function presetRange(key: Exclude<RangeKey, "custom">): { from: string; to: string } {
  const t = bakuToday();
  switch (key) {
    case "today":
      return { from: t, to: t };
    case "yesterday":
      return { from: shift(t, -1), to: shift(t, -1) };
    case "7d":
      return { from: shift(t, -6), to: t };
    case "30d":
      return { from: shift(t, -29), to: t };
  }
}

export function resolveRange(sp: { from?: string; to?: string }): { from: string; to: string; key: RangeKey } {
  if (!sp.from && !sp.to) return { ...presetRange("30d"), key: "30d" };
  const from = sp.from ?? sp.to!;
  const to = sp.to ?? sp.from!;
  for (const k of ["today", "yesterday", "7d", "30d"] as const) {
    const p = presetRange(k);
    if (p.from === from && p.to === to) return { from, to, key: k };
  }
  return { from, to, key: "custom" };
}

export const RANGE_LABEL: Record<RangeKey, string> = {
  today: "Bu gün",
  yesterday: "Dünən",
  "7d": "Son 7 gün",
  "30d": "Son 30 gün",
  custom: "Seçilmiş",
};
