#!/usr/bin/env python3
"""
Automated Data Validation, Statistical Ratios & Date Cutoff Assertion Suite.
Verifies:
1. Operational data strictly respects Friday Nov 27, 2026 14:30:00 UTC cutoff (0 rows post-cutoff).
2. Target tables cover the full 8 days (Nov 23 to Nov 30).
3. Statistical ratios across Black Week.
4. The Beauty deficit MEASURED against the pro-rated plan matches the published
   figure, and the published allocation still adds up to it.
"""

import os
import sys

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from test_utils import load_project_env, get_bigquery_client
load_project_env()

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
DATASET_ID = os.environ.get("BQ_DATASET_ID", "ecommerce_dw")

CUTOFF_TIMESTAMP = "2026-11-27 14:30:00 UTC"
START_TIMESTAMP = "2026-11-23 00:00:00 UTC"

def run_validation():
    print("=" * 80)
    print("BLACK WEEK 2026 DATA, STATISTICAL RATIOS & DATE CUTOFF VALIDATION SUITE")
    print(f"Dataset: `{PROJECT_ID}.{DATASET_ID}`")
    print(f"Simulation Anchor (Max Actuals Cutoff): {CUTOFF_TIMESTAMP}")
    print(f"Black Week Focus Start:                {START_TIMESTAMP}")
    print("=" * 80)

    client = get_bigquery_client(PROJECT_ID)

    passed = 0
    total = 0

    # 1. Statistical ratios during Black Week
    print("\n1. Validating E-Commerce Statistical Ratios for Black Week Focus Period...")

    total += 1
    cr_query = f"""
    SELECT 
        (SELECT COUNT(*) FROM `{PROJECT_ID}.{DATASET_ID}.orders` WHERE created_at >= '{START_TIMESTAMP}' AND created_at <= '{CUTOFF_TIMESTAMP}') AS order_count,
        (SELECT COUNT(*) FROM `{PROJECT_ID}.{DATASET_ID}.web_sessions` WHERE session_started_at >= '{START_TIMESTAMP}' AND session_started_at <= '{CUTOFF_TIMESTAMP}') AS session_count
    """
    cr_res = list(client.query(cr_query).result())[0]
    bw_orders = cr_res.order_count
    bw_sessions = cr_res.session_count
    cr = (bw_orders / bw_sessions) if bw_sessions > 0 else 0.0

    if 0.025 <= cr <= 0.035:
        print(f"  ✅ Conversion Rate (Orders / Sessions): {bw_orders:,} / {bw_sessions:,} = {cr*100:.2f}% (Target: ~3.0%) [PASS]")
        passed += 1
    else:
        print(f"  ❌ Conversion Rate: {bw_orders} / {bw_sessions} = {cr*100:.2f}% (Target ~3.0%) [FAIL]")

    total += 1
    pay_query = f"""
    SELECT 
        (SELECT COUNT(*) FROM `{PROJECT_ID}.{DATASET_ID}.payment_gateway_logs` WHERE status = 'SUCCESS' AND created_at >= '{START_TIMESTAMP}' AND created_at <= '{CUTOFF_TIMESTAMP}') AS succ_payments,
        (SELECT COUNT(*) FROM `{PROJECT_ID}.{DATASET_ID}.orders` WHERE created_at >= '{START_TIMESTAMP}' AND created_at <= '{CUTOFF_TIMESTAMP}') AS total_orders
    """
    pay_res = list(client.query(pay_query).result())[0]
    succ_pay = pay_res.succ_payments
    tot_ord = pay_res.total_orders
    pay_ratio = (succ_pay / tot_ord) if tot_ord > 0 else 0.0

    if 0.90 <= pay_ratio <= 1.00:
        print(f"  ✅ Payment Gateway Success Ratio: {succ_pay:,} / {tot_ord:,} = {pay_ratio*100:.2f}% [PASS]")
        passed += 1
    else:
        print(f"  ❌ Payment Ratio: {succ_pay} / {tot_ord} = {pay_ratio*100:.2f}% [FAIL]")

    total += 1
    ev_cnt_q = f"SELECT COUNT(*) AS cnt FROM `{PROJECT_ID}.{DATASET_ID}.web_events` WHERE created_at >= '{START_TIMESTAMP}' AND created_at <= '{CUTOFF_TIMESTAMP}'"
    ev_cnt = list(client.query(ev_cnt_q).result())[0].cnt
    avg_events_per_sess = (ev_cnt / bw_sessions) if bw_sessions > 0 else 0.0

    if 8.0 <= avg_events_per_sess <= 30.0:
        print(f"  ✅ Clickstream Depth (Events / Session): {ev_cnt:,} / {bw_sessions:,} = {avg_events_per_sess:.2f} events/session [PASS]")
        passed += 1
    else:
        print(f"  ❌ Clickstream Depth: {ev_cnt} / {bw_sessions} = {avg_events_per_sess:.2f} events/session [FAIL]")

    # 2. Check Target Tables Horizon
    print("\n2. Validating Planned Target Horizons (Full 8 Days: Nov 23 - Nov 30)...")
    
    total += 1
    query = f"SELECT COUNT(*) AS cnt, MIN(date) AS min_d, MAX(date) AS max_d FROM `{PROJECT_ID}.{DATASET_ID}.daily_category_targets` WHERE date >= '2026-11-23'"
    res = list(client.query(query).result())[0]
    if res.cnt == 32 and str(res.min_d) == "2026-11-23" and str(res.max_d) == "2026-11-30":
        print(f"  ✅ `daily_category_targets` (Black Week): 32 records spanning {res.min_d} to {res.max_d} [PASS]")
        passed += 1
    else:
        print(f"  ❌ `daily_category_targets`: Expected 32 records (Nov 23 to Nov 30), got {res.cnt} ({res.min_d} to {res.max_d}) [FAIL]")

    total += 1
    # `category_15min_targets` stores a repeating WEEKLY pattern, not a date-keyed
    # series: 7 day_of_week values * 96 fifteen-minute buckets * 4 categories = 2,688
    # rows. Consumers expand it to the 3,072 bucket-days of Black Week (8 days * 96
    # * 4) by joining it to a date spine on EXTRACT(DAYOFWEEK). The previous
    # expectation of 3,072 assumed the table was date-keyed and was simply wrong.
    query = f"""
      SELECT COUNT(*) AS cnt,
             COUNT(DISTINCT day_of_week) AS dows,
             COUNT(DISTINCT time_bucket) AS buckets,
             COUNT(DISTINCT category_id) AS cats
      FROM `{PROJECT_ID}.{DATASET_ID}.category_15min_targets`
    """
    res = list(client.query(query).result())[0]
    if res.cnt == 2688 and res.dows == 7 and res.buckets == 96 and res.cats == 4:
        print("  ✅ `category_15min_targets`: 2,688 rows = 7 day_of_week x 96 buckets "
              "x 4 categories (weekly pattern) [PASS]")
        passed += 1
    else:
        print(f"  ❌ `category_15min_targets`: Expected 2,688 rows (7x96x4), got "
              f"{res.cnt} ({res.dows} dows, {res.buckets} buckets, {res.cats} cats) [FAIL]")



    # 3. Check Operational Tables Temporal Cutoff (Strictly <= Friday Nov 27 14:30:00 UTC)
    print("\n3. Validating Temporal Cutoff on Operational Tables (0 rows post 2026-11-27 14:30:00 UTC)...")
    
    temporal_checks = [
        ("orders", "created_at"),
        ("order_items", "created_at"),
        ("sales_event_stream", "timestamp"),
        ("web_sessions", "session_started_at"),
        ("web_events", "created_at"),
        ("oos_interactions", "clicked_at"),
        ("inventory_snapshots", "recorded_at"),
        ("payment_gateway_logs", "created_at"),
        ("catalog_recommender_logs", "recorded_at"),
        ("competitor_price_feed", "scraped_at")
    ]

    for table_name, col_name in temporal_checks:
        total += 1
        query = f"""
        SELECT 
            MIN({col_name}) AS min_ts,
            MAX({col_name}) AS max_ts,
            COUNTIF({col_name} > '{CUTOFF_TIMESTAMP}') AS post_cutoff_count,
            COUNT(*) AS total_count
        FROM `{PROJECT_ID}.{DATASET_ID}.{table_name}`
        """
        try:
            r = list(client.query(query).result())[0]
            if r.post_cutoff_count == 0:
                print(f"  ✅ `{table_name}` ({r.total_count:,} rows): max={r.max_ts} | post_cutoff=0 [PASS]")
                passed += 1
            else:
                print(f"  ❌ `{table_name}`: Found {r.post_cutoff_count} rows exceeding cutoff! [FAIL]")
        except Exception as e:
            print(f"  ❌ `{table_name}`: Error querying table: {e}")

    # 4. Check Daily Operational Tables (Max date <= 2026-11-27)
    print("\n4. Validating Daily Operational Tables (Max date <= 2026-11-27)...")
    daily_checks = [
        ("daily_ad_performance", "date"),
        ("shipping_lead_times", "date")
    ]
    for table_name, col_name in daily_checks:
        total += 1
        query = f"""
        SELECT 
            MIN({col_name}) AS min_d,
            MAX({col_name}) AS max_d,
            COUNTIF({col_name} > '2026-11-27') AS post_cutoff_count,
            COUNT(*) AS total_count
        FROM `{PROJECT_ID}.{DATASET_ID}.{table_name}`
        """
        try:
            r = list(client.query(query).result())[0]
            if r.post_cutoff_count == 0:
                print(f"  ✅ `{table_name}` ({r.total_count:,} rows): max={r.max_d} | post_cutoff=0 [PASS]")
                passed += 1
            else:
                print(f"  ❌ `{table_name}`: Found {r.post_cutoff_count} records exceeding cutoff! [FAIL]")
        except Exception as e:
            print(f"  ❌ `{table_name}`: Error querying table: {e}")

    # 5. Beauty deficit, MEASURED against the pro-rated plan.
    #
    # This check previously summed three hardcoded literals and asserted they
    # equalled a fourth. It never queried BigQuery, so it passed on an empty
    # warehouse and proved only that addition works. It now measures the deficit.
    #
    # Basis: period-to-date at the cutoff against the PRO-RATED plan, per the
    # `target_to_date` and `pacing_variance` glossary terms. Comparing to-date
    # actuals against the full-period plan is the classic promotional-reporting
    # error and would overstate the gap badly.
    #
    # `category_15min_targets` stores a weekly pattern keyed by BigQuery's native
    # DAYOFWEEK convention (1=Sunday..7=Saturday). Sanity check if you touch this:
    # summed over Nov 23-30 it must reproduce daily_category_targets' 10,702,571.
    print("\n5. Validating the Beauty deficit against the pro-rated plan...")
    total += 1

    EXPECTED_DEFICIT = 520871.0   # measured 2026-09-11; see TECHNICAL_SPECIFICATION 3.4
    TOLERANCE = 0.05              # regeneration drift is acceptable if the story holds

    deficit_query = f"""
    WITH days AS (
      SELECT d AS dt FROM UNNEST(GENERATE_DATE_ARRAY('2026-11-23','2026-11-30')) AS d
    ),
    beauty AS (
      SELECT category_id FROM `{PROJECT_ID}.{DATASET_ID}.categories` WHERE name = 'Beauty'
    ),
    plan AS (
      SELECT SUM(t.target_revenue) AS plan_to_date
      FROM days dy
      JOIN `{PROJECT_ID}.{DATASET_ID}.category_15min_targets` t
        ON t.day_of_week = EXTRACT(DAYOFWEEK FROM dy.dt)
      WHERE t.category_id IN (SELECT category_id FROM beauty)
        AND TIMESTAMP(DATETIME(dy.dt, t.time_bucket)) < TIMESTAMP('{CUTOFF_TIMESTAMP}')
    ),
    act AS (
      SELECT SUM(oi.sale_price * oi.quantity) AS actual_to_date
      FROM `{PROJECT_ID}.{DATASET_ID}.order_items` oi
      JOIN `{PROJECT_ID}.{DATASET_ID}.orders`   o ON o.order_id   = oi.ord_hdr_num
      JOIN `{PROJECT_ID}.{DATASET_ID}.products` p ON p.product_id = oi.mat_nr
      WHERE p.category_id IN (SELECT category_id FROM beauty)
        AND o.created_at >= TIMESTAMP('{START_TIMESTAMP}')
        AND o.created_at <  TIMESTAMP('{CUTOFF_TIMESTAMP}')
    )
    SELECT act.actual_to_date, plan.plan_to_date,
           plan.plan_to_date - act.actual_to_date AS deficit
    FROM act, plan
    """
    d_res = list(client.query(deficit_query).result())[0]
    bty_actual = float(d_res.actual_to_date or 0.0)
    bty_plan = float(d_res.plan_to_date or 0.0)
    bty_deficit = float(d_res.deficit or 0.0)
    pct_behind = (bty_deficit / bty_plan * 100.0) if bty_plan else 0.0
    drift = abs(bty_deficit - EXPECTED_DEFICIT) / EXPECTED_DEFICIT

    if drift <= TOLERANCE:
        print(f"  ✅ Beauty to date: actual €{bty_actual:,.0f} vs pro-rated plan "
              f"€{bty_plan:,.0f} = €{bty_deficit:,.0f} behind ({pct_behind:.2f}%), "
              f"within {TOLERANCE*100:.0f}% of the documented €{EXPECTED_DEFICIT:,.0f} [PASS]")
        passed += 1
    else:
        print(f"  ❌ Beauty deficit €{bty_deficit:,.0f} has drifted {drift*100:.1f}% from "
              f"the documented €{EXPECTED_DEFICIT:,.0f}. Either refresh the published "
              f"figures or investigate the generator. [FAIL]")

    # 5b. The published allocation must still add up to what we just measured.
    # These constants are deliberately COPIES of the documented figures, not
    # imports of the live calculation: comparing documented constants against a
    # measured value is what makes this a genuine documentation-drift check.
    # Source of truth: measure_shortfall_allocation.compute_allocation().
    print("\n5b. Validating the published shortfall allocation still adds up...")
    total += 1
    allocation = {"Stockouts": 62386.0, "Recommender": 49803.86, "Ad throttling": 408681.0}
    alloc_sum = sum(allocation.values())
    alloc_drift = abs(alloc_sum - bty_deficit) / bty_deficit if bty_deficit else 1.0

    if alloc_drift <= 0.02:
        parts = " + ".join(f"€{v:,.0f} ({k})" for k, v in allocation.items())
        print(f"  ✅ Allocation {parts} = €{alloc_sum:,.0f}, within 2% of the "
              f"measured €{bty_deficit:,.0f} [PASS]")
        passed += 1
    else:
        print(f"  ❌ Published allocation sums to €{alloc_sum:,.0f} but the measured "
              f"deficit is €{bty_deficit:,.0f} ({alloc_drift*100:.1f}% apart). "
              f"Update TECHNICAL_SPECIFICATION 3.4 and the case study. [FAIL]")

    print("\n" + "=" * 80)
    success_rate = (passed / total) * 100.0
    print(f"DATA & STATISTICAL RATIOS VALIDATION SUMMARY: {passed}/{total} Tests Passed ({success_rate:.1f}% Success)")
    print("=" * 80)

    if passed != total:
        sys.exit(1)

if __name__ == "__main__":
    run_validation()
