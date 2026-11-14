import type { Metadata } from "next";
import "maplibre-gl/dist/maplibre-gl.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "AstraForce",
  description: "Harmonized MODIS + VIIRS burning activity calendar",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // Tarayıcı eklentileri <html>'e özellik ekleyebiliyor (ör. crxlauncher); bu fark
    // hydration uyarısı vermesin. Yalnızca bu etiketin kendi özelliklerini etkiler.
    <html lang={process.env.NEXT_PUBLIC_DEFAULT_LOCALE ?? "en"} suppressHydrationWarning>
      <body className="antialiased">{children}</body>
    </html>
  );
}
