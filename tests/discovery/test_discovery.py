from datetime import datetime, timezone
from decimal import Decimal
import json

import pytest
from pydantic import ValidationError
from retail_pipeline import discovery

from retail_pipeline.discovery import (
    CATEGORY_IDS,
    CollectionResult,
    RawProductObservation,
    SOURCE_CONFIG,
    collect_explicit_pages,
    collect_from_html,
    discover_product_urls,
    discover_electronic_city_product_urls,
    fetch_explicit_source,
    fetch_electronic_city_source,
    fetch_sitemap_source,
    fetch_html,
    fetch_source,
    main,
    parse_product_html,
    discover_sitemap_product_urls,
    dispatch_source_category,
    parse_sitemap_xml,
    compare_smoke_discoveries,
    run_smoke_matrix,
    run_smoke_test,
    write_smoke_summary,
    write_smoke_run,
    write_raw_sample,
)


def test_monolithic_phase1_module_exposes_parser_and_contract():
    """The compact Phase 1 module exposes the two core public pieces."""
    html = """
    <script type="application/ld+json">
      {"@type":"Product","name":"Demo Phone","sku":"DEMO-1",
       "offers":{"price":"3.599.000","availability":"InStock"}}
    </script>
    """

    result = parse_product_html(
        source_id="erablue",
        source_url="https://www.erablue.id/product/demo-phone",
        html=html,
        observed_at_utc=datetime(2026, 8, 19, 10, tzinfo=timezone.utc),
    )

    assert isinstance(result, RawProductObservation)
    assert result.current_price_idr == Decimal("3599000")


PRODUCT_HTML = """
<html>
  <head>
    <script type="application/ld+json">
      {"@context":"https://schema.org","@type":"Product",
       "name":"Samsung Galaxy A17 4GB/128GB Black",
       "sku":"A17-4-128-BLK",
       "offers":{"@type":"Offer","price":"3.599.000",
                 "availability":"https://schema.org/InStock"}}
    </script>
  </head>
  <body><h1>Samsung Galaxy A17 4GB/128GB Black</h1>
    <span class="original-price">Rp 3.899.000</span>
    <span class="availability">Tersedia</span>
  </body>
</html>
"""


def test_parse_product_html_extracts_common_fields():
    result = parse_product_html(
        source_id="erablue",
        source_url="https://www.erablue.id/product/samsung-a17",
        html=PRODUCT_HTML,
        observed_at_utc=datetime(2026, 8, 18, 10, tzinfo=timezone.utc),
    )

    assert result.source_product_id == "A17-4-128-BLK"
    assert result.product_name_raw == "Samsung Galaxy A17 4GB/128GB Black"
    assert result.current_price_idr == Decimal("3599000")
    assert result.original_price_idr == Decimal("3899000")
    assert result.availability_status_raw == "Tersedia"
    assert result.location_context == "UNSPECIFIED"


def test_parse_product_html_extracts_numeric_electronic_city_id():
    result = parse_product_html(
        source_id="electronic_city",
        source_url="https://eci.id/product/83776/detail",
        html=PRODUCT_HTML,
        observed_at_utc=datetime(2026, 8, 18, 10, tzinfo=timezone.utc),
    )

    assert result.source_product_id == "83776"


def test_parse_product_html_falls_back_to_visible_price_and_stock_text():
    html = """
    <html><head><title>ACER NOTEBOOK RYZEN 5</title></head>
    <body><h1>ACER NOTEBOOK RYZEN 5</h1><p>Rp. 10.909.000</p>
    <p>Stok habis!</p></body></html>
    """

    result = parse_product_html(
        source_id="electronic_city",
        source_url="https://eci.id/product/83776/detail",
        html=html,
        observed_at_utc=datetime(2026, 8, 18, 10, tzinfo=timezone.utc),
    )

    assert result.current_price_idr == Decimal("10909000")
    assert result.availability_status_raw == "Stok habis!"


def test_parse_eraspace_next_data_extracts_price_sku_and_stock():
    html = """
    <html><head><title>Realme 15 5G</title></head><body>
    <script id="__NEXT_DATA__" type="application/json">
    {"props":{"pageProps":{"data":{
      "id":4002,"name":"realme 15 5G","sku":"REA-155G-CON",
      "price":4999000,"special_price":4899000,"qty":6,
      "stock_status":1,"store_stock_status":0
    }}}}
    </script></body></html>
    """

    result = parse_product_html(
        source_id="eraspace",
        source_url="https://eraspace.com/eraspace/produk/realme-15-5g",
        html=html,
        observed_at_utc=datetime(2026, 8, 18, 10, tzinfo=timezone.utc),
    )

    assert result.source_product_id == "REA-155G-CON"
    assert result.product_name_raw == "realme 15 5G"
    assert result.current_price_idr == Decimal("4899000")
    assert result.original_price_idr == Decimal("4999000")
    assert result.availability_status_raw == "IN_STOCK"


def test_parse_eraspace_next_data_preserves_store_stock_state():
    html = """
    <script id="__NEXT_DATA__" type="application/json">
    {"props":{"pageProps":{"data":{
      "id":4001,"name":"realme 12 5G","sku":"8100140190",
      "price":3299000,"special_price":3299000,"qty":0,
      "stock_status":0,"store_stock_status":1
    }}}}
    </script>
    """

    result = parse_product_html(
        source_id="eraspace",
        source_url="https://eraspace.com/eraspace/produk/realme-12-5g",
        html=html,
        observed_at_utc=datetime(2026, 8, 18, 10, tzinfo=timezone.utc),
    )

    assert result.current_price_idr == Decimal("3299000")
    assert result.availability_status_raw == "STORE_STOCK"


def test_discover_product_urls_uses_source_patterns_and_limit():
    html = "".join(
        [
            '<a href="/product/1/detail">ECI one</a>',
            '<a href="/product/2/detail">ECI two</a>',
            '<a href="/category/phones">Category</a>',
            '<a href="https://other.example/product/9/detail">Other</a>',
        ]
    )

    result = discover_product_urls(
        source_id="electronic_city",
        category_url="https://eci.id/category/phones",
        html=html,
        limit=1,
    )

    assert result == ["https://eci.id/product/1/detail"]


def test_discover_product_urls_reads_jsonld_collection_items():
    html = """
    <script type="application/ld+json">
    {"@type":"CollectionPage","mainEntity":{"@type":"ItemList",
      "itemListElement":[
        {"item":{"@type":"Product","url":"https://www.erablue.id/handphone/a17"}},
        {"item":{"@type":"Product","url":"https://www.erablue.id/handphone/a18"}}
      ]}}
    </script>
    """

    result = discover_product_urls(
        source_id="erablue",
        category_url="https://www.erablue.id/handphone",
        html=html,
        limit=2,
    )

    assert result == [
        "https://www.erablue.id/handphone/a17",
        "https://www.erablue.id/handphone/a18",
    ]


def test_raw_observation_rejects_negative_price():
    with pytest.raises(ValidationError):
        RawProductObservation(
            source_id="erablue",
            source_product_id="1",
            source_url="https://www.erablue.id/product/1",
            product_name_raw="Example product",
            current_price_idr=Decimal("-1"),
            original_price_idr=None,
            availability_status_raw=None,
            observed_at_utc=datetime(2026, 8, 18, tzinfo=timezone.utc),
        )


def test_collect_from_html_keeps_successes_and_reports_missing_product_pages():
    category_url = "https://www.erablue.id/handphone"
    category_html = '<a href="/product/samsung-a17">A17</a><a href="/product/missing">Missing</a>'
    product_html = """
    <script type="application/ld+json">
      {"@type":"Product","name":"Samsung A17","sku":"A17-128",
       "offers":{"price":"3599000","availability":"InStock"}}
    </script>
    """

    result = collect_from_html(
        source_id="erablue",
        category_url=category_url,
        category_html=category_html,
        product_pages={"https://www.erablue.id/product/samsung-a17": product_html},
        observed_at_utc=datetime(2026, 8, 18, 10, tzinfo=timezone.utc),
        limit=10,
    )

    assert len(result.observations) == 1
    assert result.observations[0].current_price_idr == Decimal("3599000")
    assert len(result.errors) == 1
    assert "missing" in result.errors[0]["url"]


def test_collect_explicit_pages_works_without_catalogue_links():
    result = collect_explicit_pages(
        source_id="eraspace",
        category_url="https://eraspace.com/eraspace/katalog/realme-306",
        product_pages={
            "https://eraspace.com/eraspace/produk/realme-a": """
              <script type="application/ld+json">
                {"@type":"Product","name":"Realme A","sku":"REALME-A",
                 "offers":{"price":"3299000","availability":"InStock"}}
              </script>
            """
        },
        observed_at_utc=datetime(2026, 8, 18, 10, tzinfo=timezone.utc),
    )

    assert len(result.observations) == 1
    assert result.observations[0].source_product_id == "REALME-A"


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.calls: list[tuple[str, dict, int]] = []

    def get(self, url, *, headers, timeout):
        self.calls.append((url, headers, timeout))
        return FakeResponse(self.pages[url])


def test_fetch_html_uses_timeout_and_user_agent():
    session = FakeSession({"https://example.test/page": "<html/>"})

    html = fetch_html("https://example.test/page", session=session, timeout_seconds=7)

    assert html == "<html/>"
    assert session.calls[0][2] == 7
    assert "PortfolioSmokeTest" in session.calls[0][1]["User-Agent"]


def test_fetch_source_fetches_category_then_product_pages():
    category_url = "https://www.erablue.id/handphone"
    product_url = "https://www.erablue.id/product/a17"
    pages = {
        category_url: f'<a href="{product_url}">A17</a>',
        product_url: """
          <script type="application/ld+json">
            {"@type":"Product","name":"Galaxy A17","sku":"A17-128",
             "offers":{"price":"3599000","availability":"InStock"}}
          </script>
        """,
    }

    result = fetch_source(
        source_id="erablue",
        category_url=category_url,
        observed_at_utc=datetime(2026, 8, 18, 10, tzinfo=timezone.utc),
        session=FakeSession(pages),
        timeout_seconds=7,
        limit=10,
    )

    assert len(result.observations) == 1
    assert result.observations[0].source_product_id == "A17-128"


def test_fetch_source_keeps_a_discovered_url_when_its_product_request_fails():
    category_url = "https://www.erablue.id/tablet"
    product_url = "https://www.erablue.id/tablet/demo"

    class ProductTimeoutSession(FakeSession):
        def get(self, url, *, headers, timeout):
            if url == product_url:
                raise RuntimeError("product request timed out")
            return super().get(url, headers=headers, timeout=timeout)

    result = fetch_source(
        source_id="erablue",
        category_url=category_url,
        observed_at_utc=datetime(2026, 9, 1, tzinfo=timezone.utc),
        session=ProductTimeoutSession({category_url: f'<a href="{product_url}">Demo</a>'}),
        limit=1,
    )

    assert result.discovered_product_urls == [product_url]
    assert result.observations == []
    assert result.errors == [
        {"url": product_url, "error": "request failed: product request timed out"}
    ]


def test_fetch_explicit_source_fetches_approved_product_pages():
    product_url = "https://eraspace.com/eraspace/produk/realme-15-5g"
    pages = {
        product_url: """
          <script id="__NEXT_DATA__" type="application/json">
            {"props":{"pageProps":{"data":{
              "name":"Realme 15 5G","sku":"REA-155G-CON",
              "price":4999000,"special_price":4899000,
              "qty":6,"stock_status":1,"store_stock_status":0
            }}}}
          </script>
        """,
    }

    result = fetch_explicit_source(
        source_id="eraspace",
        category_url="https://eraspace.com/eraspace/katalog/realme-306",
        product_urls=[product_url],
        observed_at_utc=datetime(2026, 8, 18, 10, tzinfo=timezone.utc),
        session=FakeSession(pages),
        timeout_seconds=7,
    )

    assert len(result.discovered_product_urls) == 1
    assert len(result.observations) == 1
    assert result.observations[0].source_product_id == "REA-155G-CON"
    assert result.observations[0].current_price_idr == Decimal("4899000")


def test_write_raw_sample_writes_replayable_json(tmp_path):
    observation = RawProductObservation(
        source_id="digimap",
        source_product_id="SKU-1",
        source_url="https://www.digimap.co.id/products/macbook",
        product_name_raw="MacBook Air",
        current_price_idr=Decimal("28749000"),
        observed_at_utc=datetime(2026, 8, 18, 10, tzinfo=timezone.utc),
    )

    output_path = write_raw_sample(
        output_root=tmp_path,
        source_id="digimap",
        observed_at_utc=observation.observed_at_utc,
        observations=[observation],
        errors=[],
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["source_id"] == "digimap"
    assert payload["records"][0]["current_price_idr"] == "28749000"
    assert payload["errors"] == []


def test_write_raw_sample_supports_iterators(tmp_path):
    observation = RawProductObservation(
        source_id="erablue",
        source_product_id="SKU-2",
        source_url="https://www.erablue.id/product/a17",
        product_name_raw="Galaxy A17",
        current_price_idr=Decimal("3599000"),
        observed_at_utc=datetime(2026, 8, 18, 10, tzinfo=timezone.utc),
    )

    output_path = write_raw_sample(
        output_root=tmp_path,
        source_id="erablue",
        observed_at_utc=observation.observed_at_utc,
        observations=iter([observation]),
        errors=iter([]),
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["record_count"] == 1
    assert len(payload["records"]) == 1


def test_parse_sitemap_xml_separates_child_sitemaps_and_product_urls():
    xml = """
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://eraspace.com/sitemap/eraspace/mobile-phones-23.xml</loc></sitemap>
      <sitemap><loc>https://eraspace.com/sitemap/eraspace/tablet-403.xml</loc></sitemap>
    </sitemapindex>
    """

    child_sitemaps, product_urls = parse_sitemap_xml(xml)

    assert child_sitemaps == [
        "https://eraspace.com/sitemap/eraspace/mobile-phones-23.xml",
        "https://eraspace.com/sitemap/eraspace/tablet-403.xml",
    ]
    assert product_urls == []


def test_discover_electronic_city_product_urls_turns_public_search_results_into_detail_urls():
    """API pencarian dipakai karena halaman kategori ECI tidak berisi link produk."""
    api_url = "https://eci.test/api/product-suggestions"
    responses = {
        f"{api_url}?q=tablet&limit=6": json.dumps(
            {
                "status": "success",
                "data": [
                    {"id": 77734, "name": "Tablet pertama"},
                    {"id": "86172", "name": "Tablet kedua"},
                    {"name": "Produk tanpa ID"},
                ],
            }
        )
    }

    result = discover_electronic_city_product_urls(
        api_url,
        query="tablet",
        limit=2,
        fetch_fn=responses.__getitem__,
    )

    assert result == [
        "https://eci.test/product/77734/detail",
        "https://eci.test/product/86172/detail",
    ]


def test_fetch_sitemap_source_reads_products_from_the_selected_category_sitemap():
    """Eraspace tidak perlu membuka halaman kategori yang kosong terlebih dahulu."""
    sitemap_url = "https://eraspace.test/sitemap/eraspace/tablet-403.xml"
    product_url = "https://eraspace.test/eraspace/produk/tablet-a"
    pages = {
        sitemap_url: f"""
          <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>{product_url}</loc></url>
          </urlset>
        """,
        product_url: PRODUCT_HTML,
    }

    result = fetch_sitemap_source(
        "eraspace",
        "https://eraspace.test/eraspace/katalog/tablet-403",
        sitemap_url=sitemap_url,
        observed_at_utc=datetime(2026, 9, 1, tzinfo=timezone.utc),
        fetch_fn=pages.__getitem__,
        limit=1,
        delay_seconds=0,
    )

    assert result.discovered_product_urls == [product_url]
    assert result.observations[0].current_price_idr == Decimal("3599000")


def test_fetch_electronic_city_source_reads_detail_pages_after_public_search():
    """Hasil pencarian hanya menemukan URL; harga tetap diambil dari detail produk."""
    api_url = "https://eci.test/api/product-suggestions"
    product_url = "https://eci.test/product/77734/detail"
    pages = {
        f"{api_url}?q=tablet&limit=3": json.dumps(
            {"status": "success", "data": [{"id": 77734, "name": "Tablet"}]}
        ),
        product_url: PRODUCT_HTML,
    }

    result = fetch_electronic_city_source(
        "https://eci.test/category/handphone-dan-tablet",
        api_url=api_url,
        query="tablet",
        observed_at_utc=datetime(2026, 9, 1, tzinfo=timezone.utc),
        fetch_fn=pages.__getitem__,
        limit=1,
        delay_seconds=0,
    )

    assert result.discovered_product_urls == [product_url]
    assert result.observations[0].source_id == "electronic_city"


def test_discover_sitemap_product_urls_follows_children_and_deduplicates():
    root = "https://eraspace.test/sitemap.xml"
    child = "https://eraspace.test/sitemap/eraspace/mobile.xml"
    pages = {
        root: """
          <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <sitemap><loc>/sitemap/eraspace/mobile.xml</loc></sitemap>
          </sitemapindex>
        """,
        child: """
          <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>/eraspace/produk/phone-a</loc></url>
            <url><loc>https://eraspace.test/eraspace/produk/phone-a</loc></url>
            <url><loc>/eraspace/produk/phone-b?ref=sitemap</loc></url>
            <url><loc>/eraspace/katalog/phones</loc></url>
          </urlset>
        """,
    }

    result = discover_sitemap_product_urls(root, fetch_fn=pages.__getitem__)

    assert result == [
        "https://eraspace.test/eraspace/produk/phone-a",
        "https://eraspace.test/eraspace/produk/phone-b?ref=sitemap",
    ]


def test_discover_sitemap_product_urls_rejects_cross_host_child_sitemap():
    root = "https://eraspace.test/sitemap.xml"
    pages = {
        root: """
          <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <sitemap><loc>https://other.test/sitemap.xml</loc></sitemap>
          </sitemapindex>
        """,
    }

    with pytest.raises(ValueError, match="same host"):
        discover_sitemap_product_urls(root, fetch_fn=pages.__getitem__)


def test_source_config_contains_exactly_the_four_retailers_and_three_categories():
    assert set(SOURCE_CONFIG) == {"eraspace", "electronic_city", "digimap", "erablue"}
    assert set(CATEGORY_IDS) == {"smartphone", "tablet", "laptop"}
    assert all(set(categories) == set(CATEGORY_IDS) for categories in SOURCE_CONFIG.values())


def test_source_config_has_smoke_url_and_discovery_strategy_for_every_combination():
    for categories in SOURCE_CONFIG.values():
        for category in categories.values():
            assert category["smoke_url"].startswith("https://")
            assert category["discovery"] in {
                "sitemap",
                "product_suggestions_api",
                "shopify_sitemap",
                "category_listing",
            }


def test_dispatch_source_category_returns_the_selected_strategy_and_urls():
    plan = dispatch_source_category("eraspace", "tablet")

    assert plan["source_id"] == "eraspace"
    assert plan["category_id"] == "tablet"
    assert plan["strategy"] == "sitemap"
    assert plan["smoke_url"].endswith("/tablet-403")
    assert plan["discovery_url"] == "https://eraspace.com/sitemap/eraspace/tablet-403.xml"


def test_dispatch_exposes_the_reproducible_discovery_input_for_each_weak_source():
    eraspace = dispatch_source_category("eraspace", "tablet")
    electronic_city = dispatch_source_category("electronic_city", "laptop")

    assert eraspace["discovery_url"] == "https://eraspace.com/sitemap/eraspace/tablet-403.xml"
    assert electronic_city["strategy"] == "product_suggestions_api"
    assert electronic_city["discovery_url"] == "https://eci.id/api/product-suggestions"
    assert electronic_city["search_query"] == "laptop"


def test_dispatch_source_category_rejects_unknown_source_or_category():
    with pytest.raises(ValueError, match="unsupported source_id"):
        dispatch_source_category("unknown", "tablet")

    with pytest.raises(ValueError, match="unsupported category_id"):
        dispatch_source_category("eraspace", "television")


def _ready_collection(source_id, category_url, observed_at_utc, **_kwargs):
    """Collector kecil untuk membuktikan runner tanpa membuka internet."""
    record = RawProductObservation(
        source_id=source_id,
        source_product_id="DEMO-1",
        source_url="https://example.test/product/demo",
        product_name_raw="Demo product",
        current_price_idr=Decimal("1000"),
        observed_at_utc=observed_at_utc,
    )
    return CollectionResult(
        source_id=source_id,
        category_url=category_url,
        observed_at_utc=observed_at_utc,
        discovered_product_urls=["https://example.test/product/demo"],
        observations=[record],
        errors=[],
    )


def test_run_smoke_test_labels_the_record_with_its_selected_category():
    result = run_smoke_test(
        "erablue",
        "tablet",
        observed_at_utc=datetime(2026, 9, 1, tzinfo=timezone.utc),
        collection_runner=_ready_collection,
    )

    assert result.status == "READY"
    assert result.category_id == "tablet"
    assert result.observations[0].category_id == "tablet"
    assert result.price_valid_count == 1


def test_run_smoke_test_uses_eraspace_sitemap_adapter_instead_of_empty_listing(monkeypatch):
    calls = []

    def fake_sitemap_source(source_id, category_url, *, sitemap_url, observed_at_utc, **_kwargs):
        calls.append((source_id, category_url, sitemap_url))
        return _ready_collection(source_id, category_url, observed_at_utc)

    monkeypatch.setattr(discovery, "fetch_sitemap_source", fake_sitemap_source)
    monkeypatch.setattr(
        discovery,
        "fetch_source",
        lambda *_args, **_kwargs: pytest.fail("listing adapter must not be used for Eraspace"),
    )

    result = run_smoke_test(
        "eraspace",
        "tablet",
        observed_at_utc=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    assert result.status == "READY"
    assert calls == [
        (
            "eraspace",
            "https://eraspace.com/eraspace/katalog/tablet-403",
            "https://eraspace.com/sitemap/eraspace/tablet-403.xml",
        )
    ]


def test_run_smoke_test_uses_electronic_city_search_adapter_instead_of_empty_listing(monkeypatch):
    calls = []

    def fake_electronic_city_source(category_url, *, api_url, query, observed_at_utc, **_kwargs):
        calls.append((category_url, api_url, query))
        return _ready_collection("electronic_city", category_url, observed_at_utc)

    monkeypatch.setattr(discovery, "fetch_electronic_city_source", fake_electronic_city_source)
    monkeypatch.setattr(
        discovery,
        "fetch_source",
        lambda *_args, **_kwargs: pytest.fail(
            "listing adapter must not be used for Electronic City"
        ),
    )

    result = run_smoke_test(
        "electronic_city",
        "laptop",
        observed_at_utc=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    assert result.status == "READY"
    assert calls == [
        (
            "https://eci.id/category/laptop-dan-gaming?sort=best-selling",
            "https://eci.id/api/product-suggestions",
            "laptop",
        )
    ]


def test_run_smoke_matrix_calls_all_twelve_combinations():
    calls = []

    def collector(source_id, category_url, observed_at_utc, **_kwargs):
        calls.append((source_id, category_url))
        return _ready_collection(source_id, category_url, observed_at_utc)

    results = run_smoke_matrix(
        observed_at_utc=datetime(2026, 9, 1, tzinfo=timezone.utc),
        collection_runner=collector,
    )

    assert len(results) == 12
    assert len(calls) == 12
    assert {result.category_id for result in results} == set(CATEGORY_IDS)


def test_run_smoke_test_reports_a_failed_source_without_raising():
    def broken_collector(*_args, **_kwargs):
        raise RuntimeError("website did not respond")

    result = run_smoke_test(
        "erablue",
        "laptop",
        observed_at_utc=datetime(2026, 9, 1, tzinfo=timezone.utc),
        collection_runner=broken_collector,
    )

    assert result.status == "FAILED"
    assert result.errors == [
        {"url": "https://www.erablue.id/laptop", "error": "website did not respond"}
    ]


def test_write_smoke_run_keeps_each_category_in_a_separate_file(tmp_path):
    result = run_smoke_test(
        "erablue",
        "smartphone",
        observed_at_utc=datetime(2026, 9, 1, tzinfo=timezone.utc),
        collection_runner=_ready_collection,
    )

    output_path = write_smoke_run(tmp_path, result, run_id="phase1-demo")
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert output_path == tmp_path / "phase1-demo" / "erablue" / "smartphone.json"
    assert payload["category_id"] == "smartphone"
    assert payload["records"][0]["category_id"] == "smartphone"


def test_compare_smoke_discoveries_reports_added_and_removed_urls():
    first = run_smoke_test(
        "erablue",
        "smartphone",
        observed_at_utc=datetime(2026, 9, 1, tzinfo=timezone.utc),
        collection_runner=_ready_collection,
    )
    second = first.__class__(
        **{
            **first.__dict__,
            "discovered_product_urls": ["https://example.test/product/new"],
        }
    )

    comparison = compare_smoke_discoveries(first, second)

    assert comparison["added_urls"] == ["https://example.test/product/new"]
    assert comparison["removed_urls"] == ["https://example.test/product/demo"]


def test_write_smoke_summary_counts_each_result_status(tmp_path):
    ready = run_smoke_test(
        "erablue",
        "smartphone",
        observed_at_utc=datetime(2026, 9, 1, tzinfo=timezone.utc),
        collection_runner=_ready_collection,
    )
    failed = run_smoke_test(
        "erablue",
        "tablet",
        observed_at_utc=datetime(2026, 9, 1, tzinfo=timezone.utc),
        collection_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("down")),
    )

    output_path = write_smoke_summary(tmp_path, [ready, failed], run_id="phase1-demo")
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["status_counts"] == {"FAILED": 1, "READY": 1}


def test_main_can_run_the_smoke_matrix_from_one_command(monkeypatch, tmp_path):
    observed_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    results = run_smoke_matrix(observed_at_utc=observed_at, collection_runner=_ready_collection)
    monkeypatch.setattr("retail_pipeline.discovery.run_smoke_matrix", lambda **_kwargs: results)
    monkeypatch.setattr(
        "sys.argv",
        ["phase1_poc.py", "--smoke-matrix", "--output", str(tmp_path)],
    )

    exit_code = main()

    summary_files = list(tmp_path.rglob("summary.json"))
    assert exit_code == 0
    assert len(summary_files) == 1
