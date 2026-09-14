#!/usr/bin/env python3
"""
Step 2: Generate & Ingest Synthetic Data into 104 Extended Tables in BigQuery.
Generates realistic e-commerce synthetic records across Domains H to Q:
- Domain H: Staging & Raw Ingestion Tables (20 tables)
- Domain I: Returns, Refunds & RMA Management (10 tables)
- Domain J: Customer Support, CRM & CSAT (12 tables)
- Domain K: Supply Chain, Procurement & Warehousing (14 tables)
- Domain L: Finance, General Ledger, Tax & Accounting (12 tables)
- Domain M: Loyalty, Customer Retention & Rewards (10 tables)
- Domain N: Lifecycle Marketing, Email & Push (10 tables)
- Domain O: Product Information Management (PIM) (8 tables)
- Domain P: Retail Physical Stores & Omni-Channel POS (8 tables)
- Domain Q: Non-Production, Sandbox & QA Archives (10 tables)
"""

import os
import sys
import json
import uuid
import random
import subprocess
from datetime import datetime, timedelta, timezone, date
from faker import Faker
from google.cloud import bigquery
from google.oauth2 import credentials as oauth2_credentials

fake = Faker("en_GB")
random.seed(42)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_TMP_DIR = os.path.join(PROJECT_ROOT, ".tmp")

def load_dotenv():
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())

load_dotenv()

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")
DATASET_ID = os.environ.get("BQ_DATASET_ID", "ecommerce_dw")

def get_bigquery_client():
    token = os.environ.get("GCP_ACCESS_TOKEN")
    if not token:
        gcloud_paths = ["/google/data/ro/teams/cloud-sdk/gcloud", "gcloud"]
        for gcloud_cmd in gcloud_paths:
            try:
                res = subprocess.run([gcloud_cmd, "auth", "print-access-token"], capture_output=True, text=True, timeout=10)
                if res.returncode == 0 and res.stdout.strip():
                    token = res.stdout.strip()
                    break
            except Exception:
                continue

    if token:
        creds = oauth2_credentials.Credentials(token)
        return bigquery.Client(project=PROJECT_ID, credentials=creds)
    return bigquery.Client(project=PROJECT_ID)

# ---------------------------------------------------------------------------
# Temporal cutoff normalisation
# ---------------------------------------------------------------------------
SIM_CUTOFF = datetime(2026, 11, 27, 14, 30, 0, tzinfo=timezone.utc)
_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"

# Fields that are legitimately dated after the snapshot. These express a
# forward-looking entitlement (how long something stays valid), not an event
# that has already been observed, so a future value is correct and they must
# never be rescaled.
FUTURE_DATED_FIELDS = {
    ("store_credit_issuances", "expires_at"),
    ("discount_coupons_master", "valid_to"),
    ("gift_card_transactions", "expires_at"),
}


def _parse_ts(value):
    """Return a datetime if `value` is one of our ISO-Z timestamp strings."""
    if not isinstance(value, str) or len(value) != 20 or not value.endswith("Z"):
        return None
    try:
        return datetime.strptime(value, _TS_FMT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _normalise_event_timestamps(data):
    """Compress observed-event timestamps so none fall after the snapshot.

    Many generators above lay rows out at a fixed cadence -- for example
    `nov23 + timedelta(hours=i * 2)` for 600 rows -- without scaling that
    cadence to the length of the simulation window. A 600-row table at two
    hours per row spans 50 days and so runs months past the Friday 14:30
    snapshot, which is impossible: these columns record things that already
    happened.

    Deleting the overflow would remove up to 73% of some tables and destroy
    their row counts. Instead each affected table gets a single affine
    transform that pins its earliest timestamp in place and maps its latest
    onto the cutoff. Row counts, ordering and relative spacing all survive;
    only the cadence tightens. The transform is shared across every timestamp
    field in a table so that intra-row relationships (a shift starting before
    it ends) are preserved.
    """
    adjusted = []
    for table_name, rows in data.items():
        if not rows:
            continue

        ts_fields = {
            key for row in rows for key, value in row.items()
            if _parse_ts(value) is not None
            and (table_name, key) not in FUTURE_DATED_FIELDS
        }
        if not ts_fields:
            continue

        values = [
            parsed for row in rows for key in ts_fields
            if (parsed := _parse_ts(row.get(key))) is not None
        ]
        if not values:
            continue

        t_min, t_max = min(values), max(values)
        if t_max <= SIM_CUTOFF:
            continue

        span = (t_max - t_min).total_seconds()
        if span <= 0:
            # Every value is identical and in the future: pin them to the cutoff.
            scale = 0.0
            t_min = min(t_min, SIM_CUTOFF)
        else:
            scale = (SIM_CUTOFF - t_min).total_seconds() / span

        for row in rows:
            for key in ts_fields:
                parsed = _parse_ts(row.get(key))
                if parsed is None:
                    continue
                shifted = t_min + timedelta(
                    seconds=(parsed - t_min).total_seconds() * scale
                )
                row[key] = shifted.strftime(_TS_FMT)

        adjusted.append(f"{table_name} (was {t_max.strftime(_TS_FMT)})")

    if adjusted:
        print(f"  Temporal normalisation: rescaled {len(adjusted)} tables "
              f"whose events overran the {SIM_CUTOFF.strftime(_TS_FMT)} snapshot.")


def generate_all_extended_data():
    print("=" * 80)
    print("GENERATING SYNTHETIC DATA FOR 104 EXTENDED TABLES IN BIGQUERY")
    print(f"GCP Project: `{PROJECT_ID}` | Dataset: `{DATASET_ID}`")
    print("=" * 80)

    client = get_bigquery_client()
    now_utc = datetime(2026, 11, 27, 14, 0, 0, tzinfo=timezone.utc)
    nov23 = datetime(2026, 11, 23, 0, 0, 0, tzinfo=timezone.utc)

    # In-memory dictionary of table data lists
    data = {}

    # -------------------------------------------------------------
    # DOMAIN H: Staging & Raw Ingestion (20 Tables)
    # -------------------------------------------------------------
    data["stg_shopify_orders_raw"] = [
        {"payload_id": str(uuid.uuid4()), "topic": "orders/create", "raw_json": json.dumps({"order_num": 10000 + i, "currency": "EUR", "total_price": round(random.uniform(30, 450), 2)}), "shop_domain": "lumiere-eu.myshopify.com", "ingested_at": (nov23 + timedelta(minutes=i*3)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(2500)
    ]
    data["stg_shopify_products_raw"] = [
        {"payload_id": str(uuid.uuid4()), "shopify_product_id": 8000000000 + i, "raw_json": json.dumps({"title": f"Lumiere SKU {i}", "variants": [{"price": round(random.uniform(25, 300), 2)}]}), "ingested_at": (nov23 + timedelta(hours=i%48)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(1200)
    ]
    data["stg_shopify_customers_raw"] = [
        {"payload_id": str(uuid.uuid4()), "shopify_customer_id": 7000000000 + i, "raw_json": json.dumps({"email": f"cust_{i}@example.eu", "orders_count": random.randint(1, 15)}), "ingested_at": (nov23 + timedelta(minutes=i*10)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(1500)
    ]
    data["stg_klaviyo_email_events_raw"] = [
        {"event_id": str(uuid.uuid4()), "event_type": random.choice(["Opened Email", "Clicked Email", "Received Email"]), "profile_id": f"klaviyo_prof_{i%100}", "campaign_id": f"camp_{i%10}", "raw_payload": json.dumps({"subject": "Black Friday Exclusive", "client": "Apple Mail"}), "timestamp": (nov23 + timedelta(minutes=i*2)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(5000)
    ]
    data["stg_klaviyo_campaigns_raw"] = [
        {"campaign_id": f"kl_camp_{i}", "name": f"Klaviyo Campaign {i}", "status": "Sent", "raw_json": json.dumps({"audience_size": 25000 + i*5000}), "synced_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(125)
    ]
    data["stg_stripe_payment_intents_raw"] = [
        {"intent_id": f"pi_3M{i:08d}", "status": "succeeded" if random.random() < 0.96 else "requires_payment_method", "amount_cents": int(round(random.uniform(40, 500) * 100)), "currency": "eur", "raw_payload": json.dumps({"charges": [{"paid": True}]}), "created_at": (nov23 + timedelta(minutes=i*4)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(4000)
    ]
    data["stg_stripe_disputes_raw"] = [
        {"dispute_id": f"dp_1L{i:06d}", "charge_id": f"ch_3M{i:06d}", "amount_cents": int(round(random.uniform(50, 300) * 100)), "reason": random.choice(["fraudulent", "unrecognized", "duplicate"]), "status": random.choice(["under_review", "won", "lost"]), "created_at": (nov23 + timedelta(hours=i*2)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(300)
    ]
    data["stg_zendesk_tickets_raw"] = [
        {"ticket_id": 50000 + i, "subject": random.choice(["Order tracking update", "Return request question", "Discount code issue", "Product ingredient inquiry"]), "status": random.choice(["open", "pending", "solved", "closed"]), "priority": random.choice(["low", "normal", "high"]), "raw_json": json.dumps({"via": "web"}), "created_at": (nov23 + timedelta(minutes=i*8)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(2500)
    ]
    data["stg_zendesk_satisfaction_raw"] = [
        {"rating_id": 90000 + i, "ticket_id": 50000 + i, "score": random.choice(["good", "good", "good", "bad"]), "comment": "Fast helpful support!" if random.random() < 0.8 else "Took 2 days to reply", "created_at": (nov23 + timedelta(minutes=i*12)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(1500)
    ]
    data["stg_google_ads_campaigns_raw"] = [
        {"date": (date(2026, 11, 23) + timedelta(days=i%5)), "campaign_id": 800100 + (i//5), "campaign_name": f"Google_Search_Brand_EU_{i//5}", "impressions": random.randint(50000, 200000), "clicks": random.randint(3000, 15000), "cost_micros": int(random.uniform(1500, 8000) * 1e6), "conversions": float(random.randint(100, 600)), "synced_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(125)
    ]
    data["stg_google_ads_search_terms_raw"] = [
        {"date": (date(2026, 11, 23) + timedelta(days=i%5)), "search_term": random.choice(["lumiere shop", "luxury skin serum", "designer wool coat", "noise cancelling headphones", "black friday beauty deals"]), "campaign_id": 800100 + (i%5), "clicks": random.randint(50, 800), "impressions": random.randint(500, 8000), "cost_micros": int(random.uniform(50, 500) * 1e6), "synced_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(600)
    ]
    data["stg_meta_ad_insights_raw"] = [
        {"date_start": (date(2026, 11, 23) + timedelta(days=i%5)), "adset_id": f"adset_{i%10}", "campaign_id": "1001", "raw_json": json.dumps({"cpc": round(random.uniform(0.35, 0.90), 2), "reach": random.randint(80000, 350000)}), "synced_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(150)
    ]
    data["stg_ga4_clickstream_raw"] = [
        {"event_date": "20261125", "event_timestamp": int(nov23.timestamp() * 1e6 + i*1e6), "event_name": random.choice(["page_view", "scroll", "user_engagement", "view_item"]), "user_pseudo_id": f"pseudo_{i%200}", "raw_payload": json.dumps({"device_category": "mobile"})}
        for i in range(5000)
    ]
    data["stg_ga4_traffic_sources_raw"] = [
        {"session_id": f"SESS-GA4-{i}", "source": random.choice(["google", "meta", "direct", "newsletter", "criteo"]), "medium": random.choice(["cpc", "organic", "none", "email"]), "campaign": "black_friday_2026", "synced_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(2500)
    ]
    data["stg_sap_erp_inventory_feed_raw"] = [
        {"batch_id": f"SAP-BATCH-{i%5}", "material_number": f"MAT-{1000+i}", "plant_id": random.choice(["PLANT-PARIS-01", "PLANT-ROTTERDAM-02"]), "unrestricted_stock_qty": random.randint(0, 1500), "synced_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(1200)
    ]
    data["stg_sap_erp_purchase_orders_raw"] = [
        {"po_number": f"SAP-PO-{7000+i}", "vendor_code": f"VEND-{i%20}", "raw_payload": json.dumps({"currency": "EUR", "total_val": round(random.uniform(10000, 80000), 2)}), "created_at": (nov23 - timedelta(days=i)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(300)
    ]
    data["stg_wms_shipments_raw"] = [
        {"shipment_id": str(uuid.uuid4()), "order_id": 10000 + i, "tracking_number": f"DHL{i:09d}EU", "carrier_code": "DHL", "manifest_status": "MANIFESTED", "dispatched_at": (nov23 + timedelta(minutes=i*6)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(2000)
    ]
    data["stg_criteo_retargeting_raw"] = [
        {"date": (date(2026, 11, 23) + timedelta(days=i%5)), "campaign_id": 3001 + (i//5), "impressions": random.randint(20000, 80000), "clicks": random.randint(800, 3500), "cost_eur": round(random.uniform(400, 2000), 2), "synced_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(100)
    ]
    data["stg_trustpilot_reviews_raw"] = [
        {"review_id": str(uuid.uuid4()), "stars": random.choice([4, 5, 5, 5, 3, 1]), "title": "Super fast delivery", "content": "Delighted with my Lumiere products, luxury packaging.", "verified_buyer": True, "created_at": (nov23 + timedelta(hours=i*3)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(80)
    ]
    data["stg_adyen_settlements_raw"] = [
        {"batch_id": f"ADYEN-SETTLE-{i}", "merchant_account": "LumiereShop_EU", "gross_amount": round(random.uniform(80000, 250000), 2), "fees_amount": round(random.uniform(1200, 4000), 2), "net_amount": round(random.uniform(78000, 246000), 2), "settled_at": (nov23 + timedelta(days=i)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(5)
    ]

    # -------------------------------------------------------------
    # DOMAIN I: Returns, Refunds & RMA (10 Tables)
    # -------------------------------------------------------------
    return_reasons = [
        {"reason_code": "R_DEFECT", "category": "Quality", "description": "Item defective or broken", "requires_photo_proof": True},
        {"reason_code": "R_SIZE", "category": "Fit", "description": "Wrong apparel size or fit", "requires_photo_proof": False},
        {"reason_code": "R_MIND", "category": "Preference", "description": "Customer changed mind", "requires_photo_proof": False},
        {"reason_code": "R_LATE", "category": "Logistics", "description": "Package arrived too late", "requires_photo_proof": False},
        {"reason_code": "R_WRONG_ITEM", "category": "Logistics", "description": "Shipped incorrect SKU", "requires_photo_proof": True}
    ]
    data["return_reasons_lookup"] = return_reasons

    data["product_returns"] = [
        {"return_id": 6000 + i, "order_id": 1001 + (i%50), "order_item_id": 2000 + i, "user_id": 100 + (i%500), "reason_code": random.choice(["R_SIZE", "R_MIND", "R_DEFECT"]), "status": random.choice(["Requested", "Approved", "Received", "Inspected", "Refunded"]), "created_at": (nov23 + timedelta(hours=i%72)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(1500)
    ]
    data["return_shipping_labels"] = [
        {"label_id": f"LBL-RET-{i:05d}", "return_id": 6000 + i, "carrier_name": "DHL Express", "tracking_number": f"RET{i:08d}FR", "label_cost_eur": 4.50, "created_at": (nov23 + timedelta(hours=i%72)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(1500)
    ]
    data["return_inspections"] = [
        {"inspection_id": 7000 + i, "return_id": 6000 + i, "inspector_id": f"INSP-{i%5}", "item_condition": random.choice(["Brand New", "Open Box", "Damaged"]), "disposition": random.choice(["Restock", "Refurbish", "Scrap"]), "inspected_at": (nov23 + timedelta(hours=i%72 + 6)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(1500)
    ]
    data["warehouse_refurbishments"] = [
        {"refurb_id": 8000 + i, "product_id": 1001 + (i%50), "labor_hours_spent": round(random.uniform(0.5, 2.0), 1), "parts_cost_eur": round(random.uniform(5.0, 20.0), 2), "status": "Completed", "completed_at": (nov23 + timedelta(hours=i%72)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(60)
    ]
    data["customer_refunds"] = [
        {"refund_id": 9000 + i, "order_id": 1001 + (i%50), "return_id": 6000 + i, "refund_amount": round(random.uniform(30.0, 350.0), 2), "payment_gateway": random.choice(["Stripe", "Adyen", "PayPal"]), "gateway_refund_id": f"re_{i:07d}", "processed_at": (nov23 + timedelta(hours=i%72 + 12)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(1500)
    ]
    data["store_credit_issuances"] = [
        {"credit_id": 1001 + (i%50), "user_id": 100 + i, "amount_eur": round(random.uniform(20.0, 150.0), 2), "balance_remaining": round(random.uniform(10.0, 150.0), 2), "expires_at": (now_utc + timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ"), "created_at": (nov23 + timedelta(hours=i%72)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(80)
    ]
    data["warranty_claims"] = [
        {"claim_id": 3000 + i, "product_id": 2000 + (i%50), "user_id": 100 + i, "claim_type": "Manufacturing Defect", "status": "Approved", "filed_at": (nov23 + timedelta(hours=i%72)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(200)
    ]
    data["replacement_orders"] = [
        {"replacement_id": 4000 + i, "original_order_id": 1001 + (i%50), "new_order_id": 80000 + i, "authorized_by": "supervisor_claire", "created_at": (nov23 + timedelta(hours=i%72)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(300)
    ]
    data["restocking_fee_logs"] = [
        {"fee_id": 5000 + i, "return_id": 6000 + i, "fee_amount_eur": 9.99, "deducted_at": (nov23 + timedelta(hours=i%72)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(150)
    ]

    # -------------------------------------------------------------
    # DOMAIN J: Customer Support & CRM (12 Tables)
    # -------------------------------------------------------------
    data["support_agents"] = [
        {"agent_id": f"agent_{i:02d}", "full_name": fake.name(), "tier": random.choice(["Tier1_General", "Tier2_Specialist", "Tier3_Escalations"]), "primary_language": random.choice(["FR", "DE", "EN", "NL"])}
        for i in range(125)
    ]
    data["ticket_categories"] = [
        {"category_id": 1, "name": "WhereIsMyOrder", "sla_target_minutes": 120},
        {"category_id": 2, "name": "ProductInquiry", "sla_target_minutes": 240},
        {"category_id": 3, "name": "ReturnRequest", "sla_target_minutes": 180},
        {"category_id": 4, "name": "DiscountCodeHelp", "sla_target_minutes": 60},
        {"category_id": 5, "name": "PaymentIssue", "sla_target_minutes": 45}
    ]
    data["support_tickets"] = [
        {"ticket_id": 100000 + i, "user_id": 100 + (i%500), "order_id": 1000 + (i%1000), "channel": random.choice(["Email", "Chat", "Phone"]), "priority": random.choice(["Low", "Medium", "High"]), "status": random.choice(["Open", "Pending", "Resolved", "Closed"]), "first_response_time_sec": random.randint(180, 3600), "resolution_time_sec": random.randint(1800, 86400), "created_at": (nov23 + timedelta(minutes=i*12)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(2000)
    ]
    data["ticket_messages"] = [
        {"message_id": 200000 + i, "ticket_id": 100000 + (i//3), "sender_type": random.choice(["Customer", "Agent"]), "sender_id": f"user_{i%50}", "body": "Thank you for looking into my delivery status.", "created_at": (nov23 + timedelta(minutes=i*5)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(5000)
    ]
    data["agent_worklog_shifts"] = [
        {"shift_id": 3000 + i, "agent_id": f"agent_{i%25:02d}", "shift_date": (date(2026, 11, 23) + timedelta(days=i%5)), "tickets_resolved": random.randint(15, 45), "avg_handle_time_sec": round(random.uniform(240, 600), 1)}
        for i in range(75)
    ]
    data["csat_surveys"] = [
        {"survey_id": 4000 + i, "ticket_id": 100000 + i, "score": random.choice([4, 5, 5, 5, 3, 2]), "verbatim_feedback": "Very helpful support rep", "submitted_at": (nov23 + timedelta(minutes=i*20)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(1500)
    ]
    data["nps_feedback_responses"] = [
        {"nps_id": 5000 + i, "user_id": 100 + i, "score": random.choice([8, 9, 10, 10, 7, 5]), "feedback_text": "Great luxury shopping experience", "survey_date": date(2026, 11, 25)}
        for i in range(150)
    ]
    data["live_chat_sessions"] = [
        {"chat_session_id": str(uuid.uuid4()), "user_id": 100 + (i%200), "agent_id": f"agent_{i%20:02d}", "wait_time_sec": random.randint(5, 60), "duration_sec": random.randint(120, 900), "started_at": (nov23 + timedelta(minutes=i*15)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(1500)
    ]
    data["live_chat_messages"] = [
        {"message_id": 600000 + i, "chat_session_id": data["live_chat_sessions"][i%300]["chat_session_id"], "sender": random.choice(["Visitor", "Agent"]), "content": "Can I apply my coupon to clearance beauty items?", "sent_at": (nov23 + timedelta(minutes=i*6)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(4000)
    ]
    data["call_center_recordings_metadata"] = [
        {"call_id": str(uuid.uuid4()), "customer_phone_hash": fake.sha256()[:16], "ivr_selection": "Shipping_Status", "duration_seconds": random.randint(90, 480), "call_start_time": (nov23 + timedelta(minutes=i*30)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(150)
    ]
    data["customer_escalations"] = [
        {"escalation_id": 7000 + i, "ticket_id": 100000 + (i*10), "manager_id": "director_sarah", "escalation_reason": "High VIP basket delayed", "financial_concession_eur": 25.0, "escalated_at": (nov23 + timedelta(hours=i*4)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(125)
    ]
    data["knowledge_base_articles"] = [
        {"article_id": 8000 + i, "title": f"How to track your Black Friday delivery #{i}", "category": "Shipping & Tracking", "view_count": random.randint(500, 8000), "helpful_votes": random.randint(80, 1200), "updated_at": nov23.strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(300)
    ]

    # -------------------------------------------------------------
    # DOMAIN K: Supply Chain, WMS & Logistics (14 Tables)
    # -------------------------------------------------------------
    data["suppliers_master"] = [
        {"supplier_id": 10 + i, "company_name": f"Supplier {fake.company()} EU", "country_code": random.choice(["FR", "DE", "IT", "CH"]), "payment_terms": "Net_30", "is_active": True}
        for i in range(150)
    ]
    data["purchase_orders"] = [
        {"po_id": 5000 + i, "supplier_id": 10 + (i%30), "destination_dc_id": random.choice([1, 2]), "status": "Received", "total_amount_eur": round(random.uniform(15000, 95000), 2), "issued_date": date(2026, 10, 15), "expected_delivery_date": date(2026, 11, 20)}
        for i in range(60)
    ]
    data["purchase_order_line_items"] = [
        {"po_line_id": 60000 + i, "po_id": 5000 + (i%60), "product_id": 1000 + (i%200), "ordered_quantity": random.randint(200, 2000), "received_quantity": random.randint(200, 2000), "unit_cost_eur": round(random.uniform(15.0, 120.0), 2)}
        for i in range(1200)
    ]
    data["supplier_lead_time_history"] = [
        {"history_id": 7000 + i, "supplier_id": 10 + (i%30), "product_id": 1001 + (i%50), "promised_lead_days": 14, "actual_lead_days": random.randint(12, 18), "delivery_date": date(2026, 11, 15)}
        for i in range(600)
    ]
    data["supplier_quality_scorecards"] = [
        {"scorecard_id": 8000 + i, "supplier_id": 10 + i, "month": "2026-11", "otif_delivery_pct": round(random.uniform(92.0, 99.5), 1), "defect_rate_pct": round(random.uniform(0.1, 1.2), 2), "overall_score": round(random.uniform(88.0, 98.0), 1)}
        for i in range(150)
    ]
    data["inbound_dock_appointments"] = [
        {"appointment_id": 9000 + i, "dc_id": random.choice([1, 2]), "po_id": 5000 + (i%60), "carrier_name": "Kuehne+Nagel", "dock_door_number": (i%8) + 1, "scheduled_time": (nov23 - timedelta(days=i%10)).strftime("%Y-%m-%dT%H:%M:%SZ"), "unloaded_time": (nov23 - timedelta(days=i%10, hours=-2)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(80)
    ]
    data["warehouse_zones"] = [
        {"zone_id": 1, "dc_id": 1, "zone_name": "Paris_Luxury_Skincare_TempControl", "temperature_celsius": 18.0},
        {"zone_id": 2, "dc_id": 1, "zone_name": "Paris_Electronics_HighSecurity", "temperature_celsius": 21.0},
        # dc_id 2 is the Rotterdam Port Hub. These two zones used to be named
        # "Frankfurt_*", a distribution centre that does not exist anywhere in
        # this business - the five DCs are Paris Nord, Rotterdam Port Hub,
        # Hamburg Sued, Milano Est and Barcelona Zona Franca. DACH is kept in
        # the name because Rotterdam is the port serving the German hinterland.
        {"zone_id": 3, "dc_id": 2, "zone_name": "Rotterdam_DACH_Ambient_Fashion", "temperature_celsius": 20.0},
        {"zone_id": 4, "dc_id": 2, "zone_name": "Rotterdam_DACH_HomeDecor_Heavy", "temperature_celsius": 19.0}
    ]
    data["warehouse_aisles_and_racks"] = [
        {"bin_id": f"BIN-{zone}-{aisle:02d}-{shelf:02d}", "zone_id": zone, "aisle_number": aisle, "rack_level": shelf, "max_weight_kg": 500.0}
        for zone in [1, 2, 3, 4] for aisle in range(1, 11) for shelf in range(1, 5)
    ]
    data["pallet_inventory_locations"] = [
        {"pallet_lpn": f"LPN-{i:06d}", "bin_id": data["warehouse_aisles_and_racks"][i%len(data["warehouse_aisles_and_racks"])]["bin_id"], "product_id": 1000 + (i%200), "quantity_on_pallet": random.randint(50, 400), "last_scanned_at": nov23.strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(1500)
    ]
    data["warehouse_labor_shifts"] = [
        {"shift_id": 1001 + (i%50), "dc_id": (i%2)+1, "employee_id": f"WH_EMP_{i%40}", "role": random.choice(["Picker", "Packer", "Stager"]), "shift_start": (nov23 + timedelta(hours=i*8)).strftime("%Y-%m-%dT%H:%M:%SZ"), "shift_end": (nov23 + timedelta(hours=i*8 + 8)).strftime("%Y-%m-%dT%H:%M:%SZ"), "units_picked": random.randint(250, 850)}
        for i in range(60)
    ]
    data["forklift_telemetry_logs"] = [
        {"telemetry_id": 2000 + i, "equipment_id": f"AGV-{i%10:02d}", "battery_pct": random.randint(35, 100), "odometer_km": round(random.uniform(50.0, 450.0), 1), "recorded_at": (nov23 + timedelta(hours=i*2)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(600)
    ]
    data["cross_dock_transfer_orders"] = [
        {"transfer_id": 3000 + i, "source_dc_id": 1, "destination_dc_id": 2, "product_id": 1001 + (i%50), "quantity": random.randint(100, 500), "shipped_at": (nov23 - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"), "received_at": nov23.strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(150)
    ]
    data["freight_carrier_contracts"] = [
        {"contract_id": "CTR-DHL-2026", "carrier_name": "DHL Express", "base_rate_per_kg_eur": 2.40, "fuel_surcharge_pct": 8.5, "valid_until": date(2027, 12, 31)},
        {"contract_id": "CTR-UPS-2026", "carrier_name": "UPS Standard", "base_rate_per_kg_eur": 2.25, "fuel_surcharge_pct": 9.0, "valid_until": date(2027, 12, 31)},
        {"contract_id": "CTR-FEDEX-2026", "carrier_name": "FedEx Ground EU", "base_rate_per_kg_eur": 2.30, "fuel_surcharge_pct": 8.8, "valid_until": date(2027, 12, 31)}
    ]
    data["customs_and_duties_declarations"] = [
        {"declaration_id": f"CUST-DEC-{i:05d}", "po_id": 5000 + (i%60), "hs_tariff_code": "3304.99.00", "duty_amount_eur": round(random.uniform(500, 3500), 2), "cleared_date": date(2026, 11, 18)}
        for i in range(200)
    ]

    # -------------------------------------------------------------
    # DOMAIN L: Finance, General Ledger, Tax & Accounting (12 Tables)
    # -------------------------------------------------------------
    coa = [
        {"account_number": "1010", "account_name": "Cash and Cash Equivalents", "account_type": "Asset", "is_active": True},
        {"account_number": "1050", "account_name": "Accounts Receivable", "account_type": "Asset", "is_active": True},
        {"account_number": "1200", "account_name": "Merchandise Inventory", "account_type": "Asset", "is_active": True},
        {"account_number": "2010", "account_name": "Accounts Payable", "account_type": "Liability", "is_active": True},
        {"account_number": "2050", "account_name": "VAT Output Tax Payable", "account_type": "Liability", "is_active": True},
        {"account_number": "4010", "account_name": "E-Commerce Retail Sales Revenue", "account_type": "Revenue", "is_active": True},
        {"account_number": "5010", "account_name": "Cost of Goods Sold (COGS)", "account_type": "Expense", "is_active": True},
        {"account_number": "6010", "account_name": "Paid Advertising Marketing Expense", "account_type": "Expense", "is_active": True},
        {"account_number": "6020", "account_name": "Fulfillment and Freight Shipping Expense", "account_type": "Expense", "is_active": True},
        {"account_number": "6030", "account_name": "Payment Gateway Processing Fees", "account_type": "Expense", "is_active": True}
    ]
    data["chart_of_accounts"] = coa

    data["general_ledger_journal_entries"] = [
        {"journal_id": 80000 + i, "journal_date": (date(2026, 11, 23) + timedelta(days=i%5)), "description": f"Daily automated revenue & cash batch posting day {i%5+1}", "source_module": "Sales", "posted_by": "sys_accounting_bot", "posted_at": (nov23 + timedelta(days=i%5, hours=23)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(125)
    ]
    gl_lines = []
    for i in range(125):
        gl_lines.append({"line_id": 90000 + i*2, "journal_id": 80000 + (i%25), "account_number": "1010", "debit_amount_eur": 125000.0, "credit_amount_eur": 0.0})
        gl_lines.append({"line_id": 90000 + i*2 + 1, "journal_id": 80000 + (i%25), "account_number": "4010", "debit_amount_eur": 0.0, "credit_amount_eur": 125000.0})
    data["gl_journal_lines"] = gl_lines
    data["accounts_payable_invoices"] = [
        {"invoice_id": 1001 + (i%50), "vendor_name": f"Vendor {i%10}", "invoice_number": f"INV-2026-{i:04d}", "invoice_amount_eur": round(random.uniform(5000, 45000), 2), "payment_due_date": date(2026, 12, 15), "status": "Approved", "received_date": date(2026, 11, 15)}
        for i in range(200)
    ]
    data["accounts_payable_disbursements"] = [
        {"disbursement_id": 2000 + i, "invoice_id": 1001 + (i%50), "amount_paid_eur": round(random.uniform(5000, 45000), 2), "payment_method": "SEPA_Wire", "paid_at": (nov23 + timedelta(days=i%4)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(150)
    ]
    data["accounts_receivable_invoices"] = [
        {"ar_invoice_id": 3000 + i, "corporate_client_name": f"Corporate Client {i%8}", "billed_amount_eur": round(random.uniform(8000, 35000), 2), "due_date": date(2026, 12, 30), "is_settled": False, "issued_date": date(2026, 11, 24)}
        for i in range(100)
    ]
    data["bank_account_reconciliation"] = [
        {"reconciliation_id": 4000 + i, "bank_name": "BNP Paribas Treasury", "statement_date": (date(2026, 11, 23) + timedelta(days=i%5)), "opening_balance_eur": 4500000.0 + i*150000, "closing_balance_eur": 4650000.0 + i*150000, "variance_eur": 0.0}
        for i in range(5)
    ]
    data["vat_tax_jurisdictions"] = [
        {"country_code": "FR", "country_name": "France", "standard_vat_rate_pct": 20.0, "reduced_vat_rate_pct": 5.5},
        {"country_code": "DE", "country_name": "Germany", "standard_vat_rate_pct": 19.0, "reduced_vat_rate_pct": 7.0},
        {"country_code": "NL", "country_name": "Netherlands", "standard_vat_rate_pct": 21.0, "reduced_vat_rate_pct": 9.0},
        {"country_code": "ES", "country_name": "Spain", "standard_vat_rate_pct": 21.0, "reduced_vat_rate_pct": 10.0},
        {"country_code": "IT", "country_name": "Italy", "standard_vat_rate_pct": 22.0, "reduced_vat_rate_pct": 10.0},
        {"country_code": "BE", "country_name": "Belgium", "standard_vat_rate_pct": 21.0, "reduced_vat_rate_pct": 6.0},
        {"country_code": "AT", "country_name": "Austria", "standard_vat_rate_pct": 20.0, "reduced_vat_rate_pct": 10.0}
    ]
    data["vat_period_filing_reports"] = [
        {"filing_id": f"OSS-2026-11-{c}", "country_code": c, "taxable_sales_eur": round(random.uniform(500000, 1500000), 2), "vat_collected_eur": round(random.uniform(100000, 300000), 2), "filed_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")}
        for c in ["FR", "DE", "NL", "ES", "IT", "BE", "AT"]
    ]
    data["currency_exchange_rates_daily"] = [
        {"date": (date(2026, 11, 23) + timedelta(days=i%5)), "currency_code": curr, "rate_to_eur": rate, "fetched_at": nov23.strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(5) for curr, rate in [("USD", 1.085), ("GBP", 0.855), ("CHF", 0.945), ("PLN", 4.32)]
    ]
    data["intercompany_transfer_pricing"] = [
        {"schedule_id": "TP-MGMT-2026", "source_entity": "Lumiere Group SAS (France)", "receiving_entity": "Lumiere GmbH (Germany)", "markup_percentage": 5.0, "effective_year": 2026},
        {"schedule_id": "TP-TECH-2026", "source_entity": "Lumiere Group SAS (France)", "receiving_entity": "Lumiere BV (Netherlands)", "markup_percentage": 6.5, "effective_year": 2026}
    ]
    data["payment_gateway_fee_schedules"] = [
        {"gateway_name": "Stripe Credit Cards", "interchange_pct": 1.4, "fixed_fee_eur": 0.25, "effective_date": date(2026, 1, 1)},
        {"gateway_name": "PayPal Express Checkout", "interchange_pct": 2.9, "fixed_fee_eur": 0.35, "effective_date": date(2026, 1, 1)},
        {"gateway_name": "Adyen Local Payment Methods", "interchange_pct": 1.1, "fixed_fee_eur": 0.15, "effective_date": date(2026, 1, 1)},
        {"gateway_name": "Apple Pay / Google Pay", "interchange_pct": 1.4, "fixed_fee_eur": 0.25, "effective_date": date(2026, 1, 1)}
    ]

    # -------------------------------------------------------------
    # DOMAIN M: Loyalty, Customer Retention & Rewards (10 Tables)
    # -------------------------------------------------------------
    data["loyalty_tier_definitions"] = [
        {"tier_name": "Bronze", "qualifying_annual_spend_eur": 0.0, "points_multiplier": 1.0, "free_shipping_threshold_eur": 50.0},
        {"tier_name": "Silver", "qualifying_annual_spend_eur": 250.0, "points_multiplier": 1.25, "free_shipping_threshold_eur": 35.0},
        {"tier_name": "Gold", "qualifying_annual_spend_eur": 600.0, "points_multiplier": 1.5, "free_shipping_threshold_eur": 0.0},
        {"tier_name": "Platinum", "qualifying_annual_spend_eur": 1500.0, "points_multiplier": 2.0, "free_shipping_threshold_eur": 0.0}
    ]
    data["loyalty_members"] = [
        {"membership_id": 50000 + i, "user_id": 100 + i, "current_tier": random.choice(["Bronze", "Silver", "Gold", "Platinum"]), "total_points_balance": random.randint(50, 3500), "joined_at": (nov23 - timedelta(days=random.randint(30, 700))).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(2500)
    ]
    data["loyalty_points_ledger"] = [
        {"ledger_id": 60000 + i, "user_id": 100 + (i%500), "order_id": 1000 + (i%1000), "points_delta": random.randint(25, 450), "transaction_type": "PurchaseAccrual", "created_at": (nov23 + timedelta(minutes=i*10)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(4000)
    ]
    data["loyalty_reward_redemptions"] = [
        {"redemption_id": 7000 + i, "user_id": 100 + (i%500), "points_spent": 500, "reward_type": "10EUR_Voucher", "redeemed_at": (nov23 + timedelta(hours=i*2)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(600)
    ]
    data["discount_coupons_master"] = [
        {"coupon_id": 101, "promo_code": "BLACKFRIDAY20", "discount_type": "Percentage", "discount_value": 20.0, "min_order_amount_eur": 50.0, "is_active": True, "valid_from": nov23.strftime("%Y-%m-%dT%H:%M:%SZ"), "valid_to": (nov23 + timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ")},
        {"coupon_id": 102, "promo_code": "WELCOME10", "discount_type": "Percentage", "discount_value": 10.0, "min_order_amount_eur": 30.0, "is_active": True, "valid_from": "2026-01-01T00:00:00Z", "valid_to": "2026-12-31T23:59:59Z"},
        {"coupon_id": 103, "promo_code": "VIPLUXURY", "discount_type": "FixedAmount", "discount_value": 30.0, "min_order_amount_eur": 150.0, "is_active": True, "valid_from": nov23.strftime("%Y-%m-%dT%H:%M:%SZ"), "valid_to": (nov23 + timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ")},
        {"coupon_id": 104, "promo_code": "FREESHIP", "discount_type": "FreeShipping", "discount_value": 4.99, "min_order_amount_eur": 25.0, "is_active": True, "valid_from": nov23.strftime("%Y-%m-%dT%H:%M:%SZ"), "valid_to": (nov23 + timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    ]
    data["coupon_redemption_audit"] = [
        {"audit_id": 8000 + i, "order_id": 1001 + (i%50), "coupon_id": random.choice([101, 102, 103]), "user_id": 100 + i, "discount_applied_eur": round(random.uniform(10.0, 50.0), 2), "applied_at": (nov23 + timedelta(minutes=i*15)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(1500)
    ]
    data["referral_program_invites"] = [
        {"invite_id": 9000 + i, "referrer_user_id": 100 + i, "referral_code": f"REF-{fake.first_name().upper()}-{i}", "friend_email_hash": fake.sha256()[:16], "created_at": (nov23 + timedelta(hours=i*2)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(600)
    ]
    data["referral_reward_claims"] = [
        {"claim_id": 1001 + (i%50), "invite_id": 9000 + i, "referred_order_id": 50000 + i, "reward_credit_eur": 15.0, "claimed_at": (nov23 + timedelta(hours=i*4)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(200)
    ]
    data["gift_card_master"] = [
        {"card_id": 2000 + i, "code_hash": fake.sha256()[:20], "initial_balance_eur": 100.0, "current_balance_eur": round(random.uniform(20.0, 100.0), 2), "is_active": True, "purchaser_user_id": 100 + i, "issued_at": (nov23 - timedelta(days=i%30)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(80)
    ]
    data["gift_card_transactions"] = [
        {"transaction_id": 3000 + i, "card_id": 2000 + (i%80), "order_id": 1001 + (i%50), "amount_eur": round(random.uniform(15.0, 75.0), 2), "transacted_at": (nov23 + timedelta(hours=i*2)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(120)
    ]

    # -------------------------------------------------------------
    # DOMAIN N: Lifecycle Marketing (10 Tables)
    # -------------------------------------------------------------
    data["email_campaign_templates"] = [
        {"template_id": 1, "template_name": "BlackFriday_Midnight_VIP_Launch", "subject_line_variant_a": "Black Friday is Live: 20% Off Luxury", "subject_line_variant_b": "Your Early Access Black Friday Pass", "created_at": nov23.strftime("%Y-%m-%dT%H:%M:%SZ")},
        {"template_id": 2, "template_name": "Cart_Abandonment_Nudge", "subject_line_variant_a": "You left something in your shopping bag", "subject_line_variant_b": "Complete your order before Black Friday stock runs out", "created_at": nov23.strftime("%Y-%m-%dT%H:%M:%SZ")},
        {"template_id": 3, "template_name": "CyberMonday_SneakPeek", "subject_line_variant_a": "Cyber Monday tech & beauty deals preview", "subject_line_variant_b": "Final hours of Black Week savings", "created_at": nov23.strftime("%Y-%m-%dT%H:%M:%SZ")}
    ]
    data["email_send_queue_logs"] = [
        {"send_id": 1000000 + i, "user_id": 100 + (i%500), "template_id": (i%3)+1, "status": random.choice(["Delivered", "Opened", "Clicked", "Sent"]), "sent_at": (nov23 + timedelta(minutes=i*4)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(5000)
    ]
    data["email_bounces_and_complaints"] = [
        {"bounce_id": 5000 + i, "user_id": 100 + i, "bounce_type": random.choice(["HardBounce_BadMailbox", "SoftBounce_Quota"]), "recorded_at": (nov23 + timedelta(hours=i*4)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(150)
    ]
    data["sms_marketing_broadcasts"] = [
        {"sms_campaign_id": 10, "campaign_name": "BF_VIP_SMS_Alert", "message_copy": "Lumière Black Friday is officially live! Enjoy 20% off with code BLACKFRIDAY20 at lumireshop.eu", "target_segment": "VIP_Club", "dispatched_at": nov23.strftime("%Y-%m-%dT%H:%M:%SZ")},
        {"sms_campaign_id": 11, "campaign_name": "BF_Friday_Flash_Drop", "message_copy": "Friday Flash Deals are now live across Beauty & Fashion: lumireshop.eu/deals", "target_segment": "All_OptedIn", "dispatched_at": (nov23 + timedelta(days=4, hours=8)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    ]
    data["sms_delivery_receipts"] = [
        {"receipt_id": 80000 + i, "sms_campaign_id": random.choice([10, 11]), "user_id": 100 + (i%500), "delivery_status": "Delivered", "delivered_at": (nov23 + timedelta(minutes=i*10)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(2000)
    ]
    data["mobile_app_push_campaigns"] = [
        {"push_campaign_id": 20, "title": "Black Friday is HERE ✨", "body_text": "Explore exclusive luxury discounts up to 30% in the app.", "target_deeplink": "lumiere://deals/blackfriday", "sent_at": nov23.strftime("%Y-%m-%dT%H:%M:%SZ")},
        {"push_campaign_id": 21, "title": "⚡ Flash Restock Alert", "body_text": "Bestselling Beauty & Electronics items just restocked.", "target_deeplink": "lumiere://categories/beauty", "sent_at": (nov23 + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    ]
    data["push_notification_receipts"] = [
        {"push_id": 90000 + i, "push_campaign_id": random.choice([20, 21]), "user_id": 100 + (i%500), "platform": random.choice(["iOS", "Android"]), "was_clicked": random.random() < 0.22, "delivered_at": (nov23 + timedelta(minutes=i*8)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(2500)
    ]
    data["user_subscription_preferences"] = [
        {"preference_id": 100 + i, "user_id": 100 + i, "email_opt_in": True, "sms_opt_in": random.random() < 0.45, "push_opt_in": random.random() < 0.65, "updated_at": nov23.strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(2500)
    ]
    data["affiliate_publishers_directory"] = [
        {"affiliate_id": 50 + i, "publisher_name": f"Affiliate {fake.company()} Media", "commission_rate_pct": 8.0, "is_active": True}
        for i in range(100)
    ]
    data["affiliate_commission_payouts"] = [
        {"payout_id": 6000 + i, "affiliate_id": 50 + (i%20), "period": "2026-11", "attributed_sales_eur": round(random.uniform(5000, 35000), 2), "commission_earned_eur": round(random.uniform(400, 2800), 2), "is_paid": False}
        for i in range(100)
    ]

    # -------------------------------------------------------------
    # DOMAIN O: PIM & Catalog Merchandising (8 Tables)
    # -------------------------------------------------------------
    data["product_attribute_definitions"] = [
        {"attribute_id": 1, "attribute_code": "volume_ml", "display_label": "Volume (ml)", "data_type": "Number"},
        {"attribute_id": 2, "attribute_code": "skin_type", "display_label": "Skin Type Recommendation", "data_type": "Enum"},
        {"attribute_id": 3, "attribute_code": "battery_life_hours", "display_label": "Battery Life (Hours)", "data_type": "Number"},
        {"attribute_id": 4, "attribute_code": "material_fabric", "display_label": "Fabric Composition", "data_type": "Text"}
    ]
    data["product_attribute_values"] = [
        {"value_id": 10000 + i, "product_id": 1000 + (i%200), "attribute_id": (i%4)+1, "attribute_value": random.choice(["50ml", "All Skin Types", "24 Hours", "100% Cashmere Wool"])}
        for i in range(2000)
    ]
    data["product_multilingual_translations"] = [
        {"translation_id": 20000 + i, "product_id": 1001 + (i%50), "language_code": random.choice(["fr", "de", "nl", "es"]), "localized_name": f"Produit Luxe #{i%100}", "localized_description": "Formule dermatologique luxueuse pour des résultats visibles dès la première application."}
        for i in range(1500)
    ]
    data["product_media_gallery"] = [
        {"media_id": 30000 + i, "product_id": 1001 + (i%50), "media_type": random.choice(["Main_Hero", "Gallery_Photo", "Model_Video"]), "cdn_url": f"https://cdn.lumireshop.eu/media/prod_{i%100}_{i%3}.webp", "sort_order": (i%3)+1}
        for i in range(1500)
    ]
    data["product_size_charts"] = [
        {"size_chart_id": 1, "category_id": 3, "size_label": "S", "chest_cm": 92.0, "waist_cm": 76.0},
        {"size_chart_id": 2, "category_id": 3, "size_label": "M", "chest_cm": 98.0, "waist_cm": 82.0},
        {"size_chart_id": 3, "category_id": 3, "size_label": "L", "chest_cm": 104.0, "waist_cm": 88.0}
    ]
    data["product_brand_guidelines"] = [
        {"guideline_id": 1, "brand_name": "Lumière Paris", "min_advertised_price_policy": True, "authorized_distributor_only": True},
        {"guideline_id": 2, "brand_name": "Nuit Étoilée", "min_advertised_price_policy": True, "authorized_distributor_only": True},
        {"guideline_id": 3, "brand_name": "Aura Tech", "min_advertised_price_policy": False, "authorized_distributor_only": False}
    ]
    data["category_hierarchy_paths"] = [
        {"path_id": 1, "category_id": 1, "parent_category_id": None, "breadcrumb_path": "Home > Beauty"},
        {"path_id": 2, "category_id": 2, "parent_category_id": None, "breadcrumb_path": "Home > Electronics"},
        {"path_id": 3, "category_id": 3, "parent_category_id": None, "breadcrumb_path": "Home > Fashion"},
        {"path_id": 4, "category_id": 4, "parent_category_id": None, "breadcrumb_path": "Home > Home & Living"}
    ]
    data["seo_meta_tags_registry"] = [
        {"seo_id": 1, "page_path": "/categories/beauty", "meta_title": "Luxury Skincare & Beauty - Black Friday 2026 | Lumière", "meta_description": "Shop luxury serums, creams and fragrance at 20% off during Black Week.", "canonical_url": "https://lumireshop.eu/categories/beauty"},
        {"seo_id": 2, "page_path": "/categories/electronics", "meta_title": "High-End Audio & Tech Deals | Lumière", "meta_description": "Explore premium drones, audio and displays.", "canonical_url": "https://lumireshop.eu/categories/electronics"}
    ]

    # -------------------------------------------------------------
    # DOMAIN P: Retail Physical Stores & POS (8 Tables)
    # -------------------------------------------------------------
    data["physical_store_locations"] = [
        {"store_id": 1, "store_name": "Lumière Champs-Élysées Flagship", "city": "Paris", "country": "France", "square_meters": 450, "is_open": True},
        {"store_id": 2, "store_name": "Lumière Kurfürstendamm Boutique", "city": "Berlin", "country": "Germany", "square_meters": 380, "is_open": True},
        {"store_id": 3, "store_name": "Lumière P.C. Hooftstraat", "city": "Amsterdam", "country": "Netherlands", "square_meters": 320, "is_open": True},
        {"store_id": 4, "store_name": "Lumière Serrano Flagship", "city": "Madrid", "country": "Spain", "square_meters": 400, "is_open": True}
    ]
    data["pos_terminal_registers"] = [
        {"register_id": 101, "store_id": 1, "terminal_model": "Verifone_P400", "ip_address": "192.168.1.101"},
        {"register_id": 102, "store_id": 1, "terminal_model": "Verifone_P400", "ip_address": "192.168.1.102"},
        {"register_id": 201, "store_id": 2, "terminal_model": "Ingenico_Lane5000", "ip_address": "192.168.2.101"},
        {"register_id": 301, "store_id": 3, "terminal_model": "Verifone_P400", "ip_address": "192.168.3.101"},
        {"register_id": 401, "store_id": 4, "terminal_model": "Ingenico_Lane5000", "ip_address": "192.168.4.101"}
    ]
    data["pos_store_transactions"] = [
        {"pos_transaction_id": 500000 + i, "store_id": (i%4)+1, "register_id": 101 + (i%4)*100, "cashier_employee_id": f"CASHIER_{i%10}", "total_amount_eur": round(random.uniform(45.0, 480.0), 2), "payment_type": random.choice(["Contactless_Card", "Cash", "GiftCard"]), "transacted_at": (nov23 + timedelta(minutes=i*15)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(1500)
    ]
    data["pos_transaction_items"] = [
        {"pos_item_id": 600000 + i, "pos_transaction_id": 500000 + (i%300), "product_id": 1001 + (i%50), "quantity": random.randint(1, 2), "unit_sale_price_eur": round(random.uniform(35.0, 250.0), 2)}
        for i in range(2500)
    ]
    data["click_and_collect_orders"] = [
        {"bopis_id": 7000 + i, "order_id": 1001 + (i%50), "store_id": (i%4)+1, "pickup_pin_code": f"{random.randint(1000, 9999)}", "status": random.choice(["ReadyForPickup", "Collected"]), "collected_at": (nov23 + timedelta(hours=i*2)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(80)
    ]
    data["store_inventory_levels"] = [
        {"store_stock_id": 8000 + i, "store_id": (i%4)+1, "product_id": 1001 + (i%50), "on_hand_quantity": random.randint(5, 50), "last_cycle_counted_at": nov23.strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(2000)
    ]
    data["store_employee_rosters"] = [
        {"roster_id": 9000 + i, "store_id": (i%4)+1, "employee_name": fake.name(), "shift_role": random.choice(["Senior_Stylist", "Cashier", "Store_Manager"]), "shift_date": (date(2026, 11, 23) + timedelta(days=i%5))}
        for i in range(200)
    ]
    data["store_cash_drawer_counts"] = [
        {"drawer_count_id": 10000 + i, "store_id": (i%4)+1, "register_id": 101 + (i%4)*100, "expected_cash_eur": 1250.0, "actual_counted_cash_eur": 1250.0, "counted_at": (nov23 + timedelta(days=i%5, hours=20)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        for i in range(100)
    ]

    # -------------------------------------------------------------
    # DOMAIN Q: Non-Production, Sandbox & QA (10 Tables)
    # -------------------------------------------------------------
    data["dev_customer_churn_feature_store"] = [
        {"user_id": 100 + i, "days_since_last_order": random.randint(1, 180), "order_frequency_90d": random.randint(1, 8), "total_spend_eur": round(random.uniform(50.0, 1500.0), 2), "predicted_churn_probability": round(random.uniform(0.05, 0.75), 3), "model_version": "v2.1_lightgbm_2026"}
        for i in range(1500)
    ]
    data["dev_product_embedding_vectors"] = [
        {"product_id": 1001 + (i%50), "embedding_model_name": "text-embedding-005", "vector_dimensions": 768, "vector_blob": f"[0.045, -0.128, 0.089, ... 768 dims for product {1000+i}]"}
        for i in range(150)
    ]
    data["qa_load_test_sessions_backup"] = [
        {"test_run_id": f"RUN-LOCUST-{i}", "virtual_user_id": f"vu_{i:04d}", "target_rps": 2500, "response_time_p95_ms": round(random.uniform(45.0, 180.0), 1), "executed_at": "2026-11-20T10:00:00Z"}
        for i in range(1200)
    ]
    data["qa_checkout_synthetic_fuzz_tests"] = [
        {"fuzz_id": 5000 + i, "payload_type": random.choice(["MalformedCard", "SQL_Injection_Test", "Null_Currency"]), "http_response_code": 400, "tested_at": "2026-11-21T14:00:00Z"}
        for i in range(300)
    ]
    data["sandbox_dynamic_pricing_sim_v1"] = [
        {"sim_id": 6000 + i, "product_id": 1001 + (i%50), "price_multiplier": round(random.uniform(0.90, 1.15), 2), "simulated_demand_units": random.randint(50, 500), "simulated_margin_eur": round(random.uniform(1500.0, 12000.0), 2)}
        for i in range(80)
    ]
    data["sandbox_search_ranking_ab_test"] = [
        {"experiment_id": "EXP-RANK-01", "search_query": "anti-aging serum", "algorithm_variant": random.choice(["Variant_A_BM25", "Variant_B_HybridVector"]), "ndcg_at_10_score": round(random.uniform(0.72, 0.89), 3)}
        for i in range(60)
    ]
    data["legacy_orders_2023_archive"] = [
        {"legacy_order_id": 2023000 + i, "order_date": date(2023, 11, 24), "total_amount_eur": round(random.uniform(45.0, 380.0), 2), "category_name": random.choice(["Beauty", "Electronics", "Fashion", "Home"])}
        for i in range(1500)
    ]
    data["legacy_products_deprecated"] = [
        {"legacy_product_id": 900 + i, "product_name": f"Vintage Edition Product {i}", "discontinued_year": random.choice([2022, 2023, 2024]), "last_sale_price_eur": round(random.uniform(25.0, 120.0), 2)}
        for i in range(300)
    ]
    data["test_fraud_mock_transactions"] = [
        {"mock_id": 8000 + i, "risk_score": round(random.uniform(10.0, 95.0), 1), "risk_decision": random.choice(["Approve", "Review", "Decline"]), "ip_country_mismatch": random.random() < 0.15}
        for i in range(300)
    ]
    data["test_carrier_webhook_payloads"] = [
        {"test_payload_id": str(uuid.uuid4()), "carrier_event": "PackagePickedUp", "raw_mock_json": json.dumps({"carrier": "DHL", "status": "IN_TRANSIT"}), "tested_at": "2026-11-22T08:00:00Z"}
        for i in range(300)
    ]


    _normalise_event_timestamps(data)

    print(f"\nGenerated total records in memory. Ingesting across {len(data)} tables in parallel...")
    from concurrent.futures import ThreadPoolExecutor
    
    def load_table(item):
        table_name, rows = item
        table_ref = f"{PROJECT_ID}.{DATASET_ID}.{table_name}"
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE
        )
        os.makedirs(LOCAL_TMP_DIR, exist_ok=True)
        tmp_file = os.path.join(LOCAL_TMP_DIR, f"{table_name}.json")
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, default=str) + "\n")
            with open(tmp_file, "rb") as f:
                load_job = client.load_table_from_file(f, table_ref, job_config=job_config)
                load_job.result()
            return table_name, len(rows), True, None
        except Exception as e:
            return table_name, len(rows), False, str(e)
        finally:
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except Exception:
                    pass

    ingested_count = 0
    total_rows = sum(len(rows) for rows in data.values())
    with ThreadPoolExecutor(max_workers=10) as executor:
        for t_name, count, success, err in executor.map(load_table, data.items()):
            if success:
                ingested_count += 1
                if ingested_count % 15 == 0 or ingested_count == len(data):
                    print(f"  Progress: {ingested_count}/{len(data)} tables ingested into BigQuery.")
            else:
                print(f"  ❌ Error loading `{t_name}`: {err}")

    print("\n" + "=" * 80)
    print(f"SYNTHETIC DATA INGESTION COMPLETE: {ingested_count}/{len(data)} Extended Tables Populated.")
    print(f"Total Extended Records Ingested: {total_rows:,} rows.")
    print("=" * 80)

if __name__ == "__main__":
    generate_all_extended_data()
