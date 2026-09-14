"""
LumièreShop Backend Gateway API
================================
Main FastAPI application and routing gateway for the LumièreShop Enterprise
Conversational Analytics Platform.

Architecture Overview:
----------------------
1. Client Interface:
   Serves the Material Design 3 single-page application (`/static/index.html`).
2. Semantic Context Discovery:
   Endpoints (`/api/prepare-data`, `/api/evaluate-prompts`) interface with Google Cloud
   Knowledge Catalog (`dataplex.googleapis.com`) to dynamically map plain-English business
   intents to the exact required BigQuery warehouse tables.
3. Conversational Analytics Routing:
   Routes analytical inquiries (`/api/chat`, `/api/multi-chat`) to the Gemini Enterprise
   Agent Platform / BigQuery Data Agent API (`geminidataanalytics.googleapis.com`).
4. Stateful Session Lifecycle:
   Manages server-managed Google Cloud conversation resources and asynchronous audit
   logging into BigQuery (`agent_interaction_logs`).
"""

import os
import sys
from typing import Optional, List
import anyio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

# Core configuration parameters loaded from environment / .env
from app.config import (
    PROJECT_ID,
    DATASET_ID,
    CA_API_ENDPOINT,
    DATA_AGENT_ID,
    USER_NAME_SCREEN,
)

# Conversational Analytics and BigQuery integration service functions
from app.services.ca_service import (
    send_cmo_prompt,
    get_recent_logs,
    update_data_agent_sources,
    update_multi_agent_sources,
    get_active_mapped_tables,
    create_conversation,
    get_or_create_session_conversation,
    reset_session_conversation,
)

# Measured Black Week KPI figures (never hardcoded in the page)
from app.services.kpi_service import get_kpi_summary

# Semantic search & prompt evaluation services
from app.services.discovery_service import KnowledgeDiscoveryService
from app.services.prompt_evaluator import PromptEvaluatorService

# Initialize singleton service handlers
discovery_service = KnowledgeDiscoveryService()
prompt_evaluator = PromptEvaluatorService()

# Default active prompt used for Knowledge Catalog semantic discovery and
# BigQuery Data Agent preparation.
#
# 2026-09-13: this was a private copy of the old prompt,
#   "Prepare sales, marketing, ads, inventory, all connected business domains data"
# which grounds 50 tables - over the Conversational Analytics metadata cliff -
# and scores 0 of 11 on the main story. It is now the shared prompt, so
# /api/health reports what the demo actually uses.
from app.services.discovery_core import DISCOVERY_PROMPT

_current_active_prompt = DISCOVERY_PROMPT

# Initialize FastAPI application instance
app = FastAPI(
    title="LumièreShop Conversational Analytics Backend API",
    description="Enterprise API gateway connecting executive frontend with Google Cloud Knowledge Catalog & Gemini Data Agents.",
    version="1.0.0",
)

# Configure Cross-Origin Resource Sharing (CORS) for flexible local & cloud deployments
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static frontend assets (HTML, CSS, client-side JS)
static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ==============================================================================
# Pydantic Request & Response Data Models
# ==============================================================================

class ChatRequest(BaseModel):
    """Payload for conversational analytics inquiries sent to the Gemini Data Agent."""
    prompt: str = Field(..., description="Natural language analytical inquiry from the business user.")
    session_id: Optional[str] = Field(None, description="Unique client session identifier.")
    conversation_id: Optional[str] = Field(None, description="Optional Google Cloud server-managed conversation resource name.")
    user_name: Optional[str] = Field(None, description="User identifier or display name submitting the prompt.")
    menu_item: Optional[str] = Field("chat", description="Interface menu item context ('chat').")
    agent_no: Optional[str] = Field(None, description="Agent identifier (NULL for single agent).")
    thinking_mode: Optional[str] = Field(None, description="Thinking mode for the BigQuery Data Agent ('FAST' or 'THINKING').")


class MultiAgentChatRequest(BaseModel):
    """Payload for targeted queries in the 3-Agent Parallel Comparative Workspace."""
    agent_name: str = Field(..., description="Name of target agent (e.g., 'Agent A', 'Agent B', 'Agent C').")
    prompt: str = Field(..., description="Natural language prompt dispatched to the specific agent.")
    session_id: Optional[str] = Field(None, description="Unique client session identifier.")
    conversation_id: Optional[str] = Field(None, description="Google Cloud conversation resource name.")
    tables: Optional[List[str]] = Field(None, description="List of BigQuery tables mapped to this agent.")
    user_name: Optional[str] = Field(None, description="User identifier or display name submitting the prompt.")
    menu_item: Optional[str] = Field("compare chats", description="Interface menu item context ('compare chats').")
    agent_no: Optional[str] = Field(None, description="Agent identifier ('agentA', 'agentB', 'agentC').")
    thinking_mode: Optional[str] = Field(None, description="Thinking mode for the BigQuery Data Agent ('FAST' or 'THINKING').")


class MultiAgentSetupItem(BaseModel):
    """Configuration mapping for a single agent in multi-agent setup."""
    name: str = Field(..., description="Agent display name (e.g. 'gda-lumiere-a').")
    tables: List[str] = Field(..., description="Array of BigQuery table names assigned to this agent.")


class MultiAgentsPrepareRequest(BaseModel):
    """Payload to batch-configure all 3 parallel Data Agents in GCP with discovered table sets."""
    agents: Optional[List[MultiAgentSetupItem]] = Field(None, description="Optional list of agent definitions and their table bindings.")
    prompt: Optional[str] = Field(None, description="Single Knowledge Catalog prompt to evaluate and map to all 3 agents.")


class ResetConversationRequest(BaseModel):
    """Payload requesting initialization of a fresh conversation thread."""
    session_id: Optional[str] = Field(None, description="Client session ID for which to reset the conversation.")


class PrepareDataRequest(BaseModel):
    """Payload requesting Knowledge Catalog discovery and Data Agent pre-configuration."""
    prompt: Optional[str] = Field(None, description="Diagnostic prompt to evaluate in Knowledge Catalog.")
    session_id: Optional[str] = Field(None, description="Client session ID to pre-warm conversation thread.")


class EvaluatePromptsRequest(BaseModel):
    """Payload requesting parallel Knowledge Catalog search and LLM scoring for candidate prompts."""
    prompts: List[str] = Field(..., description="List of 2 to 3 candidate prompt strings to compare.")


class SetActivePromptRequest(BaseModel):
    """Payload to update the default active investigation prompt."""
    prompt: str = Field(..., description="The new active natural language prompt string.")


# ==============================================================================
# API Route Handlers
# ==============================================================================

@app.get("/")
async def read_root():
    """Serves the primary Material Design 3 single-page web interface."""
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "LumièreShop Backend API is active."}


@app.get("/api/health")
async def health_check():
    """
    Health check and diagnostic endpoint returning active cloud configuration,
    BigQuery dataset references, and active table mapping count.
    """
    return {
        "status": "ok",
        "project_id": PROJECT_ID,
        "dataset_id": DATASET_ID,
        "ca_api_endpoint": CA_API_ENDPOINT,
        "data_agent_id": DATA_AGENT_ID,
        "active_tables_count": len(get_active_mapped_tables()),
        "active_prompt": _current_active_prompt,
        "user_name_screen": USER_NAME_SCREEN,
    }


@app.get("/api/kpi/summary")
async def kpi_summary_endpoint(refresh: bool = False):
    """
    Headline Black Week figures, measured live from BigQuery.

    The web interface renders every euro amount and percentage from this
    response. Nothing is typed into the page, so the English and Dutch views
    cannot disagree and the exported summary report cannot go stale.

    Measured once per process and cached; pass ?refresh=true to re-measure.
    """
    try:
        return await anyio.to_thread.run_sync(lambda: get_kpi_summary(refresh))
    except Exception as exc:  # pragma: no cover - surfaced to the UI
        raise HTTPException(
            status_code=503,
            detail=f"Unable to measure KPI summary from BigQuery: {exc}",
        )


@app.post("/api/prepare-data")
async def prepare_data_endpoint(request: PrepareDataRequest):
    """
    Data Preparation & Dynamic Grounding Pipeline:
    1. Sends the CMO's prompt to Google Cloud Knowledge Catalog (semanticSearch=True),
       once for BigQuery tables and once for Business Glossary terms.
    2. Re-configures the BigQuery Data Agent (DATA_AGENT_ID) with the discovered
       tables AND the discovered glossary terms.
    3. Pre-warms the server-managed conversation resource for the active session.

    Both searches use the SAME prompt string, and the same shared module the
    setup script uses, so the live demo and the initialised environment cannot
    disagree about what the catalog found.
    """
    global _current_active_prompt
    user_prompt = request.prompt or _current_active_prompt
    _current_active_prompt = user_prompt

    try:
        # Pre-warm conversation resource in background for the session if provided
        if request.session_id:
            await anyio.to_thread.run_sync(
                get_or_create_session_conversation, request.session_id
            )

        # Step 1: Knowledge Catalog discovery - tables and glossary terms
        discovery_result = await anyio.to_thread.run_sync(
            discovery_service.discover_knowledge_context, user_prompt
        )
        discovered_tables = discovery_result.get("tables", [])
        glossary_terms = discovery_result.get("glossary_terms", [])

        # Step 2: Ground the Data Agent on both. Passing the terms here is what
        # makes this a live catalog demonstration rather than a replay of
        # whatever `scripts/06_update_data_agent.py` happened to leave behind.
        agent_result = await anyio.to_thread.run_sync(
            update_data_agent_sources, discovered_tables, glossary_terms
        )

        return {
            "status": "success",
            "prompt": discovery_result.get("prompt", user_prompt),
            "data_agent_id": DATA_AGENT_ID,
            "table_count": discovery_result.get("table_count", len(discovered_tables)),
            "term_count": discovery_result.get("term_count", 0),
            "entry_link_count": discovery_result.get("entry_link_count", 0),
            "tables": discovered_tables,
            "terms": discovery_result.get("terms", []),
            "entry_links": discovery_result.get("entry_links", []),
            "agent_configured": True,
            "message": (
                f"Discovered {discovery_result.get('table_count', len(discovered_tables))} tables "
                f"and {discovery_result.get('term_count', 0)} business glossary terms "
                f"via Knowledge Catalog."
            ),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/evaluate-prompts")
async def evaluate_prompts_endpoint(request: EvaluatePromptsRequest):
    """
    Prompt Comparison Studio:
    Executes parallel Knowledge Catalog search for 2-3 candidate prompts and evaluates
    them using Google Cloud Gemini Enterprise Agent Platform (Gemini 3.7 Flash).
    """
    if len(request.prompts) < 2 or len(request.prompts) > 3:
        raise HTTPException(status_code=400, detail="Please provide 2 or 3 candidate prompts for comparison.")

    try:
        eval_result = await prompt_evaluator.evaluate_prompts(request.prompts)
        return eval_result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/set-active-prompt")
async def set_active_prompt_endpoint(request: SetActivePromptRequest):
    """Updates the active default prompt used for data preparation and investigation."""
    global _current_active_prompt
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")
    _current_active_prompt = request.prompt.strip()
    return {
        "status": "success",
        "active_prompt": _current_active_prompt,
        "message": "Active prompt successfully updated for CMO workspace.",
    }


@app.get("/api/data-agent/status")
async def data_agent_status():
    """Returns the readiness status and current mapped table list of the BigQuery Data Agent."""
    tables = get_active_mapped_tables()
    return {
        "data_agent_id": DATA_AGENT_ID,
        "is_ready": len(tables) > 0,
        "table_count": len(tables),
        "tables": tables,
    }


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    """
    Dispatches a natural language analytics query to the BigQuery Data Agent,
    unwraps reasoning thoughts, SQL queries, and Vega-Lite chart specs,
    and logs the trace into BigQuery asynchronously.
    """
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")
    try:
        res = await anyio.to_thread.run_sync(
            send_cmo_prompt,
            request.prompt.strip(),
            request.session_id,
            request.conversation_id,
            None,
            None,
            request.user_name,
            request.menu_item or "chat",
            request.agent_no,
            request.thinking_mode or "FAST",
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/multi-agents/prepare")
async def multi_agents_prepare_endpoint(request: MultiAgentsPrepareRequest):
    """
    Configures the three comparison Data Agents in parallel.

    One prompt drives two Knowledge Catalog searches (tables, then glossary
    terms). The SAME table names are mapped onto all three agents, each in its
    own dataset - Agent A in ecommerce_dw, Agent B in ecommerce_dw_2nd, Agent C
    in ecommerce_dw_3rd - so the three tiers differ ONLY in metadata quality,
    never in the underlying rows.

    Only Agent A receives the glossary terms. That is the experiment: the other
    two datasets have no governed glossary, so there is genuinely nothing to
    map. Their terms are actively cleared on every call so a stale projection
    from an earlier run can never quietly flatter them.
    """
    try:
        discovered_tables = []
        term_count = 0
        entry_link_count = 0
        terms = []
        glossary_terms = []
        entry_links = []

        if request.prompt:
            discovery_result = await anyio.to_thread.run_sync(
                discovery_service.discover_knowledge_context, request.prompt.strip()
            )
            discovered_tables = discovery_result.get("tables", [])
            term_count = discovery_result.get("term_count", 0)
            entry_link_count = discovery_result.get("entry_link_count", 0)
            terms = discovery_result.get("terms", [])
            glossary_terms = discovery_result.get("glossary_terms", [])
            entry_links = discovery_result.get("entry_links", [])

            agents_to_update = [
                MultiAgentSetupItem(name="Agent A", tables=discovered_tables),
                MultiAgentSetupItem(name="Agent B", tables=discovered_tables),
                MultiAgentSetupItem(name="Agent C", tables=discovered_tables),
            ]
        elif request.agents:
            agents_to_update = request.agents
            if agents_to_update:
                discovered_tables = agents_to_update[0].tables
        else:
            raise HTTPException(status_code=400, detail="Either 'prompt' or 'agents' must be provided.")

        # Agent A is the catalog tier. Everyone else gets None, which clears
        # any glossary terms they are currently holding.
        async def _update_one(item: MultiAgentSetupItem):
            terms_for_agent = glossary_terms if item.name == "Agent A" else None
            await anyio.to_thread.run_sync(
                update_multi_agent_sources, item.name, item.tables, terms_for_agent
            )

        async with anyio.create_task_group() as tg:
            for item in agents_to_update:
                tg.start_soon(_update_one, item)

        return {
            "status": "success",
            "prompt": request.prompt,
            "table_count": len(discovered_tables),
            "term_count": term_count,
            "entry_link_count": entry_link_count,
            "tables": discovered_tables,
            "terms": terms,
            "entry_links": entry_links,
            "message": (
                f"Mapped {len(discovered_tables)} tables across 3 isolated agents; "
                f"{term_count} Knowledge Catalog glossary terms attached to Agent A only."
            ),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/multi-chat")
async def multi_chat_endpoint(request: MultiAgentChatRequest):
    """
    Dispatches an analytical inquiry to a specific agent in the 3-Agent Parallel Cockpit,
    recording telemetry tagged with the specific agent identifier.
    """
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")
    try:
        # Determine agent_no: either passed directly or deduced from agent_name
        agent_no = request.agent_no
        if not agent_no and request.agent_name:
            if "A" in request.agent_name:
                agent_no = "agentA"
            elif "B" in request.agent_name:
                agent_no = "agentB"
            elif "C" in request.agent_name:
                agent_no = "agentC"

        res = await anyio.to_thread.run_sync(
            send_cmo_prompt,
            request.prompt.strip(),
            request.session_id,
            request.conversation_id,
            request.agent_name,
            request.tables,
            request.user_name,
            request.menu_item or "compare chats",
            agent_no,
            request.thinking_mode or "FAST",
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/conversation/reset")
async def reset_conversation_endpoint(request: ResetConversationRequest):
    """
    Initializes a fresh server-managed Conversation resource on Google Cloud
    for the specified user session, clearing previous multi-turn state.
    """
    try:
        new_conv = await anyio.to_thread.run_sync(reset_session_conversation, request.session_id)
        return {
            "status": "success",
            "session_id": request.session_id,
            "conversation_id": new_conv,
            "message": "Fresh server-managed conversation initialized successfully on Google Cloud."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/logs")
async def logs_endpoint(limit: int = 20, session_id: str = None):
    """Retrieves recent BigQuery audit logs from `ecommerce_dw.agent_interaction_logs`."""
    try:
        return await anyio.to_thread.run_sync(get_recent_logs, limit, session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Direct execution entrypoint for local development server
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
