import path from "node:path";
import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

// Monorepo kökündeki ortak .env dosyasını yükle (NEXT_PUBLIC_* değişkenleri).
loadEnvConfig(path.resolve(__dirname, "../.."));

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Üretim Docker imajı için: yalnızca gereken dosyalarla tek başına çalışan sunucu
  output: "standalone",
  outputFileTracingRoot: path.resolve(__dirname, "../.."),
};

export default nextConfig;
