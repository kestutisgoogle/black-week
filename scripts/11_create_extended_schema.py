#!/usr/bin/env python3
"""
Phase 11: Extended Enterprise Warehouse Schema Creation Script
==============================================================
Provisions 115 extended enterprise domain tables in BigQuery (`ecommerce_dw`),
scaling total warehouse breadth to 140 tables to create an authentic, enterprise-grade
metadata search challenge for Google Cloud Knowledge Catalog.

Extended Domain Breakdown (Domains H through Q):
------------------------------------------------
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

Usage:
------
  python3 scripts/11_create_extended_schema.py
"""

import os
import sys
import subprocess
from google.cloud import bigquery
from google.oauth2 import credentials as oauth2_credentials


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

EXTENDED_TABLE_SCHEMAS = {
    # -------------------------------------------------------------
    # DOMAIN H: Staging & Raw Ingestion Tables (20 Tables)
    # -------------------------------------------------------------
    "stg_shopify_orders_raw": {
        "description": "Raw Shopify webhook JSON payloads capturing e-commerce checkout and order events.",
        "fields": [
            bigquery.SchemaField("payload_id", "STRING", mode="REQUIRED", description="Unique ingestion payload UUID"),
            bigquery.SchemaField("topic", "STRING", mode="REQUIRED", description="Shopify webhook topic name"),
            bigquery.SchemaField("raw_json", "STRING", mode="REQUIRED", description="Full unparsed JSON string payload"),
            bigquery.SchemaField("shop_domain", "STRING", mode="NULLABLE", description="Source storefront domain"),
            bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED", description="Timestamp when record was ingested into raw staging buffer")
        ]
    },
    "stg_shopify_products_raw": {
        "description": "Raw Shopify product synchronization JSON payloads from catalog webhooks.",
        "fields": [
            bigquery.SchemaField("payload_id", "STRING", mode="REQUIRED", description="Ingestion payload UUID"),
            bigquery.SchemaField("shopify_product_id", "INT64", mode="NULLABLE", description="Shopify product ID"),
            bigquery.SchemaField("raw_json", "STRING", mode="REQUIRED", description="Raw product JSON payload"),
            bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED", description="Ingestion timestamp")
        ]
    },
    "stg_shopify_customers_raw": {
        "description": "Raw Shopify customer account update webhook JSON payloads.",
        "fields": [
            bigquery.SchemaField("payload_id", "STRING", mode="REQUIRED", description="Ingestion payload UUID"),
            bigquery.SchemaField("shopify_customer_id", "INT64", mode="NULLABLE", description="Shopify customer ID"),
            bigquery.SchemaField("raw_json", "STRING", mode="REQUIRED", description="Raw customer account JSON payload"),
            bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED", description="Ingestion timestamp")
        ]
    },
    "stg_klaviyo_email_events_raw": {
        "description": "Raw event stream from Klaviyo marketing automation webhook (opens, clicks, bounces).",
        "fields": [
            bigquery.SchemaField("event_id", "STRING", mode="REQUIRED", description="Klaviyo event UUID"),
            bigquery.SchemaField("event_type", "STRING", mode="REQUIRED", description="Klaviyo event type (Opened Email, Clicked Email)"),
            bigquery.SchemaField("profile_id", "STRING", mode="NULLABLE", description="Klaviyo profile UUID"),
            bigquery.SchemaField("campaign_id", "STRING", mode="NULLABLE", description="Klaviyo campaign identifier"),
            bigquery.SchemaField("raw_payload", "STRING", mode="NULLABLE", description="Raw event JSON payload"),
            bigquery.SchemaField("timestamp", "TIMESTAMP", mode="REQUIRED", description="Event timestamp")
        ]
    },
    "stg_klaviyo_campaigns_raw": {
        "description": "Raw email campaign configuration dumps from Klaviyo REST API.",
        "fields": [
            bigquery.SchemaField("campaign_id", "STRING", mode="REQUIRED", description="Klaviyo campaign ID"),
            bigquery.SchemaField("name", "STRING", mode="REQUIRED", description="Campaign internal name"),
            bigquery.SchemaField("status", "STRING", mode="NULLABLE", description="Campaign send status"),
            bigquery.SchemaField("raw_json", "STRING", mode="NULLABLE", description="Raw campaign metadata JSON"),
            bigquery.SchemaField("synced_at", "TIMESTAMP", mode="REQUIRED", description="Sync timestamp")
        ]
    },
    "stg_stripe_payment_intents_raw": {
        "description": "Raw Stripe payment intent webhook JSON payloads for credit card authorizations.",
        "fields": [
            bigquery.SchemaField("intent_id", "STRING", mode="REQUIRED", description="Stripe payment intent ID (pi_...)"),
            bigquery.SchemaField("status", "STRING", mode="REQUIRED", description="Stripe status (succeeded, requires_payment_method)"),
            bigquery.SchemaField("amount_cents", "INT64", mode="REQUIRED", description="Transaction amount in cents"),
            bigquery.SchemaField("currency", "STRING", mode="REQUIRED", description="3-letter currency code"),
            bigquery.SchemaField("raw_payload", "STRING", mode="NULLABLE", description="Raw Stripe webhook payload JSON"),
            bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED", description="Stripe creation timestamp")
        ]
    },
    "stg_stripe_disputes_raw": {
        "description": "Raw Stripe credit card chargeback disputes and inquiry logs.",
        "fields": [
            bigquery.SchemaField("dispute_id", "STRING", mode="REQUIRED", description="Stripe dispute ID (dp_...)"),
            bigquery.SchemaField("charge_id", "STRING", mode="REQUIRED", description="Associated charge ID (ch_...)"),
            bigquery.SchemaField("amount_cents", "INT64", mode="REQUIRED", description="Disputed amount in cents"),
            bigquery.SchemaField("reason", "STRING", mode="NULLABLE", description="Dispute reason code (fraudulent, unrecognized)"),
            bigquery.SchemaField("status", "STRING", mode="REQUIRED", description="Dispute lifecycle status"),
            bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED", description="Creation timestamp")
        ]
    },
    "stg_zendesk_tickets_raw": {
        "description": "Raw customer support ticket JSON records extracted from Zendesk Support API.",
        "fields": [
            bigquery.SchemaField("ticket_id", "INT64", mode="REQUIRED", description="Zendesk ticket ID"),
            bigquery.SchemaField("subject", "STRING", mode="NULLABLE", description="Ticket subject line"),
            bigquery.SchemaField("status", "STRING", mode="REQUIRED", description="Ticket status (new, open, pending, solved, closed)"),
            bigquery.SchemaField("priority", "STRING", mode="NULLABLE", description="Ticket priority (low, normal, high, urgent)"),
            bigquery.SchemaField("raw_json", "STRING", mode="NULLABLE", description="Raw Zendesk ticket JSON dump"),
            bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED", description="Ticket creation timestamp")
        ]
    },
    "stg_zendesk_satisfaction_raw": {
        "description": "Raw customer satisfaction rating survey responses from Zendesk.",
        "fields": [
            bigquery.SchemaField("rating_id", "INT64", mode="REQUIRED", description="CSAT rating ID"),
            bigquery.SchemaField("ticket_id", "INT64", mode="REQUIRED", description="Associated Zendesk ticket ID"),
            bigquery.SchemaField("score", "STRING", mode="REQUIRED", description="CSAT score (good, bad, unoffered)"),
            bigquery.SchemaField("comment", "STRING", mode="NULLABLE", description="Customer verbatim comment"),
            bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED", description="Response timestamp")
        ]
    },
    "stg_google_ads_campaigns_raw": {
        "description": "Raw Google Ads campaign performance reporting extracts.",
        "fields": [
            bigquery.SchemaField("date", "DATE", mode="REQUIRED", description="Reporting date"),
            bigquery.SchemaField("campaign_id", "INT64", mode="REQUIRED", description="Google Ads campaign ID"),
            bigquery.SchemaField("campaign_name", "STRING", mode="REQUIRED", description="Campaign name"),
            bigquery.SchemaField("impressions", "INT64", mode="NULLABLE", description="Impression count"),
            bigquery.SchemaField("clicks", "INT64", mode="NULLABLE", description="Click count"),
            bigquery.SchemaField("cost_micros", "INT64", mode="NULLABLE", description="Cost in micros (EUR)"),
            bigquery.SchemaField("conversions", "FLOAT64", mode="NULLABLE", description="Conversion volume"),
            bigquery.SchemaField("synced_at", "TIMESTAMP", mode="REQUIRED", description="Batch sync timestamp")
        ]
    },
    "stg_google_ads_search_terms_raw": {
        "description": "Raw Google Search Ads query term performance extracts.",
        "fields": [
            bigquery.SchemaField("date", "DATE", mode="REQUIRED", description="Reporting date"),
            bigquery.SchemaField("search_term", "STRING", mode="REQUIRED", description="User search query string"),
            bigquery.SchemaField("campaign_id", "INT64", mode="REQUIRED", description="Associated campaign ID"),
            bigquery.SchemaField("clicks", "INT64", mode="NULLABLE", description="Clicks generated"),
            bigquery.SchemaField("impressions", "INT64", mode="NULLABLE", description="Impressions generated"),
            bigquery.SchemaField("cost_micros", "INT64", mode="NULLABLE", description="Cost in micros"),
            bigquery.SchemaField("synced_at", "TIMESTAMP", mode="REQUIRED", description="Batch sync timestamp")
        ]
    },
    "stg_meta_ad_insights_raw": {
        "description": "Raw Meta Marketing API adset insights JSON feeds.",
        "fields": [
            bigquery.SchemaField("date_start", "DATE", mode="REQUIRED", description="Reporting window start date"),
            bigquery.SchemaField("adset_id", "STRING", mode="REQUIRED", description="Meta adset ID"),
            bigquery.SchemaField("campaign_id", "STRING", mode="REQUIRED", description="Meta campaign ID"),
            bigquery.SchemaField("raw_json", "STRING", mode="NULLABLE", description="Raw Graph API response JSON"),
            bigquery.SchemaField("synced_at", "TIMESTAMP", mode="REQUIRED", description="Batch sync timestamp")
        ]
    },
    "stg_ga4_clickstream_raw": {
        "description": "Raw Google Analytics 4 export event records from BigQuery streaming export.",
        "fields": [
            bigquery.SchemaField("event_date", "STRING", mode="REQUIRED", description="GA4 event date (YYYYMMDD)"),
            bigquery.SchemaField("event_timestamp", "INT64", mode="REQUIRED", description="GA4 microsecond timestamp"),
            bigquery.SchemaField("event_name", "STRING", mode="REQUIRED", description="GA4 event name"),
            bigquery.SchemaField("user_pseudo_id", "STRING", mode="NULLABLE", description="GA4 pseudo anonymous client ID"),
            bigquery.SchemaField("raw_payload", "STRING", mode="NULLABLE", description="Raw GA4 record dump")
        ]
    },
    "stg_ga4_traffic_sources_raw": {
        "description": "Raw GA4 traffic acquisition attribution source records.",
        "fields": [
            bigquery.SchemaField("session_id", "STRING", mode="REQUIRED", description="GA4 session ID"),
            bigquery.SchemaField("source", "STRING", mode="NULLABLE", description="UTM source"),
            bigquery.SchemaField("medium", "STRING", mode="NULLABLE", description="UTM medium"),
            bigquery.SchemaField("campaign", "STRING", mode="NULLABLE", description="UTM campaign"),
            bigquery.SchemaField("synced_at", "TIMESTAMP", mode="REQUIRED", description="Sync timestamp")
        ]
    },
    "stg_sap_erp_inventory_feed_raw": {
        "description": "Raw nightly inventory stock feed export from SAP ERP enterprise system.",
        "fields": [
            bigquery.SchemaField("batch_id", "STRING", mode="REQUIRED", description="ERP sync batch identifier"),
            bigquery.SchemaField("material_number", "STRING", mode="REQUIRED", description="SAP material SKU ID"),
            bigquery.SchemaField("plant_id", "STRING", mode="REQUIRED", description="SAP warehouse plant code"),
            bigquery.SchemaField("unrestricted_stock_qty", "INT64", mode="REQUIRED", description="Physical stock available"),
            bigquery.SchemaField("synced_at", "TIMESTAMP", mode="REQUIRED", description="Sync timestamp")
        ]
    },
    "stg_sap_erp_purchase_orders_raw": {
        "description": "Raw SAP ERP procurement purchase order dumps.",
        "fields": [
            bigquery.SchemaField("po_number", "STRING", mode="REQUIRED", description="SAP purchase order document number"),
            bigquery.SchemaField("vendor_code", "STRING", mode="REQUIRED", description="SAP vendor code"),
            bigquery.SchemaField("raw_payload", "STRING", mode="NULLABLE", description="Raw procurement line items JSON"),
            bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED", description="PO creation date")
        ]
    },
    "stg_wms_shipments_raw": {
        "description": "Raw warehouse management system (WMS) carrier dispatch manifests.",
        "fields": [
            bigquery.SchemaField("shipment_id", "STRING", mode="REQUIRED", description="WMS shipment UUID"),
            bigquery.SchemaField("order_id", "INT64", mode="REQUIRED", description="Associated e-commerce order ID"),
            bigquery.SchemaField("tracking_number", "STRING", mode="NULLABLE", description="Carrier tracking code"),
            bigquery.SchemaField("carrier_code", "STRING", mode="NULLABLE", description="Carrier identifier (DHL, UPS)"),
            bigquery.SchemaField("manifest_status", "STRING", mode="REQUIRED", description="Manifest processing status"),
            bigquery.SchemaField("dispatched_at", "TIMESTAMP", mode="NULLABLE", description="Dispatch timestamp")
        ]
    },
    "stg_criteo_retargeting_raw": {
        "description": "Raw Criteo dynamic product retargeting daily performance reporting.",
        "fields": [
            bigquery.SchemaField("date", "DATE", mode="REQUIRED", description="Reporting date"),
            bigquery.SchemaField("campaign_id", "INT64", mode="REQUIRED", description="Criteo campaign ID"),
            bigquery.SchemaField("impressions", "INT64", mode="NULLABLE", description="Impressions delivered"),
            bigquery.SchemaField("clicks", "INT64", mode="NULLABLE", description="Clicks generated"),
            bigquery.SchemaField("cost_eur", "FLOAT64", mode="NULLABLE", description="Spend in EUR"),
            bigquery.SchemaField("synced_at", "TIMESTAMP", mode="REQUIRED", description="Sync timestamp")
        ]
    },
    "stg_trustpilot_reviews_raw": {
        "description": "Raw Trustpilot public customer review feed webhooks.",
        "fields": [
            bigquery.SchemaField("review_id", "STRING", mode="REQUIRED", description="Trustpilot review UUID"),
            bigquery.SchemaField("stars", "INT64", mode="REQUIRED", description="Star rating (1 to 5)"),
            bigquery.SchemaField("title", "STRING", mode="NULLABLE", description="Review title"),
            bigquery.SchemaField("content", "STRING", mode="NULLABLE", description="Review body text"),
            bigquery.SchemaField("verified_buyer", "BOOL", mode="REQUIRED", description="Verified purchase badge"),
            bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED", description="Review publication date")
        ]
    },
    "stg_adyen_settlements_raw": {
        "description": "Raw Adyen PSP settlement batch reconciliation ledger records.",
        "fields": [
            bigquery.SchemaField("batch_id", "STRING", mode="REQUIRED", description="Adyen settlement batch ID"),
            bigquery.SchemaField("merchant_account", "STRING", mode="REQUIRED", description="Adyen merchant account"),
            bigquery.SchemaField("gross_amount", "FLOAT64", mode="REQUIRED", description="Gross settled amount in EUR"),
            bigquery.SchemaField("fees_amount", "FLOAT64", mode="REQUIRED", description="PSP processing fee in EUR"),
            bigquery.SchemaField("net_amount", "FLOAT64", mode="REQUIRED", description="Net payout amount in EUR"),
            bigquery.SchemaField("settled_at", "TIMESTAMP", mode="REQUIRED", description="Settlement timestamp")
        ]
    },

    # -------------------------------------------------------------
    # DOMAIN I: Returns, Refunds & RMA Management (10 Tables)
    # -------------------------------------------------------------
    "product_returns": {
        "description": "Customer return merchandise authorization (RMA) requests and tracking.",
        "fields": [
            bigquery.SchemaField("return_id", "INT64", mode="REQUIRED", description="Unique RMA ID"),
            bigquery.SchemaField("order_id", "INT64", mode="REQUIRED", description="Foreign key to orders table"),
            bigquery.SchemaField("order_item_id", "INT64", mode="REQUIRED", description="Foreign key to order_items table"),
            bigquery.SchemaField("user_id", "INT64", mode="REQUIRED", description="Foreign key to users table"),
            bigquery.SchemaField("reason_code", "STRING", mode="REQUIRED", description="Return reason classification"),
            bigquery.SchemaField("status", "STRING", mode="REQUIRED", description="RMA status (Requested, Approved, Received, Inspected, Refunded)"),
            bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED", description="RMA creation timestamp")
        ]
    },
    "return_reasons_lookup": {
        "description": "Taxonomy lookup table of valid customer return reason codes and policy rules.",
        "fields": [
            bigquery.SchemaField("reason_code", "STRING", mode="REQUIRED", description="Reason code key"),
            bigquery.SchemaField("category", "STRING", mode="REQUIRED", description="High-level category (Quality, Fit, Preference, Logistics)"),
            bigquery.SchemaField("description", "STRING", mode="REQUIRED", description="Customer-facing description"),
            bigquery.SchemaField("requires_photo_proof", "BOOL", mode="REQUIRED", description="Whether photo upload is required")
        ]
    },
    "return_shipping_labels": {
        "description": "Prepaid reverse logistics parcel shipping labels generated for approved returns.",
        "fields": [
            bigquery.SchemaField("label_id", "STRING", mode="REQUIRED", description="Carrier label identifier"),
            bigquery.SchemaField("return_id", "INT64", mode="REQUIRED", description="Foreign key to product_returns"),
            bigquery.SchemaField("carrier_name", "STRING", mode="REQUIRED", description="Reverse logistics carrier (DHL, Colissimo)"),
            bigquery.SchemaField("tracking_number", "STRING", mode="REQUIRED", description="Carrier tracking number"),
            bigquery.SchemaField("label_cost_eur", "FLOAT64", mode="REQUIRED", description="Label shipping cost in EUR"),
            bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED", description="Creation timestamp")
        ]
    },
    "return_inspections": {
        "description": "Warehouse physical inspection results for returned merchandise.",
        "fields": [
            bigquery.SchemaField("inspection_id", "INT64", mode="REQUIRED", description="Inspection ID"),
            bigquery.SchemaField("return_id", "INT64", mode="REQUIRED", description="Foreign key to product_returns"),
            bigquery.SchemaField("inspector_id", "STRING", mode="REQUIRED", description="Warehouse quality inspector ID"),
            bigquery.SchemaField("item_condition", "STRING", mode="REQUIRED", description="Condition grade (Brand New, Open Box, Damaged, Defective)"),
            bigquery.SchemaField("disposition", "STRING", mode="REQUIRED", description="Warehouse disposition (Restock, Refurbish, Scrap, ReturnToVendor)"),
            bigquery.SchemaField("inspected_at", "TIMESTAMP", mode="REQUIRED", description="Inspection completion timestamp")
        ]
    },
    "warehouse_refurbishments": {
        "description": "Refurbishment and repackaging work orders for open-box returned inventory.",
        "fields": [
            bigquery.SchemaField("refurb_id", "INT64", mode="REQUIRED", description="Refurbishment job ID"),
            bigquery.SchemaField("product_id", "INT64", mode="REQUIRED", description="Foreign key to products table"),
            bigquery.SchemaField("labor_hours_spent", "FLOAT64", mode="REQUIRED", description="Labor hours spent repackaging"),
            bigquery.SchemaField("parts_cost_eur", "FLOAT64", mode="REQUIRED", description="Replacement packaging cost in EUR"),
            bigquery.SchemaField("status", "STRING", mode="REQUIRED", description="Job status (In_Progress, Completed)"),
            bigquery.SchemaField("completed_at", "TIMESTAMP", mode="NULLABLE", description="Completion timestamp")
        ]
    },
    "customer_refunds": {
        "description": "Processed financial refunds credited back to original payment methods.",
        "fields": [
            bigquery.SchemaField("refund_id", "INT64", mode="REQUIRED", description="Refund transaction ID"),
            bigquery.SchemaField("order_id", "INT64", mode="REQUIRED", description="Foreign key to orders table"),
            bigquery.SchemaField("return_id", "INT64", mode="NULLABLE", description="Foreign key to product_returns"),
            bigquery.SchemaField("refund_amount", "FLOAT64", mode="REQUIRED", description="Total refunded amount in EUR"),
            bigquery.SchemaField("payment_gateway", "STRING", mode="REQUIRED", description="Gateway used for refund (Stripe, PayPal, Adyen)"),
            bigquery.SchemaField("gateway_refund_id", "STRING", mode="NULLABLE", description="Gateway transaction reference"),
            bigquery.SchemaField("processed_at", "TIMESTAMP", mode="REQUIRED", description="Refund execution timestamp")
        ]
    },
    "store_credit_issuances": {
        "description": "Store credit and customer loyalty credit vouchers issued in lieu of cash refunds.",
        "fields": [
            bigquery.SchemaField("credit_id", "INT64", mode="REQUIRED", description="Store credit record ID"),
            bigquery.SchemaField("user_id", "INT64", mode="REQUIRED", description="Foreign key to users table"),
            bigquery.SchemaField("amount_eur", "FLOAT64", mode="REQUIRED", description="Credit value in EUR"),
            bigquery.SchemaField("balance_remaining", "FLOAT64", mode="REQUIRED", description="Remaining unredeemed credit"),
            bigquery.SchemaField("expires_at", "TIMESTAMP", mode="REQUIRED", description="Credit expiration date"),
            bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED", description="Issuance timestamp")
        ]
    },
    "warranty_claims": {
        "description": "Extended manufacturer warranty claims and defect replacement requests.",
        "fields": [
            bigquery.SchemaField("claim_id", "INT64", mode="REQUIRED", description="Warranty claim ID"),
            bigquery.SchemaField("product_id", "INT64", mode="REQUIRED", description="Foreign key to products table"),
            bigquery.SchemaField("user_id", "INT64", mode="REQUIRED", description="Foreign key to users table"),
            bigquery.SchemaField("claim_type", "STRING", mode="REQUIRED", description="Defect classification"),
            bigquery.SchemaField("status", "STRING", mode="REQUIRED", description="Claim resolution status"),
            bigquery.SchemaField("filed_at", "TIMESTAMP", mode="REQUIRED", description="Filing timestamp")
        ]
    },
    "replacement_orders": {
        "description": "Replacement orders shipped at zero cost for damaged or missing shipments.",
        "fields": [
            bigquery.SchemaField("replacement_id", "INT64", mode="REQUIRED", description="Replacement order ID"),
            bigquery.SchemaField("original_order_id", "INT64", mode="REQUIRED", description="Original order reference"),
            bigquery.SchemaField("new_order_id", "INT64", mode="REQUIRED", description="Replacement order ID"),
            bigquery.SchemaField("authorized_by", "STRING", mode="REQUIRED", description="Customer support supervisor ID"),
            bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED", description="Creation timestamp")
        ]
    },
    "restocking_fee_logs": {
        "description": "Restocking fees deducted on non-fault commercial customer returns.",
        "fields": [
            bigquery.SchemaField("fee_id", "INT64", mode="REQUIRED", description="Restocking fee record ID"),
            bigquery.SchemaField("return_id", "INT64", mode="REQUIRED", description="Foreign key to product_returns"),
            bigquery.SchemaField("fee_amount_eur", "FLOAT64", mode="REQUIRED", description="Deducted fee in EUR"),
            bigquery.SchemaField("deducted_at", "TIMESTAMP", mode="REQUIRED", description="Deduction timestamp")
        ]
    },

    # -------------------------------------------------------------
    # DOMAIN J: Customer Support, CRM & CSAT (12 Tables)
    # -------------------------------------------------------------
    "support_tickets": {
        "description": "Inbound customer support inquiries, priority triage, and resolution SLA tracking.",
        "fields": [
            bigquery.SchemaField("ticket_id", "INT64", mode="REQUIRED", description="Unique support ticket ID"),
            bigquery.SchemaField("user_id", "INT64", mode="NULLABLE", description="Foreign key to users table"),
            bigquery.SchemaField("order_id", "INT64", mode="NULLABLE", description="Associated order reference"),
            bigquery.SchemaField("channel", "STRING", mode="REQUIRED", description="Support contact channel (Email, Chat, Phone, Webform)"),
            bigquery.SchemaField("priority", "STRING", mode="REQUIRED", description="Ticket priority (Low, Medium, High, Urgent)"),
            bigquery.SchemaField("status", "STRING", mode="REQUIRED", description="Ticket status (New, Open, Pending, Resolved, Closed)"),
            bigquery.SchemaField("first_response_time_sec", "INT64", mode="NULLABLE", description="First agent response latency in seconds"),
            bigquery.SchemaField("resolution_time_sec", "INT64", mode="NULLABLE", description="Total ticket resolution time in seconds"),
            bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED", description="Ticket submission timestamp")
        ]
    },
    "ticket_messages": {
        "description": "Full communication message history and agent notes for support tickets.",
        "fields": [
            bigquery.SchemaField("message_id", "INT64", mode="REQUIRED", description="Message record ID"),
            bigquery.SchemaField("ticket_id", "INT64", mode="REQUIRED", description="Foreign key to support_tickets"),
            bigquery.SchemaField("sender_type", "STRING", mode="REQUIRED", description="Sender type (Customer, Agent, System)"),
            bigquery.SchemaField("sender_id", "STRING", mode="REQUIRED", description="Sender identifier"),
            bigquery.SchemaField("body", "STRING", mode="REQUIRED", description="Message body text"),
            bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED", description="Message timestamp")
        ]
    },
    "ticket_categories": {
        "description": "Categorical taxonomy of customer contact drivers and issue types.",
        "fields": [
            bigquery.SchemaField("category_id", "INT64", mode="REQUIRED", description="Category ID"),
            bigquery.SchemaField("name", "STRING", mode="REQUIRED", description="Category name (WhereIsMyOrder, ProductInquiry, BillingGlitch, ReturnRequest)"),
            bigquery.SchemaField("sla_target_minutes", "INT64", mode="REQUIRED", description="Target resolution SLA in minutes")
        ]
    },
    "support_agents": {
        "description": "Roster of customer support agents, skill tiers, and language capabilities.",
        "fields": [
            bigquery.SchemaField("agent_id", "STRING", mode="REQUIRED", description="Agent unique username ID"),
            bigquery.SchemaField("full_name", "STRING", mode="REQUIRED", description="Agent full name"),
            bigquery.SchemaField("tier", "STRING", mode="REQUIRED", description="Agent skill tier (Tier1_General, Tier2_Specialist, Tier3_Escalations)"),
            bigquery.SchemaField("primary_language", "STRING", mode="REQUIRED", description="Supported languages (FR, DE, EN, NL, ES, IT)")
        ]
    },
    "agent_worklog_shifts": {
        "description": "Support representative shift logs, active time, and handling volume.",
        "fields": [
            bigquery.SchemaField("shift_id", "INT64", mode="REQUIRED", description="Shift record ID"),
            bigquery.SchemaField("agent_id", "STRING", mode="REQUIRED", description="Foreign key to support_agents"),
            bigquery.SchemaField("shift_date", "DATE", mode="REQUIRED", description="Shift date"),
            bigquery.SchemaField("tickets_resolved", "INT64", mode="REQUIRED", description="Number of tickets resolved during shift"),
            bigquery.SchemaField("avg_handle_time_sec", "FLOAT64", mode="REQUIRED", description="Average handling time in seconds")
        ]
    },
    "csat_surveys": {
        "description": "Post-interaction customer satisfaction (CSAT) rating responses.",
        "fields": [
            bigquery.SchemaField("survey_id", "INT64", mode="REQUIRED", description="Survey ID"),
            bigquery.SchemaField("ticket_id", "INT64", mode="REQUIRED", description="Foreign key to support_tickets"),
            bigquery.SchemaField("score", "INT64", mode="REQUIRED", description="Satisfaction rating (1 to 5 stars)"),
            bigquery.SchemaField("verbatim_feedback", "STRING", mode="NULLABLE", description="Customer text feedback"),
            bigquery.SchemaField("submitted_at", "TIMESTAMP", mode="REQUIRED", description="Submission timestamp")
        ]
    },
    "nps_feedback_responses": {
        "description": "Quarterly Net Promoter Score (NPS) customer loyalty survey responses.",
        "fields": [
            bigquery.SchemaField("nps_id", "INT64", mode="REQUIRED", description="NPS response ID"),
            bigquery.SchemaField("user_id", "INT64", mode="REQUIRED", description="Foreign key to users table"),
            bigquery.SchemaField("score", "INT64", mode="REQUIRED", description="Likelihood to recommend (0 to 10)"),
            bigquery.SchemaField("feedback_text", "STRING", mode="NULLABLE", description="Qualitative feedback"),
            bigquery.SchemaField("survey_date", "DATE", mode="REQUIRED", description="Survey date")
        ]
    },
    "live_chat_sessions": {
        "description": "Real-time web live chat widget visitor sessions and queue wait metrics.",
        "fields": [
            bigquery.SchemaField("chat_session_id", "STRING", mode="REQUIRED", description="Chat session UUID"),
            bigquery.SchemaField("user_id", "INT64", mode="NULLABLE", description="Foreign key to users table"),
            bigquery.SchemaField("agent_id", "STRING", mode="NULLABLE", description="Assigned agent ID"),
            bigquery.SchemaField("wait_time_sec", "INT64", mode="REQUIRED", description="Visitor queue wait time in seconds"),
            bigquery.SchemaField("duration_sec", "INT64", mode="REQUIRED", description="Total chat duration in seconds"),
            bigquery.SchemaField("started_at", "TIMESTAMP", mode="REQUIRED", description="Chat start timestamp")
        ]
    },
    "live_chat_messages": {
        "description": "Transcript message records from real-time web live chat widget sessions.",
        "fields": [
            bigquery.SchemaField("message_id", "INT64", mode="REQUIRED", description="Message ID"),
            bigquery.SchemaField("chat_session_id", "STRING", mode="REQUIRED", description="Foreign key to live_chat_sessions"),
            bigquery.SchemaField("sender", "STRING", mode="REQUIRED", description="Sender (Visitor, Agent, Chatbot)"),
            bigquery.SchemaField("content", "STRING", mode="REQUIRED", description="Message text content"),
            bigquery.SchemaField("sent_at", "TIMESTAMP", mode="REQUIRED", description="Timestamp")
        ]
    },
    "call_center_recordings_metadata": {
        "description": "Inbound telephony voice call metadata, IVR routing choices, and call durations.",
        "fields": [
            bigquery.SchemaField("call_id", "STRING", mode="REQUIRED", description="Call recording UUID"),
            bigquery.SchemaField("customer_phone_hash", "STRING", mode="REQUIRED", description="Hashed customer phone number"),
            bigquery.SchemaField("ivr_selection", "STRING", mode="REQUIRED", description="IVR menu option chosen"),
            bigquery.SchemaField("duration_seconds", "INT64", mode="REQUIRED", description="Call duration in seconds"),
            bigquery.SchemaField("call_start_time", "TIMESTAMP", mode="REQUIRED", description="Call initiation timestamp")
        ]
    },
    "customer_escalations": {
        "description": "Executive and VIP customer escalations requiring senior managerial intervention.",
        "fields": [
            bigquery.SchemaField("escalation_id", "INT64", mode="REQUIRED", description="Escalation ID"),
            bigquery.SchemaField("ticket_id", "INT64", mode="REQUIRED", description="Foreign key to support_tickets"),
            bigquery.SchemaField("manager_id", "STRING", mode="REQUIRED", description="Assigned support director ID"),
            bigquery.SchemaField("escalation_reason", "STRING", mode="REQUIRED", description="Reason for escalation"),
            bigquery.SchemaField("financial_concession_eur", "FLOAT64", mode="NULLABLE", description="Goodwill coupon or compensation in EUR"),
            bigquery.SchemaField("escalated_at", "TIMESTAMP", mode="REQUIRED", description="Escalation timestamp")
        ]
    },
    "knowledge_base_articles": {
        "description": "Self-service customer help center FAQ articles, categories, and view analytics.",
        "fields": [
            bigquery.SchemaField("article_id", "INT64", mode="REQUIRED", description="Article ID"),
            bigquery.SchemaField("title", "STRING", mode="REQUIRED", description="Article title"),
            bigquery.SchemaField("category", "STRING", mode="REQUIRED", description="Knowledge base section"),
            bigquery.SchemaField("view_count", "INT64", mode="REQUIRED", description="Total page views"),
            bigquery.SchemaField("helpful_votes", "INT64", mode="REQUIRED", description="Positive user ratings"),
            bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED", description="Last edit timestamp")
        ]
    },

    # -------------------------------------------------------------
    # DOMAIN K: Supply Chain, Procurement & Warehousing Operations (14 Tables)
    # -------------------------------------------------------------
    "suppliers_master": {
        "description": "Master registry of suppliers, manufacturers, contact details, and commercial terms.",
        "fields": [
            bigquery.SchemaField("supplier_id", "INT64", mode="REQUIRED", description="Unique supplier ID"),
            bigquery.SchemaField("company_name", "STRING", mode="REQUIRED", description="Supplier legal company name"),
            bigquery.SchemaField("country_code", "STRING", mode="REQUIRED", description="Supplier country (FR, DE, IT, US, CN)"),
            bigquery.SchemaField("payment_terms", "STRING", mode="REQUIRED", description="Commercial payment terms (Net_30, Net_60)"),
            bigquery.SchemaField("is_active", "BOOL", mode="REQUIRED", description="Active vendor flag")
        ]
    },
    "purchase_orders": {
        "description": "Procurement purchase orders issued to manufacturers for inventory replenishment.",
        "fields": [
            bigquery.SchemaField("po_id", "INT64", mode="REQUIRED", description="Purchase order ID"),
            bigquery.SchemaField("supplier_id", "INT64", mode="REQUIRED", description="Foreign key to suppliers_master"),
            bigquery.SchemaField("destination_dc_id", "INT64", mode="REQUIRED", description="Destination distribution center (1: Paris Nord, 2: Rotterdam Port Hub)"),
            bigquery.SchemaField("status", "STRING", mode="REQUIRED", description="PO status (Draft, Issued, In_Transit, Received, Closed)"),
            bigquery.SchemaField("total_amount_eur", "FLOAT64", mode="REQUIRED", description="Total purchase order value in EUR"),
            bigquery.SchemaField("issued_date", "DATE", mode="REQUIRED", description="PO issue date"),
            bigquery.SchemaField("expected_delivery_date", "DATE", mode="REQUIRED", description="Expected arrival date")
        ]
    },
    "purchase_order_line_items": {
        "description": "Item-level SKU quantities and wholesale unit costs on purchase orders.",
        "fields": [
            bigquery.SchemaField("po_line_id", "INT64", mode="REQUIRED", description="PO line item record ID"),
            bigquery.SchemaField("po_id", "INT64", mode="REQUIRED", description="Foreign key to purchase_orders"),
            bigquery.SchemaField("product_id", "INT64", mode="REQUIRED", description="Foreign key to products table"),
            bigquery.SchemaField("ordered_quantity", "INT64", mode="REQUIRED", description="Quantity ordered"),
            bigquery.SchemaField("received_quantity", "INT64", mode="REQUIRED", description="Quantity received at dock"),
            bigquery.SchemaField("unit_cost_eur", "FLOAT64", mode="REQUIRED", description="Wholesale unit cost in EUR")
        ]
    },
    "supplier_lead_time_history": {
        "description": "Historical supplier production and freight lead times tracking delivery reliability.",
        "fields": [
            bigquery.SchemaField("history_id", "INT64", mode="REQUIRED", description="Lead time record ID"),
            bigquery.SchemaField("supplier_id", "INT64", mode="REQUIRED", description="Foreign key to suppliers_master"),
            bigquery.SchemaField("product_id", "INT64", mode="REQUIRED", description="Foreign key to products table"),
            bigquery.SchemaField("promised_lead_days", "INT64", mode="REQUIRED", description="Contractual lead time in days"),
            bigquery.SchemaField("actual_lead_days", "INT64", mode="REQUIRED", description="Actual observed fulfillment days"),
            bigquery.SchemaField("delivery_date", "DATE", mode="REQUIRED", description="Receipt date")
        ]
    },
    "supplier_quality_scorecards": {
        "description": "Monthly vendor quality ratings, defect rates, and on-time in-full (OTIF) metrics.",
        "fields": [
            bigquery.SchemaField("scorecard_id", "INT64", mode="REQUIRED", description="Scorecard record ID"),
            bigquery.SchemaField("supplier_id", "INT64", mode="REQUIRED", description="Foreign key to suppliers_master"),
            bigquery.SchemaField("month", "STRING", mode="REQUIRED", description="Scorecard month (YYYY-MM)"),
            bigquery.SchemaField("otif_delivery_pct", "FLOAT64", mode="REQUIRED", description="On-Time In-Full delivery rate percentage"),
            bigquery.SchemaField("defect_rate_pct", "FLOAT64", mode="REQUIRED", description="Quality inspection defect percentage"),
            bigquery.SchemaField("overall_score", "FLOAT64", mode="REQUIRED", description="Overall vendor rating score (0 to 100)")
        ]
    },
    "inbound_dock_appointments": {
        "description": "Distribution center inbound receiving dock appointment schedules and unloading logs.",
        "fields": [
            bigquery.SchemaField("appointment_id", "INT64", mode="REQUIRED", description="Dock appointment ID"),
            bigquery.SchemaField("dc_id", "INT64", mode="REQUIRED", description="Distribution center ID (1 or 2)"),
            bigquery.SchemaField("po_id", "INT64", mode="REQUIRED", description="Foreign key to purchase_orders"),
            bigquery.SchemaField("carrier_name", "STRING", mode="REQUIRED", description="Freight freight line"),
            bigquery.SchemaField("dock_door_number", "INT64", mode="REQUIRED", description="Assigned dock bay door"),
            bigquery.SchemaField("scheduled_time", "TIMESTAMP", mode="REQUIRED", description="Scheduled arrival timestamp"),
            bigquery.SchemaField("unloaded_time", "TIMESTAMP", mode="NULLABLE", description="Unloading completion timestamp")
        ]
    },
    "warehouse_zones": {
        "description": "Distribution center physical warehouse climate and temperature storage zones.",
        "fields": [
            bigquery.SchemaField("zone_id", "INT64", mode="REQUIRED", description="Zone ID"),
            bigquery.SchemaField("dc_id", "INT64", mode="REQUIRED", description="Distribution center reference"),
            bigquery.SchemaField("zone_name", "STRING", mode="REQUIRED", description="Zone name (Ambient_Luxury, Temperature_Controlled, Secure_Electronics)"),
            bigquery.SchemaField("temperature_celsius", "FLOAT64", mode="REQUIRED", description="Target temperature in Celsius")
        ]
    },
    "warehouse_aisles_and_racks": {
        "description": "Physical storage bin coordinates (aisle, rack, shelf) across fulfillment centers.",
        "fields": [
            bigquery.SchemaField("bin_id", "STRING", mode="REQUIRED", description="Storage bin barcode (e.g. A-12-03-B)"),
            bigquery.SchemaField("zone_id", "INT64", mode="REQUIRED", description="Foreign key to warehouse_zones"),
            bigquery.SchemaField("aisle_number", "INT64", mode="REQUIRED", description="Aisle number"),
            bigquery.SchemaField("rack_level", "INT64", mode="REQUIRED", description="Vertical shelf level"),
            bigquery.SchemaField("max_weight_kg", "FLOAT64", mode="REQUIRED", description="Maximum weight capacity in kg")
        ]
    },
    "pallet_inventory_locations": {
        "description": "Pallet-level putaway locations, license plate numbers (LPN), and RFID barcodes.",
        "fields": [
            bigquery.SchemaField("pallet_lpn", "STRING", mode="REQUIRED", description="License plate number LPN barcode"),
            bigquery.SchemaField("bin_id", "STRING", mode="REQUIRED", description="Current storage bin location"),
            bigquery.SchemaField("product_id", "INT64", mode="REQUIRED", description="Stored product ID"),
            bigquery.SchemaField("quantity_on_pallet", "INT64", mode="REQUIRED", description="Units on pallet"),
            bigquery.SchemaField("last_scanned_at", "TIMESTAMP", mode="REQUIRED", description="Last RFID scan timestamp")
        ]
    },
    "warehouse_labor_shifts": {
        "description": "Warehouse picker, packer, and forklift staff roster shifts and productivity logs.",
        "fields": [
            bigquery.SchemaField("shift_id", "INT64", mode="REQUIRED", description="Labor shift ID"),
            bigquery.SchemaField("dc_id", "INT64", mode="REQUIRED", description="Distribution center reference"),
            bigquery.SchemaField("employee_id", "STRING", mode="REQUIRED", description="Warehouse operator ID"),
            bigquery.SchemaField("role", "STRING", mode="REQUIRED", description="Role (Picker, Packer, Stager, Supervisor)"),
            bigquery.SchemaField("shift_start", "TIMESTAMP", mode="REQUIRED", description="Shift clock-in"),
            bigquery.SchemaField("shift_end", "TIMESTAMP", mode="REQUIRED", description="Shift clock-out"),
            bigquery.SchemaField("units_picked", "INT64", mode="REQUIRED", description="Total units picked during shift")
        ]
    },
    "forklift_telemetry_logs": {
        "description": "Automated guided vehicle (AGV) and electric forklift battery and movement telemetry.",
        "fields": [
            bigquery.SchemaField("telemetry_id", "INT64", mode="REQUIRED", description="Telemetry log ID"),
            bigquery.SchemaField("equipment_id", "STRING", mode="REQUIRED", description="Forklift asset tag"),
            bigquery.SchemaField("battery_pct", "INT64", mode="REQUIRED", description="Battery state of charge percentage"),
            bigquery.SchemaField("odometer_km", "FLOAT64", mode="REQUIRED", description="Cumulative distance traveled"),
            bigquery.SchemaField("recorded_at", "TIMESTAMP", mode="REQUIRED", description="Telemetry timestamp")
        ]
    },
    "cross_dock_transfer_orders": {
        "description": "Inter-facility transfer shipments moving stock between the Paris Nord and Rotterdam Port fulfillment hubs.",
        "fields": [
            bigquery.SchemaField("transfer_id", "INT64", mode="REQUIRED", description="Transfer shipment ID"),
            bigquery.SchemaField("source_dc_id", "INT64", mode="REQUIRED", description="Origin DC"),
            bigquery.SchemaField("destination_dc_id", "INT64", mode="REQUIRED", description="Destination DC"),
            bigquery.SchemaField("product_id", "INT64", mode="REQUIRED", description="Transferred product SKU"),
            bigquery.SchemaField("quantity", "INT64", mode="REQUIRED", description="Units transferred"),
            bigquery.SchemaField("shipped_at", "TIMESTAMP", mode="REQUIRED", description="Dispatch timestamp"),
            bigquery.SchemaField("received_at", "TIMESTAMP", mode="NULLABLE", description="Receipt timestamp")
        ]
    },
    "freight_carrier_contracts": {
        "description": "Negotiated parcel and freight shipping contracts, fuel surcharges, and rate cards.",
        "fields": [
            bigquery.SchemaField("contract_id", "STRING", mode="REQUIRED", description="Carrier contract code"),
            bigquery.SchemaField("carrier_name", "STRING", mode="REQUIRED", description="Carrier name (DHL, UPS, FedEx, DPD)"),
            bigquery.SchemaField("base_rate_per_kg_eur", "FLOAT64", mode="REQUIRED", description="Base shipping rate per kg"),
            bigquery.SchemaField("fuel_surcharge_pct", "FLOAT64", mode="REQUIRED", description="Current fuel surcharge index percentage"),
            bigquery.SchemaField("valid_until", "DATE", mode="REQUIRED", description="Contract expiration date")
        ]
    },
    "customs_and_duties_declarations": {
        "description": "Cross-border import/export customs tariff classifications and duty assessments.",
        "fields": [
            bigquery.SchemaField("declaration_id", "STRING", mode="REQUIRED", description="Customs declaration reference number"),
            bigquery.SchemaField("po_id", "INT64", mode="REQUIRED", description="Foreign key to purchase_orders"),
            bigquery.SchemaField("hs_tariff_code", "STRING", mode="REQUIRED", description="Harmonized System HS tariff code"),
            bigquery.SchemaField("duty_amount_eur", "FLOAT64", mode="REQUIRED", description="Assessed customs duty in EUR"),
            bigquery.SchemaField("cleared_date", "DATE", mode="REQUIRED", description="Customs clearance date")
        ]
    },

    # -------------------------------------------------------------
    # DOMAIN L: Finance, General Ledger, Tax & Accounting (12 Tables)
    # -------------------------------------------------------------
    "chart_of_accounts": {
        "description": "Standard corporate financial chart of accounts hierarchy (Assets, Liabilities, Equity, Revenue, COGS, Opex).",
        "fields": [
            bigquery.SchemaField("account_number", "STRING", mode="REQUIRED", description="GL account number (e.g. 1000, 4000, 5000)"),
            bigquery.SchemaField("account_name", "STRING", mode="REQUIRED", description="Account title (Cash, AccountsReceivable, SalesRevenue, MarketingOpex)"),
            bigquery.SchemaField("account_type", "STRING", mode="REQUIRED", description="Account classification (Asset, Liability, Equity, Revenue, Expense)"),
            bigquery.SchemaField("is_active", "BOOL", mode="REQUIRED", description="Active account flag")
        ]
    },
    "general_ledger_journal_entries": {
        "description": "Double-entry general ledger accounting journal transaction headers.",
        "fields": [
            bigquery.SchemaField("journal_id", "INT64", mode="REQUIRED", description="Journal entry identifier"),
            bigquery.SchemaField("journal_date", "DATE", mode="REQUIRED", description="Accounting posting date"),
            bigquery.SchemaField("description", "STRING", mode="REQUIRED", description="Journal memo description"),
            bigquery.SchemaField("source_module", "STRING", mode="REQUIRED", description="Source subledger (Sales, AP, AR, Payroll, Cash)"),
            bigquery.SchemaField("posted_by", "STRING", mode="REQUIRED", description="Finance accountant ID"),
            bigquery.SchemaField("posted_at", "TIMESTAMP", mode="REQUIRED", description="Posting timestamp")
        ]
    },
    "gl_journal_lines": {
        "description": "Debit and credit balancing line entries on general ledger journal vouchers.",
        "fields": [
            bigquery.SchemaField("line_id", "INT64", mode="REQUIRED", description="Journal line record ID"),
            bigquery.SchemaField("journal_id", "INT64", mode="REQUIRED", description="Foreign key to general_ledger_journal_entries"),
            bigquery.SchemaField("account_number", "STRING", mode="REQUIRED", description="Foreign key to chart_of_accounts"),
            bigquery.SchemaField("debit_amount_eur", "FLOAT64", mode="REQUIRED", description="Debit amount in EUR"),
            bigquery.SchemaField("credit_amount_eur", "FLOAT64", mode="REQUIRED", description="Credit amount in EUR")
        ]
    },
    "accounts_payable_invoices": {
        "description": "Incoming vendor bills and supplier invoices received for inventory and services.",
        "fields": [
            bigquery.SchemaField("invoice_id", "INT64", mode="REQUIRED", description="AP invoice record ID"),
            bigquery.SchemaField("vendor_name", "STRING", mode="REQUIRED", description="Vendor company name"),
            bigquery.SchemaField("invoice_number", "STRING", mode="REQUIRED", description="Vendor invoice number"),
            bigquery.SchemaField("invoice_amount_eur", "FLOAT64", mode="REQUIRED", description="Total invoice amount in EUR"),
            bigquery.SchemaField("payment_due_date", "DATE", mode="REQUIRED", description="Due date for payment"),
            bigquery.SchemaField("status", "STRING", mode="REQUIRED", description="Status (PendingApproval, Approved, Paid)"),
            bigquery.SchemaField("received_date", "DATE", mode="REQUIRED", description="Receipt date")
        ]
    },
    "accounts_payable_disbursements": {
        "description": "Outgoing corporate wire and SEPA bank payment disbursements paid to vendors.",
        "fields": [
            bigquery.SchemaField("disbursement_id", "INT64", mode="REQUIRED", description="Payment voucher ID"),
            bigquery.SchemaField("invoice_id", "INT64", mode="REQUIRED", description="Foreign key to accounts_payable_invoices"),
            bigquery.SchemaField("amount_paid_eur", "FLOAT64", mode="REQUIRED", description="Amount paid in EUR"),
            bigquery.SchemaField("payment_method", "STRING", mode="REQUIRED", description="Disbursement method (SEPA_Wire, Corporate_Card)"),
            bigquery.SchemaField("paid_at", "TIMESTAMP", mode="REQUIRED", description="Disbursement timestamp")
        ]
    },
    "accounts_receivable_invoices": {
        "description": "Outgoing B2B commercial invoices and corporate billing schedules.",
        "fields": [
            bigquery.SchemaField("ar_invoice_id", "INT64", mode="REQUIRED", description="AR invoice record ID"),
            bigquery.SchemaField("corporate_client_name", "STRING", mode="REQUIRED", description="B2B client name"),
            bigquery.SchemaField("billed_amount_eur", "FLOAT64", mode="REQUIRED", description="Billed amount in EUR"),
            bigquery.SchemaField("due_date", "DATE", mode="REQUIRED", description="Payment due date"),
            bigquery.SchemaField("is_settled", "BOOL", mode="REQUIRED", description="Settlement flag"),
            bigquery.SchemaField("issued_date", "DATE", mode="REQUIRED", description="Invoice issue date")
        ]
    },
    "bank_account_reconciliation": {
        "description": "Daily corporate treasury bank account statement cash reconciliation audits.",
        "fields": [
            bigquery.SchemaField("reconciliation_id", "INT64", mode="REQUIRED", description="Reconciliation ID"),
            bigquery.SchemaField("bank_name", "STRING", mode="REQUIRED", description="Financial institution (BNP_Paribas, Deutsche_Bank)"),
            bigquery.SchemaField("statement_date", "DATE", mode="REQUIRED", description="Statement date"),
            bigquery.SchemaField("opening_balance_eur", "FLOAT64", mode="REQUIRED", description="Opening cash balance in EUR"),
            bigquery.SchemaField("closing_balance_eur", "FLOAT64", mode="REQUIRED", description="Closing cash balance in EUR"),
            bigquery.SchemaField("variance_eur", "FLOAT64", mode="REQUIRED", description="Unreconciled variance in EUR")
        ]
    },
    "vat_tax_jurisdictions": {
        "description": "Standard European Union VAT rates and cross-border digital service tax rules.",
        "fields": [
            bigquery.SchemaField("country_code", "STRING", mode="REQUIRED", description="2-letter ISO country code"),
            bigquery.SchemaField("country_name", "STRING", mode="REQUIRED", description="Country name"),
            bigquery.SchemaField("standard_vat_rate_pct", "FLOAT64", mode="REQUIRED", description="Standard VAT rate percentage"),
            bigquery.SchemaField("reduced_vat_rate_pct", "FLOAT64", mode="REQUIRED", description="Reduced VAT rate percentage (e.g. food/books)")
        ]
    },
    "vat_period_filing_reports": {
        "description": "Monthly One-Stop-Shop (OSS) European VAT return filing summaries.",
        "fields": [
            bigquery.SchemaField("filing_id", "STRING", mode="REQUIRED", description="Tax filing period ID (e.g. OSS-2026-Q4)"),
            bigquery.SchemaField("country_code", "STRING", mode="REQUIRED", description="Destination consumption country"),
            bigquery.SchemaField("taxable_sales_eur", "FLOAT64", mode="REQUIRED", description="Net taxable sales in EUR"),
            bigquery.SchemaField("vat_collected_eur", "FLOAT64", mode="REQUIRED", description="Total output VAT collected"),
            bigquery.SchemaField("filed_at", "TIMESTAMP", mode="REQUIRED", description="Tax authority filing timestamp")
        ]
    },
    "currency_exchange_rates_daily": {
        "description": "Daily European Central Bank (ECB) foreign exchange reference rates against EUR.",
        "fields": [
            bigquery.SchemaField("date", "DATE", mode="REQUIRED", description="FX date"),
            bigquery.SchemaField("currency_code", "STRING", mode="REQUIRED", description="Target currency (USD, GBP, CHF, PLN, SEK)"),
            bigquery.SchemaField("rate_to_eur", "FLOAT64", mode="REQUIRED", description="Units of foreign currency per 1 EUR"),
            bigquery.SchemaField("fetched_at", "TIMESTAMP", mode="REQUIRED", description="Sync timestamp")
        ]
    },
    "intercompany_transfer_pricing": {
        "description": "Intercompany cross-entity royalty and management fee transfer pricing schedules.",
        "fields": [
            bigquery.SchemaField("schedule_id", "STRING", mode="REQUIRED", description="Transfer pricing agreement ID"),
            bigquery.SchemaField("source_entity", "STRING", mode="REQUIRED", description="Charging legal entity"),
            bigquery.SchemaField("receiving_entity", "STRING", mode="REQUIRED", description="Receiving legal entity"),
            bigquery.SchemaField("markup_percentage", "FLOAT64", mode="REQUIRED", description="Cost-plus markup percentage"),
            bigquery.SchemaField("effective_year", "INT64", mode="REQUIRED", description="Tax fiscal year")
        ]
    },
    "payment_gateway_fee_schedules": {
        "description": "Payment service provider (PSP) contractual interchange and fixed transaction fee rate cards.",
        "fields": [
            bigquery.SchemaField("gateway_name", "STRING", mode="REQUIRED", description="PSP name (Stripe, PayPal, Adyen, ApplePay)"),
            bigquery.SchemaField("interchange_pct", "FLOAT64", mode="REQUIRED", description="Variable percentage transaction fee"),
            bigquery.SchemaField("fixed_fee_eur", "FLOAT64", mode="REQUIRED", description="Fixed per-transaction fee in EUR"),
            bigquery.SchemaField("effective_date", "DATE", mode="REQUIRED", description="Effective start date")
        ]
    },

    # -------------------------------------------------------------
    # DOMAIN M: Loyalty, Customer Retention & Rewards (10 Tables)
    # -------------------------------------------------------------
    "loyalty_members": {
        "description": "Registered customer loyalty club accounts, membership tiers, and total lifetime spend.",
        "fields": [
            bigquery.SchemaField("membership_id", "INT64", mode="REQUIRED", description="Loyalty membership ID"),
            bigquery.SchemaField("user_id", "INT64", mode="REQUIRED", description="Foreign key to users table"),
            bigquery.SchemaField("current_tier", "STRING", mode="REQUIRED", description="Current tier (Bronze, Silver, Gold, Platinum)"),
            bigquery.SchemaField("total_points_balance", "INT64", mode="REQUIRED", description="Current redeemable points balance"),
            bigquery.SchemaField("joined_at", "TIMESTAMP", mode="REQUIRED", description="Loyalty program join date")
        ]
    },
    "loyalty_tier_definitions": {
        "description": "Loyalty tier threshold rules, annual qualifying spend requirements, and reward multipliers.",
        "fields": [
            bigquery.SchemaField("tier_name", "STRING", mode="REQUIRED", description="Tier name (Bronze, Silver, Gold, Platinum)"),
            bigquery.SchemaField("qualifying_annual_spend_eur", "FLOAT64", mode="REQUIRED", description="Minimum annual spend in EUR to qualify"),
            bigquery.SchemaField("points_multiplier", "FLOAT64", mode="REQUIRED", description="Point earning multiplier per 1 EUR spent"),
            bigquery.SchemaField("free_shipping_threshold_eur", "FLOAT64", mode="REQUIRED", description="Free shipping threshold for tier")
        ]
    },
    "loyalty_points_ledger": {
        "description": "Granular ledger of loyalty point accruals, order rewards, and point expirations.",
        "fields": [
            bigquery.SchemaField("ledger_id", "INT64", mode="REQUIRED", description="Ledger transaction ID"),
            bigquery.SchemaField("user_id", "INT64", mode="REQUIRED", description="Foreign key to users table"),
            bigquery.SchemaField("order_id", "INT64", mode="NULLABLE", description="Associated order ID"),
            bigquery.SchemaField("points_delta", "INT64", mode="REQUIRED", description="Points accrued (positive) or deducted (negative)"),
            bigquery.SchemaField("transaction_type", "STRING", mode="REQUIRED", description="Type (PurchaseAccrual, RewardRedemption, BirthdayBonus, Expiration)"),
            bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED", description="Transaction timestamp")
        ]
    },
    "loyalty_reward_redemptions": {
        "description": "History of loyalty points redeemed for store discount vouchers and gift catalog items.",
        "fields": [
            bigquery.SchemaField("redemption_id", "INT64", mode="REQUIRED", description="Redemption record ID"),
            bigquery.SchemaField("user_id", "INT64", mode="REQUIRED", description="Foreign key to users table"),
            bigquery.SchemaField("points_spent", "INT64", mode="REQUIRED", description="Points redeemed"),
            bigquery.SchemaField("reward_type", "STRING", mode="REQUIRED", description="Reward type (10EUR_Voucher, Free_Sample_Kit, Free_Express_Shipping)"),
            bigquery.SchemaField("redeemed_at", "TIMESTAMP", mode="REQUIRED", description="Redemption timestamp")
        ]
    },
    "discount_coupons_master": {
        "description": "Master registry of promotional discount codes, validity windows, and usage caps.",
        "fields": [
            bigquery.SchemaField("coupon_id", "INT64", mode="REQUIRED", description="Coupon record ID"),
            bigquery.SchemaField("promo_code", "STRING", mode="REQUIRED", description="Customer-facing voucher string (e.g. WELCOME10, BLACKFRIDAY20)"),
            bigquery.SchemaField("discount_type", "STRING", mode="REQUIRED", description="Discount format (Percentage, FixedAmount, FreeShipping)"),
            bigquery.SchemaField("discount_value", "FLOAT64", mode="REQUIRED", description="Discount value (e.g. 20.0 for 20% or 10.0 for €10)"),
            bigquery.SchemaField("min_order_amount_eur", "FLOAT64", mode="REQUIRED", description="Minimum qualifying basket total in EUR"),
            bigquery.SchemaField("is_active", "BOOL", mode="REQUIRED", description="Active promo flag"),
            bigquery.SchemaField("valid_from", "TIMESTAMP", mode="REQUIRED", description="Start timestamp"),
            bigquery.SchemaField("valid_to", "TIMESTAMP", mode="REQUIRED", description="Expiration timestamp")
        ]
    },
    "coupon_redemption_audit": {
        "description": "Transaction-level audit logs of discount coupons applied during checkout.",
        "fields": [
            bigquery.SchemaField("audit_id", "INT64", mode="REQUIRED", description="Audit record ID"),
            bigquery.SchemaField("order_id", "INT64", mode="REQUIRED", description="Foreign key to orders table"),
            bigquery.SchemaField("coupon_id", "INT64", mode="REQUIRED", description="Foreign key to discount_coupons_master"),
            bigquery.SchemaField("user_id", "INT64", mode="REQUIRED", description="Foreign key to users table"),
            bigquery.SchemaField("discount_applied_eur", "FLOAT64", mode="REQUIRED", description="Actual discount amount deducted in EUR"),
            bigquery.SchemaField("applied_at", "TIMESTAMP", mode="REQUIRED", description="Checkout application timestamp")
        ]
    },
    "referral_program_invites": {
        "description": "Member-get-a-member referral invitation links generated by existing customers.",
        "fields": [
            bigquery.SchemaField("invite_id", "INT64", mode="REQUIRED", description="Referral invite ID"),
            bigquery.SchemaField("referrer_user_id", "INT64", mode="REQUIRED", description="Inviting user ID"),
            bigquery.SchemaField("referral_code", "STRING", mode="REQUIRED", description="Unique referral token"),
            bigquery.SchemaField("friend_email_hash", "STRING", mode="REQUIRED", description="Hashed recipient email"),
            bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED", description="Invitation generation timestamp")
        ]
    },
    "referral_reward_claims": {
        "description": "Verified successful referral friend purchases and reward payouts credited to referrers.",
        "fields": [
            bigquery.SchemaField("claim_id", "INT64", mode="REQUIRED", description="Claim record ID"),
            bigquery.SchemaField("invite_id", "INT64", mode="REQUIRED", description="Foreign key to referral_program_invites"),
            bigquery.SchemaField("referred_order_id", "INT64", mode="REQUIRED", description="First purchase order ID of referred friend"),
            bigquery.SchemaField("reward_credit_eur", "FLOAT64", mode="REQUIRED", description="Referrer bonus credit amount in EUR"),
            bigquery.SchemaField("claimed_at", "TIMESTAMP", mode="REQUIRED", description="Reward claim timestamp")
        ]
    },
    "gift_card_master": {
        "description": "Digital and physical gift cards issued with unique encrypted card codes.",
        "fields": [
            bigquery.SchemaField("card_id", "INT64", mode="REQUIRED", description="Gift card ID"),
            bigquery.SchemaField("code_hash", "STRING", mode="REQUIRED", description="Encrypted gift card code hash"),
            bigquery.SchemaField("initial_balance_eur", "FLOAT64", mode="REQUIRED", description="Initial card balance in EUR"),
            bigquery.SchemaField("current_balance_eur", "FLOAT64", mode="REQUIRED", description="Remaining card balance in EUR"),
            bigquery.SchemaField("is_active", "BOOL", mode="REQUIRED", description="Active card flag"),
            bigquery.SchemaField("purchaser_user_id", "INT64", mode="NULLABLE", description="Purchaser user ID"),
            bigquery.SchemaField("issued_at", "TIMESTAMP", mode="REQUIRED", description="Issuance timestamp")
        ]
    },
    "gift_card_transactions": {
        "description": "Gift card balance redemptions, debit charges, and reload history.",
        "fields": [
            bigquery.SchemaField("transaction_id", "INT64", mode="REQUIRED", description="Gift card transaction ID"),
            bigquery.SchemaField("card_id", "INT64", mode="REQUIRED", description="Foreign key to gift_card_master"),
            bigquery.SchemaField("order_id", "INT64", mode="NULLABLE", description="Associated order ID"),
            bigquery.SchemaField("amount_eur", "FLOAT64", mode="REQUIRED", description="Transaction debit or credit amount"),
            bigquery.SchemaField("transacted_at", "TIMESTAMP", mode="REQUIRED", description="Transaction timestamp")
        ]
    },

    # -------------------------------------------------------------
    # DOMAIN N: Lifecycle Marketing, Email, SMS & Push (10 Tables)
    # -------------------------------------------------------------
    "email_campaign_templates": {
        "description": "Responsive HTML email marketing templates, layout blocks, and subject line variants.",
        "fields": [
            bigquery.SchemaField("template_id", "INT64", mode="REQUIRED", description="Template record ID"),
            bigquery.SchemaField("template_name", "STRING", mode="REQUIRED", description="Template title (e.g. BlackFriday_Vip_EarlyAccess, AbandonedCart_V2)"),
            bigquery.SchemaField("subject_line_variant_a", "STRING", mode="REQUIRED", description="Subject line variant A"),
            bigquery.SchemaField("subject_line_variant_b", "STRING", mode="NULLABLE", description="Subject line variant B for A/B testing"),
            bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED", description="Creation timestamp")
        ]
    },
    "email_send_queue_logs": {
        "description": "Outbound promotional and transactional email dispatch queue telemetry.",
        "fields": [
            bigquery.SchemaField("send_id", "INT64", mode="REQUIRED", description="Email dispatch record ID"),
            bigquery.SchemaField("user_id", "INT64", mode="REQUIRED", description="Foreign key to users table"),
            bigquery.SchemaField("template_id", "INT64", mode="REQUIRED", description="Foreign key to email_campaign_templates"),
            bigquery.SchemaField("status", "STRING", mode="REQUIRED", description="Dispatch status (Sent, Delivered, Bounced, Opened, Clicked)"),
            bigquery.SchemaField("sent_at", "TIMESTAMP", mode="REQUIRED", description="Dispatch timestamp")
        ]
    },
    "email_bounces_and_complaints": {
        "description": "Email deliverability hard bounces, soft bounces, and spam complaint logs.",
        "fields": [
            bigquery.SchemaField("bounce_id", "INT64", mode="REQUIRED", description="Bounce record ID"),
            bigquery.SchemaField("user_id", "INT64", mode="REQUIRED", description="User ID"),
            bigquery.SchemaField("bounce_type", "STRING", mode="REQUIRED", description="Type (HardBounce_BadMailbox, SoftBounce_Quota, SpamComplaint)"),
            bigquery.SchemaField("recorded_at", "TIMESTAMP", mode="REQUIRED", description="Timestamp")
        ]
    },
    "sms_marketing_broadcasts": {
        "description": "SMS marketing broadcast campaigns, promotional text copy, and target audience segments.",
        "fields": [
            bigquery.SchemaField("sms_campaign_id", "INT64", mode="REQUIRED", description="SMS campaign ID"),
            bigquery.SchemaField("campaign_name", "STRING", mode="REQUIRED", description="SMS campaign name"),
            bigquery.SchemaField("message_copy", "STRING", mode="REQUIRED", description="SMS message text body"),
            bigquery.SchemaField("target_segment", "STRING", mode="REQUIRED", description="Target customer audience segment"),
            bigquery.SchemaField("dispatched_at", "TIMESTAMP", mode="REQUIRED", description="Broadcast dispatch timestamp")
        ]
    },
    "sms_delivery_receipts": {
        "description": "Telco carrier SMS delivery receipts, network latency, and delivery statuses.",
        "fields": [
            bigquery.SchemaField("receipt_id", "INT64", mode="REQUIRED", description="Receipt ID"),
            bigquery.SchemaField("sms_campaign_id", "INT64", mode="REQUIRED", description="Foreign key to sms_marketing_broadcasts"),
            bigquery.SchemaField("user_id", "INT64", mode="REQUIRED", description="Foreign key to users table"),
            bigquery.SchemaField("delivery_status", "STRING", mode="REQUIRED", description="Status (Delivered, Undelivered, Expired)"),
            bigquery.SchemaField("delivered_at", "TIMESTAMP", mode="NULLABLE", description="Delivery timestamp")
        ]
    },
    "mobile_app_push_campaigns": {
        "description": "Mobile application push notification marketing campaigns and deeplink targets.",
        "fields": [
            bigquery.SchemaField("push_campaign_id", "INT64", mode="REQUIRED", description="Push campaign ID"),
            bigquery.SchemaField("title", "STRING", mode="REQUIRED", description="Notification headline"),
            bigquery.SchemaField("body_text", "STRING", mode="REQUIRED", description="Notification body"),
            bigquery.SchemaField("target_deeplink", "STRING", mode="REQUIRED", description="In-app deeplink URI"),
            bigquery.SchemaField("sent_at", "TIMESTAMP", mode="REQUIRED", description="Send timestamp")
        ]
    },
    "push_notification_receipts": {
        "description": "Firebase Cloud Messaging (FCM) and Apple APNS mobile push delivery and tap telemetry.",
        "fields": [
            bigquery.SchemaField("push_id", "INT64", mode="REQUIRED", description="Push notification ID"),
            bigquery.SchemaField("push_campaign_id", "INT64", mode="REQUIRED", description="Foreign key to mobile_app_push_campaigns"),
            bigquery.SchemaField("user_id", "INT64", mode="REQUIRED", description="Foreign key to users table"),
            bigquery.SchemaField("platform", "STRING", mode="REQUIRED", description="Device platform (iOS, Android)"),
            bigquery.SchemaField("was_clicked", "BOOL", mode="REQUIRED", description="Whether user tapped the notification"),
            bigquery.SchemaField("delivered_at", "TIMESTAMP", mode="REQUIRED", description="Delivery timestamp")
        ]
    },
    "user_subscription_preferences": {
        "description": "Granular customer GDPR marketing communication consent flags per channel.",
        "fields": [
            bigquery.SchemaField("preference_id", "INT64", mode="REQUIRED", description="Preference ID"),
            bigquery.SchemaField("user_id", "INT64", mode="REQUIRED", description="Foreign key to users table"),
            bigquery.SchemaField("email_opt_in", "BOOL", mode="REQUIRED", description="Email marketing consent"),
            bigquery.SchemaField("sms_opt_in", "BOOL", mode="REQUIRED", description="SMS marketing consent"),
            bigquery.SchemaField("push_opt_in", "BOOL", mode="REQUIRED", description="Push notification consent"),
            bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED", description="Last consent update timestamp")
        ]
    },
    "affiliate_publishers_directory": {
        "description": "Registered third-party affiliate marketing publishers, coupon portals, and blog partners.",
        "fields": [
            bigquery.SchemaField("affiliate_id", "INT64", mode="REQUIRED", description="Affiliate publisher ID"),
            bigquery.SchemaField("publisher_name", "STRING", mode="REQUIRED", description="Affiliate company/website name"),
            bigquery.SchemaField("commission_rate_pct", "FLOAT64", mode="REQUIRED", description="Contractual revenue share commission percentage"),
            bigquery.SchemaField("is_active", "BOOL", mode="REQUIRED", description="Active partner flag")
        ]
    },
    "affiliate_commission_payouts": {
        "description": "Monthly affiliate publisher conversion sales tracking and commission payout statements.",
        "fields": [
            bigquery.SchemaField("payout_id", "INT64", mode="REQUIRED", description="Payout statement ID"),
            bigquery.SchemaField("affiliate_id", "INT64", mode="REQUIRED", description="Foreign key to affiliate_publishers_directory"),
            bigquery.SchemaField("period", "STRING", mode="REQUIRED", description="Fulfillment period (YYYY-MM)"),
            bigquery.SchemaField("attributed_sales_eur", "FLOAT64", mode="REQUIRED", description="Gross order sales driven"),
            bigquery.SchemaField("commission_earned_eur", "FLOAT64", mode="REQUIRED", description="Earned publisher commission in EUR"),
            bigquery.SchemaField("is_paid", "BOOL", mode="REQUIRED", description="Payment status")
        ]
    },

    # -------------------------------------------------------------
    # DOMAIN O: Product Information Management (PIM) & Catalog Metadata (8 Tables)
    # -------------------------------------------------------------
    "product_attribute_definitions": {
        "description": "PIM master taxonomy of specification attribute keys (e.g. volume, skin_type, battery_life, fabric).",
        "fields": [
            bigquery.SchemaField("attribute_id", "INT64", mode="REQUIRED", description="Attribute key ID"),
            bigquery.SchemaField("attribute_code", "STRING", mode="REQUIRED", description="Machine attribute code (e.g. volume_ml, shade_color, voltage)"),
            bigquery.SchemaField("display_label", "STRING", mode="REQUIRED", description="Customer-facing label"),
            bigquery.SchemaField("data_type", "STRING", mode="REQUIRED", description="Data type (Text, Number, Enum, Boolean)")
        ]
    },
    "product_attribute_values": {
        "description": "Concrete specification attribute values assigned to each product SKU.",
        "fields": [
            bigquery.SchemaField("value_id", "INT64", mode="REQUIRED", description="Attribute value record ID"),
            bigquery.SchemaField("product_id", "INT64", mode="REQUIRED", description="Foreign key to products table"),
            bigquery.SchemaField("attribute_id", "INT64", mode="REQUIRED", description="Foreign key to product_attribute_definitions"),
            bigquery.SchemaField("attribute_value", "STRING", mode="REQUIRED", description="Concrete specification value string")
        ]
    },
    "product_multilingual_translations": {
        "description": "Multilingual localized product titles, marketing copy, and bullet points across European languages.",
        "fields": [
            bigquery.SchemaField("translation_id", "INT64", mode="REQUIRED", description="Translation record ID"),
            bigquery.SchemaField("product_id", "INT64", mode="REQUIRED", description="Foreign key to products table"),
            bigquery.SchemaField("language_code", "STRING", mode="REQUIRED", description="ISO language code (fr, de, nl, es, it)"),
            bigquery.SchemaField("localized_name", "STRING", mode="REQUIRED", description="Localized product title"),
            bigquery.SchemaField("localized_description", "STRING", mode="REQUIRED", description="Localized marketing description text")
        ]
    },
    "product_media_gallery": {
        "description": "CDN image gallery URLs, 360-degree interactive spin assets, and video demo links per product.",
        "fields": [
            bigquery.SchemaField("media_id", "INT64", mode="REQUIRED", description="Media asset ID"),
            bigquery.SchemaField("product_id", "INT64", mode="REQUIRED", description="Foreign key to products table"),
            bigquery.SchemaField("media_type", "STRING", mode="REQUIRED", description="Media type (Main_Hero, Gallery_Photo, Model_Video, Swatch_Color)"),
            bigquery.SchemaField("cdn_url", "STRING", mode="REQUIRED", description="Cloud CDN asset URL"),
            bigquery.SchemaField("sort_order", "INT64", mode="REQUIRED", description="Display sequence order on product page")
        ]
    },
    "product_size_charts": {
        "description": "Apparel, footwear, and beauty shade guide sizing and measurement charts.",
        "fields": [
            bigquery.SchemaField("size_chart_id", "INT64", mode="REQUIRED", description="Size chart ID"),
            bigquery.SchemaField("category_id", "INT64", mode="REQUIRED", description="Foreign key to categories table"),
            bigquery.SchemaField("size_label", "STRING", mode="REQUIRED", description="Size code (XS, S, M, L, XL, 38EU, 40EU)"),
            bigquery.SchemaField("chest_cm", "FLOAT64", mode="NULLABLE", description="Chest measurement in cm"),
            bigquery.SchemaField("waist_cm", "FLOAT64", mode="NULLABLE", description="Waist measurement in cm")
        ]
    },
    "product_brand_guidelines": {
        "description": "Brand identity guidelines, authorized luxury retailer badges, and trademark requirements.",
        "fields": [
            bigquery.SchemaField("guideline_id", "INT64", mode="REQUIRED", description="Guideline record ID"),
            bigquery.SchemaField("brand_name", "STRING", mode="REQUIRED", description="Brand name (Lumière, Nuit_Étoilée, Aura_Tech, Maison_Vogue)"),
            bigquery.SchemaField("min_advertised_price_policy", "BOOL", mode="REQUIRED", description="Strict MAP price enforcement flag"),
            bigquery.SchemaField("authorized_distributor_only", "BOOL", mode="REQUIRED", description="Restricted distribution channel flag")
        ]
    },
    "category_hierarchy_paths": {
        "description": "Breadcrumb hierarchy paths and parent-child tree mapping for store category navigation.",
        "fields": [
            bigquery.SchemaField("path_id", "INT64", mode="REQUIRED", description="Path ID"),
            bigquery.SchemaField("category_id", "INT64", mode="REQUIRED", description="Foreign key to categories table"),
            bigquery.SchemaField("parent_category_id", "INT64", mode="NULLABLE", description="Parent category reference"),
            bigquery.SchemaField("breadcrumb_path", "STRING", mode="REQUIRED", description="Full breadcrumb trail (e.g. Home > Beauty > Skincare > Serums)")
        ]
    },
    "seo_meta_tags_registry": {
        "description": "Canonical URLs, SEO meta titles, OpenGraph social cards, and schema.org structured markup.",
        "fields": [
            bigquery.SchemaField("seo_id", "INT64", mode="REQUIRED", description="SEO metadata ID"),
            bigquery.SchemaField("page_path", "STRING", mode="REQUIRED", description="Relative URL path"),
            bigquery.SchemaField("meta_title", "STRING", mode="REQUIRED", description="HTML title tag string"),
            bigquery.SchemaField("meta_description", "STRING", mode="REQUIRED", description="HTML meta description snippet"),
            bigquery.SchemaField("canonical_url", "STRING", mode="REQUIRED", description="Canonical URL reference")
        ]
    },

    # -------------------------------------------------------------
    # DOMAIN P: Retail Physical Stores & Omni-Channel POS (8 Tables)
    # -------------------------------------------------------------
    "physical_store_locations": {
        "description": "Brick-and-mortar retail flagship boutique addresses, store managers, and operating hours.",
        "fields": [
            bigquery.SchemaField("store_id", "INT64", mode="REQUIRED", description="Store boutique ID"),
            bigquery.SchemaField("store_name", "STRING", mode="REQUIRED", description="Boutique name (e.g. Paris Champs-Élysées, Berlin Kudamm, Amsterdam Kalverstraat)"),
            bigquery.SchemaField("city", "STRING", mode="REQUIRED", description="City"),
            bigquery.SchemaField("country", "STRING", mode="REQUIRED", description="Country"),
            bigquery.SchemaField("square_meters", "INT64", mode="REQUIRED", description="Retail sales floor area in sq meters"),
            bigquery.SchemaField("is_open", "BOOL", mode="REQUIRED", description="Operational status flag")
        ]
    },
    "pos_terminal_registers": {
        "description": "Point-of-sale hardware register terminal identifiers and peripheral configurations.",
        "fields": [
            bigquery.SchemaField("register_id", "INT64", mode="REQUIRED", description="POS terminal ID"),
            bigquery.SchemaField("store_id", "INT64", mode="REQUIRED", description="Foreign key to physical_store_locations"),
            bigquery.SchemaField("terminal_model", "STRING", mode="REQUIRED", description="Hardware terminal model (Verifone_P400, Ingenico_Lane5000)"),
            bigquery.SchemaField("ip_address", "STRING", mode="REQUIRED", description="Terminal static local IP")
        ]
    },
    "pos_store_transactions": {
        "description": "In-store physical point-of-sale checkout transaction receipts and sales totals.",
        "fields": [
            bigquery.SchemaField("pos_transaction_id", "INT64", mode="REQUIRED", description="POS transaction ID"),
            bigquery.SchemaField("store_id", "INT64", mode="REQUIRED", description="Foreign key to physical_store_locations"),
            bigquery.SchemaField("register_id", "INT64", mode="REQUIRED", description="Foreign key to pos_terminal_registers"),
            bigquery.SchemaField("cashier_employee_id", "STRING", mode="REQUIRED", description="Cashier staff ID"),
            bigquery.SchemaField("total_amount_eur", "FLOAT64", mode="REQUIRED", description="Total receipt total in EUR"),
            bigquery.SchemaField("payment_type", "STRING", mode="REQUIRED", description="Payment tender (Contactless_Card, Cash, GiftCard)"),
            bigquery.SchemaField("transacted_at", "TIMESTAMP", mode="REQUIRED", description="Receipt timestamp")
        ]
    },
    "pos_transaction_items": {
        "description": "Item-level SKU lines purchased in brick-and-mortar retail boutique transactions.",
        "fields": [
            bigquery.SchemaField("pos_item_id", "INT64", mode="REQUIRED", description="POS item line ID"),
            bigquery.SchemaField("pos_transaction_id", "INT64", mode="REQUIRED", description="Foreign key to pos_store_transactions"),
            bigquery.SchemaField("product_id", "INT64", mode="REQUIRED", description="Foreign key to products table"),
            bigquery.SchemaField("quantity", "INT64", mode="REQUIRED", description="Quantity purchased"),
            bigquery.SchemaField("unit_sale_price_eur", "FLOAT64", mode="REQUIRED", description="Retail price charged in EUR")
        ]
    },
    "click_and_collect_orders": {
        "description": "Buy-Online-Pick-Up-In-Store (BOPIS) staging manifests and customer collection pickup timestamps.",
        "fields": [
            bigquery.SchemaField("bopis_id", "INT64", mode="REQUIRED", description="BOPIS collection ID"),
            bigquery.SchemaField("order_id", "INT64", mode="REQUIRED", description="Foreign key to orders table"),
            bigquery.SchemaField("store_id", "INT64", mode="REQUIRED", description="Pickup boutique store ID"),
            bigquery.SchemaField("pickup_pin_code", "STRING", mode="REQUIRED", description="Encrypted collection SMS PIN"),
            bigquery.SchemaField("status", "STRING", mode="REQUIRED", description="Status (ReadyForPickup, Collected, Abandoned)"),
            bigquery.SchemaField("collected_at", "TIMESTAMP", mode="NULLABLE", description="Customer pickup timestamp")
        ]
    },
    "store_inventory_levels": {
        "description": "Physical retail boutique on-shelf and backroom inventory stock quantities per SKU.",
        "fields": [
            bigquery.SchemaField("store_stock_id", "INT64", mode="REQUIRED", description="Store stock record ID"),
            bigquery.SchemaField("store_id", "INT64", mode="REQUIRED", description="Foreign key to physical_store_locations"),
            bigquery.SchemaField("product_id", "INT64", mode="REQUIRED", description="Foreign key to products table"),
            bigquery.SchemaField("on_hand_quantity", "INT64", mode="REQUIRED", description="Units available in store"),
            bigquery.SchemaField("last_cycle_counted_at", "TIMESTAMP", mode="REQUIRED", description="Last cycle count timestamp")
        ]
    },
    "store_employee_rosters": {
        "description": "Retail boutique sales associate and store manager shift schedules.",
        "fields": [
            bigquery.SchemaField("roster_id", "INT64", mode="REQUIRED", description="Roster shift ID"),
            bigquery.SchemaField("store_id", "INT64", mode="REQUIRED", description="Foreign key to physical_store_locations"),
            bigquery.SchemaField("employee_name", "STRING", mode="REQUIRED", description="Sales associate name"),
            bigquery.SchemaField("shift_role", "STRING", mode="REQUIRED", description="Role (Store_Manager, Senior_Stylist, Cashier)"),
            bigquery.SchemaField("shift_date", "DATE", mode="REQUIRED", description="Shift date")
        ]
    },
    "store_cash_drawer_counts": {
        "description": "End-of-day POS cash drawer float reconciliation and over/short cash audits.",
        "fields": [
            bigquery.SchemaField("drawer_count_id", "INT64", mode="REQUIRED", description="Drawer audit ID"),
            bigquery.SchemaField("store_id", "INT64", mode="REQUIRED", description="Foreign key to physical_store_locations"),
            bigquery.SchemaField("register_id", "INT64", mode="REQUIRED", description="Foreign key to pos_terminal_registers"),
            bigquery.SchemaField("expected_cash_eur", "FLOAT64", mode="REQUIRED", description="System calculated cash float"),
            bigquery.SchemaField("actual_counted_cash_eur", "FLOAT64", mode="REQUIRED", description="Physical counted cash"),
            bigquery.SchemaField("counted_at", "TIMESTAMP", mode="REQUIRED", description="Audit timestamp")
        ]
    },

    # -------------------------------------------------------------
    # DOMAIN Q: Non-Production, Sandbox & QA Archives (10 Tables)
    # -------------------------------------------------------------
    "dev_customer_churn_feature_store": {
        "description": "Experimental ML feature store vectors for customer churn and lifetime value prediction models.",
        "fields": [
            bigquery.SchemaField("user_id", "INT64", mode="REQUIRED", description="User ID"),
            bigquery.SchemaField("days_since_last_order", "INT64", mode="REQUIRED", description="Recency feature"),
            bigquery.SchemaField("order_frequency_90d", "INT64", mode="REQUIRED", description="Frequency feature"),
            bigquery.SchemaField("total_spend_eur", "FLOAT64", mode="REQUIRED", description="Monetary feature"),
            bigquery.SchemaField("predicted_churn_probability", "FLOAT64", mode="REQUIRED", description="Model churn score (0.0 to 1.0)"),
            bigquery.SchemaField("model_version", "STRING", mode="REQUIRED", description="ML model experiment tag")
        ]
    },
    "dev_product_embedding_vectors": {
        "description": "768-dimensional multimodal vector embeddings generated for semantic catalog search.",
        "fields": [
            bigquery.SchemaField("product_id", "INT64", mode="REQUIRED", description="Product ID"),
            bigquery.SchemaField("embedding_model_name", "STRING", mode="REQUIRED", description="Model name (text-embedding-005)"),
            bigquery.SchemaField("vector_dimensions", "INT64", mode="REQUIRED", description="Vector length (768)"),
            bigquery.SchemaField("vector_blob", "STRING", mode="REQUIRED", description="Serialized floating point vector string")
        ]
    },
    "qa_load_test_sessions_backup": {
        "description": "Synthetic load test traffic session artifacts from pre-Black Friday Locust stress tests.",
        "fields": [
            bigquery.SchemaField("test_run_id", "STRING", mode="REQUIRED", description="Locust test run UUID"),
            bigquery.SchemaField("virtual_user_id", "STRING", mode="REQUIRED", description="Virtual simulated user ID"),
            bigquery.SchemaField("target_rps", "INT64", mode="REQUIRED", description="Target requests per second"),
            bigquery.SchemaField("response_time_p95_ms", "FLOAT64", mode="REQUIRED", description="P95 latency observed in ms"),
            bigquery.SchemaField("executed_at", "TIMESTAMP", mode="REQUIRED", description="Execution timestamp")
        ]
    },
    "qa_checkout_synthetic_fuzz_tests": {
        "description": "Automated chaos testing and synthetic fuzzing payloads tested against the checkout gateway.",
        "fields": [
            bigquery.SchemaField("fuzz_id", "INT64", mode="REQUIRED", description="Fuzz test run ID"),
            bigquery.SchemaField("payload_type", "STRING", mode="REQUIRED", description="Fuzz mutation type (MalformedCard, SQL_Injection_Test, Null_Currency)"),
            bigquery.SchemaField("http_response_code", "INT64", mode="REQUIRED", description="Observed gateway response code (400, 422)"),
            bigquery.SchemaField("tested_at", "TIMESTAMP", mode="REQUIRED", description="Test timestamp")
        ]
    },
    "sandbox_dynamic_pricing_sim_v1": {
        "description": "Offline sandbox dynamic pricing elasticity simulation results and revenue impact models.",
        "fields": [
            bigquery.SchemaField("sim_id", "INT64", mode="REQUIRED", description="Simulation ID"),
            bigquery.SchemaField("product_id", "INT64", mode="REQUIRED", description="Product ID"),
            bigquery.SchemaField("price_multiplier", "FLOAT64", mode="REQUIRED", description="Tested price delta (0.90 to 1.15)"),
            bigquery.SchemaField("simulated_demand_units", "INT64", mode="REQUIRED", description="Simulated demand volume"),
            bigquery.SchemaField("simulated_margin_eur", "FLOAT64", mode="REQUIRED", description="Simulated gross profit margin in EUR")
        ]
    },
    "sandbox_search_ranking_ab_test": {
        "description": "Offline A/B test telemetry comparing BM25 keyword matching vs hybrid dense vector search.",
        "fields": [
            bigquery.SchemaField("experiment_id", "STRING", mode="REQUIRED", description="A/B experiment ID"),
            bigquery.SchemaField("search_query", "STRING", mode="REQUIRED", description="Search query tested"),
            bigquery.SchemaField("algorithm_variant", "STRING", mode="REQUIRED", description="Variant (Variant_A_BM25, Variant_B_HybridVector)"),
            bigquery.SchemaField("ndcg_at_10_score", "FLOAT64", mode="REQUIRED", description="NDCG@10 relevance score")
        ]
    },
    "legacy_orders_2023_archive": {
        "description": "Historical cold archive of completed orders from Black Friday 2023 for multi-year YoY trend analysis.",
        "fields": [
            bigquery.SchemaField("legacy_order_id", "INT64", mode="REQUIRED", description="Archived order ID from 2023"),
            bigquery.SchemaField("order_date", "DATE", mode="REQUIRED", description="Order date in November 2023"),
            bigquery.SchemaField("total_amount_eur", "FLOAT64", mode="REQUIRED", description="Order value in EUR"),
            bigquery.SchemaField("category_name", "STRING", mode="REQUIRED", description="Category name")
        ]
    },
    "legacy_products_deprecated": {
        "description": "Discontinued catalog products retired from the active storefront between 2022 and 2024.",
        "fields": [
            bigquery.SchemaField("legacy_product_id", "INT64", mode="REQUIRED", description="Retired SKU ID"),
            bigquery.SchemaField("product_name", "STRING", mode="REQUIRED", description="Discontinued product name"),
            bigquery.SchemaField("discontinued_year", "INT64", mode="REQUIRED", description="Year retired (2022, 2023, 2024)"),
            bigquery.SchemaField("last_sale_price_eur", "FLOAT64", mode="REQUIRED", description="Final closeout price in EUR")
        ]
    },
    "test_fraud_mock_transactions": {
        "description": "Mock credit card fraud patterns and risk score simulation records for security rules.",
        "fields": [
            bigquery.SchemaField("mock_id", "INT64", mode="REQUIRED", description="Mock transaction ID"),
            bigquery.SchemaField("risk_score", "FLOAT64", mode="REQUIRED", description="Synthetic fraud score (0 to 100)"),
            bigquery.SchemaField("risk_decision", "STRING", mode="REQUIRED", description="Decision (Approve, Review, Decline)"),
            bigquery.SchemaField("ip_country_mismatch", "BOOL", mode="REQUIRED", description="GeoIP mismatch flag")
        ]
    },
    "test_carrier_webhook_payloads": {
        "description": "Mock carrier delivery tracking webhooks tested against development endpoints.",
        "fields": [
            bigquery.SchemaField("test_payload_id", "STRING", mode="REQUIRED", description="Mock payload ID"),
            bigquery.SchemaField("carrier_event", "STRING", mode="REQUIRED", description="Event name (PackagePickedUp, OutForDelivery, Delivered)"),
            bigquery.SchemaField("raw_mock_json", "STRING", mode="REQUIRED", description="Mock payload JSON"),
            bigquery.SchemaField("tested_at", "TIMESTAMP", mode="REQUIRED", description="Test timestamp")
        ]
    }
}

def create_extended_tables():
    print("=" * 80)
    print("INITIALIZING EXTENDED E-COMMERCE SCHEMA (104 NEW TABLES -> 130 TABLES TOTAL)")
    print(f"Target Dataset: `{PROJECT_ID}.{DATASET_ID}`")
    print("=" * 80)

    client = get_bigquery_client()
    created = 0
    updated = 0

    for table_name, meta in EXTENDED_TABLE_SCHEMAS.items():
        table_ref = f"{PROJECT_ID}.{DATASET_ID}.{table_name}"
        table = bigquery.Table(table_ref, schema=meta["fields"])
        table.description = meta["description"]
        
        try:
            client.create_table(table, exists_ok=True)
            # Update description if it already existed
            existing_table = client.get_table(table_ref)
            existing_table.description = meta["description"]
            existing_table.schema = meta["fields"]
            client.update_table(existing_table, ["description", "schema"])
            print(f"  ✅ Initialized `{table_name}` ({len(meta['fields'])} columns) -> {meta['description'][:65]}...")
            created += 1
        except Exception as e:
            print(f"  ❌ Error creating `{table_name}`: {e}")

    print("\n" + "=" * 80)
    print(f"EXTENDED SCHEMA INITIALIZATION COMPLETE: {created}/104 Tables Initialized in `{DATASET_ID}`")
    
    # Check total tables count in dataset
    tables = list(client.list_tables(f"{PROJECT_ID}.{DATASET_ID}"))
    print(f"Total Tables in `{PROJECT_ID}.{DATASET_ID}`: {len(tables)} Tables")
    print("=" * 80)

if __name__ == "__main__":
    create_extended_tables()
