import io
import pyarrow as pa
import pyarrow.parquet as pq
from minio import Minio

# [KONTRAK DATA] Skema kaku Gudang Silver. Tolak tipe data yang salah secara otomatis.
SILVER_SCHEMA = pa.schema(
    [
        ("source_id", pa.string()),
        ("category_id", pa.string()),
        ("source_product_id", pa.string()),
        ("source_url", pa.string()),
        ("product_name_raw", pa.string()),
        ("current_price_idr", pa.float64()),  # Harga harus angka presisi
        ("original_price_idr", pa.float64()),
        ("availability_status_raw", pa.string()),
        ("observed_at_utc", pa.timestamp("us", tz="UTC")),
        ("location_context", pa.string()),
    ]
)


def write_parquet_to_minio(
    client: Minio, bucket: str, source: str, category: str, run_id: str, records: list[dict]
) -> str:
    """Mengubah list data menjadi file Parquet padat dan menembakkannya langsung ke MinIO."""
    if not records:
        return ""

    # 1. Konversi ke bentuk Kolumnar (PyArrow Table) sambil menegakkan skema
    table = pa.Table.from_pylist(records, schema=SILVER_SCHEMA)

    # 2. Tulis ke memori sementara (tanpa menyentuh hardisk)
    buffer = io.BytesIO()
    pq.write_table(table, buffer, compression="snappy")
    buffer.seek(0)

    # 3. Struktur Partisi Analitik bergaya Hive (source=X/category=Y)
    object_name = f"silver/observations/source={source}/category={category}/run_id={run_id}.parquet"

    # 4. Tembak ke MinIO
    client.put_object(
        bucket_name=bucket,
        object_name=object_name,
        data=buffer,
        length=buffer.getbuffer().nbytes,
        content_type="application/vnd.apache.parquet",
    )
    return object_name
