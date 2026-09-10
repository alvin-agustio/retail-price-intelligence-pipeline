import json
from unittest.mock import MagicMock
from retail_pipeline.jobs import build_silver


def test_build_silver_injects_correct_category(monkeypatch):
    """Test E2E sederhana: manifest -> raw HTML -> Parse -> Pastikan category_id = 'laptop' (bukan UNSPECIFIED)"""
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_silver.py",
            "--source",
            "test_source",
            "--category",
            "laptop",
            "--run-id",
            "test_run",
        ],
    )

    mock_client = MagicMock()
    monkeypatch.setattr("retail_pipeline.storage.bronze.get_client", lambda: mock_client)

    # Mock return value untuk manifest
    fake_manifest = json.dumps(
        {
            "records": [
                {
                    "raw_object_key": "raw/a.html",
                    "url": "http://test.com",
                    "fetch_time": "2026-09-01T12:00:00Z",
                }
            ]
        }
    ).encode("utf-8")

    # Mock return value untuk HTML
    fake_html = b"<html>dummy</html>"

    # Supaya get_object bisa di-read()
    class FakeResponse:
        def __init__(self, data):
            self.data = data

        def read(self):
            return self.data

    def mock_get_object(bucket, key):
        if "manifest" in key:
            return FakeResponse(fake_manifest)
        return FakeResponse(fake_html)

    mock_client.get_object = mock_get_object

    # Mock Parser agar mereturn observasi valid dengan category_id UNSPECIFIED (mensimulasikan perilaku asli)
    from datetime import datetime, timezone
    from retail_pipeline.discovery import RawProductObservation

    fake_obs = RawProductObservation(
        source_id="test_source",
        category_id="UNSPECIFIED",  # <--- Ini yang jadi masalah sebelumnya
        source_url="http://test.com",
        product_name_raw="Laptop Test",
        current_price_idr=15000000.0,
        observed_at_utc=datetime.now(timezone.utc),
    )
    monkeypatch.setattr("retail_pipeline.discovery.parse_product_html", lambda *args, **kwargs: fake_obs)

    # Tangkap hasil sebelum masuk ke pyarrow (di silver.py)
    captured_records = []
    monkeypatch.setattr(
        "retail_pipeline.storage.silver.write_parquet_to_minio",
        lambda c, b, src, cat, rid, recs: captured_records.extend(recs) or "silver_key",
    )

    # Jalankan program
    build_silver.main()

    # Verifikasi hasilnya
    assert len(captured_records) == 1
    assert captured_records[0]["category_id"] == "laptop", "Category ID bocor sebagai UNSPECIFIED!"
