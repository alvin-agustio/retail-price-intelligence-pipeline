import io
import json
import os
import hashlib
from minio import Minio


def get_client() -> Minio:
    access_key = os.environ.get("MINIO_ACCESS_KEY")
    secret_key = os.environ.get("MINIO_SECRET_KEY")
    if not access_key or not secret_key:
        raise RuntimeError("MINIO_ACCESS_KEY and MINIO_SECRET_KEY must be set")

    return Minio(
        endpoint=os.environ.get("MINIO_ENDPOINT", "localhost:9000"),
        access_key=access_key,
        secret_key=secret_key,
        secure=False,
    )


def ensure_bucket(client: Minio, bucket_name: str = "bronze"):
    if not client.bucket_exists(bucket_name):
        client.make_bucket(bucket_name)


def _get_object_name(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def save_raw_response(
    client: Minio, bucket: str, source_id: str, category_id: str, run_id: str, url: str, html: str
) -> str:
    obj_name = f"raw/{source_id}/{category_id}/{run_id}/{_get_object_name(url)}.html"
    data = html.encode("utf-8")
    client.put_object(bucket, obj_name, io.BytesIO(data), len(data), content_type="text/html")
    return obj_name


def save_rejected(
    client: Minio, bucket: str, source_id: str, category_id: str, run_id: str, url: str, error: str
) -> str:
    obj_name = f"rejected/{source_id}/{category_id}/{run_id}/{_get_object_name(url)}.json"
    data = json.dumps({"url": url, "error": error}).encode("utf-8")
    client.put_object(
        bucket, obj_name, io.BytesIO(data), len(data), content_type="application/json"
    )
    return obj_name


def save_manifest(
    client: Minio, bucket: str, source_id: str, category_id: str, run_id: str, summary: dict
) -> str:
    obj_name = f"manifests/{source_id}/{category_id}/{run_id}.json"
    data = json.dumps(summary, indent=2).encode("utf-8")
    client.put_object(
        bucket, obj_name, io.BytesIO(data), len(data), content_type="application/json"
    )
    return obj_name
