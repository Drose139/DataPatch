SELECT product_id, units_sold, product_revenue, avg_unit_price
FROM {{ ref('fct_product_metrics') }}
WHERE units_sold IS NULL
   OR product_revenue IS NULL
   OR (units_sold<>0
       AND (avg_unit_price IS NULL OR ABS(avg_unit_price-product_revenue/units_sold)>0.0001))
