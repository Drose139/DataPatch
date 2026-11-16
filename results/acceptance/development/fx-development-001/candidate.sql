-- operator_reviewed
{{ config(materialized='table', tags=['mart','finance','revenue']) }}
-- Keep the existing (order_date, currency_code, source_system) grain.
-- Each order first gets its latest payment timestamp, with order-date fallback.
-- A daily row uses the latest resulting settlement date in its group.
with payment_dates as (
    select order_id, max(processed_at) as latest_settlement_at
    from {{ ref('stg_orders__order_payments') }}
    group by order_id
), sales_with_settlement as (
    select s.*, coalesce(cast(p.latest_settlement_at as date), s.order_date) as sale_settlement_date
    from {{ ref('fct_sales') }} s
    left join payment_dates p on s.order_id=p.order_id
), daily_sales as (


    select
        order_date,
        max(sale_settlement_date) as settlement_date,
        currency_code,
        source_system,

        -- Order counts
        count(distinct order_id) as total_orders,
        count(distinct customer_id) as unique_customers,
        count(order_line_id) as total_line_items,

        -- Revenue metrics
        sum(extended_price) as gross_revenue,
        sum(discount_amount) as total_discounts,
        sum(extended_price - discount_amount) as net_revenue,
        sum(tax_amount) as total_tax,
        sum(line_total) as total_revenue,

        -- Average metrics
        avg(unit_price) as avg_unit_price,
        avg(extended_price) as avg_line_value,

        -- Quantity metrics
        sum(quantity_ordered) as total_units_ordered,
        sum(quantity_shipped) as total_units_shipped,

        -- Fulfillment metrics
        count(case when is_fully_shipped then 1 end) as fully_shipped_lines,
        count(case when is_cancelled then 1 end) as cancelled_lines

    from sales_with_settlement
    where order_date is not null
    group by
        order_date,
        currency_code,
        source_system

),

rates_by_day as (
    select rate_date, from_currency, max(rate) as rate
    from {{ ref('dim_exchange_rates') }}
    where to_currency='USD' and rate > 0
    group by rate_date, from_currency
), rated_sales as (
    select d.*, cast(case when d.currency_code='USD' then 1
                         else coalesce(r.rate, 1) end as decimal(18,6)) as fx_rate
    from daily_sales d
    left join lateral (
        -- Exact settlement date first, otherwise the latest available prior day.
        -- If no past rate exists, use the earliest future rate before the final 1 fallback.
        select rate from rates_by_day r
        where r.from_currency=d.currency_code
        order by case when r.rate_date<=d.settlement_date then 0 else 1 end,
                 case when r.rate_date<=d.settlement_date then r.rate_date end desc,
                 r.rate_date asc
        limit 1
    ) r on true
), final as (

    select
        -- Date dimension
        order_date,
        extract(year from order_date) as year,
        extract(month from order_date) as month,
        extract(quarter from order_date) as quarter,
        extract(dayofweek from order_date) as day_of_week,
        extract(week from order_date) as week_of_year,

        settlement_date,
        fx_rate,
        cast(round(net_revenue * fx_rate, 2) as decimal(38,2)) as net_revenue_usd,
        cast(round(total_revenue * fx_rate, 2) as decimal(38,2)) as total_revenue_usd,

        -- Dimensions
        currency_code,
        source_system,

        -- Counts
        total_orders,
        unique_customers,
        total_line_items,

        -- Revenue
        gross_revenue,
        total_discounts,
        net_revenue,
        total_tax,
        total_revenue,

        -- Averages
        avg_unit_price,
        avg_line_value,
        case
            when total_orders > 0
            then total_revenue / total_orders
            else 0
        end as avg_order_value,

        -- Units
        total_units_ordered,
        total_units_shipped,

        -- Fulfillment rates
        case
            when total_line_items > 0
            then (fully_shipped_lines::decimal / total_line_items::decimal)
            else 0
        end as fulfillment_rate,

        case
            when total_line_items > 0
            then (cancelled_lines::decimal / total_line_items::decimal)
            else 0
        end as cancellation_rate,

        -- Discount rate
        case
            when gross_revenue > 0
            then (total_discounts / gross_revenue)
            else 0
        end as discount_rate,

        -- Metadata
        current_timestamp as dbt_updated_at

    from rated_sales

)

select * from final
