"""
LumièreShop Configuration Loader
================================
Dynamically manages environment variables and Google Cloud configuration parameters
for the LumièreShop Conversational Analytics platform.

Configuration Precedence:
  1. System environment variables (e.g. injected by Cloud Run or Docker runtime).
  2. Local `.env` file key-value pairs (loaded automatically in development).
  3. Safe fallback defaults for local sandbox development.
"""

import os


def load_dotenv():
    """
    Locates and parses the project-root `.env` file into os.environ.
    Uses `os.environ.setdefault` to ensure that active environment variables
    (e.g., from container runtimes or CI/CD pipelines) are never overwritten.
    """
    env_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        ".env",
    )
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip("'\""))


# Execute dotenv loading on initial module import
load_dotenv()

# ==============================================================================
# Google Cloud & BigQuery Infrastructure Settings
# ==============================================================================

# Target GCP Project ID hosting BigQuery, Knowledge Catalog, and Cloud Run
PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")

# Target BigQuery Dataset holding all 140 operational and extended domain tables
DATASET_ID = os.environ.get("BQ_DATASET_ID", "ecommerce_dw")

# 2nd BigQuery Dataset for Agent B (Identical tables/descriptions, 0 Knowledge Catalog glossary/EntryLinks)
DATASET_2ND_ID = os.environ.get("BQ_DATASET_2ND_ID", f"{DATASET_ID}_2nd")

# 3rd BigQuery Dataset for Agent C (Identical tables, 0 descriptions, 0 Knowledge Catalog glossary/EntryLinks)
DATASET_3RD_ID = os.environ.get("BQ_DATASET_3RD_ID", f"{DATASET_ID}_3rd")

# Mapping of multi-agent identifiers to their respective isolated datasets
DATASET_MAPPING = {
    "Agent A": DATASET_ID,
    "Agent B": DATASET_2ND_ID,
    "Agent C": DATASET_3RD_ID,
}

# Regional BigQuery location for dataset storage and SQL job execution
LOCATION = os.environ.get("BQ_LOCATION", "europe-west4")

# User email identity for audit logging and permissions tracking
USER_IDENTITY = os.environ.get("GCP_USER_IDENTITY", "user@example.com")

# ==============================================================================
# Gemini Enterprise Agent Platform (Conversational Analytics API) Settings
# ==============================================================================

# Base host for the Google Cloud Gemini Data Analytics REST API
CA_API_HOST = os.environ.get("CA_API_HOST", "https://geminidataanalytics.googleapis.com")

# Official v1beta REST Chat endpoint for stateful data agent conversations
CA_API_ENDPOINT = os.environ.get(
    "CA_API_ENDPOINT",
    f"https://geminidataanalytics.googleapis.com/v1beta/projects/{PROJECT_ID}/locations/global:chat",
)

# Active BigQuery Data Agent resource identifiers configured in Google Cloud
DATA_AGENT_ID = os.environ.get("DATA_AGENT_ID", "gda-blackweek-primary")
DATA_AGENT_A_ID = os.environ.get("DATA_AGENT_A_ID", "gda-blackweek-a")
DATA_AGENT_B_ID = os.environ.get("DATA_AGENT_B_ID", "gda-blackweek-b")
DATA_AGENT_C_ID = os.environ.get("DATA_AGENT_C_ID", "gda-blackweek-c")

# Fully-qualified resource names for the primary and multi-agent cockpit
DATA_AGENT_NAME = f"projects/{PROJECT_ID}/locations/global/dataAgents/{DATA_AGENT_ID}"
MULTI_DATA_AGENTS = {
    "Agent A": f"projects/{PROJECT_ID}/locations/global/dataAgents/{DATA_AGENT_A_ID}",
    "Agent B": f"projects/{PROJECT_ID}/locations/global/dataAgents/{DATA_AGENT_B_ID}",
    "Agent C": f"projects/{PROJECT_ID}/locations/global/dataAgents/{DATA_AGENT_C_ID}",
}

# ==============================================================================
# UI Screen Flow Configuration Settings
# ==============================================================================

# Controls whether the initial User Name entry screen is shown ("on" vs "off")
USER_NAME_SCREEN = os.environ.get("USER_NAME_SCREEN", "off").strip().lower() in ("on", "true", "1", "yes")

