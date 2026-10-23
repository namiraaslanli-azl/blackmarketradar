"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { presetRange, RANGE_LABEL, resolveRange } from "@/lib/range";

export default function RangePicker() {
  const sp = useSearchParams();
  const path = usePathname();
  const router = useRouter();
  const current = resolveRange({ from: sp.get("from") ?? undefined, to: sp.get("to") ?? undefined });

  const href = (from: string, to: string) => {
    const next = new URLSearchParams(sp.toString());
    next.set("from", from);
    next.set("to", to);
    next.delete("page");
    return `${path}?${next.toString()}`;
  };

  return (
    <div className="range" role="group" aria-label="Tarix aralığı">
      {(["today", "yesterday", "7d", "30d"] as const).map((k) => {
        const r = presetRange(k);
        return (
          <Link key={k} href={href(r.from, r.to)} aria-current={current.key === k ? "true" : undefined}>
            {RANGE_LABEL[k]}
          </Link>
        );
      })}
      <span className="sep">|</span>
      <input
        type="date"
        aria-label="Başlanğıc"
        value={current.from}
        max={current.to}
        onChange={(e) => e.target.value && router.push(href(e.target.value, current.to))}
      />
      <span className="faint">–</span>
      <input
        type="date"
        aria-label="Son"
        value={current.to}
        min={current.from}
        onChange={(e) => e.target.value && router.push(href(current.from, e.target.value))}
      />
    </div>
  );
}
