from retail_pipeline import discovery
from retail_pipeline.jobs import build_silver, ingest, load_warehouse
from retail_pipeline.storage import bronze, silver


def test_pipeline_modules_are_grouped_by_responsibility():
    assert callable(discovery.parse_product_html)
    assert callable(ingest.main)
    assert callable(build_silver.main)
    assert callable(load_warehouse.main)
    assert callable(bronze.get_client)
    assert hasattr(silver, "SILVER_SCHEMA")
