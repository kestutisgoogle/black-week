#!/usr/bin/env python3
"""
Phase 8: Google Cloud Knowledge Catalog Automated Data Profiling Scans
======================================================================
Creates and triggers automated profiling scans (DataScan API) for key forensic tables
in `ecommerce_dw`, indexing distinct categorical counts, column distributions, and
null rates into Knowledge Catalog to enhance semantic search discovery.

Usage:
------
  python3 scripts/08_setup_dataplex_profiling.py
"""

import os
import sys
import subprocess
import requests
import json
import time


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
LOCATION = os.environ.get("BQ_LOCATION", "europe-west4")

# Core operational tables to profile for categorical discovery and distinct values
PROFILE_TABLES = [
    {
        "scan_id": "profile-payment-logs",
        "table_name": "payment_gateway_logs",
        "display_name": "Payment Gateway Logs Profile"
    },
    {
        "scan_id": "profile-daily-ad-perf",
        "table_name": "daily_ad_performance",
        "display_name": "Daily Ad Performance Profile"
    },
    {
        "scan_id": "profile-ad-creatives",
        "table_name": "ad_creatives",
        "display_name": "Ad Creatives Fatigue Profile"
    },
    {
        "scan_id": "profile-shipping-lead-times",
        "table_name": "shipping_lead_times",
        "display_name": "Shipping Lead Times & Carrier Profile"
    },
    {
        "scan_id": "profile-catalog-recommender",
        "table_name": "catalog_recommender_logs",
        "display_name": "Catalog Recommender Widget Profile"
    }
]

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

def setup_dataplex_profiling():
    print(f"Setting up Dataplex Automated Data Profiling for project '{PROJECT_ID}' in location '{LOCATION}'...")
    token = get_access_token()
    if not token:
        print("Error: OAuth access token could not be retrieved.", file=sys.stderr)
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    base_url = f"https://dataplex.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/dataScans"

    created_scans = []

    for item in PROFILE_TABLES:
        scan_id = item["scan_id"]
        table_name = item["table_name"]
        display_name = item["display_name"]
        
        print(f"\nConfiguring DataScan `{scan_id}` for table `{table_name}`...")
        
        scan_url = f"{base_url}?dataScanId={scan_id}"
        table_resource = f"//bigquery.googleapis.com/projects/{PROJECT_ID}/datasets/{DATASET_ID}/tables/{table_name}"
        
        payload = {
            "displayName": display_name,
            "description": f"Automated Data Profiling scan for {table_name} capturing distinct enum values, null rates, and distribution statistics for Gemini Data Agent grounding.",
            "data": {
                "resource": table_resource
            },
            "dataProfileSpec": {
                "samplingPercent": 100.0
            }
        }

        # Check if scan exists or create it
        check_url = f"{base_url}/{scan_id}"
        check_res = requests.get(check_url, headers=headers)
        
        if check_res.status_code == 200:
            print(f"  DataScan `{scan_id}` already exists.")
            created_scans.append(scan_id)
        else:
            create_res = requests.post(scan_url, headers=headers, json=payload)
            print(f"  Create Status: HTTP {create_res.status_code}")
            if create_res.status_code in [200, 201]:
                print(f"  Successfully created DataScan `{scan_id}`.")
                created_scans.append(scan_id)
            else:
                print(f"  Notice/Response ({create_res.status_code}): {create_res.text[:300]}")

        # Trigger execution run if scan exists
        run_url = f"{base_url}/{scan_id}:run"
        run_res = requests.post(run_url, headers=headers, json={})
        if run_res.status_code == 200:
            job_name = run_res.json().get("name", "N/A")
            print(f"  Triggered profiling execution job: {job_name}")
        else:
            print(f"  Run response: {run_res.text[:200]}")

    print("\n" + "=" * 80)
    print(f"Dataplex Data Profiling setup complete. Total Scans Configured: {len(created_scans)}")
    print("=" * 80)

if __name__ == "__main__":
    setup_dataplex_profiling()
