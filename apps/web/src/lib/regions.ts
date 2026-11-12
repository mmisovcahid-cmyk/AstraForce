// Verisi yüklü hazır ülkeler. bbox: [batı, güney, doğu, kuzey] (WGS84 derece), harita kadrajı için.
export type Bbox = [number, number, number, number];

export const REGIONS = [
  { id: "AZ", bbox: [44.77, 38.39, 50.39, 41.91] },
  { id: "TR", bbox: [25.66, 35.81, 44.83, 42.11] },
  // ABD: kadraj kıta ABD'si; veri Alaska ve Hawaii'yi de içerir
  { id: "US", bbox: [-124.85, 24.4, -66.89, 49.38] },
  { id: "AR", bbox: [-73.6, -55.1, -53.6, -21.8] },
  { id: "GR", bbox: [19.3, 34.7, 29.7, 41.8] },
  { id: "PT", bbox: [-9.6, 36.9, -6.1, 42.2] },
  { id: "ES", bbox: [-9.4, 35.9, 4.4, 43.9] },
] as const satisfies readonly { id: string; bbox: Bbox }[];

export type RegionId = (typeof REGIONS)[number]["id"];

/** Alan kodu: hazır ülke ("TR") ya da kullanıcı bölgesi ("roi:abc123"). */
export type AreaCode = RegionId | `roi:${string}`;

export function isRegionId(v: string): v is RegionId {
  return REGIONS.some((r) => r.id === v);
}

export function parseAreaCode(v: string | null): AreaCode | null {
  if (!v) return null;
  if (isRegionId(v.toUpperCase())) return v.toUpperCase() as RegionId;
  const m = /^roi:([a-z0-9]{6,32})$/i.exec(v);
  return m ? (`roi:${m[1].toLowerCase()}` as AreaCode) : null;
}

export function isRoi(area: AreaCode): area is `roi:${string}` {
  return area.startsWith("roi:");
}

export function roiId(area: AreaCode): string | null {
  return isRoi(area) ? area.slice(4) : null;
}

export function regionBbox(id: RegionId): Bbox {
  return (REGIONS.find((r) => r.id === id) ?? REGIONS[0]).bbox;
}
