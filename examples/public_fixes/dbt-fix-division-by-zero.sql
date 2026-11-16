-- operator_reviewed
-- Reviewed delivery artifact; not a new autonomous model run.
{{
    config(
        materialized='table',
        tags=['mart', 'customer', 'metrics']
    )
}}

/*
    Customer Metrics Report
    Ticket: DATA-6001 - Model producing invalid values

    Fixes:
      1. All divisions guarded with NULLIF (no inf/nan)
      2. NULL customer_id excluded from source
      3. Removed the `total_revenue > 0` filter that dropped valid customers
      4. Time windows are relative to MAX(ordered_at) in the data, not CURRENT_DATE

    New analytics:
      - customer_engagement_score (0-100)
      - churn_risk_score (0-100)
      - customer_value_rank / customer_value_percentile / above_median_revenue
      - ltv_tier (waterfall: vip > platinum > gold > silver > bronze > at_risk > inactive)
*/

with source_orders as (

    select
        customer_id,
        grand_total,
        ordered_at,
        status
    from {{ ref('int_sales__orders_enriched') }}
    where customer_id is not null
      and status != 'CANCELLED'

),

reference_date as (

    -- Reference date = most recent order date in the data (never CURRENT_DATE)
    select
        max(ordered_at) as ref_ts,
        cast(max(ordered_at) as date) as ref_date
    from {{ ref('int_sales__orders_enriched') }}

),

customer_orders as (

    select
        o.customer_id,
        count(*) as total_orders,
        sum(o.grand_total) as total_revenue,
        cast(min(o.ordered_at) as date) as first_order_date,
        cast(max(o.ordered_at) as date) as last_order_date,
        {% if target.type == 'duckdb' %}
        count(case when o.ordered_at >= r.ref_ts - interval '30' day then 1 end) as orders_last_30d,
        count(case when o.ordered_at >= r.ref_ts - interval '90' day then 1 end) as orders_last_90d,
        count(case when o.ordered_at >= r.ref_ts - interval '180' day then 1 end) as orders_last_180d,
        sum(case when o.ordered_at >= r.ref_ts - interval '30' day then o.grand_total else 0 end) as revenue_last_30d,
        sum(case when o.ordered_at >= r.ref_ts - interval '90' day then o.grand_total else 0 end) as revenue_last_90d,
        {% else %}
        count(case when o.ordered_at >= dateadd('day', -30, r.ref_ts) then 1 end) as orders_last_30d,
        count(case when o.ordered_at >= dateadd('day', -90, r.ref_ts) then 1 end) as orders_last_90d,
        count(case when o.ordered_at >= dateadd('day', -180, r.ref_ts) then 1 end) as orders_last_180d,
        sum(case when o.ordered_at >= dateadd('day', -30, r.ref_ts) then o.grand_total else 0 end) as revenue_last_30d,
        sum(case when o.ordered_at >= dateadd('day', -90, r.ref_ts) then o.grand_total else 0 end) as revenue_last_90d,
        {% endif %}
        r.ref_date
    from source_orders o
    cross join reference_date r
    group by o.customer_id, r.ref_date

),

customer_metrics as (

    select
        customer_id,
        total_orders,
        total_revenue,
        first_order_date,
        last_order_date,
        {% if target.type == 'duckdb' %}
        cast(date_diff('day', last_order_date, ref_date) as integer) as days_since_last_order,
        {% else %}
        cast(datediff('day', last_order_date, ref_date) as integer) as days_since_last_order,
        {% endif %}
        orders_last_30d,
        orders_last_90d,
        orders_last_180d,
        revenue_last_30d,
        revenue_last_90d,

        -- revenue per order (denominator is always >= 1, NULLIF kept for safety)
        total_revenue / nullif(total_orders, 0) as avg_order_value,

        -- orders per month over the customer's observed lifetime
        {% if target.type == 'duckdb' %}
        total_orders / nullif(date_diff('month', first_order_date, ref_date), 0) as orders_per_month,
        {% else %}
        total_orders / nullif(datediff('month', first_order_date, ref_date), 0) as orders_per_month,
        {% endif %}

        revenue_last_30d / nullif(revenue_last_90d, 0) as revenue_velocity_ratio,

        orders_last_30d / nullif(orders_last_90d, 0) as order_frequency_trend

    from customer_orders

),

-- median revenue of the whole population (scalar aggregate: works on DuckDB and Snowflake)
median_revenue as (

    select
        median(cast(total_revenue as double)) as median_total_revenue
    from customer_metrics

),

scored as (

    select
        m.*,
        md.median_total_revenue,

        -- peer comparison
        percent_rank() over (order by m.total_revenue asc) as revenue_percentile,
        dense_rank() over (order by m.total_revenue desc) as customer_value_rank

    from customer_metrics m
    cross join median_revenue md

),

final as (

    select
        s.customer_id,
        s.total_orders,
        s.total_revenue,
        s.first_order_date,
        s.last_order_date,
        s.days_since_last_order,
        s.orders_last_30d,
        s.orders_last_90d,
        s.orders_last_180d,
        s.revenue_last_30d,
        s.revenue_last_90d,
        s.avg_order_value,
        s.orders_per_month,
        s.revenue_velocity_ratio,
        s.order_frequency_trend,

        -- Engagement score (0-100): recency 30%, frequency 35%, monetary 35%
        -- NULL days_since_last_order -> 365 days (recency factor = 0); other NULLs -> 0
        least(100.0, greatest(0.0,
            (
                least(1.0, greatest(0.0, (365 - coalesce(s.days_since_last_order, 365)) / 365.0)) * 0.30
              + least(1.0, greatest(0.0, coalesce(s.orders_per_month, 0) / 5.0)) * 0.35
              + coalesce(s.revenue_percentile, 0) * 0.35
            ) * 100.0
        )) as customer_engagement_score,

        -- Churn risk score (0-100): inactivity 40%, declining orders 30%, declining revenue 30%
        -- NULL days_since_last_order -> treated as maximally inactive (factor 1.0)
        least(100.0, greatest(0.0,
            (
                least(1.0, greatest(0.0, coalesce(s.days_since_last_order, 365) / 365.0)) * 0.40
              + (1.0 - least(1.0, greatest(0.0, coalesce(s.order_frequency_trend, 0)))) * 0.30
              + (1.0 - least(1.0, greatest(0.0, coalesce(s.revenue_velocity_ratio, 0)))) * 0.30
            ) * 100.0
        )) as churn_risk_score,

        s.customer_value_rank,
        s.revenue_percentile as customer_value_percentile,
        case when s.total_revenue > s.median_total_revenue then 1 else 0 end as above_median_revenue,

        -- LTV tier waterfall (order matters)
        case
            when coalesce(s.revenue_percentile, 0) >= 0.95
                 and s.orders_last_90d > 0
                 and s.total_orders >= 10 then 'vip'
            when coalesce(s.revenue_percentile, 0) >= 0.90
                 and s.orders_last_180d > 0 then 'platinum'
            when coalesce(s.revenue_percentile, 0) >= 0.75
                 or s.avg_order_value > 500 then 'gold'
            when s.total_orders >= 3 and s.total_revenue > 100 then 'silver'
            when s.total_orders >= 1 and s.total_revenue > 50 then 'bronze'
            when s.total_orders > 0 and s.days_since_last_order > 365 then 'at_risk'
            else 'inactive'
        end as ltv_tier

    from scored s

)

select * from final
