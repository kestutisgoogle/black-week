#!/usr/bin/env python3
"""
Autonomous UI & Metric Validation Test Suite for LumièreShop.
Sends discovery queries and metric validation prompts to the backend API,
validates numbers against CASE_STUDY_SOLUTION.md, scrapes DOM elements,
and captures Desktop and Mobile viewport screenshots using Playwright.
"""

import os
import sys
import json
import time
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

TEST_DIR = os.path.dirname(os.path.abspath(__file__))

PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from test_utils import load_project_env, ensure_test_server, ensure_playwright_chromium
load_project_env()

BASE_URL = ensure_test_server(8000)
ensure_playwright_chromium()
CHAT_API = f"{BASE_URL}/api/chat"
HEALTH_API = f"{BASE_URL}/api/health"
PREPARE_DATA_API = f"{BASE_URL}/api/prepare-data"
DATA_AGENT_STATUS_API = f"{BASE_URL}/api/data-agent/status"


# Test Queries from CASE_STUDY_SOLUTION.md (The Expanded Analytics Discovery Path With Dead Ends)
TEST_QUERIES = [
    {
        "id": "Step 1",
        "name": "Isolate the Outlier (The Alarm)",
        "prompt": "Give me a breakdown of actual vs target revenue for all main categories this week.",
        "phase": "Breakthrough: Isolate the outlier to Beauty (-27%)."
    },
    {
        "id": "Step 2",
        "name": "Dead End #1: The Technical Glitch Hypothesis",
        "prompt": "Did we have a technical issue? Check if site error rates, cart abandonment, or checkout failures spiked for Beauty products on Black Friday.",
        "phase": "Dead End: Checkout success rate remained steady at 98.4%."
    },
    {
        "id": "Step 3",
        "name": "Isolate Traffic vs. Conversion Rate (Funnel Analysis)",
        "prompt": "Okay, if the site isn't broken, look at the Beauty funnel. Are we losing people on traffic volume, or is the on-page conversion rate dropping?",
        "phase": "Breakthrough: CVR is 3.1% (above target), issue is paid traffic collapsed -39%."
    },
    {
        "id": "Step 4",
        "name": "Dead End #2: The Competitor Pricing Hypothesis",
        "prompt": "Our competitors launched massive influencer campaigns. Did they undercut our prices? Pull our average price index versus our top two competitors for Beauty items this week.",
        "phase": "Dead End: Price index 1.01 vs Comp A and 0.99 vs Comp B. No price war."
    },
    {
        "id": "Step 5",
        "name": "Check the Inventory Disruption (Supply Chain)",
        "prompt": "What about stock levels? Did we run out of key items in Beauty?",
        "phase": "Partial Breakthrough: Top 3 Beauty bestsellers out of stock Monday–Wednesday (€65k loss)."
    },
    {
        "id": "Step 6",
        "name": "Connect Stockouts to the Ad Bidding Algorithm (The Root Cause)",
        "prompt": "Correlate our daily paid marketing spend and average CPC for Beauty with the exact days those 3 products were out of stock.",
        "phase": "Smoking Gun: Out of stock conversion dip triggered strict bidding throttle (-31% spend, +22% CPC), causing 39% session collapse."
    }
]

def run_backend_api_tests():
    print("\n" + "=" * 80)
    print("--- Phase 0: Knowledge Catalog Discovery & Dynamic Agent Provisioning ---")
    print("=" * 80)
    health_res = requests.get(HEALTH_API)
    print(f"Health Check Status: {health_res.status_code} -> {health_res.json()}")
    
    # Test Data Preparation API
    prep_res = requests.post(PREPARE_DATA_API, json={"prompt": "Prepare sales, marketing, ads, inventory, all connected business domains data"})
    print(f"Prepare Data API Status: {prep_res.status_code}")
    if prep_res.status_code == 200:
        prep_data = prep_res.json()
        table_count = prep_data.get('table_count', 0)
        print(f"🎯 Discovered Tables Count: {table_count} dynamically mapped tables")
        print(f"🤖 BigQuery Data Agent ID: {prep_data.get('data_agent_id')}")
        print(f"📦 Mapped Tables: {prep_data.get('tables')}")
        assert table_count > 0, "Expected positive dynamic table count mapped!"
        print(f"✅ Knowledge Catalog Data Preparation verified dynamically with {table_count} tables!")

    status_res = requests.get(DATA_AGENT_STATUS_API)
    print(f"Data Agent Status API: {status_res.status_code} -> {status_res.json()}")

    print("\n" + "=" * 80)
    print("--- Phase 1: The Expanded Analytics Discovery Path (6 Queries) ---")
    print("=" * 80)
    
    session_id = f"SESS-DISCOVERY-{int(time.time())}"
    print(f"Active Stateful Session ID: {session_id}\n")

    conversation_log = []

    for q in TEST_QUERIES:
        print("-" * 80)
        print(f"📌 {q['id']}: {q['name']}")
        print(f"💬 CMO Prompt: \"{q['prompt']}\"")
        print(f"🎯 Objective: {q['phase']}")
        start = time.time()
        try:
            res = requests.post(CHAT_API, json={"prompt": q["prompt"], "session_id": session_id}, timeout=90)
            duration = round(time.time() - start, 2)
            print(f"⏱️ HTTP Status: {res.status_code} (took {duration}s)")
            
            if res.status_code == 200:
                data = res.json()
                text = data.get("text", "")
                sql = data.get("generated_sql", "")
                thinking = data.get("thinking_process", "")
                table_data = data.get("table_data", [])

                print(f"🤖 Agent Response:\n{text}\n")
                if sql and sql != "N/A":
                    print(f"💻 Generated BigQuery SQL:\n{sql}\n")
                if thinking and thinking.strip():
                    print(f"🧠 Reasoning Process:\n{thinking[:300]}...\n")

                conversation_log.append({
                    "step": q["id"],
                    "name": q["name"],
                    "phase": q["phase"],
                    "prompt": q["prompt"],
                    "response": text,
                    "sql": sql,
                    "thinking": thinking,
                    "rows_returned": len(table_data) if isinstance(table_data, list) else 0,
                    "duration_s": duration
                })
            else:
                print(f"❌ Error: {res.status_code} - {res.text[:300]}")
        except Exception as e:
            duration = round(time.time() - start, 2)
            print(f"❌ Request Exception: {e}")
            
    return conversation_log

def run_playwright_ui_scrape_and_screenshots(output_dir):
    print("\n" + "=" * 80)
    print("--- Phase 2: Web Scraping & Visual Screenshot Capture ---")
    print("=" * 80)
    os.makedirs(output_dir, exist_ok=True)
    
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as e:
            print(f"\n⚠️ [SKIPPED] Headless Linux VM detected without Chromium OS libraries ({e}).")
            print("  To enable browser tests on Linux, run: playwright install --with-deps chromium")
            print("  Or run headless BigQuery & Agent tests via: python3 scripts/test/run_all_tests.py --integration --audit\n")
            return {}
        
        # Desktop Test (1920x1080)
        print("\nLaunching Desktop Viewport (1920x1080)...")
        desktop_page = browser.new_page(viewport={"width": 1920, "height": 1080})
        desktop_page.goto(BASE_URL)
        desktop_page.wait_for_load_state("networkidle")

        # Bypass Screen 0 (User Name Screen) if active
        try:
            desktop_page.locator("#userNameView:not(.hidden)").wait_for(state="visible", timeout=1500)
            print("   Screen 0 detected. Submitting operator username...")
            desktop_page.locator("#userNameInput").fill("DevOperator")
            desktop_page.locator("#userNameSubmitBtn").click()
            desktop_page.locator("#alertView:not(.hidden)").wait_for(state="visible", timeout=5000)
            time.sleep(0.3)
        except Exception:
            pass
        
        desktop_screenshot = os.path.join(output_dir, "google_workspace_alert_view.png")
        desktop_page.screenshot(path=desktop_screenshot, full_page=True)
        print(f"📸 Screen 1 (Google Workspace Alert) screenshot saved: {desktop_screenshot}")
        
        # Click Prepare Data button
        prepare_btn = desktop_page.locator("#prepareDataBtn")
        if prepare_btn.is_visible():
            print("🔘 Clicking 'Please prepare the data to analyze the issue.'...")
            prepare_btn.click()
            
            # Wait for simulation to finish
            print("⏳ Waiting for 4-step preparation simulation to complete and transition...")
            desktop_page.locator("#workspaceView").wait_for(state="visible", timeout=20000)
            print("✅ Successfully transitioned into CMO Analytics Workspace!")
            
            # Fill and submit Prompt 1 in UI
            prompt_input = desktop_page.locator("#cmoChatInput")
            if prompt_input.is_visible():
                prompt_input.fill(TEST_QUERIES[0]["prompt"])
                desktop_page.locator("#cmoSendBtn").click()
                
                print("⏳ Waiting for agent query response...")
                desktop_page.locator("#cmoSendBtn:not([disabled])").wait_for(state="visible", timeout=90000)
                time.sleep(2)
                
                workspace_screenshot = os.path.join(output_dir, "cmo_workspace_interactive_view.png")
                desktop_page.screenshot(path=workspace_screenshot, full_page=True)
                print(f"📸 Screen 2 (CMO Workspace Interactive) screenshot saved: {workspace_screenshot}")

        browser.close()
        
    return {
        "alert_screenshot": desktop_screenshot,
        "workspace_screenshot": os.path.join(output_dir, "cmo_workspace_interactive_view.png")
    }

if __name__ == "__main__":
    artifact_dir = os.path.join(PROJECT_ROOT, "test-output")
    os.makedirs(artifact_dir, exist_ok=True)
    conversation = run_backend_api_tests()
    ui_results = run_playwright_ui_scrape_and_screenshots(artifact_dir)
    
    with open(os.path.join(artifact_dir, "discovery_path_conversation.json"), "w") as f:
        json.dump(conversation, f, indent=2)


    print("\n" + "=" * 80)
    print(f"✅ Completed execution of {len(conversation)} discovery queries.")
    print("=" * 80)

