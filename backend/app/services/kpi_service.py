"""
LumièreShop KPI Service
=======================
Serves the headline Black Week figures the web interface displays, measured
live from BigQuery rather than typed into the page.

Why this service exists
-----------------------
The storewide target, actual and shortfall were previously hardcoded in at
least eight places inside `backend/static/index.html`, across two languages.
They had already drifted: the English strings said €731.4k while the Dutch
strings said €735,7k, with a different target and actual to match. The same
class of defect put a stale three-way root-cause split into the exported
summary report, ranking stockouts as the primary driver when the case study
says ad throttling dominates.

A displayed figure that is typed by hand is a figure that will eventually
disagree with the warehouse. Everything below is therefore derived from the
same queries the offline measurement scripts use.

Caching
-------
The warehouse is a frozen simulation snapshot, so the numbers cannot change
between requests. The result is computed once and held for the process
lifetime; `refresh()` forces a re-measure if that is ever needed.
"""

import logging
import threading
from typing import Optional

from google.cloud import bigquery

from app.config import PROJECT_ID, DATASET_ID

logger = logging.getLogger(__name__)

# The simulation is frozen mid-morning on Friday 27 November 2026, so every
# "to date" figure stops at the cutoff and is compared against a pro-rated plan.
CUTOFF = "2026-11-27 14:30:00"
WINDOW_START = "2026-11-23"
LAST_PARTIAL_DAY = "2026-11-27"
BEAUTY_CATEGORY_ID = 1

# Paid channel convention, matching the business glossary term `paid_cvr` and
# scripts/test/measure_shortfall_allocation.py.
PAID_CHANNELS = "('Paid Search','Paid Social')"

_CACHE: Optional[dict] = None
_LOCK = threading.Lock()


def _fq() -> str:
    return f"`{PROJECT_ID}.{DATASET_ID}`"


def _client() -> bigquery.Client:
    from app.services.ca_service import get_bigquery_client
    return get_bigquery_client()


def _pacing_sql() -> str:
    """Actual vs pro-rated plan revenue, storewide and for Beauty.

    The plan is held at 15-minute granularity, so the final partial day is
    truncated at the cutoff rather than counted whole. Comparing a part-week
    actual against a whole-week target is the single most common way to get
    this number badly wrong.
    """
    return f"""
    WITH actual AS (
      SELECT s.primary_category_id AS category_id,
             SUM(o.total_amount)   AS revenue
      FROM {_fq()}.orders o
      JOIN {_fq()}.web_sessions s ON s.session_id = o.session_id
      WHERE o.created_at >= TIMESTAMP '{WINDOW_START}'
        AND o.created_at <  TIMESTAMP '{CUTOFF}'
      GROUP BY category_id
    ),
    plan AS (
      SELECT t.category_id,
             SUM(IF(d < DATE '{LAST_PARTIAL_DAY}' OR t.time_bucket < TIME '14:30:00',
                    t.target_revenue, 0)) AS plan_revenue
      FROM UNNEST(GENERATE_DATE_ARRAY(DATE '{WINDOW_START}',
                                      DATE '{LAST_PARTIAL_DAY}')) AS d
      JOIN {_fq()}.category_15min_targets t
        ON t.day_of_week = EXTRACT(DAYOFWEEK FROM d)
      GROUP BY t.category_id
    )
    SELECT p.category_id,
           p.plan_revenue,
           COALESCE(a.revenue, 0) AS revenue
    FROM plan p
    LEFT JOIN actual a ON a.category_id = p.category_id
    """


def _allocation_sql() -> str:
    """The inputs to the certified three-way split of the Beauty deficit.

    Mirrors scripts/test/measure_shortfall_allocation.compute_allocation().
    Returned as a single row so the whole panel costs one query.
    """
    return f"""
    WITH oos AS (
      SELECT SUM(o.pot_val) AS gross_pot_val
      FROM {_fq()}.oos_interactions o
      JOIN {_fq()}.products p ON p.product_id = o.art_code
      WHERE p.category_id = {BEAUTY_CATEGORY_ID}
    ),
    rec AS (
      SELECT COUNTIF(r.cat_mismatch_flg = 1
                     AND r.user_action = 'BOUNCED') AS bounced
      FROM {_fq()}.catalog_recommender_logs r
      JOIN {_fq()}.products p ON p.product_id = r.src_sku
      WHERE p.category_id = {BEAUTY_CATEGORY_ID}
    ),
    sess AS (
      SELECT COUNT(*) AS sessions,
             COUNTIF(traffic_source IN {PAID_CHANNELS}) AS paid_sessions,
             COUNTIF(converted_to_order) AS conversions,
             COUNTIF(converted_to_order
                     AND traffic_source IN {PAID_CHANNELS}) AS paid_conversions
      FROM {_fq()}.web_sessions
      WHERE primary_category_id = {BEAUTY_CATEGORY_ID}
        AND session_started_at >= TIMESTAMP '{WINDOW_START}'
        AND session_started_at <  TIMESTAMP '{CUTOFF}'
    ),
    aov AS (
      SELECT AVG(o.total_amount) AS aov
      FROM {_fq()}.orders o
      JOIN {_fq()}.web_sessions s ON s.session_id = o.session_id
      WHERE s.primary_category_id = {BEAUTY_CATEGORY_ID}
        AND o.created_at >= TIMESTAMP '{WINDOW_START}'
        AND o.created_at <  TIMESTAMP '{CUTOFF}'
    )
    SELECT oos.gross_pot_val, rec.bounced, aov.aov,
           sess.sessions, sess.paid_sessions,
           sess.conversions, sess.paid_conversions
    FROM oos, rec, aov, sess
    """


def _measure() -> dict:
    client = _client()

    pacing = {int(r["category_id"]): r for r in
              [dict(x.items()) for x in client.query(_pacing_sql()).result()]}

    store_plan = sum(float(r["plan_revenue"] or 0) for r in pacing.values())
    store_actual = sum(float(r["revenue"] or 0) for r in pacing.values())

    beauty = pacing.get(BEAUTY_CATEGORY_ID, {})
    beauty_plan = float(beauty.get("plan_revenue") or 0)
    beauty_actual = float(beauty.get("revenue") or 0)
    beauty_deficit = beauty_plan - beauty_actual

    a = dict(next(iter(client.query(_allocation_sql()).result())).items())
    gross = float(a["gross_pot_val"] or 0)
    bounced = int(a["bounced"] or 0)
    aov = float(a["aov"] or 0)
    paid_cvr = (a["paid_conversions"] / a["paid_sessions"]) if a["paid_sessions"] else 0.0
    all_cvr = (a["conversions"] / a["sessions"]) if a["sessions"] else 0.0

    # Certified conventions, defined in the business glossary. The stockout uses
    # the PAID rate (that demand was bought through acquisition campaigns); the
    # recommender uses the ALL-CHANNEL rate (a shopper reaching the widget is
    # already on site). Ad throttling is the RESIDUAL, because the traffic
    # collapse overlaps the on-site frictions that triggered it.
    stockout = gross * paid_cvr
    recommender = bounced * all_cvr * aov
    throttling = beauty_deficit - stockout - recommender

    def share(x):
        return (100.0 * x / beauty_deficit) if beauty_deficit else 0.0

    return {
        "as_of": "2026-11-27T14:30:00Z",
        "storewide": {
            "target": round(store_plan, 2),
            "actual": round(store_actual, 2),
            "variance": round(store_actual - store_plan, 2),
            "variance_pct": round(100.0 * (store_actual - store_plan) / store_plan, 2)
            if store_plan else 0.0,
        },
        "beauty": {
            "target": round(beauty_plan, 2),
            "actual": round(beauty_actual, 2),
            "variance": round(beauty_actual - beauty_plan, 2),
            "variance_pct": round(100.0 * (beauty_actual - beauty_plan) / beauty_plan, 2)
            if beauty_plan else 0.0,
            "deficit": round(beauty_deficit, 2),
        },
        "drivers": [
            {"key": "ad_throttling", "value": round(throttling, 2),
             "share_pct": round(share(throttling), 1), "basis": "residual"},
            {"key": "stockout", "value": round(stockout, 2),
             "share_pct": round(share(stockout), 1),
             "basis": "gross attempted value x paid conversion rate"},
            {"key": "recommender", "value": round(recommender, 2),
             "share_pct": round(share(recommender), 1),
             "basis": "bounced mismatched impressions x conversion rate x AOV"},
        ],
        "inputs": {
            "gross_pot_val": round(gross, 2),
            "bounced_impressions": bounced,
            "paid_cvr_pct": round(100.0 * paid_cvr, 3),
            "allchannel_cvr_pct": round(100.0 * all_cvr, 3),
            "aov": round(aov, 2),
        },
    }


def get_kpi_summary(force_refresh: bool = False) -> dict:
    """Return the measured KPI summary, computing it at most once per process."""
    global _CACHE
    if _CACHE is not None and not force_refresh:
        return _CACHE
    with _LOCK:
        if _CACHE is not None and not force_refresh:
            return _CACHE
        logger.info("Measuring Black Week KPI summary from BigQuery...")
        _CACHE = _measure()
        logger.info("KPI summary cached: storewide variance %.2f, Beauty deficit %.2f",
                    _CACHE["storewide"]["variance"], _CACHE["beauty"]["deficit"])
        return _CACHE


def refresh() -> dict:
    return get_kpi_summary(force_refresh=True)
