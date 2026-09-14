#!/usr/bin/env python3
"""
BigQuery Table Export & Archival Script for LumièreShop.
Exports all tables from the BigQuery dataset (excluding agent_interaction_logs) to CSV files,
generates a README.md summary with table descriptions and record counts, and archives them into a tar.gz package.
"""

import os
import sys
import csv
import json
import tarfile
import subprocess
from datetime import datetime, timezone
from google.cloud import bigquery
from google.oauth2 import credentials as oauth2_credentials

def load_dotenv():
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())

load_dotenv()

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
DATASET_ID = os.environ.get("BQ_DATASET_ID", "ecommerce_dw")
LOCATION = os.environ.get("BQ_LOCATION", "europe-west4")

EXCLUDED_TABLES = {
    "agent_interaction_logs"
}

def get_bigquery_client(project_id):
    access_token = os.environ.get("GCP_ACCESS_TOKEN")
    if not access_token:
        gcloud_paths = ["/google/data/ro/teams/cloud-sdk/gcloud", "gcloud"]
        for gcloud_cmd in gcloud_paths:
            try:
                res = subprocess.run([gcloud_cmd, "auth", "print-access-token"], capture_output=True, text=True, timeout=10)
                if res.returncode == 0 and res.stdout.strip():
                    access_token = res.stdout.strip()
                    break
            except Exception:
                continue

    if access_token:
        print("Using authenticated gcloud OAuth token for BigQuery API...")
        creds = oauth2_credentials.Credentials(access_token)
        return bigquery.Client(project=project_id, credentials=creds)
    
    return bigquery.Client(project=project_id)

def format_cell_value(val):
    if val is None:
        return ""
    if isinstance(val, (datetime,)):
        return val.isoformat()
    if isinstance(val, (dict, list)):
        return json.dumps(val)
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return str(val)

def export_tables():
    workspace_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    exports_dir = os.path.join(workspace_root, "exports")
    csv_dir = os.path.join(exports_dir, "ecommerce_dw_csv")
    tar_path = os.path.join(exports_dir, "ecommerce_dw_tables.tar.gz")

    os.makedirs(csv_dir, exist_ok=True)

    print(f"Connecting to BigQuery project '{PROJECT_ID}', dataset '{DATASET_ID}' in '{LOCATION}'...")
    client = get_bigquery_client(PROJECT_ID)
    dataset_ref = bigquery.DatasetReference(PROJECT_ID, DATASET_ID)

    try:
        tables_list = list(client.list_tables(dataset_ref))
    except Exception as e:
        print(f"Error listing tables in dataset {DATASET_ID}: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(tables_list)} total tables in dataset '{DATASET_ID}'.")

    export_metadata = []
    total_records_exported = 0

    for idx, item in enumerate(tables_list, 1):
        table_id = item.table_id

        if table_id in EXCLUDED_TABLES:
            print(f"[{idx}/{len(tables_list)}] Skipping excluded table: `{table_id}`")
            continue

        try:
            table_obj = client.get_table(item.reference)
            description = (table_obj.description or "").strip() or "No description provided."
            csv_filename = f"{table_id}.csv"
            csv_filepath = os.path.join(csv_dir, csv_filename)

            schema_fields = [field.name for field in table_obj.schema]

            row_count = 0
            with open(csv_filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(schema_fields)

                rows_iter = client.list_rows(table_obj)
                for row in rows_iter:
                    row_count += 1
                    formatted_row = [format_cell_value(row[field]) for field in schema_fields]
                    writer.writerow(formatted_row)

            total_records_exported += row_count
            export_metadata.append({
                "table_id": table_id,
                "description": description,
                "row_count": row_count,
                "csv_file": csv_filename,
                "file_size_bytes": os.path.getsize(csv_filepath)
            })

            print(f"[{idx}/{len(tables_list)}] Exported `{table_id}`: {row_count:,} records -> {csv_filename} ({os.path.getsize(csv_filepath):,} bytes)")

        except Exception as e:
            print(f"Error exporting table `{table_id}`: {e}", file=sys.stderr)
            export_metadata.append({
                "table_id": table_id,
                "description": "Error during export",
                "row_count": 0,
                "csv_file": "N/A",
                "file_size_bytes": 0,
                "error": str(e)
            })

    # Sort tables alphabetically for clean documentation
    export_metadata.sort(key=lambda x: x["table_id"])

    # Generate README.md
    readme_path = os.path.join(csv_dir, "README.md")
    export_time_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    readme_content = f"""# BigQuery Dataset Export: `{DATASET_ID}`

## 📊 Export Summary
- **GCP Project ID**: `{PROJECT_ID}`
- **Dataset ID**: `{DATASET_ID}`
- **Location**: `{LOCATION}`
- **Export Timestamp**: `{export_time_utc}`
- **Total Tables Exported**: {len(export_metadata)}
- **Total Records Exported**: {total_records_exported:,}
- **Excluded Tables**: {", ".join(sorted(EXCLUDED_TABLES))}

---

## 📋 Table Catalog & Record Counts

| # | Table Name | Records | File Size | Description |
|---|---|---:|---:|---|
"""

    for i, meta in enumerate(export_metadata, 1):
        size_kb = meta["file_size_bytes"] / 1024
        desc_escaped = meta["description"].replace("\n", " ").replace("|", "\\|")
        readme_content += f"| {i} | `{meta['table_id']}` | {meta['row_count']:,} | {size_kb:,.1f} KB | {desc_escaped} |\n"

    readme_content += """
---
*Export generated automatically for LumièreShop data analysis and auditing.*
"""

    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme_content)

    print(f"\nGenerated export documentation: {readme_path}")

    # Create tar.gz archive
    print(f"\nPackaging CSV files and README.md into compressed tar archive: {tar_path}...")
    with tarfile.open(tar_path, "w:gz") as tar:
        # Add all files in csv_dir with relative path
        for root, _, files in os.walk(csv_dir):
            for file in sorted(files):
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, csv_dir)
                tar.add(full_path, arcname=rel_path)

    tar_size_bytes = os.path.getsize(tar_path)
    tar_size_mb = tar_size_bytes / (1024 * 1024)

    print("\n" + "="*70)
    print("EXPORT & ARCHIVAL COMPLETED SUCCESSFULLY")
    print("="*70)
    print(f"Archive Location: {tar_path}")
    print(f"Archive Size:     {tar_size_mb:.2f} MB ({tar_size_bytes:,} bytes)")
    print(f"Tables Exported:  {len(export_metadata)}")
    print(f"Total Records:    {total_records_exported:,}")
    print(f"Excluded:         {', '.join(EXCLUDED_TABLES)}")
    print("="*70)

if __name__ == "__main__":
    export_tables()
