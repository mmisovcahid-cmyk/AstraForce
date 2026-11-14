-- 10. aşama: acil durum uyarıları ve afet kaynakları (EONET, GDACS, ReliefWeb).
--
-- Bu tablolar yangınla ilgili acil durum bildirimlerini saklar; FireMap ve Dashboard
-- üzerinden kullanıcılar seçili bölgesindeki aktif uyarıları görebilir.

-- NASA EONET (Earth Observatory Natural Event Tracker) olayları
CREATE TABLE eonet_events (
    id           text PRIMARY KEY,          -- EONET event id
    title        text NOT NULL,
    description  text,
    link         text,
    closed       boolean NOT NULL DEFAULT false,
    event_date   date,
    geometry     geometry(Geometry, 4326),  -- merkezi nokta / poligon
    source       text NOT NULL DEFAULT 'eonet',
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX eonet_events_geometry ON eonet_events USING gist (geometry);
CREATE INDEX eonet_events_event_date ON eonet_events (event_date);
CREATE INDEX eonet_events_closed ON eonet_events (closed);

-- GDACS (Global Disaster Alert and Coordination System) uyarıları
CREATE TABLE gdacs_alerts (
    eventid      text PRIMARY KEY,          -- GDACS event id
    eventname    text NOT NULL,
    countryname  text,
    iso3         char(3),
    eventtype    text,                      -- e.g. VF (vegetation fire), EQ, TC, FL
    alertlevel   text,                      -- e.g. red, orange, green
    fromdate     date,
    todate       date,
    geometry     geometry(Geometry, 4326),
    source       text NOT NULL DEFAULT 'gdacs',
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX gdacs_alerts_geometry ON gdacs_alerts USING gist (geometry);
CREATE INDEX gdacs_alerts_eventtype ON gdacs_alerts (eventtype);
CREATE INDEX gdacs_alerts_alertlevel ON gdacs_alerts (alertlevel);

-- ReliefWeb (UN OCHA) afet raporları
CREATE TABLE reliefweb_reports (
    rid          text PRIMARY KEY,          -- ReliefWeb report id
    name         text NOT NULL,
    body         text,
    url          text,
    date         date,
    geometry     geometry(Geometry, 4326),
    source       text NOT NULL DEFAULT 'reliefweb',
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX reliefweb_reports_geometry ON reliefweb_reports USING gist (geometry);
CREATE INDEX reliefweb_reports_date ON reliefweb_reports (date);

-- Birleşik acil durum görünümü: tüm kaynaklardan tek sorgu ile erişim
CREATE VIEW emergency_alerts AS
SELECT id AS alert_id, title AS alert_name, description AS alert_description,
       link AS alert_url, event_date AS alert_date, geometry, source, created_at, updated_at
FROM eonet_events
UNION ALL
SELECT eventid, eventname, NULL, NULL, fromdate, geometry, source, created_at, updated_at
FROM gdacs_alerts
UNION ALL
SELECT rid, name, body, url, date, geometry, source, created_at, updated_at
FROM reliefweb_reports;
