"""
Google Cloud Gemini Enterprise Agent Platform (Conversational Analytics API) Integration Service
=================================================================================================
Core backend proxy and analytical reasoning integration service connecting LumièreShop
with Google Cloud Gemini Data Analytics REST API (`geminidataanalytics.googleapis.com`).

Key Capabilities:
-----------------
1. Multi-Tier Authentication:
   Automatically detects and caches OAuth 2.0 access tokens via:
   - Application Default Credentials (ADC) / Cloud Run IAM service accounts.
   - Local development `gcloud auth print-access-token` fallback.
   - Explicit `GCP_ACCESS_TOKEN` environment variable.

2. Server-Managed Conversation Lifecycle:
   Creates and manages persistent server-side Conversation resources on Google Cloud
   (`projects/{project}/locations/global/conversations/{uuid}`) to maintain multi-turn
   state and pronoun resolution ("that category", "compare it with last year").

3. Dynamic Data Agent Grounding & Patching:
   Dynamically patches the data agent's `publishedContext.datasourceReferences.bq.tableReferences`
   with the tables discovered via Knowledge Catalog semantic search.

4. 4-Stage Analytical Reasoning Engine:
   Unwraps multi-step system responses, extracting:
   - Formulated BigQuery SQL queries.
   - Result datasets and row counts.
   - Vega-Lite interactive chart specifications.
   - BigQuery execution job IDs, scanned bytes, and slot milliseconds.
   - Follow-up diagnostic investigation questions.

5. Enterprise Audit Logging:
   Asynchronously logs every analytical interaction into `ecommerce_dw.agent_interaction_logs`.
"""

import os
import sys
import uuid
import time
import json
import requests
import subprocess
import google.auth
import google.auth.transport.requests
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Set
from google.cloud import bigquery
from google.oauth2 import credentials as oauth2_credentials
from app.config import (
    PROJECT_ID,
    LOCATION,
    DATASET_ID,
    DATASET_2ND_ID,
    DATASET_3RD_ID,
    DATASET_MAPPING,
    USER_IDENTITY,
    DATA_AGENT_ID,
    DATA_AGENT_A_ID,
    DATA_AGENT_B_ID,
    DATA_AGENT_C_ID,
    DATA_AGENT_NAME,
    MULTI_DATA_AGENTS,
)

# Primary Google Cloud Data Agent resource path and chat endpoint
CHAT_API_ENDPOINT = f"https://geminidataanalytics.googleapis.com/v1beta/projects/{PROJECT_ID}/locations/global:chat"

# Static system instruction anchoring all Conversational Analytics Data Agents to Black Friday 2026
AGENT_SYSTEM_INSTRUCTION = (
    "Today is Friday, 27 November 2026. The current time is 14:30:00 UTC.\n"
    "This data warehouse is a point-in-time snapshot taken at that instant: "
    "no operational record exists after 2026-11-27 14:30:00 UTC.\n"
    "\n"
    "Resolve every relative time expression - \"now\", \"today\", \"so far\", "
    "\"the last hour\", \"this week\", \"yesterday\", \"week to date\" - against "
    "2026-11-27 14:30:00 UTC, never against the real-world clock.\n"
    "\n"
    "Never use CURRENT_DATE(), CURRENT_TIMESTAMP(), CURRENT_DATETIME() or NOW() "
    "in generated SQL. They resolve to the real-world date, which falls outside "
    "this data\'s range, so they silently match either every row or no rows. "
    "Always write explicit date and timestamp literals.\n"
    "\n"
    "When a question concerns one product category, every rate and ratio in your "
    "answer must be computed for that same category. Do not pair a category-level "
    "numerator with a site-level denominator, and do not substitute a sitewide "
    "rate for a category rate - the two differ materially and the error is "
    "silent.\n"
    "\n"
    "When a metric has more than one accepted convention - for example a rate "
    "restricted to paid sessions versus one covering all sessions - state which "
    "convention you used, and apply the same convention to both the figure and "
    "anything you compare it against."
)

# Cached Google OAuth credential instance
_google_creds = None


def get_access_token() -> Optional[str]:
    """
    Retrieves a valid Google Cloud OAuth 2.0 access token using a 3-tier cascade:
    1. Google Application Default Credentials (ADC / Cloud Run managed service account).
    2. Local `gcloud auth print-access-token` CLI fallback.
    3. `GCP_ACCESS_TOKEN` environment variable.

    Returns:
        Optional[str]: Bearer token string if authenticated, None otherwise.
    """
    global _google_creds
    
    # 1. Try Google Application Default Credentials (ADC / Cloud Run managed service account)
    try:
        if _google_creds is None:
            _google_creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        
        auth_req = google.auth.transport.requests.Request()
        if not _google_creds.valid:
            _google_creds.refresh(auth_req)
        
        if _google_creds.token:
            return _google_creds.token
    except Exception:
        _google_creds = None

    # 2. Fallback to gcloud CLI in local development environment
    gcloud_paths = ["/google/data/ro/teams/cloud-sdk/gcloud", "gcloud"]
    for gcloud_cmd in gcloud_paths:
        try:
            res = subprocess.run([gcloud_cmd, "auth", "print-access-token"], capture_output=True, text=True, timeout=10)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            continue

    # 3. Static env var fallback
    return os.environ.get("GCP_ACCESS_TOKEN")


def get_bigquery_client() -> bigquery.Client:
    """
    Returns an authenticated Google Cloud BigQuery client instance
    using the active OAuth token or ADC.
    """
    token = get_access_token()
    if token:
        creds = oauth2_credentials.Credentials(token)
        return bigquery.Client(project=PROJECT_ID, credentials=creds)
    return bigquery.Client(project=PROJECT_ID)
def _format_raw_data_markdown(data_rows: List[Dict[str, Any]], max_rows: int = 25) -> str:
    """Formats raw query result dictionary rows into a clean Markdown table."""
    if not data_rows or not isinstance(data_rows, list):
        return ""
    valid_rows = [r for r in data_rows if isinstance(r, dict)]
    if not valid_rows:
        return ""

    headers = list(valid_rows[0].keys())
    if not headers:
        return ""

    md_lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join([":---" for _ in headers]) + " |"
    ]
    for row in valid_rows[:max_rows]:
        vals = [str(row.get(h, "")).replace("|", "\\|").replace("\n", " ") for h in headers]
        md_lines.append("| " + " | ".join(vals) + " |")

    if len(valid_rows) > max_rows:
        md_lines.append(f"\n*(Showing first {max_rows} of {len(valid_rows)} raw rows)*")

    return "\n".join(md_lines)


def format_real_thinking_process(
    api_response_data: Any,
    raw_thinking_texts: Optional[List[str]] = None,
    table_data: Optional[List[Dict[str, Any]]] = None,
    generated_sql: Optional[str] = None,
    bq_job_id: Optional[str] = None,
    elapsed_ms: int = 0,
    **kwargs: Any
) -> str:
    """
    Formats the real thinking process exactly as outputted by the BigQuery Data Agent:
    - Pastes verbatim thoughts received from the agent (no canned summary).
    - Embeds the raw data rows returned from BigQuery for queries executed during thinking.
    - Preserves executed SQL code blocks and query telemetry.
    """
    blocks = []
    seen_tables = False

    if isinstance(api_response_data, list):
        for step in api_response_data:
            sys_msg = step.get("systemMessage", {})

            # 1. Thought texts from agent
            if "text" in sys_msg:
                text_obj = sys_msg["text"]
                text_type = text_obj.get("textType", "")
                parts = text_obj.get("parts", [])
                text_val = text_obj.get("text", "")

                # Only include thoughts in the thinking process
                if text_type == "THOUGHT" or (not text_type and text_type not in ("FINAL_RESPONSE", "FOLLOWUP_QUESTIONS")):
                    thought_parts = parts if parts else ([text_val] if text_val else [])
                    if thought_parts:
                        formatted_parts = []
                        for idx, p in enumerate(thought_parts):
                            p_clean = p.strip()
                            if not p_clean:
                                continue
                            # Format SQL queries in fenced code blocks
                            if any(p_clean.upper().startswith(kw) for kw in ["SELECT", "WITH", "CREATE", "SHOW", "DESCRIBE"]):
                                formatted_parts.append(f"```sql\n{p_clean}\n```")
                            elif idx == 0 and len(thought_parts) > 1:
                                formatted_parts.append(f"**{p_clean}**")
                            else:
                                formatted_parts.append(p_clean)
                        if formatted_parts:
                            blocks.append("\n\n".join(formatted_parts))

            # 2. Raw query data returned from BigQuery
            if "data" in sys_msg:
                data_obj = sys_msg["data"]
                if "result" in data_obj and "data" in data_obj["result"]:
                    rows = data_obj["result"]["data"]
                    if rows and isinstance(rows, list):
                        table_md = _format_raw_data_markdown(rows)
                        if table_md:
                            seen_tables = True
                            blocks.append(f"**Raw Data Results ({len(rows)} rows):**\n\n{table_md}")

    # Fallback if no table data was encountered in steps but table_data is present
    if not seen_tables and table_data and isinstance(table_data, list):
        table_md = _format_raw_data_markdown(table_data)
        if table_md:
            blocks.append(f"**Raw Data Results ({len(table_data)} rows):**\n\n{table_md}")

    # Fallback to raw_thinking_texts if blocks is empty
    if not blocks and raw_thinking_texts:
        for t in raw_thinking_texts:
            if t and t.strip():
                blocks.append(t.strip())

    return "\n\n".join(blocks).strip()


# Backward-compatible alias for any existing callers
def format_rich_thinking_process(*args: Any, **kwargs: Any) -> str:
    if args and isinstance(args[0], list) and args[0] and isinstance(args[0][0], dict):
        return format_real_thinking_process(api_response_data=args[0], **kwargs)
    raw_texts = kwargs.get("raw_thinking_texts", args[0] if args else [])
    table_data = kwargs.get("table_data")
    return format_real_thinking_process(api_response_data=[], raw_thinking_texts=raw_texts, table_data=table_data, **kwargs)


# Conversations API endpoint for server-managed stateful sessions
CONVERSATIONS_API_ENDPOINT = f"https://geminidataanalytics.googleapis.com/v1/projects/{PROJECT_ID}/locations/global/conversations"

# In-memory mapping of client session IDs to server-managed GCP conversation resources
_session_conversations: Dict[str, str] = {}


def create_conversation(data_agent_name: str = None) -> Optional[str]:
    """
    Creates a new server-managed Conversation resource on Google Cloud Conversational Analytics API.

    Args:
        data_agent_name: Target Google Cloud Data Agent resource identifier.

    Returns:
        Optional[str]: Fully qualified conversation resource name (e.g., 'projects/.../conversations/...').
    """
    token = get_access_token()
    if not token:
        print("Notice: No access token available for conversation creation.", file=sys.stderr)
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-goog-user-project": PROJECT_ID
    }

    agent_name = data_agent_name or DATA_AGENT_NAME
    payload = {
        "agents": [agent_name]
    }

    try:
        res = requests.post(CONVERSATIONS_API_ENDPOINT, headers=headers, json=payload, timeout=30)
        if res.status_code in [200, 201]:
            data = res.json()
            conv_name = data.get("name")
            return conv_name
        else:
            print(f"Notice: Conversation creation returned HTTP {res.status_code}: {res.text}", file=sys.stderr)
            return None
    except Exception as e:
        print(f"Notice: Failed to create conversation resource on GCP: {e}", file=sys.stderr)
        return None


def get_or_create_session_conversation(session_id: str, data_agent_name: str = None) -> Optional[str]:
    """
    Retrieves the existing server-managed conversation resource for a session,
    or provisions a fresh one if none exists.

    Args:
        session_id: Unique client session string.
        data_agent_name: Optional target Data Agent resource name.

    Returns:
        Optional[str]: Active GCP conversation resource name.
    """
    global _session_conversations
    if not session_id:
        return create_conversation(data_agent_name)
    if session_id not in _session_conversations or not _session_conversations[session_id]:
        conv = create_conversation(data_agent_name)
        if conv:
            _session_conversations[session_id] = conv
    return _session_conversations.get(session_id)


def reset_session_conversation(session_id: str = None, data_agent_name: str = None) -> Optional[str]:
    """
    Forces the recreation of a fresh server-managed Conversation resource for a session,
    clearing previous conversational history in Google Cloud.

    Args:
        session_id: Client session identifier.
        data_agent_name: Target Data Agent resource name.

    Returns:
        Optional[str]: New GCP conversation resource name.
    """
    global _session_conversations
    conv = create_conversation(data_agent_name)
    if session_id and conv:
        _session_conversations[session_id] = conv
    return conv

def update_multi_agent_sources(
    agent_name: str,
    table_names: List[str],
    glossary_terms: Optional[List[Dict[str, str]]] = None,
) -> None:
    """
    Updates the mapped table data sources for a specific agent in the 3-Agent Parallel Workspace
    (Agent A, Agent B, or Agent C).

    Args:
        agent_name: Key in MULTI_DATA_AGENTS ('Agent A', 'Agent B', 'Agent C').
        table_names: BigQuery table identifiers to map to this agent. The names
            are remapped into the agent's own dataset via DATASET_MAPPING, so
            all three tiers see identical data with different metadata.
        glossary_terms: Knowledge Catalog terms, as
            [{"displayName", "description"}]. Pass them for the catalog tier;
            pass None for Tiers B and C, which have no governed glossary.

    WHY glossaryTerms IS ALWAYS IN THE UPDATE MASK
    ----------------------------------------------
    Until 2026-09-13 this function wrote only tableReferences and
    systemInstruction, and the mask omitted glossaryTerms entirely.

    Agent A nevertheless had 33 glossary terms attached, which looked correct.
    It was not: those terms had been written by `scripts/06_update_data_agent.py`
    and merely SURVIVED this call, because a field absent from the update mask
    is left alone. The live demo was not injecting catalog context at all - it
    was inheriting it from a setup script that had run hours earlier, and the
    day someone added glossaryTerms to the mask for any other reason, Agent A
    would have silently lost its entire catalog advantage mid-demo.

    Keeping the field in the mask ALWAYS makes the behaviour explicit in both
    directions: the catalog tier gets its terms written every time, and Tiers B
    and C get theirs actively cleared rather than left to chance.
    """
    agent_res = MULTI_DATA_AGENTS.get(agent_name)
    if not agent_res:
        return
    token = get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-goog-user-project": PROJECT_ID
    } if token else {}
    if token:
        try:
            target_dataset = DATASET_MAPPING.get(agent_name, DATASET_ID)
            update_url = (
                f"https://geminidataanalytics.googleapis.com/v1beta/{agent_res}"
                "?updateMask=dataAnalyticsAgent.publishedContext.datasourceReferences.bq.tableReferences"
                ",dataAnalyticsAgent.publishedContext.systemInstruction"
                ",dataAnalyticsAgent.publishedContext.glossaryTerms"
            )
            table_refs = [
                {"projectId": PROJECT_ID, "datasetId": target_dataset, "tableId": t}
                for t in table_names
            ]
            published: Dict[str, Any] = {
                "systemInstruction": AGENT_SYSTEM_INSTRUCTION,
                "datasourceReferences": {
                    "bq": {
                        "tableReferences": table_refs
                    }
                }
            }
            if glossary_terms:
                published["glossaryTerms"] = glossary_terms
            payload = {"dataAnalyticsAgent": {"publishedContext": published}}

            gloss_note = (
                f" and {len(glossary_terms)} Knowledge Catalog glossary terms"
                if glossary_terms else ""
            )
            res = requests.patch(update_url, headers=headers, json=payload, timeout=15)
            if res.status_code in [200, 201]:
                print(f"✅ Successfully updated {agent_name} ({agent_res}) with {len(table_names)} tables in '{target_dataset}'{gloss_note}.")
            elif res.status_code == 404:
                agent_id = agent_res.split("/")[-1]
                print(f"ℹ️ Agent {agent_name} ({agent_id}) does not exist. Creating dynamically with {len(table_names)} tables in '{target_dataset}'...")
                create_url = f"https://geminidataanalytics.googleapis.com/v1beta/projects/{PROJECT_ID}/locations/global/dataAgents?dataAgentId={agent_id}"
                create_payload = {
                    "displayName": f"LumiereShop {agent_name}",
                    "description": f"Grounded Agent for {agent_name} in {target_dataset}",
                    **payload
                }
                c_res = requests.post(create_url, headers=headers, json=create_payload, timeout=20)
                if c_res.status_code in [200, 201]:
                    print(f"✅ Successfully created and grounded {agent_name} ({agent_id}) with {len(table_names)} tables in '{target_dataset}'{gloss_note}.")
                else:
                    print(f"Notice: Failed to create {agent_name}: HTTP {c_res.status_code} - {c_res.text}")
            else:
                print(f"Notice: Failed to update {agent_name}: HTTP {res.status_code} - {res.text}")
        except Exception as e:
            print(f"Notice: Multi-agent source update exception for {agent_name}: {e}", file=sys.stderr)


def send_cmo_prompt(
    prompt: str,
    session_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    target_tables: Optional[List[str]] = None,
    user_name: Optional[str] = None,
    menu_item: Optional[str] = "chat",
    agent_no: Optional[str] = None,
    thinking_mode: Optional[str] = "FAST",
) -> Dict[str, Any]:
    """
    Dispatches a natural language analytics query to the Google Cloud Gemini Data Analytics REST API.
    Unwraps the multi-step system response, extracts generated SQL, Vega-Lite charts, BigQuery job
    telemetry, constructs 4-stage analytical reasoning traces, and logs interaction into BigQuery.

    Args:
        prompt: Natural language question from the business user.
        session_id: Client session identifier.
        conversation_id: Optional server-managed conversation resource string.
        agent_name: Optional specific agent name for 3-Agent cockpit execution.
        target_tables: Optional list of BigQuery table names.
        user_name: Optional user identifier or display name.
        menu_item: Interface menu context initiating interaction ('chat' vs 'compare chats').
        agent_no: Agent column identifier in comparative mode ('agentA', 'agentB', 'agentC', or None).
        thinking_mode: Thinking mode flag ('FAST' for rapid low-latency response, 'THINKING' for detailed reasoning).

    Returns:
        Dict[str, Any]: Formatted response payload with markdown text, reasoning, SQL, chart info, and metrics.
    """
    token = get_access_token()
    if not token:
        raise RuntimeError("GCP OAuth access token could not be retrieved.")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-goog-user-project": PROJECT_ID
    }

    if not session_id:
        session_id = f"SESS-CA-{uuid.uuid4().hex[:8]}"
    start_time = time.time()

    # Normalize thinking mode (FAST vs THINKING, default to FAST if unspecified)
    valid_thinking_modes = {"FAST", "THINKING", "THINKING_MODE_UNSPECIFIED"}
    normalized_thinking_mode = (thinking_mode or "FAST").upper()
    if normalized_thinking_mode not in valid_thinking_modes:
        normalized_thinking_mode = "FAST"

    # Step 1: Determine target GCP Data Agent resource
    target_data_agent = MULTI_DATA_AGENTS.get(agent_name, DATA_AGENT_NAME)

    # Step 2: Determine server-managed conversation resource
    conv_name = conversation_id
    if conv_name:
        if not conv_name.startswith("projects/"):
            conv_name = f"projects/{PROJECT_ID}/locations/global/conversations/{conv_name}"
    else:
        conv_name = get_or_create_session_conversation(session_id, data_agent_name=target_data_agent)

    # Step 3: Construct server-managed stateful payload with nested data_agent_context
    if conv_name:
        payload = {
            "parent": f"projects/{PROJECT_ID}/locations/global",
            "messages": [
                {
                    "userMessage": {
                        "text": prompt
                    }
                }
            ],
            "conversation_reference": {
                "conversation": conv_name,
                "data_agent_context": {
                    "data_agent": target_data_agent
                }
            },
            "thinking_mode": normalized_thinking_mode
        }
    else:
        # Fallback to direct data_agent_context if conversation creation was unavailable
        payload = {
            "parent": f"projects/{PROJECT_ID}/locations/global",
            "messages": [
                {
                    "userMessage": {
                        "text": prompt
                    }
                }
            ],
            "data_agent_context": {
                "data_agent": target_data_agent
            },
            "thinking_mode": normalized_thinking_mode
        }

    raw_response_text = ""
    api_response_data = []
    text_answer = ""
    generated_sql = ""
    table_data = []
    error_message = None

    try:
        max_retries = 4
        for attempt in range(max_retries):
            res = requests.post(CHAT_API_ENDPOINT, headers=headers, json=payload, timeout=180)
            if res.status_code == 429 and attempt < max_retries - 1:
                time.sleep(6 * (attempt + 1))
                continue
            break

        elapsed_ms = int((time.time() - start_time) * 1000)
        raw_response_text = res.text

        if res.status_code == 200:
            api_response_data = res.json()
            
            # Step 4: Parse step objects from array as in reference repository and official GCP docs
            if isinstance(api_response_data, list):
                final_texts = []
                thinking_texts = []
                all_texts = []
                followups = []
                ref_tables = set()
                has_chart = False
                chart_type = None

                for step in api_response_data:
                    sys_msg = step.get("systemMessage", {})
                    if "text" in sys_msg:
                        text_obj = sys_msg["text"]
                        text_type = text_obj.get("textType", "")
                        parts = text_obj.get("parts", [])
                        text_val = text_obj.get("text", "")
                        
                        combined = "\n".join(parts) if parts else text_val
                        if combined:
                            all_texts.append(combined)
                            if text_type == "FINAL_RESPONSE":
                                final_texts.append(combined)
                            elif text_type == "FOLLOWUP_QUESTIONS":
                                followups.extend(parts if parts else [text_val])
                            else:
                                thinking_texts.append(combined)
                    
                    if "data" in sys_msg:
                        data_obj = sys_msg["data"]
                        if "generatedSql" in data_obj:
                            generated_sql = data_obj["generatedSql"]
                        if "result" in data_obj and "data" in data_obj["result"]:
                            table_data = data_obj["result"]["data"]
                        if "bigQueryJob" in data_obj:
                            bq_job_info = data_obj["bigQueryJob"]
                            bq_job_id = bq_job_info.get("jobId")
                            bq_job_location = bq_job_info.get("location", LOCATION)
                        if "query" in data_obj and "datasources" in data_obj["query"]:
                            for ds in data_obj["query"]["datasources"]:
                                if "bigqueryTableReference" in ds:
                                    tbl_ref = ds["bigqueryTableReference"]
                                    t_name = f"{tbl_ref.get('datasetId','')}.{tbl_ref.get('tableId','')}"
                                    ref_tables.add(t_name)

                    if "chart" in sys_msg:
                        has_chart = True
                        chart_info = sys_msg.get("chart", {})
                        chart_type = chart_info.get("type", "vega_chart")

                text_answer = "\n\n".join(final_texts) if final_texts else "\n\n".join(all_texts)
                thinking_process = format_real_thinking_process(
                    api_response_data=api_response_data,
                    raw_thinking_texts=thinking_texts,
                    table_data=table_data if 'table_data' in locals() and table_data else None,
                    generated_sql=generated_sql if 'generated_sql' in locals() else None,
                    bq_job_id=bq_job_id if 'bq_job_id' in locals() else None,
                    elapsed_ms=elapsed_ms,
                )

                # Step 5: Retrieve actual BigQuery bytes & execution metadata from job
                bytes_scanned = 0
                bytes_billed = 0
                slot_millis = 0
                if 'bq_job_id' in locals() and bq_job_id:
                    try:
                        bq_client = get_bigquery_client()
                        job_details = bq_client.get_job(bq_job_id, location=bq_job_location)
                        if job_details:
                            if job_details.total_bytes_processed is not None:
                                bytes_scanned = job_details.total_bytes_processed
                            if job_details.total_bytes_billed is not None:
                                bytes_billed = job_details.total_bytes_billed
                            if job_details.slot_millis is not None:
                                slot_millis = job_details.slot_millis
                    except Exception as bq_err:
                        print(f"Notice: Failed to fetch BQ job metadata for {bq_job_id}: {bq_err}", file=sys.stderr)

        else:
            error_details = ""
            try:
                err_json = res.json().get("error", {})
                error_details = err_json.get("message", "")
            except Exception:
                error_details = res.text[:300]

            error_message = f"CA API HTTP {res.status_code}: {res.reason}"
            if error_details:
                text_answer = f"Gemini Data Analytics API Notice (HTTP {res.status_code}):\n{error_details}"
            else:
                text_answer = f"Gemini Data Analytics API response received (HTTP {res.status_code})."

    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        error_message = str(e)
        text_answer = f"API Communication Exception: {e}"

    # Return combined structured response payload and raw steps array
    response_payload = {
        "session_id": session_id,
        "conversation_id": conv_name,
        "is_stateful": bool(conv_name),
        "user_prompt": prompt,
        "thinking_mode": normalized_thinking_mode,
        "text": text_answer.strip() if text_answer.strip() else None,
        "thinking_process": thinking_process.strip() if 'thinking_process' in locals() and thinking_process and thinking_process.strip() else None,
        "generated_sql": generated_sql if generated_sql else None,
        "table_data": table_data if table_data else None,
        "steps": api_response_data,
        "error": error_message,
        "execution_time_ms": elapsed_ms,
        "bytes_scanned": bytes_scanned if 'bytes_scanned' in locals() else 0,
        "bytes_billed": bytes_billed if 'bytes_billed' in locals() else 0,
        "slot_milliseconds": slot_millis if 'slot_millis' in locals() else 0,
        "job_id": bq_job_id if 'bq_job_id' in locals() else None,
        "referenced_tables": list(ref_tables) if 'ref_tables' in locals() and ref_tables else [],
        "has_chart": has_chart if 'has_chart' in locals() else False,
        "data_agent": DATA_AGENT_NAME,
        "ca_api_endpoint": CHAT_API_ENDPOINT,
        "raw_response": raw_response_text
    }

    # Step 6: Log rich interaction trace into BigQuery agent_interaction_logs asynchronously
    log_record = [{
        "interaction_id": str(uuid.uuid4()),
        "session_id": session_id,
        "user_name": user_name or USER_IDENTITY,
        "user_account": USER_IDENTITY,
        "user_prompt": prompt,
        "generated_sql": generated_sql if generated_sql else "N/A",
        "response_text": (text_answer if text_answer else raw_response_text)[:1000],
        "execution_time_ms": elapsed_ms,
        "bytes_scanned": bytes_scanned if 'bytes_scanned' in locals() else 0,
        "bytes_billed": bytes_billed if 'bytes_billed' in locals() else 0,
        "slot_milliseconds": slot_millis if 'slot_millis' in locals() else 0,
        "job_id": bq_job_id if 'bq_job_id' in locals() else None,
        "referenced_tables": json.dumps(list(ref_tables)) if 'ref_tables' in locals() and ref_tables else None,
        "result_row_count": len(table_data) if table_data else 0,
        "thinking_process": (thinking_process[:10000] if 'thinking_process' in locals() and thinking_process else None),
        "step_count": len(api_response_data) if isinstance(api_response_data, list) else 0,
        "has_chart": has_chart if 'has_chart' in locals() else False,
        "chart_type": chart_type if 'chart_type' in locals() else None,
        "followup_questions": json.dumps(followups) if 'followups' in locals() and followups else None,
        "data_agent_id": f"{DATA_AGENT_NAME}-{agent_name.lower().replace(' ', '-')}" if agent_name else DATA_AGENT_NAME,
        "http_status_code": res.status_code if 'res' in locals() and hasattr(res, 'status_code') else 200,
        "ca_api_endpoint": CHAT_API_ENDPOINT,
        "raw_ca_api_response": raw_response_text[:10000],
        "menu_item": menu_item or "chat",
        "agent_no": agent_no if agent_no else None,
        "thinking_mode": normalized_thinking_mode,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    }]

    try:
        bq_client = get_bigquery_client()
        table_ref = f"{PROJECT_ID}.{DATASET_ID}.agent_interaction_logs"
        bq_client.insert_rows_json(table_ref, log_record, ignore_unknown_values=True)
    except Exception as e:
        print(f"Notice: Log write failed: {e}", file=sys.stderr)

    if agent_name:
        response_payload["agent_name"] = agent_name

    return response_payload


def get_recent_logs(limit: int = 20, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Queries and returns recent interaction telemetry logs from BigQuery table `agent_interaction_logs`.

    Args:
        limit: Maximum number of records to retrieve (default: 20).
        session_id: Optional session filter string.

    Returns:
        List[Dict[str, Any]]: List of interaction log records.
    """
    bq_client = get_bigquery_client()
    where_clause = f"WHERE session_id = '{session_id}'" if session_id else ""
    query = f"""
        SELECT interaction_id, session_id, user_name, menu_item, agent_no, user_prompt, generated_sql, response_text, execution_time_ms, bytes_scanned, job_id, referenced_tables, result_row_count, step_count, has_chart, ca_api_endpoint, created_at 
        FROM `{PROJECT_ID}.{DATASET_ID}.agent_interaction_logs`
        {where_clause}
        ORDER BY created_at DESC 
        LIMIT {limit}
    """
    results = bq_client.query(query).result()
    logs = []
    for r in results:
        logs.append({
            "interaction_id": r.interaction_id,
            "session_id": r.session_id,
            "user_name": getattr(r, 'user_name', None) or "N/A",
            "menu_item": getattr(r, 'menu_item', None) or "chat",
            "agent_no": getattr(r, 'agent_no', None),
            "user_prompt": r.user_prompt,
            "generated_sql": r.generated_sql,
            "response_text": r.response_text,
            "execution_time_ms": r.execution_time_ms,
            "bytes_scanned": r.bytes_scanned if hasattr(r, 'bytes_scanned') and r.bytes_scanned else 0,
            "job_id": getattr(r, 'job_id', None),
            "referenced_tables": getattr(r, 'referenced_tables', None),
            "result_row_count": getattr(r, 'result_row_count', 0),
            "step_count": getattr(r, 'step_count', 0),
            "has_chart": getattr(r, 'has_chart', False),
            "ca_api_endpoint": r.ca_api_endpoint,
            "created_at": str(r.created_at)
        })
    return logs


# In-memory list of currently active BigQuery tables grounded in the primary Data Agent
_active_mapped_tables: List[str] = []


def update_data_agent_sources(
    table_names: List[str],
    glossary_terms: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Updates the mapped table data sources for the primary BigQuery Data Agent (DATA_AGENT_ID).
    Preserves the exact same agent ID while configuring its authorized BigQuery table sources.

    Args:
        table_names: BigQuery table names discovered via Knowledge Catalog.
        glossary_terms: Knowledge Catalog business glossary terms, as
            [{"displayName", "description"}]. The primary agent backs the
            single-agent CMO workspace, which is the catalog-equipped
            experience, so it should normally receive them.

    Returns:
        Dict[str, Any]: Confirmation dictionary with table count and mapped names.

    glossaryTerms is in the update mask for the same reason as in
    `update_multi_agent_sources` - so that what the agent ends up holding is
    always what this call decided, never a leftover from an earlier run of
    `scripts/06_update_data_agent.py`.
    """
    global _active_mapped_tables
    _active_mapped_tables = table_names

    token = get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-goog-user-project": PROJECT_ID
    } if token else {}

    # Update the live GCP BigQuery Data Agent publishedContext via REST API
    if token:
        try:
            update_url = (
                f"https://geminidataanalytics.googleapis.com/v1beta/{DATA_AGENT_NAME}"
                "?updateMask=dataAnalyticsAgent.publishedContext.datasourceReferences.bq.tableReferences"
                ",dataAnalyticsAgent.publishedContext.systemInstruction"
                ",dataAnalyticsAgent.publishedContext.glossaryTerms"
            )
            table_refs = [
                {"projectId": PROJECT_ID, "datasetId": DATASET_ID, "tableId": t}
                for t in table_names
            ]
            published: Dict[str, Any] = {
                "systemInstruction": AGENT_SYSTEM_INSTRUCTION,
                "datasourceReferences": {
                    "bq": {
                        "tableReferences": table_refs
                    }
                }
            }
            if glossary_terms:
                published["glossaryTerms"] = glossary_terms
            payload = {"dataAnalyticsAgent": {"publishedContext": published}}
            res = requests.patch(update_url, headers=headers, json=payload, timeout=12)
            if res.status_code in [200, 201]:
                print(f"✅ Successfully updated live GCP BigQuery Data Agent `{DATA_AGENT_ID}` with {len(table_names)} tables.")
            elif res.status_code == 404:
                print(f"ℹ️ Primary Data Agent `{DATA_AGENT_ID}` does not exist. Creating dynamically with {len(table_names)} tables...")
                create_url = f"https://geminidataanalytics.googleapis.com/v1beta/projects/{PROJECT_ID}/locations/global/dataAgents?dataAgentId={DATA_AGENT_ID}"
                create_payload = {
                    "displayName": "LumiereShop Primary CMO Data Agent",
                    "description": "Dynamic Knowledge Catalog Grounded Data Agent for LumiereShop",
                    **payload
                }
                c_res = requests.post(create_url, headers=headers, json=create_payload, timeout=20)
                if c_res.status_code in [200, 201]:
                    print(f"✅ Successfully created and grounded primary Data Agent `{DATA_AGENT_ID}` with {len(table_names)} tables.")
                else:
                    print(f"Notice: Failed to create primary Data Agent `{DATA_AGENT_ID}`: HTTP {c_res.status_code} - {c_res.text}")
            else:
                print(f"Notice: GCP BigQuery Data Agent patch returned HTTP {res.status_code}: {res.text}")
        except Exception as e:
            print(f"Notice: Live GCP BigQuery Data Agent patch call: {e}")

    return {
        "status": "success",
        "data_agent_id": DATA_AGENT_ID,
        "data_agent_name": DATA_AGENT_NAME,
        "table_count": len(table_names),
        "tables": table_names
    }


def get_active_mapped_tables() -> List[str]:
    """Returns the list of currently active BigQuery tables mapped to the Data Agent."""
    return _active_mapped_tables

