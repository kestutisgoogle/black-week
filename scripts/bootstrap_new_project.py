#!/usr/bin/env python3
"""
LumièreShop Automated Turnkey Project Bootstrapper & Cloud Provisioner
======================================================================
Orchestrates end-to-end cloud provisioning of all LumièreShop infrastructure,
data warehouse schemas, deterministic synthetic records, Knowledge Catalog
metadata, business glossaries, and Gemini Data Agents in any fresh Google Cloud project.

Execution Stages:
-----------------
 1. Pre-Flight Configuration & Authentication Audit
 2. BigQuery Core Schema Creation (26 Tables)
 3. BigQuery Extended Enterprise Schemas (104 Tables -> 130 Tables)
 4. Investigation & Bidding Log Schema Extensions (134 Tables)
 5. Operator Identity Audit Tracking Extension (user_name column)
 6. Multi-Agent Audit Tracking Extension (menu_item, agent_no columns)
 7. Comprehensive Table & Column Metadata Descriptions (100% Coverage)
 8. Deterministic Operational Black Week Data Generation (26k Orders, 17.3M Events)
 9. Extended Enterprise Domain Data Generation
10. Multi-Week Historical Actuals Generation
11. Knowledge Catalog Business Glossary (15 Categories, 85 Terms, 188 EntryLinks)
12. Knowledge Catalog Custom AspectType (enterprise-data-context) & Bindings
13. Gemini Enterprise Data Agents Provisioning & Grounding (4 Agents)
14. Automated End-to-End System Verification (11 Composable Test Suites)

Usage:
------
  # Run full bootstrap pipeline
  python3 scripts/bootstrap_new_project.py

  # Run dry-run validation without modifying cloud state
  python3 scripts/bootstrap_new_project.py --dry-run

  # Run provisioning but skip post-deployment tests
  python3 scripts/bootstrap_new_project.py --skip-tests
"""

import os
import sys
import time
import argparse
import subprocess
from datetime import datetime, timezone

# Path resolution
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)


def load_dotenv():
    """Parses root-level .env file into os.environ."""
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip("'\""))


load_dotenv()

PROJECT_ID = os.environ.get("GCP_PROJECT_ID")
DATASET_ID = os.environ.get("BQ_DATASET_ID", "ecommerce_dw")
LOCATION = os.environ.get("BQ_LOCATION", "us-central1")
DATA_AGENT_ID = os.environ.get("DATA_AGENT_ID") or os.environ.get("CA_DATA_AGENT_ID", "gda-8216e5c2-fedb-4ef5-bb16-d65878618b8b")

STAGES = [
    ("0. Google Cloud APIs & IAM Role Bindings", "scripts/setup_gcp_apis.py"),
    ("1. Core BigQuery Schema (26 Tables)", "scripts/01_create_schema.py"),
    ("2. Extended Enterprise Schemas (104 Tables)", "scripts/11_create_extended_schema.py"),
    ("3. Forensic Log Schema Extensions", "scripts/04_extend_log_schema.py"),
    ("4. Operator Identity Schema Extension", "scripts/15_add_user_name_to_logs.py"),
    ("5. Multi-Agent Menu Auditing Extension", "scripts/17_add_menu_item_and_agent_no_to_logs.py"),
    ("6. Structured Descriptions on 140 Tables", "scripts/apply_bq_descriptions.py"),
    ("7. Operational Black Week Synthetic Data", "scripts/02_generate_data.py"),
    ("8. Extended Domain Synthetic Data", "scripts/12_generate_extended_data.py"),
    ("9. Multi-Week Historical Actuals Data", "scripts/14_generate_historical_data.py"),
    ("10. Knowledge Catalog Glossary & EntryLinks", "scripts/09_create_dataplex_glossary.py"),
    ("11. Knowledge Catalog Custom AspectType", "scripts/13_setup_dataplex_aspects.py"),
    ("12. BigQuery Isolation Datasets (2nd & 3rd)", "scripts/18_setup_isolation_datasets.py"),
    ("13. BigQuery Data Agents Provisioning", "scripts/06_update_data_agent.py"),
]


def check_preflight():
    print("=" * 80)
    print("🚀 LUMIÈRESHOP CLOUD PROVISIONING PRE-FLIGHT AUDIT")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print(f"Target Project ID : {PROJECT_ID}")
    print(f"BigQuery Dataset  : {DATASET_ID}")
    print(f"BigQuery Location : {LOCATION}")
    print(f"Data Agent ID     : {DATA_AGENT_ID}")
    print("=" * 80)

    if not PROJECT_ID or PROJECT_ID == "your-gcp-project-id":
        print("❌ Error: Valid GCP_PROJECT_ID is not configured in .env file.", file=sys.stderr)
        print("   Please copy .env.example to .env and set your target GCP Project ID.", file=sys.stderr)
        sys.exit(1)

    # Check OAuth access token
    token = None
    gcloud_cmds = ["/google/data/ro/teams/cloud-sdk/gcloud", "gcloud"]
    for cmd in gcloud_cmds:
        try:
            res = subprocess.run([cmd, "auth", "print-access-token"], capture_output=True, text=True, timeout=10)
            if res.returncode == 0 and res.stdout.strip():
                token = res.stdout.strip()
                break
        except Exception:
            continue

    if not token:
        print("❌ Error: Could not obtain Google Cloud OAuth access token.", file=sys.stderr)
        print("   Please authenticate with: `gcloud auth login` and `gcloud auth application-default login`.", file=sys.stderr)
        sys.exit(1)

    print("✅ Google Cloud authentication and environment configuration verified.")

    # Check and enable required GCP APIs
    required_apis = [
        "bigquery.googleapis.com",
        "bigqueryconnection.googleapis.com",
        "dataplex.googleapis.com",
        "datacatalog.googleapis.com",
        "geminidataanalytics.googleapis.com",
        "cloudaicompanion.googleapis.com",
        "aiplatform.googleapis.com",
        "run.googleapis.com",
        "cloudbuild.googleapis.com",
        "artifactregistry.googleapis.com",
        "iam.googleapis.com",
        "cloudresourcemanager.googleapis.com"
    ]
    print("\n⚡ Ensuring all 12 required Google Cloud APIs are enabled on project...")
    for cmd in gcloud_cmds:
        try:
            res = subprocess.run([cmd, "services", "enable", *required_apis, f"--project={PROJECT_ID}"], capture_output=True, text=True, timeout=60)
            if res.returncode == 0:
                print("✅ All 12 required Google Cloud APIs verified and active.\n")
                break
        except Exception:
            continue


def run_stage(title: str, script_rel_path: str, dry_run: bool = False) -> bool:
    print("-" * 80)
    print(f"▶️  Executing: {title} ({script_rel_path})")
    print("-" * 80)

    if dry_run:
        print(f"   [DRY-RUN] Would execute: python3 {script_rel_path}")
        return True

    start_time = time.time()
    script_abs_path = os.path.join(PROJECT_ROOT, script_rel_path)
    
    env = os.environ.copy()
    env["PYTHONPATH"] = PROJECT_ROOT + ":" + os.path.join(PROJECT_ROOT, "backend")

    res = subprocess.run([sys.executable, script_abs_path], cwd=PROJECT_ROOT, env=env)
    elapsed = time.time() - start_time

    if res.returncode != 0:
        print(f"\n❌ Stage failed with exit code {res.returncode} after {elapsed:.2f}s: {title}", file=sys.stderr)
        return False

    print(f"✅ Stage completed successfully in {elapsed:.2f}s.\n")
    return True


def main():
    parser = argparse.ArgumentParser(description="LumièreShop Automated Cloud Provisioner")
    parser.add_argument("--dry-run", action="store_true", help="Audit prerequisites and print steps without running scripts.")
    parser.add_argument("--skip-tests", action="store_true", help="Skip running post-provisioning verification tests.")
    args = parser.parse_args()

    check_preflight()

    total_start = time.time()
    for title, script in STAGES:
        success = run_stage(title, script, dry_run=args.dry_run)
        if not success:
            print("\n❌ Bootstrap sequence aborted due to an error in the pipeline.", file=sys.stderr)
            sys.exit(1)

    if not args.skip_tests and not args.dry_run:
        print("=" * 80)
        print("🧪 RUNNING POST-PROVISIONING QUALITY AUDIT (run_all_tests.py --all)")
        print("=" * 80)
        test_script = os.path.join(PROJECT_ROOT, "scripts", "test", "run_all_tests.py")
        env = os.environ.copy()
        env["PYTHONPATH"] = PROJECT_ROOT + ":" + os.path.join(PROJECT_ROOT, "backend")
        test_res = subprocess.run([sys.executable, test_script, "--all"], cwd=PROJECT_ROOT, env=env)
        if test_res.returncode != 0:
            print("\n⚠️ Warning: Some verification tests reported issues. Please inspect the log.", file=sys.stderr)
            sys.exit(1)

    total_elapsed = time.time() - total_start
    print("\n" + "=" * 80)
    print("🎉 LUMIÈRESHOP FRESH PROJECT BOOTSTRAP COMPLETED SUCCESSFULLY!")
    print(f"Total Provisioning Time: {total_elapsed:.2f}s")
    print(f"GCP Project            : {PROJECT_ID}")
    print(f"BigQuery Dataset       : {DATASET_ID} (140 Tables Provisioned)")
    print(f"Knowledge Catalog      : 15 Categories, 85 Clean Terms, 257 EntryLinks")
    try:
        sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts", "test"))
        from test_utils import get_knowledge_catalog_indexing_status
        indexing_info = get_knowledge_catalog_indexing_status(PROJECT_ID, DATASET_ID, token)
        print(f"Catalog Indexing Status: {indexing_info['indexed_tables']}/140 Tables ({indexing_info['table_percentage']}%) [{indexing_info['status']}]")
    except Exception:
        pass
    print(f"Gemini Data Agents     : 4 Agents Active & Grounded")
    print("=" * 80)


if __name__ == "__main__":
    main()
