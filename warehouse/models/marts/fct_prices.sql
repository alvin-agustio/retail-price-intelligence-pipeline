SELECT
    md5(source_id || source_product_id || observed_at_utc::text) AS observation_id,
    md5(source_id || source_product_id) AS product_key,
    source_id,
    source_product_id,
    observed_at_utc AS observed_at,
    current_price_idr AS price,
    original_price_idr AS original_price,
    availability_status_raw AS status,
    run_id
FROM {{ ref('stg_observations') }}
