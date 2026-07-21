"""Core transactional simulation: POS sales, inventory snapshots, and
manufacturer shipments.

Design (documented because it is the least obvious part of the generator):

1. For each (retailer, product) pair that is actively carried, and for each
   store of that retailer, we compute an *unconstrained daily demand* array
   fully vectorized over the date range (seasonality x day-of-week x holiday x
   promotion x a per-pair random anomaly window x product/store popularity x
   Poisson noise). No sequential dependency is needed for this step.
2. Demand is aggregated to weekly totals per store. A short **sequential loop
   over weeks only** (not days) runs a simple inventory state machine per pair,
   vectorized across that pair's stores: each week the store receives a
   replenishment (driven by a pair-level "replenishment factor" time series
   that is deliberately made too low for some pairs -- simulating shipment
   lag/stockouts -- and too high for others -- simulating overship/excess
   inventory), sells min(demand, available), and carries leftover forward.
3. The resulting weekly sold/demand ratio is broadcast back onto the daily
   demand array to produce final daily `units_sold` for POS -- so a stockout
   week visibly suppresses several days of sales rather than being an
   independent random event, which is what makes the stockout-risk and
   shipment-reconciliation analytics in later phases meaningful.
4. Manufacturer shipments are the retailer/product/week replenishment
   quantities aggregated across stores and split into 1-2 shipment lines to a
   distribution center.

This is an approximation of real CPG supply-chain dynamics, not a full
physical simulation -- it is intentionally just rich enough to produce
internally-consistent stockout, excess-inventory, and shipment-variance
signals for the analytics layers built in later phases.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from .config import CATEGORIES, DISTRIBUTION_CENTERS, GeneratorConfig
from .promotions import promo_lookup_index

DOW_WEIGHTS = np.array([1.00, 1.00, 1.02, 1.05, 1.20, 1.35, 1.15])  # Mon..Sun

SEASONALITY_CURVES = {
    "summer_peak": {6: 1.25, 7: 1.35, 8: 1.30, 12: 0.9},
    "winter_peak": {12: 1.3, 1: 1.25, 2: 1.1, 7: 0.85},
    "summer_peak_icecream": {6: 1.4, 7: 1.5, 8: 1.4, 1: 0.7, 2: 0.7},
    "flat": {},
}

def _seasonality_factor(category: str, month: int) -> float:
    curve = SEASONALITY_CURVES[CATEGORIES[category]["seasonality"]]
    return curve.get(month, 1.0)


def _week_index_bounds(n_days: int) -> list[tuple[int, int]]:
    """Return [(day_start_idx, day_end_idx_exclusive), ...] chunking n_days into weeks."""
    bounds = []
    i = 0
    while i < n_days:
        j = min(i + 7, n_days)
        bounds.append((i, j))
        i = j
    return bounds


def simulate_transactions(
    cfg: GeneratorConfig,
    retailers: pd.DataFrame,
    stores: pd.DataFrame,
    products: pd.DataFrame,
    mapping: pd.DataFrame,
    price_table: pd.DataFrame,
    promotions: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    rng = cfg.rng("simulate")
    dates = cfg.date_list
    date_arr = np.array(dates)
    months = np.array([d.month for d in dates])
    dows = np.array([d.weekday() for d in dates])

    region_dc = {dc["region"]: dc["distribution_center_id"] for dc in DISTRIBUTION_CENTERS}
    promo_idx = promo_lookup_index(promotions)

    # Per-product/per-store fixed popularity multipliers (stable across the whole run).
    pop_rng = cfg.rng("popularity")
    product_popularity = {
        pid: float(pop_rng.lognormal(mean=0.0, sigma=0.6)) for pid in products["product_id"]
    }
    vol_rng = cfg.rng("store_volume")
    store_format_base = {"Supercenter": 1.6, "General Merchandise": 1.2, "Neighborhood Grocery": 0.8, "Online Fulfillment Center": 2.2}
    store_volume_index = {}
    for row in stores.itertuples():
        base = store_format_base.get(row.store_format, 1.0)
        store_volume_index[row.store_id] = base * float(vol_rng.lognormal(mean=0.0, sigma=0.3))

    products_idx = products.set_index("product_id")

    pos_cols = {k: [] for k in [
        "retailer_id", "store_id", "retailer_product_id", "transaction_date",
        "units_sold", "gross_sales", "discount_amount", "net_sales",
        "regular_price", "selling_price", "sales_channel",
    ]}
    inv_cols = {k: [] for k in [
        "retailer_id", "store_id", "retailer_product_id", "snapshot_date",
        "on_hand_units", "on_order_units", "reserved_units", "available_units",
    ]}
    ship_rows = []
    lag_rng = cfg.rng("shipment_lag")
    ship_seq = 1

    for retailer_id in retailers["retailer_id"]:
        retailer_stores = stores[stores["retailer_id"] == retailer_id]
        # each retailer's currently-carried products, using the mapping's most
        # recent segment as of the *end* of the window to decide "does this
        # retailer carry this product at all during the window" (segments
        # handle the actual date-effective retailer_product_id).
        retailer_map = mapping[mapping["retailer_id"] == retailer_id]
        carried_products = retailer_map["product_id"].unique()

        for product_id in carried_products:
            prod = products_idx.loc[product_id]
            category = prod["category"]
            launch_date = prod["launch_date"]
            discontinued_date = prod["discontinued_date"]

            segs = retailer_map[retailer_map["product_id"] == product_id].sort_values("effective_start_date")
            price_row = price_table[(price_table["retailer_id"] == retailer_id) & (price_table["product_id"] == product_id)]
            if price_row.empty:
                continue
            regular_price = float(price_row["regular_price"].iloc[0])

            # active date mask for this (retailer, product): product must be
            # launched & not discontinued, and window must be inside the run's
            # date range.
            active_start = max(cfg.start_date, launch_date)
            active_end = cfg.end_date if pd.isna(discontinued_date) or discontinued_date is None else min(cfg.end_date, discontinued_date - dt.timedelta(days=1))
            if active_start > active_end:
                continue
            start_idx = (active_start - cfg.start_date).days
            end_idx = (active_end - cfg.start_date).days + 1
            if end_idx <= start_idx:
                continue
            active_dates = date_arr[start_idx:end_idx]
            active_months = months[start_idx:end_idx]
            active_dows = dows[start_idx:end_idx]
            n_active = len(active_dates)

            # retailer_product_id effective for each active day
            rpid_for_day = np.empty(n_active, dtype=object)
            for seg in segs.itertuples():
                seg_start = max(seg.effective_start_date, active_start)
                seg_end = seg.effective_end_date if pd.notna(seg.effective_end_date) and seg.effective_end_date is not None else active_end
                seg_end = min(seg_end, active_end)
                if seg_start > seg_end:
                    continue
                s = (seg_start - active_start).days
                e = (seg_end - active_start).days + 1
                rpid_for_day[s:e] = seg.retailer_product_id

            # day-level promo lift & price
            promo_price = np.full(n_active, regular_price)
            promo_lift = np.ones(n_active)
            for p_start, p_end, p_price, p_lift in promo_idx.get((retailer_id, product_id), []):
                s = max(0, (p_start - active_start).days)
                e = min(n_active, (p_end - active_start).days + 1)
                if s >= e:
                    continue
                promo_price[s:e] = p_price
                promo_lift[s:e] = p_lift

            # Holiday demand bump is intentionally not modeled day-by-day here (that
            # would require a per-day calendar lookup inside this hot loop); the
            # `seasonality` curves below already carry the Nov/Dec and summer
            # upticks that matter for the categories in this catalog, which keeps
            # this simulation self-contained and fast.
            holiday_bump = np.ones(n_active)

            seasonality = np.array([_seasonality_factor(category, m) for m in active_months])
            dow_factor = DOW_WEIGHTS[active_dows]

            # pair-level anomaly window (spike or drop) affecting all stores of this pair
            anomaly_mult = np.ones(n_active)
            roll = lag_rng.random()
            if roll < cfg.dq_issue_rates["anomaly_spike_pair_rate"]:
                w = int(lag_rng.integers(3, 10))
                s = int(lag_rng.integers(0, max(1, n_active - w)))
                anomaly_mult[s : s + w] *= lag_rng.uniform(3.0, 6.0)
            elif roll < cfg.dq_issue_rates["anomaly_spike_pair_rate"] + cfg.dq_issue_rates["anomaly_drop_pair_rate"]:
                w = int(lag_rng.integers(3, 10))
                s = int(lag_rng.integers(0, max(1, n_active - w)))
                anomaly_mult[s : s + w] *= lag_rng.uniform(0.05, 0.3)

            # replenishment factor time series (weekly), shared by every store of this pair
            week_bounds = _week_index_bounds(n_active)
            n_weeks = len(week_bounds)
            replen_factor = np.clip(lag_rng.normal(1.05, 0.12, size=n_weeks), 0.6, 1.6)
            lag_roll = lag_rng.random()
            if lag_roll < cfg.dq_issue_rates["shipment_lag_pair_rate"]:
                w = int(lag_rng.integers(3, min(10, n_weeks) + 1)) if n_weeks > 3 else n_weeks
                s = int(lag_rng.integers(0, max(1, n_weeks - w)))
                replen_factor[s : s + w] *= lag_rng.uniform(0.35, 0.65)
            elif lag_roll < cfg.dq_issue_rates["shipment_lag_pair_rate"] + cfg.dq_issue_rates["shipment_overship_pair_rate"]:
                w = int(lag_rng.integers(3, min(10, n_weeks) + 1)) if n_weeks > 3 else n_weeks
                s = int(lag_rng.integers(0, max(1, n_weeks - w)))
                replen_factor[s : s + w] *= lag_rng.uniform(1.5, 2.1)

            pair_stores = retailer_stores[
                (retailer_stores["opening_date"] <= active_end)
                & (retailer_stores["closing_date"].isna() | (retailer_stores["closing_date"] >= active_start))
            ]
            if pair_stores.empty:
                continue
            store_ids = pair_stores["store_id"].tolist()
            n_stores = len(store_ids)

            base_daily_lambda = 3.0 * product_popularity[product_id]
            store_vol = np.array([store_volume_index[sid] for sid in store_ids])
            store_noise_rng = cfg.rng(f"store_noise::{retailer_id}::{product_id}")
            store_noise = store_noise_rng.uniform(0.8, 1.2, size=n_stores)

            # (n_stores, n_active) unconstrained demand lambda
            daily_factor = seasonality * dow_factor * promo_lift * anomaly_mult * holiday_bump
            lambda_2d = np.outer(store_vol * store_noise, base_daily_lambda * daily_factor)
            demand_2d = rng.poisson(np.clip(lambda_2d, 0.01, None)).astype(float)

            # weekly aggregation
            weekly_demand = np.zeros((n_stores, n_weeks))
            for wi, (s, e) in enumerate(week_bounds):
                weekly_demand[:, wi] = demand_2d[:, s:e].sum(axis=1)

            # sequential weekly inventory state machine (vectorized across stores)
            on_hand = np.zeros(n_stores)
            scale_factor = np.ones((n_stores, n_weeks))
            weekly_replen_qty = np.zeros((n_stores, n_weeks))
            for wi in range(n_weeks):
                target = weekly_demand[:, wi] * replen_factor[wi]
                weekly_replen_qty[:, wi] = target
                on_hand_start = on_hand + target
                sold = np.minimum(weekly_demand[:, wi], on_hand_start)
                leftover = on_hand_start - sold
                with np.errstate(divide="ignore", invalid="ignore"):
                    sf = np.where(weekly_demand[:, wi] > 0, sold / np.maximum(weekly_demand[:, wi], 1e-9), 1.0)
                scale_factor[:, wi] = np.clip(sf, 0.0, 1.0)
                on_hand = leftover

            # broadcast weekly scale factor back to daily, compute final units_sold
            scale_daily = np.zeros((n_stores, n_active))
            for wi, (s, e) in enumerate(week_bounds):
                scale_daily[:, s:e] = scale_factor[:, wi : wi + 1]
            units_sold_2d = np.round(demand_2d * scale_daily).astype(int)

            # recompute leftover on_hand per week for the inventory snapshot output
            on_hand = np.zeros(n_stores)
            for wi, (s, e) in enumerate(week_bounds):
                on_hand_start = on_hand + weekly_replen_qty[:, wi]
                sold = units_sold_2d[:, s:e].sum(axis=1)
                leftover = np.maximum(on_hand_start - sold, 0.0)
                snap_date = active_dates[s]
                reserved = np.round(leftover * cfg.rng(f"reserved::{retailer_id}::{product_id}::{wi}").uniform(0.0, 0.08, size=n_stores))
                available = np.maximum(leftover - reserved, 0.0)
                on_order = weekly_replen_qty[:, wi + 1] if wi + 1 < n_weeks else np.zeros(n_stores)

                for si, sid in enumerate(store_ids):
                    rpid = rpid_for_day[s] if s < len(rpid_for_day) else None
                    if rpid is None:
                        continue
                    inv_cols["retailer_id"].append(retailer_id)
                    inv_cols["store_id"].append(sid)
                    inv_cols["retailer_product_id"].append(rpid)
                    inv_cols["snapshot_date"].append(snap_date)
                    inv_cols["on_hand_units"].append(int(leftover[si]))
                    inv_cols["on_order_units"].append(int(round(on_order[si])))
                    inv_cols["reserved_units"].append(int(reserved[si]))
                    inv_cols["available_units"].append(int(available[si]))
                on_hand = leftover

            # POS sales rows (skip zero-unit days ~ realistic: not every SKU sells at every store every day)
            channel_pool_in_store = "IN_STORE"
            channel_pool_online = "RETAILER_ONLINE" if retailer_id != "RTL-AMZ" else "MARKETPLACE"
            for si, sid in enumerate(store_ids):
                units_row = units_sold_2d[si]
                nz = np.nonzero(units_row)[0]
                for i in nz:
                    rpid = rpid_for_day[i]
                    if rpid is None:
                        continue
                    units = int(units_row[i])
                    sp = float(promo_price[i])
                    channel = channel_pool_online if (retailer_id == "RTL-AMZ" or rng.random() < 0.18) else channel_pool_in_store
                    gross = round(units * regular_price, 2)
                    net = round(units * sp, 2)
                    discount = round(max(gross - net, 0.0), 2)
                    pos_cols["retailer_id"].append(retailer_id)
                    pos_cols["store_id"].append(sid)
                    pos_cols["retailer_product_id"].append(rpid)
                    pos_cols["transaction_date"].append(active_dates[i])
                    pos_cols["units_sold"].append(units)
                    pos_cols["gross_sales"].append(gross)
                    pos_cols["discount_amount"].append(discount)
                    pos_cols["net_sales"].append(net)
                    pos_cols["regular_price"].append(regular_price)
                    pos_cols["selling_price"].append(sp)
                    pos_cols["sales_channel"].append(channel)

            # shipments: aggregate weekly replenishment across this pair's stores -> DC lines
            majority_region = pair_stores["region"].mode()
            region = majority_region.iloc[0] if not majority_region.empty else "Midwest"
            dc_id = region_dc.get(region, DISTRIBUTION_CENTERS[0]["distribution_center_id"])
            for wi, (s, e) in enumerate(week_bounds):
                total_units = int(round(weekly_replen_qty[:, wi].sum()))
                if total_units <= 0:
                    continue
                n_lines = 1 if total_units < 500 else int(lag_rng.integers(1, 3))
                remaining = total_units
                for line in range(n_lines):
                    line_units = remaining if line == n_lines - 1 else int(remaining * lag_rng.uniform(0.4, 0.6))
                    remaining -= line_units
                    if line_units <= 0:
                        continue
                    ship_date = active_dates[s] - dt.timedelta(days=int(lag_rng.integers(1, 4)))
                    lead_time = int(lag_rng.integers(3, 8))
                    est_delivery = ship_date + dt.timedelta(days=lead_time)
                    status_roll = lag_rng.random()
                    if status_roll < 0.85:
                        status = "DELIVERED"
                        actual_delivery = est_delivery + dt.timedelta(days=int(lag_rng.integers(-1, 3)))
                    elif status_roll < 0.93:
                        status = "IN_TRANSIT"
                        actual_delivery = None
                    elif status_roll < 0.98:
                        status = "DELAYED"
                        actual_delivery = est_delivery + dt.timedelta(days=int(lag_rng.integers(3, 10)))
                    else:
                        status = "CANCELLED"
                        actual_delivery = None
                    ship_rows.append(
                        {
                            "shipment_id": f"SHP-{ship_seq:07d}",
                            "retailer_id": retailer_id,
                            "distribution_center_id": dc_id,
                            "product_id": product_id,
                            "shipment_date": ship_date,
                            "units_shipped": line_units,
                            "shipment_status": status,
                            "estimated_delivery_date": est_delivery,
                            "actual_delivery_date": actual_delivery,
                        }
                    )
                    ship_seq += 1

    pos_sales = pd.DataFrame(pos_cols)
    inventory_snapshots = pd.DataFrame(inv_cols)
    shipments = pd.DataFrame(ship_rows)
    return {"pos_sales": pos_sales, "inventory_snapshots": inventory_snapshots, "shipments": shipments}
