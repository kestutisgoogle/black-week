#!/usr/bin/env python3
"""Measure the Beauty shortfall allocation from live BigQuery data.

READ-ONLY. Runs SELECT queries only; writes nothing.

Background
----------
The Beauty Black Week revenue deficit is EUR ~520,871. Our case study attributes
it to three causes:

    stockouts           12.3%   (~EUR 64,000)   catalyst
    recommender         9.4%    (~EUR 49,000)   secondary friction
    ad throttling       78.3%   (~EUR 408,000)  amplifier

Until now all three were *published allocations*, not measurements. Neither
`catalog_recommender_logs.opp_cost_eur` nor any other column holds a
pre-computed loss - `opp_cost_eur` is a reserved field and is always zero.

This script derives each component from transactional facts using one single
consistent methodology:

    lost revenue = missing demand  x  conversion propensity  x  order value

and reports how the components reconcile against the measured deficit.

Usage
-----
    python3 scripts/test/measure_shortfall_allocation.py
"""

import os
import sys

from google.cloud import bigquery

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))  # scripts/test -> scripts -> repo
ENV_PATH = os.path.join(REPO_ROOT, ".env")

# Black Week is 8 days, Nov 23 - Nov 30 inclusive. The simulation is frozen
# mid-morning on Friday Nov 27, so every "to date" figure stops at the cutoff.
CUTOFF = "2026-11-27 14:30:00"
WINDOW_START = "2026-11-23"
LAST_PARTIAL_DAY = "2026-11-27"
BEAUTY_CATEGORY_ID = 1

# Paid channel convention, matching measure_cmo_ground_truth.py.
PAID_CHANNELS = "('Paid Search','Paid Social')"

# The published allocation we are testing against.
PUBLISHED = {"stockout": 64000.0, "recommender": 49000.0, "ad_throttling": 408000.0}


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


def q(sql):
    return list(CLIENT.query(sql).result())


def section(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def money(x):
    return "n/a" if x is None else f"EUR {float(x):>14,.2f}"


def pct(x):
    return "n/a" if x is None else f"{float(x):>7.3f}%"


# =========================================================================== #
# 1. Diagnostics - what is actually in the tables
# =========================================================================== #

def diag_recommender_actions():
    """We need to know what a 'bounced' recommender impression looks like."""
    sql = f"""
    SELECT user_action, cat_mismatch_flg, COUNT(*) AS n
    FROM {FQ}.catalog_recommender_logs
    GROUP BY 1, 2
    ORDER BY cat_mismatch_flg DESC, n DESC
    """
    return [dict(r.items()) for r in q(sql)]


def diag_oos_window():
    """The true unavailability window, straight from the click stream."""
    sql = f"""
    SELECT o.art_code,
           p.name           AS product_name,
           p.category_id,
           MIN(o.clicked_at) AS first_click,
           MAX(o.clicked_at) AS last_click,
           COUNT(*)          AS clicks,
           SUM(o.pot_val)    AS gross_pot_val
    FROM {FQ}.oos_interactions o
    JOIN {FQ}.products p ON p.product_id = o.art_code
    GROUP BY 1, 2, 3
    ORDER BY gross_pot_val DESC
    """
    return [dict(r.items()) for r in q(sql)]


# =========================================================================== #
# 2. Conversion propensity and order value
# =========================================================================== #

def measure_cvr_and_aov():
    """Every conversion-rate convention we might reasonably use, plus AOV.

    Measured two ways: over the whole Black-Week-to-cutoff window, and over the
    stockout window only. Pinning this down matters because the glossary
    formula must name exactly one of them.
    """
    def block(label, start, end_expr, cat_filter):
        return f"""
        SELECT '{label}' AS scope,
               COUNT(*)                                             AS sessions,
               COUNTIF(traffic_source IN {PAID_CHANNELS})            AS paid_sessions,
               COUNTIF(converted_to_order)                           AS conversions,
               COUNTIF(converted_to_order
                       AND traffic_source IN {PAID_CHANNELS})        AS paid_conversions
        FROM {FQ}.web_sessions
        WHERE session_started_at >= TIMESTAMP '{start}'
          AND session_started_at <  {end_expr}
          {cat_filter}
        """

    beauty = f"AND primary_category_id = {BEAUTY_CATEGORY_ID}"
    sql = " UNION ALL ".join([
        block("beauty_blackweek", WINDOW_START, f"TIMESTAMP '{CUTOFF}'", beauty),
        block("beauty_oos_window", "2026-11-23", "TIMESTAMP '2026-11-26'", beauty),
        block("sitewide_blackweek", WINDOW_START, f"TIMESTAMP '{CUTOFF}'", ""),
        block("sitewide_oos_window", "2026-11-23", "TIMESTAMP '2026-11-26'", ""),
    ])

    out = {}
    for r in q(sql):
        d = dict(r.items())
        d["cvr_pct"] = 100.0 * d["conversions"] / d["sessions"] if d["sessions"] else None
        d["paid_cvr_pct"] = (100.0 * d["paid_conversions"] / d["paid_sessions"]
                             if d["paid_sessions"] else None)
        out[d["scope"]] = d
    return out


def measure_aov():
    """Average order value for Beauty, and sitewide, over Black Week to date.

    Beauty orders are identified through the order's session category, because
    `orders` carries no category_id.
    """
    sql = f"""
    WITH beauty_orders AS (
      SELECT o.order_id, o.total_amount
      FROM {FQ}.orders o
      JOIN {FQ}.web_sessions s ON s.session_id = o.session_id
      WHERE s.primary_category_id = {BEAUTY_CATEGORY_ID}
        AND o.created_at >= TIMESTAMP '{WINDOW_START}'
        AND o.created_at <  TIMESTAMP '{CUTOFF}'
    ),
    all_orders AS (
      SELECT order_id, total_amount
      FROM {FQ}.orders
      WHERE created_at >= TIMESTAMP '{WINDOW_START}'
        AND created_at <  TIMESTAMP '{CUTOFF}'
    )
    SELECT 'beauty' AS scope, COUNT(*) AS orders, SUM(total_amount) AS revenue,
           AVG(total_amount) AS aov FROM beauty_orders
    UNION ALL
    SELECT 'sitewide', COUNT(*), SUM(total_amount), AVG(total_amount) FROM all_orders
    """
    return {r["scope"]: dict(r.items()) for r in [dict(x.items()) for x in q(sql)]}


# =========================================================================== #
# 3. The three components
# =========================================================================== #

def measure_stockout_component():
    """Gross attempted demand on out-of-stock hero SKUs, by category."""
    sql = f"""
    SELECT p.category_id,
           c.name         AS category_name,
           COUNT(*)       AS clicks,
           SUM(o.pot_val) AS gross_pot_val
    FROM {FQ}.oos_interactions o
    JOIN {FQ}.products   p ON p.product_id  = o.art_code
    JOIN {FQ}.categories c ON c.category_id = p.category_id
    GROUP BY 1, 2
    ORDER BY gross_pot_val DESC
    """
    return [dict(r.items()) for r in q(sql)]


def measure_recommender_component():
    """Mismatched recommender impressions that the shopper abandoned.

    `opp_cost_eur` is a reserved column and always zero, so the opportunity
    cost has to be derived: bounced mismatched impressions x conversion
    propensity x order value.
    """
    sql = f"""
    SELECT p.category_id,
           COUNT(*)                                  AS impressions,
           COUNTIF(r.cat_mismatch_flg = 1)           AS mismatched,
           COUNTIF(r.cat_mismatch_flg = 1
                   AND r.user_action = 'IGNORED')    AS mismatched_ignored,
           COUNTIF(r.cat_mismatch_flg = 1
                   AND r.user_action = 'BOUNCED')    AS mismatched_bounced
    FROM {FQ}.catalog_recommender_logs r
    JOIN {FQ}.products p ON p.product_id = r.src_sku
    GROUP BY 1
    ORDER BY impressions DESC
    """
    return [dict(r.items()) for r in q(sql)]


def measure_session_deficit():
    """Beauty session shortfall against the 15-minute plan, to the cutoff.

    This is the traffic collapse caused by ad throttling. Targets carry no
    paid/organic split, so the paid share of the deficit is estimated from the
    actual paid share of sessions.
    """
    sql = f"""
    WITH actual AS (
      SELECT DATE(session_started_at) AS d,
             COUNT(*) AS sessions,
             COUNTIF(traffic_source IN {PAID_CHANNELS}) AS paid_sessions
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
    )
    SELECT SUM(a.sessions)      AS actual_sessions,
           SUM(a.paid_sessions) AS actual_paid_sessions,
           SUM(p.plan_sessions) AS plan_sessions
    FROM actual a JOIN plan p ON p.d = a.d
    """
    return dict(q(sql)[0].items())


def measure_beauty_deficit():
    """The headline number every component must reconcile against."""
    sql = f"""
    WITH actual AS (
      SELECT SUM(o.total_amount) AS revenue
      FROM {FQ}.orders o
      JOIN {FQ}.web_sessions s ON s.session_id = o.session_id
      WHERE s.primary_category_id = {BEAUTY_CATEGORY_ID}
        AND o.created_at >= TIMESTAMP '{WINDOW_START}'
        AND o.created_at <  TIMESTAMP '{CUTOFF}'
    ),
    plan AS (
      SELECT SUM(IF(d < DATE '{LAST_PARTIAL_DAY}' OR t.time_bucket < TIME '14:30:00',
                    t.target_revenue, 0)) AS plan_revenue
      FROM UNNEST(GENERATE_DATE_ARRAY(DATE '{WINDOW_START}',
                                      DATE '{LAST_PARTIAL_DAY}')) AS d
      JOIN {FQ}.category_15min_targets t
        ON t.day_of_week = EXTRACT(DAYOFWEEK FROM d)
      WHERE t.category_id = {BEAUTY_CATEGORY_ID}
    )
    SELECT plan.plan_revenue, actual.revenue,
           plan.plan_revenue - actual.revenue AS deficit
    FROM plan, actual
    """
    return dict(q(sql)[0].items())


# =========================================================================== #
# The certified allocation - single source of truth
# =========================================================================== #

def compute_allocation():
    """The certified three-way split of the Beauty deficit.

    This is imported by scripts/test/measure_cmo_ground_truth.py so that the
    drift gate and this diagnostic report can never disagree. Do not duplicate
    this arithmetic anywhere else.

    Conventions, deliberately different per component and certified as such in
    the business glossary:
      * stockout    uses the PAID conversion rate - that demand was bought
                    through acquisition campaigns, and it is the conservative
                    (lower) of the two rates.
      * recommender uses the ALL-CHANNEL rate - a shopper who reaches a
                    recommendation widget is already on site, whatever brought
                    them.
      * throttling  is the RESIDUAL - the traffic collapse overlaps the on-site
                    frictions that triggered it, so measuring all three
                    independently would double count.
    """
    cvr = measure_cvr_and_aov()
    aov = measure_aov()
    deficit = float(measure_beauty_deficit()["deficit"])

    gross = sum(float(r["gross_pot_val"] or 0)
                for r in measure_stockout_component()
                if r["category_id"] == BEAUTY_CATEGORY_ID)

    rec_rows = measure_recommender_component()
    rec = next(r for r in rec_rows if r["category_id"] == BEAUTY_CATEGORY_ID)
    bounced = int(rec["mismatched_bounced"])

    paid_rate = cvr["beauty_blackweek"]["paid_cvr_pct"] / 100.0
    all_rate = cvr["beauty_blackweek"]["cvr_pct"] / 100.0
    beauty_aov = float(aov["beauty"]["aov"])

    stockout = gross * paid_rate
    recommender = bounced * all_rate * beauty_aov
    throttling = deficit - stockout - recommender

    return {
        "deficit": deficit,
        "gross_pot_val": gross,
        "paid_cvr_pct": cvr["beauty_blackweek"]["paid_cvr_pct"],
        "allchannel_cvr_pct": cvr["beauty_blackweek"]["cvr_pct"],
        "aov": beauty_aov,
        "bounced_impressions": bounced,
        "stockout": stockout,
        "recommender": recommender,
        "throttling": throttling,
        "stockout_pct": 100.0 * stockout / deficit,
        "recommender_pct": 100.0 * recommender / deficit,
        "throttling_pct": 100.0 * throttling / deficit,
        "overstatement_factor": gross / stockout,
    }


# =========================================================================== #
# Report
# =========================================================================== #

def main():
    section("0. DIAGNOSTICS - recommender user_action values")
    rows = diag_recommender_actions()
    print(f"   {'user_action':<22}{'mismatch':>10}{'rows':>12}")
    for r in rows:
        print(f"   {str(r['user_action']):<22}{r['cat_mismatch_flg']:>10}{r['n']:>12,}")

    section("1. THE TRUE STOCKOUT WINDOW (from the click stream)")
    for r in diag_oos_window():
        print(f"   SKU {r['art_code']}  cat {r['category_id']}  {str(r['product_name'])[:34]:<34}")
        print(f"      {r['first_click']}  ->  {r['last_click']}"
              f"   clicks {r['clicks']:>7,}   gross {money(r['gross_pot_val'])}")

    section("2. CONVERSION PROPENSITY - which CVR convention is which")
    cvr = measure_cvr_and_aov()
    print(f"   {'scope':<24}{'sessions':>12}{'paid sess':>12}{'CVR':>10}{'paid CVR':>11}")
    for k in ("beauty_blackweek", "beauty_oos_window",
              "sitewide_blackweek", "sitewide_oos_window"):
        d = cvr[k]
        print(f"   {k:<24}{d['sessions']:>12,}{d['paid_sessions']:>12,}"
              f"{pct(d['cvr_pct']):>10}{pct(d['paid_cvr_pct']):>11}")

    aov = measure_aov()
    print()
    for k, d in aov.items():
        print(f"   AOV {k:<12} orders {d['orders']:>9,}   revenue {money(d['revenue'])}"
              f"   AOV EUR {float(d['aov']):>8,.2f}")

    section("3. THE BEAUTY DEFICIT - what everything must reconcile to")
    def_ = measure_beauty_deficit()
    print(f"   plan to date     {money(def_['plan_revenue'])}")
    print(f"   actual to date   {money(def_['revenue'])}")
    print(f"   DEFICIT          {money(def_['deficit'])}")
    deficit = float(def_["deficit"])

    section("4. COMPONENT A - stockout")
    oos_rows = measure_stockout_component()
    print(f"   {'cat':<5}{'category':<16}{'clicks':>10}{'gross pot_val':>20}")
    gross_total = 0.0
    gross_beauty = 0.0
    for r in oos_rows:
        g = float(r["gross_pot_val"] or 0)
        gross_total += g
        if r["category_id"] == BEAUTY_CATEGORY_ID:
            gross_beauty = g
        print(f"   {r['category_id']:<5}{str(r['category_name'])[:15]:<16}"
              f"{r['clicks']:>10,}{g:>20,.2f}")
    print(f"\n   gross attempted demand, all categories : {gross_total:>16,.2f}")
    print(f"   gross attempted demand, Beauty only    : {gross_beauty:>16,.2f}")

    print("\n   Applying each conversion convention to the BEAUTY gross value:")
    candidates = {}
    for label, rate in (
        ("beauty paid CVR, black week", cvr["beauty_blackweek"]["paid_cvr_pct"]),
        ("beauty paid CVR, oos window", cvr["beauty_oos_window"]["paid_cvr_pct"]),
        ("beauty all-session CVR, bw", cvr["beauty_blackweek"]["cvr_pct"]),
        ("sitewide paid CVR, bw", cvr["sitewide_blackweek"]["paid_cvr_pct"]),
        ("sitewide all-session CVR, bw", cvr["sitewide_blackweek"]["cvr_pct"]),
    ):
        if rate is None:
            continue
        loss = gross_beauty * rate / 100.0
        candidates[label] = loss
        print(f"      {label:<30} {pct(rate)}  ->  {money(loss)}"
              f"   = {100.0 * loss / deficit:>6.2f}% of deficit")

    section("5. COMPONENT B - recommender mismatch")
    rec_rows = measure_recommender_component()
    print(f"   {'cat':<5}{'impressions':>14}{'mismatched':>14}{'ignored':>12}{'bounced':>12}")
    rec_beauty = None
    for r in rec_rows:
        print(f"   {r['category_id']:<5}{r['impressions']:>14,}{r['mismatched']:>14,}"
              f"{r['mismatched_ignored']:>12,}{r['mismatched_bounced']:>12,}")
        if r["category_id"] == BEAUTY_CATEGORY_ID:
            rec_beauty = r

    if rec_beauty:
        beauty_aov = float(aov["beauty"]["aov"])
        paid_rate = cvr["beauty_blackweek"]["paid_cvr_pct"] / 100.0
        all_rate = cvr["beauty_blackweek"]["cvr_pct"] / 100.0
        print("\n   Derived opportunity cost (opp_cost_eur is always zero, so this"
              "\n   must come from bounced impressions x propensity x order value):")
        for basis_label, n in (("all mismatched", rec_beauty["mismatched"]),
                               ("mismatched+ignored", rec_beauty["mismatched_ignored"]),
                               ("mismatched+bounced", rec_beauty["mismatched_bounced"])):
            for rate_label, rate in (("paid CVR", paid_rate), ("all CVR", all_rate)):
                loss = n * rate * beauty_aov
                print(f"      {basis_label:<20} x {rate_label:<9} x AOV {beauty_aov:>6,.2f}"
                      f"  ->  {money(loss)}   = {100.0 * loss / deficit:>6.2f}%")

    section("6. COMPONENT C - ad throttling / traffic collapse")
    sd = measure_session_deficit()
    actual_s = float(sd["actual_sessions"])
    actual_paid = float(sd["actual_paid_sessions"])
    plan_s = float(sd["plan_sessions"])
    gap = plan_s - actual_s
    paid_share = actual_paid / actual_s if actual_s else 0.0
    print(f"   actual sessions      {actual_s:>14,.0f}")
    print(f"   plan sessions        {plan_s:>14,.0f}")
    print(f"   session deficit      {gap:>14,.0f}   ({-100.0 * gap / plan_s:.2f}%)")
    print(f"   paid share of actual {100.0 * paid_share:>13.2f}%")
    beauty_aov = float(aov["beauty"]["aov"])
    for rate_label, rate in (("beauty paid CVR", cvr["beauty_blackweek"]["paid_cvr_pct"]),
                             ("beauty all CVR", cvr["beauty_blackweek"]["cvr_pct"])):
        loss = gap * (rate / 100.0) * beauty_aov
        print(f"      full gap  x {rate_label:<16} x AOV  ->  {money(loss)}"
              f"   = {100.0 * loss / deficit:>6.2f}%")
        loss_paid = gap * paid_share * (rate / 100.0) * beauty_aov
        print(f"      paid gap  x {rate_label:<16} x AOV  ->  {money(loss_paid)}"
              f"   = {100.0 * loss_paid / deficit:>6.2f}%")

    section("7. RECONCILIATION against the published allocation")
    print(f"   published: stockout {PUBLISHED['stockout']:>12,.0f}"
          f"   recommender {PUBLISHED['recommender']:>10,.0f}"
          f"   ads {PUBLISHED['ad_throttling']:>12,.0f}")
    print(f"   published sum {sum(PUBLISHED.values()):>14,.0f}   vs deficit {deficit:>14,.2f}")
    print("\n   NOTE: independently measured components are NOT disjoint - the")
    print("   stockout-driven sessions sit inside the session deficit - so a raw")
    print("   sum will overshoot. See the report for how we reconcile.")

    section("8. THE CERTIFIED ALLOCATION (what the glossary and graders use)")
    a = compute_allocation()
    print(f"   stockout      {money(a['stockout'])}   {a['stockout_pct']:>6.2f}%"
          f"   = {a['gross_pot_val']:,.2f} x paid CVR {a['paid_cvr_pct']:.3f}%")
    print(f"   recommender   {money(a['recommender'])}   {a['recommender_pct']:>6.2f}%"
          f"   = {a['bounced_impressions']:,} x all-channel CVR "
          f"{a['allchannel_cvr_pct']:.3f}% x AOV {a['aov']:,.2f}")
    print(f"   ad throttling {money(a['throttling'])}   {a['throttling_pct']:>6.2f}%"
          f"   = residual")
    total = a["stockout"] + a["recommender"] + a["throttling"]
    print(f"   {'-' * 60}")
    print(f"   TOTAL         {money(total)}   vs deficit {money(a['deficit'])}")
    print(f"\n   overstatement factor of the naive SUM(pot_val): "
          f"{a['overstatement_factor']:.1f}x")


if __name__ == "__main__":
    main()
