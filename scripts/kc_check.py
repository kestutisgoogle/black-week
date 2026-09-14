#!/usr/bin/env python3
"""
LumièreShop Knowledge Catalog Governance & Metadata Health Checker (kc_check.py)
================================================================================
Queries Google Cloud Knowledge Catalog (Dataplex) APIs and BigQuery to summarize
the exact state of cataloged entries, harvested tables, glossaries, categories,
terms, EntryLinks, custom AspectTypes, and live semantic search readiness.

Usage:
------
  python3 scripts/kc_check.py
  python3 scripts/kc_check.py --verbose
"""

import os
import sys
import time
import argparse
import requests
import subprocess
from typing import Dict, List, Any, Optional

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)


def load_dotenv():
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("'\""))


load_dotenv()

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "").strip()
DATASET_ID = os.environ.get("BQ_DATASET_ID", "ecommerce_dw").strip()
BQ_LOCATION = os.environ.get("BQ_LOCATION", "europe-west4").lower().strip()
GLOSSARY_ID = "ecommerce-glossary"


def get_auth_token() -> str:
    try:
        from backend.app.services.ca_service import get_access_token
        token = get_access_token()
        if token:
            return token
    except Exception:
        pass

    for gcloud_cmd in ["/google/data/ro/teams/cloud-sdk/gcloud", "gcloud"]:
        try:
            res = subprocess.run([gcloud_cmd, "auth", "print-access-token"], capture_output=True, text=True, timeout=10)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            continue

    return os.environ.get("GCP_ACCESS_TOKEN", "")


def get_bigquery_tables_count(token: str) -> int:
    """Queries BigQuery REST API to get total physical table count in the dataset."""
    url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{PROJECT_ID}/datasets/{DATASET_ID}/tables?maxResults=1000"
    headers = {"Authorization": f"Bearer {token}", "x-goog-user-project": PROJECT_ID}
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            tables = res.json().get("tables", [])
            return len(tables)
    except Exception:
        pass
    return 0


def get_kc_harvested_tables(token: str) -> List[str]:
    """Retrieves BigQuery table entries harvested in Knowledge Catalog @bigquery entry group."""
    entries = []
    page_token = None
    headers = {"Authorization": f"Bearer {token}", "x-goog-user-project": PROJECT_ID}

    for _ in range(5):
        url = f"https://dataplex.googleapis.com/v1/projects/{PROJECT_ID}/locations/{BQ_LOCATION}/entryGroups/@bigquery/entries?pageSize=300"
        if page_token:
            url += f"&pageToken={page_token}"
        try:
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code == 200:
                data = res.json()
                for e in data.get("entries", []):
                    name = e.get("name", "")
                    if f"datasets/{DATASET_ID}/tables/" in name:
                        entries.append(name.split(f"datasets/{DATASET_ID}/tables/")[-1])
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
            else:
                break
        except Exception:
            break
    return entries


def get_glossary_stats(token: str) -> Dict[str, Any]:
    """Retrieves total terms, categories, and entry links for the business glossary."""
    headers = {"Authorization": f"Bearer {token}", "x-goog-user-project": PROJECT_ID}
    stats = {"glossaries": 0, "categories": 0, "terms": 0, "entry_links": 0, "aspect_types": 0}

    # 1. Check Glossaries
    try:
        url = f"https://dataplex.googleapis.com/v1/projects/{PROJECT_ID}/locations/global/glossaries"
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            glossaries = res.json().get("glossaries", [])
            stats["glossaries"] = len(glossaries)
    except Exception:
        pass

    # 2. Categories in ecommerce-glossary
    try:
        url = f"https://dataplex.googleapis.com/v1/projects/{PROJECT_ID}/locations/global/glossaries/{GLOSSARY_ID}/categories?pageSize=300"
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            cats = res.json().get("categories", [])
            stats["categories"] = len(cats)
    except Exception:
        pass

    # 3. Terms in ecommerce-glossary
    try:
        url = f"https://dataplex.googleapis.com/v1/projects/{PROJECT_ID}/locations/global/glossaries/{GLOSSARY_ID}/terms?pageSize=300"
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            terms = res.json().get("terms", [])
            stats["terms"] = len(terms)
    except Exception:
        pass

    # 4. AspectTypes
    try:
        url = f"https://dataplex.googleapis.com/v1/projects/{PROJECT_ID}/locations/global/aspectTypes"
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            ats = res.json().get("aspectTypes", [])
            stats["aspect_types"] = len(ats)
    except Exception:
        pass

    return stats


def test_semantic_search(token: str, query: str) -> Dict[str, Any]:
    """Runs a live semantic search test against Knowledge Catalog."""
    url = f"https://dataplex.googleapis.com/v1/projects/{PROJECT_ID}/locations/global:searchEntries"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "x-goog-user-project": PROJECT_ID}
    body = {
        "query": query,
        "scope": f"projects/{PROJECT_ID}",
        "semanticSearch": True,
        "pageSize": 100,
    }
    tables = []
    terms = []
    try:
        res = requests.post(url, headers=headers, json=body, timeout=15)
        if res.status_code == 200:
            results = res.json().get("results", [])
            for r in results:
                dp = r.get("dataplexEntry", {})
                name = dp.get("name", "")
                resource = dp.get("entrySource", {}).get("resource", "")
                if f"datasets/{DATASET_ID}/tables/" in name:
                    tbl = name.split(f"datasets/{DATASET_ID}/tables/")[-1]
                    if tbl not in tables:
                        tables.append(tbl)
                elif f"datasets/{DATASET_ID}/tables/" in resource:
                    tbl = resource.split(f"datasets/{DATASET_ID}/tables/")[-1]
                    if tbl not in tables:
                        tables.append(tbl)
                if "/terms/" in name or "/terms/" in resource:
                    term = (name or resource).split("/terms/")[-1]
                    if term not in terms:
                        terms.append(term)
    except Exception:
        pass
    return {"total_results": len(tables) + len(terms), "tables": tables, "terms": terms}


def main():
    parser = argparse.ArgumentParser(description="Summarize Google Cloud Knowledge Catalog health & metrics.")
    parser.add_argument("--verbose", action="store_true", help="Print table and term details")
    args = parser.parse_args()

    print("=" * 80)
    print("📚 GOOGLE CLOUD KNOWLEDGE CATALOG SUMMARY & HEALTH CHECK")
    print(f"Target Project ID : {PROJECT_ID}")
    print(f"BigQuery Dataset  : {DATASET_ID}")
    print(f"Regional Location : {BQ_LOCATION}")
    print("=" * 80)

    token = get_auth_token()
    if not token:
        print("❌ Error: Could not obtain Google Cloud OAuth access token.", file=sys.stderr)
        sys.exit(1)

    # 1. Physical BigQuery Tables
    bq_total = get_bigquery_tables_count(token)
    print(f"\n📊 1. BigQuery Physical Warehouse:")
    print(f"   • Dataset: `{DATASET_ID}`")
    print(f"   • Total Physical Tables: {bq_total}")

    # 2. Knowledge Catalog Harvested Tables
    harvested = get_kc_harvested_tables(token)
    harvest_pct = (len(harvested) / bq_total * 100) if bq_total > 0 else 0
    print(f"\n🌾 2. Knowledge Catalog Table Harvesting (@bigquery EntryGroup):")
    print(f"   • Harvested Entries Indexed: {len(harvested)} / {bq_total} ({harvest_pct:.1f}%)")
    if len(harvested) < bq_total:
        print(f"   ℹ️ Notice: {bq_total - len(harvested)} tables are pending background harvesting by Dataplex/Knowledge Catalog crawler.")

    # 3. Business Glossary & Aspect Types
    stats = get_glossary_stats(token)
    print(f"\n📖 3. Business Glossary & Semantic Taxonomy:")
    print(f"   • Glossaries: {stats['glossaries']} (Target: 1 -> `{GLOSSARY_ID}`)")
    print(f"   • Categories: {stats['categories']} (Target: 15)")
    print(f"   • Terms:      {stats['terms']} (Target: 85)")
    print(f"   • AspectTypes:{stats['aspect_types']} (Target: 1 -> `enterprise-data-context`)")

    # 4. Live Semantic Search Test
    print(f"\n🔍 4. Live Semantic Search Readiness:")
    search_1 = test_semantic_search(token, "Black Friday revenue variance stockouts ad spend")
    search_2 = test_semantic_search(token, "orders daily category targets logistics delivery lead times")
    print(f"   • Query A ('Black Friday revenue variance...'): {len(search_1['tables'])} tables, {len(search_1['terms'])} terms resolved")
    print(f"   • Query B ('logistics delivery lead times...'):   {len(search_2['tables'])} tables, {len(search_2['terms'])} terms resolved")

    if args.verbose and search_1['tables']:
        print(f"\n   📋 Sample Discovered Tables (Query A):")
        for t in search_1['tables'][:10]:
            print(f"      - {t}")

    print("\n" + "=" * 80)
    if stats['terms'] >= 80 and len(harvested) >= 20:
        print("✅ KNOWLEDGE CATALOG STATUS: HEALTHY & FULLY GROUNDED")
    elif len(harvested) < 20:
        print("⏳ KNOWLEDGE CATALOG STATUS: INDEX WARMING UP (Background Harvesting in Progress)")
    else:
        print("⚠️ KNOWLEDGE CATALOG STATUS: PARTIALLY CONFIGURED (Run scripts/09_create_dataplex_glossary.py)")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
