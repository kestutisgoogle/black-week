#!/usr/bin/env python3
"""
BigQuery Dataset Reset (DESTRUCTIVE)
====================================
Drops the three LumièreShop BigQuery datasets and every table inside them, so
that the provisioning pipeline can rebuild them from a genuinely clean slate.

Why this script exists
----------------------
`scripts/01_create_schema.py` creates tables with `create_table(exists_ok=True)`.
That is correct for a brand-new project, but it means an *existing* project keeps
its old table schemas forever: a renamed or added column in the code is silently
ignored, and the subsequent data load then fails (or writes into the wrong shape).

Without this reset the pipeline is only deterministic against an empty project.
With it, the pipeline is deterministic against any project.

What is destroyed
-----------------
  * ${BQ_DATASET_ID}      (Tier A - full Knowledge Catalog)
  * ${BQ_DATASET_2ND_ID}  (Tier B - column descriptions only)
  * ${BQ_DATASET_3RD_ID}  (Tier C - raw schema)

...including `agent_interaction_logs`, which is NOT regenerable. Chat history
from previous demo runs is permanently lost. This was an explicit, accepted
trade-off when the reset stage was introduced.

Knowledge Catalog glossary terms, EntryLinks and Aspects are NOT touched here;
they are managed by `scripts/09_create_dataplex_glossary.py` and
`scripts/cleanup_knowledge_catalog.py`.

Safety guards
-------------
This script refuses to run unless one of the following is true:
  1. `--force` was passed on the command line, or
  2. `BOOTSTRAP_RESET_CONFIRMED=1` is set in the environment (used by
     `bootstrap_new_project.py` after it has already confirmed with the operator), or
  3. the operator interactively types the target project ID exactly.

Usage
-----
  python3 scripts/00_reset_datasets.py            # interactive confirmation
  python3 scripts/00_reset_datasets.py --force    # non-interactive
  python3 scripts/00_reset_datasets.py --dry-run  # report only, destroy nothing
"""

import argparse
import os
import sys


def load_dotenv():
    """Parses the root-level .env file into os.environ (no external dependency)."""
    env_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
    )
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip("'\""))


load_dotenv()

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
LOCATION = os.environ.get("BQ_LOCATION", "europe-west4")
DATASETS = [
    os.environ.get("BQ_DATASET_ID", "ecommerce_dw"),
    os.environ.get("BQ_DATASET_2ND_ID", "ecommerce_dw_2nd"),
    os.environ.get("BQ_DATASET_3RD_ID", "ecommerce_dw_3rd"),
]


def survey(client):
    """Reports what currently exists, without changing anything."""
    report = []
    for dataset_id in DATASETS:
        fqid = f"{PROJECT_ID}.{dataset_id}"
        try:
            client.get_dataset(fqid)
            tables = list(client.list_tables(fqid))
            report.append((dataset_id, True, len(tables)))
        except Exception:
            report.append((dataset_id, False, 0))
    return report


def confirm(report) -> bool:
    """Applies the three safety guards. Returns True when the reset may proceed."""
    if os.environ.get("BOOTSTRAP_RESET_CONFIRMED") == "1":
        print("   Confirmation inherited from bootstrap_new_project.py.")
        return True

    print("\n⚠️  You are about to PERMANENTLY DELETE the datasets listed above.")
    print("   `agent_interaction_logs` chat history cannot be recovered.")
    print(f"\n   Type the project ID exactly to proceed: {PROJECT_ID}")
    try:
        typed = input("   > ").strip()
    except EOFError:
        print("\n❌ Aborted: no interactive terminal available. "
              "Re-run with --force to reset non-interactively.", file=sys.stderr)
        return False
    if typed != PROJECT_ID:
        print("❌ Aborted: the value you typed did not match the project ID.", file=sys.stderr)
        return False
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Drop the three LumièreShop BigQuery datasets (DESTRUCTIVE)."
    )
    parser.add_argument("--force", action="store_true",
                        help="Skip the interactive confirmation prompt.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be dropped and exit without deleting.")
    args = parser.parse_args()

    if not PROJECT_ID or PROJECT_ID == "your-gcp-project-id":
        print("❌ Error: GCP_PROJECT_ID is not configured in .env.", file=sys.stderr)
        sys.exit(1)

    from google.cloud import bigquery
    client = bigquery.Client(project=PROJECT_ID)

    print("=" * 80)
    print("🧨 BIGQUERY DATASET RESET (DESTRUCTIVE)")
    print(f"Target Project : {PROJECT_ID}")
    print(f"Location       : {LOCATION}")
    print("=" * 80)

    report = survey(client)
    total_tables = 0
    for dataset_id, exists, n_tables in report:
        if exists:
            total_tables += n_tables
            print(f"  • {dataset_id:<22} EXISTS  → {n_tables} tables will be destroyed")
        else:
            print(f"  • {dataset_id:<22} absent  → nothing to do")

    if total_tables == 0 and not any(e for _, e, _ in report):
        print("\n✅ Nothing to reset; all three datasets are already absent.")
        return

    if args.dry_run:
        print(f"\n[DRY-RUN] Would delete {total_tables} tables across "
              f"{sum(1 for _, e, _ in report if e)} datasets. Nothing was changed.")
        return

    if not args.force and not confirm(report):
        sys.exit(1)

    print()
    for dataset_id, exists, n_tables in report:
        if not exists:
            continue
        fqid = f"{PROJECT_ID}.{dataset_id}"
        client.delete_dataset(fqid, delete_contents=True, not_found_ok=True)
        print(f"  🗑️  Deleted dataset `{dataset_id}` ({n_tables} tables).")

    # Verify the deletion actually took effect rather than trusting the API call.
    print("\n🔍 Verifying...")
    leftover = [d for d, exists, _ in survey(client) if exists]
    if leftover:
        print(f"❌ Reset incomplete; these datasets still exist: {leftover}", file=sys.stderr)
        sys.exit(1)

    print("✅ All target datasets removed. The project is ready for a clean rebuild.")


if __name__ == "__main__":
    main()
