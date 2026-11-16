WITH source_totals AS (
  SELECT COALESCE(SUM(l.quantity_ordered),0) AS units,
         COALESCE(SUM(l.line_total),0) AS revenue
  FROM {{ ref('stg_orders__order_lines') }} l
  JOIN {{ ref('stg_orders__orders') }} o ON l.order_id=o.order_id
  WHERE o.status NOT IN ('CANCELLED','RETURNED','FAILED')
), output_totals AS (
  SELECT COALESCE(SUM(units_sold),0) AS units,
         COALESCE(SUM(product_revenue),0) AS revenue
  FROM {{ ref('fct_product_metrics') }}
)
SELECT 'valid_sale_units' AS rule, s.units AS expected, r.units AS actual
FROM source_totals s CROSS JOIN output_totals r WHERE ABS(s.units-r.units)>0.0001
UNION ALL
SELECT 'stored_sale_revenue', s.revenue, r.revenue
FROM source_totals s CROSS JOIN output_totals r WHERE ABS(s.revenue-r.revenue)>0.0001
