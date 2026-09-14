#!/usr/bin/env python3
"""
Phase 14: Historical Baseline Data Generator (Pre-Black Week Volume Calibration)
================================================================================
Generates 1.5 months of realistic baseline non-promotional transaction volume
(October 12, 2026 to November 22, 2026 — 42 days / 6 full weeks) and appends to BigQuery
without overwriting or modifying any existing Black Week records.

Enables Conversational Analytics and Gemini Data Agents to execute longitudinal
year-over-year and month-over-month trend queries ("How does Black Friday compare to normal weeks?").

Usage:
------
  python3 scripts/14_generate_historical_data.py
  python3 scripts/14_generate_historical_data.py --dry-run

`--dry-run` generates everything and validates every record against the live
destination schema, but performs no writes. It exists because this script runs
as one stage of a 15-stage bootstrap in which any non-zero exit aborts the whole
rebuild, so a fault here is expensive to discover late. Reads from BigQuery
(products, users) still happen - they are needed to build the data.
"""

import argparse
import os
import sys
import uuid
import random
import tempfile
import shutil
import json
import gzip
import numpy as np
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))
# Add scripts/ explicitly; the bootstrap invokes this as a subprocess.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
from google.cloud import bigquery
from app.config import PROJECT_ID, DATASET_ID, LOCATION
from order_status import derive_order_status, status_distribution
from clickstream import (EVENT_GAP_SECONDS, EVENTS_PER_CONVERTING_SESSION,
                         EVENTS_PER_SESSION_RANGE, browser_for, device_os_for,
                         event_at_step, is_page_view)

# Historical baseline bounds (42 days prior to Black Week)
HIST_START = datetime(2026, 10, 12, 0, 0, 0)
HIST_END = datetime(2026, 11, 22, 23, 59, 59)
TOTAL_HIST_SECONDS = int((HIST_END - HIST_START).total_seconds())

# The instant the warehouse was extracted. Mirrors CURRENT_TIME in
# scripts/02_generate_data.py and must stay equal to it: both generators write
# to the same tables, so a row either generator dates after this moment is a
# row the warehouse could not possibly hold. A 22 November order with a
# five-day return window can land past it, which is how 17 such rows appeared.
SNAPSHOT_TIME = datetime(2026, 11, 27, 14, 30, 0)

def get_bigquery_client():
    return bigquery.Client(project=PROJECT_ID, location=LOCATION)

def _first_record(file_path):
    """The first NDJSON record in a file, plain or gzipped. None if empty."""
    opener = gzip.open if file_path.endswith(".gz") else open
    with opener(file_path, "rt", encoding="utf-8") as f:
        line = f.readline()
    return json.loads(line) if line.strip() else None


def assert_columns_exist(client, table_name, record, dry_run=False):
    """Fail if `record` carries a field the destination table does not have.

    The load runs with ignore_unknown_values=True, which makes BigQuery DISCARD
    unrecognised fields rather than reject the row. A single mistyped column
    name would therefore produce a rebuild that reports complete success while
    leaving that column entirely NULL - the kind of fault that is only noticed
    much later, by an agent giving a wrong answer.

    Checking one record is enough: every record for a table is built by the
    same dict literal.

    In a dry run this reports rather than raises. A dry run happens BEFORE the
    rebuild, so the live table still has its old schema and any column this
    release adds is legitimately absent. The caller prints the collected list
    so each entry can be matched against a pending change in
    `01_create_schema.py`.
    """
    table = client.get_table(f"{PROJECT_ID}.{DATASET_ID}.{table_name}")
    unknown = sorted(set(record) - {f.name for f in table.schema})
    if unknown and not dry_run:
        raise RuntimeError(
            f"`{table_name}` would silently discard {unknown}. "
            f"Destination columns are: {sorted(f.name for f in table.schema)}"
        )
    return unknown


def append_ndjson_to_bq(client, table_name, file_path, dry_run=False, pending=None):
    table_ref = f"{PROJECT_ID}.{DATASET_ID}.{table_name}"
    sample = _first_record(file_path)
    unknown = []
    if sample is not None:
        unknown = assert_columns_exist(client, table_name, sample, dry_run=dry_run)
    if unknown and pending is not None:
        pending[table_name] = unknown

    size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if dry_run:
        note = f" | NOT IN LIVE SCHEMA YET: {unknown}" if unknown else " | schema OK"
        print(f"   [dry-run] `{table_name}`: {size_mb:,.1f} MB staged{note}")
        return

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        ignore_unknown_values=True
    )
    print(f"   Appending to `{table_name}` from {os.path.basename(file_path)} "
          f"({size_mb:,.1f} MB)...")
    with open(file_path, "rb") as source_file:
        job = client.load_table_from_file(source_file, table_ref, job_config=job_config)
        job.result()
    print(f"   ✅ Successfully appended to `{table_name}`.")

def generate_historical_data(dry_run=False):
    random.seed(1337)
    np.random.seed(1337)

    client = get_bigquery_client()
    print("=" * 80)
    print("STARTING 1.5-MONTH HISTORICAL BASELINE DATA GENERATION (OCT 12 - NOV 22, 2026)")
    print(f"Target: `{PROJECT_ID}.{DATASET_ID}` | Location: `{LOCATION}`")
    print(f"Timeline: {HIST_START.strftime('%Y-%m-%d %H:%M:%S')} to {HIST_END.strftime('%Y-%m-%d %H:%M:%S')} UTC (42 Days / 6 Weeks)")
    print("=" * 80 + "\n")

    # 1. Fetch Products master list from BigQuery
    print("1. Fetching product catalog from BigQuery...")
    prod_query = f"SELECT product_id, category_id, name, retail_price, cost FROM `{PROJECT_ID}.{DATASET_ID}.products` ORDER BY product_id"
    prod_rows = list(client.query(prod_query).result())
    products = [{
        "product_id": r.product_id,
        "category_id": r.category_id,
        "name": r.name,
        "retail_price": float(r.retail_price),
        "cost": float(r.cost)
    } for r in prod_rows]
    print(f"   Loaded {len(products)} products across 4 categories.")

    # 2. Historical Weekly Commercial Targets (6 Historical Weeks x 4 Categories = 24 Rows)
    print("\n2. Generating Historical Weekly Commercial Targets...")
    weekly_targets = []
    target_id_counter = 101
    
    # Standard baseline weekly targets per category
    base_cat_weekly_targets = {
        1: {"revenue": 220000.0, "sessions": 70000, "cvr": 0.031}, # Beauty
        2: {"revenue": 240000.0, "sessions": 30000, "cvr": 0.034}, # Electronics
        3: {"revenue": 190000.0, "sessions": 28000, "cvr": 0.032}, # Fashion
        4: {"revenue": 180000.0, "sessions": 25000, "cvr": 0.030}, # Home
    }

    week_starts = [
        "2026-10-12", "2026-10-19", "2026-10-26", "2026-11-02", "2026-11-09", "2026-11-16"
    ]

    for w_idx, w_start in enumerate(week_starts):
        # Slight seasonal growth ramp towards November
        seasonality_factor = 1.0 + (w_idx * 0.02)
        for cat_id, info in base_cat_weekly_targets.items():
            weekly_targets.append({
                "target_id": target_id_counter,
                "category_id": cat_id,
                "week_start_date": w_start,
                "target_revenue": float(round(info["revenue"] * seasonality_factor, 2)),
                "target_sessions": int(round(info["sessions"] * seasonality_factor)),
                "target_conversion_rate": info["cvr"]
            })
            target_id_counter += 1

    # 3. Historical Daily Category Targets (42 Days x 4 Categories = 168 Rows)
    print("3. Generating Historical Daily Category Targets...")
    daily_targets = []
    # Standard day-of-week weights (Sun=0.17, Mon=0.14, Tue=0.13, Wed=0.13, Thu=0.14, Fri=0.14, Sat=0.15)
    dow_weights = [0.14, 0.13, 0.13, 0.14, 0.14, 0.15, 0.17]

    for day in range(42):
        d_dt = HIST_START + timedelta(days=day)
        d_str = d_dt.strftime("%Y-%m-%d")
        w_factor = dow_weights[d_dt.weekday()]
        
        for cat_id, info in base_cat_weekly_targets.items():
            daily_rev = info["revenue"] * w_factor
            daily_sess = int(info["sessions"] * w_factor)
            daily_spend = daily_rev * 0.12 # Standard 12% marketing spend
            daily_roas = 4.8 if cat_id == 1 else (5.2 if cat_id == 2 else 4.5)

            daily_targets.append({
                "target_id": f"T-HIST-C{cat_id}-{d_str}",
                "category_id": cat_id,
                "date": d_str,
                "target_revenue": float(round(daily_rev, 2)),
                "target_sessions": daily_sess,
                "target_conversion_rate": info["cvr"],
                "target_aov": float(round(daily_rev / (daily_sess * info["cvr"]), 2)),
                "target_ad_spend": float(round(daily_spend, 2)),
                "target_roas": daily_roas
            })

    # 4. Historical Daily Ad Performance & Ad Bidding Logs
    print("4. Generating Historical Ad Performance & Bidding Logs...")
    ad_performance = []
    ad_bidding_logs = []
    ad_perf_id = 101
    ad_log_id = 101

    # The real campaign identifiers are 1001-1004, one per category - the same
    # ones Black Week writes and the only ones present in marketing_campaigns.
    #
    # History used 1, 2, 3, 4, which match NO campaign. That left 24
    # ad_bidding_log rows pointing at campaigns that do not exist, and it is a
    # second instance of the same dual-vocabulary fault as the
    # 'DACH' / 'Central Europe (DACH)' split in shipping_lead_times: one
    # logical key written two different ways by the two generators, so a join
    # or a GROUP BY quietly returns the wrong answer instead of failing.
    campaign_map = {
        1001: ("Meta Ads - Beauty Luxury Skincare", 1),
        1002: ("Google Search - Electronics Audio/Smart", 2),
        1003: ("Meta Ads - Fashion Autumn Collection", 3),
        1004: ("Google Shopping - Home Decor & Living", 4)
    }

    for day in range(42):
        d_dt = HIST_START + timedelta(days=day)
        d_str = d_dt.strftime("%Y-%m-%d")

        for camp_id, (camp_name, cat_id) in campaign_map.items():
            c_info = base_cat_weekly_targets[cat_id]
            w_factor = dow_weights[d_dt.weekday()]
            day_spend = float(round(c_info["revenue"] * w_factor * 0.12 * random.uniform(0.95, 1.05), 2))
            cpc = float(round(random.uniform(0.35, 0.42), 2))
            clicks = int(round(day_spend / cpc))
            impressions = clicks * random.randint(35, 48)
            conversions = int(round(clicks * c_info["cvr"] * random.uniform(0.98, 1.02)))

            ad_performance.append({
                "performance_id": ad_perf_id,
                # The column is `cid_ref`, not `campaign_id`. Writing the wrong
                # name left 168 of 188 rows unattributable to a campaign - and
                # therefore to a category - because the load discards fields the
                # destination does not recognise.
                "cid_ref": camp_id,
                "date": d_str,
                "impressions": impressions,
                "clicks": clicks,
                "spend": day_spend,
                "conversions": conversions,
                "average_cpc": cpc
            })
            ad_perf_id += 1

        # Weekly automated bidding health audit.
        #
        # The five quantitative columns below are the ones an agent has to
        # correlate in order to find the ad throttle (see the note at
        # 02_generate_data.py:444). Black Week populates all five; history used
        # to populate NONE of them, so the throttle read as instrumentation
        # STARTING TO EXIST on 23 November rather than a value CHANGING from
        # 1.00 to 0.78. That is the same false-signal shape as the historical
        # payment log that was once 100% successful.
        #
        # `trigger_details` used to be written here and is deliberately gone.
        # It stated the root cause as an English sentence, which let any agent
        # read the conclusion straight out of a text column; the schema dropped
        # it for that reason and the field survived here only because the load
        # was silently discarding it.
        #
        # Every value is a constant. A random draw here would shift the
        # historical stream for everything generated afterwards.
        if d_dt.weekday() == 0:
            for camp_id, (_camp_name, cat_id) in campaign_map.items():
                ad_bidding_logs.append({
                    "log_id": ad_log_id,
                    "campaign_id": camp_id,
                    "status_change": "BUDGET_NORMAL",
                    "action_taken": "NO_CHANGE",
                    # The category's healthy baseline. Beauty's 0.031 is
                    # continuous with the 0.0312 Black Week logs on 14 Nov.
                    "observed_cvr_7d": base_cat_weekly_targets[cat_id]["cvr"],
                    "target_roas_multiplier": 1.0,
                    "budget_multiplier": 1.0,
                    "bid_adjustment_pct": 0.0,
                    "logged_at": d_dt.strftime("%Y-%m-%dT06:00:00Z")
                })
                ad_log_id += 1

    # 5. Historical Daily Inventory Snapshots (42 Days x 600 SKUs = 25,200 Snapshots)
    print("5. Generating Historical Inventory Snapshots (Full Healthy Stock)...")
    inventory_snapshots = []
    snap_id = 10001

    for day in range(42):
        d_dt = HIST_START + timedelta(days=day)
        d_str = d_dt.strftime("%Y-%m-%dT08:00:00Z")
        
        for p in products:
            # During historical baseline, ALL SKUs including 1001-1003 are healthy in stock (>1,500 units)
            base_qty = 3200 - (day % 14) * 45
            inventory_snapshots.append({
                "snapshot_id": snap_id,
                "product_id": p["product_id"],
                "recorded_at": d_str,
                "stock_quantity": base_qty,
                "is_out_of_stock": False
            })
            snap_id += 1

    # 6. Historical Shipping Lead Times (42 Days x 2 DCs = 84 Rows)
    print("6. Generating Historical Shipping Lead Times...")
    shipping_lead_times = []
    lead_id = 101

    for day in range(42):
        d_dt = HIST_START + timedelta(days=day)
        d_str = d_dt.strftime("%Y-%m-%d")
        
        # Region names MUST match the vocabulary in 02_generate_data.py
        # (STANDARD_LEAD_TIME / CARRIER_BY_REGION), because both generators
        # write to the SAME shipping_lead_times.destination_region column.
        #
        # History used to say "Central Europe (DACH)" while Black Week said
        # "DACH", so WHERE destination_region = 'DACH' silently dropped every
        # historical row and a GROUP BY split one region into two. The pairing
        # below also matches the carrier assigned on the next line: Chronopost
        # serves France, DHL Express serves DACH.
        for dc_id, region in [(1, "France"), (2, "DACH")]:
            shipping_lead_times.append({
                "lead_time_id": f"LT-HIST-{lead_id}",
                "dc_id": dc_id,
                "date": d_str,
                "carrier_name": "DHL Express" if dc_id == 2 else "Chronopost",
                "destination_region": region,
                "standard_lead_time_hours": 48,
                "actual_promised_lead_time_hours": 28,
                "capacity_utilization_pct": float(round(random.uniform(62.0, 78.0), 1)),
                "cart_abandonment_impact_pct": 0.0,
                "estimated_lost_revenue": 0.0
            })
            lead_id += 1

    # 7. Historical Orders, Order Items, Sales Events & Payments (~42,000 Orders, ~70,000 Items)
    print("7. Generating Historical Orders, Items, Sales Events & Payments...")
    orders = []
    order_items = []
    sales_event_stream = []
    payment_logs = []
    # One entry per order, used in step 7b to emit the session that produced it.
    converting_sessions = []

    order_id = 100001
    order_item_id = 100001
    pay_log_id = 100001

    # We generate ~1,000 orders/day across 42 days (~42,000 orders total)
    # Total historical revenue: 6 weeks x ~€830k/week = ~€4,980,000.00
    target_weekly_rev_by_cat = {
        1: 220000.0, # Beauty
        2: 240000.0, # Electronics
        3: 190000.0, # Fashion
        4: 180000.0  # Home
    }

    # Pre-calculate category products and weight distribution
    cat_prods_map = {}
    cat_weights_map = {}
    for c_id in range(1, 5):
        c_prods = [p for p in products if p["category_id"] == c_id]
        cat_prods_map[c_id] = c_prods
        weights = 1.0 / (np.arange(1, len(c_prods) + 1) ** 0.85)
        cat_weights_map[c_id] = weights / weights.sum()

    for w_idx in range(6):
        w_start_dt = HIST_START + timedelta(days=w_idx * 7)
        
        for cat_id in range(1, 5):
            cat_target = target_weekly_rev_by_cat[cat_id] * (1.0 + w_idx * 0.02)
            # Healthy actual: 99.8% to 101.2% target completion
            cat_actual_target = cat_target * random.uniform(0.998, 1.012)
            
            c_prods = cat_prods_map[cat_id]
            c_weights = cat_weights_map[cat_id]
            n_prods = len(c_prods)

            current_rev = 0.0
            while current_rev < cat_actual_target:
                rand_sec = random.randint(0, 7 * 86400 - 1)
                order_dt = w_start_dt + timedelta(seconds=rand_sec)
                user_id = random.randint(1, 10000)

                item_roll = random.random()
                num_items = 1 if item_roll < 0.60 else (2 if item_roll < 0.88 else (3 if item_roll < 0.96 else 4))

                order_total = 0.0
                items_for_order = []

                for _ in range(num_items):
                    p_obj = np.random.choice(c_prods, p=c_weights)
                    price = float(p_obj["retail_price"])
                    qty = 1 if random.random() < 0.88 else 2
                    line_total = price * qty
                    order_total += line_total
                    items_for_order.append((p_obj["product_id"], qty, price))

                current_rev += order_total

                # The per-line return rolls are drawn HERE, ahead of the order
                # row, so that order_status can be derived from them.
                #
                # The draw SEQUENCE is unchanged from when these rolls lived
                # inside the item loop below: nothing between the two positions
                # consumes randomness, and randint() is still reached only when
                # the line is actually returned. The seeded stream is therefore
                # byte-identical, which is what keeps every published figure
                # from moving.
                ret_dts = []
                for _ in items_for_order:
                    has_ret = random.random() < 0.048  # Standard 4.8% return rate
                    if not has_ret:
                        ret_dts.append(None)
                        continue
                    # A late-November order can have its return window land
                    # after the warehouse snapshot. That return has not
                    # happened yet, so the column is NULL - and because
                    # order_status is derived from this list, the status agrees
                    # with it automatically. Clamping AFTER the draw keeps the
                    # seeded stream byte-identical.
                    r_dt = order_dt + timedelta(days=random.randint(2, 5))
                    ret_dts.append(r_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                                   if r_dt < SNAPSHOT_TIME else None)

                status = derive_order_status(d is not None for d in ret_dts)

                # Historical orders previously had no session_id at all, so a
                # warehouse-wide join from orders to web_sessions silently
                # dropped every one of them. The id is derived from the order
                # number - no random draw - and the matching session row is
                # written in step 7b below.
                hist_sid = f"SESS-HIST-{order_id}"
                converting_sessions.append((hist_sid, order_dt, user_id, cat_id))

                orders.append({
                    "order_id": order_id,
                    "session_id": hist_sid,
                    "user_id": user_id,
                    "order_status": status,
                    "total_amount": float(round(order_total, 2)),
                    "tax_amount": float(round(order_total * 0.20, 2)),
                    "shipping_fee": 4.99 if order_total < 50.0 else 0.0,
                    "num_of_items": len(items_for_order),
                    "created_at": order_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                })

                for (p_id, qty, price), ret_dt in zip(items_for_order, ret_dts):
                    order_items.append({
                        "order_item_id": order_item_id,
                        # The order foreign key is `ord_hdr_num` and the product
                        # foreign key is `mat_nr`. Writing `order_id` and
                        # `product_id` meant BigQuery discarded both, leaving
                        # 99,650 rows - 48% of the table, EUR 5,261,339.50 of
                        # revenue - joinable to neither an order nor a product,
                        # and therefore with no category at all.
                        #
                        # Note the other tables here legitimately DO use
                        # `order_id` / `product_id`; the cryptic names are
                        # specific to order_items.
                        "ord_hdr_num": order_id,
                        "user_id": user_id,
                        "mat_nr": p_id,
                        "inventory_item_id": p_id - (p_id // 1000 - 1) * 850,
                        "quantity": qty,
                        "sale_price": float(price),
                        "discount_amount": 0.0,
                        "created_at": order_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "shipped_at": (order_dt + timedelta(hours=14)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "delivered_at": (order_dt + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "returned_at": ret_dt
                    })

                    sales_event_stream.append({
                        "event_id": str(uuid.uuid4()),
                        "order_id": order_id,
                        "product_id": p_id,
                        "category_id": cat_id,
                        "quantity": qty,
                        "sale_price": float(price),
                        "discount_amount": 0.0,
                        "timestamp": order_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                    })
                    order_item_id += 1

                # ------------------------------------------------------------
                # Payment gateway logs.
                #
                # This block used to hardcode status="SUCCESS" for EVERY order
                # (despite a comment claiming ~93.5%), giving history a literal
                # 0% failure rate. Black Week runs at ~92.5% coverage with
                # ~6,000 failed/timeout attempts, so the contrast implied the
                # gateway had broken during Black Week - a false root cause that
                # every tier could "discover", and a louder signal than any of
                # the three real ones.
                #
                # History now mirrors the Black Week profile, so gateway errors
                # read as a stable background rate: present, unremarkable, and
                # correctly dismissed as a red herring.
                #
                #   PSP_COVERAGE   60,155 SUCCESS / 65,011 orders = 0.9253
                #   PSP_FAIL_RATIO  6,034 failures / 65,011 orders = 0.0928
                # ------------------------------------------------------------
                PSP_COVERAGE = 0.9253
                PSP_FAIL_RATIO = 0.0928

                psp = random.choice(["Stripe", "Stripe", "PayPal", "Adyen"])
                method = "credit_card" if psp != "PayPal" else "paypal_wallet"

                # A successful order usually - but not always - leaves a log.
                # The shortfall is instrumentation loss, not a failed payment.
                if random.random() < PSP_COVERAGE:
                    payment_logs.append({
                        "gateway_log_id": f"GW-HIST-{pay_log_id}",
                        "session_id": f"SESS-HIST-{order_id % 1200000 + 1}",
                        "order_id": order_id,
                        "payment_provider": psp,
                        "payment_method": method,
                        "status": "SUCCESS",
                        "http_status_code": 200,
                        "latency_ms": random.randint(140, 320),
                        "error_code": None,
                        "total_amount": float(round(order_total, 2)),
                        "country": random.choice(["France", "Germany", "Netherlands", "Spain", "Italy", "Belgium"]),
                        "created_at": order_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                    })
                    pay_log_id += 1

                # Standalone declined/timed-out attempts. These never became
                # orders, so order_id is NULL - the same shape Black Week emits.
                if random.random() < PSP_FAIL_RATIO:
                    fail_status = random.choice(["FAILED", "FAILED", "FAILED",
                                                 "FAILED", "TIMEOUT"])
                    is_timeout = fail_status == "TIMEOUT"
                    fail_psp = "Adyen" if is_timeout else psp
                    payment_logs.append({
                        "gateway_log_id": f"GW-HIST-{pay_log_id}",
                        "session_id": f"SESS-HIST-F-{pay_log_id}",
                        "order_id": None,
                        "payment_provider": fail_psp,
                        "payment_method": "credit_card" if fail_psp != "PayPal" else "paypal_wallet",
                        "status": fail_status,
                        "http_status_code": 504 if is_timeout else 402,
                        "latency_ms": random.randint(8000, 26000) if is_timeout else random.randint(250, 2400),
                        "error_code": ("ERR_504_GATEWAY_TIMEOUT" if is_timeout
                                       else random.choice(["INSUFFICIENT_FUNDS", "DO_NOT_HONOR",
                                                           "CARD_DECLINED", "EXPIRED_CARD"])),
                        "total_amount": float(round(order_total, 2)),
                        "country": random.choice(["France", "Germany", "Netherlands", "Spain", "Italy", "Belgium"]),
                        "created_at": order_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                    })
                    pay_log_id += 1

                order_id += 1

    print(f"   Generated {len(orders):,} historical orders (€{sum(o['total_amount'] for o in orders):,.2f} total revenue).")

    # ------------------------------------------------------------------
    # 7b. Historical clickstream.
    #
    # History previously had orders but NO sessions and NO events. Three things
    # were wrong with that:
    #
    #   * A warehouse-wide conversion rate divided ~64k historical orders by
    #     zero historical sessions, reading ~5.9% - meaningless.
    #   * "How does traffic compare with last month?" was unanswerable, which
    #     is among the first questions any CMO asks.
    #   * web_events began abruptly on 23 November. A discontinuity like that
    #     reads as an instrumentation change and invites an agent to chase it.
    #     This codebase has already been burned by exactly that shape: history
    #     once had a 0% payment failure rate, which made Black Week's ordinary
    #     ~7% look like an outage.
    #
    # Session COUNTS are derived from the orders that were actually generated
    # above, divided by a per-category conversion rate. Traffic and orders are
    # therefore consistent by construction; there is no separate session target
    # that could drift away from the revenue target.
    #
    # This runs in a different process from 02_generate_data.py and has its own
    # seed, so nothing here can perturb the Black Week figures. It is placed
    # AFTER the order loop so it cannot shift the orders either.
    # ------------------------------------------------------------------
    print("\n7b. Generating Historical Clickstream (sessions + events)...")

    # The two clickstream files are far too large to build in memory, so they
    # stream straight to gzipped NDJSON. BigQuery auto-detects gzip on load.
    clickstream_dir = tempfile.mkdtemp(dir=os.path.join(PROJECT_ROOT, ".tmp"))

    # Black Week numbers web_events from 1 and reaches roughly 43 million.
    # Historical ids start an order of magnitude clear of that so the two
    # generators can never collide on the primary key.
    HIST_EVENT_ID_BASE = 900_000_000

    # Measured from the live Black Week warehouse on 2026-09-12 so that the two
    # periods share one profile. Beauty converts best; Electronics worst.
    CVR_BY_CAT = {1: 0.0389, 2: 0.0238, 3: 0.0280, 4: 0.0263}
    # Measured Black Week shares: Organic 37.5%, Paid Search 18.8%,
    # Paid Social 17.5%, Direct 14.3%, Email 6.3%, Affiliate 5.6%.
    CHANNELS = ["Organic Search", "Paid Search", "Paid Social",
                "Direct", "Email", "Affiliate"]
    CHANNEL_WEIGHTS = [0.37513, 0.18767, 0.17526, 0.14275, 0.06283, 0.05636]
    UTM_BY_CHANNEL = {
        "Organic Search": (None, "organic", None),
        "Paid Search": ("google", "cpc", "BF26_Search_Generic"),
        "Paid Social": ("meta", "paid_social", "BF26_Social_Prospecting"),
        "Direct": (None, None, None),
        "Email": ("newsletter", "email", "BF26_CRM_Weekly"),
        "Affiliate": ("partner", "referral", "BF26_Affiliate_Network"),
    }
    ANON_SHARE = 0.25028   # measured: 25.0% of Black Week sessions are signed out

    # Visitor geography. Fetched rather than invented so web_sessions.country
    # agrees with users.country.
    user_rows = list(client.query(
        f"SELECT user_id, country FROM `{PROJECT_ID}.{DATASET_ID}.users`").result())
    user_country = {r.user_id: r.country for r in user_rows}
    all_user_ids = sorted(user_country)
    if not all_user_ids:
        raise RuntimeError("users table is empty - run 02_generate_data.py first")

    orders_by_cat = {}
    for _, _, _, c_id in converting_sessions:
        orders_by_cat[c_id] = orders_by_cat.get(c_id, 0) + 1
    nonconv_by_cat = {
        c_id: max(0, int(round(n / CVR_BY_CAT[c_id])) - n)
        for c_id, n in orders_by_cat.items()
    }
    planned = len(converting_sessions) + sum(nonconv_by_cat.values())
    print(f"   {len(converting_sessions):,} converting + "
          f"{sum(nonconv_by_cat.values()):,} non-converting = {planned:,} sessions")

    sess_path = os.path.join(clickstream_dir, "web_sessions.json.gz")
    ev_path = os.path.join(clickstream_dir, "web_events.json.gz")
    sess_written = ev_written = 0

    def emit_session(sid, start_dt, uid, c_id, converted, f_sess, f_ev):
        """Write one session and its events. Returns the number of events."""
        nonlocal ev_written
        lo, hi = (EVENTS_PER_CONVERTING_SESSION if converted
                  else EVENTS_PER_SESSION_RANGE)
        n_ev = random.randint(lo, hi)
        product_id = random.choice(cat_prods_map[c_id])["product_id"]

        ev_time = start_dt
        last_ev_time = start_dt
        page_views = 0
        for step in range(n_ev):
            ev_time += timedelta(seconds=random.randint(*EVENT_GAP_SECONDS))
            # History is entirely in the past, so unlike Black Week there is no
            # cutoff to clamp against.
            e_type, page_url = event_at_step(step, n_ev, converted, c_id, product_id)
            f_ev.write(json.dumps({
                "event_id": HIST_EVENT_ID_BASE + ev_written + step,
                "session_id": sid,
                "product_id": product_id, "event_type": e_type,
                "page_url": page_url,
                "metadata": {"error_message": None, "http_status_code": 200,
                             "estimated_lost_revenue": None},
                "created_at": ev_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }) + "\n")
            last_ev_time = ev_time
            if is_page_view(e_type):
                page_views += 1
        ev_written += n_ev

        channel = random.choices(CHANNELS, weights=CHANNEL_WEIGHTS)[0]
        utm_s, utm_m, utm_c = UTM_BY_CHANNEL[channel]
        dev_os = device_os_for(random.random())
        f_sess.write(json.dumps({
            "session_id": sid,
            # Signed-out visitors have no user_id, but their country is still
            # known from the IP lookup - same convention as Black Week.
            "user_id": None if random.random() < ANON_SHARE else uid,
            "traffic_source": channel,
            "utm_source": utm_s, "utm_medium": utm_m, "utm_campaign": utm_c,
            "primary_category_id": c_id,
            "converted_to_order": converted,
            "device_os": dev_os, "browser": browser_for(dev_os),
            "country": user_country.get(uid, "France"),
            "session_started_at": start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "session_ended_at": last_ev_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "page_views_count": page_views,
        }) + "\n")
        return n_ev

    with gzip.open(sess_path, "wt", encoding="utf-8", compresslevel=4) as f_sess, \
         gzip.open(ev_path, "wt", encoding="utf-8", compresslevel=4) as f_ev:

        # Converting sessions: one per order, starting shortly before it. The
        # same 180-1500 second browse-to-buy gap Black Week uses.
        for sid, order_dt, uid, c_id in converting_sessions:
            start_dt = order_dt - timedelta(seconds=random.randint(180, 1500))
            if start_dt < HIST_START:
                start_dt = HIST_START
            emit_session(sid, start_dt, uid, c_id, True, f_sess, f_ev)
            sess_written += 1

        # Non-converting sessions, spread uniformly across the whole window.
        nonconv_seq = 0
        for c_id, n_sessions in sorted(nonconv_by_cat.items()):
            for _ in range(n_sessions):
                nonconv_seq += 1
                start_dt = HIST_START + timedelta(
                    seconds=random.randint(0, TOTAL_HIST_SECONDS))
                uid = random.choice(all_user_ids)
                emit_session(f"SESS-HIST-N-{nonconv_seq}", start_dt, uid, c_id,
                             False, f_sess, f_ev)
                sess_written += 1
                if sess_written % 250_000 == 0:
                    print(f"   ... {sess_written:,} sessions, {ev_written:,} events")

    print(f"   Generated {sess_written:,} sessions | {ev_written:,} events "
          f"({ev_written / max(sess_written, 1):.2f} per session)")
    print(f"   Implied historical conversion rate: "
          f"{len(converting_sessions) / max(sess_written, 1):.3%}")


    # 8. Write and Append to BigQuery
    if dry_run:
        print("\n8. [dry-run] Staging records and validating against the live "
              "destination schema. Nothing will be written.")
    else:
        print("\n8. Streaming historical records to BigQuery Load Jobs...")
    local_tmp_base = os.path.join(PROJECT_ROOT, ".tmp")
    os.makedirs(local_tmp_base, exist_ok=True)
    temp_dir = tempfile.mkdtemp(dir=local_tmp_base)

    datasets_to_upload = [
        ("weekly_commercial_targets", weekly_targets),
        ("daily_category_targets", daily_targets),
        ("daily_ad_performance", ad_performance),
        ("ad_bidding_log", ad_bidding_logs),
        ("inventory_snapshots", inventory_snapshots),
        ("shipping_lead_times", shipping_lead_times),
        ("orders", orders),
        ("order_items", order_items),
        ("sales_event_stream", sales_event_stream),
        ("payment_gateway_logs", payment_logs)
    ]

    # Columns this release adds that the live (pre-rebuild) tables lack.
    # Collected rather than raised during a dry run; see assert_columns_exist.
    pending = {}

    try:
        for table_name, record_list in datasets_to_upload:
            if not record_list:
                continue
            file_path = os.path.join(temp_dir, f"{table_name}.json")
            with open(file_path, "w", encoding="utf-8") as f:
                for rec in record_list:
                    f.write(json.dumps(rec) + "\n")
            append_ndjson_to_bq(client, table_name, file_path,
                                dry_run=dry_run, pending=pending)

        # The clickstream was streamed to gzip rather than accumulated in a
        # list, so it is appended from its own staging directory. These are the
        # two largest loads in the whole pipeline by a wide margin.
        for table_name, file_path in (("web_sessions", sess_path),
                                      ("web_events", ev_path)):
            append_ndjson_to_bq(client, table_name, file_path,
                                dry_run=dry_run, pending=pending)
    finally:
        # A dry run exists to be inspected, so its output is kept. A real run
        # has nothing left to look at once BigQuery holds the rows.
        if dry_run:
            print(f"\n   Staged tables     : {temp_dir}")
            print(f"   Staged clickstream: {clickstream_dir}")
            print("   Delete these when you are done; they are large.")
        else:
            for d in (temp_dir, clickstream_dir):
                if os.path.exists(d):
                    shutil.rmtree(d, ignore_errors=True)

    if dry_run:
        if pending:
            print("\n   Fields absent from the CURRENT live schema. Each must be "
                  "declared in 01_create_schema.py, or the rebuild will discard "
                  "it silently:")
            for table_name, cols in sorted(pending.items()):
                print(f"     {table_name}: {cols}")
        else:
            print("\n   Every field matches the live schema exactly.")
        print("\n✅ DRY RUN COMPLETE - generation succeeded. Nothing was written.")
    else:
        print("\n🎉 ALL 1.5-MONTH HISTORICAL BASELINE DATA SUCCESSFULLY APPENDED TO BIGQUERY!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate the 42-day historical baseline preceding Black Week.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Generate and validate everything, but write nothing to BigQuery.")
    args = parser.parse_args()
    generate_historical_data(dry_run=args.dry_run)
