-- operator_reviewed
-- Implemented from the public cohort-retention-matrix instruction and the
-- pinned customer/orders source definitions. No reference solution or tests
-- were used to construct this SQL. Model API calls for this patch: 0.
{{ config(materialized='table', schema='marketing_analytics') }}

{% set retained_months = [0, 1, 2, 3, 6, 12] %}

with customers as (
    select
        customer_id,
        date_trunc('month', created_at) as signup_month,
        coalesce(nullif(trim(acquisition_source), ''), 'UNKNOWN') as acquisition_source
    from {{ source('customer', 'CUSTOMERS') }}
),

-- Channel eligibility is based on all signups, not one monthly cohort or
-- customers who happen to have placed an order.
eligible_channels as (
    select acquisition_source
    from customers
    group by acquisition_source
    having count(*) >= 10
),

valid_orders as (
    select
        order_id,
        customer_id,
        ordered_at,
        coalesce(grand_total, 0) as revenue,
        row_number() over (
            partition by customer_id
            order by ordered_at, order_id
        ) as purchase_number
    from {{ source('orders', 'ORDERS') }}
    where status = 'COMPLETED'
      and not coalesce(test_order_flag, false)
      and not coalesce(sample_order_flag, false)
      and not coalesce(internal_order_flag, false)
),

activity as (
    select
        c.customer_id,
        c.signup_month,
        c.acquisition_source,
        o.order_id,
        o.ordered_at,
        o.purchase_number,
        o.revenue,
        date_diff('month', c.signup_month, date_trunc('month', o.ordered_at)) as month_offset
    from customers c
    join eligible_channels e on c.acquisition_source = e.acquisition_source
    left join valid_orders o on c.customer_id = o.customer_id
),

-- One row per signed-up customer preserves nonbuyers and makes all retained
-- flags distinct-customer counts when the cohort sums them below.
customer_summary as (
    select
        customer_id,
        signup_month,
        acquisition_source,
        case when count(order_id) = 0 then 1 else 0 end as never_ordered,
        {% for month in retained_months %}
        max(case when month_offset = {{ month }} then 1 else 0 end) as m{{ month }}_retained,
        sum(case when month_offset = {{ month }} then revenue else 0 end) as m{{ month }}_revenue,
        {% if month > 0 %}
        max(case when month_offset between 0 and {{ month }} then 1 else 0 end) as m{{ month }}_cumulative,
        {% endif %}
        {% endfor %}
        case
            when max(case when month_offset = 0 then 1 else 0 end) = 1
             and max(case when month_offset > 0 then 1 else 0 end) = 0
            then 1 else 0
        end as early_churned,
        coalesce(sum(revenue), 0) as lifetime_revenue,
        min(case when purchase_number = 1 then ordered_at end) as first_purchase_at,
        min(case when purchase_number = 2 then ordered_at end) as second_purchase_at
    from activity
    group by customer_id, signup_month, acquisition_source
)

select
    strftime(signup_month, '%Y-%m') as cohort_month,
    acquisition_source,
    count(*) as cohort_size,
    sum(never_ordered) as never_ordered_count,
    {% for month in retained_months %}
    sum(m{{ month }}_retained) as m{{ month }}_retained,
    coalesce(sum(m{{ month }}_revenue), 0) as m{{ month }}_revenue,
    coalesce(round(100.0 * sum(m{{ month }}_retained) / nullif(count(*), 0), 2), 0.00) as m{{ month }}_rate,
    {% if month > 0 %}
    sum(m{{ month }}_cumulative) as m{{ month }}_cumulative,
    {% endif %}
    {% endfor %}
    sum(early_churned) as early_churned_count,
    round(sum(lifetime_revenue) / nullif(count(*), 0), 2) as cohort_ltv,
    avg(date_diff('day', first_purchase_at, second_purchase_at)) as avg_days_to_second_purchase
from customer_summary
group by signup_month, acquisition_source
order by cohort_month, acquisition_source
