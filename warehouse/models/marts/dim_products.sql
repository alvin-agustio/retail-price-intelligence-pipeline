WITH ranked AS (
    SELECT
        source_id,
        category_id,
        source_product_id,
        product_name_raw AS current_product_name,
        source_url,
        ROW_NUMBER() OVER (PARTITION BY source_id, source_product_id ORDER BY observed_at_utc DESC) as rn
    FROM {{ ref('stg_observations') }}
    WHERE source_product_id IS NOT NULL
)
SELECT 
    md5(source_id || source_product_id) AS product_key,
    source_id, 
    category_id, 
    source_product_id, 
    current_product_name, 
    source_url
FROM ranked 
WHERE rn = 1
