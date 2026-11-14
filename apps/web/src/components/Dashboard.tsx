"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import {
  type CellCollection,
  createRoi,
  type Detections,
  fetchBurnedArea,
  fetchBurnedAreaSummary,
  fetchCells,
  fetchEmergencyAlerts,
  fetchEmergencySummary,
  fetchRoi,
  fetchStaticSources,
  type RoiInfo,
  fetchDetections,
  fetchHealth,
  type Health,
} from "@/lib/api";
import { addDays, RANGE_OPTIONS, type RangeDays, rangeEndingOn, todayUtc } from "@/lib/dates";
import type { MessageKey } from "@/lib/i18n";
import { type Bbox, isRegionId, parseAreaCode, REGIONS, type RegionId, roiId } from "@/lib/regions";
import { readParams, writeParams } from "@/lib/url";
import { useLocale } from "@/lib/useLocale";
import { AppHeader } from "./AppHeader";
import { PlaceSearch } from "./PlaceSearch";
import { SOURCE_COLORS } from "./mapColors";

// MapLibre tarayıcı API'lerine ihtiyaç duyar: sunucuda render edilmez.
const FireMap = dynamic(() => import("./FireMap").then((m) => m.FireMap), { ssr: false });

type DetectionState =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "ready"; data: Detections };

export type MapLayer = "points" | "density";

type ApiState = { kind: "checking" } | { kind: "down" } | { kind: "up"; health: Health };

export function Dashboard() {
  const { locale, setLocale, t } = useLocale();
  const [regionId, setRegionId] = useState<RegionId>("AZ");
  const [api, setApi] = useState<ApiState>({ kind: "checking" });
  // Varsayılan: dün (UTC) ile biten 7 gün; bugünün NRT verisi henüz eksik olabilir.
  const [endDate, setEndDate] = useState(() => addDays(todayUtc(), -1));
  const [rangeDays, setRangeDays] = useState<RangeDays>(7);
  const [det, setDet] = useState<DetectionState>({ kind: "loading" });
  const [layer, setLayer] = useState<MapLayer>("points");
  const [cells, setCells] = useState<CellCollection | null>(null);
  const [ready, setReady] = useState(false);
  const [roi, setRoi] = useState<RoiInfo | null>(null);
  const [drawing, setDrawing] = useState(false);
  const [drawState, setDrawState] = useState<string | null>(null);
  const [focus, setFocus] = useState<Bbox | null>(null);
  const [landCoverYear, setLandCoverYear] = useState<number | null>(null);
  const [staticSources, setStaticSources] = useState<GeoJSON.FeatureCollection | null>(null);
  const [showStaticSources, setShowStaticSources] = useState(false);
  const [burnedAreas, setBurnedAreas] = useState<GeoJSON.FeatureCollection | null>(null);
  const [showBurnedAreas, setShowBurnedAreas] = useState(false);
  const [burnedAreaSummary, setBurnedAreaSummary] = useState<{ total_ha: number; cells: number } | null>(null);
  const [emergencyAlerts, setEmergencyAlerts] = useState<GeoJSON.FeatureCollection | null>(null);
  const [showEmergencyAlerts, setShowEmergencyAlerts] = useState(false);
  // Telefonda panel haritayı kaplamasın: varsayılan kapalı (çizim modunda açık)
  const [panelOpen, setPanelOpen] = useState(true);
  useEffect(() => {
    if (window.innerWidth < 640 && !new URLSearchParams(window.location.search).get("draw")) {
      setPanelOpen(false);
    }
  }, []);

  const onPolygon = async (geometry: GeoJSON.Polygon) => {
    setDrawState(t("loading"));
    try {
      const info = await createRoi({ geojson: geometry });
      window.location.href = `/?area=${info.area}`;
    } catch (e) {
      setDrawState(e instanceof Error ? e.message : String(e));
      setDrawing(false);
    }
  };

  // Takvimden gelen bağlantı: /map?region=TR&date=2021-07-29&range=1
  useEffect(() => {
    const p = readParams();
    const r = p.get("region");
    if (r && isRegionId(r)) setRegionId(r);
    // Kullanıcı bölgesi: sınırını göster, noktalar için ilk ülkesini kullan
    const id = roiId(parseAreaCode(p.get("area")) ?? "AZ");
    if (id) {
      fetchRoi(id)
        .then((info) => {
          setRoi(info);
          const c = info.countries.find(isRegionId);
          if (c) setRegionId(c);
        })
        .catch(() => setRoi(null));
    }
    if (p.get("draw") === "1") setDrawing(true);
    const d = p.get("date");
    if (d && /^\d{4}-\d{2}-\d{2}$/.test(d)) setEndDate(d);
    const rg = Number(p.get("range"));
    if ((RANGE_OPTIONS as readonly number[]).includes(rg)) setRangeDays(rg as RangeDays);
    if (p.get("layer") === "density") setLayer("density");
    setReady(true);
  }, []);

  useEffect(() => {
    if (!ready) return;
    writeParams({
      region: regionId,
      area: roi?.area ?? null,
      date: endDate,
      range: rangeDays,
      layer: layer === "density" ? layer : null,
      draw: null,
    });
  }, [ready, regionId, roi, endDate, rangeDays, layer]);

  // API henüz ayağa kalkmadıysa (ör. `pnpm dev` yeni başladı) bekle; ayağa kalkınca tekrar dene.
  const apiUp = api.kind === "up";
  useEffect(() => {
    if (!apiUp || !ready) return;
    const ctrl = new AbortController();
    setDet({ kind: "loading" });
    fetchDetections({ country: regionId, ...rangeEndingOn(endDate, rangeDays) }, ctrl.signal)
      .then((data) => setDet({ kind: "ready", data }))
      .catch(() => {
        if (!ctrl.signal.aborted) setDet({ kind: "error" });
      });
    return () => ctrl.abort();
  }, [apiUp, ready, regionId, endDate, rangeDays]);

  useEffect(() => {
    if (!apiUp || !ready || layer !== "density") return;
    const ctrl = new AbortController();
    setCells(null);
    fetchCells({ area: roi?.area ?? regionId, ...rangeEndingOn(endDate, rangeDays) }, ctrl.signal)
      .then(setCells)
      .catch(() => !ctrl.signal.aborted && setCells(null));
    return () => ctrl.abort();
  }, [apiUp, ready, layer, regionId, roi, endDate, rangeDays]);

  useEffect(() => {
    if (!apiUp || !ready) return;
    const ctrl = new AbortController();
    fetchStaticSources({ country: regionId }, ctrl.signal)
      .then((data) => setStaticSources(data))
      .catch(() => !ctrl.signal.aborted && setStaticSources(null));
    return () => ctrl.abort();
  }, [apiUp, ready, regionId]);

  useEffect(() => {
    if (!apiUp || !ready) return;
    const ctrl = new AbortController();
    const { dateFrom, dateTo } = rangeEndingOn(endDate, rangeDays);
    Promise.all([
      fetchBurnedArea(
        { area: roi?.area ?? regionId, dateFrom, dateTo },
        ctrl.signal,
      ).then((data) => setBurnedAreas(data)),
      fetchBurnedAreaSummary(
        { area: roi?.area ?? regionId, dateFrom, dateTo },
        ctrl.signal,
      ).then((data) => {
        const total = data.sensors.reduce((acc, s) => acc + s.total_ha, 0);
        const cells = data.sensors.reduce((acc, s) => acc + s.cells, 0);
        setBurnedAreaSummary({ total_ha: total, cells });
      }),
    ]).catch(() => !ctrl.signal.aborted && (setBurnedAreas(null), setBurnedAreaSummary(null)));
    return () => ctrl.abort();
  }, [apiUp, ready, regionId, roi, endDate, rangeDays]);

  useEffect(() => {
    if (!apiUp || !ready) return;
    const ctrl = new AbortController();
    const { dateFrom, dateTo } = rangeEndingOn(endDate, rangeDays);
    fetchEmergencyAlerts(
      { area: roi?.area ?? regionId, dateFrom, dateTo },
      ctrl.signal,
    ).then((data) => setEmergencyAlerts(data)).catch(() => !ctrl.signal.aborted && setEmergencyAlerts(null));
    return () => ctrl.abort();
  }, [apiUp, ready, regionId, roi, endDate, rangeDays]);

  useEffect(() => {
    const ctrl = new AbortController();
    const check = () =>
      fetchHealth(ctrl.signal)
        .then((health) => setApi({ kind: "up", health }))
        .catch(() => {
          if (!ctrl.signal.aborted) setApi({ kind: "down" });
        });
    check();
    const id = setInterval(check, 15000);
    return () => {
      ctrl.abort();
      clearInterval(id);
    };
  }, []);

  const region = REGIONS.find((r) => r.id === regionId) ?? REGIONS[0];
  const bbox: Bbox = focus ?? (roi ? roi.bbox : region.bbox);

  return (
    <div className="flex h-screen flex-col">
      <AppHeader active="/map" t={t} locale={locale} setLocale={setLocale}>
        <select
          value={roi ? "" : regionId}
          aria-label={t("country")}
          onChange={(e) => {
            if (!isRegionId(e.target.value)) return;
            setRoi(null);
            setFocus(null);
            setRegionId(e.target.value);
          }}
          className="rounded-md bg-fire-600 px-3 py-1.5 text-sm text-white"
        >
          {roi && <option value="">{t("roiLabel")}</option>}
          {REGIONS.map((r) => (
            <option key={r.id} value={r.id} className="bg-gray-900">
              {t(`region.${r.id}`)}
            </option>
          ))}
        </select>
        <StatusPills api={api} t={t} />
      </AppHeader>

      <main className="relative flex-1">
        <FireMap
          bbox={bbox}
          roiGeometry={roi?.geometry ?? null}
          drawing={drawing}
          onPolygon={onPolygon}
          landCoverYear={landCoverYear}
          staticSources={staticSources}
          showStaticSources={showStaticSources}
          burnedAreas={burnedAreas}
          showBurnedAreas={showBurnedAreas}
          emergencyAlerts={emergencyAlerts}
          showEmergencyAlerts={showEmergencyAlerts}
          detections={layer === "points" && det.kind === "ready" ? det.data : null}
          cells={layer === "density" ? cells : null}
        />

        <button
          type="button"
          onClick={() => setPanelOpen((o) => !o)}
          aria-expanded={panelOpen}
          aria-controls="map-panel"
          className="absolute left-3 top-3 z-10 rounded-md bg-gray-950/90 px-3 py-1.5 text-xs shadow-lg"
        >
          {panelOpen ? "✕" : `☰ ${t("layer")}`}
        </button>
        <section
          id="map-panel"
          hidden={!panelOpen}
          className="absolute left-3 top-12 max-h-[calc(100%-4rem)] w-72 max-w-[calc(100%-1.5rem)] space-y-3 overflow-y-auto rounded-lg bg-gray-950/85 p-3 text-xs shadow-lg backdrop-blur"
        >
          <PlaceSearch
            placeholder={t("searchPlace")}
            noResult={t("searchNoResult")}
            onSelect={(p) => {
              const d = 0.25;
              setFocus(p.bbox ?? [p.lon - d, p.lat - d, p.lon + d, p.lat + d]);
            }}
          />
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={landCoverYear !== null}
              onChange={(e) => setLandCoverYear(e.target.checked ? 2024 : null)}
            />
            <span className="flex-1">{t("landCover")}</span>
            {landCoverYear !== null && (
              <select
                value={landCoverYear}
                aria-label={t("landCoverYear")}
                onChange={(e) => setLandCoverYear(Number(e.target.value))}
                className="rounded bg-white/10 px-1 py-0.5"
              >
                {Array.from({ length: 24 }, (_, i) => 2024 - i).map((y) => (
                  <option key={y} value={y} className="bg-gray-900">
                    {y}
                  </option>
                ))}
              </select>
            )}
          </label>
          {landCoverYear !== null && <LandCoverLegend />}
          <label className="flex items-center gap-2 mt-2">
            <input
              type="checkbox"
              checked={showStaticSources}
              onChange={(e) => setShowStaticSources(e.target.checked)}
            />
            <span className="flex-1">{t("showStaticSources")}</span>
          </label>
          {showStaticSources && (
            <p className="text-gray-400 text-[11px] mt-1">
              {t("staticSources")} · {staticSources?.features.length ?? 0} hücre
            </p>
          )}
          <label className="flex items-center gap-2 mt-2">
            <input
              type="checkbox"
              checked={showBurnedAreas}
              onChange={(e) => setShowBurnedAreas(e.target.checked)}
            />
            <span className="flex-1">{t("showBurnedAreas")}</span>
          </label>
          {showBurnedAreas && burnedAreaSummary && (
            <p className="text-gray-400 text-[11px] mt-1">
              {t("burnedAreas")} · {burnedAreaSummary.cells} hücre · {burnedAreaSummary.total_ha.toLocaleString(undefined, { maximumFractionDigits: 1 })} ha
            </p>
          )}
          <label className="flex items-center gap-2 mt-2">
            <input
              type="checkbox"
              checked={showEmergencyAlerts}
              onChange={(e) => setShowEmergencyAlerts(e.target.checked)}
            />
            <span className="flex-1">{t("showEmergencyAlerts")}</span>
          </label>
          {showEmergencyAlerts && (
            <p className="text-gray-400 text-[11px] mt-1">
              {t("emergencyAlerts")} · {emergencyAlerts?.features.length ?? 0} uyarı
            </p>
          )}
          <button
            type="button"
            onClick={() => {
              setDrawState(null);
              setDrawing((d) => !d);
            }}
            aria-pressed={drawing}
            className={`w-full rounded px-2 py-1.5 font-medium ${
              drawing ? "bg-fire-600 text-white" : "bg-white/10 hover:bg-white/20"
            }`}
          >
            {drawing ? t("cancel") : `✎ ${t("drawOnMap")}`}
          </button>
          {drawing && <p className="text-gray-300">{t("drawHint")}</p>}
          {drawState && <p className="text-amber-300">{drawState}</p>}
          {roi && (
            <p className="text-gray-300">
              {roi.name || t("roiLabel")} · {Math.round(roi.area_km2).toLocaleString(locale)} km² ·{" "}
              <a className="underline" href={`/?area=${roi.area}`}>
                {t("nav.calendar")} →
              </a>
            </p>
          )}
          <div className="flex gap-1" role="group" aria-label={t("layer")}>
            {(["points", "density"] as const).map((l) => (
              <button
                key={l}
                type="button"
                aria-pressed={l === layer}
                onClick={() => setLayer(l)}
                className={`flex-1 rounded px-2 py-1 ${
                  l === layer ? "bg-white/20 text-white" : "bg-white/5 text-gray-400 hover:bg-white/10"
                }`}
              >
                {t(`layer.${l}`)}
              </button>
            ))}
          </div>
          {layer === "density" && (
            <p className="text-gray-400">
              {cells
                ? `${t("densityCells").replace("{n}", cells.meta.cells.toLocaleString(locale))} · HFI ${cells.meta.total.toLocaleString(locale)}`
                : t("loading")}
            </p>
          )}
          <div className="flex gap-2">
            <label className="flex flex-1 flex-col gap-1">
              <span className="text-gray-400">{t("endDate")}</span>
              <input
                type="date"
                value={endDate}
                max={todayUtc()}
                min="2000-11-01"
                onChange={(e) => e.target.value && setEndDate(e.target.value)}
                className="rounded bg-white/10 px-2 py-1 [color-scheme:dark]"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-gray-400">{t("range")}</span>
              <select
                value={rangeDays}
                onChange={(e) => setRangeDays(Number(e.target.value) as RangeDays)}
                className="rounded bg-white/10 px-2 py-1"
              >
                {RANGE_OPTIONS.map((d) => (
                  <option key={d} value={d} className="bg-gray-900">
                    {d} {t("days")}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div hidden={layer !== "points"}>
            <div className="mb-1 flex items-baseline justify-between">
              <span className="font-medium text-gray-200">{t("detections")}</span>
              {det.kind === "ready" && (
                <span className="tabular-nums text-gray-300">
                  {det.data.meta.total.toLocaleString(locale)}
                </span>
              )}
            </div>
            {det.kind === "loading" && <p className="text-gray-400">{t("loading")}</p>}
            {det.kind === "error" && <p className="text-red-400">{t("loadError")}</p>}
            {det.kind === "ready" && det.data.meta.total === 0 && (
              <p className="text-gray-400">{t("noData")}</p>
            )}
            <ul className="space-y-1">
              {Object.entries(SOURCE_COLORS).map(([source, color]) => (
                <li key={source} className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: color }} />
                  <span className="flex-1 text-gray-300">
                    {t(`source.${source}` as MessageKey)}
                  </span>
                  <span className="tabular-nums text-gray-400">
                    {det.kind === "ready"
                      ? (det.data.meta.by_source[source] ?? 0).toLocaleString(locale)
                      : "–"}
                  </span>
                </li>
              ))}
            </ul>
            {det.kind === "ready" && det.data.meta.truncated && (
              <p className="mt-1 text-amber-300">
                {t("truncated").replace("{n}", det.data.meta.returned.toLocaleString(locale))}
              </p>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}

function StatusPills({ api, t }: { api: ApiState; t: (k: MessageKey) => string }) {
  const pill = (label: string, state: "ok" | "warn" | "down" | "checking", text: string) => {
    const color = {
      ok: "bg-emerald-500",
      warn: "bg-amber-400",
      down: "bg-red-500",
      checking: "bg-gray-400 animate-pulse",
    }[state];
    return (
      <span className="flex items-center gap-1.5" title={text}>
        <span className={`h-2 w-2 rounded-full ${color}`} />
        <span className="text-gray-400">{label}:</span>
        <span>{text}</span>
      </span>
    );
  };

  if (api.kind === "checking") return pill(t("apiStatus"), "checking", t("statusChecking"));
  if (api.kind === "down") return pill(t("apiStatus"), "down", t("statusDown"));

  const { health } = api;
  return (
    <>
      {pill(t("apiStatus"), "ok", t("statusOk"))}
      {pill(
        t("dbStatus"),
        health.database.ok ? "ok" : "down",
        health.database.ok
          ? `PostGIS ${health.database.postgis} · H3 ${health.database.h3}`
          : t("statusDown"),
      )}
      {!health.firms_key_configured && (
        <span className="text-amber-300">⚠ {t("firmsKeyMissing")}</span>
      )}
    </>
  );
}

// MCD12Q1 IGBP sınıflarının (GIBS paleti) gruplanmış lejantı
const LAND_COVER_LEGEND: [string, string][] = [
  ["#086a10", "Forest"],
  ["#c6b044", "Shrubland"],
  ["#fbff13", "Savanna"],
  ["#b6ff05", "Grassland"],
  ["#c24f44", "Cropland"],
  ["#ff6d4c", "Crop/natural mosaic"],
  ["#27ff87", "Wetland"],
  ["#a5a5a5", "Urban"],
  ["#f9ffa4", "Barren"],
  ["#1c0dff", "Water"],
];

function LandCoverLegend() {
  return (
    <ul className="grid grid-cols-2 gap-x-2 gap-y-0.5 text-[11px] text-gray-300">
      {LAND_COVER_LEGEND.map(([c, name]) => (
        <li key={name} className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: c }} />
          {name}
        </li>
      ))}
    </ul>
  );
}
