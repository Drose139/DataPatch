-- operator_reviewed: repair from the public ticket and initial DuckDB model.
-- Preserve all source rows, output columns, amounts and view materialization.
-- Align POS local wall-clock timestamps to the SAP clock with the stated +5h.
{{ config(materialized='view', tags=['intermediate', 'sales']) }}

{% set clean_currency = "regexp_replace(CAST(%s AS VARCHAR), '[^0-9.-]', '', 'g')::decimal(18,2)" %}

{% set timestamp_expression %}
    coalesce(
        try_cast(nullif(trim(cast(timestamp_value as varchar)), '') as timestamp),
        try_strptime(trim(cast(timestamp_value as varchar)), '%m/%d/%Y %H:%M:%S'),
        try_strptime(trim(cast(timestamp_value as varchar)), '%m/%d/%Y'),
        try_strptime(trim(cast(timestamp_value as varchar)), '%d/%m/%Y %H:%M:%S'),
        try_strptime(trim(cast(timestamp_value as varchar)), '%d/%m/%Y'),
        try_strptime(trim(cast(timestamp_value as varchar)), '%Y%m%d'),
        timezone('UTC', to_timestamp(try_cast(nullif(trim(cast(timestamp_value as varchar)), '') as double)))
    )
{% endset %}

with sap_orders as (
    select
        order_id,
        order_number,
        customer_id,
        order_type,
        'SAP' as source_system,
        currency_code,
        exchange_rate,
        {{ clean_currency % 'subtotal' }} as subtotal,
        {{ clean_currency % 'discount_total' }} as discount_total,
        {{ clean_currency % 'shipping_total' }} as shipping_total,
        {{ clean_currency % 'tax_total' }} as tax_total,
        {{ clean_currency % 'grand_total' }} as grand_total,
        status,
        payment_status,
        fulfillment_status,
        {{ timestamp_expression | replace('timestamp_value', 'ordered_at') }} as ordered_at,
        {{ timestamp_expression | replace('timestamp_value', 'shipped_at') }} as shipped_at,
        {{ timestamp_expression | replace('timestamp_value', 'delivered_at') }} as delivered_at,
        {{ timestamp_expression | replace('timestamp_value', 'cancelled_at') }} as cancelled_at
    from {{ ref('stg_sap__vbak') }}
),

pos_orders as (
    select
        order_id,
        order_number,
        customer_id,
        order_type,
        'POS' as source_system,
        currency_code,
        exchange_rate,
        {{ clean_currency % 'subtotal' }} as subtotal,
        {{ clean_currency % 'discount_total' }} as discount_total,
        {{ clean_currency % 'shipping_total' }} as shipping_total,
        {{ clean_currency % 'tax_total' }} as tax_total,
        {{ clean_currency % 'grand_total' }} as grand_total,
        status,
        payment_status,
        fulfillment_status,
        {{ timestamp_expression | replace('timestamp_value', 'ordered_at') }} + interval '5 hours' as ordered_at,
        {{ timestamp_expression | replace('timestamp_value', 'shipped_at') }} + interval '5 hours' as shipped_at,
        {{ timestamp_expression | replace('timestamp_value', 'delivered_at') }} + interval '5 hours' as delivered_at,
        {{ timestamp_expression | replace('timestamp_value', 'cancelled_at') }} + interval '5 hours' as cancelled_at
    from {{ ref('stg_pos__transactions') }}
),

all_orders as (
    select * from sap_orders
    union all
    select * from pos_orders
),

final as (
    select
        order_id,
        order_number,
        customer_id,
        order_type,
        source_system,
        currency_code,
        exchange_rate,
        subtotal,
        discount_total,
        shipping_total,
        tax_total,
        grand_total,
        subtotal - discount_total as net_subtotal,
        case when subtotal > 0 then discount_total / subtotal else 0 end as discount_rate,
        status,
        payment_status,
        fulfillment_status,
        ordered_at,
        shipped_at,
        delivered_at,
        cancelled_at,
        cancelled_at is not null as is_cancelled,
        delivered_at is not null as is_delivered,
        case
            when delivered_at is not null and ordered_at is not null
            then date_diff('day', ordered_at, delivered_at)
            else null
        end as days_to_fulfill
    from all_orders
)

select * from final
