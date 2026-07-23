# CPG Pulse — Metric Definitions

Every metric below is either a column that already exists in a dbt mart (so
the "SQL logic" section is literally copied from the running model) or a
simple aggregation over one that any API/dashboard consumer can compute.
Where a metric is inherently period-relative (growth, contribution) it is
**not** pre-materialized as a stored column — it's computed at query time,
because "growth vs. what period" and "contribution within what scope" are
consumer decisions, not warehouse facts.

All dollar figures are in the synthetic dataset's implied currency (no
multi-currency handling exists — see `docs/runbook.md` known limitations).

---

## Units Sold

**Business meaning:** Total consumer-facing product volume moved through
retail POS.

**Formula:** `SUM(units_sold)`

**Required tables:** `marts.fact_retail_sales`

**SQL:**
```sql
SELECT SUM(units_sold) AS units_sold
FROM marts.fact_retail_sales
WHERE transaction_date BETWEEN :start_date AND :end_date
```

**Assumptions:** Excludes direct-to-consumer e-commerce (`fact_ecommerce_orders.units_ordered`
is a separate figure — see "E-commerce Sales Share" for the combined view).

---

## Gross Sales

**Business meaning:** Revenue at regular (non-discounted) price.

**Formula:** `SUM(gross_sales)` where `gross_sales = units_sold * regular_price`
(computed at generation/standardization time, not derived here).

**Required tables:** `marts.fact_retail_sales`

**SQL:** `SELECT SUM(gross_sales) FROM marts.fact_retail_sales WHERE ...`

**Assumptions:** "Regular price" is the retailer's own everyday shelf price
for that SKU (`dim_retailer_product_mapping` era), not MSRP.

---

## Net Sales

**Business meaning:** Actual revenue recognized, after promotional/trade discounts.

**Formula:** `SUM(net_sales)` where `net_sales = gross_sales - discount_amount`.

**Required tables:** `marts.fact_retail_sales`

**SQL:** `SELECT SUM(net_sales) FROM marts.fact_retail_sales WHERE ...`

**Assumptions:** Does not net out returns (retail POS in this dataset has no
return/refund concept — only the DTC e-commerce channel tracks `return_flag`).

---

## Average Selling Price (ASP)

**Business meaning:** Revenue-weighted average price actually paid per unit
(distinct from a simple average of `selling_price` across transactions,
which would over-weight low-volume transactions).

**Formula:** `SUM(net_sales) / NULLIF(SUM(units_sold), 0)`

**Required tables:** `marts.fact_retail_sales`

**SQL:**
```sql
SELECT SUM(net_sales) / NULLIF(SUM(units_sold), 0) AS asp
FROM marts.fact_retail_sales
WHERE transaction_date BETWEEN :start_date AND :end_date
```

**Assumptions:** `api/services/sales_service.py`'s `/sales/summary` endpoint
instead reports `AVG(selling_price)` (a simple, per-row average) for
simplicity/consistency with its GROUP BY structure — the two will differ
slightly whenever unit volume correlates with price within the group. Use the
revenue-weighted formula above for anything margin- or finance-adjacent.

---

## Discount Rate

**Business meaning:** Share of gross revenue given up to discounting.

**Formula:** `SUM(discount_amount) / NULLIF(SUM(gross_sales), 0)`

**Required tables:** `marts.fact_retail_sales`

**SQL:** implemented directly in `api/services/sales_service.py::sales_summary()`:
```sql
round(sum(fs.discount_amount) / nullif(sum(fs.gross_sales), 0), 4) AS discount_rate
```

**Assumptions:** None beyond gross_sales > 0.

---

## Sales Growth

**Business meaning:** Percent change in net sales between two comparable periods.

**Formula:** `(net_sales_current_period / net_sales_prior_period - 1) * 100`

**Required tables:** `marts.fact_retail_sales`

**SQL:** No stored column — call `/sales/summary` twice with two non-overlapping
date ranges and compute client-side (this is what the Executive Overview
dashboard page's date-range picker enables, though the page itself currently
shows point-in-time totals, not a growth delta — see `docs/runbook.md` for
this as a documented near-term enhancement).

**Assumptions:** "Comparable period" (same length, ideally same seasonality)
is left to the caller — the warehouse has no opinion on what counts as a fair
comparison.

---

## Sales Velocity

**Business meaning:** How fast a SKU is actually selling, right now, at a
given store — the demand-side input to stockout/excess-inventory risk.

**Formula:** Trailing 14-day average daily units sold, computed as-of each
inventory snapshot date (not a simple day-count average — see the model's own
comment for why a fixed 14-day denominator is used instead of counting
observed sale-days).

**Required tables:** `marts.fact_retail_sales`, `marts.fact_inventory_snapshot`

**SQL:** `dbt/models/intermediate/int_daily_velocity.sql`:
```sql
round(units_recent / 14.0, 3) AS avg_daily_units_sold
```
where `units_recent` sums `fact_retail_sales.units_sold` over the 14 days
ending on the snapshot date, for that exact `(product_id, store_id)`.

**Assumptions:** A 14-day window is a fixed constant in the model, not a
`dbt_project.yml` var (unlike the stockout/excess thresholds) — changing it
requires editing the SQL directly. Also produces `velocity_trend`
(ACCELERATING/STABLE/DECLINING/NEW_DEMAND/NO_DEMAND) by comparing this window
to the prior 14 days.

---

## Sell-Through Rate

**Business meaning:** Of the inventory available to sell in a period, what
fraction actually sold — the inverse framing of excess inventory.

**Formula:** `units_sold_in_period / (units_sold_in_period + ending_available_units)`

**Required tables:** `marts.fact_retail_sales`, `marts.fact_inventory_snapshot`

**SQL:** Not a stored column — compute by joining the two facts on
`(product_id, store_id)` for a given period:
```sql
WITH sold AS (
    SELECT product_id, store_id, SUM(units_sold) AS units_sold
    FROM marts.fact_retail_sales
    WHERE transaction_date BETWEEN :start AND :end
    GROUP BY 1, 2
),
ending_inventory AS (
    SELECT DISTINCT ON (product_id, store_id) product_id, store_id, available_units
    FROM marts.fact_inventory_snapshot
    WHERE snapshot_date <= :end
    ORDER BY product_id, store_id, snapshot_date DESC
)
SELECT s.product_id, s.store_id,
       s.units_sold::numeric / NULLIF(s.units_sold + COALESCE(i.available_units, 0), 0) AS sell_through_rate
FROM sold s LEFT JOIN ending_inventory i USING (product_id, store_id)
```

**Assumptions:** Ignores inbound replenishment mid-period (a store that
received a large shipment mid-period will show an artificially low
sell-through rate under this simple framing). A production version would use
average inventory across the period, not just the ending snapshot.

---

## Inventory Turnover

**Business meaning:** How many times inventory is sold and replaced over a period.

**Formula:** `units_sold_in_period / average_on_hand_units_in_period`

**Required tables:** `marts.fact_retail_sales`, `marts.fact_inventory_snapshot`

**SQL:**
```sql
WITH sold AS (
    SELECT product_id, store_id, SUM(units_sold) AS units_sold
    FROM marts.fact_retail_sales
    WHERE transaction_date BETWEEN :start AND :end
    GROUP BY 1, 2
),
avg_inventory AS (
    SELECT product_id, store_id, AVG(on_hand_units) AS avg_on_hand
    FROM marts.fact_inventory_snapshot
    WHERE snapshot_date BETWEEN :start AND :end
    GROUP BY 1, 2
)
SELECT s.product_id, s.store_id, s.units_sold::numeric / NULLIF(a.avg_on_hand, 0) AS inventory_turnover
FROM sold s JOIN avg_inventory a USING (product_id, store_id)
```

**Assumptions:** Uses units, not dollar cost-of-goods (a common alternate
turnover formula uses COGS / average inventory value) — this dataset has
`unit_cost` on `dim_product` if a dollar-based version is needed instead.

---

## Days of Supply / Weeks of Supply

**Business meaning:** At current sell-through velocity, how many days (or
weeks) until available inventory runs out. The core input to stockout and
excess-inventory risk classification (docs/architecture.md "Stockout Risk
Logic" / "Excess Inventory Logic").

**Formula:** `days_of_supply = available_units / avg_daily_units_sold`;
`weeks_of_supply = days_of_supply / 7`.

**Required tables:** `marts.fact_inventory_snapshot`, `intermediate.int_daily_velocity`

**SQL:** `dbt/models/marts/analytics/mart_stockout_risk.sql` and
`mart_excess_inventory_risk.sql`:
```sql
case when v.avg_daily_units_sold > 0
    then round(i.available_units / v.avg_daily_units_sold, 1)
end as days_of_supply
```

**Risk thresholds** (`dbt_project.yml` vars, business-user-tunable without a
code change):
- `stockout_high_risk_days_of_supply` = 3 → **HIGH** risk below this
- `stockout_medium_risk_days_of_supply` = 7 → **MEDIUM** risk below this, else **LOW**
- `excess_inventory_days_of_supply_threshold` = 45 → **EXCESS** above this
  (or **CRITICAL** if velocity is also DECLINING)
- Zero/null velocity → **NO_RECENT_DEMAND**, not a misleadingly low risk score

**Assumptions:** Uses the 14-day trailing velocity from `int_daily_velocity`,
not a longer-window or seasonally-adjusted demand forecast — a real
replenishment system would also factor in open purchase orders and supplier
lead time, which this dataset's `on_order_units` column captures but the risk
formula does not yet incorporate (see `docs/runbook.md` known limitations).

---

## Out-of-Stock Rate

**Business meaning:** Share of (product, store, date) observations where
available inventory was zero.

**Formula:** `COUNT(*) WHERE available_units = 0 / COUNT(*)`, or equivalently
the HIGH-risk share from `mart_stockout_risk`.

**Required tables:** `marts.fact_inventory_snapshot` or `marts.mart_stockout_risk`

**SQL:**
```sql
SELECT COUNT(*) FILTER (WHERE available_units = 0)::numeric / NULLIF(COUNT(*), 0) AS out_of_stock_rate
FROM marts.fact_inventory_snapshot
WHERE snapshot_date BETWEEN :start AND :end
```
The retailer- and product-scorecard marts instead report `high_stockout_risk_rate`
(share of snapshots at HIGH risk, i.e. <3 days of supply, a leading indicator)
rather than this strict "already at zero" trailing measure — both are valid,
answering slightly different questions ("are we about to run out" vs. "did we
already run out").

**Assumptions:** None beyond snapshot cadence being frequent enough to catch
stockouts (this dataset's snapshots are weekly — see `docs/runbook.md`).

---

## Excess Inventory Rate

**Business meaning:** Share of (product, store) observations classified as
carrying more inventory than the sell-through rate justifies.

**Formula:** `COUNT(*) WHERE excess_inventory_risk_level IN ('EXCESS','CRITICAL') / COUNT(*)`

**Required tables:** `marts.mart_excess_inventory_risk`

**SQL:**
```sql
SELECT COUNT(*) FILTER (WHERE excess_inventory_risk_level IN ('EXCESS', 'CRITICAL'))::numeric
       / NULLIF(COUNT(*), 0) AS excess_inventory_rate
FROM marts.mart_excess_inventory_risk
```

**Assumptions:** See Days of Supply above — the 45-day threshold is a var,
not hardcoded, and doesn't yet account for product-specific shelf life
(docs/architecture.md's Excess Inventory Logic section calls this out as a
"use if available" input that isn't in this dataset).

---

## Shipment-to-POS Variance

**Business meaning:** How far manufacturer shipments into a retailer's DC
diverge from consumer POS sell-through for the same product/week — the
reconciliation signal for detecting stockout risk, inventory buildup, or
reporting delays before they show up anywhere else.

**Formula:** `variance_units = units_shipped - units_sold`;
`variance_pct = variance_units / units_sold`

**Required tables:** `marts.fact_shipments`, `marts.fact_retail_sales`

**SQL:** `dbt/models/marts/analytics/mart_shipment_pos_reconciliation.sql`,
grain `retailer_id x product_id x week_start`, built via a `FULL OUTER JOIN`
(deliberately — a week with shipments but no POS match, or vice versa, is
itself a signal, not something to drop via an inner join). Signal
classification:
```sql
case
    when units_shipped = 0 and units_sold > 0 then 'MISSING_SHIPMENT_DATA_OR_REPORTING_DELAY'
    when units_sold = 0 and units_shipped > 0 then 'MISSING_POS_DATA_OR_REPORTING_DELAY'
    when units_shipped > units_sold * 1.3 then 'SHIPMENTS_OUTPACING_SALES_INVENTORY_BUILDUP'
    when units_sold > units_shipped * 1.3 then 'SALES_OUTPACING_SHIPMENTS_POTENTIAL_STOCKOUT'
    else 'ALIGNED'
end as reconciliation_signal
```

**Assumptions:** The 1.3x (30%) threshold for "outpacing" is hardcoded in
the model, not a `dbt_project.yml` var — a reasonable next enhancement.
Shipments are DC-level (retailer x product x week), while POS is store-level
rolled up to the same grain — this masks store-level reconciliation gaps
that net out at the retailer level (documented in `docs/runbook.md`).

---

## Order-to-Delivery Lead Time

**Business meaning:** How long a manufacturer shipment actually took vs. its
estimate — a supply-chain reliability signal.

**Formula:** `delivery_variance_days = actual_delivery_date - estimated_delivery_date`
(positive = late, negative = early).

**Required tables:** `marts.fact_shipments`

**SQL:** computed at the staging layer (`dbt/models/staging/stg_manufacturer_shipments.sql`)
and carried through to the fact:
```sql
case when actual_delivery_date is not null
    then (actual_delivery_date::date - estimated_delivery_date::date)
end as delivery_variance_days
```
Aggregate lead time itself (`shipment_date` to `actual_delivery_date`) is not
pre-computed but is a one-line query:
```sql
SELECT AVG(actual_delivery_date - shipment_date) AS avg_lead_time_days
FROM marts.fact_shipments
WHERE actual_delivery_date IS NOT NULL
```

**Assumptions:** `NULL` for `IN_TRANSIT`/`CANCELLED` shipments (no actual
delivery date yet/ever) — excluded from averages by the `WHERE` clause above,
not counted as zero.

---

## Promotion Lift, Incremental Promotion Units, Promotion ROI

**⚠️ These are analytical estimates, not causal-inference results.** See
`dbt/models/marts/analytics/mart_promotion_effectiveness.sql`'s own header
comment (reproduced in relevant part below) and the **Known Limitations**
section at the end of this document.

**Business meaning:**
- *Incremental units*: how many more units sold during a promotion than
  would have sold anyway (the promotion's true demand-generation effect).
- *Lift %*: incremental units as a percentage of the estimated baseline.
- *ROI*: incremental revenue generated per dollar of discount + marketing
  spend invested in the promotion.

**Formula:**
```
expected_baseline_units = baseline_avg_daily_units * promotion_duration_days
incremental_units       = actual_promo_units - expected_baseline_units
lift_percentage          = (actual_promo_units / expected_baseline_units - 1) * 100
discount_cost             = (regular_price - promotional_price) * actual_promo_units
promotion_roi              = (incremental_units * promotional_price)
                              / ((regular_price - promotional_price) * actual_promo_units + marketing_spend)
```

**Required tables:** `marts.dim_promotion`, `marts.fact_promotions`,
`marts.fact_retail_sales`, `intermediate.int_promotion_baseline`

**Baseline methodology** (`dbt/models/intermediate/int_promotion_baseline.sql`):
average daily POS sell-through over the `promotion_baseline_lookback_weeks`
(dbt var, default 8 weeks = 56 days) immediately *before* the promotion
started, **excluding** any day that itself fell inside a different promotion
for that same retailer/product (otherwise a recent unrelated promotion would
inflate the baseline and understate this one's true lift).

**Assumptions and limitations (state these explicitly wherever this metric
is surfaced):**
- No control group. There is no comparable set of stores/regions *without*
  the promotion running to isolate the promotion's effect from concurrent
  factors (seasonality beyond what the pre-period happens to reflect,
  competitor activity, macro trends). Pre-period demand is the best available
  proxy for counterfactual demand, not a substitute for a real experiment.
- **Sample-size sensitive.** Validated during Phase 6 development: on the
  small 2-month `data/sample` dataset, most promotions don't have the full
  56-day pre-period available (the dataset barely started), producing
  wildly inflated lift figures (avg >2000%). Regenerating a 7-month test
  dataset — where 45/128 promotions got the full 56-day lookback — produced
  a median lift of ~117%, closely tracking the synthetic generator's
  injected ground-truth lift range of 40-180%. **Treat lift/ROI figures as
  unreliable for any promotion whose `baseline_days` (also exposed on the
  API/mart) is well under 56.**
- `lift_percentage` is `NULL` (not zero) when `baseline_avg_daily_units` is
  `NULL` — insufficient pre-period data, not "no lift."

---

## Return Rate

**Business meaning:** Share of direct-to-consumer orders that were returned.

**Formula:** `COUNT(*) WHERE return_flag / COUNT(*)`

**Required tables:** `marts.fact_ecommerce_orders`

**SQL:**
```sql
SELECT COUNT(*) FILTER (WHERE return_flag)::numeric / NULLIF(COUNT(*), 0) AS return_rate
FROM marts.fact_ecommerce_orders
WHERE order_date BETWEEN :start AND :end
```

**Assumptions:** Only defined for the DTC e-commerce channel — retail POS
(`fact_retail_sales`) has no return/refund concept in this dataset's source
schema (matches the original spec's field list for that source).

---

## E-commerce Sales Share

**Business meaning:** What fraction of total sales happen through
e-commerce-ish channels (retailer online/marketplace pickup-delivery, plus
CPG Pulse's own DTC storefront) vs. physical in-store.

**Formula:** `net_sales(channel_type != 'Physical Retail') / net_sales(all channels)`

**Required tables:** `marts.mart_omnichannel_performance` (unifies
`fact_retail_sales` + `fact_ecommerce_orders` — see
`dbt/models/intermediate/int_product_daily_sales.sql`)

**SQL:** (as implemented in `dashboard/app.py`):
```python
ecommerce_net_sales = sum(r["net_sales"] for r in omnichannel if r["channel_type"] in {"E-commerce", "Marketplace", "Omnichannel"})
total_net_sales = sum(r["net_sales"] for r in omnichannel)
ecommerce_share = ecommerce_net_sales / total_net_sales
```

**Assumptions:** "Omnichannel" (retailer-operated online/pickup/delivery) is
counted on the e-commerce side of the split — a defensible but not the only
reasonable choice; a stricter definition might count only `MARKETPLACE` +
`DTC_ECOMMERCE` ("truly online-only") and treat "Omnichannel" as its own
third bucket.

---

## Retailer Contribution

**Business meaning:** Each retailer's share of total net sales.

**Formula:** `retailer_net_sales / SUM(net_sales) OVER ()`

**Required tables:** `marts.fact_retail_sales` (or `marts.mart_retailer_scorecard`
for a pre-aggregated starting point)

**SQL:**
```sql
SELECT retailer_id,
       SUM(net_sales) AS retailer_net_sales,
       SUM(net_sales) / SUM(SUM(net_sales)) OVER () AS retailer_contribution
FROM marts.fact_retail_sales
WHERE transaction_date BETWEEN :start AND :end
GROUP BY retailer_id
```

**Assumptions:** None. Not currently exposed as a dedicated API field —
computable from `/sales/summary?group_by=retailer`'s `net_sales` column
divided by the sum across all returned rows.

---

## Category Contribution

**Business meaning:** Each product category's share of total net sales.

**Formula:** `category_net_sales / SUM(net_sales) OVER ()`

**Required tables:** `marts.fact_retail_sales` joined to `marts.dim_product` (current)

**SQL:** same pattern as Retailer Contribution, grouped by `dim_product.category`
instead — directly available via `/sales/summary?group_by=category`.

**Assumptions:** Uses each product's *current* category (`dim_product WHERE is_current`)
even for historical sales — a product's category reassignment (tracked by the
SCD2 snapshot) is not applied point-in-time here. A stricter historical view
would join on the SCD2 version effective as of `transaction_date`.

---

## Data Freshness

**Business meaning:** How stale a given source's data is right now.

**Formula:** `now() - MAX(business_date)` for a source, or the DQ engine's
`freshness` check type: `(today - MAX(date_column)).days <= max_lag_days`.

**Required tables:** Any fact table (business-date freshness) or
`pipeline_meta.pipeline_runs` (pipeline-run recency).

**SQL (DQ engine check, `spark/quality/dq_engine.py::_run_check`, type=`freshness`):**
```python
lag_days = (dt.date.today() - max_date).days
passed = lag_days <= max_lag_days
```
Configured per-suite in YAML (`spark/quality/expectations/*.yml`), e.g.
`retail_pos_sales`: `max_lag_days: 3`; `retail_inventory`: `max_lag_days: 10`
(inventory snapshots are weekly in this dataset, so a looser threshold is
correct — see `docs/runbook.md`).

**Assumptions:** Compares against `dt.date.today()` (wall-clock date), which
means freshness checks against this project's **synthetic, backdated 2025
data** will always report as extremely stale if actually run — this is
expected and correct behavior for the check itself, not a bug; it's simply
not meaningful to run a freshness check against fixed historical demo data
(see `docs/runbook.md`).

---

## Data-Quality Pass Rate

**Business meaning:** What fraction of automated data-quality checks passed,
overall or for a given table/check category.

**Formula:** `COUNT(*) WHERE passed / COUNT(*)`

**Required tables:** `marts.fact_data_quality_results` (sourced from
`pipeline_meta.dq_results`, copied into the warehouse's `landing` schema by
`scripts/load_to_warehouse.py` — see `docs/source_to_target_mapping.md`)

**SQL:** `dbt/models/marts/analytics/mart_data_quality_summary.sql`:
```sql
select
    table_name, check_category,
    count(*) as total_checks_run,
    count(*) filter (where passed) as checks_passed,
    round(count(*) filter (where passed)::numeric / nullif(count(*), 0), 4) as pass_rate
from marts.fact_data_quality_results
group by 1, 2
```

**Assumptions:** Empty (no rows) until `spark/jobs/run_quality_checks.py` has
actually executed at least once — this table was **never populated** in this
project's development environment (PySpark jobs were never executed on the
Windows development host — see `docs/remaining_work.md` §5). The API and
dashboard both handle this as an explicit empty state, not an error.

---

## Known Limitations Summary (metrics-specific)

- Every "period" metric (growth, sell-through, turnover) requires the caller
  to choose a date range and comparison basis — the warehouse provides the
  raw facts, not an opinion about what date ranges are meaningful.
- Promotion lift/ROI is the metric most likely to be over-interpreted — it is
  explicitly an estimate, is sample-size sensitive, and has no control group.
  Never present it without that caveat.
- Category/brand contribution uses current dimension attributes, not
  point-in-time SCD2 versions, for simplicity.
- No currency conversion, no tax handling, no multi-currency support anywhere
  in this dataset or these formulas.
