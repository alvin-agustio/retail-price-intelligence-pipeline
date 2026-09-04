import argparse
import os
import io
import pandas as pd
from sqlalchemy import create_engine, text, inspect
from dotenv import load_dotenv
import bronze

load_dotenv()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--category", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    bucket = os.environ.get("MINIO_BUCKET", "bronze")
    client = bronze.get_client()

    db_user = os.environ.get("POSTGRES_USER", "erpm")
    db_pass = os.environ.get("POSTGRES_PASSWORD", "erpm")
    db_host = os.environ.get("POSTGRES_HOST", "localhost")
    db_port = os.environ.get("POSTGRES_PORT", "5432")
    db_name = os.environ.get("POSTGRES_DB", "warehouse")

    engine = create_engine(f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}")

    object_name = f"silver/observations/source={args.source}/category={args.category}/run_id={args.run_id}.parquet"
    try:
        response = client.get_object(bucket, object_name)
        df = pd.read_parquet(io.BytesIO(response.read()))
    except Exception as e:
        print(f"Gagal membaca Parquet dari Silver: {e}")
        return

    if df.empty:
        return

    df["run_id"] = args.run_id

    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS landing;"))
        # Proteksi Idempotency: Hapus data run_id lama jika tabel sudah ada
        if inspect(engine).has_table("observations", schema="landing"):
            conn.execute(
                text("DELETE FROM landing.observations WHERE run_id = :run_id"),
                {"run_id": args.run_id},
            )

        df.to_sql("observations", con=conn, schema="landing", if_exists="append", index=False)

    print(f"Sukses memuat {len(df)} baris ke landing.observations (Run ID: {args.run_id})")


if __name__ == "__main__":
    main()
