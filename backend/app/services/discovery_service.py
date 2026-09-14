"""
Knowledge Catalog Discovery Service (web application adapter)
=============================================================
Thin adapter that lets the FastAPI layer reach the shared discovery logic in
`app.services.discovery_core`.

WHAT THIS FILE USED TO DO, AND WHY IT WAS REPLACED
--------------------------------------------------
It held a second, independent implementation of catalog discovery, and it was
materially worse than the one in the setup script:

  * ONE unfiltered search. No `type=` predicate, so glossary terms, table
    entries and category entries all competed for the same relevance slots.
  * No dataset scope, so the Tier B (`_2nd`) and Tier C (`_3rd`) copies of the
    warehouse competed too - 420 BigQuery entries fighting for 100 slots when
    only 140 of them were the real warehouse.
  * No cap, so nothing stopped it grounding an agent past the 50-table cliff
    where the Conversational Analytics service silently stops reading
    Knowledge Catalog metadata entirely.
  * It never wrote glossary terms onto the agent at all.

Because the benchmark drives this path, every benchmark run re-grounded the
agents through it, overwriting the good grounding the setup script had just
produced. Measured on the 15 benchmark questions, the prompt and logic this
path used scored 0 out of 11 on the main story.

⚠️ AND THE TRAP THAT MADE IT HARD TO FIX SAFELY: the old single query
harvested tables AND glossary terms from the SAME result set. Simply adding
`type=table` to it - the obvious fix, and the one applied to the setup script
- would have silently returned zero glossary terms. The query has to be SPLIT,
which is what `discovery_core.discover()` does.

Everything here now delegates. There is no discovery logic left in this file.
"""

import os
from typing import Any, Dict, List

from app.config import PROJECT_ID, DATASET_ID
from app.services.ca_service import get_access_token
from app.services.discovery_core import (
    DISCOVERY_PROMPT,
    MAX_GROUNDED_TABLES,
    discover,
)


class KnowledgeDiscoveryService:
    """Adapter onto `discovery_core` for the FastAPI request path."""

    def __init__(
        self,
        project_id: str = PROJECT_ID,
        dataset_id: str = DATASET_ID,
        location: str = "global",
    ):
        """
        Args:
            project_id: Google Cloud project hosting Knowledge Catalog and BigQuery.
            dataset_id: BigQuery dataset holding the e-commerce warehouse.
            location: Catalog location. `searchEntries` requires 'global'
                regardless of where the BigQuery data physically lives.
        """
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.location = location
        self.entry_location = os.environ.get("BQ_LOCATION", "europe-west4").lower()
        self.glossary_id = "ecommerce-glossary"

    def _get_auth_token(self) -> str:
        """OAuth access token via Application Default Credentials."""
        return get_access_token() or ""

    def discover_knowledge_context(
        self, natural_language_prompt: str = ""
    ) -> Dict[str, Any]:
        """Run the shared two-search discovery for one business question.

        Args:
            natural_language_prompt: What the CMO typed. Falls back to the
                canonical `DISCOVERY_PROMPT` when empty, so the button in the
                interface and the setup script produce the identical result.

        Returns a dict shaped for the API response:
            tables       - list[str]
            terms        - list[str] display names, for the progress log
            glossary_terms - list[{displayName, description}], for provisioning
            entry_links  - always [] (see below)
            *_count      - convenience counts

        ENTRY LINKS ARE NOT ENUMERATED. `entry_link_count` used to be reported
        as `len(tables) + len(terms)`, which is an invented number, not a
        measurement - there is no `ListEntryLinks` method on the API. The
        Conversational Analytics backend resolves table-to-term links itself at
        runtime. Reporting a fabricated count in a demo about metadata quality
        is exactly the sort of thing that ends a customer conversation, so it
        now reports zero and says so.
        """
        prompt = (natural_language_prompt or "").strip() or DISCOVERY_PROMPT

        token = self._get_auth_token()
        if not token:
            print("Warning: No GCP token available for Knowledge Catalog search.")
            return {
                "prompt": prompt,
                "tables": [],
                "terms": [],
                "glossary_terms": [],
                "entry_links": [],
                "table_count": 0,
                "term_count": 0,
                "entry_link_count": 0,
            }

        result = discover(self.project_id, self.dataset_id, token, prompt)
        glossary_terms = result["terms"]

        return {
            "prompt": result["prompt"],
            "tables": result["tables"],
            "terms": [t["displayName"] for t in glossary_terms],
            "glossary_terms": glossary_terms,
            "entry_links": [],
            "table_count": result["table_count"],
            "term_count": result["term_count"],
            "entry_link_count": 0,
        }

    def discover_and_hydrate_tables(self, natural_language_prompt: str = "") -> List[str]:
        """Table names only, for callers that do not need the glossary."""
        return self.discover_knowledge_context(natural_language_prompt)["tables"]


# Re-exported so callers can show the user which prompt and cap are in force
# without importing the core module directly.
__all__ = [
    "KnowledgeDiscoveryService",
    "DISCOVERY_PROMPT",
    "MAX_GROUNDED_TABLES",
]
