-- operator_reviewed
-- Reviewed delivery artifact; not a new autonomous model run.
{{ config(
    materialized='table',
    tags=['product', 'marts', 'metrics']
) }}

/*
    fct_product_metrics
    ------------------------------------------------------------------
    Grain: one row per product (products dimension grain).

    Sales metrics come from order line items joined to their order header,
    excluding CANCELLED / RETURNED / FAILED orders (all other statuses are
    valid completed sales). Revenue uses the stored line_total monetary
    total of each order line (already net of line discounts, consistent
    with the order header SUBTOTAL), not a re-derived gross amount.

    Variant information is aggregated to product level before joining so
    the product grain is not fanned out.
*/

with products as (

    select
        product_id,
        product_name,
        primary_category_id
    from {{ ref('stg_product__products') }}
    qualify row_number() over (
        partition by product_id
        order by updated_at desc nulls last, created_at desc nulls last
    ) = 1

),

categories as (

    select
        category_id,
        category_name
    from {{ ref('stg_product__product_categories') }}
    qualify row_number() over (
        partition by category_id
        order by updated_at desc nulls last, created_at desc nulls last
    ) = 1

),

variants as (

    select
        product_id,
        count(distinct variant_id) as total_variants
    from {{ ref('stg_product__product_variants') }}
    where product_id is not null
    group by 1

),

variant_products as (

    -- Deduplicate repeated copies of the same mapping; conflicting mappings
    -- cannot identify a product and must not multiply the sales facts.
    select variant_id, min(product_id) as product_id
    from {{ ref('stg_product__product_variants') }}
    group by variant_id
    having count(distinct product_id) = 1
       and count(product_id) = count(*)

),

valid_order_lines as (

    select
        -- Keep an existing direct product; rescue orphan keys only through
        -- an unambiguous variant whose product also exists in the dimension.
        coalesce(p_direct.product_id, p_variant.product_id) as product_id,
        ol.order_id,
        ol.quantity_ordered,
        ol.line_total
    from {{ ref('stg_orders__order_lines') }} ol
    join {{ ref('stg_orders__orders') }} o
        on ol.order_id = o.order_id
    left join variant_products vp
        on ol.variant_id = vp.variant_id
    left join products p_direct
        on ol.product_id = p_direct.product_id
    left join products p_variant
        on vp.product_id = p_variant.product_id
    where o.status not in ('CANCELLED', 'RETURNED', 'FAILED')

),

sales as (

    select
        product_id,
        count(distinct order_id) as total_orders,
        coalesce(sum(quantity_ordered), 0) as units_sold,
        coalesce(sum(line_total), 0) as product_revenue
    from valid_order_lines
    group by 1

)

select
    p.product_id,
    p.product_name,
    c.category_name as category,
    coalesce(s.total_orders, 0) as total_orders,
    coalesce(s.units_sold, 0) as units_sold,
    coalesce(s.product_revenue, 0) as product_revenue,
    case
        when coalesce(s.units_sold, 0) > 0 then s.product_revenue / s.units_sold
        else null
    end as avg_unit_price,
    coalesce(v.total_variants, 0) as total_variants
from products p
left join sales s
    on p.product_id = s.product_id
left join categories c
    on p.primary_category_id = c.category_id
left join variants v
    on p.product_id = v.product_id
order by product_revenue desc
