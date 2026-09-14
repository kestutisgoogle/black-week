#!/usr/bin/env python3
"""
LumièreShop Automated Turnkey Project Bootstrapper & Cloud Provisioner
======================================================================
Orchestrates end-to-end cloud provisioning of all LumièreShop infrastructure,
data warehouse schemas, deterministic synthetic records, Knowledge Catalog
metadata, business glossaries, and Gemini Data Agents in any fresh Google Cloud project.

Execution Stages:
-----------------
 0. Pre-Flight Configuration & Authentication Audit
 R. BigQuery Dataset Reset (DESTRUCTIVE)             [only with --reset]
 1. BigQuery Core Schema Creation (26 Tables)
 2. BigQuery Extended Enterprise Schemas (104 Tables -> 130 Tables)
 3. Investigation & Bidding Log Schema Extensions (134 Tables)
 4. Operator Identity Audit Tracking Extension (user_name column)
 5. Multi-Agent Audit Tracking Extension (menu_item, agent_no columns)
 6. Comprehensive Table & Column Metadata Descriptions (100% Coverage)
 7. Deterministic Operational Black Week Data Generation
 8. Extended Enterprise Domain Data Generation
 9. Multi-Week Historical Actuals Generation
10. Knowledge Catalog Business Glossary (from config/business_glossary.yaml)
11. Knowledge Catalog Custom AspectType (enterprise-data-context) & Bindings
12. BigQuery Isolation Datasets (Tier B and Tier C)
13. Gemini Enterprise Data Agents Provisioning & Grounding (4 Agents)
14. Post-Rebuild Verification (spec invariants, tier parity, incident present)
15. Web Application Deployment to Cloud Run          [only with --with-app]
16. Automated End-to-End System Verification (11 Composable Test Suites)

Rebuilding an EXISTING project:
-------------------------------
`scripts/01_create_schema.py` creates tables with `create_table(exists_ok=True)`,
so a table that already exists keeps its old schema forever. A column that was
renamed or added in the code is therefore silently NOT applied, and the later
data load fails or writes into the wrong shape.

To make this impossible to hit by accident, the bootstrap performs a staleness
check and ABORTS if any of the three target datasets already exist and `--reset`
was not supplied. Passing `--reset` drops them first via
`scripts/00_reset_datasets.py`, which also permanently deletes the
`agent_interaction_logs` chat history.

Usage:
------
  # Provision a brand-new, empty project
  python3 scripts/bootstrap_new_project.py

  # Rebuild an existing project from scratch (DESTRUCTIVE)
  python3 scripts/bootstrap_new_project.py --reset

  # Run dry-run validation without modifying cloud state
  python3 scripts/bootstrap_new_project.py --dry-run

  # Run provisioning but skip post-deployment tests
  python3 scripts/bootstrap_new_project.py --skip-tests

  # Full rebuild AND deploy the web application in one command
  python3 scripts/bootstrap_new_project.py --reset --with-app
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
LOCATION = os.environ.get("BQ_LOCATION", "europe-west4")
DATA_AGENT_ID = os.environ.get("DATA_AGENT_ID") or os.environ.get("CA_DATA_AGENT_ID", "gda-8216e5c2-fedb-4ef5-bb16-d65878618b8b")

STAGES = [
    ("0. Google Cloud APIs & IAM Role Bindings", "scripts/setup_gcp_apis.py"),
    ("1. Core BigQuery Schema (26 Tables)", "scripts/01_create_schema.py"),
    ("2. Extended Enterprise Schemas (104 Tables)", "scripts/11_create_extended_schema.py"),
    ("3. Forensic Log Schema Extensions", "scripts/04_extend_log_schema.py"),
    ("4. Operator Identity Schema Extension", "scripts/15_add_user_name_to_logs.py"),
    ("5. Multi-Agent Menu Auditing Extension", "scripts/17_add_menu_item_and_agent_no_to_logs.py"),
    # ------------------------------------------------------------------
    # Data loads MUST come before descriptions.
    #
    # A BigQuery load with WRITE_TRUNCATE can replace the destination table
    # schema, and a replaced schema loses every column description. On the
    # 2026-09-11 rebuild this silently wiped all 23 core tables, because
    # descriptions were applied at stage 6 and the loads ran at stages 7-9.
    #
    # `02_generate_data.py` now passes an explicit schema so it no longer
    # replaces anything, but ordering descriptions last makes the pipeline
    # robust even if a future loader reintroduces the same mistake.
    # ------------------------------------------------------------------
    ("6. Operational Black Week Synthetic Data", "scripts/02_generate_data.py"),
    ("7. Extended Domain Synthetic Data", "scripts/12_generate_extended_data.py"),
    ("8. Multi-Week Historical Actuals Data", "scripts/14_generate_historical_data.py"),
    ("9. Structured Descriptions on 140 Tables", "scripts/apply_bq_descriptions.py"),
    ("10. Knowledge Catalog Glossary & EntryLinks", "scripts/09_create_dataplex_glossary.py"),
    ("11. Knowledge Catalog Custom AspectType", "scripts/13_setup_dataplex_aspects.py"),
    ("12. BigQuery Isolation Datasets (2nd & 3rd)", "scripts/18_setup_isolation_datasets.py"),
    ("13. BigQuery Data Agents Provisioning", "scripts/06_update_data_agent.py"),
    ("14. Post-Rebuild Verification (spec invariants + tier parity)", "scripts/verify_rebuild.py"),
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

    return token


def existing_datasets():
    """Returns the target datasets that already exist in the project.

    `01_create_schema.py` uses `create_table(exists_ok=True)`, so pre-existing
    tables keep their old schema forever. Rebuilding on top of them produces a
    silently half-stale warehouse, so the caller must either reset or abort.
    """
    datasets = [
        DATASET_ID,
        os.environ.get("BQ_DATASET_2ND_ID", f"{DATASET_ID}_2nd"),
        os.environ.get("BQ_DATASET_3RD_ID", f"{DATASET_ID}_3rd"),
    ]
    found = []
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=PROJECT_ID)
        for dataset_id in datasets:
            try:
                client.get_dataset(f"{PROJECT_ID}.{dataset_id}")
                found.append(dataset_id)
            except Exception:
                continue
    except Exception as exc:  # BigQuery unreachable: let the real stages report it.
        print(f"   ⚠️ Could not inspect existing datasets ({exc}); skipping staleness guard.")
    return found


def run_stage(title: str, script_rel_path: str, dry_run: bool = False,
              extra_args: list = None) -> bool:
    extra_args = extra_args or []
    print("-" * 80)
    print(f"▶️  Executing: {title} ({script_rel_path})")
    print("-" * 80)

    if dry_run:
        printable = " ".join([script_rel_path] + extra_args)
        print(f"   [DRY-RUN] Would execute: python3 {printable}")
        return True

    start_time = time.time()
    script_abs_path = os.path.join(PROJECT_ROOT, script_rel_path)

    env = os.environ.copy()
    env["PYTHONPATH"] = PROJECT_ROOT + ":" + os.path.join(PROJECT_ROOT, "backend")
    # Stage output is a pipe when the bootstrap itself is piped (e.g. into tee),
    # so CPython block-buffers it and a long stage looks like a hang. Force
    # line-buffered output so progress is visible in real time.
    env["PYTHONUNBUFFERED"] = "1"

    res = subprocess.run([sys.executable, script_abs_path, *extra_args],
                         cwd=PROJECT_ROOT, env=env)
    elapsed = time.time() - start_time

    if res.returncode != 0:
        print(f"\n❌ Stage failed with exit code {res.returncode} after {elapsed:.2f}s: {title}", file=sys.stderr)
        return False

    print(f"✅ Stage completed successfully in {elapsed:.2f}s.\n")
    return True


def describe_glossary():
    """Read the real counts out of the glossary so the summary cannot go stale."""
    try:
        import yaml
        path = os.path.join(PROJECT_ROOT, "config", "business_glossary.yaml")
        with open(path, "r", encoding="utf-8") as fh:
            g = yaml.safe_load(fh)["glossary"]
        terms = g.get("terms", [])
        links = {(t["id"], b["table"]) for t in terms
                 for b in (t.get("bindings") or []) if b.get("table")}
        return len(g.get("categories", [])), len(terms), len(links)
    except Exception:
        return "?", "?", "?"


def count_tables():
    """Count the tables that actually exist, rather than asserting a constant.

    The completion banner used to print a hardcoded '140 Tables Provisioned'
    regardless of what had really been created, which gave an operator no way
    to tell a complete install from a partial one.
    """
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=PROJECT_ID)
        query = (
            f"SELECT COUNT(*) AS n FROM `{PROJECT_ID}.{DATASET_ID}`"
            ".INFORMATION_SCHEMA.TABLES"
        )
        return int(list(client.query(query).result())[0]["n"])
    except Exception:
        return None


def count_agents(token):
    """Count how many of the configured data agents actually exist.

    Returns (found, expected). `expected` is derived from the agent IDs present
    in the environment, so it stays correct if the set of agents ever changes.
    """
    agent_ids = [
        os.environ.get("DATA_AGENT_ID"),
        os.environ.get("DATA_AGENT_A_ID"),
        os.environ.get("DATA_AGENT_B_ID"),
        os.environ.get("DATA_AGENT_C_ID"),
    ]
    agent_ids = [a for a in agent_ids if a]
    if not token or not agent_ids:
        return None, len(agent_ids)
    try:
        import requests
        host = os.environ.get("CA_API_HOST",
                              "https://geminidataanalytics.googleapis.com")
        found = 0
        for agent_id in agent_ids:
            url = (f"{host}/v1beta/projects/{PROJECT_ID}/locations/global"
                   f"/dataAgents/{agent_id}")
            resp = requests.get(url, headers={"Authorization": f"Bearer {token}"},
                                timeout=30)
            if resp.status_code == 200:
                found += 1
        return found, len(agent_ids)
    except Exception:
        return None, len(agent_ids)


def main():
    parser = argparse.ArgumentParser(description="LumièreShop Automated Cloud Provisioner")
    parser.add_argument("--dry-run", action="store_true", help="Audit prerequisites and print steps without running scripts.")
    parser.add_argument("--skip-tests", action="store_true", help="Skip running post-provisioning verification tests.")
    parser.add_argument("--with-app", action="store_true",
                        help="Also build and deploy the web application to Cloud Run once provisioning succeeds.")
    parser.add_argument("--reset", action="store_true",
                        help="DESTRUCTIVE. Drop the three BigQuery datasets first, so the "
                             "rebuild starts from a clean slate. Required when the datasets "
                             "already exist, because table schemas are never altered in place.")
    args = parser.parse_args()

    token = check_preflight()

    # ------------------------------------------------------------------
    # Staleness guard.
    #
    # `01_create_schema.py` calls `create_table(exists_ok=True)`. An existing
    # table therefore keeps whatever schema it already had: a column that was
    # renamed or added in the code is silently NOT applied, and the later data
    # load either fails or writes into the wrong shape. Refusing to proceed is
    # the only way to guarantee the rebuild is deterministic.
    # ------------------------------------------------------------------
    stale = [] if args.dry_run else existing_datasets()
    if stale and not args.reset:
        print("\n" + "=" * 80, file=sys.stderr)
        print("❌ ABORTED: these BigQuery datasets already exist:", file=sys.stderr)
        for dataset_id in stale:
            print(f"     • {dataset_id}", file=sys.stderr)
        print("\n   Table schemas are never altered in place, so rebuilding on top of", file=sys.stderr)
        print("   them would produce a silently half-stale warehouse.", file=sys.stderr)
        print("\n   Re-run with --reset to drop them first (DESTRUCTIVE: this also", file=sys.stderr)
        print("   permanently deletes agent_interaction_logs chat history).", file=sys.stderr)
        print("=" * 80, file=sys.stderr)
        sys.exit(1)

    total_start = time.time()

    if args.reset:
        os.environ["BOOTSTRAP_RESET_CONFIRMED"] = "1"

        # Order matters. Purge the catalogue FIRST, while the BigQuery table
        # entries its EntryLinks point at still exist; deleting the tables first
        # can leave the glossary holding dangling references.
        #
        # This step is necessary because `09_create_dataplex_glossary.py` only
        # ever creates and verifies - it never deletes. Without an explicit
        # purge, a term or EntryLink that was removed from the YAML would
        # survive in the catalogue indefinitely and remain visible to Agent A.
        if not run_stage("R1. Knowledge Catalog Purge (DESTRUCTIVE)",
                         "scripts/cleanup_knowledge_catalog.py",
                         dry_run=args.dry_run, extra_args=["--force"]):
            print("\n❌ Bootstrap sequence aborted: the Knowledge Catalog purge failed.",
                  file=sys.stderr)
            sys.exit(1)

        if not run_stage("R2. BigQuery Dataset Reset (DESTRUCTIVE)",
                         "scripts/00_reset_datasets.py",
                         dry_run=args.dry_run, extra_args=["--force"]):
            print("\n❌ Bootstrap sequence aborted: the dataset reset failed.", file=sys.stderr)
            sys.exit(1)

    for title, script in STAGES:
        success = run_stage(title, script, dry_run=args.dry_run)
        if not success:
            print("\n❌ Bootstrap sequence aborted due to an error in the pipeline.", file=sys.stderr)
            sys.exit(1)

    if args.with_app:
        success = run_stage("15. Web Application Deployment (Cloud Run)",
                            "scripts/deploy_cloud_run.py", dry_run=args.dry_run)
        if not success:
            print("\n❌ Bootstrap sequence aborted: the application failed to deploy.",
                  file=sys.stderr)
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

    # ------------------------------------------------------------------
    # A dry run executes nothing, so it must not print a completion banner.
    # It previously printed "COMPLETED SUCCESSFULLY" along with "140 Tables
    # Provisioned" and "4 Agents Active & Grounded" even though no stage had
    # run, which is indistinguishable from a real successful install.
    # ------------------------------------------------------------------
    if args.dry_run:
        print("\n" + "=" * 80)
        print("✅ DRY RUN COMPLETE — no cloud resources were created or modified.")
        print(f"GCP Project            : {PROJECT_ID}")
        print(f"BigQuery Location      : {LOCATION}")
        print(f"Stages that would run  : {len(STAGES)}")
        print("Re-run without --dry-run to provision for real.")
        print("=" * 80)
        return

    print("\n" + "=" * 80)
    print("🎉 LUMIÈRESHOP FRESH PROJECT BOOTSTRAP COMPLETED SUCCESSFULLY!")
    print(f"Total Provisioning Time: {total_elapsed:.2f}s")
    print(f"GCP Project            : {PROJECT_ID}")

    # Every figure below is measured. Nothing here is a constant: an operator
    # installing from scratch has no other way to tell a complete warehouse
    # from a partial one.
    table_count = count_tables()
    if table_count is None:
        print(f"BigQuery Dataset       : {DATASET_ID} (table count unavailable)")
    else:
        print(f"BigQuery Dataset       : {DATASET_ID} ({table_count} tables measured)")

    cats, terms, links = describe_glossary()
    print(f"Knowledge Catalog      : {cats} categories, {terms} terms, "
          f"{links} table bindings (from config/business_glossary.yaml)")

    try:
        sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts", "test"))
        from test_utils import get_knowledge_catalog_indexing_status
        indexing_info = get_knowledge_catalog_indexing_status(PROJECT_ID, DATASET_ID, token)
        denominator = table_count if table_count else "?"
        print(f"Catalog Indexing Status: {indexing_info['indexed_tables']}/{denominator} tables "
              f"({indexing_info['table_percentage']}%) [{indexing_info['status']}]")
    except Exception as exc:
        print(f"Catalog Indexing Status: unavailable ({exc})")

    found_agents, expected_agents = count_agents(token)
    if found_agents is None:
        print(f"Gemini Data Agents     : count unavailable ({expected_agents} configured)")
    elif found_agents == expected_agents:
        print(f"Gemini Data Agents     : {found_agents}/{expected_agents} agents verified present")
    else:
        print(f"Gemini Data Agents     : ⚠️ only {found_agents}/{expected_agents} agents found")

    print("=" * 80)

    if table_count is not None and table_count == 0:
        print("\n⚠️ The dataset reports zero tables. The install is NOT complete.",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
