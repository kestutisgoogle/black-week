#!/usr/bin/env python3
"""
Phase 6: Dynamic Knowledge Catalog Grounding for Gemini BigQuery Data Agents
===========================================================================
Executes live Knowledge Catalog Semantic Search against the 140-table warehouse
using business incident prompts, dynamically discovers the optimal table clusters,
and provisions/grounds the Google Cloud Data Agents with zero static bias.

Agents Provisioned & Grounded:
------------------------------
1. Primary Data Agent (`DATA_AGENT_ID`): Grounded via Knowledge Catalog search for the primary business inquiry.
2. Data Agent A (`DATA_AGENT_A_ID`): Grounded via Knowledge Catalog search for Prompt A.
3. Data Agent B (`DATA_AGENT_B_ID`): Grounded via Knowledge Catalog search for Prompt B.
4. Data Agent C (`DATA_AGENT_C_ID`): Grounded via Knowledge Catalog search for Prompt C.

Usage:
------
  python3 scripts/06_update_data_agent.py
"""

import os
import sys
import subprocess
import requests
import json
import time
from typing import List, Dict, Any


def load_dotenv():
    """Parses root-level .env file into os.environ."""
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
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
DATASET_2ND_ID = os.environ.get("BQ_DATASET_2ND_ID", f"{DATASET_ID}_2nd")
DATASET_3RD_ID = os.environ.get("BQ_DATASET_3RD_ID", f"{DATASET_ID}_3rd")
DATA_AGENT_ID = os.environ.get("DATA_AGENT_ID") or os.environ.get("CA_DATA_AGENT_ID", "gda-blackweek-primary")
DATA_AGENT_A_ID = os.environ.get("DATA_AGENT_A_ID", "gda-blackweek-a")
DATA_AGENT_B_ID = os.environ.get("DATA_AGENT_B_ID", "gda-blackweek-b")
DATA_AGENT_C_ID = os.environ.get("DATA_AGENT_C_ID", "gda-blackweek-c")

# ---------------------------------------------------------------------------
# The discovery prompt, the search logic and the grounding cap all live in ONE
# place now: backend/app/services/discovery_core.py.
#
# WHY THE IMPORT GYMNASTICS: this script runs standalone, outside the web
# application, but the shared module has to ship inside the container - the
# Dockerfile only copies `backend/`. So the module lives under `backend/app/`
# and this script puts `backend/` on its import path to reach it.
#
# `discovery_core` deliberately imports nothing from `app.config`, so importing
# it here does NOT drag in the web application's environment loader or collide
# with the .env parsing done above.
#
# WHAT WAS DELETED HERE, AND WHY
#
#   * `PROMPT` - a comma-separated list of business domains. It read like a
#     database query, not like a question a Chief Marketing Officer would type,
#     and it scored 6 of 11 on the main story. Replaced by the single
#     human-written sentence in discovery_core.DISCOVERY_PROMPT (11 of 11).
#
#   * `GLOSSARY_PROBES` - four extra hand-tuned searches. They lifted the
#     glossary term count from 17 to 30, but the demo's whole claim is that the
#     CMO types ONE question. Five searches hiding behind one typed sentence is
#     cheating, however good the numbers looked. One prompt now drives two
#     calls: one for tables, one for glossary terms.
#
#   * `MAX_GROUNDED_TABLES = 40` - now 48, and enforced in the shared module,
#     which also refuses outright above 50. See the CA_METADATA_CLIFF comment
#     there: above 50 tables the Conversational Analytics service silently
#     discards all Knowledge Catalog metadata.
# ---------------------------------------------------------------------------
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"
    ),
)
from app.services.discovery_core import (  # noqa: E402
    DISCOVERY_PROMPT,
    MAX_GROUNDED_TABLES,
    discover,
)

PROMPT = DISCOVERY_PROMPT

AGENTS_CONFIG = {
    "primary": {
        "env_key": "DATA_AGENT_ID",
        "agent_id": DATA_AGENT_ID,
        "display_name": "LumiereShop Primary Data Agent",
        "dataset_id": DATASET_ID,
        "tier": "Primary Single-Agent Workspace (ecommerce_dw)",
        "inject_glossary": True,
    },
    "agent_a": {
        "env_key": "DATA_AGENT_A_ID",
        "agent_id": DATA_AGENT_A_ID,
        "display_name": "LumiereShop Data Agent A (Full KC)",
        "dataset_id": DATASET_ID,
        "tier": "Tier A: Full Knowledge Catalog Grounding (ecommerce_dw)",
        "inject_glossary": True,
    },
    "agent_b": {
        "env_key": "DATA_AGENT_B_ID",
        "agent_id": DATA_AGENT_B_ID,
        "display_name": "LumiereShop Data Agent B (Descriptions Only)",
        "dataset_id": DATASET_2ND_ID,
        "tier": "Tier B: Isolated - Descriptions Only (ecommerce_dw_2nd)",
        "inject_glossary": False,
    },
    "agent_c": {
        "env_key": "DATA_AGENT_C_ID",
        "agent_id": DATA_AGENT_C_ID,
        "display_name": "LumiereShop Data Agent C (Raw Schema)",
        "dataset_id": DATASET_3RD_ID,
        "tier": "Tier C: Isolated - Raw Schema Only (ecommerce_dw_3rd)",
        "inject_glossary": False,
    },
}


def get_access_token():
    token = os.environ.get("GCP_ACCESS_TOKEN")
    if not token:
        gcloud_paths = ["/google/data/ro/teams/cloud-sdk/gcloud", "gcloud"]
        for gcloud_cmd in gcloud_paths:
            try:
                res = subprocess.run([gcloud_cmd, "auth", "print-access-token"], capture_output=True, text=True, timeout=10)
                if res.returncode == 0 and res.stdout.strip():
                    token = res.stdout.strip()
                    break
            except Exception:
                continue
    return token


# Knowledge Catalog search lives in backend/app/services/discovery_core.py.
#
# Two functions used to sit here - `search_knowledge_catalog_dynamic()` and
# `search_glossary_terms_dynamic()` - and the web app had a third, different
# implementation of the same idea. All three are gone. `discover()` from the
# shared module is now the only way either caller reaches the catalog, so the
# environment the setup script builds and the environment the live demo builds
# are guaranteed identical.


AGENT_SYSTEM_INSTRUCTION = (
    "Today is Friday, 27 November 2026. The current time is 14:30:00 UTC.\n"
    "This data warehouse is a point-in-time snapshot taken at that instant: "
    "no operational record exists after 2026-11-27 14:30:00 UTC.\n"
    "\n"
    "Resolve every relative time expression - \"now\", \"today\", \"so far\", "
    "\"the last hour\", \"this week\", \"yesterday\", \"week to date\" - against "
    "2026-11-27 14:30:00 UTC, never against the real-world clock.\n"
    "\n"
    "Never use CURRENT_DATE(), CURRENT_TIMESTAMP(), CURRENT_DATETIME() or NOW() "
    "in generated SQL. They resolve to the real-world date, which falls outside "
    "this data\'s range, so they silently match either every row or no rows. "
    "Always write explicit date and timestamp literals.\n"
    "\n"
    "When a question concerns one product category, every rate and ratio in your "
    "answer must be computed for that same category. Do not pair a category-level "
    "numerator with a site-level denominator, and do not substitute a sitewide "
    "rate for a category rate - the two differ materially and the error is "
    "silent.\n"
    "\n"
    "When a metric has more than one accepted convention - for example a rate "
    "restricted to paid sessions versus one covering all sessions - state which "
    "convention you used, and apply the same convention to both the figure and "
    "anything you compare it against."
)

CORE_INVESTIGATION_TABLES = [
    "categories", "products", "distribution_centers", "inventory_items", "inventory_snapshots",
    "users", "orders", "order_items", "sales_event_stream", "weekly_commercial_targets",
    "daily_category_targets", "category_15min_targets", "web_sessions", "web_events",
    "oos_interactions", "competitor_price_feed", "marketing_campaigns", "daily_ad_performance",
    "ad_bidding_log", "ad_creatives", "payment_gateway_logs", "influencer_campaigns",
    "catalog_recommender_logs", "shipping_lead_times", "competitor_promotions"
]

# ----------------------------------------------------------------------------
# DELETED 2026-09-13: `BENCHMARK_REQUIRED_TABLES`, the force-include list.
#
# It injected four tables into every tier's grounding regardless of whether
# semantic search had ranked them: `competitor_promotions`,
# `inventory_snapshots`, `distribution_centers`, `users`.
#
# The honest objection is obvious - a demo whose claim is "the catalog finds
# the right tables" should not be quietly topping up the catalog's answer with
# a hand-written list. It survived because nobody had established what the
# questions actually need.
#
# So that was measured. Mapping all 15 benchmark questions onto the certified
# SQL that grades them shows only THIRTEEN tables are load-bearing:
#
#     order_items, orders, products, categories, daily_category_targets,
#     web_sessions, oos_interactions, catalog_recommender_logs,
#     ad_bidding_log, daily_ad_performance, marketing_campaigns,
#     payment_gateway_logs, competitor_price_feed
#
# Against that list the force-include was pure theatre:
#   * `competitor_promotions` and `inventory_snapshots` - discovered on merit
#     since the cap was raised, so forcing them changed nothing.
#   * `distribution_centers` and `users` - needed by NO question whatsoever.
#     They were being forced in to satisfy a "curated 25" recall metric that
#     measured nothing anybody cared about.
#
# Deleting the list therefore costs zero questions. `CORE_INVESTIGATION_TABLES`
# above is retained, but ONLY as an advisory coverage report - it never alters
# what gets grounded.
# ----------------------------------------------------------------------------


def discover_warehouse_tables_fallback() -> List[str]:
    """
    Fallback for when Knowledge Catalog returns nothing, e.g. because the
    semantic index is still warming up after a cold start or a republish.

    ⚠️ THIS PATH IS NOT DYNAMIC DISCOVERY. It lists the dataset straight from
    BigQuery and filters against a hardcoded curated list. If it runs, the demo
    is grounded on a static list while still describing itself as
    catalog-driven, so the caller announces it loudly and records it in the
    run summary.

    The slice below was `[:25]`, a hardcoded number that predated
    MAX_GROUNDED_TABLES and silently contradicted it. It is now the same cap
    the main path uses. Note that this branch only runs when fewer than 15 of
    the curated tables exist at all, which would itself indicate a broken
    warehouse.
    """
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=PROJECT_ID)
        tables = [t.table_id for t in client.list_tables(DATASET_ID)]
        if tables:
            core_present = [t for t in CORE_INVESTIGATION_TABLES if t in tables]
            if len(core_present) >= 15:
                return core_present
            return tables[:MAX_GROUNDED_TABLES]
    except Exception as e:
        print(f"  Notice: BigQuery warehouse table listing: {e}")
    return CORE_INVESTIGATION_TABLES


def provision_or_update_data_agent(
    agent_id: str,
    display_name: str,
    description: str,
    tables: List[str],
    headers: Dict[str, str],
    target_dataset: str = DATASET_ID,
    glossary_terms: List[Dict[str, str]] = None,
) -> tuple:
    """
    Idempotently creates or updates a BigQuery Data Agent in Google Cloud with dynamically discovered tables.
    Returns (success: bool, active_agent_id: str).
    """
    table_refs = [
        {"projectId": PROJECT_ID, "datasetId": target_dataset, "tableId": t_name}
        for t_name in sorted(set(tables))
    ]

    agent_url = f"https://geminidataanalytics.googleapis.com/v1beta/projects/{PROJECT_ID}/locations/global/dataAgents/{agent_id}"
    # glossaryTerms is ALWAYS in the update mask, even for the agents that do
    # not receive any. Including it means an agent that was previously given
    # terms has them cleared when the field is absent from the payload, so
    # Tiers B and C can never silently retain a stale catalog projection.
    patch_url = (
        f"{agent_url}?updateMask=displayName,description"
        ",dataAnalyticsAgent.publishedContext.datasourceReferences"
        ",dataAnalyticsAgent.publishedContext.systemInstruction"
        ",dataAnalyticsAgent.publishedContext.glossaryTerms"
    )

    payload = {
        "displayName": display_name,
        "description": description,
        "dataAnalyticsAgent": {
            "publishedContext": {
                "systemInstruction": AGENT_SYSTEM_INSTRUCTION,
                "datasourceReferences": {
                    "bq": {
                        "tableReferences": table_refs
                    }
                }
            }
        }
    }

    if glossary_terms:
        payload["dataAnalyticsAgent"]["publishedContext"]["glossaryTerms"] = glossary_terms

    gloss_note = (f", {len(glossary_terms)} catalog glossary terms" if glossary_terms else "")
    print(f"\nGrounding Agent '{agent_id}' with {len(table_refs)} dynamically discovered tables{gloss_note}...")
    
    # 1. Try PATCH (if agent already exists and is active)
    try:
        res = requests.patch(patch_url, headers=headers, json=payload, timeout=30)
        if res.status_code in [200, 201]:
            print(f"  ✅ Data Agent '{agent_id}' updated successfully ({len(table_refs)} tables grounded).")
            return True, agent_id
        elif res.status_code == 404:
            print(f"  ℹ️ Agent '{agent_id}' does not exist (HTTP 404). Creating dynamically...")
            # 2. Try POST to create new agent
            create_url = f"https://geminidataanalytics.googleapis.com/v1beta/projects/{PROJECT_ID}/locations/global/dataAgents?dataAgentId={agent_id}"
            create_res = requests.post(create_url, headers=headers, json=payload, timeout=30)
            if create_res.status_code in [200, 201]:
                print(f"  ✅ Data Agent '{agent_id}' created and grounded successfully ({len(table_refs)} tables).")
                return True, agent_id
            elif "SOFT_DELETED" in create_res.text:
                print(f"  ❌ Agent '{agent_id}' is in Google Cloud CCFE SOFT_DELETED state. Please specify a fresh DATA_AGENT_ID in .env.", file=sys.stderr)
                return False, agent_id
            print(f"  ❌ Failed to create agent '{agent_id}' (HTTP {create_res.status_code}): {create_res.text}", file=sys.stderr)
            return False, agent_id
        elif "SOFT_DELETED" in res.text:
            print(f"  ❌ Agent '{agent_id}' is in Google Cloud CCFE SOFT_DELETED state. Please specify a fresh DATA_AGENT_ID in .env.", file=sys.stderr)
            return False, agent_id
        else:
            print(f"  ❌ Failed to patch agent '{agent_id}' (HTTP {res.status_code}): {res.text}", file=sys.stderr)
            return False, agent_id
    except Exception as e:
        print(f"  ❌ Error contacting Conversational Analytics API: {e}", file=sys.stderr)
        return False, agent_id

def main():
    print("=" * 80)
    print("🔍 LUMIÈRESHOP DYNAMIC KNOWLEDGE CATALOG AGENT GROUNDING")
    print(f"Project   : {PROJECT_ID}")
    print(f"Primary   : {DATASET_ID} (Full Knowledge Catalog Grounding)")
    print(f"Isolated 2: {DATASET_2ND_ID} (Descriptions Only, 0 Glossary/EntryLinks)")
    print(f"Isolated 3: {DATASET_3RD_ID} (Raw Schema Only, 0 Descriptions)")
    print("=" * 80)

    token = get_access_token()
    if not token:
        print("Error: Could not retrieve OAuth access token. Please run `gcloud auth application-default login`.", file=sys.stderr)
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-goog-user-project": PROJECT_ID
    }

    # ------------------------------------------------------------------
    # ONE prompt. TWO searches. Both run inside discovery_core.discover(),
    # which the web app calls too, so the environment this script builds is
    # the same environment the live demo builds.
    # ------------------------------------------------------------------
    print("\n[Dynamic Discovery] Querying Knowledge Catalog with the unified prompt:")
    print(f"  \"{PROMPT}\"")
    discovery_started = time.perf_counter()
    result = discover(PROJECT_ID, DATASET_ID, token)
    discovery_elapsed_ms = (time.perf_counter() - discovery_started) * 1000.0

    discovered_tables = result["tables"]
    glossary_terms = result["terms"]

    used_fallback = False
    if not discovered_tables:
        print("")
        print("  " + "!" * 70)
        print("  \U0001F534 KNOWLEDGE CATALOG RETURNED 0 TABLES.")
        print("  \U0001F534 Falling back to a STATIC, HARDCODED table list.")
        print("  \U0001F534 This run is NOT dynamically discovered. Do NOT present it")
        print("  \U0001F534 as catalog-driven discovery, and do NOT trust a benchmark")
        print("  \U0001F534 executed against it. Re-run once catalog indexing settles.")
        print("  " + "!" * 70)
        print("")
        discovered_tables = discover_warehouse_tables_fallback()
        used_fallback = True

    # ------------------------------------------------------------------
    # Advisory coverage report.
    #
    # This does NOT alter the table list, and since the force-include list was
    # deleted nothing else does either. The agents are grounded on exactly what
    # semantic search ranked, decoys included.
    #
    # CORE_INVESTIGATION_TABLES is a historical curation of 25 tables, and the
    # recall figure below is measured against it only so that a catastrophic
    # regression is visible. Do NOT read it as a quality score: twelve of those
    # 25 are needed by no benchmark question at all. The number that matters is
    # the load-bearing set of 13, reported separately underneath.
    # ------------------------------------------------------------------
    missing = [t for t in CORE_INVESTIGATION_TABLES if t not in discovered_tables]
    print(f"  Grounding agents on {len(discovered_tables)} tables:")
    print(f"  Tables: {discovered_tables}")
    if missing:
        print(f"  \u26A0\uFE0F Not surfaced by discovery ({len(missing)}): {missing}")
    else:
        print("  \u2705 Every curated investigation table was surfaced by discovery.")

    # The 13 tables that benchmark questions are actually graded against.
    # Derived by mapping config/cmo_questions.yaml onto the certified SQL in
    # scripts/test/measure_cmo_ground_truth.py. If any of these is missing, a
    # question is unanswerable no matter how good the agent is - and the
    # failure will look like bad reasoning rather than missing plumbing.
    load_bearing = [
        "order_items", "orders", "products", "categories",
        "daily_category_targets", "web_sessions", "oos_interactions",
        "catalog_recommender_logs", "ad_bidding_log", "daily_ad_performance",
        "marketing_campaigns", "payment_gateway_logs", "competitor_price_feed",
    ]
    lb_missing = [t for t in load_bearing if t not in discovered_tables]
    print(f"\n  [Load-bearing tables - these decide whether questions are answerable]")
    print(f"    Present : {len(load_bearing) - len(lb_missing)}/{len(load_bearing)}")
    if lb_missing:
        print(f"    \U0001F534 MISSING : {lb_missing}")
        print( "       Questions depending on these CANNOT be answered by any tier.")
    else:
        print( "    \u2705 All present.")

    found_core = [t for t in CORE_INVESTIGATION_TABLES if t in discovered_tables]
    recall = 100.0 * len(found_core) / len(CORE_INVESTIGATION_TABLES)
    precision = 100.0 * len(found_core) / len(discovered_tables) if discovered_tables else 0.0
    print("\n  [Discovery quality - measured, quote these figures]")
    print(f"    Latency          : {discovery_elapsed_ms:.0f} ms"
          + ("  (FALLBACK PATH - not a semantic search timing)" if used_fallback else ""))
    print(f"    Returned         : {len(discovered_tables)} tables")
    print(f"    Curated target   : {len(CORE_INVESTIGATION_TABLES)} tables (advisory only)")
    print(f"    Recall           : {len(found_core)}/{len(CORE_INVESTIGATION_TABLES)} = {recall:.1f}%")
    print(f"    Precision        : {len(found_core)}/{len(discovered_tables)} = {precision:.1f}%")

    # ------------------------------------------------------------------
    # The glossary terms found by the SECOND search of the same prompt.
    #
    # Only Tier A (and the primary agent) receive these. That asymmetry is the
    # point of the experiment and it is honest: ecommerce_dw_2nd and
    # ecommerce_dw_3rd have no governed glossary, so there is nothing to map.
    #
    # MEASURED, 2026-09-12, 102 live agent calls across 13 runs per cell:
    #   * stockout trap, 37 tables, no glossary : 13/13 agents trapped
    #   * stockout trap, 37 tables, glossary    :  4/13 trapped  (p = 0.007)
    #   * metric-convention ambiguity surfaced  :  6/7 with glossary,
    #                                              0/7 without  (p = 0.005)
    # ------------------------------------------------------------------
    if glossary_terms:
        payload_bytes = len(json.dumps(glossary_terms).encode("utf-8"))
        print(f"\n  [Business glossary - same prompt, second search]")
        print(f"    Discovered {len(glossary_terms)} terms ({payload_bytes:,d} bytes):")
        for t in glossary_terms:
            print(f"      - {t['displayName']}")
    else:
        print("\n  \u26A0\uFE0F Knowledge Catalog returned 0 glossary terms. Tier A will be "
              "grounded on BigQuery descriptions alone; the catalog advantage "
              "will not be demonstrable in this deployment.")

    success_count = 0
    configured_agents = {}
    failed_agents = []
    for key, cfg in AGENTS_CONFIG.items():
        env_key = cfg["env_key"]
        agent_id = cfg["agent_id"]
        display_name = cfg["display_name"]
        target_dataset = cfg["dataset_id"]
        tier_info = cfg["tier"]

        inject = cfg.get("inject_glossary", False)
        terms_for_agent = glossary_terms if inject else None

        print(f"\n[Grounding] {tier_info}")
        desc = f"Grounded with {len(discovered_tables)} tables ({target_dataset}). {tier_info}."
        if inject:
            desc += f" Mapped to {len(glossary_terms)} Knowledge Catalog glossary terms."
        ok, active_id = provision_or_update_data_agent(
            agent_id, display_name, desc, discovered_tables, headers,
            target_dataset=target_dataset, glossary_terms=terms_for_agent
        )
        if ok:
            success_count += 1
            configured_agents[env_key] = f"{active_id} -> {target_dataset}"
        else:
            failed_agents.append(f"{env_key} ({agent_id} -> {target_dataset})")

    print("\n" + "=" * 80)
    print(f"DYNAMIC GROUNDING COMPLETE: {success_count}/{len(AGENTS_CONFIG)} agents dynamically configured.")
    for k, v in configured_agents.items():
        print(f"  • {k:<18} : {v}")
    if glossary_terms:
        injected = [c["agent_id"] for c in AGENTS_CONFIG.values() if c.get("inject_glossary")]
        print(f"  • Knowledge Catalog glossary mapped to: {', '.join(injected)}")
    print("=" * 80)

    # A PARTIAL provisioning must fail the pipeline.
    #
    # This previously printed "3/4 agents dynamically configured" and exited 0.
    # On the 2026-09-12 rebuild the access token expired part-way through and
    # Tier B was the one that missed out, so the run continued with agent B
    # still grounded on the PREVIOUS generation of data while A and C moved to
    # the new one. An A/B/C comparison in which one tier is answering from
    # different rows is not a weaker experiment, it is a misleading one - and
    # nothing downstream would have revealed it, because each agent answers
    # perfectly well on its own.
    if failed_agents:
        print("\n❌ The following agents were NOT provisioned:", file=sys.stderr)
        for f in failed_agents:
            print(f"     - {f}", file=sys.stderr)
        print("   Tiers are now inconsistent with each other. Re-run this stage "
              "before trusting any comparison.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
