#!/usr/bin/env python3
"""
Phase 1: BigQuery Core Warehouse Schema Creation Script
========================================================
Creates the BigQuery dataset (`ecommerce_dw`) and provisions the initial 21 relational
warehouse tables spanning Domains A through F:

Domain Breakdown:
-----------------
  Domain A: Catalog & Inventory (categories, products, distribution_centers, inventory_items, inventory_snapshots, oos_interactions)
  Domain B: Commercial Targets (weekly_commercial_targets, daily_category_targets, category_15min_targets, target_adjustments)
  Domain C: Traffic & Clickstream (clickstream_sessions, event_stream, sales_event_stream, ab_test_allocations)
  Domain D: Orders & Transactions (orders, order_items, payments, refunds)
  Domain E: Marketing & Advertising (marketing_campaigns, ad_creatives, daily_ad_performance)
  Domain F: Logistics & Carrier SLAs (shipping_lead_times)

Usage:
------
  python3 scripts/01_create_schema.py
"""

import os
import sys
import subprocess
from google.cloud import bigquery
from google.oauth2 import credentials as oauth2_credentials


def load_dotenv():
    """Parses root-level .env file into os.environ for local pipeline execution."""
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
LOCATION = os.environ.get("BQ_LOCATION", "europe-west4")

# Schema definitions using BigQuery SchemaField API (bypasses bigquery.jobs.create)
TABLE_SCHEMAS = {
    "categories": [
        bigquery.SchemaField("category_id", "INT64", description="Unique identifier for the category."),
        bigquery.SchemaField("parent_category_id", "INT64", description="Self-referencing link to parent category for hierarchical depth."),
        bigquery.SchemaField("name", "STRING", description="Friendly display name (e.g., 'Beauty', 'Electronics')."),
        bigquery.SchemaField("slug", "STRING", description="Unique URL-safe text string.")
    ],
    "products": [
        bigquery.SchemaField("product_id", "INT64", description="Unique master identifier for the product."),
        bigquery.SchemaField("category_id", "INT64", description="Link to categories."),
        bigquery.SchemaField("name", "STRING", description="Full retail product name."),
        bigquery.SchemaField("sku", "STRING", description="Stock Keeping Unit code for supply chain operations."),
        bigquery.SchemaField("brand", "STRING", description="Brand or manufacturer name."),
        bigquery.SchemaField("retail_price", "NUMERIC", description="Default selling price."),
        bigquery.SchemaField("cost", "NUMERIC", description="Acquisition/production cost."),
        bigquery.SchemaField("is_active", "BOOL", description="Flag denoting catalog visibility.")
    ],
    "distribution_centers": [
        bigquery.SchemaField("dc_id", "INT64", description="Unique identifier for the warehouse/logistics hub."),
        bigquery.SchemaField("name", "STRING", description="Physical hub name."),
        bigquery.SchemaField("latitude", "FLOAT64", description="Hub latitude."),
        bigquery.SchemaField("longitude", "FLOAT64", description="Hub longitude.")
    ],
    "inventory_items": [
        bigquery.SchemaField("inventory_item_id", "INT64", description="Identifier for each physical batch or discrete stock unit."),
        bigquery.SchemaField("product_id", "INT64", description="Link to products."),
        bigquery.SchemaField("dc_id", "INT64", description="Link to shipping/holding distribution_centers."),
        bigquery.SchemaField("quantity_on_hand", "INT64", description="Physical units remaining in stock."),
        bigquery.SchemaField("safety_stock_level", "INT64", description="Warning limit before low-stock automated triggers fire."),
        bigquery.SchemaField("created_at", "TIMESTAMP", description="Date of arrival at the hub.")
    ],
    "inventory_snapshots": [
        bigquery.SchemaField("snapshot_id", "INT64", description="System tracking snapshot record."),
        bigquery.SchemaField("product_id", "INT64", description="Link to products."),
        bigquery.SchemaField("recorded_at", "TIMESTAMP", description="Time of log entry."),
        bigquery.SchemaField("stock_quantity", "INT64", description="Stock remaining at timestamp."),
        bigquery.SchemaField("is_out_of_stock", "BOOL", description="Flag state triggered if quantity is zero or less.")
    ],
    "users": [
        bigquery.SchemaField("user_id", "INT64", description="Customer account ID."),
        bigquery.SchemaField("email", "STRING", description="Customer primary contact address."),
        bigquery.SchemaField("first_name", "STRING", description="Given name."),
        bigquery.SchemaField("last_name", "STRING", description="Surname."),
        bigquery.SchemaField("gender", "STRING", description="Self-identified demographic data."),
        bigquery.SchemaField("age", "INT64", description="Demographics."),
        bigquery.SchemaField("country", "STRING", description="Regional localization."),
        bigquery.SchemaField("latitude", "FLOAT64", description="Approximate geolocation coordinate."),
        bigquery.SchemaField("longitude", "FLOAT64", description="Approximate geolocation coordinate."),
        bigquery.SchemaField("created_at", "TIMESTAMP", description="Date of profile creation.")
    ],
    "orders": [
        bigquery.SchemaField("order_id", "INT64", description="Transaction header identifier."),
        bigquery.SchemaField("user_id", "INT64", description="Link to buying profile in users."),
        bigquery.SchemaField("session_id", "STRING", description="Originating web session referencing web_sessions.session_id."),
        bigquery.SchemaField("order_status", "STRING", description="Fulfilment outcome, derived from the order's line items: 'Completed' (nothing returned), 'Partially Returned' (some lines returned), 'Returned' (every line returned). All three are genuinely placed, paid orders."),
        bigquery.SchemaField("total_amount", "NUMERIC", description="Total gross transaction price."),
        bigquery.SchemaField("tax_amount", "NUMERIC", description="Tax portion of the purchase."),
        bigquery.SchemaField("shipping_fee", "NUMERIC", description="Shipping cost billed."),
        bigquery.SchemaField("num_of_items", "INT64", description="Sum total of physical pieces purchased."),
        bigquery.SchemaField("created_at", "TIMESTAMP", description="Execution timestamp.")
    ],
    "order_items": [
        bigquery.SchemaField("order_item_id", "INT64", description="Transaction line item."),
        bigquery.SchemaField("ord_hdr_num", "INT64", description="Foreign key referencing master orders.order_id."),
        bigquery.SchemaField("user_id", "INT64", description="Link to users."),
        bigquery.SchemaField("mat_nr", "INT64", description="Material article identifier referencing products.product_id."),
        bigquery.SchemaField("inventory_item_id", "INT64", description="Mapping to physical unit in inventory_items."),
        bigquery.SchemaField("quantity", "INT64", description="Number of units purchased."),
        bigquery.SchemaField("sale_price", "NUMERIC", description="Capture price at checkout."),
        bigquery.SchemaField("discount_amount", "NUMERIC", description="Applied campaign deductions."),
        bigquery.SchemaField("created_at", "TIMESTAMP", description="Line item creation time."),
        bigquery.SchemaField("shipped_at", "TIMESTAMP", description="Departure log time."),
        bigquery.SchemaField("delivered_at", "TIMESTAMP", description="Successful arrival log time."),
        bigquery.SchemaField("returned_at", "TIMESTAMP", description="Customer returns timestamp.")
    ],
    "sales_event_stream": [
        bigquery.SchemaField("event_id", "STRING", description="Streaming UUID."),
        bigquery.SchemaField("order_id", "INT64", description="Target transaction."),
        bigquery.SchemaField("product_id", "INT64", description="Target product."),
        bigquery.SchemaField("category_id", "INT64", description="Target category."),
        bigquery.SchemaField("quantity", "INT64", description="Count of units."),
        bigquery.SchemaField("sale_price", "NUMERIC", description="Captured base checkout price."),
        bigquery.SchemaField("discount_amount", "NUMERIC", description="Active promotion deductions."),
        bigquery.SchemaField("timestamp", "TIMESTAMP", description="Real-time event landing time.")
    ],
    "weekly_commercial_targets": [
        bigquery.SchemaField("target_id", "INT64", description="Target budget ID."),
        bigquery.SchemaField("category_id", "INT64", description="Target category."),
        bigquery.SchemaField("week_start_date", "DATE", description="Target calendar baseline."),
        bigquery.SchemaField("target_revenue", "NUMERIC", description="Financial target."),
        bigquery.SchemaField("target_sessions", "INT64", description="Necessary session target."),
        bigquery.SchemaField("target_conversion_rate", "NUMERIC", description="Conversion target.")
    ],
    "category_15min_targets": [
        bigquery.SchemaField("target_id", "STRING", description="Sub-target mapping key."),
        bigquery.SchemaField("category_id", "INT64", description="Link to categories."),
        bigquery.SchemaField("day_of_week", "INT64", description="1 (Sunday) to 7 (Saturday)."),
        bigquery.SchemaField("time_bucket", "TIME", description="Specific 15-minute slot (e.g. 14:30:00)."),
        bigquery.SchemaField("target_revenue", "NUMERIC", description="Calculated financial target."),
        bigquery.SchemaField("target_sessions", "INT64", description="Traffic targets.")
    ],
    "daily_category_targets": [
        bigquery.SchemaField("target_id", "STRING", description="Unique identifier for daily target."),
        bigquery.SchemaField("category_id", "INT64", description="Link to categories."),
        bigquery.SchemaField("date", "DATE", description="Target calendar date."),
        bigquery.SchemaField("target_revenue", "NUMERIC", description="Targeted gross financial intake."),
        bigquery.SchemaField("target_sessions", "INT64", description="Traffic acquisition target."),
        bigquery.SchemaField("target_conversion_rate", "NUMERIC", description="Expected e-commerce conversion efficiency."),
        bigquery.SchemaField("target_aov", "NUMERIC", description="Expected mean transaction value."),
        bigquery.SchemaField("target_ad_spend", "NUMERIC", description="Allocated marketing budget resources."),
        bigquery.SchemaField("target_roas", "NUMERIC", description="Targeted efficiency for ad expenditure.")
    ],
    "web_sessions": [
        bigquery.SchemaField("session_id", "STRING", description="Persistent user browser session identifier."),
        bigquery.SchemaField("user_id", "INT64", description="Customer profile ID (nullable)."),
        bigquery.SchemaField("traffic_source", "STRING", description="Origin channel ('Paid Search', 'Direct', etc.)."),
        bigquery.SchemaField("utm_source", "STRING", description="Campaign parameter."),
        bigquery.SchemaField("utm_medium", "STRING", description="Campaign parameter."),
        bigquery.SchemaField("utm_campaign", "STRING", description="Campaign parameter."),
        bigquery.SchemaField("primary_category_id", "INT64", description="Category the session predominantly browsed, referencing categories.category_id."),
        bigquery.SchemaField("converted_to_order", "BOOL", description="True when the session resulted in a completed order."),
        bigquery.SchemaField("device_os", "STRING", description="Client operating system ('iOS', 'Android', 'Windows')."),
        bigquery.SchemaField("browser", "STRING", description="Client web browser ('Safari', 'Chrome', 'Edge')."),
        bigquery.SchemaField("country", "STRING", description="Visitor country from the IP lookup, so it is present even when the visitor is not signed in and user_id is NULL. Matches users.country for known customers."),
        bigquery.SchemaField("session_started_at", "TIMESTAMP", description="Timestamp of the first interaction in the session."),
        bigquery.SchemaField("session_ended_at", "TIMESTAMP", description="Timestamp of the last recorded interaction in the session. Equals session_started_at when the session produced no further events."),
        bigquery.SchemaField("page_views_count", "INT64", description="Navigations to a new page during the session. This is a SUBSET of the rows in web_events: in-page interactions such as filter_applied, image_zoom, review_read, wishlist_add and cart_add are events but not page views.")
    ],
    "web_events": [
        bigquery.SchemaField("event_id", "INT64", description="Auto-incrementing identifier."),
        bigquery.SchemaField("session_id", "STRING", description="Link to web_sessions."),
        bigquery.SchemaField("product_id", "INT64", description="Active item associated with user action."),
        bigquery.SchemaField("event_type", "STRING", description="Interaction category ('view', 'cart_add', 'error')."),
        bigquery.SchemaField("page_url", "STRING", description="Active page address."),
        bigquery.SchemaField("metadata", "RECORD", mode="NULLABLE", fields=[
            bigquery.SchemaField("error_message", "STRING"),
            bigquery.SchemaField("http_status_code", "INT64"),
            bigquery.SchemaField("estimated_lost_revenue", "NUMERIC")
        ], description="Nested BigQuery metadata structure."),
        bigquery.SchemaField("created_at", "TIMESTAMP", description="Time of user activity.")
    ],
    "oos_interactions": [
        bigquery.SchemaField("interaction_id", "INT64", description="Event tracking ID."),
        bigquery.SchemaField("session_id", "STRING", description="Link to active session."),
        bigquery.SchemaField("art_code", "INT64", description="Catalog article SKU code referencing products.product_id."),
        bigquery.SchemaField("clicked_at", "TIMESTAMP", description="Moment user requested out-of-stock item."),
        bigquery.SchemaField("pot_val", "NUMERIC", description="Estimated unrealized sales value from out-of-stock user friction.")
    ],
    "competitor_price_feed": [
        bigquery.SchemaField("scrape_id", "INT64", description="Tracking index of scraper run."),
        bigquery.SchemaField("product_id", "INT64", description="Internal benchmarked item link."),
        bigquery.SchemaField("competitor_name", "STRING", description="Name of scraped competitor."),
        bigquery.SchemaField("competitor_price", "NUMERIC", description="Discovered competitor retail price."),
        bigquery.SchemaField("is_in_stock", "BOOL", description="Competitor stock availability status."),
        bigquery.SchemaField("scraped_at", "TIMESTAMP", description="Timestamp of run completion.")
    ],
    "marketing_campaigns": [
        bigquery.SchemaField("campaign_id", "INT64", description="Unique ad network identification."),
        bigquery.SchemaField("name", "STRING", description="Ad campaign folder label."),
        bigquery.SchemaField("platform", "STRING", description="Target provider ('Google Ads', 'Meta Ads')."),
        bigquery.SchemaField("target_category_id", "INT64", description="Direct link to category pushed."),
        bigquery.SchemaField("bidding_strategy", "STRING", description="Active optimization ruleset."),
        bigquery.SchemaField("is_active", "BOOL", description="Active flag.")
    ],
    "daily_ad_performance": [
        bigquery.SchemaField("performance_id", "INT64", description="Aggregated record identifier."),
        bigquery.SchemaField("cid_ref", "INT64", description="External marketing campaign identifier referencing marketing_campaigns.campaign_id."),
        bigquery.SchemaField("date", "DATE", description="Date performance recorded."),
        bigquery.SchemaField("impressions", "INT64", description="View totals."),
        bigquery.SchemaField("clicks", "INT64", description="Click interaction totals."),
        bigquery.SchemaField("spend", "NUMERIC", description="Spent budget resources."),
        bigquery.SchemaField("conversions", "INT64", description="Recorded signups/sales."),
        bigquery.SchemaField("average_cpc", "NUMERIC", description="Realized cost per click.")
    ],
    "ad_bidding_log": [
        bigquery.SchemaField("log_id", "INT64", description="Automation activity index."),
        bigquery.SchemaField("campaign_id", "INT64", description="Target campaign identifier."),
        bigquery.SchemaField("status_change", "STRING", description="Bidding platform feedback state."),
        bigquery.SchemaField("action_taken", "STRING", description="Machine-emitted action code applied by the bidding engine."),
        bigquery.SchemaField("observed_cvr_7d", "FLOAT64", description="Trailing 7-day conversion rate observed by the bidding engine at evaluation time."),
        bigquery.SchemaField("target_roas_multiplier", "FLOAT64", description="Ratio of observed return on ad spend to the configured target."),
        bigquery.SchemaField("budget_multiplier", "FLOAT64", description="Fraction of the planned daily budget the engine permitted after evaluation."),
        bigquery.SchemaField("bid_adjustment_pct", "FLOAT64", description="Percentage change applied to the bid ceiling at this evaluation."),
        bigquery.SchemaField("logged_at", "TIMESTAMP", description="Machine execution time.")
    ],
    "ad_creatives": [
        bigquery.SchemaField("creative_id", "INT64", description="Unique identifier for ad creative asset."),
        bigquery.SchemaField("parent_adgroup_id", "INT64", description="Parent marketing campaign hierarchy identifier referencing marketing_campaigns.campaign_id."),
        bigquery.SchemaField("name", "STRING", description="Display name of creative asset."),
        bigquery.SchemaField("ad_format", "STRING", description="Visual medium or format."),
        bigquery.SchemaField("quality_score", "INT64", description="Ad quality and performance rating (1-10)."),
        bigquery.SchemaField("relevance_status", "STRING", description="Status of ad relevance."),
        bigquery.SchemaField("dlv_lrn_lmt_flg", "BOOL", description="Boolean flag indicating algorithmic delivery bottleneck."),
        bigquery.SchemaField("last_refreshed_at", "TIMESTAMP", description="Timestamp asset was last updated.")
    ],
    "payment_gateway_logs": [
        bigquery.SchemaField("gateway_log_id", "STRING", description="Unique identifier for the payment gateway transaction log."),
        bigquery.SchemaField("session_id", "STRING", description="Web session identifier."),
        bigquery.SchemaField("order_id", "INT64", description="Associated order identifier if available."),
        bigquery.SchemaField("payment_provider", "STRING", description="Payment service provider (e.g., 'Stripe', 'PayPal', 'Adyen')."),
        bigquery.SchemaField("payment_method", "STRING", description="Payment instrument (e.g., 'Credit Card', 'PayPal', 'Apple Pay')."),
        bigquery.SchemaField("status", "STRING", description="Payment authorization status ('SUCCESS', 'FAILED', 'TIMEOUT')."),
        bigquery.SchemaField("http_status_code", "INT64", description="HTTP status code returned by the gateway."),
        bigquery.SchemaField("error_code", "STRING", description="Gateway error code (e.g., 'ERR_504_GATEWAY_TIMEOUT', 'INSUFFICIENT_FUNDS')."),
        bigquery.SchemaField("total_amount", "NUMERIC", description="Transaction value attempted."),
        bigquery.SchemaField("latency_ms", "INT64", description="Gateway response latency in milliseconds."),
        bigquery.SchemaField("country", "STRING", description="Customer country code/name."),
        bigquery.SchemaField("created_at", "TIMESTAMP", description="Timestamp when transaction was processed.")
    ],
    "influencer_campaigns": [
        bigquery.SchemaField("influencer_id", "INT64", description="Unique identifier for influencer partnership."),
        bigquery.SchemaField("creator_name", "STRING", description="Creator social media handle or brand name."),
        bigquery.SchemaField("platform", "STRING", description="Primary social channel (e.g., 'TikTok', 'Instagram', 'YouTube')."),
        bigquery.SchemaField("campaign_name", "STRING", description="Campaign identifier."),
        bigquery.SchemaField("promo_code", "STRING", description="Unique tracking promo code (e.g., 'GLOW_ELENA_BF')."),
        bigquery.SchemaField("target_revenue", "NUMERIC", description="Contracted/projected revenue goal."),
        bigquery.SchemaField("actual_revenue", "NUMERIC", description="Realized attributed sales revenue."),
        bigquery.SchemaField("orders_count", "INT64", description="Total orders placed with creator promo code."),
        bigquery.SchemaField("views_count", "INT64", description="Total social video/post views achieved."),
        bigquery.SchemaField("fee_amount", "NUMERIC", description="Creator sponsorship fee paid."),
        bigquery.SchemaField("is_active", "BOOL", description="Campaign active status."),
        bigquery.SchemaField("created_at", "TIMESTAMP", description="Campaign launch timestamp.")
    ],
    "catalog_recommender_logs": [
        bigquery.SchemaField("log_id", "STRING", description="Unique recommender widget event identifier."),
        bigquery.SchemaField("session_id", "STRING", description="User web session identifier."),
        bigquery.SchemaField("src_sku", "INT64", description="Source product item viewed on active page (FK to products)."),
        bigquery.SchemaField("page_category_id", "INT64", description="Category ID of the current page."),
        bigquery.SchemaField("rec_sku", "INT64", description="Recommended product candidate suggested by ML engine (FK to products)."),
        bigquery.SchemaField("recommended_category_id", "INT64", description="Category ID of the recommended product."),
        bigquery.SchemaField("fb_rule_id", "INT64", description="Rule engine identifier: 99 = global category fallback, 0 = standard collaborative filter."),
        bigquery.SchemaField("cat_mismatch_flg", "INT64", description="Cross-department mismatch flag: 1 when the recommended item's category differs from the page's category, 0 otherwise."),
        bigquery.SchemaField("user_action", "STRING", description="User interaction ('CLICKED', 'BOUNCED', 'IGNORED')."),
        bigquery.SchemaField("opp_cost_eur", "NUMERIC", description="Estimated lost substitution revenue from failed recommendation cross-sell."),
        bigquery.SchemaField("recorded_at", "TIMESTAMP", description="Timestamp of recommender event.")
    ],
    "shipping_lead_times": [
        bigquery.SchemaField("lead_time_id", "STRING", description="Fulfillment operational snapshot identifier."),
        bigquery.SchemaField("dc_id", "INT64", description="Distribution center hub ID."),
        bigquery.SchemaField("date", "DATE", description="Operational date."),
        bigquery.SchemaField("carrier_name", "STRING", description="Logistics carrier (e.g., 'DHL Express', 'Chronopost', 'DPD')."),
        bigquery.SchemaField("destination_region", "STRING", description="Delivery destination zone (e.g., 'DACH', 'France', 'Southern Europe')."),
        bigquery.SchemaField("capacity_utilization_pct", "FLOAT64", description="Warehouse/carrier capacity utilization percentage."),
        bigquery.SchemaField("standard_lead_time_hours", "INT64", description="SLA target delivery window in hours."),
        bigquery.SchemaField("actual_promised_lead_time_hours", "INT64", description="Estimated delivery window displayed at checkout."),
        bigquery.SchemaField("cart_abandonment_impact_pct", "FLOAT64", description="Estimated additional cart abandonment rate induced."),
        bigquery.SchemaField("estimated_lost_revenue", "NUMERIC", description="Financial impact of extended lead time.")
    ],
    "competitor_promotions": [
        bigquery.SchemaField("promo_id", "INT64", description="Competitor promo scrape record ID."),
        bigquery.SchemaField("competitor_name", "STRING", description="Competitor name (e.g., 'Competitor A', 'Competitor B')."),
        bigquery.SchemaField("category_id", "INT64", description="Target category."),
        bigquery.SchemaField("promotion_title", "STRING", description="Competitor campaign headline."),
        bigquery.SchemaField("discount_pct", "FLOAT64", description="Competitor discount depth percentage."),
        bigquery.SchemaField("price_index_vs_lumiere", "FLOAT64", description="Price index relative to LumièreShop (e.g., 0.99x / 1.01x)."),
        bigquery.SchemaField("start_date", "DATE", description="Promotion start date."),
        bigquery.SchemaField("end_date", "DATE", description="Promotion end date."),
        bigquery.SchemaField("scraped_at", "TIMESTAMP", description="Timestamp of scrape execution.")
    ],
    "agent_interaction_logs": [
        bigquery.SchemaField("interaction_id", "STRING", description="Unique identifier for agent conversation interaction."),
        bigquery.SchemaField("session_id", "STRING", description="Identifier of user session or conversation thread."),
        bigquery.SchemaField("user_name", "STRING", description="User identifier or display name submitting the analytics inquiry."),
        bigquery.SchemaField("user_account", "STRING", description="User email or account identity executing prompt."),
        bigquery.SchemaField("user_prompt", "STRING", description="Natural language input prompt provided by user."),
        bigquery.SchemaField("generated_sql", "STRING", description="BigQuery SQL query generated by Conversational Analytics agent."),
        bigquery.SchemaField("response_text", "STRING", description="Natural language answer generated by Conversational Analytics agent."),
        bigquery.SchemaField("execution_time_ms", "INT64", description="Total execution latency in ms."),
        bigquery.SchemaField("bytes_scanned", "INT64", description="Volume of data scanned in BigQuery."),
        bigquery.SchemaField("bytes_billed", "INT64", description="Volume of data billed in bytes by BigQuery."),
        bigquery.SchemaField("slot_milliseconds", "INT64", description="Total CPU slot execution time in milliseconds."),
        bigquery.SchemaField("job_id", "STRING", description="BigQuery Job ID assigned to query execution."),
        bigquery.SchemaField("referenced_tables", "STRING", description="JSON string array of BigQuery tables queried."),
        bigquery.SchemaField("result_row_count", "INT64", description="Total records returned in query result."),
        bigquery.SchemaField("thinking_process", "STRING", description="Intermediate natural language reasoning emitted by agent."),
        bigquery.SchemaField("step_count", "INT64", description="Total execution steps taken by Data Agent."),
        bigquery.SchemaField("has_chart", "BOOL", description="Flag indicating if a visual chart was generated."),
        bigquery.SchemaField("chart_type", "STRING", description="Visual chart layout type."),
        bigquery.SchemaField("followup_questions", "STRING", description="JSON string array of recommended follow-up questions."),
        bigquery.SchemaField("data_agent_id", "STRING", description="Resource name of grounded GCP Data Agent used."),
        bigquery.SchemaField("http_status_code", "INT64", description="HTTP status code returned by API."),
        bigquery.SchemaField("ca_api_endpoint", "STRING", description="Conversational Analytics API REST endpoint path called."),
        bigquery.SchemaField("raw_ca_api_response", "STRING", description="Full JSON response payload returned by API."),
        bigquery.SchemaField("menu_item", "STRING", description="Interface menu context initiating the interaction ('chat' vs 'compare chats')."),
        bigquery.SchemaField("agent_no", "STRING", description="Agent identifier in comparative multi-agent mode ('agentA', 'agentB', 'agentC', or NULL for single agent)."),
        bigquery.SchemaField("created_at", "TIMESTAMP", description="Timestamp when interaction occurred.")
    ]
}

def load_dotenv():
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())

load_dotenv()

def get_bigquery_client(project_id):
    access_token = os.environ.get("GCP_ACCESS_TOKEN")
    if not access_token:
        gcloud_paths = ["/google/data/ro/teams/cloud-sdk/gcloud", "gcloud"]
        for gcloud_cmd in gcloud_paths:
            try:
                res = subprocess.run([gcloud_cmd, "auth", "print-access-token"], capture_output=True, text=True, timeout=10)
                if res.returncode == 0 and res.stdout.strip():
                    access_token = res.stdout.strip()
                    break
            except Exception:
                continue

    if access_token:
        print("Using authenticated gcloud OAuth token for BigQuery API calls...")
        creds = oauth2_credentials.Credentials(access_token)
        return bigquery.Client(project=project_id, credentials=creds)
    
    return bigquery.Client(project=project_id)

def create_dataset(client: bigquery.Client):
    dataset_ref = bigquery.DatasetReference(PROJECT_ID, DATASET_ID)
    try:
        dataset = client.get_dataset(dataset_ref)
        print(f"Dataset '{PROJECT_ID}.{DATASET_ID}' already exists in location {dataset.location}.")
        return
    except Exception:
        pass

    dataset = bigquery.Dataset(dataset_ref)
    dataset.location = LOCATION
    try:
        dataset = client.create_dataset(dataset, exists_ok=True)
        print(f"Dataset '{PROJECT_ID}.{DATASET_ID}' created/verified in location {LOCATION}.")
    except Exception as e:
        print(f"Notice: Dataset creation on project '{PROJECT_ID}' skipped ({e}). Proceeding to create tables...", file=sys.stderr)

def create_tables(client: bigquery.Client):
    for table_name, schema in TABLE_SCHEMAS.items():
        table_id = f"{PROJECT_ID}.{DATASET_ID}.{table_name}"
        table = bigquery.Table(table_id, schema=schema)
        try:
            table = client.create_table(table, exists_ok=True)
            print(f"Table `{table_name}` successfully created/verified via Metadata API.")
        except Exception as e:
            print(f"Error creating table `{table_name}`: {e}", file=sys.stderr)

if __name__ == "__main__":
    print(f"Starting BigQuery Schema Creation for project '{PROJECT_ID}'...")
    client = get_bigquery_client(PROJECT_ID)
    create_dataset(client)
    create_tables(client)
    print("All 26 tables creation/verification process completed.")
