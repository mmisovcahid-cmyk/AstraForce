#!/usr/bin/env python3
"""Yeni ülke ekleme sihirbazı.

Tek komutla bir ülkeyi projeye ekler ve veri işleme pipeline'ını çalıştırır.

Adımları:
  1. COUNTRIES'ye ülke kaydı ekler  (apps/api/app/ingest/sources.py)
  2. REGIONS'ye bbox kaydı ekler    (apps/web/src/lib/regions.ts)
  3. Ülke sınırlarını yükler        (ingest boundaries)
  4. Arşiv + API verisini yükler    (ingest all --country <code>)
  5. Harmonizasyonu çalıştırır      (harmonize run --country <code>)
  6. Durum raporu yazdırır

Kullanım (kökten):
  python scripts/add_country.py \\
    --code XX --name "Ülke Adı" --archive-name "Archive_Name" \\
    --bbox "w,s,e,n"

Birden çok sınırlayıcı kutu için (ör. ABD, Portekiz):
  --bbox "w1,s1,e1,n1;w2,s2,e2,n2;..."

Örnek:
  python scripts/add_country.py \\
    --code ES --name İspanya --archive-name Spain \\
    --bbox "1.9,35.0,4.4,44.0"
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES_PY = ROOT / "apps" / "api" / "app" / "ingest" / "sources.py"
REGIONS_TS = ROOT / "apps" / "web" / "src" / "lib" / "regions.ts"


def _run(cmd: list[str]) -> None:
    """Komutu çalıştırır; çıktıyı akışlar. Hata durumunda çıkış kodu ile çıkar."""
    print(f"  $ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, check=True)


def _parse_bboxes(value: str) -> list[tuple[float, float, float, float]]:
    """``w,s,e,n;w2,s2,e2,n2`` şeklindeki string'i parse eder."""
    out: list[tuple[float, float, float, float]] = []
    for part in value.split(";"):
        nums = [float(x.strip()) for x in part.split(",")]
        if len(nums) != 4:
            raise ValueError(
                f"Geçersiz bbox: '{part}' — 4 sayı gerekli (w,s,e,n), {len(nums)} verildi"
            )
        out.append(tuple(nums))  # type: ignore[arg-type]
    return out


def _bbox_expr_python(bboxes: list[tuple[float, float, float, float]]) -> str:
    """Python tuple ifadesi üretir: ((w,s,e,n),) veya ((w1,...), (w2,...),)."""
    inner = ", ".join(str(b) for b in bboxes)
    return f"(({inner}),)"


def _bbox_expr_typescript(bboxes: list[tuple[float, float, float, float]]) -> str:
    """TypeScript için ilk bbox'u dizi olarak üretir: [w, s, e, n]."""
    b = bboxes[0]
    return f"[{b[0]}, {b[1]}, {b[2]}, {b[3]}]"


def add_to_sources_py(
    code: str, archive_name: str, bboxes: list[tuple[float, float, float, float]]
) -> None:
    """COUNTRIES dict'sine yeni ülke ekler."""
    text = SOURCES_PY.read_text(encoding="utf-8")

    if f'Country("{code}"' in text:
        print(f"  ⚠ {code} zaten COUNTRIES'te mevcut, atlanıyor.")
        return

    entry = f'        Country("{code}", "{archive_name}", {_bbox_expr_python(bboxes)}),'
    marker = "\n    )\n}"
    idx = text.rfind(marker)
    if idx == -1:
        raise ValueError("COUNTRIES dict kapanışı bulunamadı (sources.py)")

    new_text = text[:idx] + "\n" + entry + text[idx:]
    SOURCES_PY.write_text(new_text, encoding="utf-8")
    print(f"  ✓ {code} eklendi → {SOURCES_PY.relative_to(ROOT)}")


def add_to_regions_ts(
    code: str, bboxes: list[tuple[float, float, float, float]]
) -> None:
    """REGIONS array'ına yeni bölge ekler (ilk bbox harita kadrajı için)."""
    text = REGIONS_TS.read_text(encoding="utf-8")

    if f'id: "{code}"' in text:
        print(f"  ⚠ {code} zaten REGIONS'da mevcut, atlanıyor.")
        return

    entry = f'  {{ id: "{code}", bbox: {_bbox_expr_typescript(bboxes)} }},'
    marker = "] as const"
    idx = text.rfind(marker)
    if idx == -1:
        raise ValueError("REGIONS array kapanışı bulunamadı (regions.ts)")

    # idx, "] as const" içindeki "]" işaretçisine işaret eder
    new_text = text[:idx] + entry + "\n" + text[idx:]
    REGIONS_TS.write_text(new_text, encoding="utf-8")
    print(f"  ✓ {code} eklendi → {REGIONS_TS.relative_to(ROOT)}")


def main() -> None:
    p = argparse.ArgumentParser(
        prog="add_country",
        description="Yeni ülke ekleme sihirbazı (ingest + harmonize dahil)",
    )
    p.add_argument("--code", required=True, help="Ülke ISO2 kodu (ör. AZ, TR, ES)")
    p.add_argument("--name", required=True, help="Ülke tam adı (ör. Azerbaijan, Türkiye, İspanya)")
    p.add_argument(
        "--archive-name",
        required=True,
        help="FIRMS arşivi içindeki ülke dosya adı (ör. Azerbaijan, Turkey, Spain)",
    )
    p.add_argument(
        "--bbox",
        required=True,
        help="Sınırlayıcı kutular [w,s,e,n]; birden çok için ';' ile ayırın",
    )
    p.add_argument(
        "--years",
        default="2000-last",
        help="Arşiv yıl aralığı (varsayılan: 2000-geçen yıl)",
    )
    args = p.parse_args()

    code = args.code.upper()
    bboxes = _parse_bboxes(args.bbox)

    print(f"\n{'=' * 50}")
    print(f"  Yeni ülke ekleme sihirbazı: {code}")
    print(f"{'=' * 50}\n")

    # 1. Kaynak dosyaları
    print("1. Kaynak dosyaları güncelleniyor...")
    add_to_sources_py(code, args.archive_name, bboxes)
    add_to_regions_ts(code, bboxes)

    # 2. Sınırlar
    print("\n2. Ülke sınırları yükleniyor (Natural Earth)...")
    _run(["pnpm", "--filter", "api", "ingest", "boundaries"])

    # 3. Arşiv + API verisi
    print(f"\n3. Veri yükleniyor: {code} ({args.years}) ...")
    _run(["pnpm", "--filter", "api", "ingest", "all", "--country", code, "--years", args.years])

    # 4. Harmonizasyon
    print(f"\n4. Harmonizasyon çalıştırılıyor: {code} ...")
    _run(["pnpm", "--filter", "api", "harmonize", "run", "--country", code])

    # 5. Durum raporu
    print(f"\n5. Durum raporu: {code} ...")
    _run(["pnpm", "--filter", "api", "ingest", "status"])
    _run(["pnpm", "--filter", "api", "harmonize", "status"])

    print(f"\n{'=' * 50}")
    print(f"  ✅ {code} başarıyla eklendi ve işlendi!")
    print(f"{'=' * 50}\n")


if __name__ == "__main__":
    main()
