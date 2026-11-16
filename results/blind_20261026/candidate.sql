WITH shipment_metrics AS (
    SELECT
        carrier_id,
        COUNT(*) as total_shipments,
        COUNT(CASE WHEN status = 'DELIVERED' THEN 1 END) as delivered_shipments,
        COUNT(CASE WHEN status = 'IN_TRANSIT' THEN 1 END) as in_transit_shipments,
        COUNT(CASE WHEN status = 'CANCELLED' THEN 1 END) as cancelled_shipments,
        SUM(SHIPPING_COST) as total_shipping_cost,
        SUM(SHIPPING_COST) / COUNT(*) as avg_shipping_cost,
        SUM(WEIGHT) as total_weight,
        SUM(WEIGHT) / COUNT(*) as avg_weight,
        AVG(date_diff('day', SHIPPED_AT, DELIVERED_AT)) as avg_delivery_days,
        MIN(date_diff('day', SHIPPED_AT, DELIVERED_AT)) as min_delivery_days,
        MAX(date_diff('day', SHIPPED_AT, DELIVERED_AT)) as max_delivery_days,
        COUNT(CASE
            WHEN status = 'DELIVERED'
            AND date_diff('day', SHIPPED_AT, DELIVERED_AT) <= 7
            THEN 1
        END) as on_time_shipments
    FROM main.stg_orders__shipments
    WHERE carrier_id IS NOT NULL
    GROUP BY carrier_id
),

-- primary shipping method = the method with the most shipments for this carrier
primary_method AS (
    SELECT carrier_id, shipping_method_id
    FROM (
        SELECT
            carrier_id,
            shipping_method_id,
            ROW_NUMBER() OVER (
                PARTITION BY carrier_id
                ORDER BY COUNT(*) DESC, shipping_method_id
            ) as rn
        FROM main.stg_orders__shipments
        WHERE carrier_id IS NOT NULL
        GROUP BY carrier_id, shipping_method_id
    ) t
    WHERE rn = 1
),

carrier_base AS (
    SELECT
        sm.carrier_id,
        pm.shipping_method_id,
        sm.total_shipments,
        sm.delivered_shipments,
        sm.in_transit_shipments,
        sm.cancelled_shipments,
        sm.total_shipping_cost,
        sm.avg_shipping_cost,
        sm.total_weight,
        sm.avg_weight,
        sm.avg_delivery_days,
        sm.min_delivery_days,
        sm.max_delivery_days,
        sm.on_time_shipments,
        CASE
            WHEN sm.delivered_shipments = 0 THEN NULL
            ELSE sm.on_time_shipments::DOUBLE / sm.delivered_shipments
        END as on_time_delivery_rate,
        CASE
            WHEN sm.total_shipments = 0 THEN NULL
            ELSE sm.delivered_shipments::DOUBLE / sm.total_shipments
        END as delivery_completion_rate
    FROM shipment_metrics sm
    LEFT JOIN primary_method pm
        ON sm.carrier_id = pm.carrier_id
),

medians AS (
    SELECT
        MEDIAN(avg_shipping_cost) as median_cost,
        MEDIAN(total_shipments) as median_volume
    FROM carrier_base
),

ranked AS (
    SELECT
        b.*,
        m.median_cost,
        m.median_volume,
        PERCENT_RANK() OVER (ORDER BY b.avg_delivery_days DESC NULLS FIRST) as speed_percentile,
        PERCENT_RANK() OVER (ORDER BY b.avg_shipping_cost DESC NULLS FIRST) as cost_percentile,
        RANK() OVER (
            PARTITION BY b.shipping_method_id
            ORDER BY b.avg_delivery_days ASC NULLS LAST, b.carrier_id
        ) as peer_rank,
        COUNT(*) OVER (PARTITION BY b.shipping_method_id) as peer_count,
        PERCENT_RANK() OVER (
            PARTITION BY b.shipping_method_id
            ORDER BY b.avg_delivery_days DESC NULLS FIRST
        ) as peer_speed_percentile,
        AVG(b.on_time_delivery_rate) OVER (PARTITION BY b.shipping_method_id) as peer_avg_on_time_rate
    FROM carrier_base b
    CROSS JOIN medians m
),

with_tiers AS (
    SELECT
        *,
        CASE
            WHEN speed_percentile <= 0.30 AND COALESCE(avg_delivery_days, 0) > 8 THEN 'critical'
            WHEN speed_percentile <= 0.60 OR COALESCE(on_time_delivery_rate, 0) < 0.75 THEN 'needs_improvement'
            WHEN speed_percentile >= 0.80 AND COALESCE(on_time_delivery_rate, 0) >= 0.92 THEN 'excellent'
            WHEN COALESCE(on_time_delivery_rate, 0) >= 0.85 AND COALESCE(avg_delivery_days, 999) <= 5 THEN 'good'
            ELSE 'good'
        END as delivery_speed_tier,
        CASE
            WHEN cost_percentile >= 0.80 AND COALESCE(delivery_completion_rate, 0) >= 0.90 THEN 'premium'
            WHEN cost_percentile >= 0.60 AND avg_shipping_cost < median_cost THEN 'economical'
            WHEN cost_percentile >= 0.30 THEN 'standard'
            ELSE 'expensive'
        END as cost_tier
    FROM ranked
),

with_factors AS (
    SELECT
        *,
        GREATEST(0.0, LEAST(1.0, COALESCE(delivery_completion_rate, 0))) as fulfillment_factor,
        GREATEST(0.0, LEAST(1.0, 1 - (COALESCE(avg_delivery_days, 14) / 14.0))) as speed_factor,
        GREATEST(0.0, LEAST(1.0, COALESCE(on_time_delivery_rate, 0))) as on_time_factor,
        CASE
            WHEN median_cost IS NULL OR median_cost = 0 THEN 1.0
            ELSE GREATEST(0.0, LEAST(1.0,
                1 - ((COALESCE(avg_shipping_cost, median_cost) - median_cost) / median_cost)
            ))
        END as cost_factor,
        CASE
            WHEN avg_delivery_days IS NULL OR avg_delivery_days = 0 THEN 1.0
            WHEN max_delivery_days IS NULL OR min_delivery_days IS NULL THEN 1.0
            ELSE GREATEST(0.0, LEAST(1.0,
                1 - (((max_delivery_days - min_delivery_days)::DOUBLE / avg_delivery_days) / 2.0)
            ))
        END as speed_consistency,
        CASE
            WHEN b.median_volume IS NULL OR b.median_volume <= 0 THEN 1.0
            ELSE LEAST(1.0, b.total_shipments::DOUBLE / b.median_volume)
        END as volume_factor
    FROM with_tiers b
)

SELECT
    carrier_id,
    shipping_method_id,
    total_shipments,
    delivered_shipments,
    in_transit_shipments,
    cancelled_shipments,
    total_shipping_cost,
    avg_shipping_cost,
    total_weight,
    avg_weight,
    avg_delivery_days,
    min_delivery_days,
    max_delivery_days,
    on_time_shipments,
    on_time_delivery_rate,
    delivery_completion_rate,
    speed_percentile,
    cost_percentile,
    delivery_speed_tier,
    cost_tier,
    peer_rank,
    peer_count,
    CASE WHEN on_time_delivery_rate > peer_avg_on_time_rate THEN 1 ELSE 0 END as above_peer_avg,
    peer_speed_percentile,
    GREATEST(0.0, LEAST(100.0,
        (0.30 * fulfillment_factor
         + 0.25 * speed_factor
         + 0.25 * on_time_factor
         + 0.20 * cost_factor) * 100.0
    )) as carrier_efficiency_index,
    GREATEST(0.0, LEAST(100.0,
        (0.40 * GREATEST(0.0, LEAST(1.0, COALESCE(delivery_completion_rate, 0)))
         + 0.30 * speed_consistency
         + 0.30 * volume_factor) * 100.0
    )) as carrier_reliability_index
FROM with_factors
