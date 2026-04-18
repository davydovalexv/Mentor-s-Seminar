from pyspark.sql import SparkSession, functions as F
from pyspark.sql.window import Window
spark = SparkSession.builder.appName("mart_city_top_products").getOrCreate()
users = spark.createDataFrame(
    [("u1", "Berlin"), ("u2", "Berlin"), ("u3", "Munich"), ("u4", "Hamburg")],
    ["user_id", "city"],
)
orders = spark.createDataFrame(
    [
        ("o1", "u1", "p1", 2, 10.0), ("o2", "u1", "p2", 1, 30.0),
        ("o3", "u2", "p1", 1, 10.0), ("o4", "u2", "p3", 5, 7.0),
        ("o5", "u3", "p2", 3, 30.0), ("o6", "u3", "p3", 1, 7.0),
        ("o7", "u4", "p1", 10, 10.0),
    ],
    ["order_id", "user_id", "product_id", "qty", "price"],
)
products = spark.createDataFrame(
    [("p1", "Ring VOLA"), ("p2", "Ring POROG"), ("p3", "Ring TISHINA")],
    ["product_id", "product_name"],
)
enriched = (
    orders.withColumn("revenue", F.col("qty") * F.col("price"))
    .join(users, "user_id", "inner")
    .join(products, "product_id", "inner")
)
agg = enriched.groupBy("city", "product_id", "product_name").agg(
    F.count("order_id").alias("orders_cnt"),
    F.sum("qty").alias("qty_sum"),
    F.sum("revenue").alias("revenue_sum"),
)
w = Window.partitionBy("city").orderBy(F.col("revenue_sum").desc())
mart = (
    agg.withColumn("rn", F.row_number().over(w))
    .where(F.col("rn") <= 2)
    .drop("rn")
)
out = "hdfs:///tmp/sandbox_zeppelin/mart_city_top_products/"
mart.write.mode("overwrite").format("parquet").save(out)
spark.read.parquet(out).orderBy("city", F.col("revenue_sum").desc()).show(truncate=False)
spark.stop()