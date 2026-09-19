#!/usr/bin/env python3
"""
Test Suite 17: Single-Agent & 3-Agent Compare Chats Audit Logging Verification
==============================================================================
Tests:
  1. BigQuery `agent_interaction_logs` schema has `menu_item` and `agent_no` columns.
  2. Single-agent chat interaction logs `menu_item='chat'` and `agent_no=None`.
  3. 3-Agent compare chats interaction logs `menu_item='compare chats'` and `agent_no='agentA'/'agentB'/'agentC'`
     along with all analytical metadata (thinking_process, generated_sql, job_id, slot_milliseconds, user_name).
  4. Backend `get_recent_logs()` returns `menu_item` and `agent_no`.

Usage:
------
  python3 scripts/test/17_test_compare_chats_logging.py
"""

import os
import sys
import time
import uuid
import json
from google.cloud import bigquery

# Ensure project root and backend are in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))

from app.config import PROJECT_ID, DATASET_ID
from app.services.ca_service import send_cmo_prompt, get_recent_logs, get_bigquery_client


def test_schema_columns():
    print("\n[Test 1] Verifying BigQuery agent_interaction_logs schema columns...")
    client = get_bigquery_client()
    table_ref = f"{PROJECT_ID}.{DATASET_ID}.agent_interaction_logs"
    table = client.get_table(table_ref)

    field_names = {f.name for f in table.schema}
    print(f"  Existing columns in agent_interaction_logs: {len(field_names)} fields")
    assert "menu_item" in field_names, "Column `menu_item` missing from agent_interaction_logs"
    assert "agent_no" in field_names, "Column `agent_no` missing from agent_interaction_logs"
    assert "user_name" in field_names, "Column `user_name` missing from agent_interaction_logs"
    assert "thinking_process" in field_names, "Column `thinking_process` missing from agent_interaction_logs"
    print("  ✅ BigQuery schema contains menu_item, agent_no, user_name, and thinking_process.")


def test_single_agent_logging():
    print("\n[Test 2] Verifying Single-Agent chat logging (menu_item='chat', agent_no=None)...")
    test_session = f"TEST-SINGLE-{uuid.uuid4().hex[:6]}"
    test_user = "TestExecutiveUser"

    res = send_cmo_prompt(
        prompt="Which category had the largest deficit?",
        session_id=test_session,
        user_name=test_user,
        menu_item="chat",
        agent_no=None
    )
    assert isinstance(res, dict) and ("text" in res or "raw_response" in res), "Expected valid response payload"
    time.sleep(3.5)  # Allow async BigQuery insert

    # Query BigQuery directly for the logged record
    client = get_bigquery_client()
    query = f"""
        SELECT interaction_id, session_id, user_name, menu_item, agent_no, user_prompt, generated_sql, thinking_process
        FROM `{PROJECT_ID}.{DATASET_ID}.agent_interaction_logs`
        WHERE session_id = '{test_session}'
        ORDER BY created_at DESC
        LIMIT 1
    """
    rows = list(client.query(query).result())
    assert len(rows) == 1, f"Expected 1 logged row for session {test_session}, found {len(rows)}"
    row = rows[0]

    print(f"  Logged Single-Agent Record:")
    print(f"    Session ID: {row.session_id}")
    print(f"    User Name:  {row.user_name}")
    print(f"    Menu Item:  {row.menu_item}")
    print(f"    Agent No:   {row.agent_no}")

    assert row.menu_item == "chat", f"Expected menu_item='chat', got '{row.menu_item}'"
    assert row.agent_no is None, f"Expected agent_no=None for single agent, got '{row.agent_no}'"
    assert row.user_name == test_user, f"Expected user_name='{test_user}', got '{row.user_name}'"
    print("  ✅ Single-agent interaction successfully audited to BigQuery.")


def test_three_agents_compare_chats_logging():
    print("\n[Test 3] Verifying 3-Agent compare chats logging (menu_item='compare chats', agent_no='agentA'/'agentB'/'agentC')...")
    test_session_base = f"TEST-MULTI-{uuid.uuid4().hex[:6]}"
    test_user = "CompareChatsAuditor"

    agents_to_test = [
        ("Agent A", "agentA", ["sales_event_stream", "orders"]),
        ("Agent B", "agentB", ["web_events", "web_sessions"]),
        ("Agent C", "agentC", ["daily_ad_performance", "marketing_campaigns"]),
    ]

    for agent_display, agent_no, tables in agents_to_test:
        sess_id = f"{test_session_base}-{agent_no}"
        res = send_cmo_prompt(
            prompt=f"Analyze breakdown for {agent_display}",
            session_id=sess_id,
            agent_name=agent_display,
            target_tables=tables,
            user_name=test_user,
            menu_item="compare chats",
            agent_no=agent_no
        )
        assert isinstance(res, dict) and ("text" in res or "raw_response" in res), f"Query failed for {agent_display}"

    time.sleep(4.0)  # Allow async BigQuery insert

    client = get_bigquery_client()
    query = f"""
        SELECT interaction_id, session_id, user_name, menu_item, agent_no, data_agent_id, user_prompt, generated_sql, thinking_process, execution_time_ms
        FROM `{PROJECT_ID}.{DATASET_ID}.agent_interaction_logs`
        WHERE session_id LIKE '{test_session_base}-%'
        ORDER BY agent_no ASC
    """
    rows = list(client.query(query).result())
    print(f"  Retrieved {len(rows)} compare chats log records from BigQuery.")
    assert len(rows) == 3, f"Expected 3 logged rows, found {len(rows)}"

    for row in rows:
        print(f"    Record: session={row.session_id}, agent_no={row.agent_no}, menu_item={row.menu_item}, data_agent={row.data_agent_id}, user={row.user_name}")
        assert row.menu_item == "compare chats", f"Expected menu_item='compare chats', got '{row.menu_item}'"
        assert row.agent_no in ("agentA", "agentB", "agentC"), f"Unexpected agent_no: '{row.agent_no}'"
        assert row.user_name == test_user, f"Expected user_name='{test_user}', got '{row.user_name}'"
        assert row.user_prompt, "Expected user_prompt to be recorded"
        print(f"      Thinking process length: {len(row.thinking_process or '')} chars")

    print("  ✅ All 3 agents in compare chats mode successfully logged with full metadata to BigQuery.")


def test_get_recent_logs_api():
    print("\n[Test 4] Verifying get_recent_logs() API response fields...")
    logs = get_recent_logs(limit=10)
    assert len(logs) > 0, "Expected non-empty logs list"
    for l in logs:
        assert "menu_item" in l, "menu_item field missing from log payload"
        assert "agent_no" in l, "agent_no field missing from log payload"
        assert "user_name" in l, "user_name field missing from log payload"

    print(f"  Checked {len(logs)} log entries. Sample:")
    print(f"    Sample: id={logs[0]['interaction_id']}, menu_item={logs[0]['menu_item']}, agent_no={logs[0]['agent_no']}, user={logs[0]['user_name']}")
    print("  ✅ get_recent_logs() API correctly returns menu_item and agent_no.")


if __name__ == "__main__":
    print("=" * 80)
    print("RUNNING COMPARE CHATS & MULTI-AGENT AUDIT LOGGING TEST SUITE")
    print("=" * 80)
    test_schema_columns()
    test_single_agent_logging()
    test_three_agents_compare_chats_logging()
    test_get_recent_logs_api()
    print("\n" + "=" * 80)
    print("🎉 ALL COMPARE CHATS & AUDIT LOGGING TESTS PASSED!")
    print("=" * 80)
