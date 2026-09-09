import argparse
import os
import sys
import time
import requests
import uuid
from datetime import datetime, timezone
from dotenv import load_dotenv
import phase1_poc
import bronze

load_dotenv()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=list(phase1_poc.SOURCE_CONFIG.keys()), required=True)
    parser.add_argument("--category", choices=list(phase1_poc.CATEGORY_IDS), required=True)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    bucket = os.environ.get("MINIO_BUCKET", "bronze")
    client = bronze.get_client()
    bronze.ensure_bucket(client, bucket)

    run_id = args.run_id or f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
    plan = phase1_poc.dispatch_source_category(args.source, args.category)

    print(
        f"[{run_id}] Mulai ingestion {args.source}/{args.category} (Strategy: {plan['strategy']})..."
    )
    http = requests.Session()

    def fetch_wrapper(url: str) -> str:
        return phase1_poc.fetch_html(url, session=http, timeout_seconds=20)

    records = []
    success_count = 0
    product_urls = []

    try:
        # shopify_sitemap (Digimap) sengaja masuk sini, bukan ke discover_sitemap_product_urls,
        # karena sitemap global Digimap mencampur semua kategori (iPhone/iPad/Mac jadi satu).
        # Scraping halaman kategori langsung menjaga kemurnian data per kategori.
        if plan["strategy"] in ("category_listing", "shopify_sitemap"):
            cat_html = fetch_wrapper(plan["smoke_url"])
            product_urls = phase1_poc.discover_product_urls(
                args.source, plan["smoke_url"], cat_html, limit=args.limit
            )
        elif plan["strategy"] == "sitemap":
            product_urls = phase1_poc.discover_sitemap_product_urls(
                plan["discovery_url"], fetch_fn=fetch_wrapper
            )[: args.limit]
        elif plan["strategy"] == "product_suggestions_api":
            product_urls = phase1_poc.discover_electronic_city_product_urls(
                plan["discovery_url"],
                query=plan["search_query"],
                limit=args.limit,
                fetch_fn=fetch_wrapper,
            )
    except Exception as e:
        print(f"Discovery Error: {e}")
        summary = {
            "run_id": run_id,
            "source_id": args.source,
            "category_id": args.category,
            "strategy": plan["strategy"],
            "discovered": 0,
            "success": 0,
            "failed": 0,
            "status": "DISCOVERY_FAILED",
            "error": str(e),
            "records": [],
        }
        bronze.save_manifest(client, bucket, args.source, args.category, run_id, summary)
        sys.exit(1)

    print(f"Ditemukan {len(product_urls)} URL produk.")

    for url in product_urls:
        observed_at_utc = datetime.now(timezone.utc)
        record = {
            "url": url,
            "fetch_time": observed_at_utc.isoformat(),
            "parse_status": "FAILED",
            "raw_object_key": None,
            "rejected_key": None,
            "price_present": False,
        }

        try:
            html = fetch_wrapper(url)
            raw_key = bronze.save_raw_response(
                client, bucket, args.source, args.category, run_id, url, html
            )
            record["raw_object_key"] = raw_key

            parsed = phase1_poc.parse_product_html(args.source, url, html, observed_at_utc)
            record["parse_status"] = "SUCCESS"
            if parsed.current_price_idr is not None:
                record["price_present"] = True
            success_count += 1
        except Exception as e:
            try:
                rej_key = bronze.save_rejected(
                    client, bucket, args.source, args.category, run_id, url, str(e)
                )
                record["rejected_key"] = rej_key
            except Exception:
                record["rejected_key"] = "FAILED_TO_SAVE_REJECTED"
            record["error"] = str(e)

        records.append(record)
        time.sleep(args.delay)

    summary = {
        "run_id": run_id,
        "source_id": args.source,
        "category_id": args.category,
        "strategy": plan["strategy"],
        "discovered": len(product_urls),
        "success": success_count,
        "failed": len(product_urls) - success_count,
        "records": records,
        "status": "COMPLETED" if success_count > 0 else "FAILED_NO_DATA",
    }
    bronze.save_manifest(client, bucket, args.source, args.category, run_id, summary)

    if success_count == 0:
        print("Gagal: Tidak ada data valid yang berhasil diambil (success_count = 0).")
        sys.exit(1)

    print(f"Selesai! Sukses: {success_count}, Gagal: {len(product_urls) - success_count}")


if __name__ == "__main__":
    main()
