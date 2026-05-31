"""AC verification: spark.sql('select 1') over gRPC succeeds."""
import sys
from pyspark.sql import SparkSession

HOST = sys.argv[1] if len(sys.argv) > 1 else "localhost"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 15002

spark = SparkSession.builder.remote(f"sc://{HOST}:{PORT}").getOrCreate()

result = spark.sql("select 1 as val").collect()
assert result[0]["val"] == 1, f"unexpected result: {result}"

print(f"OK — spark.sql('select 1') returned {result[0]['val']} via sc://{HOST}:{PORT}")
spark.stop()
