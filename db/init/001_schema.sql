CREATE EXTENSION IF NOT EXISTS postgis;

-- 서핑 스팟 (해변) 기본 정보와 해저 지형
CREATE TABLE IF NOT EXISTS spots (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    region            TEXT NOT NULL,
    geom              GEOGRAPHY(Point, 4326) NOT NULL,
    bottom_type       TEXT NOT NULL CHECK (bottom_type IN ('sand', 'reef', 'mixed', 'rock', 'unknown')),
    beginner_friendly BOOLEAN NOT NULL DEFAULT FALSE,
    board_fit         TEXT[] NOT NULL DEFAULT '{}',
    popularity        REAL NOT NULL DEFAULT 0.5,
    tour_area         TEXT,  -- 한국관광공사 관광지 집중률: 시도 코드
    tour_signgu       TEXT,  -- 시군구 코드
    tour_name         TEXT,  -- 관광지명 (예: 송정해수욕장)
    note              TEXT
);
CREATE INDEX IF NOT EXISTS spots_geom_idx ON spots USING GIST (geom);

-- 수집한 해양 기상 관측/예보 이력 (혼잡도 예측 학습용으로도 사용)
CREATE TABLE IF NOT EXISTS conditions (
    spot_id         TEXT NOT NULL REFERENCES spots(id) ON DELETE CASCADE,
    observed_at     TIMESTAMPTZ NOT NULL,
    wave_height_m   REAL,
    wave_period_s   REAL,
    wind_speed_ms   REAL,
    wind_dir_deg    REAL,
    tide_m          REAL,
    source          TEXT NOT NULL,
    PRIMARY KEY (spot_id, observed_at, source)
);
