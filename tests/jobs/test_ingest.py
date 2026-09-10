import pytest
from unittest.mock import MagicMock
from retail_pipeline.jobs.ingest import main


def test_electronic_city_routing(monkeypatch):
    """Test Electronic City API query uses search_query."""
    monkeypatch.setattr(
        "sys.argv",
        ["run_ingestion.py", "--source", "electronic_city", "--category", "tablet", "--limit", "1"],
    )

    mock_client = MagicMock()
    monkeypatch.setattr("retail_pipeline.storage.bronze.get_client", lambda: mock_client)
    monkeypatch.setattr("retail_pipeline.storage.bronze.ensure_bucket", MagicMock())
    monkeypatch.setattr("retail_pipeline.storage.bronze.save_manifest", MagicMock())

    mock_discover = MagicMock(return_value=[])
    monkeypatch.setattr("retail_pipeline.discovery.discover_electronic_city_product_urls", mock_discover)
    with pytest.raises(SystemExit):
        main()
    mock_discover.assert_called_once()
    assert mock_discover.call_args[1]["query"] == "tablet"


def test_digimap_routing(monkeypatch):
    """Test Digimap shopify_sitemap falls back to category_listing."""
    monkeypatch.setattr(
        "sys.argv",
        ["run_ingestion.py", "--source", "digimap", "--category", "tablet", "--limit", "1"],
    )

    mock_client = MagicMock()
    monkeypatch.setattr("retail_pipeline.storage.bronze.get_client", lambda: mock_client)
    monkeypatch.setattr("retail_pipeline.storage.bronze.ensure_bucket", MagicMock())
    monkeypatch.setattr("retail_pipeline.storage.bronze.save_manifest", MagicMock())

    mock_discover = MagicMock(return_value=[])
    monkeypatch.setattr("retail_pipeline.discovery.discover_product_urls", mock_discover)
    monkeypatch.setattr("retail_pipeline.discovery.fetch_html", MagicMock(return_value="<html></html>"))
    with pytest.raises(SystemExit):
        main()
    mock_discover.assert_called_once()
    assert mock_discover.call_args[0][0] == "digimap"


def test_manifest_on_discovery_failure(monkeypatch):
    """Test that a manifest is created even if discovery fails entirely."""
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_ingestion.py",
            "--source",
            "erablue",
            "--category",
            "smartphone",
            "--limit",
            "1",
            "--delay",
            "0",
        ],
    )

    mock_client = MagicMock()
    monkeypatch.setattr("retail_pipeline.storage.bronze.get_client", lambda: mock_client)
    monkeypatch.setattr("retail_pipeline.storage.bronze.ensure_bucket", MagicMock())

    mock_save_manifest = MagicMock()
    monkeypatch.setattr("retail_pipeline.storage.bronze.save_manifest", mock_save_manifest)

    # Force discovery to fail
    monkeypatch.setattr(
        "retail_pipeline.discovery.discover_product_urls", MagicMock(side_effect=Exception("Network down"))
    )
    monkeypatch.setattr("retail_pipeline.discovery.fetch_html", MagicMock(return_value="<html></html>"))

    with pytest.raises(SystemExit) as e:
        main()
    assert e.value.code == 1

    mock_save_manifest.assert_called_once()
    manifest_summary = mock_save_manifest.call_args[0][5]

    assert manifest_summary["discovered"] == 0
    assert manifest_summary["status"] == "DISCOVERY_FAILED"
    assert manifest_summary["error"] == "Network down"


def test_manifest_and_rejected(monkeypatch):
    """Test manifest contains detailed records and handles parsing failures."""
    monkeypatch.setattr(
        "sys.argv",
        ["run_ingestion.py", "--source", "erablue", "--category", "smartphone", "--limit", "1"],
    )

    mock_client = MagicMock()
    monkeypatch.setattr("retail_pipeline.storage.bronze.get_client", lambda: mock_client)
    monkeypatch.setattr("retail_pipeline.storage.bronze.ensure_bucket", MagicMock())

    monkeypatch.setattr("retail_pipeline.storage.bronze.save_rejected", MagicMock(return_value="rejected/key.json"))
    monkeypatch.setattr("retail_pipeline.storage.bronze.save_raw_response", MagicMock(return_value="raw/key.html"))

    mock_save_manifest = MagicMock()
    monkeypatch.setattr("retail_pipeline.storage.bronze.save_manifest", mock_save_manifest)

    monkeypatch.setattr(
        "retail_pipeline.discovery.discover_product_urls", MagicMock(return_value=["http://test.com"])
    )
    monkeypatch.setattr("retail_pipeline.discovery.fetch_html", MagicMock(return_value="<html></html>"))
    monkeypatch.setattr(
        "retail_pipeline.discovery.parse_product_html", MagicMock(side_effect=ValueError("Parse failed"))
    )

    with pytest.raises(SystemExit) as e:
        main()
    assert e.value.code == 1

    mock_save_manifest.assert_called_once()
    manifest_summary = mock_save_manifest.call_args[0][5]
    assert manifest_summary["failed"] == 1


def test_ingestion_succeeds_for_one_valid_product(monkeypatch):
    """One valid product must create a successful manifest without exiting."""
    from datetime import datetime, timezone
    from decimal import Decimal
    from retail_pipeline.discovery import RawProductObservation

    monkeypatch.setattr(
        "sys.argv",
        ["run_ingestion.py", "--source", "erablue", "--category", "smartphone", "--limit", "1"],
    )
    mock_client = MagicMock()
    mock_manifest = MagicMock()
    monkeypatch.setattr("retail_pipeline.storage.bronze.get_client", lambda: mock_client)
    monkeypatch.setattr("retail_pipeline.storage.bronze.ensure_bucket", MagicMock())
    monkeypatch.setattr("retail_pipeline.storage.bronze.save_raw_response", MagicMock(return_value="raw/product.html"))
    monkeypatch.setattr("retail_pipeline.storage.bronze.save_manifest", mock_manifest)
    monkeypatch.setattr("retail_pipeline.discovery.discover_product_urls", MagicMock(return_value=["https://x.test/p"]))
    monkeypatch.setattr("retail_pipeline.discovery.fetch_html", MagicMock(return_value="<html>product</html>"))

    def parse_valid(source_id, source_url, html, observed_at_utc):
        assert source_id == "erablue"
        assert source_url == "https://x.test/p"
        assert observed_at_utc.tzinfo is not None
        return RawProductObservation(
            source_id=source_id,
            source_url=source_url,
            product_name_raw="Valid Phone",
            current_price_idr=Decimal("1000000"),
            observed_at_utc=datetime.now(timezone.utc),
        )

    monkeypatch.setattr("retail_pipeline.discovery.parse_product_html", parse_valid)

    main()

    summary = mock_manifest.call_args[0][5]
    assert summary["status"] == "COMPLETED"
    assert summary["success"] == 1
    assert summary["failed"] == 0
    assert summary["records"][0]["price_present"] is True
