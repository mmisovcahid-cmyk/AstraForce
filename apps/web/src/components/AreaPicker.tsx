"use client";

import { useState } from "react";
import { createRoi, type RoiInfo } from "@/lib/api";
import type { MessageKey } from "@/lib/i18n";
import { type AreaCode, isRoi, REGIONS } from "@/lib/regions";

type T = (k: MessageKey) => string;
type Tab = "coords" | "geojson";

/**
 * Alan seçimi: hazır ülkeler + kullanıcı bölgesi (koordinat/yarıçap, GeoJSON yükleme,
 * haritada çizim). Yeni bölge oluşturulunca onChange("roi:<id>") çağrılır.
 */
export function AreaPicker({
  area,
  roi,
  onChange,
  t,
}: {
  area: AreaCode;
  roi: RoiInfo | null;
  onChange: (a: AreaCode) => void;
  t: T;
}) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("coords");
  const [lat, setLat] = useState("36.78");
  const [lon, setLon] = useState("31.44");
  const [radius, setRadius] = useState("30");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (body: Parameters<typeof createRoi>[0]) => {
    setBusy(true);
    setError(null);
    try {
      const info = await createRoi(body);
      setOpen(false);
      onChange(info.area);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const onCoords = (e: React.FormEvent) => {
    e.preventDefault();
    const la = Number(lat.replace(",", "."));
    const lo = Number(lon.replace(",", "."));
    const r = Number(radius.replace(",", "."));
    if (![la, lo, r].every(Number.isFinite)) {
      setError("lat / lon / radius?");
      return;
    }
    void submit({ circle: { lat: la, lon: lo, radius_km: r } });
  };

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) {
      setError("> 10 MB");
      return;
    }
    try {
      const json = JSON.parse(await file.text());
      void submit({ geojson: json, name: file.name.replace(/\.(geo)?json$/i, "") });
    } catch {
      setError("GeoJSON?");
    }
  };

  const btn = (active: boolean) =>
    `rounded-md px-3 py-1.5 text-sm ${
      active ? "bg-fire-600 text-white" : "bg-white/5 text-gray-300 hover:bg-white/10"
    }`;

  return (
    <div className="relative flex flex-wrap items-center gap-1" role="group" aria-label={t("area")}>
      {REGIONS.map((r) => (
        <button
          key={r.id}
          type="button"
          onClick={() => onChange(r.id)}
          aria-pressed={area === r.id}
          className={btn(area === r.id)}
        >
          {t(`region.${r.id}`)}
        </button>
      ))}
      {isRoi(area) && (
        <span className={btn(true)} title={roi ? `${roi.area_km2.toLocaleString()} km²` : undefined}>
          {roi?.name || t("roiLabel")}
          {roi && <span className="ml-1 text-xs opacity-80">· {Math.round(roi.area_km2).toLocaleString()} km²</span>}
        </span>
      )}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="rounded-md border border-dashed border-white/30 px-3 py-1.5 text-sm text-gray-300 hover:bg-white/5"
      >
        + {t("newArea")}
      </button>

      {open && (
        <div className="absolute left-0 top-full z-20 mt-2 w-80 rounded-lg border border-white/10 bg-gray-950 p-3 text-xs shadow-xl">
          <div className="mb-3 flex gap-1">
            {(["coords", "geojson"] as const).map((k) => (
              <button
                key={k}
                type="button"
                onClick={() => setTab(k)}
                aria-pressed={tab === k}
                className={`flex-1 rounded px-2 py-1 ${tab === k ? "bg-white/20" : "bg-white/5 text-gray-400"}`}
              >
                {t(k === "coords" ? "coordinates" : "uploadGeojson")}
              </button>
            ))}
            <a
              href="/map?draw=1"
              className="flex-1 rounded bg-white/5 px-2 py-1 text-center text-gray-400 hover:bg-white/10"
            >
              {t("drawOnMap")}
            </a>
          </div>

          {tab === "coords" ? (
            <form onSubmit={onCoords} className="space-y-2">
              <div className="grid grid-cols-3 gap-2">
                {(
                  [
                    ["latitude", lat, setLat],
                    ["longitude", lon, setLon],
                    ["radiusKm", radius, setRadius],
                  ] as const
                ).map(([key, value, set]) => (
                  <label key={key} className="flex flex-col gap-1">
                    <span className="text-gray-400">{t(key)}</span>
                    <input
                      inputMode="decimal"
                      value={value}
                      onChange={(e) => set(e.target.value)}
                      className="w-full rounded bg-white/10 px-2 py-1"
                    />
                  </label>
                ))}
              </div>
              <button
                type="submit"
                disabled={busy}
                className="w-full rounded bg-fire-600 px-2 py-1.5 font-medium text-white disabled:opacity-50"
              >
                {busy ? "…" : t("analyze")}
              </button>
            </form>
          ) : (
            <label className="block cursor-pointer rounded border border-dashed border-white/30 p-4 text-center text-gray-300 hover:bg-white/5">
              {busy ? "…" : t("uploadGeojson")} (.geojson, .json)
              <input
                type="file"
                accept=".geojson,.json,application/geo+json,application/json"
                className="hidden"
                onChange={(e) => void onFile(e.target.files?.[0])}
              />
            </label>
          )}
          {error && <p className="mt-2 text-red-400">{error}</p>}
        </div>
      )}
    </div>
  );
}
