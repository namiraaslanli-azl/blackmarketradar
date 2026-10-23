"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { NAV } from "@/lib/labels";

// Keyboard: "g" then a letter jumps to a section; "/" focuses the page search.
export default function Nav() {
  const path = usePathname();
  const router = useRouter();
  const sp = useSearchParams();
  const range = ["from", "to"].filter((k) => sp.get(k)).map((k) => `${k}=${sp.get(k)}`).join("&");
  const withRange = (href: string) => (range ? `${href}?${range}` : href);

  useEffect(() => {
    let pendingG = false;
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el.closest("input, textarea, select, [contenteditable]") || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "/") {
        const search = document.querySelector<HTMLInputElement>("input[type=search]");
        if (search) {
          e.preventDefault();
          search.focus();
        }
        return;
      }
      if (pendingG) {
        pendingG = false;
        const target = NAV.find((n) => n.key === e.key);
        if (target) router.push(withRange(target.href));
        return;
      }
      if (e.key === "g") {
        pendingG = true;
        setTimeout(() => (pendingG = false), 800);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const toggleTheme = () => {
    const root = document.documentElement;
    const dark = root.dataset.theme
      ? root.dataset.theme === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try {
      localStorage.setItem("theme", root.dataset.theme);
    } catch {}
  };

  return (
    <nav className="nav" aria-label="Bölmələr">
      <div className="brand">
        <div className="brand-name">Black Market Radar</div>
        <div className="brand-sub">Azerlotereya · daxili</div>
      </div>
      <div className="nav-links">
        {NAV.map((n) => {
          const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
          return (
            <Link key={n.href} href={withRange(n.href)} aria-current={active ? "page" : undefined}>
              <span>{n.label}</span>
              <kbd>g {n.key}</kbd>
            </Link>
          );
        })}
      </div>
      <div className="nav-foot">
        <button type="button" onClick={toggleTheme}>Açıq / tünd</button>
      </div>
    </nav>
  );
}
