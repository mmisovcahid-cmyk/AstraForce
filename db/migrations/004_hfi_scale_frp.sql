-- Takvimde ikinci gösterge: yangın gücü (FRP). Az sayıda ama çok büyük orman yangını
-- (ör. TR 28 Temmuz–Ağustos 2021) olay sayısında öne çıkmaz, FRP'de çıkar.
ALTER TABLE hfi_scale ADD COLUMN frp_thresholds real[];
