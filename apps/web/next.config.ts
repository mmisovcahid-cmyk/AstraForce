import path from "node:path";
import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

// Monorepo kökündeki ortak .env dosyasını yükle (NEXT_PUBLIC_* değişkenleri).
loadEnvConfig(path.resolve(__dirname, "../.."));

// Üretimde (Render) tarayıcı API'yi aynı alan adından çağırır: /api/* → API'nin iç ağ adresi.
// Böylece API'nin genel adresine ve CORS'a gerek kalmaz. Derleme sırasında okunur.
const apiInternalUrl = process.env.API_INTERNAL_URL;

// Geliştirmede sayfanın localhost dışında (ör. 192.168.56.1) açılabilmesi için: API'nin
// CORS_ORIGINS listesindeki ana makine adları Next dev kaynaklarına (HMR) da izinli olur.
const allowedDevOrigins = (process.env.CORS_ORIGINS ?? "")
  .split(",")
  .map((o) => o.trim())
  .filter(Boolean)
  .map((o) => {
    try {
      return new URL(o).hostname;
    } catch {
      return o;
    }
  });

const nextConfig: NextConfig = {
  reactStrictMode: true,
  allowedDevOrigins,
  // Üretim Docker imajı için: yalnızca gereken dosyalarla tek başına çalışan sunucu
  output: "standalone",
  outputFileTracingRoot: path.resolve(__dirname, "../.."),
  async rewrites() {
    return apiInternalUrl
      ? [{ source: "/api/:path*", destination: `${apiInternalUrl.replace(/\/$/, "")}/:path*` }]
      : [];
  },
};

export default nextConfig;
