SELECT
    source_id,
    category_id,
    source_product_id,
    source_url,
    product_name_raw,
    current_price_idr,
    original_price_idr,
    availability_status_raw,
    observed_at_utc,
    run_id
FROM {{ source('landing', 'observations') }}
