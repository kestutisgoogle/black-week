#!/usr/bin/env python3
"""
Phase 4: BigQuery Interaction Log Schema Extension Script
==========================================================
Adds rich diagnostic telemetry columns to the `agent_interaction_logs` BigQuery table,
enabling deep auditability of Gemini Conversational Analytics reasoning traces,
job IDs, bytes billed, slot milliseconds, chart types, and referenced warehouse tables.

Usage:
------
  python3 scripts/04_extend_log_schema.py
"""

import os
import sys
from google.cloud import bigquery


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
TABLE_ID = "agent_interaction_logs"

def extend_schema():
    client = bigquery.Client(project=PROJECT_ID)
    table_ref = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
    table = client.get_table(table_ref)

    existing_field_names = {field.name for field in table.schema}

    new_fields = [
        bigquery.SchemaField("job_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("bytes_billed", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("slot_milliseconds", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("referenced_tables", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("result_row_count", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("thinking_process", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("step_count", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("has_chart", "BOOLEAN", mode="NULLABLE"),
        bigquery.SchemaField("chart_type", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("followup_questions", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("data_agent_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("http_status_code", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("thinking_mode", "STRING", mode="NULLABLE"),
    ]

    schema = list(table.schema)
    added_count = 0
    for field in new_fields:
        if field.name not in existing_field_names:
            schema.append(field)
            added_count += 1

    if added_count > 0:
        table.schema = schema
        client.update_table(table, ["schema"])
        print(f"Successfully added {added_count} new metadata columns to {table_ref}!")
    else:
        print("Schema already contains all extended metadata columns.")

if __name__ == "__main__":
    extend_schema()
