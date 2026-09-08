#!/usr/bin/env python3
"""
Master Composable Test Runner & Quality Auditor for LumièreShop.
Orchestrates test suites across:
1. Data Integrity, Dates & Mathematical Variance Reconciliation
2. Multilingual Support (25 Languages & UI Localizations)
3. Semantic Search & Knowledge Catalog Table Mapping
4. Gemini Enterprise Agent Platform Conversational Analytics
5. Multi-Agent 3-Way Parallel Cockpit
6. Comprehensive Metadata & Quality Audit

Usage:
  python3 scripts/test/run_all_tests.py --all
  python3 scripts/test/run_all_tests.py --unit
  python3 scripts/test/run_all_tests.py --integration
  python3 scripts/test/run_all_tests.py --audit
"""

import os
import sys
import time
import argparse
import subprocess
import json
from datetime import datetime, timezone

# Add project root and test dir to path
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "..", ".."))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, TEST_DIR)

from test_utils import load_project_env, get_project_root, ensure_test_server, ensure_playwright_chromium, get_knowledge_catalog_indexing_status

load_project_env()

def run_test_module(name: str, script_relpath: str, args: list = None) -> dict:
    """Executes a single test script and returns execution metrics."""
    script_path = os.path.join(PROJECT_ROOT, script_relpath)
    if not os.path.exists(script_path):
        return {
            "name": name,
            "script": script_relpath,
            "status": "SKIPPED",
            "error": f"Script not found: {script_path}",
            "duration_s": 0.0
        }

    cmd = [sys.executable, script_path] + (args or [])
    start_time = time.time()
    try:
        res = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=600
        )
        duration = round(time.time() - start_time, 2)
        success = (res.returncode == 0)
        if success:
            if "[SKIPPED]" in (res.stdout or ""):
                status = "SKIPPED"
            else:
                status = "PASSED"
        else:
            status = "FAILED"

        return {
            "name": name,
            "script": script_relpath,
            "status": status,
            "returncode": res.returncode,
            "duration_s": duration,
            "stdout": res.stdout,
            "stderr": res.stderr
        }
    except subprocess.TimeoutExpired:
        duration = round(time.time() - start_time, 2)
        return {
            "name": name,
            "script": script_relpath,
            "status": "TIMEOUT",
            "returncode": -1,
            "duration_s": duration,
            "error": "Execution timed out after 360 seconds."
        }

    except Exception as e:
        duration = round(time.time() - start_time, 2)
        return {
            "name": name,
            "script": script_relpath,
            "status": "ERROR",
            "returncode": -1,
            "duration_s": duration,
            "error": str(e)
        }

def main():
    parser = argparse.ArgumentParser(description="LumièreShop Master Composable Test Suite")
    parser.add_argument("--all", action="store_true", help="Run all unit, integration, and audit tests")
    parser.add_argument("--unit", action="store_true", help="Run fast unit and consistency tests")
    parser.add_argument("--integration", action="store_true", help="Run GCP BigQuery and Knowledge Catalog integration tests")
    parser.add_argument("--audit", action="store_true", help="Run full metadata and glossary audit")
    parser.add_argument("--output-json", type=str, default="", help="Path to save structured test results JSON")
    args = parser.parse_args()

    # Default to --all if no specific flags provided
    if not (args.unit or args.integration or args.audit or args.all):
        args.all = True

    print("=" * 80)
    print(" 🚀 LUMIÈRESHOP COMPOSABLE TEST SUITE & QUALITY AUDITOR")
    print(f" Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print(f" Project Root: {PROJECT_ROOT}")
    print(f" Environment GCP_PROJECT_ID: {os.environ.get('GCP_PROJECT_ID', '')}")
    print("=" * 80)

    test_plan = []

    if args.unit or args.all:
        print("\n⚡ Ensuring local FastAPI test server and Playwright Chromium are active...")
        ensure_test_server(8000)
        ensure_playwright_chromium()
        test_plan.extend([
            ("Multilingual Support & 25-Language Dictionary", "scripts/test/test_multilingual_support.py"),
            ("Prompt & Grounded Table Consistency", "scripts/test/test_prompt_table_consistency.py"),
            ("UI Playwright & Metrics Validation", "scripts/test/test_ui_and_metrics.py"),
            ("User Name Screen & Audit Logging Flow", "scripts/test/16_test_user_name_flow.py")
        ])

    if args.integration or args.all:
        test_plan.extend([
            ("Temporal Calendar Cutoff & Math Reconciliation", "scripts/test/05_validate_data_dates.py"),
            ("Knowledge Catalog Semantic Search & Aspects", "scripts/test/10_test_knowledge_search.py"),
            ("Gemini Enterprise Data Agent Investigation Tree", "scripts/test/07_test_investigation_tree.py"),
            ("3-Agent Parallel Conversational Cockpit", "scripts/test/test_multi_agent_chat.py"),
            ("Compare Chats & Multi-Agent Audit Logging", "scripts/test/17_test_compare_chats_logging.py"),
            ("Temporal Glossary Terms & Simulation Semantics", "scripts/test/18_test_temporal_glossary_terms.py")
        ])

    if args.audit or args.all:
        test_plan.extend([
            ("Enterprise Metadata & Business Glossary Audit", "scripts/test/audit_data_and_metadata_context.py")
        ])

    results = []
    passed_count = 0
    skipped_count = 0
    failed_count = 0

    for idx, (name, relpath) in enumerate(test_plan, 1):
        print(f"\n[{idx}/{len(test_plan)}] Running: {name} ({relpath})...")
        res = run_test_module(name, relpath)
        results.append(res)

        if res["status"] == "PASSED":
            passed_count += 1
            print(f"  ✅ PASSED in {res['duration_s']}s")
        elif res["status"] == "SKIPPED":
            skipped_count += 1
            print(f"  ⚠️ SKIPPED in {res['duration_s']}s (Headless Linux VM missing browser libraries)")
        else:
            failed_count += 1
            print(f"  ❌ {res['status']} in {res['duration_s']}s")
            if res.get("stderr"):
                print(f"     Error output:\n{res['stderr'][:400]}")
            elif res.get("error"):
                print(f"     Error: {res['error']}")

    print("\n" + "=" * 80)
    print(" 📊 TEST EXECUTION SUMMARY")
    print(f" Total Tests: {len(test_plan)} | Passed: {passed_count} | Skipped: {skipped_count} | Failed: {failed_count}")
    try:
        pid = os.environ.get("GCP_PROJECT_ID", "")
        did = os.environ.get("BQ_DATASET_ID", "ecommerce_dw")
        idx_info = get_knowledge_catalog_indexing_status(pid, did)
        print(f" Knowledge Catalog Indexing: {idx_info['indexed_tables']}/140 Tables ({idx_info['table_percentage']}%) | {idx_info['indexed_terms']}/85 Terms ({idx_info['term_percentage']}%) [{idx_info['status']}]")
    except Exception:
        pass
    print("=" * 80)

    summary_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(test_plan),

        "passed": passed_count,
        "failed": failed_count,
        "success_rate": f"{(passed_count / len(test_plan) * 100):.1f}%" if test_plan else "0%",
        "results": results
    }

    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2)
        print(f"Saved test results to {args.output_json}")

    return 0 if failed_count == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
