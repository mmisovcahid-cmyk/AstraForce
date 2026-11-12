// MapLibre GL v6 haritayı bir Web Worker içinde işler. Next.js (Turbopack) bu worker
// dosyasını paketleyemediği için onu public/ klasörüne kopyalayıp
// setWorkerUrl("/maplibre/maplibre-gl-worker.mjs") ile gösteriyoruz.
// predev/prebuild ile otomatik çalışır; böylece kopya her zaman kurulu sürümle aynıdır.
import { copyFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const dist = dirname(require.resolve("maplibre-gl/dist/maplibre-gl.css"));
const out = join(dirname(fileURLToPath(import.meta.url)), "..", "public", "maplibre");

mkdirSync(out, { recursive: true });
for (const f of ["maplibre-gl-worker.mjs", "maplibre-gl-worker.mjs.map"]) {
  copyFileSync(join(dist, f), join(out, f));
}
