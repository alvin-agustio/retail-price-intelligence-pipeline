import argparse
import json
import os
import sys
from datetime import datetime
from dotenv import load_dotenv
from .. import discovery
from ..storage import bronze, silver

load_dotenv()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--category", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    bucket = os.environ.get("MINIO_BUCKET", "bronze")
    client = bronze.get_client()

    print(f"Membangun Silver untuk {args.source}/{args.category} (Run: {args.run_id})")

    # 1. Baca daftar tunggu (Manifest) dari Bronze
    manifest_key = f"manifests/{args.source}/{args.category}/{args.run_id}.json"
    try:
        resp = client.get_object(bucket, manifest_key)
        manifest = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Gagal membaca manifest: {e}")
        sys.exit(1)

    valid_records = []

    # 2. Replay: Baca HTML dari Bronze, ekstrak datanya tanpa koneksi internet
    for rec in manifest.get("records", []):
        raw_key = rec.get("raw_object_key")
        if not raw_key:
            continue

        try:
            # Ambil HTML mentah dari Gudang Bronze
            html_data = client.get_object(bucket, raw_key).read().decode("utf-8")
            fetch_time = datetime.fromisoformat(rec["fetch_time"])

            # Parsing HTML menjadi data terstruktur
            obs = discovery.parse_product_html(args.source, rec["url"], html_data, fetch_time)

            # 3. Quality Check: Tolak data tanpa harga wajar
            if obs.current_price_idr is None or obs.current_price_idr < 0:
                err_msg = f"Harga ditolak oleh Quality Check: {obs.current_price_idr}"
                print(f"Quality Check Gagal untuk {rec['url']}: {err_msg}")
                bronze.save_rejected(
                    client, bucket, args.source, args.category, args.run_id, rec["url"], err_msg
                )
                continue

            # Normalisasi tipe data untuk PyArrow (Decimal -> Float, URL -> String)
            row = obs.model_dump()
            row["category_id"] = (
                args.category
            )  # [FIX] Timpa UNSPECIFIED dengan kategori asli dari runner
            row["source_url"] = str(row["source_url"])
            row["current_price_idr"] = float(row["current_price_idr"])
            if row["original_price_idr"]:
                row["original_price_idr"] = float(row["original_price_idr"])

            valid_records.append(row)
        except Exception as e:
            # Jika HTML web berubah, akan gagal di sini. Catat bukti kegagalan (Audit Trail).
            print(f"Gagal parse URL {rec['url']}: {e}")
            bronze.save_rejected(
                client,
                bucket,
                args.source,
                args.category,
                args.run_id,
                rec["url"],
                f"Build Silver Parse Error: {str(e)}",
            )

    # 4. Kemas ke Kaleng Vakum (Parquet)
    if not valid_records:
        print("Gagal: Tidak ada data valid yang memenuhi Quality Check (0 records).")
        sys.exit(1)

    silver_key = silver.write_parquet_to_minio(
        client, bucket, args.source, args.category, args.run_id, valid_records
    )
    print(f"Sukses! {len(valid_records)} baris diamankan ke Silver: {silver_key}")


if __name__ == "__main__":
    main()
