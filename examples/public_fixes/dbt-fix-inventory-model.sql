-- operator_reviewed
-- Reviewed delivery artifact; not a new autonomous model run.
/*
================================================================================
MODEL: rpt_product_inventory_metrics
AUTHOR: Tyler Brooks
CREATED: 2024-02-15
LAST MODIFIED: 2024-11-20 by Marcus Johnson

DESCRIPTION:
Product-level inventory performance metrics including turnover ratios,
stockout analysis, inventory health tier and inventory velocity score.

KNOWN ISSUES:
  - Performance: Full refresh takes ~8 minutes on large datasets
  - TODO: Add warehouse-level breakdown

CHANGE LOG:
  2024-11-20: Added days_of_supply calculation (Marcus)
  2024-08-10: Fixed COGS join issue (Tyler)
  2024-02-15: Initial creation (Tyler)
================================================================================
*/

with inventory_levels as (
    select * from {{ ref('stg_inventory__inventory_levels') }}
),

inventory_transactions as (
    select * from {{ ref('stg_inventory__inventory_transactions') }}
),

-- Reference date for all rolling windows: latest transaction date in the data
-- (never CURRENT_DATE, so results are stable regardless of run date)
reference as (
    select max(transaction_date) as reference_date
    from inventory_transactions
),

-- Aggregate inventory at product level
product_inventory as (
    select
        il.variant_id as product_id,
        sum(il.quantity_on_hand) as total_quantity_on_hand,
        sum(il.quantity_available) as total_quantity_available,
        sum(il.quantity_reserved) as total_quantity_reserved,
        sum(il.quantity_on_hand * il.unit_cost) as total_inventory_value,
        avg(il.unit_cost) as avg_unit_cost,
        count(distinct il.warehouse_id) as warehouse_count,
        count(case when il.inventory_status = 'OUT_OF_STOCK' then 1 end) as stockout_location_count,
        count(distinct il.inventory_id) as total_locations,
        max(il.last_received_at) as last_received_date,
        max(il.last_picked_at) as last_picked_date
    from inventory_levels il
    group by il.variant_id
),

-- Calculate COGS from outbound transactions (365 days before reference date).
-- PICK quantities are stored with inconsistent signs, so use the absolute
-- picked quantity to obtain real units sold / demand (avoids near-zero or
-- negative denominators that produced inf/nan metrics).
product_cogs as (
    select
        it.variant_id as product_id,
        sum(abs(it.quantity) * it.unit_cost) as cogs_365d,
        sum(abs(it.quantity)) as units_sold_365d,
        count(distinct it.transaction_date) as selling_days
    from inventory_transactions it
    cross join reference r
    where it.transaction_type = 'PICK'
      and it.transaction_date >= r.reference_date - interval '365' day
      and it.transaction_date <= r.reference_date
    group by it.variant_id
),

-- Calculate average inventory value (simplified - using current snapshot)
avg_inventory as (
    select
        il.variant_id as product_id,
        avg(il.quantity_on_hand * il.unit_cost) as avg_inventory_value_365d
    from inventory_levels il
    group by il.variant_id
),

-- Calculate daily demand for days of supply
daily_demand as (
    select
        it.variant_id as product_id,
        sum(abs(it.quantity)) / 365.0 as avg_daily_demand
    from inventory_transactions it
    cross join reference r
    where it.transaction_type = 'PICK'
      and it.transaction_date >= r.reference_date - interval '365' day
      and it.transaction_date <= r.reference_date
    group by it.variant_id
),

-- Combine all metrics (all source products kept; denominators guarded)
product_metrics as (
    select
        pi.product_id,
        cast(null as varchar) as product_name,
        cast(null as varchar) as product_code,
        cast(null as varchar) as category_id,
        cast(null as varchar) as lifecycle_status,
        cast(null as varchar) as abc_classification,

        -- Inventory quantities
        coalesce(pi.total_quantity_on_hand, 0) as total_quantity_on_hand,
        coalesce(pi.total_quantity_available, 0) as total_quantity_available,
        coalesce(pi.total_quantity_reserved, 0) as total_quantity_reserved,
        coalesce(pi.total_inventory_value, 0) as total_inventory_value,
        coalesce(pi.avg_unit_cost, 0) as avg_unit_cost,
        coalesce(pi.warehouse_count, 0) as warehouse_count,

        -- Sales metrics
        coalesce(pc.cogs_365d, 0) as cogs_365d,
        coalesce(pc.units_sold_365d, 0) as units_sold_365d,
        coalesce(pc.selling_days, 0) as selling_days,

        pc.cogs_365d / nullif(ai.avg_inventory_value_365d, 0) as turnover_ratio,

        pi.total_inventory_value / nullif(pc.units_sold_365d, 0) as inventory_value_per_unit_sold,

        -- Stockout metrics
        coalesce(pi.stockout_location_count, 0) as stockout_location_count,
        coalesce(pi.total_locations, 0) as total_locations,

        100.0 * pi.stockout_location_count / nullif(pi.total_locations, 0) as stockout_rate,

        pi.total_quantity_on_hand / nullif(dd.avg_daily_demand, 0) as days_of_supply,

        -- Activity dates
        pi.last_received_date,
        pi.last_picked_date,

        -- Days since activity (relative to reference date)
        date_diff('day', pi.last_picked_date, r.reference_date) as days_since_last_pick,
        date_diff('day', pi.last_received_date, r.reference_date) as days_since_last_receipt

    from product_inventory pi
    left join product_cogs pc on pi.product_id = pc.product_id
    left join avg_inventory ai on pi.product_id = ai.product_id
    left join daily_demand dd on pi.product_id = dd.product_id
    cross join reference r
    where pi.product_id is not null
),

-- Window metrics used for classification and velocity scoring
metrics_scored as (
    select
        pm.*,
        percent_rank() over (order by pm.turnover_ratio) as turnover_percent_rank,
        med.median_turnover_ratio
    from product_metrics pm
    cross join (
        select median(turnover_ratio) as median_turnover_ratio
        from product_metrics
    ) med
)

select
    product_id,
    product_name,
    product_code,
    category_id,
    lifecycle_status,
    abc_classification,
    total_quantity_on_hand,
    total_quantity_available,
    total_quantity_reserved,
    round(total_inventory_value, 2) as total_inventory_value,
    round(avg_unit_cost, 2) as avg_unit_cost,
    warehouse_count,
    round(cogs_365d, 2) as cogs_365d,
    units_sold_365d,
    selling_days,
    round(turnover_ratio, 4) as turnover_ratio,
    round(inventory_value_per_unit_sold, 2) as inventory_value_per_unit_sold,
    stockout_location_count,
    total_locations,
    round(stockout_rate, 2) as stockout_rate,
    round(days_of_supply, 1) as days_of_supply,
    last_received_date,
    last_picked_date,
    days_since_last_pick,
    days_since_last_receipt,

    -- Inventory health tier (waterfall: first match wins)
    case
        when turnover_percent_rank >= 0.90
             and days_of_supply < 7
             and units_sold_365d > 0
            then 'critical'
        when stockout_rate > 15
             or (days_of_supply < 14 and units_sold_365d > 0)
             or stockout_location_count > total_locations / 2.0
            then 'at_risk'
        when turnover_ratio > median_turnover_ratio
             and stockout_rate < 5
             and days_of_supply between 14 and 84
            then 'healthy'
        else 'overstock'
    end as inventory_health_tier,

    -- Velocity score (0-100): 40% turnover rank + 30% sell-through + 30% recency
    round(
        (
            coalesce(turnover_percent_rank, 0) * 0.4
            + coalesce(
                units_sold_365d
                / nullif(units_sold_365d + greatest(total_quantity_on_hand, 0), 0),
                0
              ) * 0.3
            + (case
                   when days_since_last_pick <= 7 then 1.0
                   when days_since_last_pick <= 30 then 0.7
                   when days_since_last_pick <= 90 then 0.4
                   else 0.1
               end) * 0.3
        ) * 100
    , 2) as velocity_score
from metrics_scored
