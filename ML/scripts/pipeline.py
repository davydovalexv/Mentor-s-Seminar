import io
import os
from dataclasses import dataclass
from pathlib import Path

import boto3
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.fs as pafs
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sqlalchemy import create_engine


@dataclass
class Settings:
    pg_host: str = os.getenv("POSTGRES_HOST", "localhost")
    pg_port: str = os.getenv("POSTGRES_PORT", "5432")
    pg_db: str = os.getenv("POSTGRES_DB", "oil_analytics")
    pg_user: str = os.getenv("POSTGRES_USER", "etl_user")
    pg_password: str = os.getenv("POSTGRES_PASSWORD", "etl_pass")

    minio_endpoint: str = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    minio_access_key: str = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    minio_secret_key: str = os.getenv("MINIO_SECRET_KEY", "minioadmin")
    minio_bucket: str = os.getenv("MINIO_BUCKET", "lakehouse")

    @property
    def postgres_uri(self) -> str:
        return (
            f"postgresql+psycopg2://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_db}"
        )


def iqr_filter(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for column in columns:
        q1 = out[column].quantile(0.25)
        q3 = out[column].quantile(0.75)
        iqr = q3 - q1
        low = q1 - 1.5 * iqr
        high = q3 + 1.5 * iqr
        out = out[(out[column] >= low) & (out[column] <= high)]
    return out


def clean_production(df_prod: pd.DataFrame) -> pd.DataFrame:
    df = df_prod.copy()
    df["date"] = pd.to_datetime(df["date"])
    num_cols = [
        "oil_ton",
        "gas_m3",
        "water_m3",
        "energy_kwh",
        "downtime_hours",
        "temperature",
        "pressure",
    ]
    for col in num_cols:
        if col in ("temperature", "pressure"):
            df[col] = df.groupby("well_id")[col].transform(
                lambda s: s.fillna(s.median())
            )
        else:
            df[col] = df[col].fillna(0)

    df["downtime_coef"] = (df["downtime_hours"] / 24.0).clip(0, 1)
    df = iqr_filter(df, ["oil_ton", "temperature", "pressure"])
    return df


def build_feature_table(
    df_prod_clean: pd.DataFrame, df_telemetry: pd.DataFrame
) -> pd.DataFrame:
    tele = df_telemetry.copy()
    tele["timestamp"] = pd.to_datetime(tele["timestamp"])
    tele["date"] = tele["timestamp"].dt.date
    tele_daily = (
        tele.groupby(["well_id", "date"], as_index=False)
        .agg(
            avg_pressure=("pressure_out", "mean"),
            avg_temperature=("temperature", "mean"),
            avg_vibration=("vibration", "mean"),
            avg_rpm=("pump_speed_rpm", "mean"),
            avg_current=("pump_current", "mean"),
        )
        .assign(date=lambda d: pd.to_datetime(d["date"]))
    )

    features = df_prod_clean.merge(tele_daily, on=["well_id", "date"], how="left")
    for c in ["avg_pressure", "avg_temperature", "avg_vibration", "avg_rpm", "avg_current"]:
        features[c] = features.groupby("well_id")[c].transform(
            lambda s: s.fillna(s.median())
        )
    return features


def build_marts(df_features: pd.DataFrame, wells: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily_prod = (
        df_features.groupby("date", as_index=False)
        .agg(
            total_oil_ton=("oil_ton", "sum"),
            avg_pressure=("avg_pressure", "mean"),
            avg_temperature=("avg_temperature", "mean"),
            avg_downtime_coef=("downtime_coef", "mean"),
        )
        .sort_values("date")
    )

    well_kpi = (
        df_features.groupby("well_id", as_index=False)
        .agg(
            avg_oil_ton=("oil_ton", "mean"),
            downtime_pct=("downtime_coef", lambda s: float(s.mean() * 100)),
            avg_pressure=("avg_pressure", "mean"),
            avg_temperature=("avg_temperature", "mean"),
        )
        .merge(wells[["well_id", "name", "field_name", "region", "status"]], on="well_id", how="left")
        .sort_values("avg_oil_ton", ascending=False)
    )

    well_kpi["performance_rank"] = np.arange(1, len(well_kpi) + 1)
    return daily_prod, well_kpi


def build_ml_metrics(df_features: pd.DataFrame) -> pd.DataFrame:
    model_df = df_features[
        [
            "oil_ton",
            "avg_pressure",
            "avg_temperature",
            "energy_kwh",
            "downtime_coef",
            "avg_vibration",
            "avg_rpm",
            "avg_current",
        ]
    ].dropna()
    if len(model_df) < 10:
        return pd.DataFrame(
            [{"model": "RandomForestRegressor", "mae": np.nan, "r2": np.nan, "rows_used": len(model_df)}]
        )

    x = model_df.drop(columns=["oil_ton"])
    y = model_df["oil_ton"]
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.25, random_state=42
    )
    model = RandomForestRegressor(n_estimators=200, random_state=42)
    model.fit(x_train, y_train)
    preds = model.predict(x_test)

    return pd.DataFrame(
        [
            {
                "model": "RandomForestRegressor",
                "mae": float(mean_absolute_error(y_test, preds)),
                "r2": float(r2_score(y_test, preds)),
                "rows_used": len(model_df),
            }
        ]
    )


def build_target_training_dataset(
    df_targets: pd.DataFrame,
    df_telemetry: pd.DataFrame,
    df_production: pd.DataFrame,
) -> pd.DataFrame:
    targets = df_targets.copy()
    targets["date"] = pd.to_datetime(targets["date"])
    targets = targets.rename(columns={"daily_oil_ton": "target_oil_ton"})

    telemetry = df_telemetry.copy()
    telemetry["timestamp"] = pd.to_datetime(telemetry["timestamp"])
    telemetry["date"] = telemetry["timestamp"].dt.floor("D")
    telemetry["power_kw"] = telemetry["pump_current"] * telemetry["pump_speed_rpm"] / 1000.0

    telemetry_daily = telemetry.groupby(["well_id", "date"], as_index=False).agg(
        pressure=("pressure_out", "mean"),
        temperature=("temperature", "mean"),
        pump_power_kw=("power_kw", "mean"),
        pump_runtime_hours=("timestamp", "count"),
    )

    production_daily = df_production.copy()
    production_daily["date"] = pd.to_datetime(production_daily["date"])
    production_daily["prod_runtime_hours"] = (24 - production_daily["downtime_hours"]).clip(0, 24)
    production_daily["prod_power_kw"] = production_daily["energy_kwh"] / 24.0
    production_daily = production_daily.rename(
        columns={"pressure": "prod_pressure", "temperature": "prod_temperature"}
    )
    production_daily = production_daily[
        [
            "well_id",
            "date",
            "prod_pressure",
            "prod_temperature",
            "prod_power_kw",
            "prod_runtime_hours",
        ]
    ]

    dataset = targets.merge(telemetry_daily, on=["well_id", "date"], how="left")
    dataset = dataset.merge(production_daily, on=["well_id", "date"], how="left")

    # Primary source is telemetry aggregation, fallback to production-derived values.
    dataset["pressure"] = dataset["pressure"].fillna(dataset["prod_pressure"])
    dataset["temperature"] = dataset["temperature"].fillna(dataset["prod_temperature"])
    dataset["pump_power_kw"] = dataset["pump_power_kw"].fillna(dataset["prod_power_kw"])
    dataset["pump_runtime_hours"] = dataset["pump_runtime_hours"].fillna(dataset["prod_runtime_hours"])

    for column in ["pressure", "temperature", "pump_power_kw", "pump_runtime_hours"]:
        dataset[column] = dataset.groupby("well_id")[column].transform(
            lambda s: s.fillna(s.median())
        )
        dataset[column] = dataset[column].fillna(dataset[column].median())

    return dataset[
        ["well_id", "date", "target_oil_ton", "pressure", "temperature", "pump_power_kw", "pump_runtime_hours"]
    ].dropna(subset=["target_oil_ton"])


def train_and_score_models(
    dataset: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    data = dataset.sort_values("date").copy()
    feature_cols = ["pressure", "temperature", "pump_power_kw", "pump_runtime_hours"]
    min_rows = 12
    if len(data) < min_rows:
        empty_preds = pd.DataFrame(
            columns=["model", "well_id", "date", "actual_oil_ton", "predicted_oil_ton", "abs_error", "sq_error"]
        )
        empty_err = pd.DataFrame(columns=["model", "date", "mae_day", "rmse_day"])
        metrics = pd.DataFrame(
            [
                {"model": "LinearRegression", "mae": np.nan, "rmse": np.nan, "r2": np.nan, "rows_used": len(data)},
                {"model": "RandomForestRegressor", "mae": np.nan, "rmse": np.nan, "r2": np.nan, "rows_used": len(data)},
            ]
        )
        return metrics, empty_preds, empty_err

    x = data[feature_cols]
    y = data["target_oil_ton"]
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.25, random_state=42
    )

    models = {
        "LinearRegression": LinearRegression(),
        "RandomForestRegressor": RandomForestRegressor(n_estimators=300, random_state=42),
    }

    metrics_rows: list[dict] = []
    preds_frames: list[pd.DataFrame] = []

    for model_name, model in models.items():
        model.fit(x_train, y_train)
        test_preds = model.predict(x_test)
        rmse = float(np.sqrt(mean_squared_error(y_test, test_preds)))
        mae = float(mean_absolute_error(y_test, test_preds))
        r2 = float(r2_score(y_test, test_preds))

        metrics_rows.append(
            {"model": model_name, "mae": mae, "rmse": rmse, "r2": r2, "rows_used": len(data)}
        )

        full_preds = model.predict(x)
        pred_df = data[["well_id", "date", "target_oil_ton"]].copy()
        pred_df["model"] = model_name
        pred_df["predicted_oil_ton"] = full_preds
        pred_df["actual_oil_ton"] = pred_df["target_oil_ton"]
        pred_df["abs_error"] = (pred_df["actual_oil_ton"] - pred_df["predicted_oil_ton"]).abs()
        pred_df["sq_error"] = (pred_df["actual_oil_ton"] - pred_df["predicted_oil_ton"]) ** 2
        preds_frames.append(
            pred_df[["model", "well_id", "date", "actual_oil_ton", "predicted_oil_ton", "abs_error", "sq_error"]]
        )

    preds_all = pd.concat(preds_frames, ignore_index=True)
    error_over_time = (
        preds_all.groupby(["model", "date"], as_index=False)
        .agg(mae_day=("abs_error", "mean"), mse_day=("sq_error", "mean"))
    )
    error_over_time["rmse_day"] = np.sqrt(error_over_time["mse_day"])
    error_over_time = error_over_time.drop(columns=["mse_day"])

    return pd.DataFrame(metrics_rows), preds_all, error_over_time


def write_partitioned_parquet(
    df: pd.DataFrame,
    s3_base_prefix: str,
    partition_cols: list[str],
    fs: pafs.S3FileSystem,
) -> None:
    table = pa.Table.from_pandas(df, preserve_index=False)
    ds.write_dataset(
        data=table,
        base_dir=s3_base_prefix,
        format="parquet",
        partitioning=partition_cols,
        existing_data_behavior="overwrite_or_ignore",
        filesystem=fs,
    )


def upload_csv(df: pd.DataFrame, s3_client, bucket: str, key: str) -> None:
    buffer = io.StringIO()
    df.to_csv(buffer, index=False)
    s3_client.put_object(Bucket=bucket, Key=key, Body=buffer.getvalue().encode("utf-8"))


def ensure_task3_tables(engine) -> None:
    with engine.begin() as conn:
        has_pumps = conn.exec_driver_sql("SELECT to_regclass('public.pumps')").scalar()
        has_sensors = conn.exec_driver_sql("SELECT to_regclass('public.pump_sensors')").scalar()
        has_failures = conn.exec_driver_sql("SELECT to_regclass('public.pump_failures')").scalar()

        if has_pumps and has_sensors and has_failures:
            return

        base = Path("/app/Files/Файлы к ML")
        ddl_path = base / "task3ddl (1).sql"
        data_path = base / "task3 (1).sql"
        for sql_path in [ddl_path, data_path]:
            sql_text = sql_path.read_text(encoding="utf-8")
            statements = [stmt.strip() for stmt in sql_text.split(";") if stmt.strip()]
            for statement in statements:
                conn.exec_driver_sql(statement)


def ensure_task4_tables(engine) -> None:
    with engine.begin() as conn:
        has_deliveries = conn.exec_driver_sql("SELECT to_regclass('public.deliveries')").scalar()
        has_drivers = conn.exec_driver_sql("SELECT to_regclass('public.drivers')").scalar()
        has_vehicles = conn.exec_driver_sql("SELECT to_regclass('public.vehicles')").scalar()

        if has_deliveries and has_drivers and has_vehicles:
            return

        base = Path("/app/Files/Файлы к ML")
        ddl_path = base / "tak4ddl (1).sql"
        data_path = base / "task4 (1).sql"
        for sql_path in [ddl_path, data_path]:
            sql_text = sql_path.read_text(encoding="utf-8")
            statements = [stmt.strip() for stmt in sql_text.split(";") if stmt.strip()]
            for statement in statements:
                conn.exec_driver_sql(statement)


def build_logistics_marts(
    df_deliveries: pd.DataFrame, df_drivers: pd.DataFrame, df_vehicles: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    deliveries = df_deliveries.copy()
    drivers = df_drivers.copy()
    vehicles = df_vehicles.copy()

    deliveries["date"] = pd.to_datetime(deliveries["date"])
    numeric_cols = ["volume_ton", "cost_usd", "delay_hours", "distance_km"]
    for col in numeric_cols:
        deliveries[col] = pd.to_numeric(deliveries[col], errors="coerce")
    vehicles["capacity_ton"] = pd.to_numeric(vehicles["capacity_ton"], errors="coerce")

    deliveries = deliveries.merge(
        drivers[["driver_id", "name", "experience_years", "region"]],
        on="driver_id",
        how="left",
    ).rename(columns={"name": "driver_name", "region": "driver_region"})
    deliveries = deliveries.merge(
        vehicles[["vehicle_id", "capacity_ton", "fuel_type"]],
        on="vehicle_id",
        how="left",
    )

    deliveries["route"] = deliveries["source"] + " -> " + deliveries["destination"]
    deliveries["delay_flag"] = (deliveries["delay_hours"] > 0).astype(int)
    deliveries["cost_per_km"] = deliveries["cost_usd"] / deliveries["distance_km"].replace(0, np.nan)
    deliveries["load_factor"] = deliveries["volume_ton"] / deliveries["capacity_ton"].replace(0, np.nan)
    deliveries["load_factor"] = deliveries["load_factor"].clip(lower=0)
    deliveries["distance_bucket"] = pd.cut(
        deliveries["distance_km"],
        bins=[0, 120, 160, 200, np.inf],
        labels=["short", "medium", "long", "very_long"],
        include_lowest=True,
    )

    delay_vs_weather = (
        deliveries.groupby("weather_conditions", as_index=False)
        .agg(
            trips=("delivery_id", "count"),
            avg_delay_hours=("delay_hours", "mean"),
            delay_rate_pct=("delay_flag", lambda s: float(s.mean() * 100)),
            avg_distance_km=("distance_km", "mean"),
        )
        .sort_values("avg_delay_hours", ascending=False)
    )

    cost_vs_distance = deliveries[
        [
            "delivery_id",
            "date",
            "route",
            "source",
            "destination",
            "driver_name",
            "weather_conditions",
            "distance_km",
            "volume_ton",
            "cost_usd",
            "cost_per_km",
            "delay_hours",
        ]
    ].copy()

    driver_kpi = (
        deliveries.groupby(
            ["driver_id", "driver_name", "experience_years", "driver_region"], as_index=False
        )
        .agg(
            trips=("delivery_id", "count"),
            total_volume_ton=("volume_ton", "sum"),
            total_cost_usd=("cost_usd", "sum"),
            avg_delay_hours=("delay_hours", "mean"),
            delay_rate_pct=("delay_flag", lambda s: float(s.mean() * 100)),
            avg_cost_per_km=("cost_per_km", "mean"),
            avg_distance_km=("distance_km", "mean"),
            avg_load_factor=("load_factor", "mean"),
        )
        .sort_values(["delay_rate_pct", "avg_delay_hours"])
    )

    factor_weather = (
        deliveries.groupby("weather_conditions", as_index=False)
        .agg(trips=("delivery_id", "count"), avg_delay_hours=("delay_hours", "mean"))
        .rename(columns={"weather_conditions": "factor_value"})
        .assign(factor_type="weather")
    )
    factor_distance = (
        deliveries.groupby("distance_bucket", as_index=False, observed=False)
        .agg(trips=("delivery_id", "count"), avg_delay_hours=("delay_hours", "mean"))
        .rename(columns={"distance_bucket": "factor_value"})
        .assign(factor_type="distance_bucket")
    )
    factor_driver = (
        deliveries.groupby("driver_name", as_index=False)
        .agg(trips=("delivery_id", "count"), avg_delay_hours=("delay_hours", "mean"))
        .rename(columns={"driver_name": "factor_value"})
        .assign(factor_type="driver")
    )
    delay_factors = pd.concat([factor_weather, factor_distance, factor_driver], ignore_index=True)

    route_optimization = (
        deliveries.groupby(["route", "source", "destination"], as_index=False)
        .agg(
            trips=("delivery_id", "count"),
            total_volume_ton=("volume_ton", "sum"),
            avg_distance_km=("distance_km", "mean"),
            avg_delay_hours=("delay_hours", "mean"),
            delay_rate_pct=("delay_flag", lambda s: float(s.mean() * 100)),
            avg_cost_per_km=("cost_per_km", "mean"),
        )
        .sort_values(["delay_rate_pct", "avg_cost_per_km"], ascending=False)
    )
    delay_norm = route_optimization["avg_delay_hours"].rank(pct=True)
    cost_norm = route_optimization["avg_cost_per_km"].rank(pct=True)
    route_optimization["route_risk_score"] = ((0.6 * delay_norm + 0.4 * cost_norm) * 100).round(1)
    route_optimization["priority"] = pd.cut(
        route_optimization["route_risk_score"],
        bins=[-0.1, 33, 66, 100],
        labels=["low", "medium", "high"],
    )
    route_optimization["recommended_action"] = np.where(
        route_optimization["priority"] == "high",
        "replan immediately",
        np.where(route_optimization["priority"] == "medium", "monitor and optimize", "keep current"),
    )

    return (
        delay_vs_weather,
        cost_vs_distance,
        driver_kpi,
        delay_factors,
        route_optimization,
    )


def detect_pump_anomalies(df_sensors: pd.DataFrame) -> pd.DataFrame:
    sensors = df_sensors.copy()
    sensors["timestamp"] = pd.to_datetime(sensors["timestamp"])
    features = ["temperature", "vibration", "current", "rpm"]
    for col in features:
        sensors[col] = pd.to_numeric(sensors[col], errors="coerce")

    clean = sensors.dropna(subset=features).copy()

    for col in features:
        mean = clean[col].mean()
        std = clean[col].std(ddof=0)
        if std == 0 or np.isnan(std):
            clean[f"z_{col}"] = 0.0
        else:
            clean[f"z_{col}"] = (clean[col] - mean) / std

    clean["max_abs_zscore"] = clean[[f"z_{c}" for c in features]].abs().max(axis=1)
    clean["is_anomaly_zscore"] = clean["max_abs_zscore"] > 3

    iso = IsolationForest(contamination=0.1, random_state=42)
    iso.fit(clean[features])
    clean["iforest_pred"] = iso.predict(clean[features])
    clean["iforest_score"] = -iso.score_samples(clean[features])
    clean["is_anomaly_iforest"] = clean["iforest_pred"] == -1

    clean["is_anomaly"] = clean["is_anomaly_zscore"] | clean["is_anomaly_iforest"]
    clean["anomaly_flag"] = clean["is_anomaly"].astype(int)
    clean["anomaly_iforest_flag"] = clean["is_anomaly_iforest"].astype(int)
    clean["anomaly_zscore_flag"] = clean["is_anomaly_zscore"].astype(int)
    return clean[
        [
            "record_id",
            "pump_id",
            "timestamp",
            "temperature",
            "vibration",
            "current",
            "rpm",
            "pressure",
            "max_abs_zscore",
            "iforest_score",
            "is_anomaly_zscore",
            "is_anomaly_iforest",
            "is_anomaly",
            "anomaly_zscore_flag",
            "anomaly_iforest_flag",
            "anomaly_flag",
        ]
    ].sort_values(["timestamp", "pump_id"])


def build_pre_failure_features(
    df_sensors: pd.DataFrame, df_failures: pd.DataFrame, horizon_hours: int = 24
) -> pd.DataFrame:
    sensors = df_sensors.copy()
    failures = df_failures.copy()
    sensors["timestamp"] = pd.to_datetime(sensors["timestamp"])
    failures["failure_date"] = pd.to_datetime(failures["failure_date"])

    rows: list[pd.DataFrame] = []
    for _, failure in failures.iterrows():
        pump_id = int(failure["pump_id"])
        failure_ts = failure["failure_date"]
        window_start = failure_ts - pd.Timedelta(hours=horizon_hours)
        subset = sensors[
            (sensors["pump_id"] == pump_id)
            & (sensors["timestamp"] >= window_start)
            & (sensors["timestamp"] <= failure_ts)
        ].copy()
        if subset.empty:
            continue
        subset["failure_id"] = int(failure["failure_id"])
        subset["failure_type"] = failure["failure_type"]
        subset["failure_date"] = failure_ts
        subset["hours_before_failure"] = (
            (failure_ts - subset["timestamp"]).dt.total_seconds() / 3600.0
        )
        rows.append(subset)

    if not rows:
        return pd.DataFrame(
            columns=[
                "failure_id",
                "pump_id",
                "failure_type",
                "timestamp",
                "hours_before_failure",
                "temperature",
                "vibration",
                "current",
                "rpm",
                "pressure",
            ]
        )

    out = pd.concat(rows, ignore_index=True)
    return out[
        [
            "failure_id",
            "pump_id",
            "failure_type",
            "timestamp",
            "hours_before_failure",
            "temperature",
            "vibration",
            "current",
            "rpm",
            "pressure",
        ]
    ].sort_values(["failure_id", "timestamp"])


def build_failure_probability(
    df_sensors: pd.DataFrame, df_failures: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    sensors = df_sensors.copy()
    failures = df_failures.copy()
    sensors["timestamp"] = pd.to_datetime(sensors["timestamp"])
    failures["failure_date"] = pd.to_datetime(failures["failure_date"])

    feature_cols = ["temperature", "vibration", "current", "rpm", "pressure"]
    for col in feature_cols:
        sensors[col] = pd.to_numeric(sensors[col], errors="coerce")
    sensors = sensors.dropna(subset=feature_cols).copy()

    sensors["hours_to_failure"] = np.inf
    sensors["will_fail_24h"] = 0

    for _, failure in failures.iterrows():
        pump_mask = sensors["pump_id"] == int(failure["pump_id"])
        delta_h = (
            failure["failure_date"] - sensors.loc[pump_mask, "timestamp"]
        ).dt.total_seconds() / 3600.0
        valid_h = delta_h.where(delta_h >= 0, np.inf)
        sensors.loc[pump_mask, "hours_to_failure"] = np.minimum(
            sensors.loc[pump_mask, "hours_to_failure"], valid_h
        )

    sensors["will_fail_24h"] = (sensors["hours_to_failure"] <= 24).astype(int)
    class_count = sensors["will_fail_24h"].nunique()

    if class_count < 2 or len(sensors) < 20:
        latest = sensors.sort_values("timestamp").groupby("pump_id", as_index=False).tail(1).copy()
        risk_raw = (
            latest["vibration"].rank(pct=True)
            + latest["temperature"].rank(pct=True)
            + latest["current"].rank(pct=True)
        ) / 3.0
        latest["risk_probability"] = risk_raw
        latest["risk_score"] = (latest["risk_probability"] * 100).round(1)
        latest["risk_level"] = pd.cut(
            latest["risk_score"],
            bins=[-0.1, 33, 66, 100],
            labels=["low", "medium", "high"],
        )
        metrics = pd.DataFrame(
            [
                {
                    "model": "heuristic_risk",
                    "mae": np.nan,
                    "rmse": np.nan,
                    "r2": np.nan,
                    "rows_used": len(sensors),
                }
            ]
        )
        return (
            latest[
                [
                    "pump_id",
                    "timestamp",
                    "temperature",
                    "vibration",
                    "current",
                    "rpm",
                    "pressure",
                    "risk_probability",
                    "risk_score",
                    "risk_level",
                ]
            ],
            metrics,
        )

    x = sensors[feature_cols]
    y = sensors["will_fail_24h"]
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.25, random_state=42, stratify=y
    )

    clf = RandomForestClassifier(
        n_estimators=300, random_state=42, class_weight="balanced"
    )
    clf.fit(x_train, y_train)
    preds = clf.predict_proba(x_test)[:, 1]
    rmse = float(np.sqrt(mean_squared_error(y_test, preds)))
    mae = float(mean_absolute_error(y_test, preds))

    latest = sensors.sort_values("timestamp").groupby("pump_id", as_index=False).tail(1).copy()
    latest["risk_probability"] = clf.predict_proba(latest[feature_cols])[:, 1]
    latest["risk_score"] = (latest["risk_probability"] * 100).round(1)
    latest["risk_level"] = pd.cut(
        latest["risk_score"],
        bins=[-0.1, 33, 66, 100],
        labels=["low", "medium", "high"],
    )

    metrics = pd.DataFrame(
        [
            {
                "model": "RandomForestClassifier",
                "mae": mae,
                "rmse": rmse,
                "r2": np.nan,
                "rows_used": len(sensors),
            }
        ]
    )
    return (
        latest[
            [
                "pump_id",
                "timestamp",
                "temperature",
                "vibration",
                "current",
                "rpm",
                "pressure",
                "risk_probability",
                "risk_score",
                "risk_level",
            ]
        ],
        metrics,
    )


def main() -> None:
    cfg = Settings()
    engine = create_engine(cfg.postgres_uri)
    ensure_task3_tables(engine)
    ensure_task4_tables(engine)

    df_wells = pd.read_sql("SELECT * FROM wells", engine)
    df_prod = pd.read_sql("SELECT * FROM production", engine)
    df_telemetry = pd.read_sql('SELECT * FROM telemetry ORDER BY "timestamp"', engine)
    df_targets = pd.read_sql("SELECT * FROM well_targets", engine)
    df_pump_sensors = pd.read_sql("SELECT * FROM pump_sensors ORDER BY timestamp", engine)
    df_pump_failures = pd.read_sql("SELECT * FROM pump_failures ORDER BY failure_date", engine)
    df_deliveries = pd.read_sql("SELECT * FROM deliveries ORDER BY date", engine)
    df_drivers = pd.read_sql("SELECT * FROM drivers", engine)
    df_vehicles = pd.read_sql("SELECT * FROM vehicles", engine)

    df_prod_clean = clean_production(df_prod)
    df_features = build_feature_table(df_prod_clean, df_telemetry)
    daily_prod, well_kpi = build_marts(df_features, df_wells)
    ml_metrics = build_ml_metrics(df_features)
    target_dataset = build_target_training_dataset(df_targets, df_telemetry, df_prod)
    target_ml_metrics, actual_vs_pred, error_over_time = train_and_score_models(target_dataset)
    pump_anomalies = detect_pump_anomalies(df_pump_sensors)
    pre_failure = build_pre_failure_features(df_pump_sensors, df_pump_failures)
    pump_risk, pump_risk_metrics = build_failure_probability(df_pump_sensors, df_pump_failures)
    (
        delay_vs_weather,
        cost_vs_distance,
        driver_kpi,
        delay_factors,
        route_optimization,
    ) = build_logistics_marts(df_deliveries, df_drivers, df_vehicles)

    corr_temp_oil = float(df_features[["avg_temperature", "oil_ton"]].corr().iloc[0, 1])
    corr_pressure_oil = float(df_features[["avg_pressure", "oil_ton"]].corr().iloc[0, 1])
    influence = pd.DataFrame(
        [
            {"factor": "avg_temperature", "corr_with_oil_ton": corr_temp_oil},
            {"factor": "avg_pressure", "corr_with_oil_ton": corr_pressure_oil},
        ]
    )

    best_worst = pd.concat(
        [
            well_kpi.head(3).assign(segment="best"),
            well_kpi.tail(3).assign(segment="worst"),
        ],
        ignore_index=True,
    )

    s3_client = boto3.client(
        "s3",
        endpoint_url=f"http://{cfg.minio_endpoint}",
        aws_access_key_id=cfg.minio_access_key,
        aws_secret_access_key=cfg.minio_secret_key,
    )

    s3fs = pafs.S3FileSystem(
        access_key=cfg.minio_access_key,
        secret_key=cfg.minio_secret_key,
        endpoint_override=cfg.minio_endpoint,
        scheme="http",
        region="us-east-1",
    )

    df_features["year"] = df_features["date"].dt.year
    df_features["month"] = df_features["date"].dt.month
    daily_prod["year"] = pd.to_datetime(daily_prod["date"]).dt.year
    daily_prod["month"] = pd.to_datetime(daily_prod["date"]).dt.month

    write_partitioned_parquet(
        df_features,
        f"{cfg.minio_bucket}/processed/features",
        ["year", "month"],
        s3fs,
    )
    write_partitioned_parquet(
        daily_prod,
        f"{cfg.minio_bucket}/marts/daily_production",
        ["year", "month"],
        s3fs,
    )

    upload_csv(well_kpi, s3_client, cfg.minio_bucket, "marts/well_kpi.csv")
    upload_csv(best_worst, s3_client, cfg.minio_bucket, "marts/best_worst_wells.csv")
    upload_csv(influence, s3_client, cfg.minio_bucket, "marts/influence_factors.csv")
    upload_csv(ml_metrics, s3_client, cfg.minio_bucket, "ml/ml_metrics.csv")
    upload_csv(target_dataset, s3_client, cfg.minio_bucket, "ml/well_targets_features.csv")
    upload_csv(target_ml_metrics, s3_client, cfg.minio_bucket, "ml/target_model_metrics.csv")
    upload_csv(actual_vs_pred, s3_client, cfg.minio_bucket, "ml/actual_vs_predicted.csv")
    upload_csv(error_over_time, s3_client, cfg.minio_bucket, "ml/model_error_over_time.csv")
    upload_csv(pump_anomalies, s3_client, cfg.minio_bucket, "ml/pump_anomalies.csv")
    upload_csv(pre_failure, s3_client, cfg.minio_bucket, "ml/pre_failure_signals.csv")
    upload_csv(pump_risk, s3_client, cfg.minio_bucket, "ml/pump_risk_scores.csv")
    upload_csv(pump_risk_metrics, s3_client, cfg.minio_bucket, "ml/pump_risk_model_metrics.csv")
    upload_csv(delay_vs_weather, s3_client, cfg.minio_bucket, "marts/delay_vs_weather.csv")
    upload_csv(cost_vs_distance, s3_client, cfg.minio_bucket, "marts/cost_vs_distance.csv")
    upload_csv(driver_kpi, s3_client, cfg.minio_bucket, "marts/driver_kpi.csv")
    upload_csv(delay_factors, s3_client, cfg.minio_bucket, "marts/delay_factors.csv")
    upload_csv(route_optimization, s3_client, cfg.minio_bucket, "marts/route_optimization.csv")

    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS mart")

    daily_prod.to_sql("daily_production", engine, schema="mart", if_exists="replace", index=False)
    well_kpi.to_sql("well_kpi", engine, schema="mart", if_exists="replace", index=False)
    best_worst.to_sql("best_worst_wells", engine, schema="mart", if_exists="replace", index=False)
    influence.to_sql("influence_factors", engine, schema="mart", if_exists="replace", index=False)
    ml_metrics.to_sql("ml_metrics", engine, schema="mart", if_exists="replace", index=False)
    target_dataset.to_sql("well_targets_features", engine, schema="mart", if_exists="replace", index=False)
    target_ml_metrics.to_sql("target_model_metrics", engine, schema="mart", if_exists="replace", index=False)
    actual_vs_pred.to_sql("actual_vs_predicted", engine, schema="mart", if_exists="replace", index=False)
    error_over_time.to_sql("model_error_over_time", engine, schema="mart", if_exists="replace", index=False)
    pump_anomalies.to_sql("pump_anomalies", engine, schema="mart", if_exists="replace", index=False)
    pre_failure.to_sql("pre_failure_signals", engine, schema="mart", if_exists="replace", index=False)
    pump_risk.to_sql("pump_risk_scores", engine, schema="mart", if_exists="replace", index=False)
    pump_risk_metrics.to_sql("pump_risk_model_metrics", engine, schema="mart", if_exists="replace", index=False)
    delay_vs_weather.to_sql("delay_vs_weather", engine, schema="mart", if_exists="replace", index=False)
    cost_vs_distance.to_sql("cost_vs_distance", engine, schema="mart", if_exists="replace", index=False)
    driver_kpi.to_sql("driver_kpi", engine, schema="mart", if_exists="replace", index=False)
    delay_factors.to_sql("delay_factors", engine, schema="mart", if_exists="replace", index=False)
    route_optimization.to_sql("route_optimization", engine, schema="mart", if_exists="replace", index=False)

    print("Pipeline completed successfully.")


if __name__ == "__main__":
    main()
