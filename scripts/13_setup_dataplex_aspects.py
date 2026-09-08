#!/usr/bin/env python3
"""
Phase 13: Google Cloud Knowledge Catalog Custom Metadata Aspect Setup Script
=============================================================================
Creates the `enterprise-data-context` AspectType in Google Cloud Knowledge Catalog
(location: `global`) and attaches structured governance metadata aspects across all
140 BigQuery warehouse tables in `ecommerce_dw`.

This structured metadata layer enables Knowledge Catalog semantic search to index
forensic diagnostic summaries, grain definitions, metric measures, and relationship links.

Usage:
------
  python3 scripts/13_setup_dataplex_aspects.py
"""

import json
import os
import time
import subprocess
import sys
import requests
from concurrent.futures import ThreadPoolExecutor


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
LOCATION = "global"
ENTRY_LOCATION = os.environ.get("BQ_LOCATION", "us-central1")
DATASET_ID = os.environ.get("BQ_DATASET_ID", "ecommerce_dw")

# Import the 130+ table metadata dictionary from apply_bq_descriptions
from apply_bq_descriptions import TABLE_METADATA

# Explicit rich context for the 25 core commerce & telemetry tables (Neutralized Enterprise Semantics)
CRUCIAL_ASPECT_CONTEXT = {
    "categories": (
        "Master product category taxonomy and merchandising hierarchy. Used to partition commercial intake targets, "
        "category pacing curves, and actual sales revenue across retail merchandising lines."
    ),
    "products": (
        "Master product catalog, default selling prices, cost of goods, and brand metadata. Core dimension table for "
        "evaluating product-level revenue contribution, margins, and SKU catalog attributes."
    ),
    "distribution_centers": (
        "Regional warehouse fulfillment hubs and logistics centers (Paris Hub DC1, Frankfurt Hub DC2). Tracks regional "
        "inventory allocation, dispatch capacity, and warehouse throughput."
    ),
    "inventory_items": (
        "Real-time master stock allocations, warehouse batch availability, and safety stock thresholds. Tracks active "
        "warehouse inventory levels, physical buffer quantities, and replenishment thresholds."
    ),
    "inventory_snapshots": (
        "Historical hourly and daily inventory snapshots tracking stock depletion and availability timelines across "
        "distribution centers. Captures SKU inventory balances and zero-stock duration intervals."
    ),
    "users": (
        "Registered customer accounts, country codes, geographic cohorts, and account creation dates. Dimension table for "
        "customer segmentation, cohort retention, and geographic market distribution."
    ),
    "orders": (
        "Master order transactions, order timestamps, status, gross revenue, net revenue, and promotional discounts. Central "
        "fact table for analyzing commercial sales volume, transaction velocity, and overall revenue realization."
    ),
    "order_items": (
        "Line-item level order transactions detailing purchased SKUs, unit quantities, item prices, and margins. Computes "
        "SKU-level revenue contribution, basket size distribution, and product gross margins."
    ),
    "sales_event_stream": (
        "Real-time streaming transactional event feed capturing high-frequency sales events and intra-hour intake velocity "
        "across all active digital storefront channels."
    ),
    "weekly_commercial_targets": (
        "Executive weekly revenue budgets and targets by domain and country. Benchmark baseline for evaluating commercial "
        "performance, sales target attainment, and seasonal demand planning."
    ),
    "daily_category_targets": (
        "Daily commercial revenue targets, planned conversion rates, target ROAS, and expected order volume by category. "
        "Establishes commercial pacing quotas and planned daily conversion benchmarks."
    ),
    "category_15min_targets": (
        "Intraday 15-minute expected revenue target curves and pacing baselines by category. Models hourly intraday customer "
        "traffic curves, expected intake velocity, and hourly pacing benchmarks."
    ),
    "web_sessions": (
        "Digital storefront user traffic sessions, device types, landing pages, UTM campaign parameters, and traffic acquisition channels."
    ),
    "web_events": (
        "High-volume clickstream event logs tracking page views, search queries, cart additions, and checkout steps. Telemetry "
        "table for analyzing conversion funnel performance and user drop-off points."
    ),
    "oos_interactions": (
        "Out-of-stock telemetry logging user attempts to purchase zero-stock SKUs, waitlist joins, and bounce events. Captures "
        "unfulfilled consumer demand and calculates estimated lost revenue due to stockouts."
    ),
    "competitor_price_feed": (
        "Hourly competitor pricing scrapes, market discounts, and matched SKU price indices across EU retailers. Benchmark "
        "table for monitoring market price elasticity and retail price parity."
    ),
    "marketing_campaigns": (
        "Paid acquisition campaign master directory, channel allocations, and daily budget caps across Google Search, Meta Ads, and video networks."
    ),
    "daily_ad_performance": (
        "Daily marketing performance tracking ad impressions, clicks, advertising spend, attributed revenue, and realized return on ad spend (ROAS) across paid campaigns."
    ),
    "ad_bidding_log": (
        "Automated smart bidding engine telemetry capturing bid status, target ROAS constraints, budget adjustments, auction pacing, and algorithm learning states."
    ),
    "ad_creatives": (
        "Marketing creative assets, banner copy, video tags, quality scores, click-through rates, and platform algorithmic learning status."
    ),
    "payment_gateway_logs": (
        "Payment service provider (PSP) transaction logs, authorization latencies, gateway response codes, and payment error rates across PayPal, Stripe, and Adyen."
    ),
    "influencer_campaigns": (
        "Creator and influencer partner contracts, promotional coupon codes, target revenue quotas, commission rates, and attributed campaign revenue."
    ),
    "catalog_recommender_logs": (
        "Product recommendation engine impressions, click logs, fallback recommendation flags, and category relevance scoring."
    ),
    "shipping_lead_times": (
        "Promised customer delivery lead times, carrier routing performance, regional transit latency, and delivery SLA compliance."
    ),
    "competitor_promotions": (
        "Competitor promotional campaign calendars, sitewide discount depths, flash sales, and banner marketing intelligence."
    ),
}

# Domain-specific enrichment for extended tables (Domains H through Q)
EXTENDED_DOMAIN_CONTEXT_TEMPLATES = {
    "domain_h_staging": "Raw third-party ELT staging table capturing untransformed partner API feeds and real-time webhook payloads. Diagnostic Role: Pipeline Ingestion Freshness & Sync Error Monitoring.",
    "domain_i_returns": "Enterprise returns and RMA management dataset tracking customer return requests, warehouse inspection triage grades, and refund payment turnaround. Diagnostic Role: Post-Purchase Dissatisfaction, Damaged Product Rates & Refund Processing Latency.",
    "domain_j_support": "Customer support ticketing and CRM operational telemetry tracking helpdesk queues, agent messaging, first contact resolution (FCR), and post-resolution CSAT surveys. Diagnostic Role: Customer Service Queue Backlog, Escalations & Channel Satisfaction.",
    "domain_k_supply_chain": "Supply chain, procurement, and warehouse management (WMS) dataset capturing supplier purchase orders, inbound dock appointments, aisle rack cube utilization, and supplier on-time delivery (OTD). Diagnostic Role: Inbound Supplier SLA Tracking & Warehouse Storage Density.",
    "domain_l_finance": "Corporate finance and accounting general ledger (GL) dataset capturing double-entry journal entries, chart of accounts mappings, accounts payable (AP) invoice aging, and bank statement reconciliations. Diagnostic Role: Financial Auditability, AP Aging & Trial Balance Reconciliation.",
    "domain_m_loyalty": "Customer loyalty, rewards, and retention program dataset tracking tier memberships, point ledger burn-to-earn velocity, rewards redemptions, and gift card breakage. Diagnostic Role: Customer Retention, Loyalty Point Utilization & Churn Prevention.",
    "domain_n_lifecycle": "Lifecycle marketing, CRM automation, and affiliate network telemetry tracking email campaign deliverability, template conversions, bounce rates, and partner commissions. Diagnostic Role: Lifecycle Deliverability, Campaign Unsubscribe Rates & Affiliate ROI.",
    "domain_o_pim": "Product Information Management (PIM) and master catalog registry tracking SKU attribute completeness, multilingual translations, size charts, and digital media assets. Diagnostic Role: Master Catalog Quality, Translation Coverage & Merchandising Completeness.",
    "domain_p_omnichannel": "Omni-channel retail physical store and point-of-sale (POS) transactional dataset tracking brick-and-mortar store registers, in-person sales, click-and-collect (BOPIS) pickup SLAs, and store inventory. Diagnostic Role: Physical Store Performance & BOPIS Fulfillment Latency.",
    "domain_q_sandbox": "Non-production sandbox experimentation and quality assurance dataset capturing synthetic load test sessions, pricing simulations, and automated telemetry. Diagnostic Role: Experimental Feature Validation & QA Harness."
}

def resolve_dataset_location(project_id, dataset_id, default_loc):
    """Auto-detects the exact BigQuery dataset region from Google Cloud."""
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=project_id)
        dataset = client.get_dataset(dataset_id)
        if dataset and dataset.location:
            return dataset.location.lower()
    except Exception:
        pass
    return default_loc


def get_access_token():
    token = os.environ.get("GCP_ACCESS_TOKEN")
    if not token:
        gcloud_paths = ["/google/data/ro/teams/cloud-sdk/gcloud", "gcloud"]
        for gcloud_cmd in gcloud_paths:
            try:
                res = subprocess.run(
                    [gcloud_cmd, "auth", "print-access-token"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if res.returncode == 0 and res.stdout.strip():
                    token = res.stdout.strip()
                    break
            except Exception:
                continue
    return token

def get_project_number(token):
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://cloudresourcemanager.googleapis.com/v1/projects/{PROJECT_ID}"
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            num = r.json().get("projectNumber")
            if num:
                return str(num)
    except Exception:
        pass

    for cmd in ["/google/data/ro/teams/cloud-sdk/gcloud", "gcloud"]:
        try:
            res = subprocess.run([cmd, "projects", "describe", PROJECT_ID, "--format=value(projectNumber)"], capture_output=True, text=True, timeout=10)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            continue
    return ""

def create_or_get_global_aspect_type(token):
    aspect_type_id = "enterprise-data-context"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-goog-user-project": PROJECT_ID
    }
    url = f"https://dataplex.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/aspectTypes/{aspect_type_id}"
    
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        print(f"✅ Found existing global AspectType: enterprise-data-context")
        return r.json()["name"]

    create_url = f"https://dataplex.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/aspectTypes?aspectTypeId={aspect_type_id}"
    payload = {
        "description": "Enterprise context, business domain categorization, data tier, and diagnostic role for LumièreShop warehouse tables.",
        "metadataTemplate": {
            "name": aspect_type_id,
            "type": "record",
            "recordFields": [
                {"name": "business_domain", "type": "string", "index": 1, "annotations": {"description": "Business domain identifier across Domains A through Q"}},
                {"name": "data_tier", "type": "string", "index": 2, "annotations": {"description": "Medallion architectural tier: gold_curated, silver_consolidated, bronze_raw_staging, sandbox_qa"}},
                {"name": "operational_role", "type": "string", "index": 3, "annotations": {"description": "Standard business operations function in retail enterprise workflow"}},
                {"name": "incident_relevance_summary", "type": "string", "index": 4, "annotations": {"description": "Detailed business context and diagnostic relevance regarding commercial sales targets, Black Week revenue pacing, stockouts, marketing spend, and fulfillment"}}
            ]
        }
    }
    r = requests.post(create_url, headers=headers, json=payload)
    if r.status_code in (200, 201):
        print(f"✅ Successfully created global AspectType: enterprise-data-context")
        print("⏳ Pausing 5s for global metadata control plane propagation...")
        time.sleep(5.0)
    elif r.status_code == 409:
        print(f"✅ Global AspectType enterprise-data-context already exists.")
    else:
        print(f"⚠️ AspectType creation returned HTTP {r.status_code}: {r.text[:200]}")
    return f"projects/{PROJECT_ID}/locations/{LOCATION}/aspectTypes/{aspect_type_id}"

def attach_single_aspect(args):
    table_name, meta, token, project_number, entry_loc = args
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-goog-user-project": PROJECT_ID
    }
    
    labels = meta.get("labels", {})
    domain = labels.get("domain", "general_enterprise")
    tier = labels.get("data_tier", "gold_curated")
    role = labels.get("diagnostic_role", "operational_table")
    
    # 1. Use explicit crucial context if in Core 25
    if table_name in CRUCIAL_ASPECT_CONTEXT:
        incident_summary = CRUCIAL_ASPECT_CONTEXT[table_name]
    else:
        # 2. Use enriched domain diagnostic template combined with table description
        base_desc = meta.get("description", "")
        template = EXTENDED_DOMAIN_CONTEXT_TEMPLATES.get(domain, "")
        if template:
            incident_summary = f"{base_desc} [DIAGNOSTIC CONTEXT]: {template}"
        else:
            incident_summary = base_desc
    
    entry_id = f"bigquery.googleapis.com/projects/{PROJECT_ID}/datasets/{DATASET_ID}/tables/{table_name}"
    
    # Try formats: 1) numeric project number, 2) alphanumeric project ID
    ident_pairs = [
        (project_number, f"projects/{project_number}/locations/global/aspectTypes/enterprise-data-context", f"{project_number}.global.enterprise-data-context"),
        (PROJECT_ID, f"projects/{PROJECT_ID}/locations/global/aspectTypes/enterprise-data-context", f"{PROJECT_ID}.global.enterprise-data-context")
    ]
    
    last_err = ""
    for attempt in range(5):
        for proj_ident, aspect_type_uri, aspect_ref_key in ident_pairs:
            if not proj_ident:
                continue
            entry_path = f"projects/{proj_ident}/locations/{entry_loc}/entryGroups/@bigquery/entries/{entry_id}"
            url = f"https://dataplex.googleapis.com/v1/{entry_path}"
            
            aspect_payload = {
                "aspectType": aspect_type_uri,
                "data": {
                    "business_domain": domain,
                    "data_tier": tier,
                    "operational_role": role,
                    "incident_relevance_summary": incident_summary
                }
            }
            
            patch_payload = {"aspects": {aspect_ref_key: aspect_payload}}
            patch_url = f"{url}?updateMask=aspects"
            
            try:
                r = requests.patch(patch_url, headers=headers, json=patch_payload, timeout=20)
                if r.status_code == 200:
                    return table_name, True, None
                elif r.status_code == 429 or (r.status_code == 403 and any(k in r.text.lower() for k in ["quota", "may not exist", "permission denied", "rate limit"])):
                    backoff = 2.5 * (1.5 ** attempt)
                    time.sleep(backoff)
                    continue
                else:
                    err_detail = r.text[:200].replace("\n", " ")
                    last_err = f"HTTP {r.status_code}: {err_detail}"
            except Exception as e:
                last_err = str(e)
        
        # Exponential backoff on rate limits or concurrency locks
        if attempt < 4:
            time.sleep(1.5 * (attempt + 1))
            
    return table_name, False, last_err

def attach_aspects_parallel(token, project_number, entry_loc):
    total = len(TABLE_METADATA)
    print(f"\nAttaching global `enterprise-data-context` aspects in parallel across {total} BigQuery tables (Location: {entry_loc})...")
    
    tasks = [(t_name, meta, token, project_number, entry_loc) for t_name, meta in TABLE_METADATA.items()]
    
    successful_tables = set()
    failed_tasks = []
    errors = []
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        for table_name, success, err in executor.map(attach_single_aspect, tasks):
            if success:
                successful_tables.add(table_name)
            else:
                failed_tasks.append(next(t for t in tasks if t[0] == table_name))
                if len(errors) < 5:
                    errors.append(f"{table_name} -> {err}")
            if len(successful_tables) % 25 == 0 or (len(successful_tables) + len(failed_tasks)) == total:
                print(f"  Progress: {len(successful_tables)}/{len(successful_tables) + len(failed_tasks)} tables processed (Total: {total}).")

    # Reconciliation Pass for any failed tables
    if failed_tasks:
        print(f"\n⏳ Running Reconciliation Pass for {len(failed_tasks)} remaining tables after 4s pause...")
        time.sleep(4.0)
        for task in list(failed_tasks):
            t_name, success, err = attach_single_aspect(task)
            if success:
                successful_tables.add(t_name)
                failed_tasks.remove(task)
            else:
                print(f"  ⚠️ Reconciliation failed for `{t_name}`: {err}", file=sys.stderr)
            time.sleep(0.5)

    if len(successful_tables) == total:
        print(f"✅ Completed global aspect attachment: {len(successful_tables)}/{total} tables processed (100% complete).\n")
    else:
        print(f"\n❌ ERROR: Failed to attach aspects to all tables ({len(successful_tables)}/{total}). Missing: {[t[0] for t in failed_tasks]}", file=sys.stderr)
        sys.exit(1)

def main():
    if not PROJECT_ID:
        print("ERROR: GCP_PROJECT_ID is not set in environment or .env file.", file=sys.stderr)
        sys.exit(1)
        
    token = get_access_token()
    if not token:
        print("ERROR: Could not retrieve GCP access token. Please run `gcloud auth application-default login`.", file=sys.stderr)
        sys.exit(1)
        
    project_number = get_project_number(token)
    if not project_number:
        print(f"ERROR: Could not resolve GCP project number for '{PROJECT_ID}'. Please verify gcloud project access.", file=sys.stderr)
        sys.exit(1)

    # Auto-detect exact BigQuery dataset location if available
    entry_loc = resolve_dataset_location(PROJECT_ID, DATASET_ID, ENTRY_LOCATION)
    print(f"GCP Project: {PROJECT_ID} (Number: {project_number}) | Dataset: {DATASET_ID} (Location: {entry_loc})")
    
    create_or_get_global_aspect_type(token)
    attach_aspects_parallel(token, project_number, entry_loc)

if __name__ == "__main__":
    main()
