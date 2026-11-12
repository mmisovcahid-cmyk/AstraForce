import type { Metadata } from "next";
import "maplibre-gl/dist/maplibre-gl.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "AstraForce",
  description: "Harmonized MODIS + VIIRS burning activity calendar",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang={process.env.NEXT_PUBLIC_DEFAULT_LOCALE ?? "en"}>
      <body className="antialiased">{children}</body>
    </html>
  );
}
