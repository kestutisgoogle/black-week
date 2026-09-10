#!/usr/bin/env python3
"""
Knowledge Catalog Business Glossary Export Script
=================================================
Exports terms and categories from Google Cloud Knowledge Catalog global business
glossary (`ecommerce-glossary`) to RFC4180-compliant CSV files in the `export/` directory.

Target CSV Outputs:
1. `export/business-glossary.csv` (7-column terms schema):
   `term_display_name,description,steward,tagged_assets,synonyms,related_terms,belongs_to_category`

2. `export/categories.csv` (4-column categories schema):
   `category_display_name,description,steward,belongs_to_category`

Schema and format reference:
https://github.com/GoogleCloudPlatform/knowledge-catalog-labs/tree/main/dataplex-quickstart-labs/00-resources/scripts/python/business-glossary-import

Usage:
------
  # Standard export to export/business-glossary.csv and export/categories.csv
  python3 scripts/export_business_glossary_to_csv.py

  # Custom output paths and flags
  python3 scripts/export_business_glossary_to_csv.py \
    --output export/business-glossary.csv \
    --categories-csv export/categories.csv \
    --include-header
"""

import os
import sys
import csv
import json
import time
import argparse
import subprocess
import requests
from typing import Dict, List, Any, Optional, Tuple


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


def get_access_token() -> Optional[str]:
    """Retrieves Google Cloud OAuth access token via env or gcloud CLI."""
    token = os.environ.get("GCP_ACCESS_TOKEN")
    if token:
        return token

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
                return res.stdout.strip()
        except Exception:
            continue

    try:
        from google.auth import default
        from google.auth.transport.requests import Request
        creds, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(Request())
        if creds.token:
            return creds.token
    except Exception:
        pass

    return None


def api_request_with_retry(
    method: str,
    url: str,
    headers: dict,
    json_payload: dict = None,
    max_retries: int = 6
) -> Optional[requests.Response]:
    """
    Executes an HTTP request with exponential backoff for Knowledge Catalog API
    rate limits (HTTP 429) or quota throttling (HTTP 403).
    """
    res = None
    for attempt in range(max_retries):
        try:
            if method.upper() == "GET":
                res = requests.get(url, headers=headers, timeout=25)
            elif method.upper() == "POST":
                res = requests.post(url, headers=headers, json=json_payload, timeout=25)
            else:
                res = requests.request(method, url, headers=headers, json=json_payload, timeout=25)

            if res.status_code == 429 or (res.status_code == 403 and "quota" in res.text.lower()):
                retry_after = res.headers.get("Retry-After")
                if retry_after:
                    try:
                        backoff = float(retry_after) + 1.0
                    except ValueError:
                        backoff = 3.0 * (1.5 ** attempt)
                else:
                    backoff = 3.0 * (1.5 ** attempt)
                print(f"    ⏳ Rate limit encountered (HTTP {res.status_code}). Backing off {backoff:.1f}s ({attempt + 1}/{max_retries})...")
                time.sleep(backoff)
                continue
            elif res.status_code >= 500:
                time.sleep(2.0)
                continue

            return res
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2.0)
            else:
                print(f"    ⚠️ Request failed after retries: {e}", file=sys.stderr)
                return None
    return res


def load_local_glossary_metadata() -> Dict[str, Any]:
    """Loads local business glossary JSON definition as reference/fallback."""
    local_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config",
        "business_glossary.json"
    )
    if os.path.exists(local_path):
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                return json.load(f).get("glossary", {})
        except Exception as e:
            print(f"    ⚠️ Warning loading local glossary config: {e}")
    return {}


def parse_term_description(description_raw: str) -> Tuple[str, str, List[str]]:
    """
    Extracts definition, formula, and synonyms from Knowledge Catalog description block.
    Format deployed by 09_create_dataplex_glossary.py:
      {definition}
      Calculation Formula: {formula}
      Synonyms: {synonym1}, {synonym2}
    """
    if not description_raw:
        return "", "", []

    text = description_raw.strip()
    formula = ""
    synonyms: List[str] = []

    # Extract Synonyms if present
    if "Synonyms:" in text:
        parts = text.split("Synonyms:", 1)
        text = parts[0].strip()
        syn_raw = parts[1].strip()
        synonyms = [s.strip() for s in syn_raw.split(",") if s.strip()]

    # Extract Calculation Formula if present
    if "Calculation Formula:" in text:
        parts = text.split("Calculation Formula:", 1)
        text = parts[0].strip()
        formula = parts[1].strip()

    definition = text.strip()
    return definition, formula, synonyms


def fetch_live_glossary_data(
    project_id: str,
    location: str,
    glossary_id: str,
    bq_location: str,
    token: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, List[str]]]:
    """
    Queries Knowledge Catalog REST API for live categories, terms, and entry links.
    Returns (categories, terms, term_entrylinks_map).
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-goog-user-project": project_id,
    }

    base_url = f"https://dataplex.googleapis.com/v1/projects/{project_id}/locations/{location}/glossaries/{glossary_id}"

    # 1. Fetch Categories
    print(f"  Fetching Categories from Knowledge Catalog (`{glossary_id}` in `{location}`)...")
    categories = []
    page_token = None
    while True:
        cat_url = f"{base_url}/categories?pageSize=1000"
        if page_token:
            cat_url += f"&pageToken={page_token}"
        res = api_request_with_retry("GET", cat_url, headers)
        if res and res.status_code == 200:
            data = res.json()
            cats = data.get("categories", [])
            categories.extend(cats)
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        else:
            status = res.status_code if res else "ERR"
            print(f"    ⚠️ Unable to fetch live categories (HTTP {status}).")
            break

    # 2. Fetch Terms
    print(f"  Fetching Business Terms from Knowledge Catalog (`{glossary_id}` in `{location}`)...")
    terms = []
    page_token = None
    while True:
        term_url = f"{base_url}/terms?pageSize=1000"
        if page_token:
            term_url += f"&pageToken={page_token}"
        res = api_request_with_retry("GET", term_url, headers)
        if res and res.status_code == 200:
            data = res.json()
            t_list = data.get("terms", [])
            terms.extend(t_list)
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        else:
            status = res.status_code if res else "ERR"
            print(f"    ⚠️ Unable to fetch live terms (HTTP {status}).")
            break

    # 3. Fetch EntryLinks (Tagged Assets)
    print(f"  Fetching EntryLinks from Knowledge Catalog (EntryGroup: `@bigquery` in `{bq_location}`)...")
    entry_links_map: Dict[str, List[str]] = {}
    try:
        links_url = f"https://dataplex.googleapis.com/v1/projects/{project_id}/locations/{bq_location}/entryGroups/@bigquery/entryLinks?pageSize=1000"
        res = api_request_with_retry("GET", links_url, headers)
        if res and res.status_code == 200:
            data = res.json()
            links = data.get("entryLinks", [])
            for link in links:
                refs = link.get("entryReferences", [])
                source_table = ""
                target_term = ""
                for ref in refs:
                    ref_name = ref.get("name", "")
                    if ref.get("type") == "SOURCE" and "/tables/" in ref_name:
                        source_table = ref_name.split("/tables/")[-1]
                    elif ref.get("type") == "TARGET" and "/terms/" in ref_name:
                        target_term = ref_name.split("/terms/")[-1]

                if target_term and source_table:
                    entry_links_map.setdefault(target_term, []).append(source_table)
    except Exception as e:
        print(f"    ⚠️ EntryLinks query note: {e}")

    return categories, terms, entry_links_map


def build_export_records(
    live_categories: List[Dict[str, Any]],
    live_terms: List[Dict[str, Any]],
    entry_links_map: Dict[str, List[str]],
    local_glossary: Dict[str, Any],
    source_mode: str = "hybrid"
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """
    Harmonizes live Knowledge Catalog data with local definitions to produce
    RFC4180-compliant export rows for terms and categories.
    """
    local_cats_list = local_glossary.get("categories", [])
    local_terms_list = local_glossary.get("terms", [])

    local_cats_by_id = {c.get("id"): c for c in local_cats_list if c.get("id")}
    local_terms_by_id = {t.get("id"): t for t in local_terms_list if t.get("id")}
    local_terms_by_name = {t.get("display_name", "").strip().lower(): t for t in local_terms_list if t.get("display_name")}

    # Build Categories lookup table: ID -> display_name
    cat_id_to_display: Dict[str, str] = {}
    cat_rows: List[Dict[str, str]] = []

    # If live categories exist, use them; otherwise fallback to local
    processed_cat_ids = set()
    if source_mode in ["api", "hybrid"] and live_categories:
        for cat in live_categories:
            full_name = cat.get("name", "")
            cat_id = full_name.split("/categories/")[-1] if "/categories/" in full_name else cat.get("id", "")
            display_name = cat.get("displayName") or cat.get("display_name") or cat_id
            description = cat.get("description", "")
            cat_id_to_display[cat_id] = display_name
            processed_cat_ids.add(cat_id)

            # Local metadata enrichment for steward & parent
            local_c = local_cats_by_id.get(cat_id, {})
            steward = local_c.get("steward", f"LumièreShop Data Governance <governance@lumiereshop.internal>")
            parent_cat = local_c.get("belongs_to_category", "")

            cat_rows.append({
                "category_display_name": display_name,
                "description": description,
                "steward": steward,
                "belongs_to_category": parent_cat,
            })

    # Add any local categories not in live API
    for c in local_cats_list:
        cid = c.get("id")
        if cid and cid not in processed_cat_ids:
            display_name = c.get("display_name", cid)
            cat_id_to_display[cid] = display_name
            cat_rows.append({
                "category_display_name": display_name,
                "description": c.get("description", ""),
                "steward": c.get("steward", "LumièreShop Data Governance <governance@lumiereshop.internal>"),
                "belongs_to_category": c.get("belongs_to_category", ""),
            })

    # Group terms by category to infer related_terms
    terms_by_category: Dict[str, List[str]] = {}
    for t in local_terms_list:
        cid = t.get("category_id", "")
        if cid:
            terms_by_category.setdefault(cid, []).append(t.get("display_name", ""))

    # Process Business Terms
    term_rows: List[Dict[str, str]] = []
    processed_term_ids = set()

    if source_mode in ["api", "hybrid"] and live_terms:
        for term in live_terms:
            full_name = term.get("name", "")
            term_id = full_name.split("/terms/")[-1] if "/terms/" in full_name else term.get("id", "")
            display_name = term.get("displayName") or term.get("display_name") or term_id
            raw_desc = term.get("description", "")

            # Parse compound description
            definition, formula, parsed_synonyms = parse_term_description(raw_desc)

            # Match local metadata
            local_t = local_terms_by_id.get(term_id) or local_terms_by_name.get(display_name.strip().lower(), {})

            # 1. Clean description
            clean_desc = definition if definition else local_t.get("definition", raw_desc)

            # 2. Steward
            steward = local_t.get("steward", "LumièreShop Data Governance <governance@lumiereshop.internal>")

            # 3. Tagged assets (combine EntryLinks and local column bindings)
            tagged_assets_set = set()
            # From live EntryLinks
            for t_name in entry_links_map.get(term_id, []):
                tagged_assets_set.add(t_name)
            # From local bindings (table:column format per reference schema)
            for b in local_t.get("bindings", []):
                tbl = b.get("table", "")
                col = b.get("column", "")
                if tbl and col:
                    tagged_assets_set.add(f"{tbl}:{col}")
                elif tbl:
                    tagged_assets_set.add(tbl)
            tagged_assets_str = ", ".join(sorted(list(tagged_assets_set)))

            # 4. Synonyms
            synonyms_list = local_t.get("synonyms") or parsed_synonyms
            synonyms_str = ", ".join(synonyms_list) if synonyms_list else ""

            # 5. Belongs to Category
            cat_id = local_t.get("category_id", "")
            belongs_to_category = cat_id_to_display.get(cat_id, "")
            if not belongs_to_category and cat_id:
                belongs_to_category = cat_id.replace("_", " ").title()

            # 6. Related Terms (terms sharing the same category/domain)
            related_terms_list = [t_name for t_name in terms_by_category.get(cat_id, []) if t_name != display_name][:5]
            related_terms_str = ", ".join(related_terms_list)

            term_rows.append({
                "term_display_name": display_name,
                "description": clean_desc,
                "steward": steward,
                "tagged_assets": tagged_assets_str,
                "synonyms": synonyms_str,
                "related_terms": related_terms_str,
                "belongs_to_category": belongs_to_category,
            })
            processed_term_ids.add(term_id)

    # If in local or hybrid mode, append any local terms that were missing from API
    if source_mode in ["local", "hybrid"]:
        for t in local_terms_list:
            tid = t.get("id")
            if tid and tid not in processed_term_ids:
                display_name = t.get("display_name", tid)
                cat_id = t.get("category_id", "")
                belongs_to_category = cat_id_to_display.get(cat_id, "")
                if not belongs_to_category and cat_id:
                    belongs_to_category = cat_id.replace("_", " ").title()

                tagged_assets_list = []
                for b in t.get("bindings", []):
                    tbl = b.get("table", "")
                    col = b.get("column", "")
                    if tbl and col:
                        tagged_assets_list.append(f"{tbl}:{col}")
                    elif tbl:
                        tagged_assets_list.append(tbl)

                related_terms_list = [name for name in terms_by_category.get(cat_id, []) if name != display_name][:5]

                term_rows.append({
                    "term_display_name": display_name,
                    "description": t.get("definition", ""),
                    "steward": t.get("steward", "LumièreShop Data Governance <governance@lumiereshop.internal>"),
                    "tagged_assets": ", ".join(tagged_assets_list),
                    "synonyms": ", ".join(t.get("synonyms", [])),
                    "related_terms": ", ".join(related_terms_list),
                    "belongs_to_category": belongs_to_category,
                })
                processed_term_ids.add(tid)

    # Sort predictably by category and term name
    term_rows.sort(key=lambda r: (r["belongs_to_category"], r["term_display_name"]))
    cat_rows.sort(key=lambda r: r["category_display_name"])

    return term_rows, cat_rows


def export_csv(
    filepath: str,
    fieldnames: List[str],
    rows: List[Dict[str, str]],
    include_header: bool = True
):
    """Writes records to an RFC4180-compliant UTF-8 CSV file."""
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            quoting=csv.QUOTE_MINIMAL,
            lineterminator="\n"
        )
        if include_header:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(
        description="Export Google Cloud Knowledge Catalog Business Glossary terms & categories to RFC4180 CSV."
    )
    parser.add_argument(
        "-o", "--output",
        default="export/business-glossary.csv",
        help="Destination path for terms CSV file (default: export/business-glossary.csv)"
    )
    parser.add_argument(
        "--categories-csv",
        default="export/categories.csv",
        help="Destination path for categories CSV file (default: export/categories.csv)"
    )
    parser.add_argument(
        "--project",
        default=os.environ.get("GCP_PROJECT_ID", ""),
        help="Google Cloud Project ID (default: read from .env GCP_PROJECT_ID)"
    )
    parser.add_argument(
        "--location",
        default="global",
        help="Knowledge Catalog glossary location (default: global)"
    )
    parser.add_argument(
        "--glossary",
        default="ecommerce-glossary",
        help="Knowledge Catalog glossary ID (default: ecommerce-glossary)"
    )
    parser.add_argument(
        "--bq-location",
        default=os.environ.get("BQ_LOCATION", "us-central1"),
        help="BigQuery / EntryGroup location for EntryLinks (default: us-central1)"
    )
    parser.add_argument(
        "--include-header",
        dest="include_header",
        action="store_true",
        default=True,
        help="Include header line in output CSV (default: True)"
    )
    parser.add_argument(
        "--no-header",
        dest="include_header",
        action="store_false",
        help="Omit header line in output CSV"
    )
    parser.add_argument(
        "--source",
        choices=["hybrid", "api", "local"],
        default="hybrid",
        help="Data extraction source mode: hybrid (API + local metadata enrichment), api (live GCP only), or local (offline fallback)"
    )

    args = parser.parse_args()

    project_id = args.project
    location = args.location
    glossary_id = args.glossary
    bq_location = args.bq_location
    source_mode = args.source

    print("=" * 80)
    print("Google Cloud Knowledge Catalog Business Glossary Export")
    print("=" * 80)
    print(f"Project ID:    {project_id or 'None (Offline / Local Mode)'}")
    print(f"Glossary ID:   {glossary_id}")
    print(f"Location:      {location}")
    print(f"Source Mode:   {source_mode}")
    print(f"Terms CSV:     {args.output}")
    print(f"Categories CSV:{args.categories_csv}")
    print(f"CSV Header:    {'Enabled' if args.include_header else 'Disabled'}")
    print("-" * 80)

    live_categories = []
    live_terms = []
    entry_links_map = {}

    local_glossary = load_local_glossary_metadata()

    # Attempt live API connection if in hybrid or api mode
    if source_mode in ["hybrid", "api"] and project_id:
        token = get_access_token()
        if token:
            print("🔑 Authenticated via OAuth token. Fetching live metadata from Google Cloud...")
            try:
                live_categories, live_terms, entry_links_map = fetch_live_glossary_data(
                    project_id=project_id,
                    location=location,
                    glossary_id=glossary_id,
                    bq_location=bq_location,
                    token=token
                )
                print(f"  ✅ Live Knowledge Catalog data retrieved: {len(live_categories)} categories, {len(live_terms)} terms.")
            except Exception as e:
                print(f"  ⚠️ Error during live Knowledge Catalog extraction: {e}")
                if source_mode == "api":
                    print("❌ Aborting since --source=api was requested.", file=sys.stderr)
                    sys.exit(1)
        else:
            print("⚠️ No GCP access token available. Proceeding in fallback mode.")
            if source_mode == "api":
                print("❌ Error: Valid GCP OAuth access token required for --source=api.", file=sys.stderr)
                sys.exit(1)

    # Harmonize records
    term_fieldnames = [
        "term_display_name",
        "description",
        "steward",
        "tagged_assets",
        "synonyms",
        "related_terms",
        "belongs_to_category"
    ]
    cat_fieldnames = [
        "category_display_name",
        "description",
        "steward",
        "belongs_to_category"
    ]

    term_rows, cat_rows = build_export_records(
        live_categories=live_categories,
        live_terms=live_terms,
        entry_links_map=entry_links_map,
        local_glossary=local_glossary,
        source_mode=source_mode
    )

    # Write Terms CSV
    export_csv(args.output, term_fieldnames, term_rows, include_header=args.include_header)
    print(f"\n✅ Exported {len(term_rows)} Business Terms to `{args.output}`")

    # Write Categories CSV
    if args.categories_csv:
        export_csv(args.categories_csv, cat_fieldnames, cat_rows, include_header=args.include_header)
        print(f"✅ Exported {len(cat_rows)} Glossary Categories to `{args.categories_csv}`")

    print("\n" + "=" * 80)
    print(f"Export Complete! Files created in `{os.path.dirname(os.path.abspath(args.output))}`")
    print("=" * 80)


if __name__ == "__main__":
    main()
