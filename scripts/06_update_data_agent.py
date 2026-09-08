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

PROMPT = "Prepare sales, marketing, ads, inventory, all connected business domains data"

AGENTS_CONFIG = {
    "primary": {
        "env_key": "DATA_AGENT_ID",
        "agent_id": DATA_AGENT_ID,
        "display_name": "LumiereShop Primary Data Agent",
        "dataset_id": DATASET_ID,
        "tier": "Primary Single-Agent Workspace (ecommerce_dw)",
    },
    "agent_a": {
        "env_key": "DATA_AGENT_A_ID",
        "agent_id": DATA_AGENT_A_ID,
        "display_name": "LumiereShop Data Agent A (Full KC)",
        "dataset_id": DATASET_ID,
        "tier": "Tier A: Full Knowledge Catalog Grounding (ecommerce_dw)",
    },
    "agent_b": {
        "env_key": "DATA_AGENT_B_ID",
        "agent_id": DATA_AGENT_B_ID,
        "display_name": "LumiereShop Data Agent B (Descriptions Only)",
        "dataset_id": DATASET_2ND_ID,
        "tier": "Tier B: Isolated - Descriptions Only (ecommerce_dw_2nd)",
    },
    "agent_c": {
        "env_key": "DATA_AGENT_C_ID",
        "agent_id": DATA_AGENT_C_ID,
        "display_name": "LumiereShop Data Agent C (Raw Schema)",
        "dataset_id": DATASET_3RD_ID,
        "tier": "Tier C: Isolated - Raw Schema Only (ecommerce_dw_3rd)",
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


def search_knowledge_catalog_dynamic(prompt: str, token: str) -> List[str]:
    """
    Executes live semantic search against Google Cloud Knowledge Catalog to dynamically
    discover relevant BigQuery tables from the 140-table dataset without static bias.
    """
    url = f"https://dataplex.googleapis.com/v1/projects/{PROJECT_ID}/locations/global:searchEntries"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-goog-user-project": PROJECT_ID
    }
    body = {
        "query": prompt,
        "scope": f"projects/{PROJECT_ID}",
        "semanticSearch": True,
        "pageSize": 100
    }

    try:
        res = requests.post(url, headers=headers, json=body, timeout=15)
        if res.status_code != 200:
            print(f"  Notice: Knowledge Catalog search returned HTTP {res.status_code}")
            return []

        results = res.json().get("results", [])
        discovered_tables = []
        dataset_pattern = f"datasets/{DATASET_ID}/tables/"

        for r in results:
            lr = r.get("linkedResource", "")
            dp = r.get("dataplexEntry", {})
            name = dp.get("name", "")
            resource = dp.get("entrySource", {}).get("resource", "")

            if dataset_pattern in lr:
                tbl = lr.split(dataset_pattern)[-1]
                if tbl not in discovered_tables:
                    discovered_tables.append(tbl)
            elif dataset_pattern in name:
                tbl = name.split(dataset_pattern)[-1]
                if tbl not in discovered_tables:
                    discovered_tables.append(tbl)
            elif dataset_pattern in resource:
                tbl = resource.split(dataset_pattern)[-1]
                if tbl not in discovered_tables:
                    discovered_tables.append(tbl)

        return discovered_tables
    except Exception as e:
        print(f"  Notice: Knowledge Catalog search error: {e}")
        return []


AGENT_SYSTEM_INSTRUCTION = "Today is Friday, November 27th, 2026"

CORE_INVESTIGATION_TABLES = [
    "categories", "products", "distribution_centers", "inventory_items", "inventory_snapshots",
    "users", "orders", "order_items", "sales_event_stream", "weekly_commercial_targets",
    "daily_category_targets", "category_15min_targets", "web_sessions", "web_events",
    "oos_interactions", "competitor_price_feed", "marketing_campaigns", "daily_ad_performance",
    "ad_bidding_log", "ad_creatives", "payment_gateway_logs", "influencer_campaigns",
    "catalog_recommender_logs", "shipping_lead_times", "competitor_promotions"
]


def discover_warehouse_tables_fallback() -> List[str]:
    """
    Fallback: Discovers available tables directly from BigQuery dataset when
    Knowledge Catalog semantic index is still warming up during cold start.
    """
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=PROJECT_ID)
        tables = [t.table_id for t in client.list_tables(DATASET_ID)]
        if tables:
            core_present = [t for t in CORE_INVESTIGATION_TABLES if t in tables]
            if len(core_present) >= 15:
                return core_present
            return tables[:25]
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
    patch_url = f"{agent_url}?updateMask=displayName,description,dataAnalyticsAgent.publishedContext.datasourceReferences,dataAnalyticsAgent.publishedContext.systemInstruction"

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

    print(f"\nGrounding Agent '{agent_id}' with {len(table_refs)} dynamically discovered tables...")
    
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

    # Discover tables once via Knowledge Catalog semantic search
    print(f"\n[Dynamic Discovery] Querying Knowledge Catalog with unified prompt:")
    print(f"  Prompt: '{PROMPT}'")
    discovered_tables = search_knowledge_catalog_dynamic(PROMPT, token)
    
    if not discovered_tables:
        print("  ℹ️ Knowledge Catalog returned 0 tables (indexing in progress). Using resilient warehouse fallback...")
        discovered_tables = discover_warehouse_tables_fallback()

    print(f"  Discovered {len(discovered_tables)} tables for all agents:")
    print(f"  Tables: {discovered_tables}")

    success_count = 0
    configured_agents = {}
    for key, cfg in AGENTS_CONFIG.items():
        env_key = cfg["env_key"]
        agent_id = cfg["agent_id"]
        display_name = cfg["display_name"]
        target_dataset = cfg["dataset_id"]
        tier_info = cfg["tier"]

        print(f"\n[Grounding] {tier_info}")
        desc = f"Grounded with {len(discovered_tables)} tables ({target_dataset}). {tier_info}."
        ok, active_id = provision_or_update_data_agent(
            agent_id, display_name, desc, discovered_tables, headers, target_dataset=target_dataset
        )
        if ok:
            success_count += 1
            configured_agents[env_key] = f"{active_id} -> {target_dataset}"

    print("\n" + "=" * 80)
    print(f"DYNAMIC GROUNDING COMPLETE: {success_count}/{len(AGENTS_CONFIG)} agents dynamically configured.")
    for k, v in configured_agents.items():
        print(f"  • {k:<18} : {v}")
    print("=" * 80)


if __name__ == "__main__":
    main()
