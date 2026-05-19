\set ON_ERROR_STOP on

-- Load source scripts provided in the assignment.
\i '/seed_files/Файлы к ML/task1ddl (1).sql'
\i '/seed_files/Файлы к ML/1task (1).sql'
\i '/seed_files/Файлы к ML/task2ddl (1).sql'
\i '/seed_files/Файлы к ML/2task (1).sql'

-- Normalize names for the current pipeline requirements.
ALTER TABLE IF EXISTS well_telemetry RENAME TO telemetry;

-- Useful indexes for ETL and BI workloads.
CREATE INDEX IF NOT EXISTS idx_production_date ON production(date);
CREATE INDEX IF NOT EXISTS idx_production_well_date ON production(well_id, date);
CREATE INDEX IF NOT EXISTS idx_telemetry_well_ts ON telemetry(well_id, "timestamp");

-- Data marts schema consumed by Superset.
CREATE SCHEMA IF NOT EXISTS mart;
