SELECT 'missing_product' AS rule, CAST(p.product_id AS VARCHAR) AS product_id
FROM {{ ref('stg_product__products') }} p
WHERE NOT EXISTS (SELECT 1 FROM {{ ref('fct_product_metrics') }} r WHERE r.product_id=p.product_id)
UNION ALL
SELECT 'invalid_or_duplicate_product', CAST(r.product_id AS VARCHAR)
FROM {{ ref('fct_product_metrics') }} r
GROUP BY r.product_id
HAVING COUNT(*)<>1 OR r.product_id IS NULL
UNION ALL
SELECT 'unknown_product', CAST(r.product_id AS VARCHAR)
FROM {{ ref('fct_product_metrics') }} r
WHERE NOT EXISTS (SELECT 1 FROM {{ ref('stg_product__products') }} p WHERE p.product_id=r.product_id)
