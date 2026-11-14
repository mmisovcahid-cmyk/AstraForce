"use client";

import * as maplibregl from "maplibre-gl";
import { useEffect, useRef } from "react";
import { TerraDraw, TerraDrawPolygonMode } from "terra-draw";
import { TerraDrawMapLibreGLAdapter } from "terra-draw-maplibre-gl-adapter";
import type { CellCollection, Detections } from "@/lib/api";
import { LEVEL_COLORS } from "@/lib/calendar";
import type { Bbox } from "@/lib/regions";
import { SOURCE_COLORS } from "./mapColors";

// Worker dosyası public/maplibre/ altına kopyalanır (scripts/copy-maplibre-worker.mjs).
maplibregl.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");

const STYLE_URL =
  process.env.NEXT_PUBLIC_MAP_STYLE_URL ?? "https://tiles.openfreemap.org/styles/liberty";

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

/** Yoğunluk katmanı için log ölçekli 0..1 değer (en yoğun hücre = 1). */
function normalizeCells(cells: CellCollection | null): GeoJSON.FeatureCollection {
  if (!cells || !cells.features.length) return EMPTY;
  const max = Math.log1p(cells.meta.max || 1);
  return {
    type: "FeatureCollection",
    features: cells.features.map((f) => ({
      ...f,
      properties: { ...f.properties, norm: Math.log1p(f.properties.hfi) / max },
    })),
  };
}

export function FireMap({
  bbox,
  detections,
  cells = null,
  roiGeometry = null,
  drawing = false,
  onPolygon,
  landCoverYear = null,
  staticSources = null,
  showStaticSources = false,
  burnedAreas = null,
  showBurnedAreas = false,
  emergencyAlerts = null,
  showEmergencyAlerts = false,
}: {
  bbox: Bbox;
  detections: Detections | null;
  cells?: CellCollection | null;
  /** Seçili kullanıcı bölgesinin sınırı (çizgi olarak gösterilir). */
  roiGeometry?: GeoJSON.Geometry | null;
  /** true iken kullanıcı haritada çokgen çizer; bitince onPolygon çağrılır. */
  drawing?: boolean;
  onPolygon?: (geometry: GeoJSON.Polygon) => void;
  /** NASA GIBS MODIS MCD12Q1 (IGBP) arazi örtüsü katmanı; null = kapalı. */
  landCoverYear?: number | null;
  /** Statik ısı kaynakları (meşale, endüstri) GeoJSON katmanı. */
  staticSources?: GeoJSON.FeatureCollection | null;
  /** Statik kaynak katmanının haritada gösterilip gösterilmeyeceği. */
  showStaticSources?: boolean;
  /** Yanık alan hücreleri GeoJSON katmanı. */
  burnedAreas?: GeoJSON.FeatureCollection | null;
  /** Yanık alan katmanının haritada gösterilip gösterilmeyeceği. */
  showBurnedAreas?: boolean;
  /** Acil durum uyarıları GeoJSON katmanı (EONET, GDACS, ReliefWeb). */
  emergencyAlerts?: GeoJSON.FeatureCollection | null;
  /** Acil durum uyarı katmanının haritada gösterilip gösterilmeyeceği. */
  showEmergencyAlerts?: boolean;
}) {
  const latestLandCover = useRef<number | null>(landCoverYear);
  const drawRef = useRef<TerraDraw | null>(null);
  const onPolygonRef = useRef(onPolygon);
  onPolygonRef.current = onPolygon;
  const latestRoi = useRef<GeoJSON.FeatureCollection>(EMPTY);
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const latest = useRef<GeoJSON.FeatureCollection>(EMPTY);
  const latestCells = useRef<GeoJSON.FeatureCollection>(EMPTY);

  useEffect(() => {
    if (!container.current) return;
    const m = new maplibregl.Map({
      container: container.current,
      style: STYLE_URL,
      bounds: bbox,
      fitBoundsOptions: { padding: 40 },
      attributionControl: { compact: true },
    });
    m.addControl(new maplibregl.NavigationControl(), "top-right");
    m.addControl(new maplibregl.ScaleControl(), "bottom-left");

    m.on("load", () => {
      addLandCover(m, latestLandCover.current);
      // H3 r5 yoğunluk katmanı (harmonize HFI), noktaların altında
      m.addSource("cells", { type: "geojson", data: latestCells.current });
      m.addLayer({
        id: "cells",
        type: "fill",
        source: "cells",
        paint: {
          "fill-color": [
            "interpolate",
            ["linear"],
            ["get", "norm"],
            0, LEVEL_COLORS[1],
            0.5, LEVEL_COLORS[2],
            0.8, LEVEL_COLORS[3],
            1, LEVEL_COLORS[4],
          ],
          "fill-opacity": 0.65,
          "fill-outline-color": "rgba(255,255,255,0.15)",
        },
      });
      m.addSource("roi", { type: "geojson", data: latestRoi.current });
      m.addLayer({
        id: "roi-outline",
        type: "line",
        source: "roi",
        paint: { "line-color": "#f8fafc", "line-width": 2, "line-dasharray": [2, 1] },
      });
      m.addSource("detections", { type: "geojson", data: latest.current });
      m.addLayer({
        id: "detections",
        type: "circle",
        source: "detections",
        paint: {
          "circle-color": [
            "match",
            ["get", "source"],
            "MODIS", SOURCE_COLORS.MODIS,
            "VIIRS_SNPP", SOURCE_COLORS.VIIRS_SNPP,
            "VIIRS_NOAA20", SOURCE_COLORS.VIIRS_NOAA20,
            "VIIRS_NOAA21", SOURCE_COLORS.VIIRS_NOAA21,
            "#9ca3af",
          ],
          // FRP (MW) büyüdükçe nokta büyür.
          "circle-radius": [
            "interpolate",
            ["linear"],
            ["coalesce", ["get", "frp"], 0],
            0, 2.5,
            50, 5,
            500, 9,
          ],
          "circle-opacity": 0.75,
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 0.5,
        },
      });
      // Statik ısı kaynakları katmanı (meşale, endüstri) — varsayılan gizli
      m.addSource("static-sources", { type: "geojson", data: EMPTY });
      m.addLayer({
        id: "static-sources",
        type: "fill",
        source: "static-sources",
        paint: {
          "fill-color": "#ef4444",
          "fill-opacity": 0.35,
          "fill-outline-color": "#b91c1c",
        },
      });
      m.setLayoutProperty("static-sources", "visibility", "none");
      // Yanık alan katmanı (burned area) — varsayılan gizli
      m.addSource("burned-areas", { type: "geojson", data: EMPTY });
      m.addLayer({
        id: "burned-areas",
        type: "fill",
        source: "burned-areas",
        paint: {
          "fill-color": "#f59e0b",
          "fill-opacity": 0.45,
          "fill-outline-color": "#d97706",
        },
      });
      m.setLayoutProperty("burned-areas", "visibility", "none");
      // Acil durum uyarıları katmanı (EONET, GDACS, ReliefWeb) — varsayılan gizli
      m.addSource("emergency-alerts", { type: "geojson", data: EMPTY });
      m.addLayer({
        id: "emergency-alerts",
        type: "fill",
        source: "emergency-alerts",
        paint: {
          "fill-color": "#ef4444",
          "fill-opacity": 0.5,
          "fill-outline-color": "#b91c1c",
        },
      });
      m.setLayoutProperty("emergency-alerts", "visibility", "none");

      const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });
      m.on("mouseenter", "detections", (e) => {
        m.getCanvas().style.cursor = "pointer";
        const f = e.features?.[0];
        if (!f) return;
        const p = f.properties as Record<string, string | number | null>;
        const ts = String(p.acq_ts).replace("T", " ").slice(0, 16);
        popup
          .setLngLat((f.geometry as GeoJSON.Point).coordinates as [number, number])
          .setHTML(
            `<b>${p.source}</b> · ${p.product}<br>${ts} UTC<br>FRP: ${p.frp ?? "–"} MW`,
          )
          .addTo(m);
      });
      m.on("mouseleave", "detections", () => {
        m.getCanvas().style.cursor = "";
        popup.remove();
      });
      m.on("mousemove", "cells", (e) => {
        const f = e.features?.[0];
        if (!f) return;
        const p = f.properties as Record<string, number>;
        popup
          .setLngLat(e.lngLat)
          .setHTML(`HFI: <b>${Number(p.hfi).toFixed(1)}</b><br>FRP: ${Number(p.frp).toFixed(0)} MW<br>${p.days} gün/days`)
          .addTo(m);
      });
      m.on("mouseleave", "cells", () => popup.remove());
    });

    map.current = m;
    // Geliştirmede tarayıcı konsolundan incelemek için (window.__astraMap)
    if (process.env.NODE_ENV !== "production") {
      (window as unknown as { __astraMap?: maplibregl.Map }).__astraMap = m;
    }
    return () => {
      m.remove();
      map.current = null;
    };
    // Harita yalnızca bir kez oluşturulur; bölge ve veri değişimi aşağıdaki effect'lerde.
  }, []);

  useEffect(() => {
    map.current?.fitBounds(bbox, { padding: 40, duration: 1200 });
  }, [bbox]);

  useEffect(() => {
    latest.current = detections ?? EMPTY;
    const src = map.current?.getSource("detections") as maplibregl.GeoJSONSource | undefined;
    src?.setData(latest.current);
  }, [detections]);

  useEffect(() => {
    latestCells.current = normalizeCells(cells);
    const src = map.current?.getSource("cells") as maplibregl.GeoJSONSource | undefined;
    src?.setData(latestCells.current);
  }, [cells]);

  // Statik ısı kaynakları katmanı: veri geldiğinde source'u güncelle
  useEffect(() => {
    const src = map.current?.getSource("static-sources") as maplibregl.GeoJSONSource | undefined;
    if (src) src.setData(staticSources ?? EMPTY);
  }, [staticSources]);

  // Yanık alan katmanı: veri geldiğinde source'u güncelle
  useEffect(() => {
    const src = map.current?.getSource("burned-areas") as maplibregl.GeoJSONSource | undefined;
    if (src) src.setData(burnedAreas ?? EMPTY);
  }, [burnedAreas]);

  // Acil durum uyarıları katmanı: veri geldiğinde source'u güncelle
  useEffect(() => {
    const src = map.current?.getSource("emergency-alerts") as maplibregl.GeoJSONSource | undefined;
    if (src) src.setData(emergencyAlerts ?? EMPTY);
  }, [emergencyAlerts]);

  // Statik kaynak katmanı görünürlüğü toggle
  useEffect(() => {
    const m = map.current;
    if (m?.isStyleLoaded() && m.getLayer("static-sources")) {
      m.setLayoutProperty("static-sources", "visibility", showStaticSources ? "visible" : "none");
    }
  }, [showStaticSources]);

  // Yanık alan katmanı görünürlüğü toggle
  useEffect(() => {
    const m = map.current;
    if (m?.isStyleLoaded() && m.getLayer("burned-areas")) {
      m.setLayoutProperty("burned-areas", "visibility", showBurnedAreas ? "visible" : "none");
    }
  }, [showBurnedAreas]);

  // Acil durum uyarıları katmanı görünürlüğü toggle
  useEffect(() => {
    const m = map.current;
    if (m?.isStyleLoaded() && m.getLayer("emergency-alerts")) {
      m.setLayoutProperty(
        "emergency-alerts",
        "visibility",
        showEmergencyAlerts ? "visible" : "none",
      );
    }
  }, [showEmergencyAlerts]);

  useEffect(() => {
    latestRoi.current = roiGeometry
      ? { type: "FeatureCollection", features: [{ type: "Feature", geometry: roiGeometry, properties: {} }] }
      : EMPTY;
    const src = map.current?.getSource("roi") as maplibregl.GeoJSONSource | undefined;
    src?.setData(latestRoi.current);
  }, [roiGeometry]);

  useEffect(() => {
    latestLandCover.current = landCoverYear;
    const m = map.current;
    if (m?.isStyleLoaded()) addLandCover(m, landCoverYear);
  }, [landCoverYear]);

  // Çizim modu (terra-draw): çokgen bitince üst bileşene bildir
  useEffect(() => {
    const m = map.current;
    if (!m || !drawing) return;
    const start = () => {
      const draw = new TerraDraw({
        adapter: new TerraDrawMapLibreGLAdapter({ map: m }),
        modes: [new TerraDrawPolygonMode()],
      });
      draw.start();
      draw.setMode("polygon");
      draw.on("finish", (id) => {
        const feat = draw.getSnapshotFeature(id);
        if (feat?.geometry.type === "Polygon") onPolygonRef.current?.(feat.geometry as GeoJSON.Polygon);
      });
      drawRef.current = draw;
    };
    if (m.isStyleLoaded()) start();
    else m.once("load", start);
    return () => {
      m.off("load", start);
      drawRef.current?.stop();
      drawRef.current = null;
    };
  }, [drawing]);

  return <div ref={container} className="h-full w-full" data-testid="fire-map" />;
}

const GIBS_LAND_COVER =
  "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Combined_L3_IGBP_Land_Cover_Type_Annual/default/{year}-01-01/GoogleMapsCompatible_Level8/{z}/{y}/{x}.png";

/** Arazi örtüsü raster katmanını (yeniden) ekler; yıl değişince kaynak yenilenir. */
function addLandCover(m: maplibregl.Map, year: number | null) {
  if (m.getLayer("landcover")) m.removeLayer("landcover");
  if (m.getSource("landcover")) m.removeSource("landcover");
  if (year === null) return;
  m.addSource("landcover", {
    type: "raster",
    tiles: [GIBS_LAND_COVER.replace("{year}", String(year))],
    tileSize: 256,
    maxzoom: 8,
    attribution: "Land cover: NASA GIBS / MODIS MCD12Q1",
  });
  // Yangın katmanlarının altında kalsın
  const before = m.getLayer("cells") ? "cells" : undefined;
  m.addLayer({ id: "landcover", type: "raster", source: "landcover", paint: { "raster-opacity": 0.6 } }, before);
}
