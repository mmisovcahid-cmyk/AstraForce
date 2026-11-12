import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[4]
RAW_DIR = ROOT_DIR / "data" / "raw"

ARCHIVE_BASE = "https://firms.modaps.eosdis.nasa.gov/data/country"
API_BASE = "https://firms.modaps.eosdis.nasa.gov/api"
# FIRMS API tek istekte en fazla 5 gün döndürür.
API_MAX_DAYS = 5


@dataclass(frozen=True)
class Source:
    code: str  # fire_detection.source değeri
    alias: str  # CLI'da kullanılan kısa ad
    archive_dir: str | None  # yıllık ülke dosyalarının klasör/ön eki (None: yalnızca API)
    archive_first_year: int
    api_sp: str
    api_nrt: str


SOURCES: dict[str, Source] = {
    s.alias: s
    for s in (
        Source("MODIS", "modis", "modis", 2000, "MODIS_SP", "MODIS_NRT"),
        Source("VIIRS_SNPP", "snpp", "viirs-snpp", 2012, "VIIRS_SNPP_SP", "VIIRS_SNPP_NRT"),
        Source(
            "VIIRS_NOAA20", "noaa20", "viirs-jpss1", 2018, "VIIRS_NOAA20_SP", "VIIRS_NOAA20_NRT"
        ),
        # NOAA-21: SP 2023-03'ten, NRT 2024-01'den. Yıllık ülke dosyası yok → yalnızca API.
        Source("VIIRS_NOAA21", "noaa21", None, 2023, "VIIRS_NOAA21_SP", "VIIRS_NOAA21_NRT"),
    )
}


@dataclass(frozen=True)
class Country:
    iso2: str
    archive_name: str  # FIRMS yıllık dosya adındaki ülke adı
    # FIRMS API için sınırlayıcı kutular [batı, güney, doğu, kuzey]. Sonuçlar daha sonra
    # country_boundary poligonuna kırpılır (komşu ülkelerin noktaları atılır).
    api_bboxes: tuple[tuple[float, float, float, float], ...]


COUNTRIES: dict[str, Country] = {
    c.iso2: c
    for c in (
        Country("AZ", "Azerbaijan", ((44.7, 38.3, 50.7, 42.0),)),
        Country("TR", "Turkey", ((25.6, 35.8, 44.9, 42.2),)),
        Country(
            "US",
            "United_States",
            (
                (-125.0, 24.4, -66.8, 49.5),  # kıta ABD
                (-180.0, 51.0, -129.9, 71.6),  # Alaska (antimeridyenin batısı)
                (172.4, 51.0, 180.0, 53.1),  # Aleut adaları (antimeridyenin doğusu)
                (-160.6, 18.8, -154.7, 22.4),  # Hawaii
            ),
        ),
        # Arjantin (Tierra del Fuego dahil); Falkland Adaları ayrı ülke (FK), kırpmada düşer
        Country("AR", "Argentina", ((-73.6, -55.1, -53.5, -21.7),)),
        # Akdeniz yangın rejimi (Türkiye ile karşılaştırma için)
        Country("GR", "Greece", ((19.3, 34.7, 29.7, 41.8),)),
        Country(
            "PT",
            "Portugal",
            (
                (-9.6, 36.9, -6.1, 42.2),  # anakara
                (-31.4, 36.9, -24.9, 39.8),  # Azorlar
                (-17.3, 32.6, -16.2, 33.2),  # Madeira
            ),
        ),
    )
}


def archive_url(source: Source, year: int, country: Country) -> str:
    d = source.archive_dir
    return f"{ARCHIVE_BASE}/{d}/{year}/{d}_{year}_{country.archive_name}.csv"


def archive_path(source: Source, year: int, country: Country) -> Path:
    d = source.archive_dir
    return RAW_DIR / "country" / d / str(year) / f"{d}_{year}_{country.archive_name}.csv"


def _split_list(value: str) -> list[str]:
    # PowerShell `--country AZ,TR,US` ifadesini diziye çevirip "AZ TR US" olarak iletir;
    # bu yüzden virgül ve boşluk ikisi de ayırıcı kabul edilir.
    return [v for v in re.split(r"[,\s]+", value) if v]


def parse_sources(value: str) -> list[Source]:
    names = [v.lower() for v in _split_list(value)]
    unknown = [n for n in names if n not in SOURCES]
    if unknown:
        raise ValueError(f"Bilinmeyen kaynak: {', '.join(unknown)} (geçerli: {', '.join(SOURCES)})")
    return [SOURCES[n] for n in names]


def parse_countries(value: str) -> list[Country]:
    codes = [v.upper() for v in _split_list(value)]
    unknown = [c for c in codes if c not in COUNTRIES]
    if unknown:
        raise ValueError(f"Bilinmeyen ülke: {', '.join(unknown)} (geçerli: {', '.join(COUNTRIES)})")
    return [COUNTRIES[c] for c in codes]


def parse_years(value: str) -> tuple[int, int]:
    if "-" in value:
        a, b = value.split("-", 1)
        start, end = int(a), int(b)
    else:
        start = end = int(value)
    if start > end:
        raise ValueError("Yıl aralığı ters: başlangıç bitişten büyük olamaz.")
    return start, end


@dataclass(frozen=True)
class Window:
    product: str  # 'SP' | 'NRT'
    start: date
    days: int

    @property
    def end(self) -> date:
        return self.start + timedelta(days=self.days - 1)


def _chunks(product: str, start: date, end: date) -> list[Window]:
    out: list[Window] = []
    d = start
    while d <= end:
        days = min(API_MAX_DAYS, (end - d).days + 1)
        out.append(Window(product, d, days))
        d += timedelta(days=days)
    return out


def plan_windows(
    start: date,
    end: date,
    sp_range: tuple[date, date] | None,
    nrt_range: tuple[date, date] | None,
) -> list[Window]:
    """[start, end] aralığını FIRMS API pencerelerine böler.

    Kesinleşmiş SP verisi olan günler SP'den, sonrası NRT'den çekilir; ikisi çakışmaz.
    """
    windows: list[Window] = []
    nrt_from = start
    if sp_range:
        sp_start, sp_end = max(start, sp_range[0]), min(end, sp_range[1])
        if sp_start <= sp_end:
            windows += _chunks("SP", sp_start, sp_end)
        nrt_from = max(start, sp_range[1] + timedelta(days=1))
    if nrt_range:
        nrt_start, nrt_end = max(nrt_from, nrt_range[0]), min(end, nrt_range[1])
        if nrt_start <= nrt_end:
            windows += _chunks("NRT", nrt_start, nrt_end)
    return windows
