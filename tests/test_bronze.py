from unittest.mock import MagicMock
import pytest

import bronze
from bronze import save_raw_response
import hashlib


def test_save_raw_response():
    mock_client = MagicMock()
    url = "http://a/b"
    expected_hash = hashlib.md5(url.encode()).hexdigest()
    obj_name = save_raw_response(
        mock_client, "test-bucket", "store", "smartphone", "run1", url, "<html>"
    )
    assert obj_name == f"raw/store/smartphone/run1/{expected_hash}.html"
    mock_client.put_object.assert_called_once()


def test_get_client_requires_minio_credentials(monkeypatch):
    monkeypatch.delenv("MINIO_ACCESS_KEY", raising=False)
    monkeypatch.delenv("MINIO_SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="MINIO_ACCESS_KEY and MINIO_SECRET_KEY"):
        bronze.get_client()
