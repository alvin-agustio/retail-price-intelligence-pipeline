from unittest.mock import MagicMock
import pandas as pd
import load_warehouse


def test_load_warehouse_idempotency(monkeypatch):
    # Mock arguments
    monkeypatch.setattr(
        "sys.argv",
        [
            "load_warehouse.py",
            "--source",
            "test_src",
            "--category",
            "test_cat",
            "--run-id",
            "test_run_123",
        ],
    )

    # Mock MinIO Client and Parquet Data
    mock_client = MagicMock()
    monkeypatch.setattr("bronze.get_client", lambda: mock_client)

    # Create fake parquet bytes
    import io

    fake_df = pd.DataFrame({"col1": [1, 2]})
    parquet_bytes = io.BytesIO()
    fake_df.to_parquet(parquet_bytes)
    parquet_bytes.seek(0)

    class FakeResponse:
        def read(self):
            return parquet_bytes.getvalue()

    mock_client.get_object.return_value = FakeResponse()

    # Mock SQLAlchemy Engine and Connection
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.begin.return_value.__enter__.return_value = mock_conn
    monkeypatch.setattr("load_warehouse.create_engine", lambda *args, **kwargs: mock_engine)

    # Mock inspect
    mock_inspect = MagicMock()
    mock_inspect.return_value.has_table.return_value = True
    monkeypatch.setattr("load_warehouse.inspect", mock_inspect)

    # Mock Pandas to_sql to track if it's called
    to_sql_called = False

    def fake_to_sql(self, *args, **kwargs):
        nonlocal to_sql_called
        to_sql_called = True

    monkeypatch.setattr(pd.DataFrame, "to_sql", fake_to_sql)

    # Run the loader
    load_warehouse.main()

    # Verify idempotency DELETE query was executed
    delete_called = False
    for call in mock_conn.execute.call_args_list:
        query = str(call[0][0])
        if "DELETE FROM landing.observations WHERE run_id = :run_id" in query:
            assert call[0][1] == {"run_id": "test_run_123"}
            delete_called = True

    assert delete_called, "Idempotency DELETE query was not executed!"
    assert to_sql_called, "Data was not loaded via to_sql!"
