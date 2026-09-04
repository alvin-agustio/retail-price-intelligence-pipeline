import pytest
import pyarrow as pa
from datetime import datetime, timezone
from silver import SILVER_SCHEMA


def test_silver_schema_validation():
    """Pastikan skema Parquet menolak tipe data yang salah (Schema Enforcement)"""
    valid_record = {
        "source_id": "erablue",
        "category_id": "smartphone",
        "source_product_id": "123",
        "source_url": "http://test.com",
        "product_name_raw": "Item",
        "current_price_idr": 10000.0,
        "original_price_idr": None,
        "availability_status_raw": "in_stock",
        "observed_at_utc": datetime.now(timezone.utc),
        "location_context": "default",
    }

    # 1. Pastikan record yang benar berhasil masuk Parquet
    table = pa.Table.from_pylist([valid_record], schema=SILVER_SCHEMA)
    assert table.num_rows == 1

    # 2. Pastikan record yang kotor (harga berupa teks) ditolak mentah-mentah
    invalid_record = valid_record.copy()
    invalid_record["current_price_idr"] = "sepuluh ribu"

    with pytest.raises(Exception):
        pa.Table.from_pylist([invalid_record], schema=SILVER_SCHEMA)
