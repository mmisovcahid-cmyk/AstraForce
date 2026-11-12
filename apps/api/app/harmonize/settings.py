"""Harmonizasyon parametreleri. Değiştirince HFI_VERSION'ı artırın."""

from datetime import date

HFI_VERSION = "hfi-v2"  # v2: sıcak nokta (det) hedefi + katsayı tablosu

# Temizlik
MIN_CONFIDENCE = 1  # 0 düşük, 1 nominal, 2 yüksek
# Kalıcı kaynak: aynı r8 hücresinde ≥ bu kadar farklı günde ve ≥ bu kadar farklı yılda tespit
PERSISTENT_MIN_DAYS = 100
PERSISTENT_MIN_YEARS = 5

# ST-DBSCAN (min_samples=1, yani mekân-zaman bağlantılı bileşenler)
EVENT_EPS_KM = 1.5
EVENT_EPS_DAYS = 1

# Kaynaklar
MODIS = "MODIS"
VIIRS_SOURCES = ("VIIRS_SNPP", "VIIRS_NOAA20")
ALL_SOURCES = (MODIS, *VIIRS_SOURCES)
AQUA_FIRST_DAY = date(2002, 7, 4)  # öncesinde MODIS = yalnızca Terra
TERRA_FACTOR_YEARS = (2003, 2007)  # Terra+Aqua / Terra oranının hesaplandığı yıllar
VIIRS_FIRST_DAY = date(2012, 1, 20)

# Kalibrasyon
RATIO_WINDOW_YEARS = 2  # oran modeli: test yılının ±2 yılı
RATIO_PRIOR_WEIGHT = 20.0  # ay oranını yıllık orana çeken sözde-sayım (seyrek aylar için)
H3_RES = 5

EPOCH = date(2000, 1, 1)  # gün indeksleri bu tarihe göre
