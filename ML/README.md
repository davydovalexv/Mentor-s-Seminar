## Тема проекта
Учебный data pipeline для аналитики нефтедобычи:

`PostgreSQL -> ETL/ELT -> MinIO -> Jupyter (EDA/ML) -> витрины -> Superset`

## Цель
Показать полный цикл работы с данными:

- загрузка и хранение исходных таблиц;
- очистка и преобразование данных;
- подготовка витрин для BI;
- базовое ML-моделирование;
- визуализация результатов.

## Используемый стек

- Docker / Docker Compose
- PostgreSQL
- MinIO (S3-совместимое хранилище)
- Jupyter (pandas, scikit-learn)
- Apache Superset

## Что реализовано

### 1) Инфраструктура и интеграция сервисов

- все сервисы поднимаются через `docker-compose.yml`;
- источники SQL загружаются в PostgreSQL автоматически;
- pipeline запускается из Jupyter-контейнера;
- результаты пишутся в PostgreSQL (`mart` schema) и MinIO.

### 2) ETL/ELT и подготовка данных

- обработка `NULL`;
- фильтрация выбросов (IQR);
- агрегации по дням и по скважинам;
- feature engineering (`avg_pressure`, `avg_temperature`, `downtime_coef` и др.);
- partitioning Parquet в MinIO (`year/month`).

### 3) Практические задания

- **Задание 1. Аналитика добычи**
  - витрины: `daily_production`, `well_kpi`, `best_worst_wells`, `influence_factors`.
- **Задание 2. Прогноз дебита (ML)**
  - модели: `LinearRegression`, `RandomForestRegressor`;
  - метрики: `MAE`, `RMSE` (+ `R2`);
  - витрины: `actual_vs_predicted`, `model_error_over_time`.
- **Задание 3. Аномалии и отказы оборудования**
  - аномалии: `z-score`, `IsolationForest`;
  - признаки перед отказом: окно 24 часа;
  - риск отказа: `RandomForestClassifier`;
  - витрины: `pump_anomalies`, `pre_failure_signals`, `pump_risk_scores`.
- **Задание 4. Логистика и поставки**
  - анализ задержек: погода, расстояние, водитель;
  - расчет `cost_per_km`;
  - приоритизация маршрутов (`route_optimization`).

й запуск

После запуска доступны:

- Superset: `http://localhost:8088` (`admin/admin`)
- Jupyter: `http://localhost:8888` (`ml-token`)
- MinIO Console: `http://localhost:9001` (`minioadmin/minioadmin`)

