-- ROI hesaplaması veritabanında sahiplenilir (birden çok API worker'ı aynı bölgeyi iki kez
-- hesaplamasın). Hesaplayan worker her yılda heartbeat_at'i yeniler; heartbeat'i eskimiş bir
-- "running" bölge (worker çöktü / yeniden başladı) başka bir istek tarafından devralınabilir.
ALTER TABLE roi ADD COLUMN heartbeat_at timestamptz;
