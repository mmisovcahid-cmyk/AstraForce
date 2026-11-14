4) Kurulum (tek komut)
pnpm setup:all

Bu komut paketleri ve Python’u kurar, veritabanını başlatır ve .env dosyasını oluşturur.

6) Veriyi yükleyin (yalnızca ilk sefer, ~1,5 saat)

pnpm ingest all --country AZ,TR,US,AR,GR,PT
pnpm harmonize run --country AZ,TR,US,AR,GR,PT

Daha hızlı denemek isterseniz yalnızca küçük bir ülkeyle başlayın, birkaç dakika sürer:

pnpm ingest all --country AZ
pnpm harmonize run --country AZ

7) Uygulamayı başlatın
pnpm dev

Tarayıcıda http://localhost:3000 adresini açın. Durdurmak için terminalde Ctrl + C.

Sonraki günlerde

Docker Desktop’ı açın, ardından:

pnpm db:up
pnpm dev

Verileri güncellemek isterseniz:

pnpm update:daily

Not: Kendi bilgisayarınızdaki mevcut klasörde (Documents\GitHub\AstraForce) her şey zaten kurulu ve veri yüklü. Orada yalnızca 7. adım (pnpm dev) yeterli.