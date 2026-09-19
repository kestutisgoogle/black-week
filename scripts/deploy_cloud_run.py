#!/usr/bin/env python3
"""
Turnkey Google Cloud Run Deployer for LumièreShop
=================================================
Automates all 4 deployment steps to Google Cloud Run:
1. Validates and creates Docker repository in Artifact Registry (`lumiere-shop-repo`).
2. Configures IAM policy bindings on the Cloud Run compute service account.
3. Builds and pushes the container image via Google Cloud Build.
4. Deploys the service to Google Cloud Run with environment variables from `.env`.

Usage:
------
  python3 scripts/deploy_cloud_run.py
"""

import os
import sys
import subprocess
import time
from typing import Dict, Any


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

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
DATASET_ID = os.environ.get("BQ_DATASET_ID", "ecommerce_dw")
DATASET_2ND_ID = os.environ.get("BQ_DATASET_2ND_ID", f"{DATASET_ID}_2nd")
DATASET_3RD_ID = os.environ.get("BQ_DATASET_3RD_ID", f"{DATASET_ID}_3rd")
REGION = os.environ.get("BQ_LOCATION", "europe-west4").lower()
DATA_AGENT_ID = os.environ.get("DATA_AGENT_ID") or os.environ.get("CA_DATA_AGENT_ID", "gda-blackweek-primary")
DATA_AGENT_A_ID = os.environ.get("DATA_AGENT_A_ID", "gda-blackweek-a")
DATA_AGENT_B_ID = os.environ.get("DATA_AGENT_B_ID", "gda-blackweek-b")
DATA_AGENT_C_ID = os.environ.get("DATA_AGENT_C_ID", "gda-blackweek-c")
USER_NAME_SCREEN = os.environ.get("USER_NAME_SCREEN", "on")


def get_gcloud_path() -> str:
    for cmd in ["/google/data/ro/teams/cloud-sdk/gcloud", "gcloud"]:
        try:
            res = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                return cmd
        except Exception:
            continue
    return "gcloud"


GCLOUD = get_gcloud_path()


def run_cmd(args: list, desc: str, check: bool = True) -> subprocess.CompletedProcess:
    print(f"\n▶️  {desc}...")
    start = time.time()
    res = subprocess.run(args, cwd=PROJECT_ROOT, capture_output=True, text=True)
    duration = round(time.time() - start, 2)
    if res.returncode == 0:
        print(f"  ✅ Completed in {duration}s")
        if res.stdout.strip():
            lines = res.stdout.strip().splitlines()
            for l in lines[-4:]:
                print(f"     {l}")
    else:
        print(f"  ❌ Command failed with exit code {res.returncode} in {duration}s")
        if res.stdout.strip():
            print("  --- Standard Output ---")
            for l in res.stdout.strip().splitlines():
                print(f"     {l}")
        if res.stderr.strip():
            print("  --- Error Output ---")
            for l in res.stderr.strip().splitlines():
                print(f"     {l}")
        if check:
            print(f"\n❌ Deployment halted due to error in: {desc}", file=sys.stderr)
            sys.exit(1)
    return res


def get_project_number(project_id: str) -> str:
    # 1. Check .env
    env_num = os.environ.get("GCP_PROJECT_NUMBER")
    if env_num and env_num.strip().isdigit():
        return env_num.strip()

    # 2. Try REST API with access token
    try:
        from backend.app.services.ca_service import get_access_token
        token = get_access_token()
        if token:
            url = f"https://cloudresourcemanager.googleapis.com/v1/projects/{project_id}"
            headers = {"Authorization": f"Bearer {token}"}
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                p_num = str(res.json().get("projectNumber", ""))
                if p_num:
                    return p_num
    except Exception:
        pass

    # 3. Fallback to gcloud CLI
    try:
        res = subprocess.run(
            [GCLOUD, "projects", "describe", project_id, "--format=value(projectNumber)", "--quiet"],
            capture_output=True,
            text=True,
            timeout=15
        )
        if res.returncode == 0 and res.stdout.strip() and res.stdout.strip().isdigit():
            return res.stdout.strip()
    except Exception:
        pass

    return ""


def main():
    print("=" * 80)
    print("🚀 LUMIÈRESHOP CLOUD RUN AUTOMATED DEPLOYER")
    print(f"Target Project ID : {PROJECT_ID}")
    print(f"Target Region     : {REGION}")
    print(f"BigQuery Primary  : {DATASET_ID}")
    print(f"BigQuery 2nd (B)  : {DATASET_2ND_ID}")
    print(f"BigQuery 3rd (C)  : {DATASET_3RD_ID}")
    print(f"Primary Agent ID  : {DATA_AGENT_ID}")
    print(f"Compare Agent A   : {DATA_AGENT_A_ID}")
    print(f"Compare Agent B   : {DATA_AGENT_B_ID}")
    print(f"Compare Agent C   : {DATA_AGENT_C_ID}")
    print("=" * 80)

    if not PROJECT_ID:
        # Fallback to active gcloud config
        res = subprocess.run([GCLOUD, "config", "get-value", "project"], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip() and res.stdout.strip() != "(unset)":
            project_id = res.stdout.strip()
        else:
            print("ERROR: GCP_PROJECT_ID is not configured in .env file or gcloud config.", file=sys.stderr)
            sys.exit(1)
    else:
        project_id = PROJECT_ID

    project_number = get_project_number(project_id)
    if not project_number:
        print(f"ERROR: Could not retrieve project number for project '{project_id}'.", file=sys.stderr)
        sys.exit(1)

    print(f"Resolved Project Number: {project_number}")

    # 1. Artifact Registry repository
    repo_check = subprocess.run(
        [GCLOUD, "artifacts", "repositories", "describe", "lumiere-shop-repo", f"--location={REGION}", f"--project={project_id}"],
        capture_output=True,
        text=True
    )
    if repo_check.returncode == 0:
        print("\n▶️  1. Artifact Registry repository `lumiere-shop-repo` already exists.")
    else:
        create_res = subprocess.run(
            [
                GCLOUD, "artifacts", "repositories", "create", "lumiere-shop-repo",
                "--repository-format=docker",
                f"--location={REGION}",
                "--description=Docker repository for LumièreShop",
                f"--project={project_id}"
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True
        )
        if create_res.returncode == 0 or "already exists" in create_res.stderr.lower():
            print("\n▶️  1. Artifact Registry repository `lumiere-shop-repo` ready.")
        else:
            print(f"❌ Failed to create Artifact Registry repo: {create_res.stderr}", file=sys.stderr)
            sys.exit(1)

    # 2. IAM Policy Bindings
    print(f"\n▶️  2. Configuring IAM roles for Service Accounts ({project_number})...")
    compute_sa = f"serviceAccount:{project_number}-compute@developer.gserviceaccount.com"
    compute_roles = [
        "roles/geminidataanalytics.dataAgentUser",
        "roles/geminidataanalytics.dataAgentStatelessUser",
        "roles/geminidataanalytics.dataAgentCreator",
        "roles/geminidataanalytics.dataAgentOwner",
        "roles/geminidataanalytics.admin",
        "roles/bigquery.admin",
        "roles/bigquery.dataEditor",
        "roles/bigquery.jobUser",
        "roles/dataplex.viewer",
        "roles/dataplex.catalogAdmin",
        "roles/dataplex.aspectTypeOwner",
        "roles/dataplex.aspectTypeUser",
        "roles/dataplex.metadataWriter",
        "roles/datacatalog.admin",
        "roles/datacatalog.viewer",
        "roles/aiplatform.user",
        "roles/cloudaicompanion.user",
        "roles/cloudaicompanion.admin",
        "roles/serviceusage.serviceUsageConsumer",
        "roles/artifactregistry.writer",
        "roles/artifactregistry.reader",
        "roles/storage.admin",
        "roles/logging.logWriter"
    ]
    for role in compute_roles:
        subprocess.run(
            [GCLOUD, "projects", "add-iam-policy-binding", project_id, f"--member={compute_sa}", f"--role={role}", "--quiet"],
            capture_output=True,
            text=True
        )

    cb_sa = f"serviceAccount:{project_number}@cloudbuild.gserviceaccount.com"
    cb_roles = [
        "roles/artifactregistry.writer",
        "roles/logging.logWriter",
        "roles/storage.admin"
    ]
    for role in cb_roles:
        subprocess.run(
            [GCLOUD, "projects", "add-iam-policy-binding", project_id, f"--member={cb_sa}", f"--role={role}", "--quiet"],
            capture_output=True,
            text=True
        )
    print("  ✅ Compute and Cloud Build Service Account IAM roles configured.")

    # 3. Build container with Cloud Build
    image_tag = f"{REGION}-docker.pkg.dev/{project_id}/lumiere-shop-repo/lumiere-app:latest"
    run_cmd(
        [
            GCLOUD, "builds", "submit",
            f"--tag={image_tag}",
            f"--project={project_id}"
        ],
        desc="3. Building and pushing container image via Google Cloud Build"
    )

    # 4. Deploy to Cloud Run
    env_vars = (
        f"GCP_PROJECT_ID={project_id},"
        f"BQ_DATASET_ID={DATASET_ID},"
        f"BQ_DATASET_2ND_ID={DATASET_2ND_ID},"
        f"BQ_DATASET_3RD_ID={DATASET_3RD_ID},"
        f"BQ_LOCATION={REGION},"
        f"CA_API_HOST=https://geminidataanalytics.googleapis.com,"
        f"CA_API_ENDPOINT=https://geminidataanalytics.googleapis.com/v1beta/projects/{project_id}/locations/global:chat,"
        f"DATA_AGENT_ID={DATA_AGENT_ID},"
        f"DATA_AGENT_A_ID={DATA_AGENT_A_ID},"
        f"DATA_AGENT_B_ID={DATA_AGENT_B_ID},"
        f"DATA_AGENT_C_ID={DATA_AGENT_C_ID},"
        f"USER_NAME_SCREEN={USER_NAME_SCREEN}"
    )

    deploy_res = run_cmd(
        [
            GCLOUD, "run", "deploy", "lumiere-shop-app",
            f"--image={image_tag}",
            f"--region={REGION}",
            f"--project={project_id}",
            "--platform=managed",
            "--allow-unauthenticated",
            "--no-invoker-iam-check",
            f"--set-env-vars={env_vars}"
        ],
        desc="4. Deploying service to Google Cloud Run"
    )

    # Retrieve Service URL
    url_res = subprocess.run(
        [GCLOUD, "run", "services", "describe", "lumiere-shop-app", f"--region={REGION}", f"--project={project_id}", "--format=value(status.url)"],
        capture_output=True,
        text=True
    )
    service_url = url_res.stdout.strip() if url_res.returncode == 0 else ""

    print("\n" + "=" * 80)
    print("🎉 CLOUD RUN DEPLOYMENT SUCCESSFUL!")
    if service_url:
        print(f"🔗 Live Production URL : {service_url}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
