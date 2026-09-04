from unittest.mock import MagicMock
from run_ingestion import main


def test_electronic_city_routing(monkeypatch):
    """Test Electronic City API query uses search_query."""
    monkeypatch.setattr(
        "sys.argv",
        ["run_ingestion.py", "--source", "electronic_city", "--category", "tablet", "--limit", "1"],
    )

    mock_client = MagicMock()
    monkeypatch.setattr("bronze.get_client", lambda: mock_client)
    monkeypatch.setattr("bronze.ensure_bucket", MagicMock())
    monkeypatch.setattr("bronze.save_manifest", MagicMock())

    mock_discover = MagicMock(return_value=[])
    monkeypatch.setattr("phase1_poc.discover_electronic_city_product_urls", mock_discover)

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
    monkeypatch.setattr("bronze.get_client", lambda: mock_client)
    monkeypatch.setattr("bronze.ensure_bucket", MagicMock())
    monkeypatch.setattr("bronze.save_manifest", MagicMock())

    mock_discover = MagicMock(return_value=[])
    monkeypatch.setattr("phase1_poc.discover_product_urls", mock_discover)
    monkeypatch.setattr("phase1_poc.fetch_html", MagicMock(return_value="<html></html>"))

    main()

    mock_discover.assert_called_once()
    assert mock_discover.call_args[0][0] == "digimap"


def test_manifest_on_discovery_failure(monkeypatch):
    """Test that a manifest is created even if discovery fails entirely."""
    monkeypatch.setattr(
        "sys.argv",
        ["run_ingestion.py", "--source", "erablue", "--category", "smartphone", "--limit", "1"],
    )

    mock_client = MagicMock()
    monkeypatch.setattr("bronze.get_client", lambda: mock_client)
    monkeypatch.setattr("bronze.ensure_bucket", MagicMock())

    mock_save_manifest = MagicMock()
    monkeypatch.setattr("bronze.save_manifest", mock_save_manifest)

    # Force discovery to fail
    monkeypatch.setattr(
        "phase1_poc.discover_product_urls", MagicMock(side_effect=Exception("Network down"))
    )
    monkeypatch.setattr("phase1_poc.fetch_html", MagicMock(return_value="<html></html>"))

    main()

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
    monkeypatch.setattr("bronze.get_client", lambda: mock_client)
    monkeypatch.setattr("bronze.ensure_bucket", MagicMock())

    monkeypatch.setattr("bronze.save_rejected", MagicMock(return_value="rejected/key.json"))
    monkeypatch.setattr("bronze.save_raw_response", MagicMock(return_value="raw/key.html"))

    mock_save_manifest = MagicMock()
    monkeypatch.setattr("bronze.save_manifest", mock_save_manifest)

    monkeypatch.setattr(
        "phase1_poc.discover_product_urls", MagicMock(return_value=["http://test.com"])
    )
    monkeypatch.setattr("phase1_poc.fetch_html", MagicMock(return_value="<html></html>"))
    monkeypatch.setattr(
        "phase1_poc.parse_product_html", MagicMock(side_effect=ValueError("Parse failed"))
    )

    main()

    mock_save_manifest.assert_called_once()
    manifest_summary = mock_save_manifest.call_args[0][5]
    assert manifest_summary["failed"] == 1
