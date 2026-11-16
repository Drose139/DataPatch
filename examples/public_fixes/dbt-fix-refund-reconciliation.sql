-- operator_reviewed
-- Reviewed delivery artifact; not a new autonomous model run.
{{
    config(
        materialized='table',
        tags=['mart', 'sales', 'returns']
    )
}}

with return_lines_agg as (
    select
        rl.return_id,
        count(*) as return_line_count,
        sum(rl.refund_amount) as total_refund_amount
    from {{ ref('stg_orders__return_lines') }} rl
    group by rl.return_id
),

returns_base as (
    select
        r.return_id,
        r.return_number,
        r.order_id,
        r.customer_id,
        r.return_type,
        r.refund_method,
        r.status,
        r.refund_amount as total_return_amount,
        coalesce(rla.total_refund_amount, 0) as total_refund_amount_lines,
        coalesce(rla.return_line_count, 0) as return_line_count,
        r.requested_at as requested_at,
        r.received_at as received_at,
        r.processed_at as processed_at
    from {{ ref('stg_orders__returns') }} r
    left join return_lines_agg rla on r.return_id = rla.return_id
),

with_timing as (
    select
        *,
        date_diff('day', requested_at, received_at) as days_to_receive,
        date_diff('day', received_at, processed_at) as days_to_process,
        date_diff('day', requested_at, processed_at) as total_processing_days,
        -- ratio: NULL when the denominator is zero or the amounts are NULL (no inf/NaN)
        {{ safe_divide('total_refund_amount_lines', 'total_return_amount') }} as refund_completion_rate,
        -- efficiency: NULL when the denominator is zero (same day) (no inf/NaN)
        {{ safe_divide('1.0', 'total_processing_days') }} as processing_efficiency
    from returns_base
),

-- percentiles computed only over non-NULL processing days
processing_rank as (
    select
        return_id,
        percent_rank() over (order by total_processing_days desc) as processing_pct_rank
    from with_timing
    where total_processing_days is not null
),

with_rank as (
    select
        t.*,
        pr.processing_pct_rank
    from with_timing t
    left join processing_rank pr on t.return_id = pr.return_id
)

select
    return_id,
    return_number,
    order_id,
    customer_id,
    return_type,
    refund_method,
    status,
    total_return_amount,
    total_refund_amount_lines as total_refund_amount,
    return_line_count,
    requested_at,
    received_at,
    processed_at,
    days_to_receive,
    days_to_process,
    total_processing_days,
    refund_completion_rate,
    processing_efficiency,
    -- waterfall classification, first match wins
    case
        when processing_pct_rank <= 0.25
             and coalesce(total_processing_days, 0) > 10
            then 'critical_delay'
        when processing_pct_rank <= 0.50
             or coalesce(refund_completion_rate, 0) < 0.80
            then 'needs_improvement'
        when coalesce(refund_completion_rate, 0) >= 0.85
             and coalesce(total_processing_days, 2147483647) <= 7
            then 'acceptable'
        when processing_pct_rank >= 0.75
             and coalesce(refund_completion_rate, 0) >= 0.90
            then 'efficient'
        else 'acceptable'
    end as refund_velocity_tier
from with_rank
