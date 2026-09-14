#!/usr/bin/env python3
"""
Phase 9: Google Cloud Knowledge Catalog Business Glossary & EntryLinks Deployment Script
========================================================================================
Creates and deploys the enterprise Business Glossary (`ecommerce-glossary`),
glossary categories, and term nodes in Google Cloud Knowledge Catalog (location: `global`).
Terms contain clean business definitions, formulas, and synonyms.
Physical table/column relationships are provisioned natively as Knowledge Catalog EntryLinks
connecting BigQuery table entries to their respective business terms.

This script will REFUSE to run if scripts/verify_metadata_integrity.py
reports any finding. Metadata that contradicts the warehouse is worse than
no metadata, so the check is a hard gate rather than a warning.

Usage:
------
  python3 scripts/09_create_dataplex_glossary.py
"""

import os
import sys
import time
import subprocess
import requests
import json
import hashlib
import yaml


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
DATASET_ID = os.environ.get("BQ_DATASET_ID", os.environ.get("BIGQUERY_DATASET_ID", "ecommerce_dw"))
LOCATION = "global"
BQ_LOCATION = os.environ.get("BQ_LOCATION", os.environ.get("BIGQUERY_LOCATION", "us-central1"))
GLOSSARY_ID = "ecommerce-glossary"


def get_access_token(force_refresh=False):
    """Mint an OAuth access token.

    force_refresh=True skips the GCP_ACCESS_TOKEN environment variable. That
    variable holds a token captured once at start-up; re-reading it during a
    long run would just hand back the same expired string.
    """
    token = None if force_refresh else os.environ.get("GCP_ACCESS_TOKEN")
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


_TOKEN_MINTED_AT = 0.0


def refresh_auth(headers, max_age_seconds=900):
    """Re-mint the OAuth token in place once it passes max_age_seconds.

    Provisioning ~300 EntryLinks takes several minutes, and the whole run
    previously shared one token fetched at start-up. If that token expired
    mid-flight every remaining call failed with HTTP 401 and the catalogue was
    left half-provisioned - which is exactly what happened on 2026-09-12, with
    the run dying at 179 of 295 links. Refreshing on a timer is cheap: the
    check is a float comparison, and gcloud is only invoked every 15 minutes.
    """
    global _TOKEN_MINTED_AT
    now = time.time()
    if now - _TOKEN_MINTED_AT < max_age_seconds:
        return
    fresh = get_access_token(force_refresh=True)
    if fresh:
        headers["Authorization"] = f"Bearer {fresh}"
        _TOKEN_MINTED_AT = now


def get_project_number(project_id, token):
    """Retrieves numeric project number from Cloud Resource Manager or gcloud CLI."""
    try:
        res = requests.get(
            f"https://cloudresourcemanager.googleapis.com/v1/projects/{project_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if res.status_code == 200:
            num = res.json().get("projectNumber")
            if num:
                return str(num)
    except Exception:
        pass

    # Fallback to gcloud CLI
    for cmd in ["/google/data/ro/teams/cloud-sdk/gcloud", "gcloud"]:
        try:
            res = subprocess.run([cmd, "projects", "describe", project_id, "--format=value(projectNumber)"], capture_output=True, text=True, timeout=10)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            continue
    return ""


def api_request_with_retry(method: str, url: str, headers: dict, json_payload: dict = None, max_retries: int = 8) -> requests.Response:
    """
    Executes an HTTP request with automated exponential backoff retry when encountering
    Google Cloud API rate limits (HTTP 429 or quota-related 403).
    """
    res = None
    for attempt in range(max_retries):
        try:
            if method.upper() == "GET":
                res = requests.get(url, headers=headers, timeout=20)
            elif method.upper() == "POST":
                res = requests.post(url, headers=headers, json=json_payload, timeout=20)
            elif method.upper() == "PATCH":
                res = requests.patch(url, headers=headers, json=json_payload, timeout=20)
            else:
                res = requests.request(method, url, headers=headers, json=json_payload, timeout=20)

            # Check if rate limited or quota exceeded
            if res.status_code == 429 or (res.status_code == 403 and "quota" in res.text.lower()):
                retry_after = res.headers.get("Retry-After")
                if retry_after:
                    try:
                        backoff = float(retry_after) + 1.0
                    except ValueError:
                        backoff = 4.0 * (1.5 ** attempt)
                else:
                    backoff = 4.0 * (1.5 ** attempt)
                print(f"    ⏳ GCP API rate limit encountered (HTTP {res.status_code}). Pausing {backoff:.1f}s before retry ({attempt + 1}/{max_retries})...")
                time.sleep(backoff)
                continue
            elif res.status_code >= 500:
                time.sleep(2.5)
                continue
            return res
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2.5)
            else:
                raise e
    return res


def run_integrity_gate():
    """Hard gate: refuse to deploy metadata that does not validate.

    A glossary term whose formula references a renamed column is worse than
    having no glossary at all - instead of failing to help, it makes the agent
    confidently wrong. The validator runs offline against the schema creation
    scripts, needs no credentials and takes about a second, so there is no
    operational reason to skip it.

    The glossary is read from config/business_glossary.yaml, which is the
    single source of truth; there is no second copy to fall out of step.
    """
    checker = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "verify_metadata_integrity.py")
    print("\n0. Metadata integrity gate...")
    result = subprocess.run([sys.executable, checker, "--strict"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        print("\n\u274c ABORTED: the glossary failed its integrity check. "
              "Nothing was deployed.", file=sys.stderr)
        print("   Fix the findings above, then re-run this script.",
              file=sys.stderr)
        sys.exit(1)
    print("   \u2705 Glossary passed the integrity check.")


def deploy_glossary():
    run_integrity_gate()

    print(f"\nDeploying Knowledge Catalog Business Glossary `{GLOSSARY_ID}` in `{PROJECT_ID}` (Location: `{LOCATION}`)...")
    token = get_access_token()
    if not token:
        print("Error: Could not retrieve OAuth access token.", file=sys.stderr)
        sys.exit(1)

    project_number = get_project_number(PROJECT_ID, token)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-goog-user-project": PROJECT_ID,
    }
    global _TOKEN_MINTED_AT
    _TOKEN_MINTED_AT = time.time()

    # config/business_glossary.yaml is the single source of truth for the
    # glossary. It is read directly here so that there is no second copy
    # of the same content that could silently fall out of step with it.
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "business_glossary.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        glossary_data = yaml.safe_load(f).get("glossary", {})

    base_url = f"https://dataplex.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/glossaries"
    glossary_resource_name = f"projects/{PROJECT_ID}/locations/{LOCATION}/glossaries/{GLOSSARY_ID}"
    glossary_url = f"{base_url}/{GLOSSARY_ID}"

    # 1. Create or verify Glossary resource
    print(f"1. Creating/Verifying Glossary `{GLOSSARY_ID}` in `{LOCATION}`...")
    check_res = api_request_with_retry("GET", glossary_url, headers)
    if check_res and check_res.status_code == 200:
        print(f"  Glossary `{GLOSSARY_ID}` already exists.")
    else:
        create_payload = {
            "displayName": glossary_data.get("display_name", "LumièreShop Executive Retail Glossary"),
            "description": glossary_data.get("description", "Enterprise semantic glossary for LumièreShop"),
        }
        create_res = api_request_with_retry("POST", f"{base_url}?glossaryId={GLOSSARY_ID}", headers, create_payload)
        print(f"  Glossary Creation Status: HTTP {create_res.status_code if create_res else 'N/A'}")

    # 2. Deploy Categories with Multi-Pass Reconciliation
    categories = glossary_data.get("categories", [])
    print(f"\n2. Deploying {len(categories)} Glossary Categories in `{LOCATION}`...")
    pending_categories = list(categories)
    completed_categories = set()

    for pass_num in range(1, 4):
        if not pending_categories:
            break
        if pass_num > 1:
            print(f"  ⏳ Category Reconciliation Pass {pass_num}: {len(pending_categories)} categories remaining after 3s pause...")
            time.sleep(3.0)

        for cat in list(pending_categories):
            cat_id = cat["id"]
            cat_url = f"{glossary_url}/categories/{cat_id}"
            cat_payload = {
                "parent": glossary_resource_name,
                "displayName": cat["display_name"],
                "description": cat["description"][:1000],
            }
            cat_check = api_request_with_retry("GET", cat_url, headers)
            if cat_check is not None and cat_check.status_code == 200:
                up_res = api_request_with_retry("PATCH", f"{cat_url}?updateMask=displayName,description", headers, cat_payload)
                if up_res is not None and up_res.status_code == 200:
                    completed_categories.add(cat_id)
                    pending_categories.remove(cat)
            else:
                cr_res = api_request_with_retry("POST", f"{glossary_url}/categories?categoryId={cat_id}", headers, cat_payload)
                if cr_res is not None and (cr_res.status_code in [200, 201] or cr_res.status_code == 409):
                    completed_categories.add(cat_id)
                    pending_categories.remove(cat)
            time.sleep(0.35)

    if len(completed_categories) < len(categories):
        print(f"❌ ERROR: Failed to deploy all categories ({len(completed_categories)}/{len(categories)}).", file=sys.stderr)
        sys.exit(1)
    print(f"  ✅ All {len(completed_categories)} categories successfully deployed.")

    # 3. Deploy Terms with Multi-Pass Reconciliation & Calibrated Pacing
    terms = glossary_data.get("terms", [])
    print(f"\n3. Deploying {len(terms)} Business Terms in `{LOCATION}` (Paced for GCP Quotas)...")
    pending_terms = list(terms)
    completed_terms = set()

    for pass_num in range(1, 4):
        if not pending_terms:
            break
        if pass_num > 1:
            print(f"\n  ⏳ Term Reconciliation Pass {pass_num}: {len(pending_terms)} terms remaining after 4s pause...")
            time.sleep(4.0)

        for idx, term in enumerate(list(pending_terms), 1):
            term_id = term["id"]
            term_url = f"{glossary_url}/terms/{term_id}"

            parts = [term["definition"]]
            formula_str = term.get("formula", "")
            if formula_str and formula_str != "N/A":
                parts.append(f"Calculation Formula: {formula_str}")
            synonyms_str = ", ".join(term.get("synonyms", []))
            if synonyms_str:
                parts.append(f"Synonyms: {synonyms_str}")
            desc_text = "\n\n".join(parts)

            term_payload = {
                "parent": glossary_resource_name,
                "displayName": term["display_name"],
                "description": desc_text[:1000],
            }

            refresh_auth(headers)
            term_check = api_request_with_retry("GET", term_url, headers)
            success = False
            if term_check is not None and term_check.status_code == 200:
                update_res = api_request_with_retry("PATCH", f"{term_url}?updateMask=displayName,description", headers, term_payload)
                if update_res is not None and update_res.status_code == 200:
                    success = True
            else:
                create_term_res = api_request_with_retry("POST", f"{glossary_url}/terms?termId={term_id}", headers, term_payload)
                if create_term_res is not None and create_term_res.status_code in [200, 201]:
                    success = True
                elif create_term_res is not None and create_term_res.status_code == 409:
                    update_res = api_request_with_retry("PATCH", f"{term_url}?updateMask=displayName,description", headers, term_payload)
                    if update_res is not None and update_res.status_code == 200:
                        success = True

            if success:
                completed_terms.add(term_id)
                pending_terms.remove(term)

            if idx % 15 == 0 or idx == len(terms) or len(completed_terms) == len(terms):
                print(f"  Progress: [{len(completed_terms):02d}/{len(terms):02d}] business terms synchronized...")

            time.sleep(0.45)

    if len(completed_terms) < len(terms):
        print(f"❌ ERROR: Failed to deploy all terms ({len(completed_terms)}/{len(terms)}). Missing: {[t['id'] for t in pending_terms]}", file=sys.stderr)
        sys.exit(1)
    print(f"  ✅ Terms deployed with clean descriptions: {len(completed_terms)}/{len(terms)}")

    # 4. Provision Native Knowledge Catalog EntryLinks with Multi-Pass Reconciliation
    print(f"\n4. Provisioning Native Knowledge Catalog EntryLinks in `{BQ_LOCATION}`...")
    link_type = "projects/655216118709/locations/global/entryLinkTypes/definition"

    all_links = []
    for term in terms:
        term_id = term["id"]
        term_target_name = f"projects/{project_number}/locations/global/entryGroups/@dataplex/entries/projects/{project_number}/locations/global/glossaries/{GLOSSARY_ID}/terms/{term_id}"
        bindings = term.get("bindings", [])
        bound_tables = sorted(list(set([b["table"] for b in bindings if b.get("table")])))
        for table_name in bound_tables:
            raw_id = f"link-{term_id}-{table_name}".replace("_", "-").lower()
            if len(raw_id) > 63:
                h = hashlib.md5(raw_id.encode("utf-8")).hexdigest()[:8]
                link_id = f"{raw_id[:54]}-{h}"
            else:
                link_id = raw_id
            bq_source_name = f"projects/{project_number}/locations/{BQ_LOCATION}/entryGroups/@bigquery/entries/bigquery.googleapis.com/projects/{PROJECT_ID}/datasets/{DATASET_ID}/tables/{table_name}"
            all_links.append((term_id, table_name, bq_source_name, term_target_name, link_id))

    total_bindings = len(all_links)
    pending_links = list(all_links)
    completed_links = set()

    for pass_num in range(1, 4):
        if not pending_links:
            break
        if pass_num > 1:
            print(f"\n  ⏳ EntryLinks Reconciliation Pass {pass_num}: {len(pending_links)} links remaining after 5s pause...")
            time.sleep(5.0)

        pacing_delay = 0.45 if pass_num == 1 else 0.75

        for idx, (term_id, table_name, bq_source_name, term_target_name, link_id) in enumerate(list(pending_links), 1):
            refresh_auth(headers)
            link_url = f"https://dataplex.googleapis.com/v1/projects/{PROJECT_ID}/locations/{BQ_LOCATION}/entryGroups/@bigquery/entryLinks?entryLinkId={link_id}"
            link_payload = {
                "entryLinkType": link_type,
                "entryReferences": [
                    {
                        "type": "SOURCE",
                        "name": bq_source_name,
                    },
                    {
                        "type": "TARGET",
                        "name": term_target_name,
                    }
                ]
            }

            try:
                link_res = api_request_with_retry("POST", link_url, headers, link_payload)
                if link_res is not None and (link_res.status_code in [200, 201, 409] or "already exists" in link_res.text):
                    completed_links.add(link_id)
                    pending_links.remove((term_id, table_name, bq_source_name, term_target_name, link_id))
                else:
                    err_msg = link_res.text[:120] if link_res is not None else "Timeout/No response"
                    print(f"    ⚠️ Warning: EntryLink `{link_id}` returned HTTP {link_res.status_code if link_res is not None else 'ERR'}: {err_msg}")
            except Exception as e:
                print(f"    ⚠️ Warning: Exception on EntryLink `{link_id}`: {e}")

            if len(completed_links) % 30 == 0 or len(completed_links) == total_bindings or idx == len(pending_links):
                print(f"  Progress: [{len(completed_links):03d}/{total_bindings:03d}] EntryLinks active...")

            time.sleep(pacing_delay)

    if len(completed_links) < total_bindings:
        print(f"\n❌ ERROR: Failed to provision all EntryLinks ({len(completed_links)}/{total_bindings}).", file=sys.stderr)
        print(f"Missing {len(pending_links)} EntryLinks: {[item[4] for item in pending_links[:10]]}...", file=sys.stderr)
        sys.exit(1)

    print(f"  ✅ EntryLinks provisioned: {len(completed_links)}/{total_bindings} (100% complete)")

    print("\n" + "=" * 80)
    print(f"Knowledge Catalog Glossary & Native EntryLinks Deployment Complete!")
    print(f"Summary: {len(categories)} Categories | {len(completed_terms)}/{len(terms)} Clean Terms | {len(completed_links)}/{total_bindings} EntryLinks")
    print("=" * 80)


if __name__ == "__main__":
    deploy_glossary()
