# Phase 2 Closeout: Ingestion & Bronze

## Pencapaian Utama
- **Immutable Evidence**: Seluruh raw payload (HTML) tersimpan di MinIO sebelum proses parsing dilakukan. Object keys diamankan menggunakan hash MD5 dari URL untuk mencegah collision antar produk (misal: akhiran /detail di ECI).
- **Idempotency & Isolation**: Run ID kini anti-kolisi dengan format YYYYMMDDTHHMMSSZ-<uuid pendek>. Data terisolasi bersih berdasarkan source + category.
- **Fail-Safe Manifest & Rejected Records**: Record yang gagal parsing dicatat di bucket MinIO (folder ejected/). Jika proses pencarian URL (*discovery*) mati total karena server down, manifest tetap tercipta dengan status DISCOVERY_FAILED.
- **Support Penuh 4 Toko (Matriks 12/12)**: Discovery menggunakan kembali router bawaan dari Phase 1 (dispatch_source_category). Digimap (*shopify_sitemap*) sengaja dikembalikan ke scraping *category listing* untuk menjaga kemurnian batas kategori agar URL iPhone tidak tercampur ke folder iPad.
- **Detailed Manifest**: Manifest tidak hanya mencatat count, melainkan memetakan seluruh record per URL, status parsing, ketersediaan harga (price_present), dan object keys di MinIO.
- **Batas Phase yang Tegas**: File "silver_temp" gadungan beserta folder data/phase-2/silver_temp sudah dimusnahkan. Pipeline berhenti tepat di batas Bronze.

## Status
Semua *edge cases* arsitektural untuk Phase 2 telah ditambal dengan ketat, termasuk skenario koneksi putus dan kebocoran kategori. Environment dependencies (minio, python-dotenv) dipastikan dapat ter-install dengan baik (Python >=3.11). Seluruh tes (42 test) terpantau hijau. Pipeline 100% siap bertransisi ke Phase 3.
