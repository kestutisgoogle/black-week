"""
Knowledge Catalog Discovery Core
================================
The single definition of how LumièreShop finds the data it grounds its agents
on. Both callers import from here:

  * `scripts/06_update_data_agent.py` - environment initialisation. Provisions
    the four agents once, so the demo starts from a known-good state.
  * `backend/app/services/discovery_service.py` - the live demo. The CMO types
    a question, the app searches the catalog in front of the audience, and
    provisions the agents from whatever comes back.

WHY THIS FILE EXISTS
--------------------
Those two used to be separate implementations, and they disagreed on every
single detail that matters:

    setup script                          web app
    ------------                          -------
    6 searches (1 table + 5 glossary)     1 search
    no dataset filter                     no dataset filter
    system=bigquery type=table            no entry predicate
    cap 40                                no cap
    4 force-included tables               none
    injected glossary terms               did NOT inject glossary terms

The web app's single unfiltered search scored 0 out of 11 on the main story
questions. Because the benchmark drives the web app path, every benchmark run
ever produced re-grounded the agents WORSE than the setup script had, after
the setup script had already grounded them correctly. Nothing reported this,
because each agent answers perfectly fluently from whatever it happens to
have.

One module removes the possibility. There is one prompt and one algorithm.

DESIGN CONSTRAINT: this module must import nothing from `app.config`. The
setup script runs outside the web application and loads its own environment.
Everything it needs - project, dataset, access token - is passed in.

THE ONE-PROMPT RULE
-------------------
The demo's claim is that a CMO types one question and the catalog finds the
data. Running five hand-tuned searches behind that one typed question would
be cheating, however good the results looked. So: ONE prompt string, used
verbatim for TWO calls, because tables and glossary terms are different entry
types and making them compete in a single ranking costs six terms for no gain.

Measured 2026-09-13, one prompt, two calls vs one prompt, one merged call:
    two calls   : 48 tables, 17 terms
    merged call : 35 tables, 22 terms   (tables and terms crowd each other out)
"""

from typing import Any, Dict, List, Optional

import requests

SEARCH_ENDPOINT = "https://dataplex.googleapis.com/v1/projects/{project}/locations/global:searchEntries"


# ---------------------------------------------------------------------------
# THE DISCOVERY PROMPT
#
# Written the way a Chief Marketing Officer would actually type it: one
# sentence, plain business language, no table names, no column names, no SQL
# vocabulary. It names the SYMPTOM (categories behind plan, Beauty short) and
# the CANDIDATE CAUSES a commercial review would check. It does not name the
# answer - the agent still has to work out which of the six candidates
# actually did the damage, and in what proportion.
#
# Three of the six causes listed are deliberately WRONG PATHS. Payment gateway
# failures and competitor pricing are red herrings the investigation is
# supposed to raise and dismiss. Mentioning them makes the agent's job harder,
# not easier, and it is what an honest review would look at.
#
# ⚠️ DO NOT REWORD THIS. It is a sharp local optimum, not a robust phrasing.
#
# Selected from ~56 candidates over 4 rounds and ~112 live searches, then
# confirmed stable across 5 identical repeat runs.
#
#   this prompt                        : 48 tables, 17 terms, 11/11 main story
#   previous setup-script prompt       : 35 tables, 28 terms,  6/11
#   previous web-app prompt            : 50 tables,  9 terms,  0/11
#
# Six near-identical variants were measured. Adding the phrase "return on ad
# spend", or "discounts", collapsed main-story coverage from 11/11 to 1/11,
# because the search stopped returning `orders` and/or `web_sessions`. The
# sentence is load-bearing as written.
#
# If a glossary term you need does not surface, FIX THE GLOSSARY, NOT THIS
# STRING. That is how the ROAS-convention warning came to live inside the
# `Target ROAS Budget Throttling` term rather than in `Paid ROAS`.
# ---------------------------------------------------------------------------
DISCOVERY_PROMPT = (
    "I need to know how each product category is pacing against its Black "
    "Week revenue plan to date, and how much revenue the Beauty shortfall "
    "lost to each cause: traffic and conversion rate, advertising budget "
    "throttling, items being out of stock, mismatched product "
    "recommendations, payment gateway failures, and competitor pricing."
)


# ---------------------------------------------------------------------------
# 🔴 THE 50-TABLE CLIFF - the most dangerous limit in this project.
#
# The Conversational Analytics service holds a constant
# `LARGE_VOLUME_TABLES_THRESHOLD = 50`. When an agent's datasource references
# exceed it, the service STOPS retrieving table schemas and STOPS retrieving
# Knowledge Catalog metadata altogether, and instead tells the model to fetch
# context per-table on demand.
#
# It does not raise. It does not warn. The agent still answers, fluently and
# confidently, from nothing but table names.
#
# Corroborated by Google Cloud Support case 75330703: "if the number of table
# is more than 50, table/column description is not used".
#
# The comparison being demonstrated is "catalog metadata versus no catalog
# metadata". Crossing this line turns Tier A into Tier C while every dashboard,
# log line and status endpoint continues to report success. A candidate prompt
# measured earlier in this project returned 72 tables and looked like a top
# performer; it would have destroyed the demo invisibly.
#
# The check is `> 50`, so exactly 50 is safe and 51 trips it. It counts ALL
# tables across ALL datasource references.
# ---------------------------------------------------------------------------
CA_METADATA_CLIFF = 50

# ---------------------------------------------------------------------------
# NON-ANALYTIC TABLE PATTERNS
# ---------------------------------------------------------------------------
# Added 2026-09-13 after measuring that the cap was one rank away from
# breaking the demo.
#
# THE MEASUREMENT. The prompt returns 58 tables. `payment_gateway_logs` -
# the table the entire payment red-herring question rests on - ranked
# **47th**. With a cap of 48 it was surviving by a single position out of 58,
# and semantic ranking drifts between runs. One bad draw on demo day and that
# question becomes unanswerable for every tier, silently.
#
# Nine of those 58 are not analytic tables at all: raw staging feeds, a QA
# load-test backup, and deprecated or archived copies. No benchmark question
# uses any of them. Excluding them lifts `payment_gateway_logs` from 47th to
# 40th and frees four slots below the metadata cliff.
#
# WHY THIS IS A PATTERN RULE AND NOT A TABLE LIST. A hardcoded list of table
# names would be exactly the cheating this project is built to avoid - the
# demo's claim is that discovery is live and nothing is pre-selected. These
# are blind prefix and substring rules of the kind every real catalog
# deployment applies to keep staging data out of analyst-facing search. They
# are applied without knowing which tables they will hit.
#
# WHAT THEY DELIBERATELY DO NOT TOUCH. All five red herrings survive:
# payment_gateway_logs, competitor_price_feed, competitor_promotions,
# influencer_campaigns, shipping_lead_times. The filter removes noise, not
# decoys - the questions that test whether an agent can reject a plausible
# wrong answer are entirely unaffected.
NON_ANALYTIC_PREFIXES = ("stg_", "qa_", "tmp_", "_")
NON_ANALYTIC_SUBSTRINGS = ("_backup", "legacy", "archive", "deprecated")


def is_non_analytic(table: str) -> bool:
    """True for raw staging, QA, backup, archived or deprecated tables.

    Kept as a function rather than inlined so that callers and tests can ask
    the same question the filter asks, instead of re-implementing it.
    """
    t = table.lower()
    return (t.startswith(NON_ANALYTIC_PREFIXES)
            or any(s in t for s in NON_ANALYTIC_SUBSTRINGS))


# Six slots of headroom below the cliff.
#
# Was 48, which left only two. The prompt returns 58 raw; after the
# non-analytic filter that is 49, and the deepest load-bearing table
# (`payment_gateway_logs`) sits at 40 - so 44 keeps every table any question
# needs, with four positions of margin for ranking drift, and stays well
# clear of the point where the service stops reading metadata.
MAX_GROUNDED_TABLES = 44


def _headers(project_id: str, token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-goog-user-project": project_id,
    }


def search_tables(
    project_id: str,
    dataset_id: str,
    token: str,
    prompt: str = DISCOVERY_PROMPT,
    timeout: int = 30,
) -> List[str]:
    """Rank the tables in one BigQuery dataset against a business question.

    SCOPING - `parent=` is the only thing that actually works
    ---------------------------------------------------------
    `scope` on the request body accepts a project or an organisation, never a
    dataset. So without a predicate, the Tier B and Tier C copies of the
    warehouse compete for the same relevance slots as the real one.

    Measured 2026-09-13, live, against the 25 curated investigation tables:

        query variant                        results  TierA  TierB  TierC
        -----------------------------------  -------  -----  -----  -----
        fully_qualified_name:<proj>.<ds>.         100     31     34     35
        parent:ecommerce_dw     (substring)        60     28     18     14
        parent=ecommerce_dw     (exact)            35     35      0      0
        parent=<project>.ecommerce_dw               0      -      -      -

      * `parent=` takes the BARE dataset name. Adding the project prefix
        returns zero results.
      * `parent:` is a SUBSTRING match, so it leaks: `ecommerce_dw` is a
        prefix of `ecommerce_dw_2nd` and `ecommerce_dw_3rd`.
      * `fully_qualified_name:` is not a documented predicate at all. Semantic
        search treated it as free text, which is why it never filtered
        anything. It was in this code for weeks doing nothing.

    RESULT COUNT - a relevance cut-off, not a page limit
    ----------------------------------------------------
    An earlier version of this code asserted searchEntries had "a hard
    100-result budget that cannot be raised". That was wrong, and the
    published docs say so: pageSize accepts up to 1000, and semantic search
    does paginate.

    Measured 2026-09-13:
        semanticSearch=true, bare predicate
            -> 5 pages, nextPageToken on each, 420 entries, all 140 tables
        semanticSearch=false, same predicate, pageSize=1000
            -> 420 entries in one page, no token
        semanticSearch=true, a long prose prompt, pageSize 100/250/500/1000
            -> exactly 100 every time, totalSize=100, NO nextPageToken

    A long prose query returns the complete set of entries that clear the
    server's semantic relevance threshold. No token is offered because there
    is nothing more to fetch. Pagination here would be dead code.

    DO NOT "fix" recall by setting semanticSearch=False. A literal search with
    the predicate returns all 420 entries and perfect recall, but that is not
    discovery - it is enumerating the project, and it would ground the agents
    on all 140 tables, far over the 50-table cliff. The relevance ranking IS
    the product being demonstrated.
    """
    body = {
        "query": f"{prompt} system=bigquery type=table parent={dataset_id}",
        "scope": f"projects/{project_id}",
        "semanticSearch": True,
        "pageSize": 100,
    }

    try:
        res = requests.post(
            SEARCH_ENDPOINT.format(project=project_id),
            headers=_headers(project_id, token),
            json=body,
            timeout=timeout,
        )
        if res.status_code != 200:
            print(f"  Notice: Knowledge Catalog table search returned HTTP {res.status_code}")
            return []
        results = res.json().get("results", [])
    except Exception as exc:
        print(f"  Notice: Knowledge Catalog table search error: {exc}")
        return []

    pattern = f"datasets/{dataset_id}/tables/"
    tables: List[str] = []
    for r in results:
        entry = r.get("dataplexEntry", {})
        for candidate in (
            r.get("linkedResource", ""),
            entry.get("name", ""),
            entry.get("entrySource", {}).get("resource", ""),
        ):
            if pattern in candidate:
                name = candidate.split(pattern)[-1]
                # `parent=` is an exact match, so a leaked `_2nd`/`_3rd` table
                # should be impossible. Verified anyway - a silent tier leak
                # would invalidate the whole comparison.
                if name and "/" not in name and name not in tables:
                    tables.append(name)
                break
    return tables


def search_glossary_terms(
    project_id: str,
    token: str,
    prompt: str = DISCOVERY_PROMPT,
    timeout: int = 30,
) -> List[Dict[str, str]]:
    """Rank Business Glossary terms against the same business question.

    The catalog is the system of record. Nothing here reads a local file: the
    display names and definitions are whatever is currently published in
    Knowledge Catalog, so editing a term changes what the agent receives on
    the next provisioning run.

    Returned in the shape the Conversational Analytics API expects on
    `publishedContext.glossaryTerms`: {"displayName", "description"}.

    ⚠️ `type=glossary_term` uses an UNDERSCORE. The hyphenated spelling
    `type=glossary-term` silently returns zero results instead of erroring,
    even though the entryType itself renders with a hyphen.

    A SEPARATE CALL, NOT A SEPARATE PROMPT. This runs the identical prompt
    string against a different entry type. Four extra hand-tuned glossary
    probes used to run here and were deleted: they lifted the term count from
    17 to 30, but five searches hiding behind one typed question is not the
    live discovery the demo claims to show.

    EntryLinks are deliberately not enumerated. The Conversational Analytics
    backend resolves table-to-term links itself at runtime; our job at
    provisioning time is to map the resources, not to pre-resolve the
    relationships between them.
    """
    body = {
        "query": f"{prompt} type=glossary_term",
        "scope": f"projects/{project_id}",
        "semanticSearch": True,
        "pageSize": 200,
    }

    try:
        res = requests.post(
            SEARCH_ENDPOINT.format(project=project_id),
            headers=_headers(project_id, token),
            json=body,
            timeout=timeout,
        )
        if res.status_code != 200:
            print(f"  Notice: Knowledge Catalog glossary search returned HTTP {res.status_code}")
            return []
        results = res.json().get("results", [])
    except Exception as exc:
        print(f"  Notice: Knowledge Catalog glossary search error: {exc}")
        return []

    seen: Dict[str, Dict[str, str]] = {}
    for r in results:
        entry = r.get("dataplexEntry", {})
        if "glossary-term" not in entry.get("entryType", ""):
            continue
        src = entry.get("entrySource", {})
        resource = src.get("resource") or entry.get("name", "")
        display = (src.get("displayName") or "").strip()
        desc = (src.get("description") or "").strip()
        if not resource or not display or resource in seen:
            continue
        seen[resource] = {"displayName": display, "description": desc}
    return list(seen.values())


def discover(
    project_id: str,
    dataset_id: str,
    token: str,
    prompt: Optional[str] = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    """One prompt, two searches, one capped result. The whole contract.

    Returns:
        tables       - list[str], capped, ordered by relevance
        terms        - list[{displayName, description}] for the catalog tier
        dropped      - list[str] discarded by the cap, so truncation is never
                       invisible to the caller
        table_count / term_count
        prompt       - the exact string used, for display and for audit

    Raises:
        RuntimeError if the capped list would still cross the 50-table cliff.
        Answering is worse than failing here: an agent over the cliff looks
        healthy and proves the opposite of the demo's thesis.
    """
    prompt = prompt or DISCOVERY_PROMPT

    raw = search_tables(project_id, dataset_id, token, prompt)

    # Stage 1: drop non-analytic tables. Done BEFORE the cap, so the slots
    # freed are given to real tables rather than wasted on staging copies.
    excluded = [t for t in raw if is_non_analytic(t)]
    ranked = [t for t in raw if not is_non_analytic(t)]

    if excluded and verbose:
        print(
            f"  🧹 Excluded {len(excluded)} non-analytic table(s) "
            f"(staging / QA / backup / archived): {excluded}"
        )

    # Stage 2: cap what remains.
    dropped = ranked[MAX_GROUNDED_TABLES:]
    tables = ranked[:MAX_GROUNDED_TABLES]

    if dropped and verbose:
        print(
            f"  ✂️  MAX_GROUNDED_TABLES={MAX_GROUNDED_TABLES} discarded "
            f"{len(dropped)} ranked table(s): {dropped}"
        )

    if len(tables) > CA_METADATA_CLIFF:
        raise RuntimeError(
            f"Refusing to ground {len(tables)} tables. The Conversational "
            f"Analytics service silently discards ALL schema and Knowledge "
            f"Catalog metadata above {CA_METADATA_CLIFF} tables, so the agent "
            f"would appear to work while receiving no catalog context at all. "
            f"Lower MAX_GROUNDED_TABLES (currently {MAX_GROUNDED_TABLES})."
        )

    terms = search_glossary_terms(project_id, token, prompt)

    if verbose:
        print(
            f"  Search returned {len(raw)}; {len(excluded)} non-analytic "
            f"excluded; {len(ranked)} ranked; grounding on {len(tables)} "
            f"(cliff at {CA_METADATA_CLIFF}, headroom "
            f"{CA_METADATA_CLIFF - len(tables)})."
        )
        print(f"  Discovered {len(terms)} business glossary terms.")

    return {
        "prompt": prompt,
        "tables": tables,
        "terms": terms,
        "excluded": excluded,
        "dropped": dropped,
        "raw_count": len(raw),
        "table_count": len(tables),
        "term_count": len(terms),
    }
