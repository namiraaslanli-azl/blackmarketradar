import type { Metadata, Viewport } from "next";
import { Suspense } from "react";
import Nav from "@/components/Nav";
import RangePicker from "@/components/RangePicker";
import "./globals.css";

export const metadata: Metadata = {
  title: "Black Market Radar",
  description: "Qanunsuz qumar reklamının monitorinqi — Azerlotereya daxili alət",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

// Applies a saved theme before paint so there is no flash.
const themeScript = `try{var t=localStorage.getItem("theme");if(t)document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="az" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>
        <div className="shell">
          <Suspense>
            <Nav />
          </Suspense>
          <div className="main">
            <header className="topbar">
              <Suspense>
                <RangePicker />
              </Suspense>
              <span className="muted hide-sm" style={{ fontSize: 12 }}>
                Vaxt zonası: Bakı (UTC+4)
              </span>
            </header>
            <main className="page">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
