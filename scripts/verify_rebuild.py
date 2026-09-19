#!/usr/bin/env python3
"""
Post-rebuild verification against live BigQuery.

Checks the invariants that the demo depends on and that nothing else verifies
end to end. Read-only: issues SELECT queries and reads table metadata, and
writes nothing.

What it checks
--------------
  1. SPEC INVARIANTS   - the hard ratios in TECHNICAL_SPECIFICATION.md section 3.2
                         and the zero-post-cutoff rule in section 3.1
  2. TIER PARITY       - the three datasets hold identical row counts, so any
                         difference in agent behaviour is attributable to
                         metadata and not to the data
  3. TIER METADATA     - Tier A carries full descriptions, Tier B thin ones,
                         Tier C none. This is the experiment's independent
                         variable and it must be demonstrably true.
  4. NARRATIVE FACTS   - the incident is actually present in the data

Usage
-----
  python3 scripts/verify_rebuild.py             # exits non-zero on any failure
  python3 scripts/verify_rebuild.py --lenient   # report only, always exit 0
"""

import argparse
import os
import sys

from google.cloud import bigquery


def load_dotenv():
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("'\""))


load_dotenv()

PROJECT = os.environ.get("GCP_PROJECT_ID", "")
DATASET = os.environ.get("BQ_DATASET_ID", "ecommerce_dw")
LOCATION = os.environ.get("BQ_LOCATION", "europe-west4")
TIERS = [DATASET, f"{DATASET}_2nd", f"{DATASET}_3rd"]

CUTOFF = "2026-11-27 14:30:00 UTC"
# Same instant, in a form BigQuery's TIMESTAMP() will parse.
CUTOFF_TS = "2026-11-27 14:30:00"

results = []


def check(name, ok, detail):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}\n         {detail}")


def scalar(client, sql):
    return list(client.query(sql, location=LOCATION).result())[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lenient", action="store_true",
                        help="Report failures but always exit 0.")
    args = parser.parse_args()

    if not PROJECT:
        print("GCP_PROJECT_ID is not set in .env", file=sys.stderr)
        sys.exit(1)

    import subprocess
    from google.oauth2 import credentials as oauth2_credentials
    token = None
    for cmd in ["/google/data/ro/teams/cloud-sdk/gcloud", "gcloud"]:
        try:
            res = subprocess.run([cmd, "auth", "print-access-token"], capture_output=True, text=True, timeout=10)
            if res.returncode == 0 and res.stdout.strip():
                token = res.stdout.strip()
                break
        except Exception:
            continue
    client = bigquery.Client(project=PROJECT, credentials=oauth2_credentials.Credentials(token)) if token else bigquery.Client(project=PROJECT)
    fq = f"`{PROJECT}.{DATASET}`"

    print("=" * 78)
    print("POST-REBUILD VERIFICATION")
    print("=" * 78)
    print(f"Project : {PROJECT}")
    print(f"Dataset : {DATASET}  (+ _2nd, _3rd)")

    # ---- 1. Spec invariants ------------------------------------------------
    print("\n1. TECHNICAL_SPECIFICATION invariants")

    # ------------------------------------------------------------------
    # These ratios are scoped to the Black Week simulation window.
    #
    # HISTORY: `14_generate_historical_data.py` used to append ~64k historical
    # orders with NO historical `web_sessions` or `web_events` at all, so a
    # warehouse-wide conversion rate divided two different populations and read
    # a meaningless ~5.9%. It now generates the matching clickstream, with
    # session counts derived from those same orders, so the warehouse-wide
    # figure is finally sound.
    #
    # These checks stay scoped to Black Week regardless, because
    # TECHNICAL_SPECIFICATION section 3.2 states its targets for that window.
    # Widening them would compare against the wrong benchmark.
    # ------------------------------------------------------------------
    BW_START = "2026-11-23"

    # ------------------------------------------------------------------
    # What counts as a real, placed order.
    #
    # `order_status` used to hold the single value 'Completed', so these
    # checks simply filtered on it. It is now DERIVED from the per-line
    # returns, giving 'Completed', 'Returned' and 'Partially Returned'. All
    # three are genuinely placed, paid-for orders - a return happens days
    # AFTER the order converts, so excluding them would understate the
    # conversion rate and overstate payment-gateway coverage.
    #
    # Filtering on the set rather than dropping the WHERE clause keeps the
    # check honest if a non-converting status (e.g. 'Payment Failed') is ever
    # introduced. That option was considered and deferred; see BACKLOG.md.
    # ------------------------------------------------------------------
    PLACED = "order_status IN ('Completed', 'Returned', 'Partially Returned')"

    row = scalar(client, f"""
        SELECT
          (SELECT COUNT(*) FROM {fq}.orders
             WHERE {PLACED} AND created_at >= '{BW_START}') AS orders,
          (SELECT COUNT(*) FROM {fq}.web_sessions
             WHERE session_started_at >= '{BW_START}')                        AS sessions,
          (SELECT COUNT(*) FROM {fq}.web_events
             WHERE created_at >= '{BW_START}')                                AS events
    """)
    cvr = row.orders / row.sessions * 100 if row.sessions else 0
    check("Sitewide CVR within 2.8-3.2% (Black Week)", 2.8 <= cvr <= 3.2,
          f"{cvr:.2f}%  ({row.orders:,} orders / {row.sessions:,} sessions)")

    eps = row.events / row.sessions if row.sessions else 0
    check("Events per session within 15-25 (Black Week)", 15.0 <= eps <= 25.0,
          f"{eps:.2f}  ({row.events:,} events)")

    # Payment coverage is checked BOTH warehouse-wide and for Black Week.
    # History now mirrors the Black Week gateway profile, so a divergence
    # between the two means the historical generator has drifted again.
    row = scalar(client, f"""
        SELECT
          (SELECT COUNT(*) FROM {fq}.payment_gateway_logs
             WHERE status = 'SUCCESS')                                         AS ok_logs,
          (SELECT COUNT(*) FROM {fq}.orders
             WHERE {PLACED})                                                   AS orders,
          (SELECT COUNT(*) FROM {fq}.payment_gateway_logs
             WHERE status = 'SUCCESS' AND created_at >= '{BW_START}')          AS ok_logs_bw,
          (SELECT COUNT(*) FROM {fq}.orders
             WHERE {PLACED} AND created_at >= '{BW_START}')                    AS orders_bw
    """)
    cov = row.ok_logs / row.orders if row.orders else 0
    check("Payment gateway coverage within 0.90-0.95 (warehouse-wide)", 0.90 <= cov <= 0.95,
          f"{cov:.3f}  ({row.ok_logs:,} successful logs / {row.orders:,} orders)")

    cov_bw = row.ok_logs_bw / row.orders_bw if row.orders_bw else 0
    check("Payment gateway coverage within 0.90-0.95 (Black Week)", 0.90 <= cov_bw <= 0.95,
          f"{cov_bw:.3f}  ({row.ok_logs_bw:,} successful logs / {row.orders_bw:,} orders)")

    # ------------------------------------------------------------------
    # order_status must not be degenerate.
    #
    # It held the single value 'Completed' for every one of 128,997 rows. The
    # column looked populated, so nothing flagged it, and all three agent tiers
    # read it and concluded that orders never went wrong. A count alone would
    # not have caught that - only looking at DISTINCT values does.
    # ------------------------------------------------------------------
    rows = list(client.query(f"""
        SELECT order_status, COUNT(*) AS n
        FROM {fq}.orders GROUP BY order_status ORDER BY n DESC
    """).result())
    seen = {r.order_status: r.n for r in rows}
    total = sum(seen.values())
    expected = {"Completed", "Partially Returned", "Returned"}

    check("order_status holds all three placed-order values",
          set(seen) == expected,
          " | ".join(f"{s} {n:,} ({n/max(total,1):.1%})" for s, n in seen.items()))

    # Roughly 5% of LINES are returned and orders average about 1.65 lines, so
    # 'Completed' should land near 92%. A wide band is deliberate - this is a
    # guard against degeneracy, not a re-statement of the return rate.
    completed_share = seen.get("Completed", 0) / max(total, 1)
    check("Completed share within 85-96%", 0.85 <= completed_share <= 0.96,
          f"{completed_share:.1%}")

    # The strong check: the status on `orders` must agree with the per-line
    # `returned_at` dates on `order_items`. These are two different tables
    # written from the same rolls, so any disagreement means the derivation was
    # bypassed, duplicated, or has drifted between the two generators.
    row = scalar(client, f"""
        WITH per_order AS (
          SELECT oi.ord_hdr_num AS order_id,
                 COUNT(*) AS lines,
                 COUNTIF(oi.returned_at IS NOT NULL) AS returned_lines
          FROM {fq}.order_items oi
          GROUP BY order_id
        )
        SELECT COUNTIF(o.order_status != CASE
                 WHEN p.returned_lines = 0          THEN 'Completed'
                 WHEN p.returned_lines = p.lines    THEN 'Returned'
                 ELSE 'Partially Returned' END) AS mismatched,
               COUNT(*) AS checked
        FROM per_order p
        JOIN {fq}.orders o ON o.order_id = p.order_id
    """)
    check("order_status agrees with order_items.returned_at on every order",
          row.mismatched == 0,
          f"{row.mismatched:,} mismatched of {row.checked:,} checked")

    # Sweep EVERY timestamp column in the dataset, not just orders and
    # web_events. An earlier version of this check looked at those two tables
    # only and reported a clean bill of health while 38 other columns held
    # records dated as far ahead as 2027 -- the generators laid rows out at a
    # fixed cadence without scaling it to the length of the simulation window.
    #
    # A handful of columns are forward-looking by definition: they record how
    # long an entitlement stays valid rather than something already observed,
    # so a future value is correct and they are exempt.
    exempt = {
        ("store_credit_issuances", "expires_at"),
        ("discount_coupons_master", "valid_to"),
        ("gift_card_transactions", "expires_at"),
    }
    probes = []
    schema_rows = list(client.query(f"""
        SELECT table_name, column_name, data_type, description
        FROM {fq}.INFORMATION_SCHEMA.COLUMN_FIELD_PATHS
        WHERE field_path = column_name
    """, location=LOCATION).result())
    for r in schema_rows:
        if r.data_type not in ("TIMESTAMP", "DATETIME"):
            continue
        if (r.table_name, r.column_name) in exempt:
            continue
        probes.append(
            f"SELECT '{r.table_name}.{r.column_name}' AS col, "
            f"COUNTIF({r.column_name} > TIMESTAMP('{CUTOFF_TS}')) AS n "
            f"FROM `{PROJECT}.{DATASET}.{r.table_name}`")

    late = []
    if probes:
        query = ("SELECT col, n FROM (" + " UNION ALL ".join(probes)
                 + ") WHERE n > 0 ORDER BY n DESC")
        late = [(r.col, r.n) for r in client.query(query, location=LOCATION).result()]

    total_bad = sum(n for _, n in late)
    detail = f"swept {len(probes)} timestamp columns"
    if late:
        worst = ", ".join(f"{col}={n:,}" for col, n in late[:5])
        detail += (f"; {len(late)} LEAKING, {total_bad:,} rows past {CUTOFF_TS}"
                   f"  (worst: {worst})")
    check("Zero post-cutoff records (all timestamp columns)", not late, detail)

    # ---- 2. Historical continuity -----------------------------------------
    #
    # History and Black Week are produced by two DIFFERENT scripts writing to
    # the SAME tables. Every check here exists because a divergence between
    # them is invisible in row counts but loud in the data.
    #
    # The precedent: historical payment logs were once 100% successful, which
    # made Black Week's ordinary ~7% failure rate look like a gateway outage -
    # a false root cause that every agent tier could "discover", competing with
    # the three real ones.
    # ------------------------------------------------------------------
    print("\n2. Historical continuity (the six weeks before Black Week)")

    row = scalar(client, f"""
        SELECT
          (SELECT COUNT(*) FROM {fq}.web_sessions
             WHERE session_started_at < '{BW_START}')                          AS hist_sessions,
          (SELECT COUNT(*) FROM {fq}.web_events
             WHERE created_at < '{BW_START}')                                  AS hist_events,
          (SELECT COUNT(*) FROM {fq}.orders
             WHERE {PLACED} AND created_at < '{BW_START}')                     AS hist_orders
    """)
    check("History has its own clickstream, not just orders",
          row.hist_sessions > 0 and row.hist_events > 0,
          f"{row.hist_sessions:,} sessions | {row.hist_events:,} events | "
          f"{row.hist_orders:,} orders")

    hist_cvr = row.hist_orders / row.hist_sessions * 100 if row.hist_sessions else 0
    check("Historical CVR within 2.0-4.5%", 2.0 <= hist_cvr <= 4.5,
          f"{hist_cvr:.2f}%  (a pre-promotional period converts a little "
          f"differently from Black Week, but not by an order of magnitude)")

    hist_eps = row.hist_events / row.hist_sessions if row.hist_sessions else 0
    check("Historical events per session within 15-25", 15.0 <= hist_eps <= 25.0,
          f"{hist_eps:.2f}  (same band as Black Week, so web_events shows no "
          f"step change on 23 November)")

    # The three columns added in this release. They are loaded with
    # ignore_unknown_values=True, so a mistyped name would be discarded in
    # silence and leave the column wholly NULL.
    row = scalar(client, f"""
        SELECT COUNT(*) AS n,
               COUNTIF(country IS NULL)                      AS no_country,
               COUNTIF(session_ended_at IS NULL)             AS no_end,
               COUNTIF(page_views_count IS NULL)             AS no_pv,
               COUNTIF(page_views_count <= 0)                AS zero_pv,
               COUNTIF(session_ended_at < session_started_at) AS backwards
        FROM {fq}.web_sessions
    """)
    check("New web_sessions columns are populated on every row",
          row.no_country == 0 and row.no_end == 0 and row.no_pv == 0,
          f"{row.n:,} sessions | NULL country {row.no_country:,} | "
          f"NULL session_ended_at {row.no_end:,} | NULL page_views_count {row.no_pv:,}")

    check("page_views_count is positive and session_ended_at is not before the start",
          row.zero_pv == 0 and row.backwards == 0,
          f"{row.zero_pv:,} non-positive page views | {row.backwards:,} sessions "
          f"ending before they began")

    # page_views_count must be a genuine SUBSET of web_events, not a copy of
    # it. Five of the fourteen funnel steps are in-page interactions.
    row = scalar(client, f"""
        SELECT
          (SELECT SUM(page_views_count) FROM {fq}.web_sessions) AS pv,
          (SELECT COUNT(*) FROM {fq}.web_events)                AS ev
    """)
    ratio = row.pv / row.ev if row.ev else 0
    check("page_views_count is a strict subset of web_events (0.5-0.95)",
          0.5 <= ratio <= 0.95,
          f"{row.pv:,} page views / {row.ev:,} events = {ratio:.3f}")

    # Historical orders previously carried no session_id at all, so a
    # warehouse-wide orders -> web_sessions join silently dropped ~64,000 rows
    # while still returning a plausible-looking result.
    row = scalar(client, f"""
        SELECT COUNT(*) AS n,
               COUNTIF(o.session_id IS NULL) AS no_sid,
               COUNTIF(s.session_id IS NULL) AS unmatched
        FROM {fq}.orders o
        LEFT JOIN {fq}.web_sessions s USING (session_id)
    """)
    check("Every order joins to a real web_session",
          row.no_sid == 0 and row.unmatched == 0,
          f"{row.n:,} orders | {row.no_sid:,} without a session_id | "
          f"{row.unmatched:,} pointing at a session that does not exist")

    # Foreign keys silently dropped by the historical loader. `order_items`
    # uses the cryptic names `ord_hdr_num` and `mat_nr`; the historical
    # generator wrote `order_id` and `product_id`, and because the load runs
    # with ignore_unknown_values=True BigQuery discarded both without error.
    # 48% of the table had no order and no product, and nothing noticed.
    row = scalar(client, f"""
        SELECT COUNT(*) AS n,
               COUNTIF(oi.ord_hdr_num IS NULL) AS no_order,
               COUNTIF(oi.mat_nr IS NULL)      AS no_product,
               COUNTIF(o.order_id IS NULL)     AS unmatched_order,
               COUNTIF(p.product_id IS NULL)   AS unmatched_product
        FROM {fq}.order_items oi
        LEFT JOIN {fq}.orders o   ON o.order_id   = oi.ord_hdr_num
        LEFT JOIN {fq}.products p ON p.product_id = oi.mat_nr
    """)
    check("Every order_item resolves to a real order and a real product",
          row.no_order == 0 and row.no_product == 0
          and row.unmatched_order == 0 and row.unmatched_product == 0,
          f"{row.n:,} line items | NULL ord_hdr_num {row.no_order:,} | "
          f"NULL mat_nr {row.no_product:,} | orphaned order {row.unmatched_order:,} | "
          f"orphaned product {row.unmatched_product:,}")

    # Same failure mode: the column is `cid_ref`, not `campaign_id`.
    row = scalar(client, f"""
        SELECT COUNT(*) AS n,
               COUNTIF(d.cid_ref IS NULL)       AS no_camp,
               COUNTIF(m.campaign_id IS NULL)   AS unmatched
        FROM {fq}.daily_ad_performance d
        LEFT JOIN {fq}.marketing_campaigns m ON m.campaign_id = d.cid_ref
    """)
    check("Every ad-performance row resolves to a real campaign",
          row.no_camp == 0 and row.unmatched == 0,
          f"{row.n:,} rows | NULL cid_ref {row.no_camp:,} | "
          f"pointing at a campaign that does not exist {row.unmatched:,}")

    # The throttle must read as a value CHANGING, not as instrumentation
    # appearing. Historical rows left all five quantitative columns NULL, so
    # budget_multiplier only existed from 23 November onward. They also used
    # campaign ids 1-4, which exist in no campaign table.
    row = scalar(client, f"""
        SELECT COUNT(*) AS n,
               COUNTIF(b.budget_multiplier IS NULL)      AS no_budget,
               COUNTIF(b.observed_cvr_7d IS NULL)        AS no_cvr,
               COUNTIF(b.target_roas_multiplier IS NULL) AS no_roas,
               COUNTIF(b.logged_at < '{BW_START}')       AS historical,
               COUNTIF(m.campaign_id IS NULL)            AS unmatched
        FROM {fq}.ad_bidding_log b
        LEFT JOIN {fq}.marketing_campaigns m ON m.campaign_id = b.campaign_id
    """)
    check("Bidding log is quantified across the whole timeline, not just Black Week",
          row.no_budget == 0 and row.no_cvr == 0 and row.no_roas == 0
          and row.historical > 0 and row.unmatched == 0,
          f"{row.n} rows ({row.historical} before Black Week) | "
          f"NULL budget_multiplier {row.no_budget} | NULL observed_cvr_7d {row.no_cvr} | "
          f"NULL target_roas_multiplier {row.no_roas} | "
          f"pointing at a non-existent campaign {row.unmatched}")

    # One column, two vocabularies: Black Week wrote 'DACH' while history wrote
    # 'Central Europe (DACH)'. WHERE destination_region = 'DACH' therefore
    # dropped every historical row, and GROUP BY split one region into two.
    #
    # The original check looked for '(' or the word 'Europe'. That was fitted
    # to the one bad pair rather than to the defect, and it failed the wholly
    # legitimate region 'Southern Europe'. What actually characterises the bug
    # is CONTAINMENT - a long-form label that wraps the short one - so that is
    # what is tested now. The parenthesis test is kept because an annotated
    # label is never the intended vocabulary here.
    rows = list(client.query(f"""
        SELECT DISTINCT destination_region FROM {fq}.shipping_lead_times
    """).result())
    regions = sorted(r.destination_region for r in rows)
    split = [f"{a} wraps {b}" for a in regions for b in regions
             if a != b and b in a]
    split += [f"{r} is annotated" for r in regions if "(" in r]
    check("shipping_lead_times uses a single region vocabulary",
          not split, f"{regions}" + (f" | {'; '.join(split)}" if split else ""))

    # 'Frankfurt' named a distribution centre that exists nowhere in this
    # business; the five DCs are Paris Nord, Rotterdam Port Hub, Hamburg Sued,
    # Milano Est and Barcelona Zona Franca.
    row = scalar(client, f"""
        SELECT COUNTIF(zone_name LIKE '%Frankfurt%') AS n, COUNT(*) AS total
        FROM {fq}.warehouse_zones
    """)
    check("No warehouse zone names a non-existent distribution centre",
          row.n == 0, f"{row.n} of {row.total} zones mention Frankfurt")

    # ---- 3. Tier parity ----------------------------------------------------
    print("\n3. Tier row-count parity (the experiment's control)")
    probes = ["orders", "order_items", "web_sessions", "products",
              "daily_ad_performance", "oos_interactions", "catalog_recommender_logs"]
    mismatched = []
    for table in probes:
        counts = []
        for ds in TIERS:
            try:
                counts.append(scalar(client,
                    f"SELECT COUNT(*) AS n FROM `{PROJECT}.{ds}.{table}`").n)
            except Exception as exc:
                counts.append(f"ERR:{type(exc).__name__}")
        if len(set(counts)) != 1:
            mismatched.append((table, counts))
    check("All three datasets hold identical row counts", not mismatched,
          f"{len(probes)} tables probed"
          + ("" if not mismatched else f"  MISMATCH: {mismatched}"))

    # ---- 4. Tier metadata --------------------------------------------------
    print("\n4. Tier metadata differentiation (the independent variable)")
    coverage = {}
    for ds in TIERS:
        rows = list(client.query(f"""
            SELECT COUNT(*) AS total,
                   COUNTIF(description IS NOT NULL AND description != '') AS described,
                   COUNTIF(LENGTH(IFNULL(description, '')) > 60)          AS rich
            FROM `{PROJECT}.{ds}`.INFORMATION_SCHEMA.COLUMN_FIELD_PATHS
        """, location=LOCATION).result())[0]
        coverage[ds] = rows

    a, b, c = (coverage[t] for t in TIERS)
    check("Tier A columns are richly described",
          a.rich > 0 and a.described / a.total > 0.8,
          f"{a.described}/{a.total} described, {a.rich} long-form")
    check("Tier B is thin: described but almost no long-form text",
          b.described > 0 and b.rich <= max(2, int(0.02 * b.total)),
          f"{b.described}/{b.total} described, {b.rich} long-form")
    check("Tier C has no descriptions at all", c.described == 0,
          f"{c.described}/{c.total} described")

    # ---- 5. Narrative facts ------------------------------------------------
    print("\n5. Incident is present in the data")

    row = scalar(client, f"""
        SELECT COUNT(*) AS n,
               COUNTIF(status_change = 'TARGET_ROAS_BREACH_THROTTLED') AS breaches,
               COUNTIF(budget_multiplier < 1.0)                        AS throttled
        FROM {fq}.ad_bidding_log
    """)
    check("Bidding log records a ROAS breach and an active budget cap",
          row.breaches > 0 and row.throttled > 0,
          f"{row.n} rows, {row.breaches} breaches, {row.throttled} with budget_multiplier < 1")

    row = scalar(client, f"""
        SELECT COUNT(*) AS n, ROUND(SUM(pot_val), 2) AS gross
        FROM {fq}.oos_interactions
    """)
    check("Stockout interactions exist with gross demand recorded",
          row.n > 0 and row.gross > 0,
          f"{row.n:,} interactions, SUM(pot_val)={row.gross:,.2f} "
          f"(gross demand - must NOT be reported as the loss)")

    row = scalar(client, f"""
        SELECT COUNT(*) AS n,
               COUNTIF(cat_mismatch_flg = 1)                    AS mismatched,
               COUNTIF(cat_mismatch_flg = 1 AND fb_rule_id = 99) AS fallback
        FROM {fq}.catalog_recommender_logs
    """)
    check("Recommender mismatch present via the certified rule",
          row.fallback > 0,
          f"{row.n:,} impressions, {row.mismatched:,} mismatched, "
          f"{row.fallback:,} matching cat_mismatch_flg=1 AND fb_rule_id=99")

    row = scalar(client, f"""
        SELECT COUNTIF(discount_amount != 0) AS nonzero, COUNT(*) AS n
        FROM {fq}.order_items
    """)
    check("discount_amount is uniformly zero, as the glossary certifies",
          row.nonzero == 0, f"{row.nonzero} non-zero of {row.n:,} rows")

    # ---- description coverage ----------------------------------------------
    #
    # apply_bq_descriptions.py looks each column up by name and SKIPS anything
    # it cannot find. That is forgiving at runtime and invisible at review
    # time: a typo in a column name behaves exactly like a deliberate
    # omission. 33 such entries had accumulated - including the primary keys of
    # payment_gateway_logs and daily_ad_performance, and a `status` column on
    # marketing_campaigns documented as carrying THROTTLED that never existed -
    # while the real columns they were meant to describe sat undocumented.
    #
    # Both directions are gated, because either one alone can hide the fault.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import apply_bq_descriptions as abd  # noqa: E402  (import here: needs .env)

    described = {}
    for tname, meta in abd.TABLE_METADATA.items():
        described.setdefault(tname, set()).update(meta.get("columns") or {})
    for tname, cols in abd.COLUMN_DESCRIPTIONS.items():
        described.setdefault(tname, set()).update(cols)

    live_cols, empty_desc = {}, []
    for r in schema_rows:
        live_cols.setdefault(r.table_name, set()).add(r.column_name)
        if not r.description:
            empty_desc.append(f"{r.table_name}.{r.column_name}")

    dead = [f"{t}.{c}" for t, cols in described.items()
            for c in cols if c not in live_cols.get(t, set())]
    dead += [f"{t}.*" for t in described if t not in live_cols]
    undescribed = [f"{t}.{c}" for t, cols in live_cols.items()
                   for c in cols if c not in described.get(t, set())]

    check("Every description entry names a column that exists",
          not dead,
          f"{len(dead)} dead entries" + (f": {', '.join(sorted(dead)[:8])}"
                                         + (" ..." if len(dead) > 8 else "")
                                         if dead else ""))
    check("Every column in the warehouse carries a description",
          not empty_desc,
          f"{len(empty_desc)} blank of "
          f"{sum(len(c) for c in live_cols.values())}"
          + (f": {', '.join(sorted(empty_desc)[:8])}"
             + (" ..." if len(empty_desc) > 8 else "") if empty_desc else ""))
    check("Every column is accounted for in apply_bq_descriptions.py",
          not undescribed,
          f"{len(undescribed)} unaccounted"
          + (f": {', '.join(sorted(undescribed)[:8])}"
             + (" ..." if len(undescribed) > 8 else "") if undescribed else ""))

    # ---- summary -----------------------------------------------------------
    failed = [n for n, ok, _ in results if not ok]
    print("\n" + "=" * 78)
    print(f"Checks: {len(results)} | Passed: {len(results) - len(failed)} | Failed: {len(failed)}")
    if failed:
        print("FAILED:")
        for n in failed:
            print(f"   - {n}")
        print("RESULT: FAIL")
    else:
        print("RESULT: PASS - the rebuild is sound.")
    print("=" * 78)

    if failed and not args.lenient:
        sys.exit(1)


if __name__ == "__main__":
    main()
