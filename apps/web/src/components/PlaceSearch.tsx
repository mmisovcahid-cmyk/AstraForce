"use client";

import { useRef, useState } from "react";
import type { Bbox } from "@/lib/regions";

export type Place = { name: string; lat: number; lon: number; bbox: Bbox | null };

type PhotonFeature = {
  geometry: { coordinates: [number, number] };
  properties: {
    name?: string;
    city?: string;
    state?: string;
    country?: string;
    extent?: [number, number, number, number]; // [batı, kuzey, doğu, güney]
  };
};

/**
 * Yer adı arama (Photon / OpenStreetMap, anahtar gerektirmez). Yalnızca Enter ya da
 * düğmeyle arar (her tuş vuruşunda değil) — ücretsiz servisin kullanım kuralına uygun.
 */
export function PlaceSearch({
  onSelect,
  placeholder,
  noResult,
  className = "",
}: {
  onSelect: (p: Place) => void;
  placeholder: string;
  noResult: string;
  className?: string;
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Place[] | null>(null);
  const [busy, setBusy] = useState(false);
  const ctrl = useRef<AbortController | null>(null);

  const search = async () => {
    const query = q.trim();
    if (query.length < 2) return;
    ctrl.current?.abort();
    ctrl.current = new AbortController();
    setBusy(true);
    try {
      const res = await fetch(
        `https://photon.komoot.io/api/?q=${encodeURIComponent(query)}&limit=6`,
        { signal: ctrl.current.signal },
      );
      const data: { features: PhotonFeature[] } = await res.json();
      setResults(
        data.features.map((f) => {
          const p = f.properties;
          const [lon, lat] = f.geometry.coordinates;
          const label = [p.name, p.state, p.country].filter(Boolean).join(", ");
          const e = p.extent;
          return { name: label || query, lat, lon, bbox: e ? [e[0], e[3], e[2], e[1]] : null };
        }),
      );
    } catch {
      setResults([]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`relative ${className}`}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void search();
        }}
        className="flex gap-1"
        role="search"
      >
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={placeholder}
          aria-label={placeholder}
          className="min-w-0 flex-1 rounded bg-white/10 px-2 py-1"
        />
        <button type="submit" className="rounded bg-white/10 px-2 py-1 hover:bg-white/20" aria-label="search">
          {busy ? "…" : "⌕"}
        </button>
      </form>
      {results && (
        <ul className="absolute left-0 right-0 top-full z-30 mt-1 max-h-60 overflow-auto rounded border border-white/10 bg-gray-950 text-xs shadow-xl">
          {results.length === 0 && <li className="px-2 py-1.5 text-gray-500">{noResult}</li>}
          {results.map((r) => (
            <li key={`${r.lat},${r.lon},${r.name}`}>
              <button
                type="button"
                className="w-full px-2 py-1.5 text-left hover:bg-white/10"
                onClick={() => {
                  setResults(null);
                  setQ(r.name);
                  onSelect(r);
                }}
              >
                {r.name}
                <span className="ml-1 text-gray-500">
                  {r.lat.toFixed(2)}, {r.lon.toFixed(2)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
