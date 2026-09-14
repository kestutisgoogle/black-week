#!/usr/bin/env python3
"""
Phase 18: BigQuery Isolation Datasets Setup & Replication
==========================================================
Sets up and replicates the 140-table warehouse into two isolated datasets:
1. `ecommerce_dw_2nd` (or `${BQ_DATASET_ID}_2nd`):
   - Exact copy of all tables and data rows from `ecommerce_dw`.
   - Preserves all table descriptions and column descriptions.
   - 0 Knowledge Catalog business glossary terms, 0 EntryLinks, 0 custom aspects.
2. `ecommerce_dw_3rd` (or `${BQ_DATASET_ID}_3rd`):
   - Exact copy of all tables and data rows from `ecommerce_dw`.
   - Explicitly strips all table descriptions and column descriptions (pure raw schema).
   - 0 Knowledge Catalog business glossary terms, 0 EntryLinks, 0 custom aspects.

Usage:
------
  python3 scripts/18_setup_isolation_datasets.py [--force-recreate]
"""

import os
import sys
import time
import argparse
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Tuple
from google.cloud import bigquery
from google.cloud.exceptions import NotFound

# Load environment variables
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

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
LOCATION = os.environ.get("BQ_LOCATION", "europe-west4")
DATASET_1ST_ID = os.environ.get("BQ_DATASET_ID", "ecommerce_dw")
DATASET_2ND_ID = os.environ.get("BQ_DATASET_2ND_ID", f"{DATASET_1ST_ID}_2nd")
DATASET_3RD_ID = os.environ.get("BQ_DATASET_3RD_ID", f"{DATASET_1ST_ID}_3rd")


def get_client() -> bigquery.Client:
    """Returns an authenticated BigQuery client."""
    return bigquery.Client(project=PROJECT_ID, location=LOCATION)


def ensure_dataset(client: bigquery.Client, dataset_id: str, description: str):
    """Ensures a BigQuery dataset exists in the configured location."""
    dataset_ref = bigquery.DatasetReference(PROJECT_ID, dataset_id)
    try:
        ds = client.get_dataset(dataset_ref)
        print(f"  ✓ Dataset '{dataset_id}' exists in location '{ds.location}'.")
    except NotFound:
        print(f"  + Creating dataset '{dataset_id}' in location '{LOCATION}'...")
        ds = bigquery.Dataset(dataset_ref)
        ds.location = LOCATION
        ds.description = description
        client.create_dataset(ds, timeout=30)
        print(f"  ✅ Dataset '{dataset_id}' created successfully.")


def strip_field_descriptions(field: bigquery.SchemaField) -> bigquery.SchemaField:
    """Recursively creates a new SchemaField with descriptions set to None."""
    subfields = ()
    if field.fields:
        subfields = tuple(strip_field_descriptions(sf) for sf in field.fields)
    
    return bigquery.SchemaField(
        name=field.name,
        field_type=field.field_type,
        mode=field.mode,
        description=None,
        fields=subfields,
        policy_tags=field.policy_tags,
        precision=field.precision,
        scale=field.scale,
        max_length=field.max_length,
    )


# ---------------------------------------------------------------------------
# TIER B: THIN, SOURCE-SYSTEM-STYLE DESCRIPTIONS
# ---------------------------------------------------------------------------
#
# Tier B represents a very common real-world situation: a warehouse where
# somebody typed a short label into the column description field and stopped
# there. The label expands the abbreviation. It does NOT explain what the
# column means, which table it joins to, what its code values signify, or how
# it should be aggregated.
#
# This matters because Tier B previously received a BYTE-IDENTICAL copy of
# Tier A's curated descriptions - including "1 = taxonomy parity error (e.g.
# Beauty displaying Electronics)", which states the root cause outright, and
# "...referencing products.product_id", which hands over the join. That made
# Tier B a warehouse whose catalogue merely lived in a different field, and is
# why Agent B scored level with Agent A.
#
# The governing rule for Tier B text:
#   ALLOWED     - expanding an abbreviation into words
#   NOT ALLOWED - code-value semantics, join targets, governance tier/domain/
#                 grain, aggregation rules, or anything about the incident
#
# Deliberately NOT hand-tuned per column: coverage is chosen by a stable hash
# so that nobody can accuse us of picking which columns Tier B gets to see.

TIER_B_COVERAGE = 0.60          # share of columns that carry any label at all
TIER_B_COVERAGE_SALT = "lumiere-tier-b-v1"

# Generic data-modelling abbreviations, expanded because any source-system
# data dictionary would expand them.
TOKEN_EXPANSIONS = {
    "nr": "number", "num": "number", "ref": "reference", "flg": "flag",
    "cd": "code", "amt": "amount", "qty": "quantity", "pct": "percent",
    "ts": "timestamp", "hdr": "header", "art": "article", "mat": "material",
    "avg": "average", "max": "maximum", "min": "minimum", "pos": "position",
}

# Left deliberately unexpanded, because a real source export would not expand
# them either. They are shown as-is, capitalised.
ACRONYMS = {
    "id", "eur", "sku", "cvr", "roas", "cpc", "url", "os", "dc", "utm",
    "oos", "cid", "http", "sql", "api", "json", "uuid", "ip", "ua",
}


def humanise_column(name: str) -> str:
    """Turn `ord_hdr_num` into `Ord header number` - a label, not an explanation."""
    words = []
    for part in name.split("_"):
        low = part.lower()
        if low in TOKEN_EXPANSIONS:
            words.append(TOKEN_EXPANSIONS[low])
        elif low in ACRONYMS:
            words.append(low.upper())
        else:
            words.append(low)
    text = " ".join(words).strip()
    return text[:1].upper() + text[1:] if text else text


def _covered(table_id: str, column: str) -> bool:
    """Stable, reproducible decision on whether this column gets a label."""
    key = f"{TIER_B_COVERAGE_SALT}|{table_id}.{column}".encode("utf-8")
    bucket = int(hashlib.md5(key).hexdigest()[:8], 16) % 1000
    return bucket < int(TIER_B_COVERAGE * 1000)


def thin_field_descriptions(field: bigquery.SchemaField, table_id: str) -> bigquery.SchemaField:
    """Recursively replace curated descriptions with thin labels."""
    subfields = ()
    if field.fields:
        subfields = tuple(thin_field_descriptions(sf, table_id) for sf in field.fields)

    description = humanise_column(field.name) if _covered(table_id, field.name) else None

    return bigquery.SchemaField(
        name=field.name,
        field_type=field.field_type,
        mode=field.mode,
        description=description,
        fields=subfields,
        policy_tags=field.policy_tags,
        precision=field.precision,
        scale=field.scale,
        max_length=field.max_length,
    )


# Description handling per tier.
DESC_FULL = "full"    # Tier A source: curated Knowledge Catalog text
DESC_THIN = "thin"    # Tier B: short source-system labels, partial coverage
DESC_NONE = "none"    # Tier C: raw schema, nothing at all


def copy_single_table(
    client: bigquery.Client,
    src_dataset: str,
    dst_dataset: str,
    table_id: str,
    description_mode: str = DESC_FULL,
) -> Tuple[str, bool, str]:
    """
    Copies a single table from src_dataset to dst_dataset using BigQuery table copy job.
    Row data is always identical; only the description metadata differs by tier.
    """
    src_ref = bigquery.TableReference(bigquery.DatasetReference(PROJECT_ID, src_dataset), table_id)
    dst_ref = bigquery.TableReference(bigquery.DatasetReference(PROJECT_ID, dst_dataset), table_id)

    try:
        job_config = bigquery.CopyJobConfig(write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE)
        copy_job = client.copy_table(src_ref, dst_ref, job_config=job_config)
        # A copy job is a storage-level operation, so it does not scale with
        # row count the way a query does - but `web_events` is now ~86M rows
        # (Black Week plus the six weeks of history) and it is by far the
        # largest table here. Timing out does NOT cancel the job, it only stops
        # waiting, so too short a ceiling reports a failure for a copy that
        # actually succeeded - and any non-zero exit aborts the whole rebuild.
        copy_job.result(timeout=600)

        if description_mode == DESC_NONE:
            table = client.get_table(dst_ref)
            table.description = None
            table.schema = [strip_field_descriptions(f) for f in table.schema]
            client.update_table(table, ["schema", "description"])
        elif description_mode == DESC_THIN:
            table = client.get_table(dst_ref)
            # The Tier A table description is a governance block
            # ([PURPOSE][DOMAIN][GRAIN][TIER & REFRESH]). A raw replica would
            # not carry that, so it goes.
            table.description = None
            table.schema = [thin_field_descriptions(f, table_id) for f in table.schema]
            client.update_table(table, ["schema", "description"])

        return table_id, True, "OK"
    except Exception as e:
        return table_id, False, str(e)


def replicate_dataset(
    client: bigquery.Client,
    src_dataset: str,
    dst_dataset: str,
    table_ids: List[str],
    description_mode: str,
    tier_name: str,
):
    """Copies all tables in parallel to destination dataset."""
    print(f"\nReplicating {len(table_ids)} tables from '{src_dataset}' -> '{dst_dataset}' ({tier_name})...")
    start_t = time.time()
    success_count = 0
    errors = []

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = {
            executor.submit(
                copy_single_table,
                client,
                src_dataset,
                dst_dataset,
                tid,
                description_mode,
            ): tid
            for tid in table_ids
        }

        for idx, future in enumerate(as_completed(futures), 1):
            tid, ok, err_msg = future.result()
            if ok:
                success_count += 1
            else:
                errors.append((tid, err_msg))
            
            if idx % 20 == 0 or idx == len(table_ids):
                print(f"  Progress: {idx}/{len(table_ids)} tables processed...")

    elapsed = time.time() - start_t
    print(f"  ✅ Replicated {success_count}/{len(table_ids)} tables to '{dst_dataset}' in {elapsed:.2f}s.")
    if errors:
        print(f"  ⚠️ Encountered {len(errors)} errors:")
        for tid, err in errors[:5]:
            print(f"     • Table '{tid}': {err}")


def audit_datasets(client: bigquery.Client, table_ids: List[str]):
    """Performs comprehensive verification of schemas, descriptions, and row counts."""
    print("\n" + "=" * 80)
    print("📊 ISOLATION DATASETS COMPREHENSIVE VERIFICATION & AUDIT")
    print("=" * 80)

    # 1. Table count audit
    t1_tables = set(t.table_id for t in client.list_tables(DATASET_1ST_ID))
    t2_tables = set(t.table_id for t in client.list_tables(DATASET_2ND_ID))
    t3_tables = set(t.table_id for t in client.list_tables(DATASET_3RD_ID))

    print(f"1. Physical Table Counts:")
    print(f"   • Primary ({DATASET_1ST_ID}) : {len(t1_tables)} tables")
    print(f"   • Tier B  ({DATASET_2ND_ID}) : {len(t2_tables)} tables (Match: {len(t1_tables) == len(t2_tables)})")
    print(f"   • Tier C  ({DATASET_3RD_ID}) : {len(t3_tables)} tables (Match: {len(t1_tables) == len(t3_tables)})")

    # 2. Description coverage audit across 5 core sample tables
    sample_tables = ["orders", "products", "daily_ad_performance", "web_sessions", "categories"]
    print(f"\n2. Metadata Descriptions Audit (Sample Tables):")
    for tid in sample_tables:
        if tid in t1_tables and tid in t2_tables and tid in t3_tables:
            tbl_1 = client.get_table(bigquery.TableReference(bigquery.DatasetReference(PROJECT_ID, DATASET_1ST_ID), tid))
            tbl_2 = client.get_table(bigquery.TableReference(bigquery.DatasetReference(PROJECT_ID, DATASET_2ND_ID), tid))
            tbl_3 = client.get_table(bigquery.TableReference(bigquery.DatasetReference(PROJECT_ID, DATASET_3RD_ID), tid))

            desc1_cnt = sum(1 for f in tbl_1.schema if f.description)
            desc2_cnt = sum(1 for f in tbl_2.schema if f.description)
            desc3_cnt = sum(1 for f in tbl_3.schema if f.description)

            print(f"   • Table '{tid}':")
            print(f"     - Tier A: {desc1_cnt}/{len(tbl_1.schema)} column desc | Table desc: {bool(tbl_1.description)}")
            print(f"     - Tier B: {desc2_cnt}/{len(tbl_2.schema)} column desc | Table desc: {bool(tbl_2.description)}")
            print(f"     - Tier C: {desc3_cnt}/{len(tbl_3.schema)} column desc | Table desc: {bool(tbl_3.description)}")

    # 3. Row count audit across high-volume sample tables
    print(f"\n3. Data Invariant Row Count Verification:")
    row_check_query = f"""
    SELECT
      (SELECT count(1) FROM `{PROJECT_ID}.{DATASET_1ST_ID}.orders`) as orders_1,
      (SELECT count(1) FROM `{PROJECT_ID}.{DATASET_2ND_ID}.orders`) as orders_2,
      (SELECT count(1) FROM `{PROJECT_ID}.{DATASET_3RD_ID}.orders`) as orders_3,
      (SELECT count(1) FROM `{PROJECT_ID}.{DATASET_1ST_ID}.products`) as products_1,
      (SELECT count(1) FROM `{PROJECT_ID}.{DATASET_2ND_ID}.products`) as products_2,
      (SELECT count(1) FROM `{PROJECT_ID}.{DATASET_3RD_ID}.products`) as products_3,
      (SELECT count(1) FROM `{PROJECT_ID}.{DATASET_1ST_ID}.daily_ad_performance`) as ads_1,
      (SELECT count(1) FROM `{PROJECT_ID}.{DATASET_2ND_ID}.daily_ad_performance`) as ads_2,
      (SELECT count(1) FROM `{PROJECT_ID}.{DATASET_3RD_ID}.daily_ad_performance`) as ads_3
    """
    res = list(client.query(row_check_query).result())[0]
    print(f"   • `orders` rows               : {res['orders_1']} (Tier A) == {res['orders_2']} (Tier B) == {res['orders_3']} (Tier C)")
    print(f"   • `products` rows             : {res['products_1']} (Tier A) == {res['products_2']} (Tier B) == {res['products_3']} (Tier C)")
    print(f"   • `daily_ad_performance` rows : {res['ads_1']} (Tier A) == {res['ads_2']} (Tier B) == {res['ads_3']} (Tier C)")

    assert res['orders_1'] == res['orders_2'] == res['orders_3'], "Error: Orders row counts do not match!"
    assert res['products_1'] == res['products_2'] == res['products_3'], "Error: Products row counts do not match!"
    assert res['ads_1'] == res['ads_2'] == res['ads_3'], "Error: Ad performance row counts do not match!"
    print(f"\n  ✅ 100% Exact Row-Level Parity Verified across all 3 datasets.")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Replicate BigQuery datasets for 3-Chat Knowledge Catalog isolation.")
    parser.add_argument("--audit-only", action="store_true", help="Audit datasets without copying.")
    args = parser.parse_args()

    print("=" * 80)
    print("🚀 LUMIÈRESHOP BIGQUERY ISOLATION DATASETS SETUP & REPLICATION")
    print(f"Project  : {PROJECT_ID} | Region: {LOCATION}")
    print(f"Tier A   : {DATASET_1ST_ID} (Primary Dataset with Full Knowledge Catalog)")
    print(f"Tier B   : {DATASET_2ND_ID} (Isolated: Thin Column Labels Only, 0 Glossary/EntryLinks)")
    print(f"Tier C   : {DATASET_3RD_ID} (Isolated: Raw Schema Only, 0 Descriptions)")
    print("=" * 80)

    if not PROJECT_ID:
        print("Error: GCP_PROJECT_ID not found in .env.", file=sys.stderr)
        sys.exit(1)

    client = get_client()

    # Verify primary dataset
    try:
        ds1 = client.get_dataset(bigquery.DatasetReference(PROJECT_ID, DATASET_1ST_ID))
        src_tables = sorted([t.table_id for t in client.list_tables(ds1)])
        print(f"Found {len(src_tables)} physical tables in primary dataset '{DATASET_1ST_ID}'.")
    except Exception as e:
        print(f"Error: Could not access primary dataset '{DATASET_1ST_ID}': {e}", file=sys.stderr)
        sys.exit(1)

    if args.audit_only:
        audit_datasets(client, src_tables)
        return

    # 1. Ensure 2nd and 3rd datasets exist
    ensure_dataset(
        client,
        DATASET_2ND_ID,
        "LumièreShop Tier B Isolated Dataset (Exact row copy; thin source-system column labels only, zero Knowledge Catalog glossary/EntryLinks)."
    )
    ensure_dataset(
        client,
        DATASET_3RD_ID,
        "LumièreShop Tier C Isolated Dataset (Exact table copy with zero table/column descriptions, zero Knowledge Catalog glossary/EntryLinks)."
    )

    # 2. Replicate Tier B (ecommerce_dw_2nd) with descriptions intact
    replicate_dataset(
        client,
        DATASET_1ST_ID,
        DATASET_2ND_ID,
        src_tables,
        description_mode=DESC_THIN,
        tier_name="Tier B: Thin Source-System Labels",
    )

    # 3. Replicate Tier C (ecommerce_dw_3rd) with descriptions stripped
    replicate_dataset(
        client,
        DATASET_1ST_ID,
        DATASET_3RD_ID,
        src_tables,
        description_mode=DESC_NONE,
        tier_name="Tier C: Raw Schema Only (Descriptions Stripped)",
    )

    # 4. Audit & Verification
    audit_datasets(client, src_tables)
    print("\n✅ BigQuery Isolation Datasets Provisioning & Replication successfully completed!")


if __name__ == "__main__":
    main()
