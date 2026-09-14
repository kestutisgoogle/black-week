"""
Multi-Prompt Semantic Evaluation Service (Prompt Comparison Studio)
====================================================================
Provides comparative semantic evaluation across candidate natural language prompts
using Google Cloud Knowledge Catalog dynamic search and Google Cloud Gemini
Enterprise Agent Platform (Gemini 3.7 Flash).

Workflow:
---------
1. Parallel Semantic Search:
   Dispatches 2 to 3 candidate prompts in parallel to Knowledge Catalog `searchEntries`
   API using `asyncio.gather`.
2. 2-Hop Graph Traversal:
   Parses both direct BigQuery table entries and business glossary term bindings in-memory.
3. Multi-Factor LLM Evaluation:
   Submits the discovered table sets, counts, and glossary term lists to Gemini 3.7 Flash
   with structured JSON schema instructions and a strict scoring rubric.
4. Deterministic Heuristic Fallback:
   If Vertex AI APIs are unreachable, a deterministic scoring engine evaluates table volume,
   5-domain forensic breadth, and priority alignment to return consistent evaluation scores.
"""

import os
import json
import asyncio
import requests
from typing import List, Dict, Any, Optional
from app.config import PROJECT_ID, DATASET_ID, LOCATION
from app.services.ca_service import get_access_token
from app.services import discovery_core


class PromptEvaluatorService:
    """
    Evaluator service comparing prompt candidates against Knowledge Catalog and Vertex AI.
    """

    def __init__(
        self,
        project_id: str = PROJECT_ID,
        dataset_id: str = DATASET_ID,
        region: str = LOCATION,
    ):
        """
        Initializes PromptEvaluatorService with Google Cloud project and regional settings.

        Args:
            project_id: Target GCP Project ID.
            dataset_id: BigQuery dataset identifier.
            region: Google Cloud regional location.
        """
        self.project_id = project_id
        self.dataset_id = dataset_id
        # `region` already defaults to LOCATION, which is sourced from BQ_LOCATION
        # in config.py. No hardcoded region fallback here: a wrong default would
        # silently point this service at a region the install never provisioned.
        self.region = region or LOCATION

    async def search_single_prompt(self, prompt: str, token: str) -> Dict[str, Any]:
        """
        Rank the warehouse against one candidate prompt, using the SAME discovery
        code path as live provisioning and the environment setup script.

        WHY THIS DELEGATES
        ------------------
        This method used to issue its own `searchEntries` call with the bare
        prompt as the whole query - no `system=bigquery type=table`, no
        `parent=<dataset>` scope, and a single page shared between tables and
        glossary terms. The consequence was that the comparison screen reported
        **4 tables** for the approved prompt while the provisioning screen,
        moments earlier, reported **44** for the identical prompt. Two screens
        in the same demo, disagreeing by an order of magnitude, on the one
        number the demo is about.

        `discovery_core` is the hard-won implementation: dataset-scoped table
        search plus a separate `type=glossary_term` search, with the
        non-analytic filter and the 44-table cap. Sharing it means the
        comparison screen, the live provisioning path and
        `scripts/06_update_data_agent.py` can never disagree again.

        Args:
            prompt: Candidate prompt text string.
            token: Google Cloud OAuth access token.

        Returns:
            Dict with the prompt, discovered tables, glossary terms and counts.
        """
        try:
            # discover() is the whole contract: dataset-scoped table search,
            # the non-analytic filter, the MAX_GROUNDED_TABLES cap and the
            # glossary search. Calling the two lower-level searches directly
            # would report the RAW ranked count (58) where the provisioning
            # screen reports the grounded count (44) - the same off-by-a-mile
            # disagreement this method was rewritten to eliminate.
            result = await asyncio.to_thread(
                discovery_core.discover,
                self.project_id,
                self.dataset_id,
                token,
                prompt,
                False,  # verbose - candidates run in parallel, interleaved logs are noise
            )
            tables = result.get("tables", [])
            terms = [
                t.get("displayName", "")
                for t in result.get("terms", [])
                if t.get("displayName")
            ]

            # EntryLinks cannot be enumerated: the Catalog API exposes no
            # ListEntryLinks method. This used to report len(tables)+len(terms),
            # which is an invented number, not a measurement. In a demo whose
            # whole subject is metadata trustworthiness, printing a fabricated
            # figure is indefensible, so it reports zero and the UI omits it.
            return {
                "prompt": prompt,
                "tables": tables,
                "terms": terms,
                "table_count": len(tables),
                "term_count": len(terms),
                "raw_count": result.get("raw_count", len(tables)),
                "entry_link_count": 0,
                "top_10_tables": tables[:10],
            }
        except Exception as e:
            print(f"Exception during Knowledge Catalog search for '{prompt[:30]}': {e}")
            return {
                "prompt": prompt,
                "tables": [],
                "terms": [],
                "table_count": 0,
                "term_count": 0,
                "entry_link_count": 0,
                "top_10_tables": [],
            }

    async def evaluate_prompts(self, prompts: List[str]) -> Dict[str, Any]:
        """
        Executes parallel Knowledge Catalog search queries and evaluates results with
        Google Cloud Gemini Enterprise Agent Platform (Gemini 3.7 Flash).

        Args:
            prompts: List of 2 to 3 candidate natural language prompts.

        Returns:
            Dict[str, Any]: Comparative evaluation report with scores, strengths, weaknesses,
                            domain coverage matrix, and recommendation rationale.
        """
        token = get_access_token()
        if not token:
            return {"status": "error", "message": "Failed to obtain GCP access token."}

        # Step 1: Parallel asynchronous search execution across all candidates
        search_tasks = [self.search_single_prompt(p, token) for p in prompts]
        search_results = await asyncio.gather(*search_tasks)

        # Explicitly tag each search result with its prompt_id and index
        for i, sr in enumerate(search_results):
            sr["prompt_id"] = f"Prompt_{chr(65 + i)}"
            sr["index"] = i

        # Step 2: Construct evaluation prompt for Google Cloud Gemini Enterprise Agent Platform
        system_instruction = (
            "Today is Friday, November 27th, 2026.\n"
            "You are an expert Chief Data Officer and Google Cloud Data Architect. "
            "You are evaluating 2 to 3 candidate natural language search prompts used in Google Cloud Knowledge Catalog "
            "to dynamically discover BigQuery tables for a Black Friday revenue shortfall investigation in 'ecommerce_dw'.\n\n"
            "Key Investigation Forensic Pillars:\n"
            "1. Commercial Targets & Revenue Pacing (weekly_commercial_targets, daily_category_targets, category_15min_targets, sales_event_stream, orders, order_items)\n"
            "2. Warehouse Stockouts & Availability (oos_interactions, inventory_items, inventory_snapshots, products, categories)\n"
            "3. Logistics & Carrier Delivery SLAs (shipping_lead_times, distribution_centers)\n"
            "4. Marketing & Ad Bidding Throttling (ad_bidding_log, daily_ad_performance, ad_creatives, marketing_campaigns)\n"
            "5. Competitive Price Feeds & Recommendation Logs (competitor_price_feed, competitor_promotions, catalog_recommender_logs)\n\n"
            "SCORING GUIDELINES (Strictly Differentiate Scores 50-98 based on Table Count and Domain Breadth):\n"
            "- A prompt discovering ~28-30 tables with full 5-domain coverage should receive a top score of 92-96.\n"
            "- A prompt discovering ~20-22 tables missing 1 or 2 domains (e.g. logistics or marketing) should receive 75-84.\n"
            "- A prompt discovering <20 tables or missing multiple critical domains should receive 55-72.\n"
            "- NEVER give identical scores to prompts that retrieved different numbers of tables or different domain coverages.\n"
            "- Differentiate the scores clearly so the user sees a clear comparison (e.g. 95 vs 82 vs 68)."
        )

        llm_prompt_data = {
            "candidate_prompts_evaluated": [
                {
                    "prompt_id": f"Prompt_{chr(65 + i)}",
                    "prompt_text": res.get("prompt"),
                    "table_count": res.get("table_count"),
                    "tables_retrieved": res.get("tables"),
                    "top_tables": res.get("top_10_tables"),
                    "glossary_terms": res.get("terms"),
                }
                for i, res in enumerate(search_results)
            ]
        }

        user_content = (
            f"Here are the Knowledge Catalog search results for the candidate prompts:\n\n"
            f"{json.dumps(llm_prompt_data, indent=2)}\n\n"
            "Please analyze and compare these prompts. Return your evaluation strictly as JSON with this schema:\n"
            "{\n"
            '  "evaluations": [\n'
            '    {\n'
            '      "prompt_id": "Prompt_A",\n'
            '      "score": 95,\n'
            '      "summary": "Brief 1-sentence evaluation",\n'
            '      "strengths": ["...", "..."],\n'
            '      "weaknesses": ["..."],\n'
            '      "domain_coverage": {\n'
            '        "commercial_targets": "High / Medium / Low",\n'
            '        "stockouts_inventory": "High / Medium / Low",\n'
            '        "logistics_slas": "High / Medium / Low",\n'
            '        "paid_advertising": "High / Medium / Low",\n'
            '        "market_intelligence": "High / Medium / Low"\n'
            '      }\n'
            '    }\n'
            '  ],\n'
            '  "recommended_prompt_id": "Prompt_A",\n'
            '  "recommendation_rationale": "Why this prompt is optimal for the CMO workspace",\n'
            '  "executive_synthesis": "2-3 sentences summarizing the semantic differences"\n'
            "}"
        )

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "x-goog-user-project": self.project_id,
        }

        payload = {
            "contents": [{"role": "user", "parts": [{"text": user_content}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.2,
            },
        }

        # Step 3: Candidate models with resilient multi-region fallbacks.
        # The regional candidate follows BQ_LOCATION so nothing is pinned to one
        # region. This stays safe even if the chosen region does not serve the
        # model: "global" is both the first and the last candidate, so the chain
        # still succeeds.
        model_candidates = [
            ("global", "gemini-3.7-flash", 15),
            (LOCATION, "gemini-2.5-flash", 10),
            ("global", "gemini-2.5-flash", 10),
        ]

        evaluation_json = None
        model_used_label = "none"

        for location, model_name, req_timeout in model_candidates:
            if location == "global":
                endpoint_url = f"https://aiplatform.googleapis.com/v1/projects/{self.project_id}/locations/global/publishers/google/models/{model_name}:generateContent"
            else:
                endpoint_url = f"https://{location}-aiplatform.googleapis.com/v1/projects/{self.project_id}/locations/{location}/publishers/google/models/{model_name}:generateContent"

            try:
                res = await asyncio.to_thread(requests.post, endpoint_url, headers=headers, json=payload, timeout=req_timeout)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        text_response = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "{}")
                        evaluation_json = json.loads(text_response)
                        model_used_label = f"{model_name} ({location})"
                        break
                else:
                    print(f"Notice: Vertex AI {model_name} in {location} returned HTTP {res.status_code}")
            except Exception as e:
                print(f"Notice: Vertex AI {model_name} in {location} call: {e}")
                continue

        # Step 4: Fallback to deterministic rule engine if cloud LLM call is unavailable
        if not evaluation_json:
            evaluation_json = self._build_deterministic_evaluation(search_results)
            model_used_label = "deterministic-rule-engine"

        return {
            "status": "success",
            "model_used": model_used_label,
            "search_results": search_results,
            "evaluation": evaluation_json,
        }

    def _build_deterministic_evaluation(self, search_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Provides high-quality fallback evaluation if Gemini Enterprise Agent Platform is temporarily unreachable.
        Calculates scores based on table count (0-35 pts), domain breadth (0-40 pts), and priority alignment (0-20 pts).
        """
        evals = []
        best_id = "Prompt_A"
        max_score = -1

        for i, res in enumerate(search_results):
            pid = f"Prompt_{chr(65 + i)}"
            count = res.get("table_count", 0)
            tables = set(res.get("tables", []))
            top_tables = set(res.get("top_10_tables", []))

            # Domain presence checks across key diagnostic clusters
            has_targets = bool(tables.intersection({"weekly_commercial_targets", "daily_category_targets", "category_15min_targets", "sales_event_stream"}))
            has_stockouts = bool(tables.intersection({"oos_interactions", "inventory_items", "inventory_snapshots"}))
            has_shipping = bool(tables.intersection({"shipping_lead_times", "distribution_centers"}))
            has_ads = bool(tables.intersection({"ad_bidding_log", "daily_ad_performance", "ad_creatives"}))
            has_competitor = bool(tables.intersection({"competitor_price_feed", "competitor_promotions", "catalog_recommender_logs"}))

            # Dynamic multi-factor scoring (Range: 50 - 96)
            # Factor 1: Table Volume (0 to 35 pts)
            volume_pts = min(35, int((count / 30.0) * 35))
            
            # Factor 2: Domain Coverage (0 to 40 pts, 8 pts per domain)
            domain_flags = [has_targets, has_stockouts, has_shipping, has_ads, has_competitor]
            domain_pts = sum(8 for d in domain_flags if d)
            
            # Factor 3: Top-10 Priority Alignment (0 to 20 pts)
            priority_tables = {"weekly_commercial_targets", "sales_event_stream", "oos_interactions", "ad_bidding_log", "daily_category_targets"}
            priority_pts = min(20, len(top_tables.intersection(priority_tables)) * 4)

            # Composite Score (minimum 50, maximum 96)
            score = max(50, min(96, volume_pts + domain_pts + priority_pts))
            
            if score > max_score:
                max_score = score
                best_id = pid

            strengths = [f"Retrieved {count} tables across BigQuery warehouse"]
            if has_targets:
                strengths.append("High priority on commercial revenue pacing and 15-min targets")
            if has_stockouts and has_ads:
                strengths.append("Covers supply chain out-of-stock and ad spend throttling")

            weaknesses = []
            if not has_shipping:
                weaknesses.append("Missing regional logistics SLAs and carrier lead times")
            if not has_competitor:
                weaknesses.append("Lacks competitive price intelligence and benchmark promotions")
            if count < 25:
                weaknesses.append(f"Sub-optimal forensic breadth ({count} tables vs 29 benchmark)")

            evals.append({
                "prompt_id": pid,
                "score": score,
                "summary": f"Discovered {count} relevant tables across commercial and operational domains.",
                "strengths": strengths,
                "weaknesses": weaknesses,
                "domain_coverage": {
                    "commercial_targets": "High" if has_targets else "Low",
                    "stockouts_inventory": "High" if has_stockouts else "Low",
                    "logistics_slas": "High" if has_shipping else "Low",
                    "paid_advertising": "High" if has_ads else "Low",
                    "market_intelligence": "High" if has_competitor else "Low"
                }
            })

        return {
            "evaluations": evals,
            "recommended_prompt_id": best_id,
            "recommendation_rationale": f"{best_id} achieved the highest diagnostic table coverage ({max_score}/100) with balanced domain representation.",
            "executive_synthesis": "Comparative evaluation indicates significant differences in domain breadth and operational table capture across the candidate queries."
        }

