#!/usr/bin/env python3
"""
Verify that the Knowledge Catalog glossary is internally consistent before it
is deployed.

Why this exists
---------------
Tier A's entire value proposition is that its metadata is trustworthy. A
glossary term whose `formula` references a renamed column does not merely fail
to help - it actively sends the agent to write SQL that errors or silently
returns nothing. That is worse than having no glossary at all, and it is the
single easiest way for a hostile reviewer to discredit the demo.

Checks performed
----------------
  1. BINDING INTEGRITY - every bindings[].table exists, every bindings[].column
                         exists on that table
  2. FORMULA INTEGRITY - identifiers named in `formula` resolve against the
                         real schema, covering three forms:
                           a) qualified   table.column
                           b) bare snake_case tokens
                           c) bare tokens used in a comparison, e.g. `ill = TRUE`
                         (c) matters because a renamed single-word column such
                         as `ill` has no underscore and would otherwise slip
                         through the snake_case heuristic.
  3. INCIDENT LEAKAGE  - no definition names the categories, SKUs, campaigns or
                         headline figures involved in the scenario

Reads schemas directly from the creation scripts, so it runs offline with no
BigQuery access and no credentials.

Usage
-----
  python3 scripts/verify_metadata_integrity.py
  python3 scripts/verify_metadata_integrity.py --strict   # non-zero exit on any finding
"""

import argparse
import importlib.util
import os
import re
import sys

import yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(PROJECT_ROOT, "scripts")
GLOSSARY = os.path.join(PROJECT_ROOT, "config", "business_glossary.yaml")


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _field_names(fields):
    """Handle both SchemaField objects and plain dicts."""
    names = set()
    for f in fields:
        if hasattr(f, "name"):
            names.add(f.name)
        elif isinstance(f, dict) and "name" in f:
            names.add(f["name"])
    return names


def load_real_schema():
    """Collect {table_name: {column names}} from the schema creation scripts."""
    real = {}

    core = _load_module(os.path.join(SCRIPTS, "01_create_schema.py"), "_sch_core")
    for table, fields in getattr(core, "TABLE_SCHEMAS", {}).items():
        real[table] = _field_names(fields)

    ext_path = os.path.join(SCRIPTS, "11_create_extended_schema.py")
    if os.path.exists(ext_path):
        ext = _load_module(ext_path, "_sch_ext")
        for table, spec in getattr(ext, "EXTENDED_TABLE_SCHEMAS", {}).items():
            fields = spec.get("fields", []) if isinstance(spec, dict) else spec
            real[table] = _field_names(fields)

    return real


# Anything that names the scenario rather than defining a concept.
INCIDENT_PATTERNS = [
    (r"\bBeauty\b", "names the affected category"),
    (r"\bElectronics\b", "names the category used in the mismatch"),
    (r"\b100[1-5]\b", "names an affected hero SKU"),
    (r"\bcampaign[_ ]?1001\b", "names the throttled campaign"),
    (r"(?<![\d.,])(?:415|530|65|50)[,_ ]?000\b", "states a headline loss figure"),
    (r"\broot cause\b", "asserts a root cause"),
    (r"taxonomy parity error", "states the failure mode as fact"),
]

# Tokens in a formula that are prose or SQL keywords, not column names.
FORMULA_STOPWORDS = {
    "sum", "count", "avg", "min", "max", "and", "or", "not", "from", "where",
    "select", "case", "when", "then", "else", "end", "as", "distinct", "null",
    "true", "false", "is", "in", "on", "join", "left", "inner", "group", "by",
    "order", "total", "completed", "orders", "web", "sessions", "actual",
    "revenue", "target", "date", "time", "interval", "vs", "count_distinct",
    "coalesce", "safe_divide", "round", "cast", "int64", "float64", "numeric",
    "timestamp", "current", "over", "partition", "nullif", "extract",
    # SQL builtins that look like snake_case identifiers
    "timestamp_diff", "date_diff", "datetime_diff", "timestamp_trunc",
    "date_trunc", "safe_cast", "safe_divide", "string_agg", "array_agg",
    "countif", "sumif", "percentile_cont", "format_date", "parse_date",
    "date_sub", "date_add", "timestamp_sub", "timestamp_add", "current_date",
    "current_timestamp", "count_if", "approx_count_distinct",
    # prose that legitimately appears in a methodology note
    "do", "use", "the", "to", "of", "for", "a", "an", "it", "if", "onset",
    "restricted", "affected", "category", "window", "unavailability", "force",
    "held", "after", "recovery", "with", "throttle", "corroborated", "by",
}

RE_QUALIFIED = re.compile(r"\b([a-z][a-z0-9_]*)\.([a-z][a-z0-9_]*)\b")
# A bare token immediately used in a comparison is being used as a column.
RE_COMPARISON = re.compile(r"(?<![.\w'\"])([a-z][a-z0-9_]*)\s*(?:<=|>=|!=|<|>|=)(?!=)")

# Knowledge Catalog silently truncates a term description at this many
# characters. scripts/09_create_dataplex_glossary.py enforces it with
# `desc_text[:1000]`, which drops the tail WITHOUT any error. The tail is
# exactly where imperative warnings ("do NOT report SUM(...)") tend to land,
# so an overlong term can lose its entire anti-trap mechanism in silence.
CATALOG_DESCRIPTION_LIMIT = 1000
# Anything above this is not yet broken but has too little headroom to survive
# a routine wording tweak, so it is surfaced as a warning.
CATALOG_DESCRIPTION_WARN = 900


def assemble_description(term):
    """Reproduce, byte for byte, the description that the publisher sends.

    This MUST stay in lockstep with the `parts`/`desc_text` block in
    scripts/09_create_dataplex_glossary.py. If that assembly changes, this
    gate silently stops measuring the right string.
    """
    parts = [term["definition"]]
    formula_str = term.get("formula", "")
    if formula_str and formula_str != "N/A":
        parts.append(f"Calculation Formula: {formula_str}")
    synonyms_str = ", ".join(term.get("synonyms", []))
    if synonyms_str:
        parts.append(f"Synonyms: {synonyms_str}")
    return "\n\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--strict", action="store_true",
                        help="Exit non-zero if any finding is reported.")
    args = parser.parse_args()

    real = load_real_schema()
    with open(GLOSSARY, "r", encoding="utf-8") as fh:
        glossary = yaml.safe_load(fh)
    terms = glossary["glossary"]["terms"]

    all_columns = set()
    for cols in real.values():
        all_columns |= cols

    print("=" * 78)
    print("KNOWLEDGE CATALOG METADATA INTEGRITY CHECK")
    print("=" * 78)
    print(f"Tables known from schema scripts : {len(real)}")
    print(f"Distinct columns                 : {len(all_columns)}")
    print(f"Glossary terms                   : {len(terms)}")

    missing_tables, missing_columns = [], []
    unresolved_formula, leaks = [], []
    literals, unbound_refs = [], []
    overlong_desc, tight_desc = [], []
    binding_count = 0

    for term in terms:
        tid = term["id"]

        # Length gate. Measured on the assembled string the publisher actually
        # sends, not on the YAML definition alone.
        desc_len = len(assemble_description(term))
        if desc_len > CATALOG_DESCRIPTION_LIMIT:
            overlong_desc.append((tid, desc_len,
                                  desc_len - CATALOG_DESCRIPTION_LIMIT))
        elif desc_len > CATALOG_DESCRIPTION_WARN:
            tight_desc.append((tid, desc_len,
                               CATALOG_DESCRIPTION_LIMIT - desc_len))

        for binding in (term.get("bindings") or []):
            binding_count += 1
            table, column = binding.get("table"), binding.get("column")
            if table not in real:
                missing_tables.append((tid, table, column))
            elif column and column not in real[table]:
                missing_columns.append((tid, table, column))

        formula = str(term.get("formula") or "")
        bound_tables = [b.get("table") for b in (term.get("bindings") or [])
                        if b.get("table") in real]

        # (a) qualified references: table.column
        qualified_cols = set()
        for tbl, col in RE_QUALIFIED.findall(formula):
            qualified_cols.add(col)
            if tbl not in real:
                # Not a known table. Could be a SQL alias, but in this
                # glossary every qualifier is a real table name.
                unresolved_formula.append(
                    (tid, f"{tbl}.{col}", "qualifier is not a known table"))
            elif col not in real[tbl]:
                unresolved_formula.append(
                    (tid, f"{tbl}.{col}", f"no such column on {tbl}"))
            elif tbl not in bound_tables:
                unbound_refs.append((tid, f"{tbl}.{col}"))

        # (b) bare snake_case tokens
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", formula):
            low = token.lower()
            if low in FORMULA_STOPWORDS or "_" not in low:
                continue
            if token in qualified_cols:      # already checked as table.column
                continue
            # ALL_CAPS tokens are enum/status literals compared against, not
            # column names. Collect them for a separate value check.
            if token.isupper():
                literals.append((tid, token))
                continue
            if low in real:                      # a table name, fine
                continue
            if token in all_columns:             # exists somewhere
                if bound_tables and not any(token in real[t] for t in bound_tables):
                    unresolved_formula.append(
                        (tid, token, "exists, but not on any bound table"))
                continue
            unresolved_formula.append((tid, token, "does not exist anywhere"))

        # (c) bare tokens used in a comparison. Catches single-word columns
        # such as `ill` that carry no underscore.
        for token in RE_COMPARISON.findall(formula):
            low = token.lower()
            if low in FORMULA_STOPWORDS or "_" in low:
                continue                 # snake_case already covered by (b)
            if token in qualified_cols or low in real or token in all_columns:
                continue
            unresolved_formula.append(
                (tid, token, "compared against, but is not a column anywhere"))

        blob = " ".join(str(term.get(k, "")) for k in ("display_name", "definition", "formula"))
        for pattern, why in INCIDENT_PATTERNS:
            if re.search(pattern, blob, re.I):
                leaks.append((tid, why, re.search(pattern, blob, re.I).group(0)))

    def section(title, rows, fmt):
        print("\n" + "-" * 78)
        if rows:
            print(f"[FAIL] {title}: {len(rows)}")
            for row in rows:
                print("   " + fmt(row))
        else:
            print(f"[ OK ] {title}: none")
        return len(rows)

    n1 = section("Bindings referencing a table that does not exist",
                 missing_tables, lambda r: f"{r[0]:<44} -> {r[1]}.{r[2]}")
    n2 = section("Bindings referencing a column that does not exist",
                 missing_columns, lambda r: f"{r[0]:<44} -> {r[1]}.{r[2]}")
    n3 = section("Formula identifiers that do not resolve",
                 unresolved_formula, lambda r: f"{r[0]:<44} -> {r[1]}  ({r[2]})")
    n4 = section("Certified definitions leaking the incident",
                 leaks, lambda r: f"{r[0]:<44} -> {r[1]}: '{r[2]}'")
    n5 = section(
        f"Descriptions over the {CATALOG_DESCRIPTION_LIMIT}-char catalog cap "
        "(tail would be SILENTLY discarded)",
        overlong_desc,
        lambda r: f"{r[0]:<44} -> {r[1]} chars, {r[2]} would be cut")

    # Not a failure, but terms this close to the cap cannot absorb an edit.
    print("\n" + "-" * 78)
    print(f"[INFO] Descriptions within {CATALOG_DESCRIPTION_LIMIT - CATALOG_DESCRIPTION_WARN} "
          f"chars of the cap (low headroom): {len(tight_desc)}")
    for tid, length, spare in tight_desc:
        print(f"   {tid:<44} -> {length} chars, {spare} to spare")

    # Informational only: these are values a formula compares against. They
    # cannot be validated against the schema, but a stale enum value makes a
    # certified formula return zero rows, which is just as damaging.
    print("\n" + "-" * 78)
    print(f"[INFO] Enum/status literals used in formulas (verify by hand): {len(literals)}")
    for tid, lit in literals:
        print(f"   {tid:<44} -> '{lit}'")

    # A formula may legitimately reference a table it is not bound to, but the
    # agent will not receive an EntryLink for it, so it is worth surfacing.
    print("\n" + "-" * 78)
    print(f"[INFO] Formula references a real table the term is not bound to: {len(unbound_refs)}")
    for tid, ref in unbound_refs:
        print(f"   {tid:<44} -> {ref}")

    total = n1 + n2 + n3 + n4 + n5
    print("\n" + "=" * 78)
    print(f"Bindings checked: {binding_count} | Findings: {total}")
    if total == 0:
        print("RESULT: PASS - the catalogue is internally consistent.")
    else:
        print("RESULT: FAIL - fix the findings above before rebuilding the catalogue.")
    print("=" * 78)

    if args.strict and total:
        sys.exit(1)


if __name__ == "__main__":
    main()
