#!/usr/bin/env python3
"""
Measure every CMO ground-truth figure directly from BigQuery
============================================================

WHY THIS EXISTS
---------------
The previous benchmark question Q2 graded agents against the claim that Beauty
conversion "dropped from 3.2% to 2.1%". Measured daily CVR is 3.57 / 3.68 /
3.61 / 4.15 / 4.25 percent — above target every single day. An agent answering
CORRECTLY would have been marked wrong.

That happened because the expected answer was written from a narrative document
instead of from a query. The same check later found that three of the four
red-herring figures in TECHNICAL_SPECIFICATION.md sec 3.4 had also drifted away
from the data.

So: nothing goes into `config/cmo_questions.yaml` unless it comes out of here.

USAGE
-----
    # Print every measured figure.
    python3 scripts/test/measure_cmo_ground_truth.py

    # Compare the YAML against live data. Exits 1 if anything has drifted.
    # Run this after EVERY data rebuild.
    python3 scripts/test/measure_cmo_ground_truth.py --check

    # Widen the drift tolerance (default 0.5%).
    python3 scripts/test/measure_cmo_ground_truth.py --check --drift-pct 2

MEASUREMENT BASIS
-----------------
Everything is period-to-date at the simulation cutoff 2026-11-27 14:30 UTC,
compared against the PRO-RATED plan for the elapsed part of Black Week.
`category_15min_targets` is a weekly pattern: 2,688 rows = 7 days x 96 buckets
x 4 categories, joined on BigQuery's native DAYOFWEEK convention (1=Sunday).
The naive full-period comparison is measured too, because it is the trap the
`pacing_variance` glossary term warns about and the benchmark needs the wrong
number in order to detect it.
"""

import argparse
import os
import sys

try:
    import yaml
except ImportError:
    yaml = None

from google.cloud import bigquery

# --------------------------------------------------------------------------- config
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))  # scripts/test -> scripts -> repo
ENV_PATH = os.path.join(REPO_ROOT, ".env")
QUESTIONS_YAML = os.path.join(REPO_ROOT, "config", "cmo_questions.yaml")

CUTOFF = "2026-11-27 14:30:00"
WINDOW_START = "2026-11-23"
WINDOW_END = "2026-11-30"          # Black Week is 8 days, Nov 23 - Nov 30 inclusive
LAST_PARTIAL_DAY = "2026-11-27"
BEAUTY_CATEGORY_ID = 1


def load_env(path):
    """No hardcoded project ids - everything comes from .env (GEMINI.md rule)."""
    env = {}
    if not os.path.exists(path):
        sys.exit(f".env not found at {path}")
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = load_env(ENV_PATH)
PROJECT = ENV["GCP_PROJECT_ID"]
DATASET = ENV["BQ_DATASET_ID"]
FQ = f"`{PROJECT}.{DATASET}`"

CLIENT = bigquery.Client(project=PROJECT)

# The three-way split of the Beauty deficit is measured, not asserted. The
# arithmetic lives in exactly one place so this gate and the diagnostic report
# can never disagree; see measure_shortfall_allocation.compute_allocation().
sys.path.insert(0, SCRIPT_DIR)
from measure_shortfall_allocation import compute_allocation  # noqa: E402


def q(sql):
    return list(CLIENT.query(sql).result())


def section(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


# =========================================================================== #
# Measurements
# =========================================================================== #

def measure_pacing():
    """Actual vs PRO-RATED plan, and vs the naive FULL-period plan (the trap)."""
    sql = f"""
    WITH spine AS (
      SELECT d FROM UNNEST(GENERATE_DATE_ARRAY(
        DATE '{WINDOW_START}', DATE '{LAST_PARTIAL_DAY}')) AS d
    ),
    plan_to_date AS (
      SELECT t.category_id, SUM(t.target_revenue) AS plan_rev,
                            SUM(t.target_sessions) AS plan_sessions
      FROM spine s
      JOIN {FQ}.category_15min_targets t
        ON t.day_of_week = EXTRACT(DAYOFWEEK FROM s.d)
      WHERE s.d < DATE '{LAST_PARTIAL_DAY}' OR t.time_bucket < TIME '14:30:00'
      GROUP BY 1
    ),
    plan_full AS (
      SELECT t.category_id, SUM(t.target_revenue) AS plan_rev_full
      FROM UNNEST(GENERATE_DATE_ARRAY(DATE '{WINDOW_START}', DATE '{WINDOW_END}')) AS d
      JOIN {FQ}.category_15min_targets t
        ON t.day_of_week = EXTRACT(DAYOFWEEK FROM d)
      GROUP BY 1
    ),
    actual AS (
      SELECT p.category_id, SUM(oi.sale_price * oi.quantity) AS actual_rev
      FROM {FQ}.order_items oi
      JOIN {FQ}.orders o   ON o.order_id  = oi.ord_hdr_num
      JOIN {FQ}.products p ON p.product_id = oi.mat_nr
      WHERE o.created_at >= TIMESTAMP '{WINDOW_START}'
        AND o.created_at <  TIMESTAMP '{CUTOFF}'
      GROUP BY 1
    )
    SELECT c.name AS category,
           pd.plan_rev, pd.plan_sessions, pf.plan_rev_full, a.actual_rev,
           a.actual_rev - pd.plan_rev AS variance,
           (a.actual_rev / pd.plan_rev - 1) * 100 AS variance_pct,
           (a.actual_rev / pf.plan_rev_full - 1) * 100 AS naive_variance_pct,
           a.actual_rev - pf.plan_rev_full AS naive_variance
    FROM plan_to_date pd
    JOIN plan_full pf ON pf.category_id = pd.category_id
    JOIN actual a     ON a.category_id  = pd.category_id
    JOIN {FQ}.categories c ON c.category_id = pd.category_id
    ORDER BY variance
    """
    out = {}
    tot_plan = tot_actual = tot_plan_full = 0.0
    for r in q(sql):
        out[r.category] = {
            "plan": float(r.plan_rev),
            "plan_sessions": float(r.plan_sessions or 0),
            "plan_full": float(r.plan_rev_full),
            "actual": float(r.actual_rev),
            "variance": float(r.variance),
            "variance_pct": float(r.variance_pct),
            "naive_variance": float(r.naive_variance),
            "naive_variance_pct": float(r.naive_variance_pct),
        }
        tot_plan += float(r.plan_rev)
        tot_actual += float(r.actual_rev)
        tot_plan_full += float(r.plan_rev_full)

    out["_STOREWIDE"] = {
        "plan": tot_plan,
        "plan_full": tot_plan_full,
        "actual": tot_actual,
        "variance": tot_actual - tot_plan,
        "variance_pct": (tot_actual / tot_plan - 1) * 100,
        "naive_variance": tot_actual - tot_plan_full,
        "naive_variance_pct": (tot_actual / tot_plan_full - 1) * 100,
    }
    return out


def print_pacing(m):
    section("PACING — actual vs pro-rated plan (and the naive full-period trap)")
    hdr = (f"   {'category':<14}{'plan':>13}{'actual':>13}{'variance':>12}"
           f"{'var %':>9}{'NAIVE var %':>13}")
    print(hdr)
    for name, v in m.items():
        label = "STOREWIDE" if name == "_STOREWIDE" else name
        print(f"   {label:<14}{v['plan']:>13,.0f}{v['actual']:>13,.0f}"
              f"{v['variance']:>12,.0f}{v['variance_pct']:>8.2f}%"
              f"{v['naive_variance_pct']:>12.2f}%")
    print("\n   The NAIVE column is what an agent reports when it compares to-date")
    print("   actuals against the whole-week plan. It is the pacing trap.")


def measure_beauty_totals():
    """Window totals for Beauty: sessions vs plan, and CVR vs a SESSION-WEIGHTED
    target.

    The daily target conversion rate varies (3.98 -> 3.68 across the window), so
    a straight average of daily rates is not the target for the window. It has to
    be weighted by planned sessions. Getting this wrong is how the question set
    came to claim a flat "3.2% target" that exists nowhere in the data.
    """
    sql = f"""
    WITH act AS (
      SELECT COUNT(*) AS sessions, COUNTIF(converted_to_order) AS conv
      FROM {FQ}.web_sessions
      WHERE primary_category_id = {BEAUTY_CATEGORY_ID}
        AND session_started_at >= TIMESTAMP '{WINDOW_START}'
        AND session_started_at <  TIMESTAMP '{CUTOFF}'
    ),
    dsess AS (
      SELECT d, SUM(IF(d < DATE '{LAST_PARTIAL_DAY}' OR t.time_bucket < TIME '14:30:00',
                       t.target_sessions, 0)) AS ps
      FROM UNNEST(GENERATE_DATE_ARRAY(DATE '{WINDOW_START}',
                                      DATE '{LAST_PARTIAL_DAY}')) AS d
      JOIN {FQ}.category_15min_targets t
        ON t.day_of_week = EXTRACT(DAYOFWEEK FROM d)
      WHERE t.category_id = {BEAUTY_CATEGORY_ID}
      GROUP BY d
    ),
    wt AS (
      SELECT SUM(ds.ps) AS plan_sessions,
             SUM(ds.ps * tg.target_conversion_rate * 100) / SUM(ds.ps) AS cvr_target
      FROM dsess ds
      JOIN {FQ}.daily_category_targets tg
        ON tg.date = ds.d AND tg.category_id = {BEAUTY_CATEGORY_ID}
    )
    SELECT a.sessions, a.conv, a.conv / a.sessions * 100 AS cvr_actual,
           wt.plan_sessions, wt.cvr_target,
           (a.sessions / wt.plan_sessions - 1) * 100 AS sessions_vs_plan_pct,
           (a.conv / a.sessions * 100 / wt.cvr_target - 1) * 100 AS cvr_vs_target_pct
    FROM act a, wt
    """
    r = q(sql)[0]
    return {
        "sessions": int(r.sessions),
        "plan_sessions": float(r.plan_sessions),
        "sessions_vs_plan_pct": float(r.sessions_vs_plan_pct),
        "cvr_actual_pct": round(float(r.cvr_actual), 3),
        "cvr_target_pct": round(float(r.cvr_target), 3),
        "cvr_vs_target_pct": float(r.cvr_vs_target_pct),
    }


def measure_beauty_funnel():
    """Sessions vs plan, and conversion vs target, per day."""
    sql = f"""
    WITH actual AS (
      SELECT DATE(session_started_at) AS d,
             COUNT(*) AS sessions,
             COUNTIF(traffic_source IN ('Paid Search','Paid Social')) AS paid_sessions,
             SAFE_DIVIDE(COUNTIF(converted_to_order), COUNT(*)) * 100 AS cvr_pct
      FROM {FQ}.web_sessions
      WHERE primary_category_id = {BEAUTY_CATEGORY_ID}
        AND session_started_at >= TIMESTAMP '{WINDOW_START}'
        AND session_started_at <  TIMESTAMP '{CUTOFF}'
      GROUP BY d
    ),
    plan AS (
      SELECT d,
             SUM(IF(d < DATE '{LAST_PARTIAL_DAY}' OR t.time_bucket < TIME '14:30:00',
                    t.target_sessions, 0)) AS plan_sessions
      FROM UNNEST(GENERATE_DATE_ARRAY(DATE '{WINDOW_START}',
                                      DATE '{LAST_PARTIAL_DAY}')) AS d
      JOIN {FQ}.category_15min_targets t
        ON t.day_of_week = EXTRACT(DAYOFWEEK FROM d)
      WHERE t.category_id = {BEAUTY_CATEGORY_ID}
      GROUP BY d
    ),
    tgt AS (
      SELECT date AS d, target_conversion_rate * 100 AS cvr_target_pct
      FROM {FQ}.daily_category_targets
      WHERE category_id = {BEAUTY_CATEGORY_ID}
    )
    SELECT a.d, a.sessions, a.paid_sessions, ROUND(a.cvr_pct, 2) AS cvr_pct,
           p.plan_sessions,
           (a.sessions / NULLIF(p.plan_sessions, 0) - 1) * 100 AS sessions_vs_plan_pct,
           ROUND(tgt.cvr_target_pct, 2) AS cvr_target_pct
    FROM actual a
    JOIN plan p ON p.d = a.d
    LEFT JOIN tgt ON tgt.d = a.d
    ORDER BY a.d
    """
    return [dict(r.items()) for r in q(sql)]


def print_funnel(rows):
    section("BEAUTY FUNNEL — did traffic break, or did conversion break?")
    print(f"   {'date':<12}{'sessions':>10}{'plan':>11}{'vs plan':>10}"
          f"{'CVR %':>8}{'target':>8}")
    for r in rows:
        vs = r["sessions_vs_plan_pct"]
        print(f"   {str(r['d']):<12}{r['sessions']:>10,}"
              f"{float(r['plan_sessions'] or 0):>11,.0f}"
              f"{(vs if vs is not None else 0):>9.1f}%"
              f"{float(r['cvr_pct'] or 0):>8.2f}"
              f"{float(r['cvr_target_pct'] or 0):>8.2f}")
    complete = [r for r in rows if str(r["d"]) != LAST_PARTIAL_DAY]
    if complete:
        avg = sum(r["sessions_vs_plan_pct"] for r in complete) / len(complete)
        print(f"\n   Sessions vs plan, complete days only: {avg:.1f}%")
        print("   Conversion ran ABOVE target every day. The traffic side broke,")
        print("   not the conversion side. This is what the old Q2 got wrong.")
    return complete


def measure_oos_trap():
    r = q(f"SELECT SUM(pot_val) AS gross, COUNT(*) AS n FROM {FQ}.oos_interactions")[0]
    return {"gross": float(r.gross or 0), "rows": int(r.n)}


def measure_roas():
    sql = f"""
    WITH spend AS (
      SELECT SUM(dap.spend) AS ad_spend
      FROM {FQ}.daily_ad_performance dap
      JOIN {FQ}.marketing_campaigns mc ON mc.campaign_id = dap.cid_ref
      WHERE mc.target_category_id = {BEAUTY_CATEGORY_ID}
        AND dap.date BETWEEN DATE '{WINDOW_START}' AND DATE '{LAST_PARTIAL_DAY}'
    ),
    rev AS (
      SELECT SUM(oi.sale_price * oi.quantity) AS all_rev,
             SUM(IF(ws.traffic_source IN ('Paid Search','Paid Social'),
                    oi.sale_price * oi.quantity, 0)) AS paid_rev
      FROM {FQ}.order_items oi
      JOIN {FQ}.orders o   ON o.order_id   = oi.ord_hdr_num
      JOIN {FQ}.products p ON p.product_id = oi.mat_nr
      LEFT JOIN {FQ}.web_sessions ws ON ws.session_id = o.session_id
      WHERE p.category_id = {BEAUTY_CATEGORY_ID}
        AND o.created_at >= TIMESTAMP '{WINDOW_START}'
        AND o.created_at <  TIMESTAMP '{CUTOFF}'
    ),
    plan AS (
      SELECT AVG(target_roas) AS target_roas
      FROM {FQ}.daily_category_targets
      WHERE category_id = {BEAUTY_CATEGORY_ID}
        AND date BETWEEN DATE '{WINDOW_START}' AND DATE '{LAST_PARTIAL_DAY}'
    )
    SELECT s.ad_spend, r.all_rev, r.paid_rev,
           r.all_rev  / s.ad_spend AS blended_roas,
           r.paid_rev / s.ad_spend AS paid_roas,
           p.target_roas
    FROM spend s, rev r, plan p
    """
    r = q(sql)[0]
    return {
        "ad_spend": float(r.ad_spend or 0),
        "all_rev": float(r.all_rev or 0),
        "paid_rev": float(r.paid_rev or 0),
        "blended_roas": round(float(r.blended_roas), 2),
        "paid_roas": round(float(r.paid_roas), 2),
        "target_roas": round(float(r.target_roas), 2),
    }


def measure_discounts():
    r = q(f"""SELECT COUNT(*) AS n, COUNTIF(discount_amount != 0) AS nz,
                     SUM(discount_amount) AS total
              FROM {FQ}.order_items""")[0]
    return {"rows": int(r.n), "non_zero": int(r.nz), "total": float(r.total or 0)}


def measure_payment_herring():
    """Daily 504 timeouts during Black Week - is there a spike, or is it flat?"""
    sql = f"""
    SELECT DATE(created_at) AS d, payment_provider,
           COUNT(*) AS n, SUM(total_amount) AS value
    FROM {FQ}.payment_gateway_logs
    WHERE http_status_code = 504
      AND created_at >= TIMESTAMP '{WINDOW_START}'
      AND created_at <  TIMESTAMP '{CUTOFF}'
    GROUP BY 1, 2 ORDER BY 1
    """
    rows = [dict(r.items()) for r in q(sql)]

    # The headline series 218/267/287/226/134 is ALL PROVIDERS combined, not
    # Adyen. An earlier version of the question set attributed it to Adyen
    # alone, which is wrong by roughly 2x - Adyen's own peak is 158.
    by_day = {}
    for r in rows:
        d = str(r["d"])
        by_day.setdefault(d, {"all_n": 0, "adyen_n": 0, "value": 0.0})
        by_day[d]["all_n"] += int(r["n"])
        by_day[d]["value"] += float(r["value"] or 0)
        if r["payment_provider"] == "Adyen":
            by_day[d]["adyen_n"] += int(r["n"])

    peak_day = max(by_day, key=lambda d: by_day[d]["all_n"]) if by_day else None
    return {
        "daily": rows,
        "by_day": by_day,
        "peak_day": peak_day,
        "peak_all_n": by_day[peak_day]["all_n"] if peak_day else 0,
        "peak_adyen_n": by_day[peak_day]["adyen_n"] if peak_day else 0,
        "peak_value": by_day[peak_day]["value"] if peak_day else 0.0,
    }


def measure_competitor_herring():
    sql = f"""
    SELECT category_id,
           MIN(price_index_vs_lumiere) AS lo,
           MAX(price_index_vs_lumiere) AS hi,
           COUNT(*) AS n
    FROM {FQ}.competitor_promotions GROUP BY 1 ORDER BY 1
    """
    return {int(r.category_id): {"lo": round(float(r.lo), 3),
                                 "hi": round(float(r.hi), 3),
                                 "n": int(r.n)} for r in q(sql)}


def measure_throttling():
    sql = f"""
    SELECT status_change, action_taken, COUNT(*) AS n,
           MIN(logged_at) AS first_at, MIN(budget_multiplier) AS min_mult
    FROM {FQ}.ad_bidding_log GROUP BY 1, 2 ORDER BY n DESC
    """
    return [dict(r.items()) for r in q(sql)]


def measure_recommender():
    r = q(f"""SELECT COUNT(*) AS n, COUNTIF(cat_mismatch_flg = 1) AS mismatched
              FROM {FQ}.catalog_recommender_logs""")[0]
    return {"rows": int(r.n), "mismatched": int(r.mismatched)}


# =========================================================================== #
# Drift check against the YAML
# =========================================================================== #

def build_expectations(m):
    """Map (question_id, figure_key) -> measured value.

    Only figures derivable from a query appear here.

    The three-way split of the Beauty deficit USED TO live in NOT_MEASURABLE,
    because it was a published attribution the warehouse could not confirm. It
    is now measured: the two on-site frictions are derived from transactional
    facts and ad throttling is the residual. See compute_allocation(). That
    change is the fix for the defect where the glossary's certified stockout
    method silently absorbed the concurrent ad-throttling losses and returned
    87% of the deficit instead of 12%.
    """
    p = m["pacing"]
    b = p["Beauty"]
    sw = p["_STOREWIDE"]
    tot = m["beauty_totals"]
    roas = m["roas"]
    comp = m["competitor"]
    pay = m["payment"]

    exp = {
        # --- demo set
        ("D-Q1", "beauty_variance"): b["variance"],
        ("D-Q1", "beauty_variance_pct"): b["variance_pct"],
        ("D-Q1", "electronics_variance_pct"): p["Electronics"]["variance_pct"],
        ("D-Q1", "home_variance_pct"): p["Home"]["variance_pct"],
        ("D-Q1", "fashion_variance_pct"): p["Fashion"]["variance_pct"],
        ("D-Q2", "sessions_vs_plan_pct"): tot["sessions_vs_plan_pct"],
        ("D-Q2", "cvr_actual_pct"): tot["cvr_actual_pct"],
        ("D-Q2", "cvr_target_pct"): tot["cvr_target_pct"],
        ("D-Q4", "mismatched_impressions"): m["recommender"]["mismatched"],
        ("D-Q6", "total_deficit"): b["variance"],
        # --- benchmark set
        ("B-D1", "storewide_variance_pct"): sw["variance_pct"],
        ("B-D1", "beauty_variance_pct"): b["variance_pct"],
        ("B-D2", "beauty"): b["variance"],
        ("B-D2", "electronics"): p["Electronics"]["variance"],
        ("B-D2", "home"): p["Home"]["variance"],
        ("B-D2", "fashion"): p["Fashion"]["variance"],
        ("B-D3", "sessions_vs_plan_pct"): tot["sessions_vs_plan_pct"],
        ("B-D3", "cvr_actual_pct"): tot["cvr_actual_pct"],
        ("B-D3", "cvr_target_pct"): tot["cvr_target_pct"],
        ("B-S2", "blended_actual"): roas["blended_roas"],
        ("B-S2", "blended_target"): roas["target_roas"],
        ("B-X1", "total_deficit"): b["variance"],
    }
    if comp.get(BEAUTY_CATEGORY_ID):
        exp[("B-R2", "beauty_index_low")] = comp[BEAUTY_CATEGORY_ID]["lo"]
    exp[("B-D1", "naive_storewide_variance")] = sw["naive_variance"]
    exp[("B-D1", "naive_storewide_variance_pct")] = sw["naive_variance_pct"]
    exp[("B-D2", "naive_beauty")] = b["naive_variance"]
    exp[("B-D2", "naive_beauty_pct")] = b["naive_variance_pct"]
    exp[("B-D2", "naive_electronics")] = p["Electronics"]["naive_variance"]
    exp[("B-D2", "naive_home")] = p["Home"]["naive_variance"]
    exp[("B-D2", "naive_fashion")] = p["Fashion"]["naive_variance"]

    # --- context values: not graded against agents, but asserted in the
    # summaries, so they must not drift either.
    oos = m["oos"]
    # `m["discounts"]` is deliberately not bound here any more - its only
    # consumer was the retired B-S3 gate. It is still measured, and still
    # reported by the caller further down this file.
    alloc = m["allocation"]
    exp[("B-S1", "naive_wrong")] = oos["gross"]
    exp[("B-S1", "overstatement_factor")] = alloc["overstatement_factor"]
    exp[("B-S1", "correct")] = alloc["stockout"]

    # The certified allocation - now measured, so the gate enforces it.
    exp[("D-Q3", "attributed_loss")] = alloc["stockout"]
    exp[("D-Q3", "share_of_deficit_pct")] = alloc["stockout_pct"]
    exp[("D-Q4", "attributed_loss")] = alloc["recommender"]
    exp[("D-Q4", "share_of_deficit_pct")] = alloc["recommender_pct"]
    exp[("D-Q4", "bounced_impressions")] = float(alloc["bounced_impressions"])
    exp[("D-Q5", "attributed_loss")] = alloc["throttling"]
    exp[("D-Q5", "share_of_deficit_pct")] = alloc["throttling_pct"]
    for qid in ("D-Q6", "B-X1"):
        exp[(qid, "stockouts")] = alloc["stockout"]
        exp[(qid, "recommender")] = alloc["recommender"]
        exp[(qid, "ads")] = alloc["throttling"]
    exp[("B-S2", "paid_attributed")] = roas["paid_roas"]
    exp[("B-S2", "ad_spend")] = roas["ad_spend"]
    # B-S3 ("how much did we give away in discounts") was RETIRED from
    # config/cmo_questions.yaml on 2026-09-13, so there is no longer a
    # published `rows` / `non_zero` figure for this gate to pin. The
    # underlying discount measurement is still taken and still printed
    # below, because a sudden non-zero discount_amount would mean the data
    # generator had changed behaviour and we would want to see that.
    # Retired because the question only separated the agent tiers when the
    # agent held the glossary term "Known Unpopulated Columns", which the
    # unified discovery prompt does not retrieve.

    # categories: 1 = Beauty, 2 = Electronics, 3 = Fashion, 4 = Home.
    # This was previously named HOME_CATEGORY_ID, which was wrong: id 3 is
    # Fashion. The figure itself was always correct, but it was published in
    # config/cmo_questions.yaml under a "Home" label. Fashion is the right
    # category to cite anyway - it is the one where competitors are clearly
    # MORE expensive (1.043-1.168), which is what the red herring rests on.
    FASHION_CATEGORY_ID = 3
    if comp.get(BEAUTY_CATEGORY_ID):
        exp[("B-R2", "beauty_index_high")] = comp[BEAUTY_CATEGORY_ID]["hi"]
    if comp.get(FASHION_CATEGORY_ID):
        exp[("B-R2", "fashion_index_low")] = comp[FASHION_CATEGORY_ID]["lo"]
        exp[("B-R2", "fashion_index_high")] = comp[FASHION_CATEGORY_ID]["hi"]

    throttle = [r for r in m["throttling"]
                if r["status_change"] == "TARGET_ROAS_BREACH_THROTTLED"]
    if throttle:
        exp[("D-Q5", "throttle_events")] = float(throttle[0]["n"])
        exp[("D-Q5", "min_budget_multiplier")] = float(throttle[0]["min_mult"])

    if pay.get("peak_day"):
        exp[("B-R1", "peak_count")] = float(pay["peak_all_n"])
        exp[("B-R1", "peak_value")] = float(pay["peak_value"])
        exp[("B-R1", "adyen_peak_count")] = float(pay["peak_adyen_n"])
    return exp


# Every figure in cmo_questions.yaml is now derivable from the warehouse.
# Entries added here are reported by --check as "not measurable" rather than
# compared, so this set must stay empty unless something genuinely cannot be
# measured. It was emptied on 2026-09-12 when the three-way split of the Beauty
# deficit stopped being a published allocation and became a measurement.
NOT_MEASURABLE = set()


def run_check(m, drift_pct):
    if yaml is None:
        sys.exit("PyYAML is required for --check:  python3 -m pip install pyyaml")
    if not os.path.exists(QUESTIONS_YAML):
        sys.exit(f"Question set not found: {QUESTIONS_YAML}")
    with open(QUESTIONS_YAML, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    expectations = build_expectations(m)
    drifted, ok, uncovered, allocated = [], [], [], []

    for set_key in ("demo_script", "benchmark"):
        for question in cfg.get(set_key) or []:
            qid = question["id"]
            gt = question.get("ground_truth") or {}
            # `context` values are not graded against agents, but they ARE
            # asserted in the human-readable summary, so they must not drift
            # either. The "3.2% conversion target" that broke this question set
            # twice lived in `context`.
            merged = dict(gt.get("figures") or {})
            merged.update(gt.get("context") or {})
            for key, stated in merged.items():
                if not isinstance(stated, (int, float)) or isinstance(stated, bool):
                    continue
                pair = (qid, key)
                if pair in NOT_MEASURABLE:
                    allocated.append((qid, key, stated))
                    continue
                if pair not in expectations:
                    uncovered.append((qid, key, stated))
                    continue
                actual = float(expectations[pair])
                stated_f = float(stated)
                # SIGN-INSENSITIVE, matching the runner's scorer: a deficit is
                # written "-520,871" in a plan comparison and "520,871" when
                # called a shortfall. Comparing signed values reported a
                # spurious 200% drift on every such figure.
                a, b = abs(actual), abs(stated_f)
                denom = a if a else 1.0
                delta = abs(b - a) / denom * 100
                if delta > drift_pct:
                    drifted.append((qid, key, stated_f, actual, delta))
                else:
                    ok.append((qid, key, stated_f, actual, delta))

    section(f"DRIFT CHECK — config/cmo_questions.yaml vs live data "
            f"(tolerance {drift_pct}%)")

    print(f"\n   {len(ok)} figure(s) match measured data.")

    if allocated:
        print(f"\n   {len(allocated)} figure(s) are PUBLISHED ALLOCATIONS, not")
        print("   measurements, so they are not checkable against the warehouse:")
        for qid, key, stated in allocated:
            print(f"      {qid:<6} {key:<26} {stated:>14,}")

    if uncovered:
        print(f"\n   WARNING: {len(uncovered)} figure(s) have NO measurement behind them.")
        print("   Add a query for each, or move it into the `context` block:")
        for qid, key, stated in uncovered:
            print(f"      {qid:<6} {key:<26} {stated:>14,}")

    if drifted:
        print(f"\n   FAILED: {len(drifted)} figure(s) have DRIFTED from the data:")
        print(f"      {'question':<8}{'figure':<28}{'in YAML':>16}{'measured':>16}{'delta':>9}")
        for qid, key, stated, actual, delta in drifted:
            print(f"      {qid:<8}{key:<28}{stated:>16,.2f}{actual:>16,.2f}{delta:>8.1f}%")
        print("\n   Update config/cmo_questions.yaml with the measured values before")
        print("   grading any agent against it.")
        return 1

    print("\n   PASS — no measured figure has drifted.")
    return 1 if uncovered else 0


# =========================================================================== #
# Main
# =========================================================================== #

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="compare config/cmo_questions.yaml against live data; "
                         "exit 1 on drift")
    ap.add_argument("--drift-pct", type=float, default=0.5,
                    help="allowed drift before --check fails (default: 0.5)")
    ap.add_argument("--quiet", action="store_true",
                    help="with --check, suppress the measurement dump")
    args = ap.parse_args()

    verbose = not (args.check and args.quiet)

    print(f"project {PROJECT} · dataset {DATASET} · cutoff {CUTOFF} UTC")

    m = {}
    m["pacing"] = measure_pacing()
    if verbose:
        print_pacing(m["pacing"])

    funnel = measure_beauty_funnel()
    m["funnel"] = funnel
    m["beauty_totals"] = measure_beauty_totals()
    if verbose:
        print_funnel(funnel)
        t = m["beauty_totals"]
        print(f"\n   WINDOW TOTALS")
        print(f"      sessions {t['sessions']:,} vs plan {t['plan_sessions']:,.0f}"
              f"  =  {t['sessions_vs_plan_pct']:+.2f}%")
        print(f"      CVR {t['cvr_actual_pct']}% vs session-weighted target "
              f"{t['cvr_target_pct']}%  =  {t['cvr_vs_target_pct']:+.2f}%")
        ratio = abs(t['sessions_vs_plan_pct']) / max(abs(t['cvr_vs_target_pct']), 0.01)
        print(f"      the traffic gap is {ratio:.0f}x the conversion gap")

    m["oos"] = measure_oos_trap()
    m["allocation"] = compute_allocation()
    if verbose:
        section("SEMANTIC TRAP — SUM(oos_interactions.pot_val)")
        gross = m["oos"]["gross"]
        print(f"   NAIVE   SUM(pot_val)            EUR {gross:>16,.2f}  "
              f"({m['oos']['rows']:,} rows)")
        a = m["allocation"]
        print(f"   CORRECT certified method        EUR {a['stockout']:>16,.2f}")
        print(f"      = SUM(pot_val) x paid CVR {a['paid_cvr_pct']:.3f}%")
        print(f"   overstatement factor            "
              f"{a['overstatement_factor']:>16.1f}x")
        print("\n   pot_val is GROSS attempted basket value. The naive sum exceeds")
        print("   the entire storewide deficit, which is the tell.")

    m["roas"] = measure_roas()
    if verbose:
        section("SEMANTIC TRAP — ROAS convention collision (Beauty)")
        r = m["roas"]
        print(f"   ad spend                 EUR {r['ad_spend']:>14,.0f}")
        print(f"   all-channel revenue      EUR {r['all_rev']:>14,.0f}")
        print(f"   paid-attributed revenue  EUR {r['paid_rev']:>14,.0f}")
        print(f"   BLENDED roas   {r['blended_roas']:>6.2f}x   vs plan target "
              f"{r['target_roas']:.2f}x  <- same convention, Beauty is AHEAD")
        print(f"   PAID    roas   {r['paid_roas']:>6.2f}x   <- different measure, "
              f"must NOT be compared to the target")

    m["discounts"] = measure_discounts()
    if verbose:
        section("SEMANTIC TRAP — unpopulated field")
        d = m["discounts"]
        print(f"   order_items rows {d['rows']:,} · non-zero discount_amount "
              f"{d['non_zero']} · SUM {d['total']:,.2f}")
        print("   The honest answer is 'this field is not populated', not 'we gave")
        print("   no discounts'.")

    m["payment"] = measure_payment_herring()
    if verbose:
        section("RED HERRING — payment gateway 504s during Black Week")
        print(f"   {'date':<12}{'all providers':>14}{'of which Adyen':>16}{'value':>14}")
        for d, v in sorted(m["payment"]["by_day"].items()):
            print(f"   {d:<12}{v['all_n']:>14,}{v['adyen_n']:>16,}"
                  f"   EUR {v['value']:>11,.2f}")
        print("\n   The headline series is ALL PROVIDERS, not Adyen alone.")
        print("   Flat across the week and storewide, so it cannot explain a")
        print("   deficit concentrated in one category.")

    m["competitor"] = measure_competitor_herring()
    if verbose:
        section("RED HERRING — competitor price index")
        for cid, v in m["competitor"].items():
            print(f"   category {cid}: {v['lo']} .. {v['hi']}  ({v['n']} promos)")
        print("\n   Around parity. Above 1.0 means the competitor is MORE expensive.")

    m["recommender"] = measure_recommender()
    if verbose:
        section("RECOMMENDER — category mismatch rate")
        rec = m["recommender"]
        print(f"   {rec['mismatched']:,} of {rec['rows']:,} impressions flagged "
              f"cat_mismatch_flg = 1 "
              f"({rec['mismatched'] / rec['rows'] * 100:.1f}%)")

    m["throttling"] = measure_throttling()
    if verbose:
        section("AD THROTTLING — ad_bidding_log")
        for r in m["throttling"]:
            print(f"   {str(r['status_change']):<36}{str(r['action_taken']):<24}"
                  f"n={r['n']:<4}first={r['first_at']}  "
                  f"min_mult={r['min_mult']}")

    if args.check:
        sys.exit(run_check(m, args.drift_pct))


if __name__ == "__main__":
    main()
