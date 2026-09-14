#!/usr/bin/env python3
"""
Phase 2: Causal E-Commerce Simulation for LumièreShop Black Week 2026.
=======================================================================

Calendar
--------
  Plan window     : Monday Nov 23 2026 00:00 UTC -> Monday Nov 30 2026 23:59 UTC (8 days)
  Simulation clock: Friday Nov 27 2026 14:30 UTC (Black Friday, early afternoon)
  Actuals         : strictly bounded to [Nov 23 00:00, Nov 27 14:30)

Design philosophy
-----------------
Revenue is an OUTPUT of this simulation, not an input. Earlier versions of this
generator looped until a category hit a hardcoded revenue figure, wrote the
stockout loss as a constant (`pot_val = 55.00` on 1,181 rows), and wrote the
root cause as an English sentence inside `ad_bidding_log.trigger_details`. That
made the headline numbers unfalsifiable and let any agent read the conclusion
straight out of a text column.

Here the causal chain runs forward:

    ad spend --> clicks (spend / CPC) --> paid sessions -----+
                                                             |
    organic / direct / email / affiliate sessions -----------+--> sessions
                                                                     |
    stockout penalty  ---.                                           v
    recommender penalty --+--> conversion rate  --------------> orders
                                     |                               |
                                     |                               v
                                     |                        basket sampling
                                     |                               |
                                     v                               v
                          bidding engine observes CVR          REVENUE (emergent)
                                     |
                                     v
                          budget multiplier --> ad spend  (closes the loop)

What is CALIBRATED (chosen by us, from domain knowledge):
  - daily and intraday demand curves
  - channel mix per category
  - relative conversion rates between channels
  - product price pools
  - planned ad budgets, base CPC, creative-fatigue schedule
  - the bidding engine's decision rule and thresholds
  - one scalar CVR multiplier per category, fitted so that order volume lands
    near plan (a model fit; the SHAPE of the data is entirely causal)

What EMERGES (computed, never asserted):
  - revenue, per category, per day, per channel
  - the Beauty revenue gap and each of its three components
  - the stockout loss (from abandoned sessions and real product prices)
  - the recommender loss (from bounced fallback impressions)
  - the ad-throttling loss (from clicks the throttled budget never bought)

Consistency note
----------------
The previous narrative asserted "-31% spend, CPC +22%" together with "-39%
clicks". Those three cannot hold simultaneously, since clicks = spend / CPC and
0.69 / 1.22 = 0.57 (i.e. -43% clicks). This simulation uses the internally
consistent set: spend -31%, CPC +14%, clicks -39%.

Usage
-----
  python3 scripts/02_generate_data.py --calibrate   # fast KPI check, no writes
  python3 scripts/02_generate_data.py --skip-load   # generate but do not upload
  python3 scripts/02_generate_data.py               # full run + BigQuery load
"""

import argparse
import gzip
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np
from google.cloud import bigquery
from google.oauth2 import credentials as oauth2_credentials

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The bootstrap runs these scripts as subprocesses, so do not rely on the
# working directory putting scripts/ on the path - add it explicitly.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
from order_status import derive_order_status, status_distribution
from clickstream import (EVENT_FUNNEL, EVENT_GAP_SECONDS,
                         EVENTS_PER_CONVERTING_SESSION, EVENTS_PER_SESSION_RANGE,
                         NON_PAGEVIEW_EVENTS, browser_for, device_os_for,
                         event_at_step, is_page_view)


def load_dotenv():
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip("'\""))


load_dotenv()

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
DATASET_ID = os.environ.get("BQ_DATASET_ID", "ecommerce_dw")

# ---------------------------------------------------------------------------
# 1. CALENDAR
# ---------------------------------------------------------------------------

SIMULATION_START = datetime(2026, 11, 23, 0, 0, 0)   # Monday
CURRENT_TIME = datetime(2026, 11, 27, 14, 30, 0)     # Black Friday 14:30 (the clock)
PLAN_END = datetime(2026, 12, 1, 0, 0, 0)            # exclusive end of the 8-day plan

# Share of Black Week volume falling on each of the 8 planned days.
# Thursday builds, Friday (Black Friday) is the peak, the weekend tails off and
# Cyber Monday lifts again.
DAY_WEIGHTS = [0.10, 0.11, 0.12, 0.18, 0.24, 0.08, 0.07, 0.10]

STOCKOUT_DAYS = {0, 1, 2}      # Mon, Tue, Wed - SKUs 1001-1003 unavailable
STOCKOUT_SKUS = [1001, 1002, 1003]

# ---------------------------------------------------------------------------
# 2. PUBLISHED TARGETS (target-to-date, i.e. as at the Friday 14:30 clock)
# ---------------------------------------------------------------------------
# These are the figures quoted in CASE_STUDY_SOLUTION.md. The full 8-day plan
# stored in BigQuery is derived by dividing by the observed window fraction, so
# that a correctly paced "target to date" reproduces exactly these numbers.
# An agent that naively compares a 4.6-day actual against the full 8-day target
# will overstate the gap - which is the intended lesson.

TARGET_TO_DATE = {
    1: {"revenue": 1_950_000.0, "aov": 61.0, "paid_sessions": 512_000,
        "organic_sessions": 187_000, "paid_cvr": 0.029, "ad_spend": 205_000.0},
    2: {"revenue": 1_670_000.0, "aov": 180.0, "paid_sessions": 118_000,
        "organic_sessions": 74_000, "paid_cvr": 0.024, "ad_spend": 120_000.0},
    3: {"revenue": 1_450_000.0, "aov": 85.0, "paid_sessions": 195_000,
        "organic_sessions": 148_000, "paid_cvr": 0.030, "ad_spend": 110_000.0},
    4: {"revenue": 1_580_000.0, "aov": 110.0, "paid_sessions": 168_000,
        "organic_sessions": 132_000, "paid_cvr": 0.029, "ad_spend": 115_000.0},
}

# Order volume we are fitting the per-category CVR scalar towards. Derived from
# the published revenue and AOV KPIs; revenue itself is never written directly.
ACTUAL_AOV_GOAL = {1: 58.0, 2: 176.0, 3: 83.0, 4: 107.0}
ACTUAL_REVENUE_GOAL = {1: 1_420_000.0, 2: 1_570_000.0, 3: 1_406_500.0, 4: 1_516_800.0}

# ---------------------------------------------------------------------------
# 3. CATEGORY AND CHANNEL STRUCTURE
# ---------------------------------------------------------------------------

CATEGORY_NAMES = {1: "Beauty", 2: "Electronics", 3: "Fashion", 4: "Home"}

# Price pools are tuned so that the emergent AOV lands near ACTUAL_AOV_GOAL.
# average units per order = 1.65 items x 1.15 qty = 1.8975
PRICE_POOLS = {
    1: [12.90, 16.90, 19.90, 24.90, 29.90, 34.90, 39.90, 45.90, 49.90],
    2: [18.90, 32.90, 46.90, 64.90, 82.90, 99.90, 119.90, 149.90, 159.90],
    3: [15.90, 20.90, 30.90, 41.90, 46.90, 51.90, 62.90, 67.90, 72.90],
    4: [16.90, 23.90, 32.90, 42.90, 51.90, 61.90, 74.90, 84.90, 89.90],
}

COST_RATIO = {1: 0.30, 2: 0.52, 3: 0.36, 4: 0.34}

PAID_CHANNELS = ("Paid Search", "Paid Social")
NONPAID_CHANNELS = ("Organic Search", "Direct", "Email", "Affiliate")
ALL_CHANNELS = PAID_CHANNELS + NONPAID_CHANNELS

# Split of a category's paid clicks across the two paid surfaces.
PAID_SPLIT = {1: {"Paid Social": 0.60, "Paid Search": 0.40},
              2: {"Paid Social": 0.25, "Paid Search": 0.75},
              3: {"Paid Social": 0.55, "Paid Search": 0.45},
              4: {"Paid Social": 0.35, "Paid Search": 0.65}}

# Non-paid session volumes to date, per category. Beauty's organic figure is a
# published KPI (198,000) and is fixed. The other categories are calibrated so
# that the SITEWIDE conversion rate lands inside the 2.8%-3.2% band mandated by
# TECHNICAL_SPECIFICATION.md section 3.2 - orders are pinned by the published
# revenue and AOV targets, so sessions are the only free variable.
#
# The resulting mix (paid ~30% of sessions) is also more realistic for an
# established retailer than a paid-heavy split.
NONPAID_SESSIONS = {
    1: {"Organic Search": 198_000, "Direct": 52_000, "Email": 45_000, "Affiliate": 30_000},
    2: {"Organic Search": 148_000, "Direct": 74_000, "Email": 20_000, "Affiliate": 22_000},
    3: {"Organic Search": 248_000, "Direct": 95_000, "Email": 37_000, "Affiliate": 38_000},
    4: {"Organic Search": 218_000, "Direct": 88_000, "Email": 34_000, "Affiliate": 32_000},
}

# Conversion rate of each channel relative to that category's paid traffic.
# Cold paid traffic converts worst; direct and email (returning customers and
# the VIP early-access list) convert several times better.
CHANNEL_CVR_MULT = {
    "Paid Search": 1.00, "Paid Social": 1.00,
    "Organic Search": 1.25, "Direct": 2.05, "Email": 2.55, "Affiliate": 1.45,
}

# Categories whose PAID conversion rate is a published KPI and therefore may
# not be moved by the order-volume fitter. Only Beauty qualifies (3.1% actual
# vs 2.9% target, quoted in CASE_STUDY_SOLUTION.md).
PINNED_PAID_CVR_CATEGORIES = {1}

# Paid campaigns push hero products, so paid baskets run slightly larger.
CHANNEL_BASKET_MULT = {
    "Paid Search": 1.07, "Paid Social": 1.07,
    "Organic Search": 0.98, "Direct": 1.00, "Email": 1.02, "Affiliate": 0.95,
}

UTM_BY_CHANNEL = {
    "Paid Search": ("google", "cpc", "black_friday_search"),
    "Paid Social": ("meta", "cpc", "black_friday_beauty"),
    "Organic Search": ("organic", "none", None),
    "Direct": ("direct", "none", None),
    "Email": ("newsletter", "email", "bf_vip_early_access"),
    "Affiliate": ("criteo", "affiliate", "retargeting_deals"),
}

# ---------------------------------------------------------------------------
# 4. ADVERTISING AND THE BIDDING ENGINE
# ---------------------------------------------------------------------------

CAMPAIGNS = {
    1: {"campaign_id": 1001, "name": "Beauty_BlackFriday_PaidSocial",
        "platform": "Meta Ads", "bidding_strategy": "Strict Target ROAS"},
    2: {"campaign_id": 1002, "name": "Electronics_BlackFriday_Search",
        "platform": "Google Ads", "bidding_strategy": "Maximize Conversions"},
    3: {"campaign_id": 1003, "name": "Fashion_Winter_Retargeting",
        "platform": "Criteo", "bidding_strategy": "Target CPA"},
    4: {"campaign_id": 1004, "name": "Home_Deals_Newsletter",
        "platform": "Klaviyo", "bidding_strategy": "Direct CRM"},
}

# Daily fraction of the planned budget the bidding engine actually released.
# Only Beauty (campaign 1001) is on a strict target-ROAS strategy, so only
# Beauty throttles. Monday is a blend: the engine ran unconstrained until its
# 11:30 evaluation, then clamped down for the rest of the day.
BUDGET_MULTIPLIER = {
    1: [0.78, 0.62, 0.62, 0.68, 0.78, 1.00, 1.00, 1.00],
    2: [1.00, 1.00, 0.98, 1.00, 1.00, 1.00, 1.00, 1.00],
    3: [1.00, 0.99, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00],
    4: [1.00, 1.00, 1.00, 0.99, 1.00, 1.00, 1.00, 1.00],
}

# Creative fatigue lifts cost-per-click. Beauty's top 5 creatives were flagged
# learning-limited on Nov 22, so its CPC drifts up across the week.
CPC_FATIGUE = {
    1: [1.08, 1.12, 1.15, 1.16, 1.17, 1.17, 1.17, 1.17],
    2: [1.00, 1.00, 1.01, 1.01, 1.02, 1.02, 1.02, 1.02],
    3: [1.01, 1.01, 1.02, 1.02, 1.02, 1.02, 1.02, 1.02],
    4: [1.00, 1.01, 1.00, 1.01, 1.01, 1.01, 1.01, 1.01],
}

# The bidding engine trips when realised return on ad spend falls below this
# fraction of the configured target. "Strict Target ROAS" means a tight
# tolerance band, which is precisely why this strategy was the wrong choice for
# a promotional week: a 6% shortfall is enough to cap the budget.
#
# NOTE: the trigger is ROAS, not conversion rate. Beauty's realised paid CVR
# (3.10%) is actually ABOVE its 2.9% plan, so a CVR-based rule would never
# fire. ROAS breaks because creative fatigue lifts CPC at the same time the
# stockout depresses CVR - cost per click up, revenue per click down.
ROAS_THROTTLE_THRESHOLD = 0.94

# ---------------------------------------------------------------------------
# 5. INCIDENT MECHANICS
# ---------------------------------------------------------------------------

# Share of Beauty sessions that arrive intending to buy one of the three hero
# SKUs. They are the three best sellers, so this sits high - but still below
# their ~22% share of normal Beauty purchase volume.
HERO_INTENT_SHARE = 0.148
SUBSTITUTION_RATE = 0.42        # of blocked visitors who buy something else

# When a hero SKU page has no in-category substitute, the recommender falls
# back to a global rule and surfaces an unrelated department. This fires more
# widely than just the three dead SKUs, because the fallback rule is evaluated
# for every Beauty page whose primary recommendation set is empty.
FALLBACK_IMPRESSION_SHARE = 0.19    # of Beauty sessions during the stockout
FALLBACK_BOUNCE_RATE = 0.348        # of those impressions that end the session

# NOTE ON `pot_val`
# ----------------
# `oos_interactions.pot_val` holds GROSS unrealised demand: the retail value of
# the item the customer could not buy. It is deliberately NOT the net revenue
# loss. Converting gross demand into a loss requires knowing the substitution
# rate and the category conversion propensity - a certified methodology that
# lives in the business glossary, not in the column. An agent that simply sums
# the column will overstate the loss by more than an order of magnitude.

# Clickstream depth and the event funnel now live in scripts/clickstream.py,
# shared with the historical generator so the two periods cannot differ in
# shape. See that module for why that matters.

# Share of order LINES that are sent back. Two separate places read this: the
# `returned_at` stamp on order_items, and the derived `order_status` on orders.
# They must agree, otherwise an order could be labelled 'Returned' while none
# of its lines carries a return date. Keeping it as one constant makes that
# agreement structural rather than a convention someone has to remember.
ITEM_RETURN_RATE = 0.05

COUNTRIES = ["France", "Germany", "Netherlands", "Spain", "Italy",
             "Belgium", "Austria", "Sweden"]


# ---------------------------------------------------------------------------
# 6. TIME GRID
# ---------------------------------------------------------------------------

def build_intraday_weights():
    """Hourly share of a day's volume: a lunch bump and a larger evening peak."""
    weights = []
    for h in range(24):
        w = 0.15 + math.exp(-((h - 11.5) ** 2) / 12.0) + 1.2 * math.exp(-((h - 20.5) ** 2) / 10.0)
        weights.append(w)
    total = sum(weights)
    return [w / total for w in weights]


INTRADAY_WEIGHTS = build_intraday_weights()


def build_time_grid():
    """
    Enumerate every hour of the plan, tagging which fall before the clock.

    Returns (grid, observed_fraction) where grid is a list of dicts and
    observed_fraction is the share of total planned volume that lies inside the
    observed window. That fraction is what converts a published "target to
    date" into the full 8-day plan figure stored in BigQuery.
    """
    grid = []
    observed = 0.0
    total = 0.0
    cursor = SIMULATION_START
    while cursor < PLAN_END:
        day_idx = (cursor.date() - SIMULATION_START.date()).days
        weight = DAY_WEIGHTS[day_idx] * INTRADAY_WEIGHTS[cursor.hour]
        is_observed = cursor < CURRENT_TIME
        # The final partial hour (14:00-14:30 on Friday) counts by half.
        if is_observed and cursor + timedelta(hours=1) > CURRENT_TIME:
            fraction = (CURRENT_TIME - cursor).total_seconds() / 3600.0
            weight_observed = weight * fraction
        else:
            weight_observed = weight if is_observed else 0.0
        grid.append({
            "start": cursor,
            "day_idx": day_idx,
            "hour": cursor.hour,
            "weight": weight,
            "weight_observed": weight_observed,
            "observed": is_observed,
        })
        total += weight
        observed += weight_observed
        cursor += timedelta(hours=1)
    return grid, observed / total


# ---------------------------------------------------------------------------
# 7. THE AD ENGINE
# ---------------------------------------------------------------------------

def simulate_ad_engine(observed_fraction):
    """
    Run the paid-media loop day by day.

    Planned budget comes from the commercial plan. The bidding engine releases
    only a fraction of it (`budget_multiplier`), creative fatigue raises CPC,
    and clicks fall out as spend / CPC. Beauty's throttle is what ultimately
    starves the funnel.

    Returns (perf_rows, bidding_rows, paid_clicks_by_cat_day, planned_clicks).
    """
    perf_rows = []
    bidding_rows = []
    paid_clicks = defaultdict(dict)
    planned_clicks = defaultdict(dict)
    perf_id = 1
    log_id = 1

    for cat_id, target in TARGET_TO_DATE.items():
        # Scale the published to-date budget up to the full 8-day plan.
        full_week_spend = target["ad_spend"] / observed_fraction
        # Planned CPC is implied by the plan: budget buys the planned sessions.
        planned_cpc = target["ad_spend"] / target["paid_sessions"]

        for day_idx in range(8):
            planned_budget = full_week_spend * DAY_WEIGHTS[day_idx]
            budget_mult = BUDGET_MULTIPLIER[cat_id][day_idx]
            cpc = planned_cpc * CPC_FATIGUE[cat_id][day_idx]

            spend = planned_budget * budget_mult
            clicks = spend / cpc
            planned_clicks[cat_id][day_idx] = planned_budget / planned_cpc
            paid_clicks[cat_id][day_idx] = clicks

            day_date = (SIMULATION_START + timedelta(days=day_idx)).date()
            if day_date > CURRENT_TIME.date():
                continue  # the plan runs to Nov 30; actuals stop at the clock

            # Friday is only observed to 14:30, so scale that day's row down.
            if day_date == CURRENT_TIME.date():
                day_fraction = sum(
                    INTRADAY_WEIGHTS[h] for h in range(CURRENT_TIME.hour)
                ) + INTRADAY_WEIGHTS[CURRENT_TIME.hour] * 0.5
                spend *= day_fraction
                clicks *= day_fraction
                paid_clicks[cat_id][day_idx] = clicks
                planned_clicks[cat_id][day_idx] *= day_fraction

            impressions = clicks / random.uniform(0.019, 0.024)
            perf_rows.append({
                "performance_id": perf_id,
                "cid_ref": CAMPAIGNS[cat_id]["campaign_id"],
                "date": day_date.strftime("%Y-%m-%d"),
                "impressions": int(round(impressions)),
                "clicks": int(round(clicks)),
                "spend": float(round(spend, 2)),
                "conversions": 0,     # filled in once orders are known
                "average_cpc": float(round(cpc, 4)),
            })
            perf_id += 1

    return perf_rows, bidding_rows, paid_clicks, planned_clicks


def build_bidding_log(telemetry, spend_by_cat_day, target_roas_by_cat):
    """
    Emit the bidding engine's decision trail as numeric telemetry.

    Every field is derived from what the transactional tables actually contain,
    so the log can never contradict them. There is deliberately no prose
    explanation: an agent has to correlate `observed_cvr_7d`,
    `target_roas_multiplier` and `budget_multiplier` against the spend and
    session series to work out what happened.

    The engine evaluates a TRAILING window, which is what produces the lag in
    the recovery. Conditions normalise on Thursday, but Monday-Wednesday are
    still inside the trailing average, so the cap is released only gradually.
    """
    rows = []
    log_id = 1

    paid_rev = telemetry["paid_revenue"]
    paid_sess = telemetry["paid_sessions"]
    paid_ord = telemetry["paid_orders"]

    # Standing configuration events that predate the incident.
    rows.append({
        "log_id": log_id, "campaign_id": 1001, "status_change": "BIDDING_MIGRATION",
        "action_taken": "STRATEGY_SET_TARGET_ROAS", "observed_cvr_7d": 0.0312,
        "target_roas_multiplier": 1.02, "budget_multiplier": 1.00,
        "bid_adjustment_pct": 0.0, "logged_at": "2026-11-14T09:00:00Z",
    })
    log_id += 1
    rows.append({
        "log_id": log_id, "campaign_id": 1001, "status_change": "LEARNING_LIMITED",
        "action_taken": "CREATIVE_SET_FLAGGED", "observed_cvr_7d": 0.0305,
        "target_roas_multiplier": 0.98, "budget_multiplier": 1.00,
        "bid_adjustment_pct": 0.0, "logged_at": "2026-11-22T10:00:00Z",
    })
    log_id += 1

    for cat_id in sorted(TARGET_TO_DATE):
        campaign_id = CAMPAIGNS[cat_id]["campaign_id"]
        target_roas = target_roas_by_cat[cat_id]

        for day_idx in range(8):
            day = SIMULATION_START + timedelta(days=day_idx)
            if day > CURRENT_TIME:
                break

            # Trailing window: everything before today. On day 0 the engine has
            # no in-week history, so it evaluates the morning it is looking at.
            window = list(range(day_idx)) or [0]
            rev = sum(paid_rev.get((cat_id, d), 0.0) for d in window)
            spend = sum(spend_by_cat_day.get((cat_id, d), 0.0) for d in window)
            sess = sum(paid_sess.get((cat_id, d), 0) for d in window)
            ords = sum(paid_ord.get((cat_id, d), 0) for d in window)
            if spend <= 0 or sess <= 0:
                continue

            observed_roas = rev / spend
            observed_cvr = ords / sess
            ratio = observed_roas / target_roas if target_roas else 1.0
            budget_mult = BUDGET_MULTIPLIER[cat_id][day_idx]

            if ratio < ROAS_THROTTLE_THRESHOLD:
                status, action = "TARGET_ROAS_BREACH_THROTTLED", "BUDGET_CAP_APPLIED"
            elif budget_mult < 1.0:
                # Trailing window has recovered but the cap has not been lifted.
                status, action = "BUDGET_CONSTRAINED", "BUDGET_CAP_MAINTAINED"
            else:
                status, action = "BUDGET_NORMAL", "NO_CHANGE"

            rows.append({
                "log_id": log_id,
                "campaign_id": campaign_id,
                "status_change": status,
                "action_taken": action,
                "observed_cvr_7d": float(round(observed_cvr, 5)),
                "target_roas_multiplier": float(round(ratio, 4)),
                "budget_multiplier": float(round(budget_mult, 3)),
                "bid_adjustment_pct": float(round((budget_mult - 1.0) * 100, 2)),
                "logged_at": day.replace(hour=11, minute=30).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
            log_id += 1

    return rows


# ---------------------------------------------------------------------------
# 8. CONVERSION MODEL
# ---------------------------------------------------------------------------

def stockout_cvr_penalty(cat_id, day_idx):
    """
    Fraction of normal conversion retained while the hero SKUs are unavailable.

    Visitors who came for SKU 1001-1003 either substitute or leave. Only Beauty
    is affected, and only Mon-Wed.
    """
    if cat_id != 1 or day_idx not in STOCKOUT_DAYS:
        return 1.0
    lost = HERO_INTENT_SHARE * (1.0 - SUBSTITUTION_RATE)
    return 1.0 - lost


def recommender_cvr_penalty(cat_id, day_idx):
    """
    Additional conversion loss from the cross-category recommendation fallback.

    When a Beauty page has no in-category substitute to offer, the widget falls
    back to a global rule and surfaces an unrelated department. Those visitors
    bounce rather than convert.
    """
    if cat_id != 1 or day_idx not in STOCKOUT_DAYS:
        return 1.0
    return 1.0 - FALLBACK_IMPRESSION_SHARE * FALLBACK_BOUNCE_RATE


def solve_cvr_scalars(effective_sessions, target_orders_by_cat, base_paid_cvr):
    """
    Fit one scalar per category so that total orders land on plan.

    `effective_sessions[cat][channel]` must already be weighted by the incident
    penalties in force on each day, otherwise the stockout and recommender
    losses would push realised orders below the fitted target.

    Beauty's paid conversion rate is a published KPI (3.1%), so for Beauty the
    scalar is applied only to non-paid channels and paid traffic is pinned. No
    such constraint exists for the other categories, and pinning them too would
    force their organic traffic to convert WORSE than their cold paid traffic -
    the opposite of how retail actually behaves. So elsewhere the scalar moves
    every channel together and the relative ordering is preserved.
    """
    scalars = {}
    for cat_id, target_orders in target_orders_by_cat.items():
        paid_cvr = base_paid_cvr[cat_id]
        pinned = cat_id in PINNED_PAID_CVR_CATEGORIES
        fixed_orders = 0.0
        scalable_unit = 0.0
        for channel, n_sessions in effective_sessions[cat_id].items():
            weighted = n_sessions * paid_cvr * CHANNEL_CVR_MULT[channel]
            if pinned and channel in PAID_CHANNELS:
                fixed_orders += weighted
            else:
                scalable_unit += weighted
        if scalable_unit <= 0:
            scalars[cat_id] = 1.0
            continue
        scalars[cat_id] = max(0.05, (target_orders - fixed_orders) / scalable_unit)
    return scalars


# ---------------------------------------------------------------------------
# 9. CATALOG
# ---------------------------------------------------------------------------

def build_catalog(rng):
    """Build categories and 600 products with category-appropriate price pools."""
    categories = [
        {"category_id": 1, "parent_category_id": None, "name": "Beauty", "slug": "beauty"},
        {"category_id": 2, "parent_category_id": None, "name": "Electronics", "slug": "electronics"},
        {"category_id": 3, "parent_category_id": None, "name": "Fashion", "slug": "fashion"},
        {"category_id": 4, "parent_category_id": None, "name": "Home", "slug": "home"},
    ]

    products = []
    # The three hero SKUs that go out of stock, plus the next two best sellers.
    hero = [
        (1001, "Lumière Advanced Night Repair Serum", "Lumière Beauty", 39.90),
        (1002, "Éclat Radiance Mist", "Lumière Beauty", 29.90),
        (1003, "Aura Glow Cream", "Lumière Beauty", 34.90),
        (1004, "Velvet Hydrating Cleanser", "Lumière Beauty", 24.90),
        (1005, "Satin Lip Elixir", "Lumière Beauty", 19.90),
    ]
    for pid, name, brand, price in hero:
        products.append({
            "product_id": pid, "category_id": 1, "name": name, "sku": f"SKU-{pid}",
            "brand": brand, "retail_price": price,
            "cost": float(round(price * COST_RATIO[1], 2)), "is_active": True,
        })

    naming = {
        1: (["Hydra", "Botanical", "Rosewater", "Silky", "Charcoal", "Brightening",
             "Nourishing", "Gentle", "Mineral", "Peptide", "Collagen", "Radiant",
             "Matte", "Volumizing", "Illuminating", "Scalp", "Revitalizing", "Pure",
             "Luminous", "Organic"],
            ["Serum", "Mist", "Cream", "Cleanser", "Elixir", "Toner", "Mask", "Scrub",
             "Lotion", "Concentrate", "Powder", "Lipstick", "Mascara", "Highlighter",
             "Shampoo", "Conditioner", "Balm", "Essence", "Peel", "Fluid"],
            ["Lumière Beauty", "Éclat Botanical", "Aura Labs", "Maison Botanique", "PureSkin Paris"]),
        2: (["Wireless", "Noise-Cancelling", "Smart", "Ultra-HD", "Ergonomic", "RGB",
             "Portable", "Multiport", "MagSafe", "Hi-Fi", "Pro-Grade", "Compact",
             "Digital", "High-Speed", "Bluetooth", "Optical", "Fast-Charge", "Gaming",
             "Studio", "Voice-Enabled"],
            ["Headphones", "Earbuds", "Speaker", "Watch", "Mouse", "Keyboard", "Webcam",
             "Docking Station", "Power Bank", "Security Camera", "Charger", "Router",
             "Gaming Headset", "Desk Lamp", "Tablet", "Drone", "Mic", "SSD Drive",
             "Smart Scale", "Purifier"],
            ["SoundPro", "FitTech", "NovaTech", "AeroGadgets", "CyberPulse", "VividAudio"]),
        3: (["Cashmere", "Wool", "Linen", "Denim", "Organic Cotton", "Leather", "Silk",
             "Merino", "Structured", "Trench", "Suede", "Pleated", "Vintage", "Oversized",
             "Crossbody", "Performance", "Fleece", "Quilted", "Monogram", "Classic"],
            ["Sweater", "Overcoat", "Blazer", "Jeans", "T-Shirt", "Boots", "Blouse",
             "Scarf", "Tote Bag", "Coat", "Sneakers", "Skirt", "Belt", "Trousers",
             "Jacket", "Cardigan", "Shorts", "Hoodie", "Hat", "Loafers"],
            ["LuxeStyle", "Atelier Paris", "Urban Thread", "Nordic Wear", "Maison Couture"]),
        4: (["Aroma", "Egyptian Cotton", "Ceramic", "Minimalist", "Weighted", "Cast Iron",
             "Ergonomic", "Velvet", "Soy Wax", "Bamboo", "Espresso", "Stainless Steel",
             "Jute", "Air Fryer", "Non-Stick", "Porcelain", "Standing", "Decorative",
             "Memory Foam", "Teak"],
            ["Diffuser", "Sheet Set", "Vase", "Table Lamp", "Blanket", "Dutch Oven",
             "Office Chair", "Pillow Set", "Candle", "Towel Set", "Coffee Maker",
             "Cutlery Set", "Area Rug", "Digital Oven", "Cookware Set", "Dinnerware",
             "Floor Mirror", "Wall Clock", "Humidifier", "Cutting Board"],
            ["Maison Living", "Nordic Nest", "Artisan Home", "EcoComfort", "Studio Casa"]),
    }
    id_ranges = {1: range(1006, 1151), 2: range(2001, 2151),
                 3: range(3001, 3151), 4: range(4001, 4151)}

    for cat_id, rng_ids in id_ranges.items():
        prefixes, types, brands = naming[cat_id]
        for i in rng_ids:
            price = float(rng.choice(PRICE_POOLS[cat_id]))
            products.append({
                "product_id": i, "category_id": cat_id,
                "name": f"{rng.choice(prefixes)} {rng.choice(types)} {i % 20 + 1}",
                "sku": f"SKU-{i}", "brand": rng.choice(brands),
                "retail_price": price,
                "cost": float(round(price * COST_RATIO[cat_id], 2)),
                "is_active": True,
            })

    return categories, products


def build_purchase_weights(products):
    """
    Zipf-style popularity: a handful of hero SKUs carry most of the volume.

    Returns per-category (product_id array, price array, probability array).
    """
    by_cat = {}
    for cat_id in CATEGORY_NAMES:
        items = [p for p in products if p["category_id"] == cat_id]
        n = len(items)
        weights = 1.0 / (np.arange(1, n + 1) ** 0.85)
        weights /= weights.sum()
        by_cat[cat_id] = (
            np.array([p["product_id"] for p in items]),
            np.array([float(p["retail_price"]) for p in items]),
            weights,
        )
    return by_cat


# ---------------------------------------------------------------------------
# 10. MAIN SIMULATION
# ---------------------------------------------------------------------------

def run_simulation(calibrate_only=False, seed=42):
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)

    grid, observed_fraction = build_time_grid()
    print(f"Observed window fraction (Mon 00:00 -> Fri 14:30): {observed_fraction:.4f}")

    categories, products = build_catalog(rng)
    cat_pick = build_purchase_weights(products)
    price_by_id = {p["product_id"]: float(p["retail_price"]) for p in products}

    # --- Paid traffic emerges from the ad engine -------------------------
    perf_rows, _, paid_clicks, planned_clicks = simulate_ad_engine(observed_fraction)

    paid_sessions_total = {
        cat: sum(v for d, v in days.items() if d <= 4)
        for cat, days in paid_clicks.items()
    }
    planned_sessions_total = {
        cat: sum(v for d, v in days.items() if d <= 4)
        for cat, days in planned_clicks.items()
    }

    # --- Assemble total sessions per category and channel ----------------
    sessions_by_cat_channel = {}
    for cat_id in CATEGORY_NAMES:
        channels = {}
        for channel, share in PAID_SPLIT[cat_id].items():
            channels[channel] = paid_sessions_total[cat_id] * share
        for channel, count in NONPAID_SESSIONS[cat_id].items():
            channels[channel] = float(count)
        sessions_by_cat_channel[cat_id] = channels

    # --- Fit the conversion scalars --------------------------------------
    # Share of observed volume falling on each day, needed to weight the
    # incident penalties correctly.
    observed_hours = [g for g in grid if g["observed"]]
    obs_weight_total = sum(g["weight_observed"] for g in observed_hours)
    day_share = defaultdict(float)
    for g in observed_hours:
        day_share[g["day_idx"]] += g["weight_observed"] / obs_weight_total

    def penalty_weighted_share(cat_id):
        """Average conversion multiplier across the observed window."""
        return sum(
            share * stockout_cvr_penalty(cat_id, day) * recommender_cvr_penalty(cat_id, day)
            for day, share in day_share.items()
        )

    effective_sessions = {}
    for cat_id in CATEGORY_NAMES:
        factor = penalty_weighted_share(cat_id)
        effective_sessions[cat_id] = {
            channel: n * factor
            for channel, n in sessions_by_cat_channel[cat_id].items()
        }

    target_orders = {c: ACTUAL_REVENUE_GOAL[c] / ACTUAL_AOV_GOAL[c] for c in CATEGORY_NAMES}
    base_paid_cvr = {c: TARGET_TO_DATE[c]["paid_cvr"] for c in CATEGORY_NAMES}
    # Beauty's REALISED paid conversion rate is a published KPI (3.1%). The
    # incident penalties depress it, so the underlying base rate has to sit
    # above 3.1% for the realised figure to land on it.
    base_paid_cvr[1] = 0.031 / penalty_weighted_share(1)
    print(f"  Beauty base paid CVR (pre-incident): {base_paid_cvr[1]*100:.3f}%"
          f"  -> realised {0.031*100:.2f}%")

    cvr_scalars = solve_cvr_scalars(effective_sessions, target_orders, base_paid_cvr)
    for cat_id, scalar in sorted(cvr_scalars.items()):
        print(f"  CVR scalar {CATEGORY_NAMES[cat_id]:<12}: {scalar:.4f}")

    def cvr_for(cat_id, channel, day_idx):
        base = base_paid_cvr[cat_id] * CHANNEL_CVR_MULT[channel]
        pinned_paid = (cat_id in PINNED_PAID_CVR_CATEGORIES
                       and channel in PAID_CHANNELS)
        if not pinned_paid:
            base *= cvr_scalars[cat_id]
        return (base
                * stockout_cvr_penalty(cat_id, day_idx)
                * recommender_cvr_penalty(cat_id, day_idx))

    # --- Distribute sessions across the observed hours -------------------
    plan = []          # (hour_meta, cat_id, channel, n_sessions, cvr)
    for cat_id in CATEGORY_NAMES:
        for channel, total_sessions in sessions_by_cat_channel[cat_id].items():
            for g in observed_hours:
                share = g["weight_observed"] / obs_weight_total
                n = total_sessions * share
                if n <= 0:
                    continue
                plan.append((g, cat_id, channel, n, cvr_for(cat_id, channel, g["day_idx"])))

    # --- Calibration mode: aggregate arithmetic only ---------------------
    if calibrate_only:
        return summarise_calibration(
            plan, cat_pick, sessions_by_cat_channel,
            paid_sessions_total, planned_sessions_total,
            perf_rows, observed_fraction,
            {"day_share": day_share, "base_paid_cvr": base_paid_cvr,
             "cvr_scalars": cvr_scalars})

    # --- What the bidding engine believes "healthy" looks like ------------
    # The target ROAS configured on each campaign reflects the paid performance
    # the account delivered before the incident, NOT the raw commercial plan.
    # Deriving it any other way would make every campaign look breached.
    expected_paid_cvr = {}
    target_roas_by_cat = {}
    for cat_id in CATEGORY_NAMES:
        pinned = cat_id in PINNED_PAID_CVR_CATEGORIES
        expected_paid_cvr[cat_id] = (base_paid_cvr[cat_id]
                                     * (1.0 if pinned else cvr_scalars[cat_id]))
        t = TARGET_TO_DATE[cat_id]
        planned_cpc = t["ad_spend"] / t["paid_sessions"]
        paid_aov = expected_aov(cat_id, cat_pick, CHANNEL_BASKET_MULT["Paid Search"])
        target_roas_by_cat[cat_id] = expected_paid_cvr[cat_id] * paid_aov / planned_cpc

    return plan, {
        "grid": grid,
        "observed_fraction": observed_fraction,
        "categories": categories,
        "products": products,
        "cat_pick": cat_pick,
        "price_by_id": price_by_id,
        "perf_rows": perf_rows,
        "paid_sessions_total": paid_sessions_total,
        "planned_sessions_total": planned_sessions_total,
        "sessions_by_cat_channel": sessions_by_cat_channel,
        "cvr_scalars": cvr_scalars,
        "base_paid_cvr": base_paid_cvr,
        "expected_paid_cvr": expected_paid_cvr,
        "target_roas_by_cat": target_roas_by_cat,
    }


def expected_aov(cat_id, cat_pick, channel_mult=1.0):
    """Expected basket value for a category, given the popularity weighting."""
    _, prices, weights = cat_pick[cat_id]
    mean_price = float((prices * weights).sum())
    units_per_order = 1.65 * 1.15
    return mean_price * units_per_order * channel_mult


def summarise_calibration(plan, cat_pick, sessions_by_cat_channel,
                          paid_sessions_total, planned_sessions_total,
                          perf_rows, observed_fraction, ctx):
    """Fast KPI reconciliation without materialising sessions or events."""
    orders = defaultdict(float)
    revenue = defaultdict(float)
    sessions = defaultdict(float)
    paid_orders = defaultdict(float)

    for g, cat_id, channel, n, cvr in plan:
        o = n * cvr
        sessions[cat_id] += n
        orders[cat_id] += o
        revenue[cat_id] += o * expected_aov(cat_id, cat_pick, CHANNEL_BASKET_MULT[channel])
        if channel in ("Paid Search", "Paid Social"):
            paid_orders[cat_id] += o

    spend_by_cat = defaultdict(float)
    clicks_by_cat = defaultdict(float)
    for row in perf_rows:
        for cat_id, camp in CAMPAIGNS.items():
            if camp["campaign_id"] == row["cid_ref"]:
                spend_by_cat[cat_id] += row["spend"]
                clicks_by_cat[cat_id] += row["clicks"]

    print("\n" + "=" * 96)
    print("KPI RECONCILIATION  (actual = emergent from the simulation)")
    print("=" * 96)
    header = f"{'Category':<12}{'Sessions':>11}{'Orders':>9}{'AOV':>9}{'Revenue':>13}{'Target TD':>13}{'Gap':>12}{'Gap %':>8}"
    print(header)
    print("-" * 96)
    total_rev = 0.0
    for cat_id in sorted(CATEGORY_NAMES):
        target_td = TARGET_TO_DATE[cat_id]["revenue"]
        rev = revenue[cat_id]
        aov = rev / orders[cat_id] if orders[cat_id] else 0
        gap = rev - target_td
        total_rev += rev
        print(f"{CATEGORY_NAMES[cat_id]:<12}{sessions[cat_id]:>11,.0f}{orders[cat_id]:>9,.0f}"
              f"{aov:>9,.2f}{rev:>13,.0f}{target_td:>13,.0f}{gap:>12,.0f}{gap/target_td*100:>7.1f}%")
    print("-" * 96)
    print(f"{'TOTAL':<12}{sum(sessions.values()):>11,.0f}{sum(orders.values()):>9,.0f}"
          f"{'':>9}{total_rev:>13,.0f}")

    print("\n" + "=" * 96)
    print("BEAUTY DETAIL vs PUBLISHED KPIs")
    print("=" * 96)
    b_paid = sum(n for g, c, ch, n, _ in plan if c == 1 and ch in ("Paid Search", "Paid Social"))
    b_org = sum(n for g, c, ch, n, _ in plan if c == 1 and ch == "Organic Search")
    b_paid_cvr = paid_orders[1] / b_paid if b_paid else 0
    b_aov = revenue[1] / orders[1] if orders[1] else 0
    paid_rev = paid_orders[1] * expected_aov(1, cat_pick, CHANNEL_BASKET_MULT["Paid Social"])

    checks = [
        ("Revenue", revenue[1], 1_420_000, "EUR"),
        ("AOV", b_aov, 58.0, "EUR"),
        ("Paid sessions", b_paid, 310_000, ""),
        ("Organic sessions", b_org, 198_000, ""),
        ("Paid CVR", b_paid_cvr * 100, 3.1, "%"),
        ("Ad spend", spend_by_cat[1], 142_000, "EUR"),
        ("Paid clicks", clicks_by_cat[1], 310_000, ""),
        ("ROAS (paid)", paid_rev / spend_by_cat[1] if spend_by_cat[1] else 0, 4.1, "x"),
        ("Revenue gap", revenue[1] - 1_950_000, -530_000, "EUR"),
    ]
    print(f"{'Metric':<20}{'Simulated':>15}{'Published':>15}{'Delta':>12}{'Delta %':>10}")
    print("-" * 96)
    for name, actual, published, unit in checks:
        delta = actual - published
        pct = (delta / published * 100) if published else 0
        flag = "  OK" if abs(pct) <= 3 else ("  ~" if abs(pct) <= 8 else "  XX")
        print(f"{name:<20}{actual:>15,.2f}{published:>15,.2f}{delta:>12,.2f}{pct:>9.1f}%{flag}")

    print("\nPaid session change vs plan: "
          f"{(paid_sessions_total[1]/planned_sessions_total[1]-1)*100:.1f}% "
          f"(published -39%)")
    print(f"Spend change vs plan: "
          f"{(spend_by_cat[1]/(TARGET_TO_DATE[1]['ad_spend'])-1)*100:.1f}% (published -31%)")

    # ------------------------------------------------------------------
    # Emergent attribution of the Beauty gap.
    # Every component below is computed against a counterfactual funnel
    # (no budget throttle, no stockout, no recommender fallback). None of
    # these figures is stored anywhere in the warehouse.
    # ------------------------------------------------------------------
    day_share = ctx["day_share"]
    stockout_share = sum(s for d, s in day_share.items() if d in STOCKOUT_DAYS)
    beauty_sessions = sessions[1]
    beauty_aov = revenue[1] / orders[1] if orders[1] else 0.0
    paid_aov = expected_aov(1, cat_pick, CHANNEL_BASKET_MULT["Paid Social"])

    # Blended Beauty conversion rate with the incident penalties removed.
    unpenalised_orders = 0.0
    for g, cat_id, channel, n, cvr in plan:
        if cat_id != 1:
            continue
        pen = (stockout_cvr_penalty(1, g["day_idx"])
               * recommender_cvr_penalty(1, g["day_idx"]))
        unpenalised_orders += n * cvr / pen
    cf_cvr = unpenalised_orders / beauty_sessions if beauty_sessions else 0.0

    lost_clicks = planned_sessions_total[1] - paid_sessions_total[1]
    realised_paid_cvr = paid_orders[1] / b_paid if b_paid else 0.0
    affected = beauty_sessions * stockout_share

    throttle_loss = lost_clicks * realised_paid_cvr * paid_aov
    stockout_loss = (affected * HERO_INTENT_SHARE * (1 - SUBSTITUTION_RATE)
                     * cf_cvr * beauty_aov)
    reco_loss = (affected * FALLBACK_IMPRESSION_SHARE * FALLBACK_BOUNCE_RATE
                 * cf_cvr * beauty_aov)

    gap = TARGET_TO_DATE[1]["revenue"] - revenue[1]
    explained = throttle_loss + stockout_loss + reco_loss
    residual = gap - explained

    print("\n" + "=" * 96)
    print("EMERGENT ATTRIBUTION OF THE BEAUTY GAP  (nothing here is stored in the warehouse)")
    print("=" * 96)
    print(f"{'Component':<34}{'Simulated':>15}{'Published':>15}{'Share':>10}")
    print("-" * 96)
    for label, value, published in (
        ("Ad budget throttling", throttle_loss, 415_000),
        ("Hero SKU stockout", stockout_loss, 65_000),
        ("Recommender fallback", reco_loss, 50_000),
    ):
        print(f"{label:<34}{value:>15,.0f}{published:>15,.0f}{value/gap*100:>9.1f}%")
    print("-" * 96)
    print(f"{'Explained':<34}{explained:>15,.0f}{530_000:>15,.0f}{explained/gap*100:>9.1f}%")
    print(f"{'Unexplained residual':<34}{residual:>15,.0f}{'-':>15}{residual/gap*100:>9.1f}%")
    print(f"{'TOTAL GAP':<34}{gap:>15,.0f}{530_000:>15,.0f}{100.0:>9.1f}%")
    print("\nA small unexplained residual is intentional: real attribution never")
    print("closes to zero, and a gap that reconciles perfectly looks reverse-engineered.")
    return None


# ---------------------------------------------------------------------------
# 11. MATERIALISATION
# ---------------------------------------------------------------------------

# EVENT_FUNNEL and NON_PAGEVIEW_EVENTS are imported from scripts/clickstream.py
# at the top of this file. They are shared with 14_generate_historical_data.py
# so that the six weeks of history and the Black Week window have exactly the
# same clickstream shape - any difference would show up in the data as a step
# change on 23 November and read as a real signal.


def materialise(plan, ctx, seed=42):
    """
    Turn the aggregate plan into rows.

    Sessions and events stream to disk because there are millions of them.
    Orders are built only from sessions that actually converted, so
    `orders.session_id` always resolves and `web_sessions.converted_to_order`
    is true exactly for those sessions.
    """
    np_rng = np.random.default_rng(seed)

    cat_pick = ctx["cat_pick"]
    price_by_id = ctx["price_by_id"]
    inv_by_product = ctx["inv_by_product"]
    user_country_map = ctx.get("user_country", {})

    local_tmp = os.path.join(PROJECT_ROOT, ".tmp")
    os.makedirs(local_tmp, exist_ok=True)
    temp_dir = tempfile.mkdtemp(dir=local_tmp)
    # Gzipped NDJSON: ~45M events would otherwise be well over 10 GB on disk.
    # BigQuery load jobs accept gzipped newline-delimited JSON directly.
    sessions_path = os.path.join(temp_dir, "web_sessions.json.gz")
    events_path = os.path.join(temp_dir, "web_events.json.gz")

    orders, order_items, sales_events = [], [], []
    oos_interactions, recommender_logs = [], []
    session_seq = order_seq = item_seq = event_seq = 0
    oos_seq = rec_seq = total_events = 0

    # Telemetry the ad platform would have observed, accumulated as rows are
    # built. The bidding engine's decision log is derived from these, so the
    # log can never disagree with the transactional tables.
    sessions_by_cat_day = defaultdict(int)
    orders_by_cat_day = defaultdict(int)
    paid_sessions_by_cat_day = defaultdict(int)
    paid_orders_by_cat_day = defaultdict(int)
    paid_revenue_by_cat_day = defaultdict(float)
    revenue_by_cat_day = defaultdict(float)

    hero_prices = {pid: price_by_id[pid] for pid in STOCKOUT_SKUS}
    print(f"Materialising into {temp_dir} ...")

    with gzip.open(sessions_path, "wt", encoding="utf-8", compresslevel=4) as f_sess, \
         gzip.open(events_path, "wt", encoding="utf-8", compresslevel=4) as f_ev:

        for g, cat_id, channel, n_float, cvr in plan:
            n = int(round(n_float))
            if n <= 0:
                continue
            day_idx = g["day_idx"]
            hour_start = g["start"]
            span = int(min(3600, (CURRENT_TIME - hour_start).total_seconds()))
            if span <= 0:
                continue

            # The stockout acts at row level via hero intent, so divide it out
            # of the bucket rate to avoid applying the same penalty twice.
            stock_pen = stockout_cvr_penalty(cat_id, day_idx)
            cvr_non_hero = cvr / stock_pen if stock_pen else cvr

            in_stockout = cat_id == 1 and day_idx in STOCKOUT_DAYS
            offsets = np_rng.integers(0, span, n)
            hero_intent = (np_rng.random(n) < HERO_INTENT_SHARE
                           if in_stockout else np.zeros(n, dtype=bool))
            # Hero-intent visitors convert only if they accept a substitute.
            conv_prob = np.where(hero_intent, cvr_non_hero * SUBSTITUTION_RATE, cvr_non_hero)
            converts = np_rng.random(n) < conv_prob

            fallback_seen = (np_rng.random(n) < FALLBACK_IMPRESSION_SHARE
                             if in_stockout else np.zeros(n, dtype=bool))
            fallback_bounced = fallback_seen & (np_rng.random(n) < FALLBACK_BOUNCE_RATE)
            normal_rec = np_rng.random(n) < 0.02

            pids, prices, weights = cat_pick[cat_id]
            browse_pick = np_rng.choice(len(pids), size=n, p=weights)
            n_events_arr = np.where(
                converts,
                np_rng.integers(EVENTS_PER_CONVERTING_SESSION[0],
                                EVENTS_PER_CONVERTING_SESSION[1], n),
                np_rng.integers(EVENTS_PER_SESSION_RANGE[0],
                                EVENTS_PER_SESSION_RANGE[1], n))
            has_user = np_rng.random(n) < 0.75
            user_ids = np_rng.integers(1, 10001, n)
            os_roll = np_rng.random(n)
            utm_s, utm_m, utm_c = UTM_BY_CHANNEL[channel]

            n_conv = int(converts.sum())
            is_paid = channel in PAID_CHANNELS
            sessions_by_cat_day[(cat_id, day_idx)] += n
            orders_by_cat_day[(cat_id, day_idx)] += n_conv
            if is_paid:
                paid_sessions_by_cat_day[(cat_id, day_idx)] += n
                paid_orders_by_cat_day[(cat_id, day_idx)] += n_conv

            item_counts = basket_pick = basket_qty = returns_roll = None
            if n_conv:
                roll = np_rng.random(n_conv)
                item_counts = np.where(roll < 0.55, 1,
                                np.where(roll < 0.85, 2,
                                  np.where(roll < 0.95, 3, 4)))
                total_items = int(item_counts.sum())
                basket_pick = np_rng.choice(len(pids), size=total_items, p=weights)
                basket_qty = np.where(np_rng.random(total_items) < 0.85, 1, 2)
                returns_roll = np_rng.random(total_items)
            conv_cursor = item_cursor = 0
            basket_mult = CHANNEL_BASKET_MULT[channel]

            for i in range(n):
                session_seq += 1
                sid = f"SESS-{session_seq}"
                s_dt = hour_start + timedelta(seconds=int(offsets[i]))
                converted = bool(converts[i])

                dev_os = device_os_for(os_roll[i])
                browser = browser_for(dev_os)

                browse_pid = int(pids[browse_pick[i]])
                ev_time = s_dt
                n_ev = int(n_events_arr[i])
                # Counted, not estimated. The loop below can break early when it
                # reaches the data cutoff, so the number of events actually
                # emitted is frequently lower than n_ev. Deriving these two
                # fields from what was really written is what keeps
                # web_sessions and web_events agreeing with each other.
                last_ev_time = s_dt
                page_views = 0
                for step in range(n_ev):
                    ev_time += timedelta(seconds=int(np_rng.integers(*EVENT_GAP_SECONDS)))
                    stop_after_this = False
                    if ev_time >= CURRENT_TIME:
                        if step > 0:
                            break
                        # Step 0 is the landing page view. A session that
                        # exists at all was opened by one, so when the very
                        # first gap happens to straddle the cutoff the answer
                        # is to clamp that event inside the window - not to
                        # write a session row with no clickstream behind it
                        # and page_views_count = 0.
                        #
                        # The session must then END here. Falling through to
                        # step 1 would draw a SECOND gap before breaking, and
                        # one extra draw per affected session is enough to
                        # shift every subsequent value in the shared stream -
                        # measured at +12,154 events and +16,088 EUR of revenue
                        # when this was got wrong. Breaking after the write
                        # keeps the draw count at exactly one, as before.
                        ev_time = max(s_dt, CURRENT_TIME - timedelta(seconds=1))
                        stop_after_this = True
                    e_type, page_url = event_at_step(step, n_ev, converted,
                                                     cat_id, browse_pid)
                    event_seq += 1
                    f_ev.write(json.dumps({
                        "event_id": event_seq, "session_id": sid,
                        "product_id": browse_pid, "event_type": e_type,
                        "page_url": page_url,
                        "metadata": {"error_message": None, "http_status_code": 200,
                                     "estimated_lost_revenue": None},
                        "created_at": ev_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }) + "\n")
                    total_events += 1
                    last_ev_time = ev_time
                    # A page view is a navigation to a URL. Interactions that
                    # stay on the same page (filters, zooms) are events but not
                    # page views, which is why this is a subset of the event
                    # count and not a duplicate of it.
                    if is_page_view(e_type):
                        page_views += 1
                    if stop_after_this:
                        break

                # The session row is written HERE, after its events, because
                # session_ended_at and page_views_count are read off them. The
                # write order is unchanged - still exactly one session row per
                # iteration, in the same sequence - and moving a file write
                # consumes no random numbers.
                f_sess.write(json.dumps({
                    "session_id": sid,
                    "user_id": int(user_ids[i]) if has_user[i] else None,
                    "traffic_source": channel,
                    "utm_source": utm_s, "utm_medium": utm_m, "utm_campaign": utm_c,
                    "primary_category_id": cat_id,
                    "converted_to_order": converted,
                    "device_os": dev_os, "browser": browser,
                    # Geography comes from the IP lookup, so it is known even
                    # when the visitor is not signed in and user_id is NULL.
                    "country": user_country_map.get(int(user_ids[i]), "France"),
                    "session_started_at": s_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "session_ended_at": last_ev_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "page_views_count": page_views,
                }) + "\n")

                if hero_intent[i]:
                    oos_seq += 1
                    sku = STOCKOUT_SKUS[oos_seq % len(STOCKOUT_SKUS)]
                    qty = 1 if np_rng.random() < 0.85 else 2
                    oos_interactions.append({
                        "interaction_id": oos_seq, "session_id": sid, "art_code": sku,
                        # Clamp to the snapshot: a click cannot be observed after the
                        # moment the warehouse was extracted. Mirrors the order clamp below.
                        "clicked_at": min(s_dt + timedelta(seconds=int(np_rng.integers(30, 240))),
                                          CURRENT_TIME - timedelta(seconds=30))
                                      .strftime("%Y-%m-%dT%H:%M:%SZ"),
                        # Gross unrealised demand, NOT a net revenue loss.
                        "pot_val": float(round(hero_prices[sku] * qty, 2)),
                    })

                if fallback_seen[i]:
                    rec_seq += 1
                    rec_cat = int(np_rng.choice([2, 3, 4]))
                    rec_pids, _, rec_w = cat_pick[rec_cat]
                    recommender_logs.append({
                        "log_id": f"REC-{rec_seq}", "session_id": sid,
                        "src_sku": STOCKOUT_SKUS[rec_seq % len(STOCKOUT_SKUS)],
                        "page_category_id": 1,
                        "rec_sku": int(rec_pids[np_rng.choice(len(rec_pids), p=rec_w)]),
                        "recommended_category_id": rec_cat,
                        "fb_rule_id": 99, "cat_mismatch_flg": 1,
                        "user_action": "BOUNCED" if fallback_bounced[i] else "IGNORED",
                        "opp_cost_eur": None,
                        # Clamp to the snapshot: sessions starting in the final five
                        # minutes would otherwise log impressions after the cutoff.
                        "recorded_at": min(s_dt + timedelta(seconds=int(np_rng.integers(20, 300))),
                                           CURRENT_TIME - timedelta(seconds=30))
                                       .strftime("%Y-%m-%dT%H:%M:%SZ"),
                    })
                elif normal_rec[i]:
                    rec_seq += 1
                    recommender_logs.append({
                        "log_id": f"REC-{rec_seq}", "session_id": sid,
                        "src_sku": browse_pid, "page_category_id": cat_id,
                        "rec_sku": int(pids[np_rng.choice(len(pids), p=weights)]),
                        "recommended_category_id": cat_id,
                        "fb_rule_id": 0, "cat_mismatch_flg": 0,
                        "user_action": "CLICKED" if np_rng.random() < 0.6 else "IGNORED",
                        "opp_cost_eur": None,
                        # Clamp to the snapshot: sessions starting in the final five
                        # minutes would otherwise log impressions after the cutoff.
                        "recorded_at": min(s_dt + timedelta(seconds=int(np_rng.integers(20, 300))),
                                           CURRENT_TIME - timedelta(seconds=30))
                                       .strftime("%Y-%m-%dT%H:%M:%SZ"),
                    })

                if not converted:
                    continue

                n_items = int(item_counts[conv_cursor])
                conv_cursor += 1
                order_seq += 1
                o_dt = s_dt + timedelta(seconds=int(np_rng.integers(180, 1500)))
                if o_dt >= CURRENT_TIME:
                    o_dt = CURRENT_TIME - timedelta(seconds=30)

                order_total = 0.0
                lines = []
                for _ in range(n_items):
                    idx = basket_pick[item_cursor]
                    qty = int(basket_qty[item_cursor])
                    ret_roll = returns_roll[item_cursor]
                    item_cursor += 1
                    price = float(round(float(prices[idx]) * basket_mult, 2))
                    order_total += price * qty
                    lines.append((int(pids[idx]), qty, price, ret_roll))

                revenue_by_cat_day[(cat_id, day_idx)] += order_total
                if is_paid:
                    paid_revenue_by_cat_day[(cat_id, day_idx)] += order_total

                # The return DATE is drawn HERE, ahead of the order row that
                # needs it, rather than inside the line loop below.
                #
                # Two reasons. First, a return dated after the warehouse
                # snapshot has not happened yet, so the column must be NULL -
                # and order_status has to agree with that, which means the
                # status needs the dates. Writing "Returned" for a return that
                # is still in the future was making the warehouse contradict
                # itself. Second, hoisting is RNG-neutral: the draw still
                # happens once per line, in line order, under exactly the same
                # `returned` condition, and nothing between here and the old
                # site consumes randomness.
                return_dts = []
                for _, _, _, rr in lines:
                    if rr >= ITEM_RETURN_RATE:
                        return_dts.append(None)
                        continue
                    r_dt = o_dt + timedelta(days=int(np_rng.integers(1, 3)))
                    return_dts.append(r_dt if r_dt < CURRENT_TIME else None)

                # order_status is DERIVED from the return dates above, so it
                # consumes no new random numbers and cannot shift the shared
                # RNG stream. The rule itself lives in scripts/order_status.py,
                # shared with the historical generator.
                status = derive_order_status(d is not None for d in return_dts)

                orders.append({
                    "order_id": order_seq, "user_id": int(user_ids[i]),
                    "session_id": sid, "order_status": status,
                    "total_amount": float(round(order_total, 2)),
                    "tax_amount": float(round(order_total * 0.20, 2)),
                    "shipping_fee": 4.99 if order_total < 50.0 else 0.0,
                    "num_of_items": len(lines),
                    "created_at": o_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                })

                for (pid, qty, price, _), r_dt in zip(lines, return_dts):
                    item_seq += 1
                    # Dispatch and delivery are clamped for the same reason as
                    # the return date: an order placed two hours before the
                    # extract has not shipped yet, so the warehouse holds NULL
                    # rather than a promise about the future. Before this, 100%
                    # of 26-27 November line items carried a delivery date that
                    # had not arrived.
                    ship_dt = o_dt + timedelta(hours=12)
                    deliv_dt = o_dt + timedelta(days=2)
                    order_items.append({
                        "order_item_id": item_seq, "ord_hdr_num": order_seq,
                        "user_id": int(user_ids[i]), "mat_nr": pid,
                        "inventory_item_id": inv_by_product[pid],
                        "quantity": qty, "sale_price": price, "discount_amount": 0.0,
                        "created_at": o_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "shipped_at": (ship_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                                       if ship_dt < CURRENT_TIME else None),
                        "delivered_at": (deliv_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                                         if deliv_dt < CURRENT_TIME else None),
                        "returned_at": (r_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                                        if r_dt else None),
                    })
                    sales_events.append({
                        "event_id": str(uuid.uuid4()), "order_id": order_seq,
                        "product_id": pid, "category_id": cat_id, "quantity": qty,
                        "sale_price": price, "discount_amount": 0.0,
                        "timestamp": o_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    })

    print(f"  {session_seq:,} sessions | {total_events:,} events "
          f"({total_events/max(session_seq,1):.2f} per session)")
    print(f"  {order_seq:,} orders | {item_seq:,} order items")
    _dist = status_distribution(orders)
    print("  order_status: " + " | ".join(
        f"{s} {n:,} ({n / max(len(orders), 1):.1%})" for s, n in _dist.items()))
    print(f"  {len(oos_interactions):,} OOS interactions | "
          f"{len(recommender_logs):,} recommender impressions")

    return {
        "temp_dir": temp_dir,
        "sessions_path": sessions_path,
        "events_path": events_path,
        "session_count": session_seq,
        "orders": orders,
        "order_items": order_items,
        "sales_event_stream": sales_events,
        "oos_interactions": oos_interactions,
        "catalog_recommender_logs": recommender_logs,
        "telemetry": {
            "sessions": dict(sessions_by_cat_day),
            "orders": dict(orders_by_cat_day),
            "paid_sessions": dict(paid_sessions_by_cat_day),
            "paid_orders": dict(paid_orders_by_cat_day),
            "paid_revenue": dict(paid_revenue_by_cat_day),
            "revenue": dict(revenue_by_cat_day),
        },
    }


# ---------------------------------------------------------------------------
# 12. SUPPORTING ENTITIES (warehouses, stock, customers)
# ---------------------------------------------------------------------------

DISTRIBUTION_CENTERS = [
    (1, "Paris Nord Fulfilment Centre", 48.9362, 2.3574),
    (2, "Rotterdam Port Hub", 51.9244, 4.4777),
    (3, "Hamburg Sud Logistics Hub", 53.5511, 9.9937),
    (4, "Milano Est Distribution Centre", 45.4642, 9.1900),
    (5, "Barcelona Zona Franca Hub", 41.3479, 2.1300),
]

# Share of the customer base by country. DACH is Germany + Austria.
COUNTRY_WEIGHTS = {
    "France": 0.24, "Germany": 0.22, "Netherlands": 0.12, "Spain": 0.11,
    "Italy": 0.11, "Belgium": 0.08, "Austria": 0.07, "Sweden": 0.05,
}

COUNTRY_TO_REGION = {
    "France": "France", "Germany": "DACH", "Austria": "DACH",
    "Netherlands": "Benelux", "Belgium": "Benelux",
    "Spain": "Southern Europe", "Italy": "Southern Europe",
    "Sweden": "Nordics",
}

COUNTRY_COORDS = {
    "France": (48.8566, 2.3522), "Germany": (52.5200, 13.4050),
    "Netherlands": (52.3676, 4.9041), "Spain": (40.4168, -3.7038),
    "Italy": (45.4642, 9.1900), "Belgium": (50.8503, 4.3517),
    "Austria": (48.2082, 16.3738), "Sweden": (59.3293, 18.0686),
}

N_USERS = 10_000

# The three hero SKUs run dry late on Sunday and are back on the shelf late on
# Wednesday. STOCKOUT_DAYS ({0,1,2}) is the conversion-model view of the same
# window; these two timestamps are the operational view recorded in stock data.
STOCKOUT_BEGAN_AT = datetime(2026, 11, 22, 18, 0, 0)
STOCKOUT_ENDED_AT = datetime(2026, 11, 25, 23, 0, 0)

SNAPSHOT_START = datetime(2026, 11, 20, 0, 0, 0)
SNAPSHOT_INTERVAL_HOURS = 6


def build_supporting_entities(products, rng, np_rng):
    """
    Build warehouses, stock records and the customer base.

    Must run BEFORE materialise(), because order lines reference
    `inventory_items.inventory_item_id` through the returned `inv_by_product`
    mapping.
    """
    print("Building distribution centres, inventory and customers ...")

    distribution_centers = [
        {"dc_id": dc_id, "name": name, "latitude": lat, "longitude": lon}
        for dc_id, name, lat, lon in DISTRIBUTION_CENTERS
    ]

    inventory_items = []
    inv_by_product = {}
    inv_seq = 0
    base_stock = {}

    for p in products:
        pid = p["product_id"]
        is_hero = pid in STOCKOUT_SKUS
        # A-class SKUs are held in more hubs than the long tail.
        n_batches = 3 if pid < 1006 else (2 if rng.random() < 0.35 else 1)
        dc_ids = rng.sample([d[0] for d in DISTRIBUTION_CENTERS], n_batches)
        total = 0
        for j, dc_id in enumerate(dc_ids):
            inv_seq += 1
            # The heroes were restocked on Wednesday night, so as at the clock
            # they hold stock again. The outage lives in the snapshot history.
            qty = int(np_rng.integers(280, 640)) if is_hero else int(np_rng.integers(40, 900))
            safety = max(20, int(qty * float(np_rng.uniform(0.08, 0.18))))
            arrival = (STOCKOUT_ENDED_AT - timedelta(hours=2) if is_hero
                       else SNAPSHOT_START - timedelta(days=int(np_rng.integers(3, 45))))
            inventory_items.append({
                "inventory_item_id": inv_seq,
                "product_id": pid,
                "dc_id": dc_id,
                "quantity_on_hand": qty,
                "safety_stock_level": safety,
                "created_at": arrival.strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
            total += qty
            if j == 0:
                inv_by_product[pid] = inv_seq
        base_stock[pid] = total

    # --- Snapshots -------------------------------------------------------
    # A stock level series every 6 hours. Levels drift down as the week sells
    # through, with a replenishment bump midweek. The three hero SKUs sit at
    # zero for the duration of the outage; nothing in this table says why.
    inventory_snapshots = []
    snap_seq = 0
    cursor = SNAPSHOT_START
    buckets = []
    while cursor < CURRENT_TIME:
        buckets.append(cursor)
        cursor += timedelta(hours=SNAPSHOT_INTERVAL_HOURS)

    for p in products:
        pid = p["product_id"]
        is_hero = pid in STOCKOUT_SKUS
        level = float(base_stock[pid]) * float(np_rng.uniform(1.25, 1.8))
        # Sell-through per bucket, faster for popular low-id SKUs.
        rank = (pid % 150) + 1
        drain = 1.0 / (rank ** 0.55) * float(np_rng.uniform(0.6, 1.4))
        for b in buckets:
            snap_seq += 1
            level = max(0.0, level - level * min(0.22, drain))
            if b.hour == 0 and b.day % 2 == 0:
                level += base_stock[pid] * float(np_rng.uniform(0.10, 0.35))
            if is_hero:
                if STOCKOUT_BEGAN_AT <= b < STOCKOUT_ENDED_AT:
                    qty = 0
                elif b < STOCKOUT_BEGAN_AT:
                    # Draining hard in the run-up: demand outran the reorder.
                    hours_left = (STOCKOUT_BEGAN_AT - b).total_seconds() / 3600.0
                    qty = int(max(0, hours_left * float(np_rng.uniform(2.0, 5.0))))
                else:
                    qty = int(base_stock[pid] * float(np_rng.uniform(0.72, 1.0)))
            else:
                qty = int(round(level))
            inventory_snapshots.append({
                "snapshot_id": snap_seq,
                "product_id": pid,
                "recorded_at": b.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "stock_quantity": qty,
                "is_out_of_stock": qty <= 0,
            })

    # --- Customers -------------------------------------------------------
    first_names = ["Camille", "Lucas", "Sofia", "Jonas", "Emma", "Mateo", "Lea",
                   "Nils", "Chiara", "Hugo", "Anouk", "Elias", "Marta", "Finn",
                   "Ines", "Viktor", "Julia", "Sander", "Nora", "Tomas"]
    last_names = ["Dubois", "Moreau", "Fischer", "Bakker", "Rossi", "Garcia",
                  "Lambert", "Weber", "de Vries", "Conti", "Lopez", "Janssen",
                  "Schneider", "Bianchi", "Martin", "Nilsson", "Peeters",
                  "Hoffmann", "Ferrari", "Andersson"]
    countries = list(COUNTRY_WEIGHTS)
    country_p = np.array([COUNTRY_WEIGHTS[c] for c in countries])
    country_p = country_p / country_p.sum()
    country_pick = np_rng.choice(len(countries), size=N_USERS, p=country_p)

    users = []
    for i in range(1, N_USERS + 1):
        country = countries[int(country_pick[i - 1])]
        lat, lon = COUNTRY_COORDS[country]
        fn = rng.choice(first_names)
        ln = rng.choice(last_names)
        signup = SNAPSHOT_START - timedelta(days=int(np_rng.integers(5, 1400)))
        users.append({
            "user_id": i,
            "email": f"{fn.lower()}.{ln.lower().replace(' ', '')}{i}@example.com",
            "first_name": fn,
            "last_name": ln,
            "gender": rng.choice(["Female", "Male", "Prefer not to say"]),
            "age": int(np_rng.integers(18, 72)),
            "country": country,
            "latitude": float(round(lat + float(np_rng.normal(0, 0.8)), 4)),
            "longitude": float(round(lon + float(np_rng.normal(0, 0.8)), 4)),
            "created_at": signup.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

    print(f"  {len(distribution_centers)} hubs | {len(inventory_items):,} stock batches "
          f"| {len(inventory_snapshots):,} snapshots | {len(users):,} customers")

    return (distribution_centers, inventory_items, inventory_snapshots,
            users, inv_by_product)


# ---------------------------------------------------------------------------
# 13. COMMERCIAL TARGETS
# ---------------------------------------------------------------------------

def quarter_hour_weights():
    """Split the hourly demand curve into 96 quarter-hour buckets."""
    weights = []
    for h in range(24):
        cur = INTRADAY_WEIGHTS[h]
        nxt = INTRADAY_WEIGHTS[(h + 1) % 24]
        for q in range(4):
            frac = (q + 0.5) / 4.0
            weights.append(cur + (nxt - cur) * frac * 0.5)
    total = sum(weights)
    return [w / total for w in weights]


QUARTER_WEIGHTS = quarter_hour_weights()

# Promotional days pull the basket up slightly; the weekend tail pulls it down.
AOV_DAY_FACTOR = [0.97, 0.98, 0.99, 1.02, 1.05, 1.00, 0.98, 1.01]


def build_targets(observed_fraction):
    """
    Derive the stored commercial plan from the published to-date targets.

    The figures quoted in the case study are TARGET TO DATE, i.e. as at the
    Friday 14:30 clock. BigQuery holds the full 8-day plan, so each figure is
    divided by the observed window fraction. Correctly pacing the stored plan
    back to the clock reproduces the published number exactly; comparing a
    4.6-day actual against the full 8-day plan does not.
    """
    weekly, daily, intraday = [], [], []
    week_start = SIMULATION_START.date().strftime("%Y-%m-%d")
    target_seq = 0

    for cat_id in sorted(TARGET_TO_DATE):
        t = TARGET_TO_DATE[cat_id]
        # Direct, email and affiliate traffic is unaffected by paid media, so
        # the plan for those channels is close to what they delivered.
        other_td = sum(v for ch, v in NONPAID_SESSIONS[cat_id].items()
                       if ch != "Organic Search") * 1.02
        sessions_td = t["paid_sessions"] + t["organic_sessions"] + other_td

        rev_week = t["revenue"] / observed_fraction
        sessions_week = sessions_td / observed_fraction
        spend_week = t["ad_spend"] / observed_fraction
        orders_week = rev_week / t["aov"]
        cvr_week = orders_week / sessions_week

        target_seq += 1
        weekly.append({
            "target_id": target_seq,
            "category_id": cat_id,
            "week_start_date": week_start,
            "target_revenue": float(round(rev_week, 2)),
            "target_sessions": int(round(sessions_week)),
            "target_conversion_rate": float(round(cvr_week, 5)),
        })

        for day_idx in range(8):
            day = (SIMULATION_START + timedelta(days=day_idx)).date()
            w = DAY_WEIGHTS[day_idx]
            day_rev = rev_week * w
            day_sessions = sessions_week * w
            day_spend = spend_week * w
            day_aov = t["aov"] * AOV_DAY_FACTOR[day_idx]
            day_orders = day_rev / day_aov
            daily.append({
                "target_id": f"DCT-{cat_id}-{day.strftime('%Y%m%d')}",
                "category_id": cat_id,
                "date": day.strftime("%Y-%m-%d"),
                "target_revenue": float(round(day_rev, 2)),
                "target_sessions": int(round(day_sessions)),
                "target_conversion_rate": float(round(day_orders / day_sessions, 5)),
                "target_aov": float(round(day_aov, 2)),
                "target_ad_spend": float(round(day_spend, 2)),
                # Blended ROAS: TOTAL category revenue over ad spend, not the
                # paid-attributed ROAS the bidding engine optimises against.
                # The two are legitimately different metrics.
                "target_roas": float(round(day_rev / day_spend, 3)),
            })

            # The quarter-hour plan is a weekly shape, keyed by day of week, so
            # only the first seven days contribute (day 7 repeats Monday).
            if day_idx >= 7:
                continue
            dow = (day.weekday() + 1) % 7 + 1
            for q in range(96):
                hh, mm = divmod(q * 15, 60)
                intraday.append({
                    "target_id": f"Q15-{cat_id}-{dow}-{hh:02d}{mm:02d}",
                    "category_id": cat_id,
                    "day_of_week": dow,
                    "time_bucket": f"{hh:02d}:{mm:02d}:00",
                    "target_revenue": float(round(day_rev * QUARTER_WEIGHTS[q], 2)),
                    "target_sessions": int(round(day_sessions * QUARTER_WEIGHTS[q])),
                })

    print(f"  {len(weekly)} weekly | {len(daily)} daily | "
          f"{len(intraday):,} quarter-hour targets")
    return weekly, daily, intraday


# ---------------------------------------------------------------------------
# 14. PERIPHERAL TABLES
# ---------------------------------------------------------------------------

COMPETITORS = ["BellaNord", "Prisma Retail", "Kaufhaus24"]

CARRIER_BY_REGION = {
    "France": "Chronopost", "DACH": "DHL Express", "Benelux": "PostNL",
    "Southern Europe": "GLS Italia", "Nordics": "PostNord",
}

# Standard fulfilment SLA per region, in hours.
STANDARD_LEAD_TIME = {
    "France": 24, "DACH": 48, "Benelux": 24,
    "Southern Europe": 72, "Nordics": 72,
}

PAYMENT_PROVIDERS = [("Stripe", 0.42), ("Adyen", 0.36), ("PayPal", 0.22)]
PAYMENT_METHODS = [("Credit Card", 0.54), ("PayPal", 0.21),
                   ("Apple Pay", 0.15), ("SEPA Direct Debit", 0.10)]


def build_peripheral_tables(products, users, orders, session_count, rng, np_rng):
    """
    Build the surrounding operational tables.

    Everything financial here is DERIVED from the transactional tables that the
    simulation already produced. Nothing states a conclusion, and nothing is a
    precomputed answer waiting to be read out.
    """
    print("Building peripheral operational tables ...")
    price_by_id = {p["product_id"]: float(p["retail_price"]) for p in products}
    user_country = {u["user_id"]: u["country"] for u in users}

    # --- Competitor price feed ------------------------------------------
    # A scraper run on the Monday and again on the Thursday. Competitor pricing
    # varies around ours with genuine noise, not a fixed 0.99x / 1.01x.
    competitor_price_feed = []
    scrape_seq = 0
    sampled = rng.sample([p["product_id"] for p in products], 200)
    for scrape_day in (0, 3):
        scraped_at = SIMULATION_START + timedelta(days=scrape_day, hours=4, minutes=15)
        for pid in sampled:
            for comp in COMPETITORS:
                scrape_seq += 1
                index = float(np_rng.normal(0.99, 0.075))
                index = min(max(index, 0.72), 1.34)
                competitor_price_feed.append({
                    "scrape_id": scrape_seq,
                    "product_id": pid,
                    "competitor_name": comp,
                    "competitor_price": float(round(price_by_id[pid] * index, 2)),
                    "is_in_stock": bool(np_rng.random() > 0.11),
                    "scraped_at": scraped_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                })

    # --- Marketing campaigns --------------------------------------------
    marketing_campaigns = [
        {"campaign_id": c["campaign_id"], "name": c["name"], "platform": c["platform"],
         "target_category_id": cat_id, "bidding_strategy": c["bidding_strategy"],
         "is_active": True}
        for cat_id, c in sorted(CAMPAIGNS.items())
    ]
    # Retired campaigns from earlier in the quarter, so the table is not a
    # suspiciously tidy list of exactly four rows.
    marketing_campaigns += [
        {"campaign_id": 991, "name": "Beauty_Autumn_Prospecting", "platform": "Meta Ads",
         "target_category_id": 1, "bidding_strategy": "Maximize Conversions", "is_active": False},
        {"campaign_id": 992, "name": "Electronics_BackToSchool", "platform": "Google Ads",
         "target_category_id": 2, "bidding_strategy": "Target CPA", "is_active": False},
        {"campaign_id": 993, "name": "Fashion_SS26_Teaser", "platform": "Pinterest Ads",
         "target_category_id": 3, "bidding_strategy": "Maximize Clicks", "is_active": False},
    ]

    # --- Ad creatives ----------------------------------------------------
    # Beauty's paid social set has not been refreshed since September. Stale
    # creative is what drives the CPC inflation the bidding engine reacts to.
    ad_creatives = []
    creative_seq = 5000
    beauty_stale = [
        "BF26_Beauty_Serum_Hero_V1", "BF26_Beauty_Serum_Hero_V2",
        "BF26_Beauty_Carousel_Bestsellers", "BF26_Beauty_Story_GlowRoutine",
        "BF26_Beauty_Reel_UGC_Elena",
    ]
    for name in beauty_stale:
        creative_seq += 1
        ad_creatives.append({
            "creative_id": creative_seq, "parent_adgroup_id": 1001, "name": name,
            "ad_format": rng.choice(["Video", "Carousel", "Static Image"]),
            "quality_score": int(np_rng.integers(3, 6)),
            "relevance_status": "BELOW_AVERAGE",
            "dlv_lrn_lmt_flg": True,
            "last_refreshed_at": (datetime(2026, 9, 1)
                                  + timedelta(days=int(np_rng.integers(0, 21)))
                                  ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    for name in ["BF26_Beauty_Static_GiftSet", "BF26_Beauty_Video_Unboxing",
                 "BF26_Beauty_Collection_Advent"]:
        creative_seq += 1
        ad_creatives.append({
            "creative_id": creative_seq, "parent_adgroup_id": 1001, "name": name,
            "ad_format": rng.choice(["Video", "Static Image"]),
            "quality_score": int(np_rng.integers(6, 9)),
            "relevance_status": "AVERAGE",
            "dlv_lrn_lmt_flg": False,
            "last_refreshed_at": (datetime(2026, 11, 12)
                                  + timedelta(days=int(np_rng.integers(0, 8)))
                                  ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    other_creatives = {
        1002: ["BF26_Electronics_Search_RSA_A", "BF26_Electronics_Search_RSA_B",
               "BF26_Electronics_Shopping_Feed"],
        1003: ["BF26_Fashion_Retarget_Dynamic", "BF26_Fashion_Retarget_Static",
               "BF26_Fashion_Collection_Winter"],
        1004: ["BF26_Home_Newsletter_Header", "BF26_Home_Newsletter_Deals",
               "BF26_Home_Newsletter_GiftGuide"],
    }
    for campaign_id, names in other_creatives.items():
        for name in names:
            creative_seq += 1
            ad_creatives.append({
                "creative_id": creative_seq, "parent_adgroup_id": campaign_id,
                "name": name,
                "ad_format": rng.choice(["Video", "Carousel", "Static Image", "Text"]),
                "quality_score": int(np_rng.integers(6, 10)),
                "relevance_status": rng.choice(["AVERAGE", "ABOVE_AVERAGE"]),
                "dlv_lrn_lmt_flg": False,
                "last_refreshed_at": (datetime(2026, 11, 10)
                                      + timedelta(days=int(np_rng.integers(0, 11)))
                                      ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })

    # --- Payment gateway logs -------------------------------------------
    # One authorisation per completed order, plus retries and standalone
    # failures on sessions that never produced an order.
    #
    # A genuine but SMALL operational issue is seeded here: one provider runs
    # elevated timeouts in one country midweek. It is real, it is findable, and
    # it is nowhere near large enough to explain the Beauty shortfall. It is
    # there so that an agent has something plausible to chase and rule out.
    payment_gateway_logs = []
    prov_names = [p[0] for p in PAYMENT_PROVIDERS]
    prov_p = np.array([p[1] for p in PAYMENT_PROVIDERS])
    meth_names = [m[0] for m in PAYMENT_METHODS]
    meth_p = np.array([m[1] for m in PAYMENT_METHODS])
    n_ord = len(orders)
    prov_pick = np_rng.choice(len(prov_names), size=n_ord, p=prov_p)
    meth_pick = np_rng.choice(len(meth_names), size=n_ord, p=meth_p)
    retry_roll = np_rng.random(n_ord)
    # TECHNICAL_SPECIFICATION.md section 3.2 requires successful gateway logs to
    # cover 90-95% of completed orders. The remainder are settled off-gateway
    # (store vouchers, gift cards, B2B bank invoices) and never appear here.
    gateway_roll = np_rng.random(n_ord)
    latency = np_rng.integers(180, 1400, n_ord)
    pay_seq = 0

    for i, o in enumerate(orders):
        if gateway_roll[i] < 0.075:
            continue
        provider = prov_names[int(prov_pick[i])]
        method = meth_names[int(meth_pick[i])]
        country = user_country.get(o["user_id"], "France")
        created = datetime.strptime(o["created_at"], "%Y-%m-%dT%H:%M:%SZ")

        if retry_roll[i] < 0.048:
            pay_seq += 1
            payment_gateway_logs.append({
                "gateway_log_id": f"PG-{pay_seq}",
                "session_id": o["session_id"], "order_id": None,
                "payment_provider": provider, "payment_method": method,
                "status": "FAILED", "http_status_code": 402,
                "error_code": rng.choice(["INSUFFICIENT_FUNDS", "DO_NOT_HONOR",
                                          "ERR_3DS_CHALLENGE_ABANDONED"]),
                "total_amount": float(o["total_amount"]),
                "latency_ms": int(np_rng.integers(300, 2200)),
                "country": country,
                "created_at": (created - timedelta(seconds=int(np_rng.integers(45, 400)))
                               ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
        pay_seq += 1
        payment_gateway_logs.append({
            "gateway_log_id": f"PG-{pay_seq}",
            "session_id": o["session_id"], "order_id": o["order_id"],
            "payment_provider": provider, "payment_method": method,
            "status": "SUCCESS", "http_status_code": 200, "error_code": None,
            "total_amount": float(o["total_amount"]),
            "latency_ms": int(latency[i]), "country": country,
            "created_at": o["created_at"],
        })

    # Standalone failures: sessions that reached the gateway and stopped there.
    n_standalone = 3200
    for _ in range(n_standalone):
        pay_seq += 1
        sid = f"SESS-{int(np_rng.integers(1, max(session_count, 2)))}"
        when = SIMULATION_START + timedelta(
            seconds=int(np_rng.integers(0, int((CURRENT_TIME - SIMULATION_START).total_seconds()))))
        country = rng.choices(list(COUNTRY_WEIGHTS), weights=list(COUNTRY_WEIGHTS.values()))[0]
        # The midweek incident: Adyen timeouts in Germany on Nov 24-25.
        adyen_window = (datetime(2026, 11, 24, 6, 0) <= when < datetime(2026, 11, 25, 22, 0))
        if adyen_window and country == "Germany" and np_rng.random() < 0.55:
            provider, status, code, http = "Adyen", "TIMEOUT", "ERR_504_GATEWAY_TIMEOUT", 504
            lat_ms = int(np_rng.integers(9000, 30000))
        else:
            provider = rng.choices(prov_names, weights=[p[1] for p in PAYMENT_PROVIDERS])[0]
            status = rng.choice(["FAILED", "FAILED", "TIMEOUT"])
            code = ("ERR_504_GATEWAY_TIMEOUT" if status == "TIMEOUT"
                    else rng.choice(["INSUFFICIENT_FUNDS", "CARD_EXPIRED",
                                     "DO_NOT_HONOR", "ERR_3DS_CHALLENGE_ABANDONED"]))
            http = 504 if status == "TIMEOUT" else 402
            lat_ms = int(np_rng.integers(8000, 26000)) if status == "TIMEOUT" else int(np_rng.integers(250, 2400))
        payment_gateway_logs.append({
            "gateway_log_id": f"PG-{pay_seq}",
            "session_id": sid, "order_id": None,
            "payment_provider": provider,
            "payment_method": rng.choices(meth_names, weights=[m[1] for m in PAYMENT_METHODS])[0],
            "status": status, "http_status_code": http, "error_code": code,
            "total_amount": float(round(float(np_rng.uniform(19, 260)), 2)),
            "latency_ms": lat_ms, "country": country,
            "created_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

    # --- Influencer campaigns -------------------------------------------
    influencer_specs = [
        (1, "@elena.glowroutine", "TikTok", "BF26_Beauty_Creator_Wave1", "GLOW_ELENA_BF", 1),
        (2, "@marc.techdaily", "YouTube", "BF26_Electronics_Reviews", "TECH_MARC_BF", 2),
        (3, "@sofia.style", "Instagram", "BF26_Fashion_Lookbook", "STYLE_SOFIA_BF", 3),
        (4, "@maison.nordique", "Instagram", "BF26_Home_Interiors", "NEST_MAISON_BF", 4),
        (5, "@juliaskin", "TikTok", "BF26_Beauty_Creator_Wave1", "SKIN_JULIA_BF", 1),
        (6, "@thefinnfiles", "YouTube", "BF26_Electronics_Reviews", "GEAR_FINN_BF", 2),
        (7, "@camille.curates", "Instagram", "BF26_Beauty_Creator_Wave2", "CURATE_CAMILLE_BF", 1),
        (8, "@nordicnest.se", "Pinterest", "BF26_Home_Interiors", "NORDIC_NEST_BF", 4),
    ]
    influencer_campaigns = []
    for inf_id, handle, platform, campaign, promo, cat_id in influencer_specs:
        views = int(np_rng.integers(38_000, 940_000))
        cvr = float(np_rng.uniform(0.0035, 0.0125))
        orders_count = int(views * cvr)
        aov = ACTUAL_AOV_GOAL[cat_id] * float(np_rng.uniform(0.92, 1.18))
        actual = orders_count * aov
        influencer_campaigns.append({
            "influencer_id": inf_id, "creator_name": handle, "platform": platform,
            "campaign_name": campaign, "promo_code": promo,
            "target_revenue": float(round(actual * float(np_rng.uniform(0.85, 1.45)), 2)),
            "actual_revenue": float(round(actual, 2)),
            "orders_count": orders_count, "views_count": views,
            "fee_amount": float(round(float(np_rng.uniform(1_800, 24_000)), 2)),
            "is_active": True,
            "created_at": (SIMULATION_START - timedelta(days=int(np_rng.integers(3, 20)))
                           ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

    # --- Shipping lead times --------------------------------------------
    # Peak-season carrier congestion pushes the promised delivery window out,
    # which costs a measurable slice of checkout conversion. The financial
    # impact is DERIVED from the revenue actually booked in that region on that
    # day, not asserted as a constant.
    revenue_by_date = defaultdict(float)
    revenue_by_date_region = defaultdict(float)
    for o in orders:
        d = o["created_at"][:10]
        region = COUNTRY_TO_REGION.get(user_country.get(o["user_id"], "France"), "France")
        revenue_by_date[d] += float(o["total_amount"])
        revenue_by_date_region[(d, region)] += float(o["total_amount"])

    shipping_lead_times = []
    regions = list(STANDARD_LEAD_TIME)
    for day_idx in range(5):
        day = (SIMULATION_START + timedelta(days=day_idx)).date()
        d_str = day.strftime("%Y-%m-%d")
        for dc_id, _, _, _ in DISTRIBUTION_CENTERS:
            for region in regions:
                std = STANDARD_LEAD_TIME[region]
                # DACH congestion builds from Tuesday and peaks on Thursday.
                if region == "DACH":
                    util = [78.0, 91.5, 96.2, 98.4, 94.1][day_idx]
                else:
                    util = float(np_rng.uniform(62.0, 86.0))
                overrun = max(0.0, (util - 90.0) / 10.0)
                promised = int(round(std * (1.0 + overrun * 0.85)))
                # Every extra 24h of promised wait costs roughly 1.9 points of
                # checkout completion (LumiereShop's own elasticity estimate).
                extra_hours = max(0, promised - std)
                abandon_pct = round(extra_hours / 24.0 * 1.9, 3)
                region_rev = revenue_by_date_region.get((d_str, region), 0.0)
                # This hub's share of the region's volume.
                hub_share = 1.0 / len(DISTRIBUTION_CENTERS)
                lost = region_rev * hub_share * (abandon_pct / 100.0)
                shipping_lead_times.append({
                    "lead_time_id": f"SLT-{dc_id}-{region.replace(' ', '')}-{day.strftime('%Y%m%d')}",
                    "dc_id": dc_id, "date": d_str,
                    "carrier_name": CARRIER_BY_REGION[region],
                    "destination_region": region,
                    "capacity_utilization_pct": float(round(util, 1)),
                    "standard_lead_time_hours": std,
                    "actual_promised_lead_time_hours": promised,
                    "cart_abandonment_impact_pct": float(abandon_pct),
                    "estimated_lost_revenue": float(round(lost, 2)),
                })

    # --- Competitor promotions ------------------------------------------
    promo_specs = [
        ("BellaNord", 1, "Beauty Week - up to 40% off skincare", 40.0),
        ("BellaNord", 3, "Winter Wardrobe Event", 30.0),
        ("Prisma Retail", 1, "Black Friday Beauty Doorbusters", 45.0),
        ("Prisma Retail", 2, "Tech Deals Countdown", 25.0),
        ("Prisma Retail", 4, "Home & Living Black Friday", 35.0),
        ("Kaufhaus24", 1, "Beauty Advent Pre-Sale", 25.0),
        ("Kaufhaus24", 2, "Elektronik Schnappchen", 30.0),
        ("Kaufhaus24", 3, "Mode Black Week", 50.0),
        ("BellaNord", 2, "Audio & Wearables Flash Sale", 20.0),
        ("BellaNord", 4, "Cosy Home Edit", 22.0),
        ("Prisma Retail", 3, "Fashion Friday Drops", 40.0),
        ("Kaufhaus24", 4, "Haushalt Black Week", 28.0),
    ]
    competitor_promotions = []
    for i, (comp, cat_id, title, discount) in enumerate(promo_specs, start=1):
        start_offset = int(np_rng.integers(-3, 2))
        start = (SIMULATION_START + timedelta(days=start_offset)).date()
        end = (SIMULATION_START + timedelta(days=int(np_rng.integers(5, 10)))).date()
        competitor_promotions.append({
            "promo_id": i, "competitor_name": comp, "category_id": cat_id,
            "promotion_title": title,
            "discount_pct": float(round(discount + float(np_rng.normal(0, 2.5)), 1)),
            "price_index_vs_lumiere": float(round(float(np_rng.normal(0.985, 0.055)), 4)),
            "start_date": start.strftime("%Y-%m-%d"),
            "end_date": end.strftime("%Y-%m-%d"),
            "scraped_at": (SIMULATION_START + timedelta(days=1, hours=6)
                           ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

    print(f"  {len(competitor_price_feed):,} price scrapes | "
          f"{len(payment_gateway_logs):,} gateway logs | "
          f"{len(ad_creatives)} creatives | {len(shipping_lead_times)} lead-time rows")

    return {
        "competitor_price_feed": competitor_price_feed,
        "marketing_campaigns": marketing_campaigns,
        "ad_creatives": ad_creatives,
        "payment_gateway_logs": payment_gateway_logs,
        "influencer_campaigns": influencer_campaigns,
        "shipping_lead_times": shipping_lead_times,
        "competitor_promotions": competitor_promotions,
    }


# ---------------------------------------------------------------------------
# 15. BIGQUERY LOAD AND ORCHESTRATION
# ---------------------------------------------------------------------------

def get_bigquery_client(project_id):
    access_token = os.environ.get("GCP_ACCESS_TOKEN")
    if not access_token:
        for gcloud_cmd in ("/google/data/ro/teams/cloud-sdk/gcloud", "gcloud"):
            try:
                res = subprocess.run([gcloud_cmd, "auth", "print-access-token"],
                                     capture_output=True, text=True, timeout=15)
                if res.returncode == 0 and res.stdout.strip():
                    access_token = res.stdout.strip()
                    break
            except Exception:
                continue
    if access_token:
        creds = oauth2_credentials.Credentials(access_token)
        return bigquery.Client(project=project_id, credentials=creds)
    return bigquery.Client(project=project_id)


def load_ndjson_file_to_bq(client, table_name, file_path):
    table_ref = f"{PROJECT_ID}.{DATASET_ID}.{table_name}"
    # Pass the destination schema for the same reason as the in-memory loader:
    # WRITE_TRUNCATE without a schema lets autodetect replace the table and
    # destroy its column descriptions.
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        ignore_unknown_values=True,
        schema=client.get_table(table_ref).schema,
    )
    # NOTE: do NOT set `job_config.compression`. That property exists only on
    # ExtractJobConfig; assigning it to a LoadJobConfig raises
    #   "Property compression is unknown for LoadJobConfig"
    # which is exactly what silently emptied web_sessions and web_events on the
    # 2026-09-11 rebuild. BigQuery auto-detects gzip on load, so nothing is
    # needed here for `.gz` inputs.
    size_mb = os.path.getsize(file_path) / (1024 * 1024)
    print(f"  Uploading `{table_name}` ({size_mb:,.1f} MB) ...")
    with open(file_path, "rb") as source_file:
        job = client.load_table_from_file(source_file, table_ref, job_config=job_config)
        job.result()
    print(f"  Loaded `{table_name}`.")


def report_outcome(out, ctx, spend_by_cat_day):
    """
    Print what the simulation actually produced.

    This is the reconciliation record: every figure here is counted from the
    generated rows, so it can be checked directly against BigQuery afterwards.
    """
    tel = out["telemetry"]
    print("\n" + "=" * 78)
    print("EMERGENT OUTCOME (counted from generated rows)")
    print("=" * 78)

    rev_by_cat = defaultdict(float)
    sess_by_cat = defaultdict(int)
    ord_by_cat = defaultdict(int)
    paid_rev_by_cat = defaultdict(float)
    spend_by_cat = defaultdict(float)
    for (cat_id, _day), v in tel["revenue"].items():
        rev_by_cat[cat_id] += v
    for (cat_id, _day), v in tel["sessions"].items():
        sess_by_cat[cat_id] += v
    for (cat_id, _day), v in tel["orders"].items():
        ord_by_cat[cat_id] += v
    for (cat_id, _day), v in tel["paid_revenue"].items():
        paid_rev_by_cat[cat_id] += v
    for (cat_id, _day), v in spend_by_cat_day.items():
        spend_by_cat[cat_id] += v

    print(f"{'Category':<14}{'Sessions':>12}{'Orders':>10}{'Revenue':>14}"
          f"{'AOV':>9}{'CVR':>8}{'PaidROAS':>10}")
    for cat_id in sorted(CATEGORY_NAMES):
        rev = rev_by_cat[cat_id]
        orders_n = ord_by_cat[cat_id]
        sess = sess_by_cat[cat_id]
        aov = rev / orders_n if orders_n else 0.0
        cvr = orders_n / sess if sess else 0.0
        roas = paid_rev_by_cat[cat_id] / spend_by_cat[cat_id] if spend_by_cat[cat_id] else 0.0
        print(f"{CATEGORY_NAMES[cat_id]:<14}{sess:>12,}{orders_n:>10,}"
              f"{rev:>14,.0f}{aov:>9.2f}{cvr*100:>7.2f}%{roas:>10.2f}x")

    total_rev = sum(rev_by_cat.values())
    print(f"{'TOTAL':<14}{sum(sess_by_cat.values()):>12,}"
          f"{sum(ord_by_cat.values()):>10,}{total_rev:>14,.0f}")

    beauty_target_td = TARGET_TO_DATE[1]["revenue"]
    gap = rev_by_cat[1] - beauty_target_td
    print(f"\nBeauty vs target-to-date: {rev_by_cat[1]:,.0f} vs {beauty_target_td:,.0f}"
          f"  ->  {gap:,.0f} ({gap / beauty_target_td * 100:+.1f}%)")

    oos = out["oos_interactions"]
    gross_demand = sum(r["pot_val"] for r in oos)
    print(f"\nStockout: {len(oos):,} blocked interactions, "
          f"{gross_demand:,.0f} EUR GROSS unrealised demand.")
    print(f"  (Net loss requires the substitution rate; summing pot_val "
          f"overstates it by roughly {1 / (1 - SUBSTITUTION_RATE):.1f}x before "
          f"conversion propensity is even applied.)")

    recs = out["catalog_recommender_logs"]
    mismatched = [r for r in recs if r["cat_mismatch_flg"] == 1]
    bounced = [r for r in mismatched if r["user_action"] == "BOUNCED"]
    print(f"Recommender: {len(recs):,} impressions, {len(mismatched):,} "
          f"cross-department, {len(bounced):,} ended the session.")
    print("=" * 78)


def generate_all_data(skip_load=False, seed=42):
    print("=" * 78)
    print("LUMIERESHOP BLACK WEEK 2026 - CAUSAL SIMULATION")
    print(f"Project {PROJECT_ID} | dataset {DATASET_ID}")
    print(f"Plan window  : {SIMULATION_START:%Y-%m-%d %H:%M} -> {PLAN_END:%Y-%m-%d %H:%M} UTC")
    print(f"Clock        : {CURRENT_TIME:%Y-%m-%d %H:%M} UTC (actuals stop here)")
    print("=" * 78 + "\n")

    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed + 1)

    # 1. Run the causal model.
    plan, ctx = run_simulation(calibrate_only=False, seed=seed)

    # 2. Supporting entities first: order lines reference inventory batches.
    (distribution_centers, inventory_items, inventory_snapshots,
     users, inv_by_product) = build_supporting_entities(ctx["products"], rng, np_rng)
    ctx["inv_by_product"] = inv_by_product
    # web_sessions.country is DERIVED from the visitor's customer record rather
    # than drawn, so it costs no random numbers and can never contradict
    # users.country or the country on the payment gateway log.
    ctx["user_country"] = {u["user_id"]: u["country"] for u in users}

    # 3. Materialise the clickstream, orders and incident logs.
    out = materialise(plan, ctx, seed=seed)
    telemetry = out["telemetry"]

    # 4. Close the loop: fill realised conversions into the ad performance
    #    table and derive the bidding engine's decision log from what happened.
    cat_by_campaign = {c["campaign_id"]: cat for cat, c in CAMPAIGNS.items()}
    spend_by_cat_day = defaultdict(float)
    for row in ctx["perf_rows"]:
        cat_id = cat_by_campaign[row["cid_ref"]]
        day_idx = (datetime.strptime(row["date"], "%Y-%m-%d").date()
                   - SIMULATION_START.date()).days
        spend_by_cat_day[(cat_id, day_idx)] += float(row["spend"])
        row["conversions"] = int(telemetry["paid_orders"].get((cat_id, day_idx), 0))

    ad_bidding_log = build_bidding_log(telemetry, spend_by_cat_day,
                                       ctx["target_roas_by_cat"])
    print(f"  Bidding log: {len(ad_bidding_log)} evaluations.")
    for cat_id in sorted(CATEGORY_NAMES):
        cid = CAMPAIGNS[cat_id]["campaign_id"]
        seq = [r for r in ad_bidding_log
               if r["campaign_id"] == cid and r["logged_at"] >= "2026-11-23"]
        marks = "".join("X" if r["status_change"] == "TARGET_ROAS_BREACH_THROTTLED"
                        else ("c" if r["status_change"] == "BUDGET_CONSTRAINED" else ".")
                        for r in seq)
        ratios = " ".join(f"{r['target_roas_multiplier']:.2f}" for r in seq)
        print(f"    {CATEGORY_NAMES[cat_id]:<12} {marks:<8}  roas ratio: {ratios}")
    print("    (X = ROAS breach and cap applied, c = cap maintained, . = normal)")

    # 5. Commercial plan and the surrounding operational tables.
    print("Building commercial targets ...")
    weekly, daily, intraday = build_targets(ctx["observed_fraction"])
    peripheral = build_peripheral_tables(ctx["products"], users, out["orders"],
                                         out["session_count"], rng, np_rng)

    report_outcome(out, ctx, spend_by_cat_day)

    memory_tables = {
        "categories": ctx["categories"],
        "products": ctx["products"],
        "distribution_centers": distribution_centers,
        "inventory_items": inventory_items,
        "inventory_snapshots": inventory_snapshots,
        "users": users,
        "orders": out["orders"],
        "order_items": out["order_items"],
        "sales_event_stream": out["sales_event_stream"],
        "weekly_commercial_targets": weekly,
        "daily_category_targets": daily,
        "category_15min_targets": intraday,
        "oos_interactions": out["oos_interactions"],
        "catalog_recommender_logs": out["catalog_recommender_logs"],
        "daily_ad_performance": ctx["perf_rows"],
        "ad_bidding_log": ad_bidding_log,
    }
    memory_tables.update(peripheral)

    if skip_load:
        print("\n--skip-load: writing row counts only, nothing sent to BigQuery.\n")
        for name, rows in sorted(memory_tables.items()):
            print(f"  {name:<32}{len(rows):>12,} rows")
        for name, path in (("web_sessions", out["sessions_path"]),
                           ("web_events", out["events_path"])):
            opener = gzip.open if path.endswith(".gz") else open
            with opener(path, "rt", encoding="utf-8") as fh:
                n = sum(1 for _ in fh)
            print(f"  {name:<32}{n:>12,} rows  ({path})")
        print(f"\nStaged files left in {out['temp_dir']}")
        return

    client = get_bigquery_client(PROJECT_ID)
    print("\nLoading in-memory tables into BigQuery ...")
    failures = []
    for name, rows in memory_tables.items():
        table_ref = f"{PROJECT_ID}.{DATASET_ID}.{name}"
        # CRITICAL: pass the destination schema explicitly.
        #
        # `load_table_from_json()` with no schema makes the client enable
        # autodetect, and WRITE_TRUNCATE then REPLACES the table schema with the
        # inferred one. That silently destroys every column description applied
        # earlier in the pipeline - it wiped all 23 core tables on the
        # 2026-09-11 rebuild while leaving the 114 extended tables intact,
        # because those load through a different code path.
        #
        # Supplying the schema also means a mismatch between the generator and
        # `01_create_schema.py` fails the load loudly instead of quietly
        # reshaping the warehouse.
        try:
            job_config = bigquery.LoadJobConfig(
                write_disposition="WRITE_TRUNCATE",
                schema=client.get_table(table_ref).schema,
            )
        except Exception as exc:
            failures.append(name)
            print(f"  FAILED `{name}`: could not read destination schema: {exc}",
                  file=sys.stderr)
            continue
        try:
            job = client.load_table_from_json(rows, table_ref, job_config=job_config)
            job.result()
            print(f"  Loaded {len(rows):>10,} rows into `{name}`.")
        except Exception as exc:
            failures.append(name)
            print(f"  FAILED `{name}`: {exc}", file=sys.stderr)

    print("\nLoading clickstream tables from disk ...")
    try:
        load_ndjson_file_to_bq(client, "web_sessions", out["sessions_path"])
        load_ndjson_file_to_bq(client, "web_events", out["events_path"])
    except Exception as exc:
        failures.append("web_sessions/web_events")
        print(f"  FAILED clickstream load: {exc}", file=sys.stderr)
    finally:
        shutil.rmtree(out["temp_dir"], ignore_errors=True)

    print("\n" + "=" * 78)
    if failures:
        print(f"COMPLETED WITH {len(failures)} FAILURE(S): {', '.join(failures)}")
        print("=" * 78)
        # Exit non-zero so the bootstrap ABORTS here.
        #
        # This previously returned 0. On the 2026-09-11 rebuild the clickstream
        # load failed, `web_sessions` and `web_events` were left empty, and the
        # pipeline happily went on to build the glossary, the isolation datasets
        # and all four data agents on top of a warehouse with no traffic data.
        # A partial load must never look like success.
        sys.exit(1)
    print("DATA GENERATION AND LOAD COMPLETED SUCCESSFULLY")
    print("=" * 78)


def main():
    parser = argparse.ArgumentParser(
        description="Generate the LumiereShop Black Week 2026 dataset.")
    parser.add_argument("--calibrate", action="store_true",
                        help="Fast aggregate KPI check. Writes nothing.")
    parser.add_argument("--skip-load", action="store_true",
                        help="Generate all rows but do not upload to BigQuery.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    args = parser.parse_args()

    if args.calibrate:
        run_simulation(calibrate_only=True, seed=args.seed)
        return

    if not PROJECT_ID and not args.skip_load:
        print("GCP_PROJECT_ID is not set in .env - refusing to run.", file=sys.stderr)
        sys.exit(1)

    generate_all_data(skip_load=args.skip_load, seed=args.seed)


if __name__ == "__main__":
    main()
