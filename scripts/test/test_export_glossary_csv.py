#!/usr/bin/env python3
"""
Test Suite: Knowledge Catalog Business Glossary Export Verification
==================================================================
Validates:
1. Execution of `scripts/export_business_glossary_to_csv.py`
2. Correct creation of `export/business-glossary.csv` and `export/categories.csv`
3. Exact 7-column schema for terms CSV matching `business-glossary-import`
4. Exact 4-column schema for categories CSV
5. RFC4180 parsing and UTF-8 encoding integrity
6. Total term count matches 85 terms and 15 categories
"""

import os
import sys
import csv
import subprocess

EXPECTED_TERM_COLUMNS = [
    "term_display_name",
    "description",
    "steward",
    "tagged_assets",
    "synonyms",
    "related_terms",
    "belongs_to_category"
]

EXPECTED_CAT_COLUMNS = [
    "category_display_name",
    "description",
    "steward",
    "belongs_to_category"
]


def test_glossary_export():
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    script_path = os.path.join(root_dir, "scripts", "export_business_glossary_to_csv.py")
    export_dir = os.path.join(root_dir, "export")
    terms_csv = os.path.join(export_dir, "business-glossary.csv")
    cats_csv = os.path.join(export_dir, "categories.csv")

    print(f"Running export script: {script_path} ...")
    cmd = [
        sys.executable,
        script_path,
        "--output", terms_csv,
        "--categories-csv", cats_csv,
        "--include-header"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=root_dir)
    print("STDOUT:\n", res.stdout)
    if res.stderr:
        print("STDERR:\n", res.stderr)

    assert res.returncode == 0, f"Export script failed with code {res.returncode}"
    assert os.path.exists(terms_csv), f"Missing {terms_csv}"
    assert os.path.exists(cats_csv), f"Missing {cats_csv}"

    # 1. Validate Terms CSV
    print(f"\nValidating Terms CSV: {terms_csv} ...")
    with open(terms_csv, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        assert header == EXPECTED_TERM_COLUMNS, f"Header mismatch! Expected {EXPECTED_TERM_COLUMNS}, got {header}"
        rows = list(reader)

    print(f"  ✅ Headers match exactly: {header}")
    print(f"  ✅ Total terms exported: {len(rows)}")
    assert len(rows) == 85, f"Expected 85 terms, got {len(rows)}"

    # Check non-empty key fields for all terms
    for idx, row in enumerate(rows, 1):
        term_name = row[0]
        desc = row[1]
        steward = row[2]
        tagged = row[3]
        category = row[6]
        assert term_name, f"Row {idx} has empty term_display_name"
        assert desc, f"Row {idx} ({term_name}) has empty description"
        assert category, f"Row {idx} ({term_name}) has empty belongs_to_category"

    print("  ✅ All 85 terms contain non-empty display names, descriptions, and category mappings.")

    # 2. Validate Categories CSV
    print(f"\nValidating Categories CSV: {cats_csv} ...")
    with open(cats_csv, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        assert header == EXPECTED_CAT_COLUMNS, f"Categories header mismatch! Expected {EXPECTED_CAT_COLUMNS}, got {header}"
        cat_rows = list(reader)

    print(f"  ✅ Category headers match exactly: {header}")
    print(f"  ✅ Total categories exported: {len(cat_rows)}")
    assert len(cat_rows) >= 15, f"Expected at least 15 categories, got {len(cat_rows)}"

    for idx, row in enumerate(cat_rows, 1):
        cat_name = row[0]
        desc = row[1]
        assert cat_name, f"Category row {idx} has empty category_display_name"
        assert desc, f"Category row {idx} ({cat_name}) has empty description"

    print(f"  ✅ All {len(cat_rows)} categories contain non-empty display names and descriptions.")

    print("\n" + "=" * 80)
    print("🎉 ALL TESTS PASSED SUCCESSFULLY!")
    print("=" * 80)


if __name__ == "__main__":
    test_glossary_export()
