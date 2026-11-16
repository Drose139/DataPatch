-- operator_reviewed
-- Preserve all source orders and the original model materialization.
-- Aggregate before joining a complete inclusive calendar; missing days are zero.
with orders as (
    select * from {{ ref('stg_orders__orders') }}
), bounds as (
    select cast(min(ordered_at) as date) as first_day,
           cast(max(ordered_at) as date) as last_day
    from orders
), calendar as (
{% if target.type == 'snowflake' %}
    select dateadd(day, offset_day, first_day)::date as order_date
    from bounds, lateral (
        select row_number() over (order by seq4()) - 1 as offset_day
        from table(generator(rowcount => 100000))
    ) where offset_day <= datediff(day, first_day, last_day)
{% else %}
    select cast(day as date) as order_date
    from bounds, lateral generate_series(first_day, last_day, interval '1 day') as dates(day)
{% endif %}
), daily as (
    select cast(ordered_at as date) as order_date,
           count(distinct order_id) as total_orders,
           count(distinct customer_id) as unique_customers,
           sum(grand_total) as total_revenue,
           sum(subtotal) as subtotal_revenue,
           sum(discount_total) as total_discounts,
           sum(shipping_total) as total_shipping,
           sum(tax_total) as total_tax,
           avg(grand_total) as avg_order_value
    from orders
    group by 1
), complete_daily as (
    select c.order_date,
           coalesce(d.total_orders, 0) as total_orders,
           coalesce(d.unique_customers, 0) as unique_customers,
           coalesce(d.total_revenue, 0) as total_revenue,
           coalesce(d.subtotal_revenue, 0) as subtotal_revenue,
           coalesce(d.total_discounts, 0) as total_discounts,
           coalesce(d.total_shipping, 0) as total_shipping,
           coalesce(d.total_tax, 0) as total_tax,
           coalesce(d.avg_order_value, 0) as avg_order_value
    from calendar c left join daily d on c.order_date = d.order_date
)
select *, sum(total_revenue) over (
    order by order_date rows between unbounded preceding and current row
) as cumulative_revenue
from complete_daily
order by order_date
