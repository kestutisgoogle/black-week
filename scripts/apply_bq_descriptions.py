#!/usr/bin/env python3
"""
BigQuery Warehouse Description & Metadata Annotation Utility
=============================================================
Applies structured 5-part functional descriptions (`[PURPOSE]`, `[DOMAIN]`, `[GRAIN]`,
`[TIER & REFRESH]`, `[ANALYTICAL ROLE]`), labels, and column-level definitions across
all 140 BigQuery tables in `ecommerce_dw`.

Ensures 100% metadata coverage so Google Cloud Knowledge Catalog semantic search
can index tables with maximum diagnostic precision.

Usage:
------
  python3 scripts/apply_bq_descriptions.py
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

# ----------------------------------------------------------------------------------------------------------------------
# TABLE METADATA: 5-Part Functional Descriptions & Medallion Architecture Labels
# ----------------------------------------------------------------------------------------------------------------------
TABLE_METADATA = {
    # -------------------------------------------------------------
    # DOMAIN A: Core Catalog & Warehouse Physical Logistics (6 Tables)
    # -------------------------------------------------------------
    "categories": {
        "description": "[PURPOSE]: Master product category taxonomy with hierarchical parent references for merchandising and commercial sales reporting. [DOMAIN]: Domain A: Core Commerce Catalog. [GRAIN]: One row per product category (category_id). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 01:00 UTC. [ANALYTICAL ROLE]: Catalog Dimension - Category Hierarchy & Merchandising Taxonomy.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_a_catalog", "diagnostic_role": "catalog_taxonomy", "grain": "category", "update_frequency": "batch_daily", "environment": "production"}
    },
    "products": {
        "description": "[PURPOSE]: Master catalog of all retail products, default selling prices, cost of goods, brands, and category mappings for commercial intake tracking. [DOMAIN]: Domain A: Core Commerce Catalog. [GRAIN]: One row per distinct product SKU (product_id). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 01:00 UTC. [ANALYTICAL ROLE]: Product Dimension - SKU Metadata, Pricing & Unit Economics.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_a_catalog", "diagnostic_role": "product_master", "grain": "product_sku", "update_frequency": "batch_daily", "environment": "production"}
    },
    "distribution_centers": {
        "description": "[PURPOSE]: Regional fulfillment centers and warehouse logistics hubs managing physical inventory and order dispatch across Europe. [DOMAIN]: Domain A: Core Commerce Catalog. [GRAIN]: One row per logistics hub (dc_id). [TIER & REFRESH]: GOLD_CURATED | Master Static. [ANALYTICAL ROLE]: Fulfillment Dimension - Regional Logistics Hub Partitioning & Dispatch Routing.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_a_catalog", "diagnostic_role": "fulfillment_hubs", "grain": "distribution_center", "update_frequency": "static", "environment": "production"}
    },
    "inventory_items": {
        "description": "[PURPOSE]: Real-time master stock allocations, safety stock warning thresholds, and warehouse batch availability tracking across distribution centers. [DOMAIN]: Domain A: Core Commerce Catalog. [GRAIN]: One row per inventory allocation batch per hub (inventory_item_id). [TIER & REFRESH]: GOLD_CURATED | Real-Time Micro-batch (5 min). [ANALYTICAL ROLE]: Inventory Balance - Real-Time Stock Buffer & Safety Stock Level Tracking.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_a_catalog", "diagnostic_role": "inventory_stockouts", "grain": "stock_batch", "update_frequency": "streaming", "environment": "production"}
    },
    "inventory_snapshots": {
        "description": "[PURPOSE]: Daily and hourly historical inventory snapshots tracking stock depletion, stockouts, and inventory availability across warehouse hubs. [DOMAIN]: Domain A: Core Commerce Catalog. [GRAIN]: One row per SKU per recording timestamp (snapshot_id). [TIER & REFRESH]: GOLD_CURATED | Hourly Snapshot. [ANALYTICAL ROLE]: Inventory Availability - Historical Stock Depletion & Zero-Stock Duration Tracking.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_a_catalog", "diagnostic_role": "inventory_stockouts", "grain": "sku_snapshot", "update_frequency": "batch_hourly", "environment": "production"}
    },
    "users": {
        "description": "[PURPOSE]: Customer user accounts with demographic localization, country mapping, and lifetime activity profiles. [DOMAIN]: Domain A: Core Commerce Catalog. [GRAIN]: One row per registered customer account (user_id). [TIER & REFRESH]: GOLD_CURATED | Real-Time Ingestion. [ANALYTICAL ROLE]: Customer Dimension - Geographic Cohort Partitioning & Demographic Breakdown.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_a_catalog", "diagnostic_role": "customer_demographics", "grain": "user_account", "update_frequency": "streaming", "environment": "production"}
    },

    # -------------------------------------------------------------
    # DOMAIN B: Transactional Sales & Commercial Targets (6 Tables)
    # -------------------------------------------------------------
    "orders": {
        "description": "[PURPOSE]: Core transactional sales order headers capturing customer checkout completion, gross merchandise value (GMV), order status, payment confirmation, and timestamps for commercial revenue analysis. [DOMAIN]: Domain B: Transactions & Target Curves. [GRAIN]: One row per checkout order header (order_id). [TIER & REFRESH]: GOLD_CURATED | Real-Time Streaming. [ANALYTICAL ROLE]: Sales Intake - Gross Merchandise Value (GMV) & Revenue Realization Reporting.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_b_transactions", "diagnostic_role": "sales_revenue_actuals", "grain": "order_header", "update_frequency": "streaming", "environment": "production"}
    },
    "order_items": {
        "description": "[PURPOSE]: Discrete purchase line items recording product SKU references, realized sale prices, return status, and basket-level revenue realization. [DOMAIN]: Domain B: Transactions & Target Curves. [GRAIN]: One row per purchased item line (order_item_id). [TIER & REFRESH]: GOLD_CURATED | Real-Time Streaming. [ANALYTICAL ROLE]: Line Item Sales - SKU-Level Contribution, Basket Margins & Volume Breakdown.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_b_transactions", "diagnostic_role": "sales_revenue_actuals", "grain": "order_item", "update_frequency": "streaming", "environment": "production"}
    },
    "sales_event_stream": {
        "description": "[PURPOSE]: Real-time streaming transactional event feed capturing high-frequency sales events and intra-hour intake velocity. [DOMAIN]: Domain B: Transactions & Target Curves. [GRAIN]: One row per real-time purchase event (event_id). [TIER & REFRESH]: GOLD_CURATED | Streaming Event-Driven (<1s). [ANALYTICAL ROLE]: Streaming Velocity - Real-Time Sales Rate & Intra-Hour Order Volume Monitoring.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_b_transactions", "diagnostic_role": "sales_revenue_actuals", "grain": "sales_event", "update_frequency": "streaming", "environment": "production"}
    },
    "weekly_commercial_targets": {
        "description": "[PURPOSE]: Executive commercial financial planning benchmarks, expected visitor sessions, target revenue in EUR, and conversion rate (CVR) goals by product category and calendar week for sales target tracking and commercial performance analysis. [DOMAIN]: Domain B: Commercial Pacing Targets. [GRAIN]: One row per product category per calendar week (target_id). [TIER & REFRESH]: GOLD_CURATED | Pre-Season Financial Benchmark. [ANALYTICAL ROLE]: Commercial Planning - Weekly Commercial Quotas & Financial Benchmark Targets.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_b_transactions", "diagnostic_role": "commercial_pacing_targets", "grain": "category_week", "update_frequency": "static", "environment": "production"}
    },
    "daily_category_targets": {
        "description": "[PURPOSE]: Intra-week daily pacing targets, budget allocations, expected conversion rates, and commercial revenue quotas per category for daily sales pacing and commercial performance analysis. [DOMAIN]: Domain B: Commercial Pacing Targets. [GRAIN]: One row per category per calendar day (target_id). [TIER & REFRESH]: GOLD_CURATED | Daily Benchmark. [ANALYTICAL ROLE]: Commercial Planning - Daily Revenue Quotas, Planned Conversion Rates & Pacing Baselines.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_b_transactions", "diagnostic_role": "commercial_pacing_targets", "grain": "category_day", "update_frequency": "static", "environment": "production"}
    },
    "category_15min_targets": {
        "description": "[PURPOSE]: Intraday 15-minute pacing targets modeling hourly customer traffic waves, intake velocity benchmarks, and intra-day pacing curves. [DOMAIN]: Domain B: Commercial Pacing Targets. [GRAIN]: One row per category per 15-minute time window (target_id). [TIER & REFRESH]: GOLD_CURATED | Intraday Curve Benchmark. [ANALYTICAL ROLE]: Intraday Pacing - 15-Minute Intake Velocity & Demand Curves.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_b_transactions", "diagnostic_role": "commercial_pacing_targets", "grain": "category_interval", "update_frequency": "static", "environment": "production"}
    },

    # -------------------------------------------------------------
    # DOMAIN C: Web Clickstream & Funnel Telemetry (3 Tables)
    # -------------------------------------------------------------
    "web_sessions": {
        "description": "[PURPOSE]: Web clickstream traffic sessions recording marketing channels, UTM acquisition tags, device operating systems, browsers, and user journey attribution. [DOMAIN]: Domain C: Web Clickstream & Funnel. [GRAIN]: One row per browser session (session_id). [TIER & REFRESH]: GOLD_CURATED | Real-Time Streaming Sessionization. [ANALYTICAL ROLE]: Web Traffic - Acquisition Channel Sessions & Conversion Rate Attribution.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_c_clickstream", "diagnostic_role": "funnel_clickstream", "grain": "user_session", "update_frequency": "streaming", "environment": "production"}
    },
    "web_events": {
        "description": "[PURPOSE]: User interaction clickstream funnel events capturing product page views, cart additions, checkout initiations, and transaction successes for conversion funnel drop-off analysis. [DOMAIN]: Domain C: Web Clickstream & Funnel. [GRAIN]: One row per clickstream interaction event (event_id). [TIER & REFRESH]: GOLD_CURATED | Real-Time Ingestion Feed. [ANALYTICAL ROLE]: Clickstream Funnel - Micro-Conversions, Page Navigation & Cart Telemetry.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_c_clickstream", "diagnostic_role": "funnel_clickstream", "grain": "click_event", "update_frequency": "streaming", "environment": "production"}
    },
    "oos_interactions": {
        "description": "[PURPOSE]: Customer browsing and cart interactions on out-of-stock items, capturing GROSS unfulfilled demand at list price. This table records demand that could not be served; it does NOT record a net revenue loss, which additionally requires the substitution rate and category conversion propensity. [DOMAIN]: Domain C: Out-of-Stock Telemetry. [GRAIN]: One row per out-of-stock user click interaction (interaction_id). [TIER & REFRESH]: GOLD_CURATED | Real-Time Event Feed. [ANALYTICAL ROLE]: Lost Demand Telemetry - Stockout Click Tracking & Unfulfilled Demand Estimation.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_c_clickstream", "diagnostic_role": "inventory_stockouts", "grain": "oos_click", "update_frequency": "streaming", "environment": "production"}
    },

    # -------------------------------------------------------------
    # DOMAIN D: Competitor Pricing & Promotions (2 Tables)
    # -------------------------------------------------------------
    "competitor_price_feed": {
        "description": "[PURPOSE]: Daily competitor retail pricing scrapes benchmarking price parity indices, market elasticity, and competitor price movements. [DOMAIN]: Domain D: Competitor Pricing Intelligence. [GRAIN]: One row per product SKU per competitor scrape (feed_id). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 06:00 UTC. [ANALYTICAL ROLE]: Pricing Intelligence - Competitor Price Parity & Elasticity Tracking.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_d_pricing", "diagnostic_role": "competitor_benchmarks", "grain": "sku_competitor_day", "update_frequency": "batch_daily", "environment": "production"}
    },
    "competitor_promotions": {
        "description": "[PURPOSE]: Scraped competitor retail promotional campaigns, discount depths, promotional banners, and relative price parity benchmarking data. [DOMAIN]: Domain D: Competitor Campaign Intelligence. [GRAIN]: One row per competitor promotion campaign (promo_id). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 06:00 UTC. [ANALYTICAL ROLE]: Promotional Intelligence - Competitor Campaign Monitoring & Discount Tracking.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_d_pricing", "diagnostic_role": "competitor_benchmarks", "grain": "promotion_campaign", "update_frequency": "batch_daily", "environment": "production"}
    },

    # -------------------------------------------------------------
    # DOMAIN E: Paid Advertising & Attribution (4 Tables)
    # -------------------------------------------------------------
    "marketing_campaigns": {
        "description": "[PURPOSE]: Paid digital marketing campaign configurations across Meta Ads and Google Ads with target ROAS, target CPA, and bidding strategy definitions. [DOMAIN]: Domain E: Paid Advertising & Attribution. [GRAIN]: One row per advertising campaign (campaign_id). [TIER & REFRESH]: GOLD_CURATED | Batch Hourly Sync. [ANALYTICAL ROLE]: Marketing Directory - Paid Search & Social Campaign Metadata Master.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_e_advertising", "diagnostic_role": "paid_marketing_efficiency", "grain": "ad_campaign", "update_frequency": "batch_hourly", "environment": "production"}
    },
    "daily_ad_performance": {
        "description": "[PURPOSE]: Daily marketing performance tracking impressions, clicks, advertising spend in EUR, attributed conversions, average CPC, and ROAS efficiency. [DOMAIN]: Domain E: Ad Spend & Paid Traffic. [GRAIN]: One row per campaign per calendar day (perf_id). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 03:00 UTC. [ANALYTICAL ROLE]: Paid Acquisition - Daily Spend Velocity, CPC Efficiency & Attributed ROAS Tracking.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_e_advertising", "diagnostic_role": "paid_marketing_efficiency", "grain": "campaign_day", "update_frequency": "batch_daily", "environment": "production"}
    },
    "ad_bidding_log": {
        "description": "[PURPOSE]: Automated ad platform bidding engine telemetry capturing target ROAS constraints, budget throttling events, and algorithmic learning phase status. [DOMAIN]: Domain E: Bidding Engine Telemetry. [GRAIN]: One row per bidding algorithm throttle/adjustment event (log_id). [TIER & REFRESH]: GOLD_CURATED | Real-Time Platform Webhook. [ANALYTICAL ROLE]: Bidding Telemetry - Automated Target ROAS Constraints & Budget Throttling Telemetry.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_e_advertising", "diagnostic_role": "paid_marketing_efficiency", "grain": "bidding_adjustment", "update_frequency": "streaming", "environment": "production"}
    },
    "ad_creatives": {
        "description": "[PURPOSE]: Creative asset performance tracking creative fatigue, quality scores, click-through rates, and learning-limited states impacting ad delivery. [DOMAIN]: Domain E: Creative Fatigue & Quality Scores. [GRAIN]: One row per creative visual asset (creative_id). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 04:00 UTC. [ANALYTICAL ROLE]: Creative Performance - Asset Fatigue, Quality Scores & Algorithmic Delivery Status.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_e_advertising", "diagnostic_role": "paid_marketing_efficiency", "grain": "creative_asset", "update_frequency": "batch_daily", "environment": "production"}
    },

    # -------------------------------------------------------------
    # DOMAIN F: Payment Gateways, Creators & Logistics (4 Tables)
    # -------------------------------------------------------------
    "payment_gateway_logs": {
        "description": "[PURPOSE]: Payment service provider (PSP) authorization logs capturing transaction success rates, latency in milliseconds, error codes, and checkout drop-offs across Stripe, PayPal, and Adyen. [DOMAIN]: Domain F: Payment Gateway Processing. [GRAIN]: One row per PSP gateway transaction attempt (log_id). [TIER & REFRESH]: GOLD_CURATED | Real-Time Streaming Gateway Logs. [ANALYTICAL ROLE]: Checkout Reliability - Payment Gateway Processing Health & Latency Monitoring.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_f_operations", "diagnostic_role": "payment_gateway_processing", "grain": "payment_transaction", "update_frequency": "streaming", "environment": "production"}
    },
    "influencer_campaigns": {
        "description": "[PURPOSE]: Creator marketing performance tracking sponsored content views, promo code redemptions, target vs actual revenue quotas, and creator fees. [DOMAIN]: Domain F: Creator & Influencer Marketing. [GRAIN]: One row per creator partnership campaign (campaign_id). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 05:00 UTC. [ANALYTICAL ROLE]: Creator Marketing - Influencer Campaign Redemptions & Commission Tracking.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_f_operations", "diagnostic_role": "creator_influencer_attribution", "grain": "creator_campaign", "update_frequency": "batch_daily", "environment": "production"}
    },
    "catalog_recommender_logs": {
        "description": "[PURPOSE]: On-page product recommendation widget impressions capturing algorithm fallback events, category mismatch errors, and lost substitution sales. [DOMAIN]: Domain F: Recommender Engine Telemetry. [GRAIN]: One row per widget recommendation display event (log_id). [TIER & REFRESH]: GOLD_CURATED | Real-Time Clickstream Telemetry. [ANALYTICAL ROLE]: Recommender Telemetry - Algorithmic Fallback Rates & Cross-Sell Engagement.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_f_operations", "diagnostic_role": "recommender_telemetry", "grain": "recommendation_impression", "update_frequency": "streaming", "environment": "production"}
    },
    "shipping_lead_times": {
        "description": "[PURPOSE]: Fulfillment center operational metrics, carrier workload, promised delivery SLAs, and delivery delay impacts on cart abandonment and conversion. [DOMAIN]: Domain F: Fulfillment & Delivery SLAs. [GRAIN]: One row per carrier per destination region per calendar day (lead_time_id). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 05:00 UTC. [ANALYTICAL ROLE]: Fulfillment Reliability - Carrier Transit Lead Times & Delivery SLA Tracking.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_f_operations", "diagnostic_role": "fulfillment_leadtimes", "grain": "carrier_region_day", "update_frequency": "batch_daily", "environment": "production"}
    },

    # -------------------------------------------------------------
    # DOMAIN G: Agent Governance (1 Table)
    # -------------------------------------------------------------
    "agent_interaction_logs": {
        "description": "[PURPOSE]: Conversational Analytics session audit logs recording natural language prompts, generated SQL queries, latency, and token execution costs. [DOMAIN]: Domain G: Agent Governance & Audit. [GRAIN]: One row per conversational user interaction turn (interaction_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Real-Time Async Audit Append. [ANALYTICAL ROLE]: System Governance - Conversational AI Audit Trail & Query Telemetry.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_g_governance", "diagnostic_role": "governance_audit", "grain": "agent_interaction", "update_frequency": "streaming", "environment": "production"}
    },

    # -------------------------------------------------------------
    # DOMAIN H: Staging & Raw Ingestion Tables (20 Tables)
    # -------------------------------------------------------------
    "stg_shopify_orders_raw": {
        "description": "[PURPOSE]: Raw Shopify webhook JSON payloads capturing e-commerce checkout and order events. [DOMAIN]: Domain H: Staging & Raw Ingestion Tables. [GRAIN]: One row per webhook payload (payload_id). [TIER & REFRESH]: BRONZE_RAW_STAGING | Event-Driven Webhook. [ANALYTICAL ROLE]: Staging Ingestion - Raw Ingestion Buffer.",
        "labels": {"data_tier": "bronze_raw_staging", "domain": "domain_h_staging", "diagnostic_role": "staging_raw_stream", "grain": "raw_payload", "update_frequency": "streaming", "environment": "staging"}
    },
    "stg_shopify_products_raw": {
        "description": "[PURPOSE]: Raw Shopify product synchronization JSON payloads from catalog webhooks. [DOMAIN]: Domain H: Staging & Raw Ingestion Tables. [GRAIN]: One row per product payload (payload_id). [TIER & REFRESH]: BRONZE_RAW_STAGING | Event-Driven Webhook. [ANALYTICAL ROLE]: Staging Ingestion - Raw Ingestion Buffer.",
        "labels": {"data_tier": "bronze_raw_staging", "domain": "domain_h_staging", "diagnostic_role": "staging_raw_stream", "grain": "raw_payload", "update_frequency": "streaming", "environment": "staging"}
    },
    "stg_shopify_customers_raw": {
        "description": "[PURPOSE]: Raw Shopify customer account update webhook JSON payloads. [DOMAIN]: Domain H: Staging & Raw Ingestion Tables. [GRAIN]: One row per customer payload (payload_id). [TIER & REFRESH]: BRONZE_RAW_STAGING | Event-Driven Webhook. [ANALYTICAL ROLE]: Staging Ingestion - Raw Ingestion Buffer.",
        "labels": {"data_tier": "bronze_raw_staging", "domain": "domain_h_staging", "diagnostic_role": "staging_raw_stream", "grain": "raw_payload", "update_frequency": "streaming", "environment": "staging"}
    },
    "stg_klaviyo_email_events_raw": {
        "description": "[PURPOSE]: Raw event stream from Klaviyo marketing automation webhook (opens, clicks, bounces). [DOMAIN]: Domain H: Staging & Raw Ingestion Tables. [GRAIN]: One row per email event (event_id). [TIER & REFRESH]: BRONZE_RAW_STAGING | Event-Driven Webhook. [ANALYTICAL ROLE]: Staging Ingestion - Raw Ingestion Buffer.",
        "labels": {"data_tier": "bronze_raw_staging", "domain": "domain_h_staging", "diagnostic_role": "staging_raw_stream", "grain": "raw_event", "update_frequency": "streaming", "environment": "staging"}
    },
    "stg_klaviyo_campaigns_raw": {
        "description": "[PURPOSE]: Raw email campaign configuration dumps from Klaviyo REST API. [DOMAIN]: Domain H: Staging & Raw Ingestion Tables. [GRAIN]: One row per campaign record (campaign_id). [TIER & REFRESH]: BRONZE_RAW_STAGING | Batch Daily Sync. [ANALYTICAL ROLE]: Staging Ingestion - Raw Ingestion Buffer.",
        "labels": {"data_tier": "bronze_raw_staging", "domain": "domain_h_staging", "diagnostic_role": "staging_raw_stream", "grain": "raw_campaign", "update_frequency": "batch_daily", "environment": "staging"}
    },
    "stg_stripe_payment_intents_raw": {
        "description": "[PURPOSE]: Raw Stripe payment intent webhook JSON payloads for credit card authorizations. [DOMAIN]: Domain H: Staging & Raw Ingestion Tables. [GRAIN]: One row per payment intent (intent_id). [TIER & REFRESH]: BRONZE_RAW_STAGING | Event-Driven Webhook. [ANALYTICAL ROLE]: Staging Ingestion - Raw Ingestion Buffer.",
        "labels": {"data_tier": "bronze_raw_staging", "domain": "domain_h_staging", "diagnostic_role": "staging_raw_stream", "grain": "raw_intent", "update_frequency": "streaming", "environment": "staging"}
    },
    "stg_stripe_disputes_raw": {
        "description": "[PURPOSE]: Raw Stripe credit card chargeback disputes and inquiry logs. [DOMAIN]: Domain H: Staging & Raw Ingestion Tables. [GRAIN]: One row per dispute record (dispute_id). [TIER & REFRESH]: BRONZE_RAW_STAGING | Event-Driven Webhook. [ANALYTICAL ROLE]: Staging Ingestion - Raw Ingestion Buffer.",
        "labels": {"data_tier": "bronze_raw_staging", "domain": "domain_h_staging", "diagnostic_role": "staging_raw_stream", "grain": "raw_dispute", "update_frequency": "streaming", "environment": "staging"}
    },
    "stg_zendesk_tickets_raw": {
        "description": "[PURPOSE]: Raw customer support ticket JSON records extracted from Zendesk Support API. [DOMAIN]: Domain H: Staging & Raw Ingestion Tables. [GRAIN]: One row per ticket record (ticket_id). [TIER & REFRESH]: BRONZE_RAW_STAGING | Micro-batch (15 min). [ANALYTICAL ROLE]: Staging Ingestion - Raw Ingestion Buffer.",
        "labels": {"data_tier": "bronze_raw_staging", "domain": "domain_h_staging", "diagnostic_role": "staging_raw_stream", "grain": "raw_ticket", "update_frequency": "batch_hourly", "environment": "staging"}
    },
    "stg_zendesk_satisfaction_raw": {
        "description": "[PURPOSE]: Raw customer satisfaction rating survey responses from Zendesk. [DOMAIN]: Domain H: Staging & Raw Ingestion Tables. [GRAIN]: One row per rating response (rating_id). [TIER & REFRESH]: BRONZE_RAW_STAGING | Micro-batch (15 min). [ANALYTICAL ROLE]: Staging Ingestion - Raw Ingestion Buffer.",
        "labels": {"data_tier": "bronze_raw_staging", "domain": "domain_h_staging", "diagnostic_role": "staging_raw_stream", "grain": "raw_survey", "update_frequency": "batch_hourly", "environment": "staging"}
    },
    "stg_google_ads_campaigns_raw": {
        "description": "[PURPOSE]: Raw Google Ads campaign performance reporting extracts. [DOMAIN]: Domain H: Staging & Raw Ingestion Tables. [GRAIN]: One row per campaign reporting day (campaign_id, date). [TIER & REFRESH]: BRONZE_RAW_STAGING | Batch Daily Sync. [ANALYTICAL ROLE]: Staging Ingestion - Raw Ingestion Buffer.",
        "labels": {"data_tier": "bronze_raw_staging", "domain": "domain_h_staging", "diagnostic_role": "staging_raw_stream", "grain": "raw_ad_report", "update_frequency": "batch_daily", "environment": "staging"}
    },
    "stg_google_ads_search_terms_raw": {
        "description": "[PURPOSE]: Raw Google Search Ads query term performance extracts. [DOMAIN]: Domain H: Staging & Raw Ingestion Tables. [GRAIN]: One row per search query per date (search_term, date). [TIER & REFRESH]: BRONZE_RAW_STAGING | Batch Daily Sync. [ANALYTICAL ROLE]: Staging Ingestion - Raw Ingestion Buffer.",
        "labels": {"data_tier": "bronze_raw_staging", "domain": "domain_h_staging", "diagnostic_role": "staging_raw_stream", "grain": "raw_search_term", "update_frequency": "batch_daily", "environment": "staging"}
    },
    "stg_meta_ad_insights_raw": {
        "description": "[PURPOSE]: Raw Meta Marketing API adset insights JSON feeds. [DOMAIN]: Domain H: Staging & Raw Ingestion Tables. [GRAIN]: One row per adset reporting interval (adset_id, date_start). [TIER & REFRESH]: BRONZE_RAW_STAGING | Batch Daily Sync. [ANALYTICAL ROLE]: Staging Ingestion - Raw Ingestion Buffer.",
        "labels": {"data_tier": "bronze_raw_staging", "domain": "domain_h_staging", "diagnostic_role": "staging_raw_stream", "grain": "raw_ad_insight", "update_frequency": "batch_daily", "environment": "staging"}
    },
    "stg_ga4_clickstream_raw": {
        "description": "[PURPOSE]: Raw Google Analytics 4 export event records from BigQuery streaming export. [DOMAIN]: Domain H: Staging & Raw Ingestion Tables. [GRAIN]: One row per raw GA4 hit event. [TIER & REFRESH]: BRONZE_RAW_STAGING | Real-Time GA4 Stream. [ANALYTICAL ROLE]: Staging Ingestion - Raw Ingestion Buffer.",
        "labels": {"data_tier": "bronze_raw_staging", "domain": "domain_h_staging", "diagnostic_role": "staging_raw_stream", "grain": "raw_clickstream", "update_frequency": "streaming", "environment": "staging"}
    },
    "stg_ga4_traffic_sources_raw": {
        "description": "[PURPOSE]: Raw GA4 traffic acquisition attribution source records. [DOMAIN]: Domain H: Staging & Raw Ingestion Tables. [GRAIN]: One row per session traffic acquisition tag (session_id). [TIER & REFRESH]: BRONZE_RAW_STAGING | Batch Daily Sync. [ANALYTICAL ROLE]: Staging Ingestion - Raw Ingestion Buffer.",
        "labels": {"data_tier": "bronze_raw_staging", "domain": "domain_h_staging", "diagnostic_role": "staging_raw_stream", "grain": "raw_traffic_source", "update_frequency": "batch_daily", "environment": "staging"}
    },
    "stg_sap_erp_inventory_feed_raw": {
        "description": "[PURPOSE]: Raw nightly inventory stock feed export from SAP ERP enterprise system. [DOMAIN]: Domain H: Staging & Raw Ingestion Tables. [GRAIN]: One row per SAP material plant balance (batch_id, material_number). [TIER & REFRESH]: BRONZE_RAW_STAGING | Batch Nightly File Dump. [ANALYTICAL ROLE]: Staging Ingestion - Raw Ingestion Buffer.",
        "labels": {"data_tier": "bronze_raw_staging", "domain": "domain_h_staging", "diagnostic_role": "staging_raw_stream", "grain": "raw_erp_stock", "update_frequency": "batch_daily", "environment": "staging"}
    },
    "stg_sap_erp_purchase_orders_raw": {
        "description": "[PURPOSE]: Raw SAP ERP procurement purchase order dumps. [DOMAIN]: Domain H: Staging & Raw Ingestion Tables. [GRAIN]: One row per SAP purchase order header (po_number). [TIER & REFRESH]: BRONZE_RAW_STAGING | Batch Daily Sync. [ANALYTICAL ROLE]: Staging Ingestion - Raw Ingestion Buffer.",
        "labels": {"data_tier": "bronze_raw_staging", "domain": "domain_h_staging", "diagnostic_role": "staging_raw_stream", "grain": "raw_po_dump", "update_frequency": "batch_daily", "environment": "staging"}
    },
    "stg_wms_shipments_raw": {
        "description": "[PURPOSE]: Raw warehouse management system (WMS) carrier dispatch manifests. [DOMAIN]: Domain H: Staging & Raw Ingestion Tables. [GRAIN]: One row per warehouse shipment manifest (shipment_id). [TIER & REFRESH]: BRONZE_RAW_STAGING | Micro-batch (10 min). [ANALYTICAL ROLE]: Staging Ingestion - Raw Ingestion Buffer.",
        "labels": {"data_tier": "bronze_raw_staging", "domain": "domain_h_staging", "diagnostic_role": "staging_raw_stream", "grain": "raw_wms_manifest", "update_frequency": "batch_hourly", "environment": "staging"}
    },
    "stg_criteo_retargeting_raw": {
        "description": "[PURPOSE]: Raw Criteo dynamic product retargeting daily performance reporting. [DOMAIN]: Domain H: Staging & Raw Ingestion Tables. [GRAIN]: One row per retargeting campaign per date (campaign_id, date). [TIER & REFRESH]: BRONZE_RAW_STAGING | Batch Daily Sync. [ANALYTICAL ROLE]: Staging Ingestion - Raw Ingestion Buffer.",
        "labels": {"data_tier": "bronze_raw_staging", "domain": "domain_h_staging", "diagnostic_role": "staging_raw_stream", "grain": "raw_retargeting", "update_frequency": "batch_daily", "environment": "staging"}
    },
    "stg_trustpilot_reviews_raw": {
        "description": "[PURPOSE]: Raw Trustpilot public customer review feed webhooks. [DOMAIN]: Domain H: Staging & Raw Ingestion Tables. [GRAIN]: One row per customer review (review_id). [TIER & REFRESH]: BRONZE_RAW_STAGING | Event-Driven Webhook. [ANALYTICAL ROLE]: Staging Ingestion - Raw Ingestion Buffer.",
        "labels": {"data_tier": "bronze_raw_staging", "domain": "domain_h_staging", "diagnostic_role": "staging_raw_stream", "grain": "raw_review", "update_frequency": "streaming", "environment": "staging"}
    },
    "stg_adyen_settlements_raw": {
        "description": "[PURPOSE]: Raw daily settlement payout reports from Adyen payment platform. [DOMAIN]: Domain H: Staging & Raw Ingestion Tables. [GRAIN]: One row per settlement batch (batch_id). [TIER & REFRESH]: BRONZE_RAW_STAGING | Batch Daily Payout Sync. [ANALYTICAL ROLE]: Staging Ingestion - Raw Ingestion Buffer.",
        "labels": {"data_tier": "bronze_raw_staging", "domain": "domain_h_staging", "diagnostic_role": "staging_raw_stream", "grain": "raw_settlement", "update_frequency": "batch_daily", "environment": "staging"}
    },

    # -------------------------------------------------------------
    # DOMAIN I: Returns, Refunds & RMA Management (10 Tables)
    # -------------------------------------------------------------
    "product_returns": {
        "description": "[PURPOSE]: Customer post-delivery return authorizations (RMA), return reasons, processing statuses, and item condition triage for reverse logistics and refund operations. [DOMAIN]: Domain I: Returns, Refunds & RMA Management. [GRAIN]: One row per returned item authorization (return_id). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 02:00 UTC. [ANALYTICAL ROLE]: Post-Purchase Reverse Logistics - Returns & RMA Quality Forensics.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_i_returns", "diagnostic_role": "returns_rma", "grain": "return_authorization", "update_frequency": "batch_daily", "environment": "production"}
    },
    "return_reasons_lookup": {
        "description": "[PURPOSE]: Standardized catalog of customer return reason codes, policy categories, and evidence requirements. [DOMAIN]: Domain I: Returns, Refunds & RMA Management. [GRAIN]: One row per return reason code (reason_code). [TIER & REFRESH]: GOLD_CURATED | Master Static. [ANALYTICAL ROLE]: Post-Purchase Reference - Return Reason Taxonomy.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_i_returns", "diagnostic_role": "returns_rma", "grain": "reason_code", "update_frequency": "static", "environment": "production"}
    },
    "return_shipping_labels": {
        "description": "[PURPOSE]: Logistics return shipping waybills and tracking records generated for customer merchandise returns. [DOMAIN]: Domain I: Returns, Refunds & RMA Management. [GRAIN]: One row per return parcel label (label_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Event-Driven Ingestion. [ANALYTICAL ROLE]: Reverse Logistics - In-Transit Return Parcel Tracking.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_i_returns", "diagnostic_role": "returns_rma", "grain": "shipping_label", "update_frequency": "streaming", "environment": "production"}
    },
    "return_inspections": {
        "description": "[PURPOSE]: Physical warehouse inspection triage logs evaluating item condition and restocking eligibility for returned goods. [DOMAIN]: Domain I: Returns, Refunds & RMA Management. [GRAIN]: One row per return triage inspection (inspection_id). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 03:00 UTC. [ANALYTICAL ROLE]: Warehouse Operations - RMA Quality Inspection & Restock Triage.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_i_returns", "diagnostic_role": "returns_rma", "grain": "inspection_event", "update_frequency": "batch_daily", "environment": "production"}
    },
    "warehouse_refurbishments": {
        "description": "[PURPOSE]: Refurbishment work orders, technician labor hours, and replacement parts costs for returned open-box electronics. [DOMAIN]: Domain I: Returns, Refunds & RMA Management. [GRAIN]: One row per refurbishing work order (refurb_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Batch Daily @ 04:00 UTC. [ANALYTICAL ROLE]: Warehouse Operations - Open-Box Refurbishment Cost Tracking.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_i_returns", "diagnostic_role": "returns_rma", "grain": "refurb_workorder", "update_frequency": "batch_daily", "environment": "production"}
    },
    "customer_refunds": {
        "description": "[PURPOSE]: Monetary refund disbursements issued to customers following verified returns, cancellations, or damaged item claims. [DOMAIN]: Domain I: Returns, Refunds & RMA Management. [GRAIN]: One row per refund transaction (refund_id). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 02:00 UTC. [ANALYTICAL ROLE]: Post-Purchase Financials - Customer Refund Value & Gateway Settlements.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_i_returns", "diagnostic_role": "returns_rma", "grain": "refund_transaction", "update_frequency": "batch_daily", "environment": "production"}
    },
    "store_credit_issuances": {
        "description": "[PURPOSE]: Store credit ledger records, customer credit balances, and credit expiration tracking. [DOMAIN]: Domain I: Returns, Refunds & RMA Management. [GRAIN]: One row per store credit grant (credit_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Batch Daily @ 02:00 UTC. [ANALYTICAL ROLE]: Customer Accounting - Store Credit Balances & Liability.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_i_returns", "diagnostic_role": "returns_rma", "grain": "store_credit", "update_frequency": "batch_daily", "environment": "production"}
    },
    "warranty_claims": {
        "description": "[PURPOSE]: Customer warranty claims, defect reports, manufacturer claim filings, and resolution triage. [DOMAIN]: Domain I: Returns, Refunds & RMA Management. [GRAIN]: One row per warranty claim filing (claim_id). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 03:00 UTC. [ANALYTICAL ROLE]: Product Quality - Warranty Failure Rates & Defect Forensics.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_i_returns", "diagnostic_role": "returns_rma", "grain": "warranty_claim", "update_frequency": "batch_daily", "environment": "production"}
    },
    "replacement_orders": {
        "description": "[PURPOSE]: Zero-cost replacement orders dispatched to customers for lost, defective, or incorrect shipments. [DOMAIN]: Domain I: Returns, Refunds & RMA Management. [GRAIN]: One row per replacement order link (replacement_id). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 02:00 UTC. [ANALYTICAL ROLE]: Customer Resolution - Replacement Order Fulfillment Tracking.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_i_returns", "diagnostic_role": "returns_rma", "grain": "replacement_order", "update_frequency": "batch_daily", "environment": "production"}
    },
    "restocking_fee_logs": {
        "description": "[PURPOSE]: Restocking fee deductions applied to customer return refunds for out-of-policy returns or bulky freight items. [DOMAIN]: Domain I: Returns, Refunds & RMA Management. [GRAIN]: One row per fee deduction (fee_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Batch Daily @ 02:00 UTC. [ANALYTICAL ROLE]: Reverse Logistics - Restocking Fee Cost Recovery.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_i_returns", "diagnostic_role": "returns_rma", "grain": "fee_deduction", "update_frequency": "batch_daily", "environment": "production"}
    },

    # -------------------------------------------------------------
    # DOMAIN J: Customer Support, CRM & CSAT (12 Tables)
    # -------------------------------------------------------------
    "support_tickets": {
        "description": "[PURPOSE]: Customer service support cases, ticket priority, omnichannel resolution duration, and first-response metrics. [DOMAIN]: Domain J: Customer Support, CRM & CSAT. [GRAIN]: One row per customer service ticket (ticket_id). [TIER & REFRESH]: GOLD_CURATED | Batch Hourly Sync. [ANALYTICAL ROLE]: Support Operations - Customer Inquiries, SLA Adherence & Escalations.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_j_support", "diagnostic_role": "customer_support", "grain": "support_ticket", "update_frequency": "batch_hourly", "environment": "production"}
    },
    "ticket_messages": {
        "description": "[PURPOSE]: Detailed communication thread messages exchanged between support agents and customers. [DOMAIN]: Domain J: Customer Support, CRM & CSAT. [GRAIN]: One row per message in ticket thread (message_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Streaming Message Ingestion. [ANALYTICAL ROLE]: Support Operations - Message Content & Agent Dialogue Audit.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_j_support", "diagnostic_role": "customer_support", "grain": "ticket_message", "update_frequency": "streaming", "environment": "production"}
    },
    "ticket_categories": {
        "description": "[PURPOSE]: Classification taxonomy of customer support issue types and target resolution SLA targets in minutes. [DOMAIN]: Domain J: Customer Support, CRM & CSAT. [GRAIN]: One row per ticket category (category_id). [TIER & REFRESH]: GOLD_CURATED | Master Static. [ANALYTICAL ROLE]: Support Operations - SLA Target Configurations.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_j_support", "diagnostic_role": "customer_support", "grain": "ticket_category", "update_frequency": "static", "environment": "production"}
    },
    "support_agents": {
        "description": "[PURPOSE]: Customer support representative profiles, tier rankings, language capabilities, and assigned shift schedules. [DOMAIN]: Domain J: Customer Support, CRM & CSAT. [GRAIN]: One row per support agent (agent_id). [TIER & REFRESH]: GOLD_CURATED | Master Static. [ANALYTICAL ROLE]: Support Operations - Agent Staffing & Skillset Routing.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_j_support", "diagnostic_role": "customer_support", "grain": "support_agent", "update_frequency": "static", "environment": "production"}
    },
    "agent_worklog_shifts": {
        "description": "[PURPOSE]: Daily customer support agent productivity records, tickets resolved, and average handle time (AHT) in seconds. [DOMAIN]: Domain J: Customer Support, CRM & CSAT. [GRAIN]: One row per agent shift (shift_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Batch Daily @ 01:00 UTC. [ANALYTICAL ROLE]: Support Operations - Agent Productivity & Shift Performance.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_j_support", "diagnostic_role": "customer_support", "grain": "agent_shift", "update_frequency": "batch_daily", "environment": "production"}
    },
    "csat_surveys": {
        "description": "[PURPOSE]: Post-service customer satisfaction survey scores (1-5 scale) and verbatim feedback submitted following ticket resolution. [DOMAIN]: Domain J: Customer Support, CRM & CSAT. [GRAIN]: One row per survey response (survey_id). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 02:00 UTC. [ANALYTICAL ROLE]: Customer Experience - CSAT Sentiment & Service Quality Scoring.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_j_support", "diagnostic_role": "customer_support", "grain": "csat_survey", "update_frequency": "batch_daily", "environment": "production"}
    },
    "nps_feedback_responses": {
        "description": "[PURPOSE]: Relationship Net Promoter Score (NPS) surveys measuring overall customer brand loyalty and willingness to recommend. [DOMAIN]: Domain J: Customer Support, CRM & CSAT. [GRAIN]: One row per NPS survey submission (nps_id). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 02:00 UTC. [ANALYTICAL ROLE]: Customer Experience - Net Promoter Score & Brand Advocacy.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_j_support", "diagnostic_role": "customer_support", "grain": "nps_response", "update_frequency": "batch_daily", "environment": "production"}
    },
    "live_chat_sessions": {
        "description": "[PURPOSE]: Real-time live chat sessions between web visitors and support agents, recording queue wait times and chat duration. [DOMAIN]: Domain J: Customer Support, CRM & CSAT. [GRAIN]: One row per live chat session (chat_session_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Batch Hourly Sync. [ANALYTICAL ROLE]: Customer Experience - Live Chat Wait Times & Queue Health.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_j_support", "diagnostic_role": "customer_support", "grain": "chat_session", "update_frequency": "batch_hourly", "environment": "production"}
    },
    "live_chat_messages": {
        "description": "[PURPOSE]: Individual real-time chat transcript messages exchanged during live customer chat sessions. [DOMAIN]: Domain J: Customer Support, CRM & CSAT. [GRAIN]: One row per chat transcript message (message_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Streaming Message Ingestion. [ANALYTICAL ROLE]: Support Operations - Live Chat Dialogue Records.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_j_support", "diagnostic_role": "customer_support", "grain": "chat_message", "update_frequency": "streaming", "environment": "production"}
    },
    "call_center_recordings_metadata": {
        "description": "[PURPOSE]: Inbound telephony call records, interactive voice response (IVR) menu traversal, call duration, and customer phone hashes. [DOMAIN]: Domain J: Customer Support, CRM & CSAT. [GRAIN]: One row per voice telephony call (call_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Batch Hourly Sync. [ANALYTICAL ROLE]: Support Operations - Telephony Call Center Telemetry.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_j_support", "diagnostic_role": "customer_support", "grain": "telephony_call", "update_frequency": "batch_hourly", "environment": "production"}
    },
    "customer_escalations": {
        "description": "[PURPOSE]: High-priority customer escalations handled by management, documenting escalation reason, resolution category, and financial goodwill concessions in EUR. [DOMAIN]: Domain J: Customer Support, CRM & CSAT. [GRAIN]: One row per escalation case (escalation_id). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 02:00 UTC. [ANALYTICAL ROLE]: Customer Relations - Critical Escalation Tracking & Concession Analysis.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_j_support", "diagnostic_role": "customer_support", "grain": "escalation_case", "update_frequency": "batch_daily", "environment": "production"}
    },
    "knowledge_base_articles": {
        "description": "[PURPOSE]: Help center self-service FAQ articles, view counts, and customer helpfulness voting metrics. [DOMAIN]: Domain J: Customer Support, CRM & CSAT. [GRAIN]: One row per knowledge base article (article_id). [TIER & REFRESH]: GOLD_CURATED | Master Static. [ANALYTICAL ROLE]: Self-Service - Help Center Knowledge Article Performance.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_j_support", "diagnostic_role": "customer_support", "grain": "kb_article", "update_frequency": "static", "environment": "production"}
    },

    # -------------------------------------------------------------
    # DOMAIN K: Supply Chain, Procurement & Warehousing (14 Tables)
    # -------------------------------------------------------------
    "suppliers_master": {
        "description": "[PURPOSE]: Global product manufacturer and wholesale supplier master profiles, country codes, payment terms, and active contract status. [DOMAIN]: Domain K: Supply Chain, Procurement & Warehousing. [GRAIN]: One row per vendor supplier (supplier_id). [TIER & REFRESH]: GOLD_CURATED | Master Static. [ANALYTICAL ROLE]: Supply Chain - Vendor Profiles & Procurement Terms.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_k_supply_chain", "diagnostic_role": "procurement_wms", "grain": "supplier", "update_frequency": "static", "environment": "production"}
    },
    "purchase_orders": {
        "description": "[PURPOSE]: Commercial procurement purchase order headers issued to product suppliers with contractual delivery deadlines and values in EUR. [DOMAIN]: Domain K: Supply Chain, Procurement & Warehousing. [GRAIN]: One row per purchase order header (po_id). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 04:00 UTC. [ANALYTICAL ROLE]: Procurement - Inbound Purchase Order Commitments.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_k_supply_chain", "diagnostic_role": "procurement_wms", "grain": "po_header", "update_frequency": "batch_daily", "environment": "production"}
    },
    "purchase_order_line_items": {
        "description": "[PURPOSE]: Itemized procurement line items specifying ordered quantities, received quantities, and unit wholesale costs in EUR. [DOMAIN]: Domain K: Supply Chain, Procurement & Warehousing. [GRAIN]: One row per purchase order line (po_line_id). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 04:00 UTC. [ANALYTICAL ROLE]: Procurement - SKU Inbound Receipt Fulfillment & Unit Costs.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_k_supply_chain", "diagnostic_role": "procurement_wms", "grain": "po_line", "update_frequency": "batch_daily", "environment": "production"}
    },
    "supplier_lead_time_history": {
        "description": "[PURPOSE]: Historical supplier manufacturing and transit lead times comparing promised days vs actual delivery dates. [DOMAIN]: Domain K: Supply Chain, Procurement & Warehousing. [GRAIN]: One row per supplier shipment delivery (history_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Batch Daily @ 04:00 UTC. [ANALYTICAL ROLE]: Supply Chain - Supplier Lead Time Variance & Reliability.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_k_supply_chain", "diagnostic_role": "procurement_wms", "grain": "lead_time_record", "update_frequency": "batch_daily", "environment": "production"}
    },
    "supplier_quality_scorecards": {
        "description": "[PURPOSE]: Monthly supplier performance evaluation scorecards tracking On-Time In-Full (OTIF %) delivery and defect rates. [DOMAIN]: Domain K: Supply Chain, Procurement & Warehousing. [GRAIN]: One row per supplier per month (scorecard_id). [TIER & REFRESH]: GOLD_CURATED | Batch Monthly. [ANALYTICAL ROLE]: Supply Chain - Supplier OTIF Delivery & Quality Scorecards.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_k_supply_chain", "diagnostic_role": "procurement_wms", "grain": "supplier_month", "update_frequency": "batch_daily", "environment": "production"}
    },
    "inbound_dock_appointments": {
        "description": "[PURPOSE]: Warehouse inbound freight dock door appointment schedules, carrier arrival timestamps, and trailer unloading durations. [DOMAIN]: Domain K: Supply Chain, Procurement & Warehousing. [GRAIN]: One row per freight dock appointment (appointment_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Batch Daily @ 05:00 UTC. [ANALYTICAL ROLE]: Warehouse Logistics - Inbound Dock Dwell Times & Freight Staging.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_k_supply_chain", "diagnostic_role": "procurement_wms", "grain": "dock_appointment", "update_frequency": "batch_daily", "environment": "production"}
    },
    "warehouse_zones": {
        "description": "[PURPOSE]: Warehouse physical floor zones (e.g. Mezzanine, Cold Storage, High-Bay Racking) and climate control parameters. [DOMAIN]: Domain K: Supply Chain, Procurement & Warehousing. [GRAIN]: One row per warehouse physical zone (zone_id). [TIER & REFRESH]: GOLD_CURATED | Master Static. [ANALYTICAL ROLE]: Warehouse Infrastructure - Physical Zone Topology.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_k_supply_chain", "diagnostic_role": "procurement_wms", "grain": "warehouse_zone", "update_frequency": "static", "environment": "production"}
    },
    "warehouse_aisles_and_racks": {
        "description": "[PURPOSE]: Storage bin locations, aisle coordinates, vertical rack levels, and maximum weight capacity limits. [DOMAIN]: Domain K: Supply Chain, Procurement & Warehousing. [GRAIN]: One row per physical storage bin (bin_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Master Static. [ANALYTICAL ROLE]: Warehouse Infrastructure - Bin Location Coordinates.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_k_supply_chain", "diagnostic_role": "procurement_wms", "grain": "storage_bin", "update_frequency": "static", "environment": "production"}
    },
    "pallet_inventory_locations": {
        "description": "[PURPOSE]: Real-time pallet License Plate Number (LPN) tracking linking physical pallets to warehouse bin coordinates. [DOMAIN]: Domain K: Supply Chain, Procurement & Warehousing. [GRAIN]: One row per pallet LPN (pallet_lpn). [TIER & REFRESH]: SILVER_CONSOLIDATED | Real-Time Barcode Scan Sync. [ANALYTICAL ROLE]: WMS Operations - Pallet LPN Real-Time Tracking.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_k_supply_chain", "diagnostic_role": "procurement_wms", "grain": "pallet_lpn", "update_frequency": "streaming", "environment": "production"}
    },
    "warehouse_labor_shifts": {
        "description": "[PURPOSE]: Warehouse worker labor shift schedules, picking tasks completed, and units picked per hour for logistics fulfillment. [DOMAIN]: Domain K: Supply Chain, Procurement & Warehousing. [GRAIN]: One row per employee shift (shift_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Batch Daily @ 06:00 UTC. [ANALYTICAL ROLE]: Warehouse Labor - Fulfillment Picking Productivity.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_k_supply_chain", "diagnostic_role": "procurement_wms", "grain": "labor_shift", "update_frequency": "batch_daily", "environment": "production"}
    },
    "forklift_telemetry_logs": {
        "description": "[PURPOSE]: Material handling equipment (forklift) IoT telemetry, battery state of charge, odometer readings, and maintenance alerts. [DOMAIN]: Domain K: Supply Chain, Procurement & Warehousing. [GRAIN]: One row per equipment telemetry ping (telemetry_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Real-Time IoT Ingestion. [ANALYTICAL ROLE]: Warehouse IoT - Equipment Maintenance & Fleet Health.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_k_supply_chain", "diagnostic_role": "procurement_wms", "grain": "equipment_telemetry", "update_frequency": "streaming", "environment": "production"}
    },
    "cross_dock_transfer_orders": {
        "description": "[PURPOSE]: Inter-hub inventory transfer shipments moving stock between regional distribution centers across Europe. [DOMAIN]: Domain K: Supply Chain, Procurement & Warehousing. [GRAIN]: One row per inter-hub transfer shipment (transfer_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Batch Daily @ 05:00 UTC. [ANALYTICAL ROLE]: Supply Chain - Inter-DC Inventory Balancing Transfers.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_k_supply_chain", "diagnostic_role": "procurement_wms", "grain": "transfer_order", "update_frequency": "batch_daily", "environment": "production"}
    },
    "freight_carrier_contracts": {
        "description": "[PURPOSE]: Master freight carrier commercial service contracts, contracted base rates per kilogram, and fuel surcharge formulas. [DOMAIN]: Domain K: Supply Chain, Procurement & Warehousing. [GRAIN]: One row per carrier contract (contract_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Master Static. [ANALYTICAL ROLE]: Logistics Contracts - Freight Rate Schedules.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_k_supply_chain", "diagnostic_role": "procurement_wms", "grain": "carrier_contract", "update_frequency": "static", "environment": "production"}
    },
    "customs_and_duties_declarations": {
        "description": "[PURPOSE]: International import customs declarations, Harmonized System (HS) tariff codes, and paid import duty amounts in EUR. [DOMAIN]: Domain K: Supply Chain, Procurement & Warehousing. [GRAIN]: One row per customs import entry (declaration_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Batch Daily @ 04:00 UTC. [ANALYTICAL ROLE]: International Trade - Import Tariffs & Customs Compliance.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_k_supply_chain", "diagnostic_role": "procurement_wms", "grain": "customs_declaration", "update_frequency": "batch_daily", "environment": "production"}
    },

    # -------------------------------------------------------------
    # DOMAIN L: Finance, General Ledger, Tax & Accounting (12 Tables)
    # -------------------------------------------------------------
    "chart_of_accounts": {
        "description": "[PURPOSE]: Master general ledger chart of accounts defining corporate asset, liability, equity, revenue, and expense account codes. [DOMAIN]: Domain L: Finance, General Ledger, Tax & Accounting. [GRAIN]: One row per financial account (account_number). [TIER & REFRESH]: GOLD_CURATED | Master Static. [ANALYTICAL ROLE]: Corporate Accounting - Chart of Accounts Master Reference.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_l_finance", "diagnostic_role": "general_ledger_tax", "grain": "gl_account", "update_frequency": "static", "environment": "production"}
    },
    "general_ledger_journal_entries": {
        "description": "[PURPOSE]: Official enterprise general ledger accounting journal header entries recording double-entry bookkeeping debits and credits for monthly corporate financial closes. [DOMAIN]: Domain L: Finance, General Ledger, Tax & Accounting. [GRAIN]: One row per journal posting header (journal_id). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 04:00 UTC. [ANALYTICAL ROLE]: Corporate Finance - Statutory General Ledger Bookkeeping.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_l_finance", "diagnostic_role": "general_ledger_tax", "grain": "journal_header", "update_frequency": "batch_daily", "environment": "production"}
    },
    "gl_journal_lines": {
        "description": "[PURPOSE]: Granular debit and credit line item postings mapped to chart of accounts codes for general ledger reconciliation. [DOMAIN]: Domain L: Finance, General Ledger, Tax & Accounting. [GRAIN]: One row per accounting journal line (line_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Batch Daily @ 04:00 UTC. [ANALYTICAL ROLE]: Corporate Accounting - Journal Debit/Credit Line Items.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_l_finance", "diagnostic_role": "general_ledger_tax", "grain": "journal_line", "update_frequency": "batch_daily", "environment": "production"}
    },
    "accounts_payable_invoices": {
        "description": "[PURPOSE]: Vendor accounts payable (AP) commercial invoices, invoice amounts in EUR, payment due dates, and approval statuses. [DOMAIN]: Domain L: Finance, General Ledger, Tax & Accounting. [GRAIN]: One row per vendor invoice (invoice_id). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 03:00 UTC. [ANALYTICAL ROLE]: Corporate Treasury - Accounts Payable Invoices & Vendor Obligations.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_l_finance", "diagnostic_role": "general_ledger_tax", "grain": "ap_invoice", "update_frequency": "batch_daily", "environment": "production"}
    },
    "accounts_payable_disbursements": {
        "description": "[PURPOSE]: Outbound cash disbursement payments executed to settle vendor accounts payable invoices. [DOMAIN]: Domain L: Finance, General Ledger, Tax & Accounting. [GRAIN]: One row per payment disbursement (disbursement_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Batch Daily @ 03:00 UTC. [ANALYTICAL ROLE]: Corporate Treasury - Outbound Cash Disbursements.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_l_finance", "diagnostic_role": "general_ledger_tax", "grain": "ap_disbursement", "update_frequency": "batch_daily", "environment": "production"}
    },
    "accounts_receivable_invoices": {
        "description": "[PURPOSE]: B2B corporate client billing invoices, accounts receivable balances, credit terms, and payment settlement tracking. [DOMAIN]: Domain L: Finance, General Ledger, Tax & Accounting. [GRAIN]: One row per corporate billing invoice (ar_invoice_id). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 03:00 UTC. [ANALYTICAL ROLE]: Corporate Finance - B2B Accounts Receivable Billing & DSO.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_l_finance", "diagnostic_role": "general_ledger_tax", "grain": "ar_invoice", "update_frequency": "batch_daily", "environment": "production"}
    },
    "bank_account_reconciliation": {
        "description": "[PURPOSE]: Monthly corporate bank account balance reconciliations comparing statement ending balances against general ledger cash. [DOMAIN]: Domain L: Finance, General Ledger, Tax & Accounting. [GRAIN]: One row per bank account reconciliation period (reconciliation_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Batch Monthly. [ANALYTICAL ROLE]: Corporate Treasury - Cash Balance & Bank Reconciliation.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_l_finance", "diagnostic_role": "general_ledger_tax", "grain": "bank_reconciliation", "update_frequency": "batch_daily", "environment": "production"}
    },
    "vat_tax_jurisdictions": {
        "description": "[PURPOSE]: Master European Value Added Tax (VAT) rate tables across European destination countries and standard/reduced rate categories. [DOMAIN]: Domain L: Finance, General Ledger, Tax & Accounting. [GRAIN]: One row per country tax jurisdiction (country_code). [TIER & REFRESH]: GOLD_CURATED | Master Static. [ANALYTICAL ROLE]: Tax Compliance - European Destination VAT Rates.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_l_finance", "diagnostic_role": "general_ledger_tax", "grain": "tax_jurisdiction", "update_frequency": "static", "environment": "production"}
    },
    "vat_period_filing_reports": {
        "description": "[PURPOSE]: Periodic statutory VAT tax return filings summarizing taxable sales revenue and collected output VAT across European jurisdictions. [DOMAIN]: Domain L: Finance, General Ledger, Tax & Accounting. [GRAIN]: One row per tax return filing period (filing_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Batch Monthly. [ANALYTICAL ROLE]: Tax Compliance - Statutory VAT Period Return Filings.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_l_finance", "diagnostic_role": "general_ledger_tax", "grain": "vat_filing", "update_frequency": "batch_daily", "environment": "production"}
    },
    "currency_exchange_rates_daily": {
        "description": "[PURPOSE]: Daily foreign currency exchange rates benchmarking EUR against USD, GBP, CHF, and other major trading currencies. [DOMAIN]: Domain L: Finance, General Ledger, Tax & Accounting. [GRAIN]: One row per currency per calendar day (currency_code, date). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 00:30 UTC. [ANALYTICAL ROLE]: Treasury & Pricing - Daily Foreign Exchange FX Rates.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_l_finance", "diagnostic_role": "general_ledger_tax", "grain": "fx_rate_day", "update_frequency": "batch_daily", "environment": "production"}
    },
    "intercompany_transfer_pricing": {
        "description": "[PURPOSE]: Cross-border intercompany transfer pricing schedules and cost-plus markup percentages between European corporate subsidiaries. [DOMAIN]: Domain L: Finance, General Ledger, Tax & Accounting. [GRAIN]: One row per transfer pricing relationship (schedule_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Master Static. [ANALYTICAL ROLE]: Tax & Treasury - Intercompany Transfer Pricing Schedules.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_l_finance", "diagnostic_role": "general_ledger_tax", "grain": "transfer_pricing", "update_frequency": "static", "environment": "production"}
    },
    "payment_gateway_fee_schedules": {
        "description": "[PURPOSE]: Contracted merchant interchange fee percentages and fixed per-transaction processing fees across Stripe, PayPal, and Adyen. [DOMAIN]: Domain L: Finance, General Ledger, Tax & Accounting. [GRAIN]: One row per payment gateway schedule (gateway_name, effective_date). [TIER & REFRESH]: SILVER_CONSOLIDATED | Master Static. [ANALYTICAL ROLE]: Payment Operations - Merchant Interchange Fee Schedules.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_l_finance", "diagnostic_role": "general_ledger_tax", "grain": "gateway_fee", "update_frequency": "static", "environment": "production"}
    },

    # -------------------------------------------------------------
    # DOMAIN M: Loyalty, Customer Retention & Rewards (10 Tables)
    # -------------------------------------------------------------
    "loyalty_members": {
        "description": "[PURPOSE]: Customer loyalty program membership profiles, reward tier standings (Silver, Gold, Platinum), and active point balances. [DOMAIN]: Domain M: Loyalty, Customer Retention & Rewards. [GRAIN]: One row per loyalty member account (membership_id). [TIER & REFRESH]: GOLD_CURATED | Real-Time Sync. [ANALYTICAL ROLE]: Retention Marketing - Loyalty Member Profiles & Balances.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_m_loyalty", "diagnostic_role": "loyalty_retention", "grain": "loyalty_member", "update_frequency": "streaming", "environment": "production"}
    },
    "loyalty_tier_definitions": {
        "description": "[PURPOSE]: Loyalty program tier qualification rules, annual spend thresholds in EUR, and promotional point earning multipliers. [DOMAIN]: Domain M: Loyalty, Customer Retention & Rewards. [GRAIN]: One row per loyalty tier level (tier_name). [TIER & REFRESH]: GOLD_CURATED | Master Static. [ANALYTICAL ROLE]: Retention Marketing - Tier Multipliers & Benefit Rules.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_m_loyalty", "diagnostic_role": "loyalty_retention", "grain": "loyalty_tier", "update_frequency": "static", "environment": "production"}
    },
    "loyalty_points_ledger": {
        "description": "[PURPOSE]: Detailed transactional audit ledger recording loyalty points earned from purchases, bonus campaigns, and point expirations. [DOMAIN]: Domain M: Loyalty, Customer Retention & Rewards. [GRAIN]: One row per loyalty point transaction event (ledger_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Real-Time Ledger Posting. [ANALYTICAL ROLE]: Retention Marketing - Granular Points Earn & Expiration Ledger.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_m_loyalty", "diagnostic_role": "loyalty_retention", "grain": "points_transaction", "update_frequency": "streaming", "environment": "production"}
    },
    "loyalty_reward_redemptions": {
        "description": "[PURPOSE]: Member reward redemption events converting accumulated loyalty points into discount vouchers or merchandise gifts. [DOMAIN]: Domain M: Loyalty, Customer Retention & Rewards. [GRAIN]: One row per reward redemption (redemption_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Real-Time Event Sync. [ANALYTICAL ROLE]: Retention Marketing - Reward Redemption Rates & Burn.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_m_loyalty", "diagnostic_role": "loyalty_retention", "grain": "reward_redemption", "update_frequency": "streaming", "environment": "production"}
    },
    "discount_coupons_master": {
        "description": "[PURPOSE]: Marketing promotional coupon codes, percentage discount values, minimum order thresholds, and expiration dates. [DOMAIN]: Domain M: Loyalty, Customer Retention & Rewards. [GRAIN]: One row per discount coupon definition (coupon_id). [TIER & REFRESH]: GOLD_CURATED | Master Static. [ANALYTICAL ROLE]: Merchandising - Promo Code Rules & Discount Depths.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_m_loyalty", "diagnostic_role": "loyalty_retention", "grain": "discount_coupon", "update_frequency": "static", "environment": "production"}
    },
    "coupon_redemption_audit": {
        "description": "[PURPOSE]: Audit logs recording every checkout coupon code application, user ID, and monetary discount amount realized in EUR. [DOMAIN]: Domain M: Loyalty, Customer Retention & Rewards. [GRAIN]: One row per checkout coupon application (audit_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Real-Time Streaming Checkout Sync. [ANALYTICAL ROLE]: Promotion Forensics - Order Coupon Redemptions & Margin Impact.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_m_loyalty", "diagnostic_role": "loyalty_retention", "grain": "coupon_redemption", "update_frequency": "streaming", "environment": "production"}
    },
    "referral_program_invites": {
        "description": "[PURPOSE]: Customer referral invitation tracking, unique referral links, and recipient invitation delivery logs. [DOMAIN]: Domain M: Loyalty, Customer Retention & Rewards. [GRAIN]: One row per referral invitation dispatched (invite_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Event-Driven Sync. [ANALYTICAL ROLE]: Growth Marketing - Referral Program Invites & Viral Expansion.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_m_loyalty", "diagnostic_role": "loyalty_retention", "grain": "referral_invite", "update_frequency": "streaming", "environment": "production"}
    },
    "referral_reward_claims": {
        "description": "[PURPOSE]: Referral rewards credited to advocating customers upon successful order completion by referred friends. [DOMAIN]: Domain M: Loyalty, Customer Retention & Rewards. [GRAIN]: One row per referral bonus claim (claim_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Batch Daily @ 03:00 UTC. [ANALYTICAL ROLE]: Growth Marketing - Referral Reward Payouts & CAC Efficiency.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_m_loyalty", "diagnostic_role": "loyalty_retention", "grain": "reward_claim", "update_frequency": "batch_daily", "environment": "production"}
    },
    "gift_card_master": {
        "description": "[PURPOSE]: Electronic and physical gift card registry, initial balances in EUR, current remaining balances, and activation states. [DOMAIN]: Domain M: Loyalty, Customer Retention & Rewards. [GRAIN]: One row per issued gift card (card_id). [TIER & REFRESH]: GOLD_CURATED | Real-Time Balance Sync. [ANALYTICAL ROLE]: Customer Finance - Gift Card Issuance & Outstanding Liability.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_m_loyalty", "diagnostic_role": "loyalty_retention", "grain": "gift_card", "update_frequency": "streaming", "environment": "production"}
    },
    "gift_card_transactions": {
        "description": "[PURPOSE]: Individual debit and top-up transactions charged against customer gift card balances during checkout. [DOMAIN]: Domain M: Loyalty, Customer Retention & Rewards. [GRAIN]: One row per gift card redemption transaction (transaction_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Real-Time Transaction Append. [ANALYTICAL ROLE]: Payment Accounting - Gift Card Redemptions at Checkout.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_m_loyalty", "diagnostic_role": "loyalty_retention", "grain": "gift_card_transaction", "update_frequency": "streaming", "environment": "production"}
    },

    # -------------------------------------------------------------
    # DOMAIN N: Lifecycle Marketing, Email & Push (10 Tables)
    # -------------------------------------------------------------
    "email_campaign_templates": {
        "description": "[PURPOSE]: Marketing email templates, subject line A/B test variations, and creative layouts for automated CRM lifecycle journeys. [DOMAIN]: Domain N: Lifecycle Marketing, Email & Push. [GRAIN]: One row per email template (template_id). [TIER & REFRESH]: GOLD_CURATED | Master Static. [ANALYTICAL ROLE]: Lifecycle Marketing - Email Template Master & A/B Copy.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_n_lifecycle", "diagnostic_role": "lifecycle_messaging", "grain": "email_template", "update_frequency": "static", "environment": "production"}
    },
    "email_send_queue_logs": {
        "description": "[PURPOSE]: Outbound email dispatch queue execution logs, deliverability statuses, and send timestamps. [DOMAIN]: Domain N: Lifecycle Marketing, Email & Push. [GRAIN]: One row per dispatched email transmission (send_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Real-Time Dispatch Log. [ANALYTICAL ROLE]: Lifecycle Operations - Outbound Email Queue & Send Latency.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_n_lifecycle", "diagnostic_role": "lifecycle_messaging", "grain": "email_send", "update_frequency": "streaming", "environment": "production"}
    },
    "email_bounces_and_complaints": {
        "description": "[PURPOSE]: Hard/soft email bounce records, spam complaints, and invalid email addresses for sender reputation management. [DOMAIN]: Domain N: Lifecycle Marketing, Email & Push. [GRAIN]: One row per bounce or complaint event (bounce_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Event-Driven Ingestion. [ANALYTICAL ROLE]: Deliverability - Email Bounce Rates & Reputation Safeguards.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_n_lifecycle", "diagnostic_role": "lifecycle_messaging", "grain": "bounce_event", "update_frequency": "streaming", "environment": "production"}
    },
    "sms_marketing_broadcasts": {
        "description": "[PURPOSE]: SMS text marketing campaign broadcasts, promotional message copy, and targeted customer cohort segments. [DOMAIN]: Domain N: Lifecycle Marketing, Email & Push. [GRAIN]: One row per SMS marketing campaign (sms_campaign_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Batch Daily Sync. [ANALYTICAL ROLE]: Lifecycle Marketing - SMS Marketing Campaigns & Copy.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_n_lifecycle", "diagnostic_role": "lifecycle_messaging", "grain": "sms_campaign", "update_frequency": "batch_daily", "environment": "production"}
    },
    "sms_delivery_receipts": {
        "description": "[PURPOSE]: Telecommunications carrier SMS delivery receipts and handset delivery confirmations. [DOMAIN]: Domain N: Lifecycle Marketing, Email & Push. [GRAIN]: One row per SMS message delivery receipt (receipt_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Real-Time Webhook Append. [ANALYTICAL ROLE]: Deliverability - SMS Handset Delivery Receipts.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_n_lifecycle", "diagnostic_role": "lifecycle_messaging", "grain": "sms_receipt", "update_frequency": "streaming", "environment": "production"}
    },
    "mobile_app_push_campaigns": {
        "description": "[PURPOSE]: Mobile app push notification broadcasts, rich media titles, and deep link targets for iOS/Android apps. [DOMAIN]: Domain N: Lifecycle Marketing, Email & Push. [GRAIN]: One row per push campaign broadcast (push_campaign_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Batch Daily Sync. [ANALYTICAL ROLE]: App Marketing - Push Notification Campaigns & Deeplinks.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_n_lifecycle", "diagnostic_role": "lifecycle_messaging", "grain": "push_campaign", "update_frequency": "batch_daily", "environment": "production"}
    },
    "push_notification_receipts": {
        "description": "[PURPOSE]: Individual mobile app push notification delivery receipts and user tap/click interactions. [DOMAIN]: Domain N: Lifecycle Marketing, Email & Push. [GRAIN]: One row per push receipt event (push_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Real-Time Telemetry Stream. [ANALYTICAL ROLE]: App Marketing - Push Notification Click-Through Telemetry.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_n_lifecycle", "diagnostic_role": "lifecycle_messaging", "grain": "push_receipt", "update_frequency": "streaming", "environment": "production"}
    },
    "user_subscription_preferences": {
        "description": "[PURPOSE]: Customer communication consent settings, marketing opt-ins (email, SMS, push), and GDPR compliance timestamps. [DOMAIN]: Domain N: Lifecycle Marketing, Email & Push. [GRAIN]: One row per customer communication preference (preference_id). [TIER & REFRESH]: GOLD_CURATED | Real-Time Sync. [ANALYTICAL ROLE]: Consent Compliance - Marketing Channel Opt-in Registry.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_n_lifecycle", "diagnostic_role": "lifecycle_messaging", "grain": "user_preference", "update_frequency": "streaming", "environment": "production"}
    },
    "affiliate_publishers_directory": {
        "description": "[PURPOSE]: Third-party affiliate publisher networks, promotional partners, and contracted commission rates. [DOMAIN]: Domain N: Lifecycle Marketing, Email & Push. [GRAIN]: One row per affiliate partner (affiliate_id). [TIER & REFRESH]: GOLD_CURATED | Master Static. [ANALYTICAL ROLE]: Partner Marketing - Affiliate Publisher Directory & Rates.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_n_lifecycle", "diagnostic_role": "lifecycle_messaging", "grain": "affiliate_publisher", "update_frequency": "static", "environment": "production"}
    },
    "affiliate_commission_payouts": {
        "description": "[PURPOSE]: Monthly affiliate publisher commission calculations, attributed sales volume in EUR, and payout approval records. [DOMAIN]: Domain N: Lifecycle Marketing, Email & Push. [GRAIN]: One row per affiliate monthly billing statement (payout_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Batch Monthly. [ANALYTICAL ROLE]: Partner Marketing - Affiliate Commission Payout Statements.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_n_lifecycle", "diagnostic_role": "lifecycle_messaging", "grain": "affiliate_payout", "update_frequency": "batch_daily", "environment": "production"}
    },

    # -------------------------------------------------------------
    # DOMAIN O: Product Information Management (PIM) (8 Tables)
    # -------------------------------------------------------------
    "product_attribute_definitions": {
        "description": "[PURPOSE]: Master Product Information Management (PIM) attribute definitions (e.g. skin_type, battery_capacity, fabric_composition). [DOMAIN]: Domain O: Product Information Management (PIM). [GRAIN]: One row per attribute definition (attribute_id). [TIER & REFRESH]: GOLD_CURATED | Master Static. [ANALYTICAL ROLE]: Catalog Management - Master PIM Specification Schema.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_o_pim", "diagnostic_role": "pim_catalog_specs", "grain": "attribute_definition", "update_frequency": "static", "environment": "production"}
    },
    "product_attribute_values": {
        "description": "[PURPOSE]: EAV (Entity-Attribute-Value) structured technical product specifications and filter criteria for catalog search. [DOMAIN]: Domain O: Product Information Management (PIM). [GRAIN]: One row per SKU attribute value assignment (value_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Batch Daily @ 01:00 UTC. [ANALYTICAL ROLE]: Catalog Management - SKU Attribute Value Specifications.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_o_pim", "diagnostic_role": "pim_catalog_specs", "grain": "attribute_value", "update_frequency": "batch_daily", "environment": "production"}
    },
    "product_multilingual_translations": {
        "description": "[PURPOSE]: Localized product titles and marketing descriptions translated into French, German, Italian, Spanish, and Dutch. [DOMAIN]: Domain O: Product Information Management (PIM). [GRAIN]: One row per SKU per language translation (translation_id). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 01:00 UTC. [ANALYTICAL ROLE]: Localization - Multilingual Catalog Copy & Descriptions.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_o_pim", "diagnostic_role": "pim_catalog_specs", "grain": "translation", "update_frequency": "batch_daily", "environment": "production"}
    },
    "product_media_gallery": {
        "description": "[PURPOSE]: High-resolution product images, video URLs, CDN asset paths, and display sort orders. [DOMAIN]: Domain O: Product Information Management (PIM). [GRAIN]: One row per media visual asset (media_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Batch Daily @ 01:00 UTC. [ANALYTICAL ROLE]: Digital Assets - Product Image CDN Gallery.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_o_pim", "diagnostic_role": "pim_catalog_specs", "grain": "media_asset", "update_frequency": "batch_daily", "environment": "production"}
    },
    "product_size_charts": {
        "description": "[PURPOSE]: Category size conversion tables, body measurements in centimeters, and international size mapping. [DOMAIN]: Domain O: Product Information Management (PIM). [GRAIN]: One row per size chart specification (size_chart_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Master Static. [ANALYTICAL ROLE]: Apparel Merchandising - Size Chart Measurement Specs.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_o_pim", "diagnostic_role": "pim_catalog_specs", "grain": "size_chart", "update_frequency": "static", "environment": "production"}
    },
    "product_brand_guidelines": {
        "description": "[PURPOSE]: Manufacturer minimum advertised price (MAP) policies, brand authorization rules, and trademark guidelines. [DOMAIN]: Domain O: Product Information Management (PIM). [GRAIN]: One row per brand guideline (guideline_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Master Static. [ANALYTICAL ROLE]: Merchandising Compliance - Brand MAP Guidelines.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_o_pim", "diagnostic_role": "pim_catalog_specs", "grain": "brand_guideline", "update_frequency": "static", "environment": "production"}
    },
    "category_hierarchy_paths": {
        "description": "[PURPOSE]: Materialized category hierarchy breadcrumb paths for fast e-commerce storefront navigation and facet filtering. [DOMAIN]: Domain O: Product Information Management (PIM). [GRAIN]: One row per hierarchical category path (path_id). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 01:00 UTC. [ANALYTICAL ROLE]: Catalog Navigation - Materialized Category Tree Paths.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_o_pim", "diagnostic_role": "pim_catalog_specs", "grain": "hierarchy_path", "update_frequency": "batch_daily", "environment": "production"}
    },
    "seo_meta_tags_registry": {
        "description": "[PURPOSE]: Search engine optimization (SEO) title tags, meta descriptions, and canonical URLs across all web catalog pages. [DOMAIN]: Domain O: Product Information Management (PIM). [GRAIN]: One row per indexed page URL (seo_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Batch Daily @ 01:00 UTC. [ANALYTICAL ROLE]: Organic Search - SEO Meta Tags & Canonical Registry.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_o_pim", "diagnostic_role": "pim_catalog_specs", "grain": "seo_tag", "update_frequency": "batch_daily", "environment": "production"}
    },

    # -------------------------------------------------------------
    # DOMAIN P: Retail Physical Stores & Omni-Channel POS (8 Tables)
    # -------------------------------------------------------------
    "physical_store_locations": {
        "description": "[PURPOSE]: Master directory of brick-and-mortar retail stores, address geolocations, floor square meters, and opening status. [DOMAIN]: Domain P: Retail Physical Stores & Omni-Channel POS. [GRAIN]: One row per retail store branch (store_id). [TIER & REFRESH]: GOLD_CURATED | Master Static. [ANALYTICAL ROLE]: Retail Store Operations - Physical Store Location Directory.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_p_pos_stores", "diagnostic_role": "pos_retail_operations", "grain": "store_location", "update_frequency": "static", "environment": "production"}
    },
    "pos_terminal_registers": {
        "description": "[PURPOSE]: Point of Sale (POS) checkout terminal registers, hardware models, serial numbers, and IP address bindings. [DOMAIN]: Domain P: Retail Physical Stores & Omni-Channel POS. [GRAIN]: One row per POS terminal register (register_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Master Static. [ANALYTICAL ROLE]: Store Hardware - POS Cash Register Terminal Master.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_p_pos_stores", "diagnostic_role": "pos_retail_operations", "grain": "pos_terminal", "update_frequency": "static", "environment": "production"}
    },
    "pos_store_transactions": {
        "description": "[PURPOSE]: In-store brick-and-mortar point-of-sale customer sales transactions, cashier employee IDs, and payment tender types. [DOMAIN]: Domain P: Retail Physical Stores & Omni-Channel POS. [GRAIN]: One row per in-store checkout transaction header (pos_transaction_id). [TIER & REFRESH]: GOLD_CURATED | Real-Time POS Sync. [ANALYTICAL ROLE]: Retail Store Operations - In-Store Physical POS Revenue & Receipts.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_p_pos_stores", "diagnostic_role": "pos_retail_operations", "grain": "pos_transaction", "update_frequency": "streaming", "environment": "production"}
    },
    "pos_transaction_items": {
        "description": "[PURPOSE]: Granular purchase line items sold through physical store cash registers. [DOMAIN]: Domain P: Retail Physical Stores & Omni-Channel POS. [GRAIN]: One row per in-store purchased item line (pos_item_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Real-Time POS Sync. [ANALYTICAL ROLE]: Store Merchandising - In-Store SKU Basket Contribution.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_p_pos_stores", "diagnostic_role": "pos_retail_operations", "grain": "pos_item", "update_frequency": "streaming", "environment": "production"}
    },
    "click_and_collect_orders": {
        "description": "[PURPOSE]: Buy Online Pick Up in Store (BOPIS) orders, store pickup verification PINs, customer collection timestamps, and fulfillment states. [DOMAIN]: Domain P: Retail Physical Stores & Omni-Channel POS. [GRAIN]: One row per BOPIS pickup order (bopis_id). [TIER & REFRESH]: GOLD_CURATED | Real-Time Order Stream. [ANALYTICAL ROLE]: Omni-Channel Fulfillment - Click & Collect (BOPIS) Store Pickups.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_p_pos_stores", "diagnostic_role": "pos_retail_operations", "grain": "bopis_order", "update_frequency": "streaming", "environment": "production"}
    },
    "store_inventory_levels": {
        "description": "[PURPOSE]: Real-time store on-hand stock quantities, shelf availability, and periodic cycle count audit dates per retail location. [DOMAIN]: Domain P: Retail Physical Stores & Omni-Channel POS. [GRAIN]: One row per SKU per retail store (store_stock_id). [TIER & REFRESH]: GOLD_CURATED | Batch Daily @ 05:00 UTC. [ANALYTICAL ROLE]: Store Operations - Physical Shelf Stock & Cycle Counts.",
        "labels": {"data_tier": "gold_curated", "domain": "domain_p_pos_stores", "diagnostic_role": "pos_retail_operations", "grain": "store_sku_stock", "update_frequency": "batch_daily", "environment": "production"}
    },
    "store_employee_rosters": {
        "description": "[PURPOSE]: In-store retail employee staffing rosters, shift schedules, and operational store roles (Cashier, Floor Supervisor). [DOMAIN]: Domain P: Retail Physical Stores & Omni-Channel POS. [GRAIN]: One row per store employee shift (roster_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Batch Daily @ 06:00 UTC. [ANALYTICAL ROLE]: Store Operations - Store Employee Work Schedules.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_p_pos_stores", "diagnostic_role": "pos_retail_operations", "grain": "store_roster", "update_frequency": "batch_daily", "environment": "production"}
    },
    "store_cash_drawer_counts": {
        "description": "[PURPOSE]: Daily store register cash drawer end-of-shift balancing logs and physical cash counting variances in EUR. [DOMAIN]: Domain P: Retail Physical Stores & Omni-Channel POS. [GRAIN]: One row per register drawer cash count (drawer_count_id). [TIER & REFRESH]: SILVER_CONSOLIDATED | Batch Daily @ 23:00 UTC. [ANALYTICAL ROLE]: Store Audit - End-of-Day Register Cash Balancing.",
        "labels": {"data_tier": "silver_consolidated", "domain": "domain_p_pos_stores", "diagnostic_role": "pos_retail_operations", "grain": "drawer_count", "update_frequency": "batch_daily", "environment": "production"}
    },

    # -------------------------------------------------------------
    # DOMAIN Q: Non-Production, Sandbox & QA Archives (10 Tables)
    # -------------------------------------------------------------
    "dev_customer_churn_feature_store": {
        "description": "[PURPOSE]: Machine learning feature store containing customer behavioral aggregations and predicted churn risk scores. [DOMAIN]: Domain Q: Non-Production, Sandbox & QA Archives. [GRAIN]: One row per customer feature vector (user_id). [TIER & REFRESH]: SANDBOX_QA | Ad-Hoc Experimental. [ANALYTICAL ROLE]: Experimental Sandbox - ML Feature Store.",
        "labels": {"data_tier": "sandbox_qa", "domain": "domain_q_sandbox", "diagnostic_role": "sandbox_experimental", "grain": "feature_vector", "update_frequency": "batch_daily", "environment": "sandbox"}
    },
    "dev_product_embedding_vectors": {
        "description": "[PURPOSE]: Product catalog semantic embedding vector embeddings for experimental visual similarity models. [DOMAIN]: Domain Q: Non-Production, Sandbox & QA Archives. [GRAIN]: One row per product vector embedding (product_id). [TIER & REFRESH]: SANDBOX_QA | Ad-Hoc Experimental. [ANALYTICAL ROLE]: Experimental Sandbox - Vector Embeddings.",
        "labels": {"data_tier": "sandbox_qa", "domain": "domain_q_sandbox", "diagnostic_role": "sandbox_experimental", "grain": "embedding_vector", "update_frequency": "batch_daily", "environment": "sandbox"}
    },
    "qa_load_test_sessions_backup": {
        "description": "[PURPOSE]: Archived load test benchmark traffic logs generated by synthetic load testing tools. [DOMAIN]: Domain Q: Non-Production, Sandbox & QA Archives. [GRAIN]: One row per load test synthetic run (test_run_id). [TIER & REFRESH]: SANDBOX_QA | QA Archive. [ANALYTICAL ROLE]: QA Sandbox - Synthetic Load Testing Logs.",
        "labels": {"data_tier": "sandbox_qa", "domain": "domain_q_sandbox", "diagnostic_role": "sandbox_experimental", "grain": "load_test_run", "update_frequency": "static", "environment": "sandbox"}
    },
    "qa_checkout_synthetic_fuzz_tests": {
        "description": "[PURPOSE]: Automated checkout synthetic fuzz testing payloads and HTTP response code validations. [DOMAIN]: Domain Q: Non-Production, Sandbox & QA Archives. [GRAIN]: One row per fuzz test execution (fuzz_id). [TIER & REFRESH]: SANDBOX_QA | QA Automated Suite. [ANALYTICAL ROLE]: QA Sandbox - Synthetic Fuzz Test Results.",
        "labels": {"data_tier": "sandbox_qa", "domain": "domain_q_sandbox", "diagnostic_role": "sandbox_experimental", "grain": "fuzz_test", "update_frequency": "static", "environment": "sandbox"}
    },
    "sandbox_dynamic_pricing_sim_v1": {
        "description": "[PURPOSE]: Offline dynamic pricing simulator sandbox estimating price elasticity curves and revenue trade-offs. [DOMAIN]: Domain Q: Non-Production, Sandbox & QA Archives. [GRAIN]: One row per pricing simulation run (sim_id). [TIER & REFRESH]: SANDBOX_QA | Sandbox Simulator. [ANALYTICAL ROLE]: QA Sandbox - Offline Pricing Simulation.",
        "labels": {"data_tier": "sandbox_qa", "domain": "domain_q_sandbox", "diagnostic_role": "sandbox_experimental", "grain": "pricing_sim", "update_frequency": "static", "environment": "sandbox"}
    },
    "sandbox_search_ranking_ab_test": {
        "description": "[PURPOSE]: Search ranking algorithm A/B experiment evaluation logs recording NDCG@10 relevance scores. [DOMAIN]: Domain Q: Non-Production, Sandbox & QA Archives. [GRAIN]: One row per search experiment evaluation (experiment_id). [TIER & REFRESH]: SANDBOX_QA | Search Science Sandbox. [ANALYTICAL ROLE]: Search Science Sandbox - Search Algorithm A/B Tests.",
        "labels": {"data_tier": "sandbox_qa", "domain": "domain_q_sandbox", "diagnostic_role": "sandbox_experimental", "grain": "search_experiment", "update_frequency": "static", "environment": "sandbox"}
    },
    "legacy_orders_2023_archive": {
        "description": "[PURPOSE]: Deprecated archive of historical 2023 customer order headers retained for legal and compliance audit. [DOMAIN]: Domain Q: Non-Production, Sandbox & QA Archives. [GRAIN]: One row per archived legacy order (legacy_order_id). [TIER & REFRESH]: SANDBOX_QA | Cold Storage Archive. [ANALYTICAL ROLE]: Legacy Archive - 2023 Historical Orders Archive.",
        "labels": {"data_tier": "sandbox_qa", "domain": "domain_q_sandbox", "diagnostic_role": "sandbox_experimental", "grain": "legacy_order", "update_frequency": "static", "environment": "sandbox"}
    },
    "legacy_products_deprecated": {
        "description": "[PURPOSE]: Discontinued catalog products and end-of-life merchandise from previous retail seasons. [DOMAIN]: Domain Q: Non-Production, Sandbox & QA Archives. [GRAIN]: One row per discontinued SKU (legacy_product_id). [TIER & REFRESH]: SANDBOX_QA | Cold Storage Archive. [ANALYTICAL ROLE]: Legacy Archive - Discontinued Product Archive.",
        "labels": {"data_tier": "sandbox_qa", "domain": "domain_q_sandbox", "diagnostic_role": "sandbox_experimental", "grain": "legacy_product", "update_frequency": "static", "environment": "sandbox"}
    },
    "test_fraud_mock_transactions": {
        "description": "[PURPOSE]: Synthetic fraud model test transactions evaluating rule triggers and mock transaction risks. [DOMAIN]: Domain Q: Non-Production, Sandbox & QA Archives. [GRAIN]: One row per mock transaction (mock_id). [TIER & REFRESH]: SANDBOX_QA | Test Synthetic Dataset. [ANALYTICAL ROLE]: Fraud Sandbox - Synthetic Fraud Rule Tests.",
        "labels": {"data_tier": "sandbox_qa", "domain": "domain_q_sandbox", "diagnostic_role": "sandbox_experimental", "grain": "mock_transaction", "update_frequency": "static", "environment": "sandbox"}
    },
    "test_carrier_webhook_payloads": {
        "description": "[PURPOSE]: Synthetic logistics carrier webhook testing fixtures for development mocking and contract verification. [DOMAIN]: Domain Q: Non-Production, Sandbox & QA Archives. [GRAIN]: One row per synthetic webhook payload (test_payload_id). [TIER & REFRESH]: SANDBOX_QA | Test Synthetic Fixture. [ANALYTICAL ROLE]: Logistics Sandbox - Carrier Webhook Test Fixtures.",
        "labels": {"data_tier": "sandbox_qa", "domain": "domain_q_sandbox", "diagnostic_role": "sandbox_experimental", "grain": "mock_webhook", "update_frequency": "static", "environment": "sandbox"}
    }
}

# ----------------------------------------------------------------------------------------------------------------------
# COLUMN DESCRIPTIONS: Full Schema Column Descriptions across All Tables
# ----------------------------------------------------------------------------------------------------------------------
COLUMN_DESCRIPTIONS = {
    # Core Domain A-G Column Schemas
    "categories": {
        "category_id": "Unique identifier for the product category (Primary Key)",
        "parent_category_id": "Self-referencing link to parent category for hierarchy",
        "name": "Display name of the category (e.g., Beauty, Electronics, Fashion, Home)",
        "slug": "URL-safe slug text string"
    },
    "products": {
        "product_id": "Unique master identifier for the product (Primary Key)",
        "category_id": "Foreign key to categories table",
        "name": "Full retail product name",
        "sku": "Stock Keeping Unit code",
        "brand": "Brand or manufacturer name",
        "retail_price": "Default selling price in EUR",
        "cost": "Acquisition and production cost in EUR",
        "is_active": "Catalog visibility flag"
    },
    "distribution_centers": {
        "dc_id": "Unique identifier for the logistics hub (Primary Key)",
        "name": "Logistics hub name (e.g. Paris Nord Fulfilment Centre, Rotterdam Port Hub)",
        "latitude": "Hub geolocation latitude",
        "longitude": "Hub geolocation longitude"
    },
    "inventory_items": {
        "inventory_item_id": "Unique identifier for stock batch (Primary Key)",
        "product_id": "Foreign key to products table",
        "dc_id": "Foreign key to distribution_centers table",
        "quantity_on_hand": "Physical units currently available in stock",
        "safety_stock_level": "Safety stock threshold for reorder alerts",
        "created_at": "Batch intake timestamp"
    },
    "inventory_snapshots": {
        "snapshot_id": "System tracking snapshot identifier (Primary Key)",
        "product_id": "Foreign key to products table",
        "recorded_at": "Snapshot capture timestamp",
        "stock_quantity": "Units remaining at snapshot time",
        "is_out_of_stock": "Boolean flag indicating zero stock quantity"
    },
    "users": {
        "user_id": "Customer account identifier (Primary Key)",
        "email": "Customer contact email address",
        "first_name": "Customer given name",
        "last_name": "Customer surname",
        "gender": "Self-identified demographic gender",
        "age": "Customer age in years",
        "country": "Customer localization country (e.g. France, Germany)",
        "latitude": "Customer geolocation coordinate latitude",
        "longitude": "Customer geolocation coordinate longitude",
        "created_at": "Account creation timestamp"
    },
    "orders": {
        "order_id": "Transaction header identifier (Primary Key)",
        "user_id": "Foreign key to users table",
        "session_id": "Originating web session referencing web_sessions.session_id. Join on this to attribute an order to its acquisition channel",
        "order_status": "Fulfilment outcome, derived from the order's line items: 'Completed' (nothing returned), 'Partially Returned' (some lines returned), 'Returned' (every line returned). All three are genuinely placed, paid orders. A failed payment attempt never becomes an order and appears only in payment_gateway_logs with a NULL order_id",
        "total_amount": "Merchandise value of the order in EUR, equal to the sum of sale_price x quantity across its order_items. Excludes VAT (see tax_amount) and delivery charges (see shipping_fee), which are held separately and are not revenue. Not reduced for items subsequently returned",
        "tax_amount": "VAT tax portion of transaction in EUR",
        "shipping_fee": "Shipping delivery fee billed in EUR",
        "num_of_items": "Total physical items count in order",
        "created_at": "Transaction execution timestamp"
    },
    "order_items": {
        "order_item_id": "Transaction line item identifier (Primary Key)",
        "ord_hdr_num": "Foreign key referencing master orders.order_id",
        "user_id": "Foreign key to users table",
        "mat_nr": "Material article identifier referencing products.product_id",
        "inventory_item_id": "Foreign key to inventory_items table",
        "quantity": "Quantity of product units purchased",
        "sale_price": "Captured unit selling price at checkout in EUR",
        "discount_amount": "Reserved field for per-line promotional discount in EUR. NOT POPULATED by any source system and always 0.00; the promotions feed is not connected. A sum of zero indicates an absent feed, not an absence of discounting",
        "created_at": "Line item creation timestamp",
        "shipped_at": "Logistics carrier dispatch timestamp",
        "delivered_at": "Customer delivery confirmation timestamp",
        "returned_at": "Timestamp the returned item was received back. NULL for items that were not returned, so this column is the basis for distinguishing gross from net merchandise revenue"
    },
    "sales_event_stream": {
        "event_id": "Streaming event UUID identifier (Primary Key)",
        "order_id": "Foreign key to orders table",
        "product_id": "Foreign key to products table",
        "category_id": "Foreign key to categories table",
        "quantity": "Count of units sold",
        "sale_price": "Captured base unit price in EUR",
        "discount_amount": "Reserved field for per-event promotional discount in EUR. NOT POPULATED by any source system and always 0.00; mirrors order_items.discount_amount",
        "timestamp": "Real-time streaming ingestion timestamp"
    },
    "weekly_commercial_targets": {
        "target_id": "Commercial target identifier (Primary Key)",
        "category_id": "Foreign key to categories table",
        "week_start_date": "Target week start date (2026-11-23)",
        "target_revenue": "Total planned commercial revenue target in EUR",
        "target_sessions": "Expected web traffic sessions",
        "target_conversion_rate": "Target e-commerce conversion rate (CVR)"
    },
    "daily_category_targets": {
        "target_id": "Daily target identifier (Primary Key)",
        "category_id": "Foreign key to categories table",
        "date": "Target calendar date (2026-11-23 to 2026-11-30)",
        "target_revenue": "Daily planned category revenue in EUR",
        "target_sessions": "Daily planned web session traffic target",
        "target_conversion_rate": "Expected conversion rate benchmark",
        "target_aov": "Expected average order value in EUR",
        "target_ad_spend": "Allocated paid marketing ad spend budget in EUR",
        "target_roas": "Target return on ad spend multiplier benchmark"
    },
    "category_15min_targets": {
        "target_id": "15-minute pacing target identifier (Primary Key)",
        "category_id": "Foreign key to categories table",
        "day_of_week": "Day of week integer (1=Sunday..7=Saturday)",
        "time_bucket": "15-minute time bucket",
        "target_revenue": "Planned revenue target for the 15-minute interval in EUR",
        "target_sessions": "Planned web sessions traffic for the interval"
    },
    "web_sessions": {
        "session_id": "Unique browser session UUID (Primary Key)",
        "user_id": "Customer profile identifier (nullable)",
        "traffic_source": "Origin channel (Paid Search, Paid Social, Direct, Email, Organic)",
        "utm_source": "UTM campaign source tag (google, meta, criteo, newsletter)",
        "utm_medium": "UTM medium tag (cpc, social, email, referral)",
        "utm_campaign": "UTM campaign tag",
        "primary_category_id": "Category the session predominantly browsed, referencing categories.category_id",
        "device_os": "Client operating system (iOS, Android, Windows, macOS). This is the device dimension for this table; there is no separate device_category column",
        "browser": "Client web browser (Safari, Chrome, Firefox, Edge)",
        "country": "Visitor country from the IP lookup. Present even when the visitor is not signed in and user_id is NULL, so it is the correct basis for geographic session analysis. Matches users.country for known customers",
        "session_started_at": "Timestamp of the first interaction in the session",
        "session_ended_at": "Timestamp of the last recorded interaction. Session duration is session_ended_at minus session_started_at, and is zero when the session produced no further events",
        "page_views_count": "Navigations to a new page during the session. A SUBSET of the rows in web_events, not a copy of them: in-page interactions such as filter_applied, image_zoom, review_read, wishlist_add and cart_add are recorded as events but are not page views",
        "converted_to_order": "Boolean flag indicating if session converted to a purchase"
    },
    "web_events": {
        "event_id": "Unique event identifier (Primary Key)",
        "session_id": "Foreign key to web_sessions table",
        "product_id": "Foreign key to products table (nullable)",
        "event_type": "Funnel event type (page_view, product_view, cart_add, checkout_start, checkout_success)",
        "page_url": "Page URL path",
        "metadata": "JSON metadata payload",
        "created_at": "Event interaction timestamp"
    },
    "oos_interactions": {
        "interaction_id": "Out of stock interaction identifier (Primary Key)",
        "session_id": "Foreign key to web_sessions table",
        "art_code": "Catalog article SKU code referencing products.product_id",
        "clicked_at": "Interaction timestamp",
        "pot_val": "Potential order value of the unavailable item at list price (unit retail price x requested quantity). GROSS unrealised demand only - this is NOT a net revenue loss, because a share of these visitors buy a substitute instead. Summing this column overstates lost revenue by more than an order of magnitude; use the certified stockout_lost_revenue methodology."
    },
    "competitor_price_feed": {
        "scrape_id": "Scraped pricing feed identifier (Primary Key)",
        "product_id": "Foreign key to products table",
        "competitor_name": "Competitor retail brand (e.g. SephoraEU, DouglasDE, LookFantastic)",
        "competitor_price": "Competitor retail selling price in EUR",
        "is_in_stock": "Whether the competitor had the item available at the moment of the scrape",
        "scraped_at": "Feed scraping timestamp"
    },
    "competitor_promotions": {
        "promo_id": "Competitor promotion identifier (Primary Key)",
        "competitor_name": "Competitor brand name",
        "category_id": "Foreign key to categories table",
        "discount_pct": "Promotional discount percentage (e.g. 20.0%)",
        "promotion_title": "Promotion as the competitor advertised it (e.g. Sitewide Flash 20% Off)",
        "start_date": "Promotion validity start date",
        "end_date": "Promotion validity end date",
        "price_index_vs_lumiere": "Competitor price divided by the LumiereShop price for the same category. Above 1.0 means the competitor is the more expensive of the two",
        "scraped_at": "Timestamp the promotion was scraped from the competitor site"
    },
    "marketing_campaigns": {
        "campaign_id": "Marketing campaign identifier (Primary Key)",
        "target_category_id": "Category this campaign promotes, referencing categories.category_id",
        "name": "Campaign display name",
        "platform": "Advertising platform (Meta Ads, Google Ads, TikTok)",
        "bidding_strategy": "Automated bidding algorithm (Target ROAS, Maximize Conversions, Manual CPC)",
        "is_active": "Whether the campaign is live. This is the only state this table records; it carries no budget, no date range and no throttling state"
    },
    "daily_ad_performance": {
        "performance_id": "Ad performance record identifier (Primary Key)",
        "cid_ref": "External marketing campaign identifier referencing marketing_campaigns.campaign_id",
        "date": "Calendar tracking date (2026-11-23 to 2026-11-27)",
        "impressions": "Total ad impressions served",
        "clicks": "Total ad clicks generated",
        "spend": "Total advertising expenditure in EUR",
        "conversions": "Total attributed order conversions count",
        "average_cpc": "Average cost per click in EUR"
    },
    "ad_bidding_log": {
        "log_id": "Bidding telemetry log identifier (Primary Key)",
        "campaign_id": "Foreign key to marketing_campaigns table",
        "status_change": "Bidding platform state reported at this evaluation",
        "action_taken": "Machine-emitted action code applied by the bidding engine",
        "observed_cvr_7d": "Trailing 7-day conversion rate observed by the bidding engine at evaluation time",
        "target_roas_multiplier": "Ratio of observed return on ad spend to the configured target. Below 1.0 means the campaign is underperforming its ROAS target",
        "budget_multiplier": "Fraction of the planned daily budget the engine permitted after evaluation. Below 1.0 means spend was capped",
        "bid_adjustment_pct": "Percentage change applied to the bid ceiling at this evaluation",
        "logged_at": "Machine execution timestamp"
    },
    "ad_creatives": {
        "creative_id": "Creative asset identifier (Primary Key)",
        "parent_adgroup_id": "Parent marketing campaign hierarchy identifier referencing marketing_campaigns.campaign_id",
        "name": "Creative asset name",
        "ad_format": "Creative format (Video, Carousel, Static Image)",
        "quality_score": "Ad platform quality score (1 to 10 scale)",
        "dlv_lrn_lmt_flg": "Delivery learning-limited flag: TRUE when the ad platform reports the creative is not receiving enough conversion signal to exit the learning phase, which constrains delivery and raises effective cost per click",
        "relevance_status": "Relevance status (ACTIVE, FATIGUED, LOW_QUALITY)",
        "last_refreshed_at": "Timestamp when creative asset was last updated"
    },
    "payment_gateway_logs": {
        "gateway_log_id": "PSP authorization log identifier (Primary Key)",
        "order_id": "Foreign key to orders table",
        "session_id": "Foreign key to web_sessions table",
        "payment_provider": "Payment service provider (Stripe, PayPal, Adyen)",
        "payment_method": "Instrument the customer paid with (card, wallet, bank transfer)",
        "status": "Transaction status (SUCCESS, FAILED, TIMEOUT)",
        "error_code": "Gateway error code (e.g. HTTP_504_GATEWAY_TIMEOUT, CARD_DECLINED)",
        "http_status_code": "HTTP status the gateway returned for the authorization call",
        "latency_ms": "Authorization latency in milliseconds",
        "total_amount": "Transaction amount in EUR",
        "country": "Country the payment was initiated from",
        "created_at": "Gateway transaction timestamp"
    },
    "influencer_campaigns": {
        "influencer_id": "Creator campaign identifier (Primary Key)",
        "campaign_name": "Creator campaign display name",
        "creator_name": "Social media creator handle (e.g. @elena.glowroutine, @marc.techdaily)",
        "platform": "Creator platform (Instagram, TikTok, YouTube)",
        "promo_code": "Discount code issued to the creator. This is what attributes an order back to the campaign; there is no category column on this table",
        "target_revenue": "Contractual commercial target revenue in EUR",
        "actual_revenue": "Revenue attributed to this creator's promo code in EUR",
        "orders_count": "Orders attributed to this creator's promo code",
        "views_count": "Impressions the creator's content received on the platform",
        "fee_amount": "Flat fee paid to the creator in EUR",
        "is_active": "Whether the creator campaign is still running",
        "created_at": "Timestamp the campaign record was created"
    },
    "catalog_recommender_logs": {
        "log_id": "Recommendation impression log identifier (Primary Key)",
        "session_id": "Foreign key to web_sessions table",
        "src_sku": "Source product item viewed on active page (FK to products)",
        "rec_sku": "Recommended product candidate suggested by ML engine (FK to products)",
        "page_category_id": "Category of the product on the page being viewed, referencing categories.category_id",
        "recommended_category_id": "Category of the recommended product, referencing categories.category_id",
        "fb_rule_id": "Rule engine identifier: 99 = global category fallback, 0 = standard collaborative filter",
        "cat_mismatch_flg": "Cross-department mismatch flag: 1 when the recommended item's category differs from the page's category, 0 otherwise",
        "user_action": "Visitor action (BOUNCED, CLICKED, IGNORED)",
        "opp_cost_eur": "Reserved field for per-impression opportunity cost. NOT POPULATED by the recommender service; opportunity cost must be derived from bounced impressions and category conversion propensity",
        "recorded_at": "Impression timestamp"
    },
    "shipping_lead_times": {
        "lead_time_id": "Lead time operational record identifier (Primary Key)",
        "date": "Operational date (2026-11-23 to 2026-11-27)",
        "dc_id": "Foreign key to distribution_centers table",
        "destination_region": "Destination delivery country (France, DACH, Benelux)",
        "carrier_name": "Logistics carrier (DHL, Chronopost, DPD)",
        "standard_lead_time_hours": "Standard promised delivery SLA in hours (e.g. 24h)",
        "actual_promised_lead_time_hours": "Real-time checkout promised delivery SLA in hours (e.g. 48h)",
        "capacity_utilization_pct": "Warehouse and carrier capacity utilization percentage",
        "cart_abandonment_impact_pct": "Attributed checkout abandonment percentage from SLA breach",
        "estimated_lost_revenue": "Estimated lost checkout revenue in EUR"
    },
    "agent_interaction_logs": {
        "interaction_id": "Conversational analytics session UUID (Primary Key)",
        "session_id": "Identifier of user session or conversation thread",
        "user_name": "User identifier or display name submitting the analytics inquiry",
        "user_account": "User email or account identity executing prompt",
        "user_prompt": "Natural language user prompt",
        "response_text": "Markdown response text generated by the agent",
        "generated_sql": "Dynamic BigQuery SQL query generated by Gemini Data Agent",
        "job_id": "BigQuery execution job identifier for the generated query",
        "execution_time_ms": "Total query and agent latency in milliseconds",
        "bytes_billed": "BigQuery bytes billed for the generated query",
        "bytes_scanned": "BigQuery bytes scanned before billing rounding",
        "slot_milliseconds": "BigQuery slot milliseconds consumed",
        "http_status_code": "HTTP status returned by the Conversational Analytics API call",
        "ca_api_endpoint": "Conversational Analytics API endpoint invoked",
        "data_agent_id": "Data agent that produced the answer, which identifies the metadata tier it was configured with",
        "referenced_tables": "Tables the generated SQL actually read",
        "result_row_count": "Rows returned by the generated query",
        "step_count": "Number of reasoning steps returned in the agent response",
        "has_chart": "Whether the answer carried a chart specification",
        "chart_type": "Chart type produced with the answer, when there was one",
        "followup_questions": "Follow-up questions the agent proposed",
        "thinking_process": "Agent reasoning trace captured from the API response",
        "thinking_mode": "Reasoning verbosity the agent ran in for this interaction",
        "raw_ca_api_response": "Unparsed Conversational Analytics API payload, retained for audit",
        "created_at": "Timestamp the interaction was recorded",
        "menu_item": "Interface menu context initiating the interaction ('chat' vs 'compare chats')",
        "agent_no": "Agent identifier in comparative multi-agent mode ('agentA', 'agentB', 'agentC', or NULL for single agent)"
    }
}

# Dynamically merge column descriptions for all extended enterprise warehouse tables
try:
    import importlib.util
    _ext_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "11_create_extended_schema.py")
    if os.path.exists(_ext_path):
        _spec = importlib.util.spec_from_file_location("ext_schemas", _ext_path)
        _ext_mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_ext_mod)
        for _t_name, _schema in getattr(_ext_mod, "EXTENDED_TABLE_SCHEMAS", {}).items():
            if _t_name not in COLUMN_DESCRIPTIONS:
                _col_map = {}
                for _f in _schema.get("fields", []):
                    _col_map[_f.name] = _f.description
                COLUMN_DESCRIPTIONS[_t_name] = _col_map
except Exception as _e:
    pass

def get_access_token():
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
    return token

def apply_descriptions():
    print(f"Applying BigQuery 5-Part Functional Metadata, Medallion Labels & Column Annotations for `{PROJECT_ID}.{DATASET_ID}`...")
    token = get_access_token()
    if token:
        creds = oauth2_credentials.Credentials(token)
        client = bigquery.Client(project=PROJECT_ID, credentials=creds)
    else:
        client = bigquery.Client(project=PROJECT_ID)

    updated_count = 0
    total_tables = len(TABLE_METADATA)
    stale_keys = []          # documented here, absent from the live table
    undocumented = []        # present in the live table, no curated description

    for table_name, meta in TABLE_METADATA.items():
        desc = meta["description"]
        labels = meta.get("labels", {})
        table_ref = f"{PROJECT_ID}.{DATASET_ID}.{table_name}"
        try:
            table = client.get_table(table_ref)
            table.description = desc
            table.labels = labels

            # Update column descriptions if defined
            if table_name in COLUMN_DESCRIPTIONS:
                col_map = COLUMN_DESCRIPTIONS[table_name]
                live_names = {f.name for f in table.schema}
                for key in col_map:
                    if key not in live_names:
                        stale_keys.append(f"{table_name}.{key}")
                new_fields = []
                for field in table.schema:
                    new_desc = col_map.get(field.name, field.description)
                    if not new_desc:
                        undocumented.append(f"{table_name}.{field.name}")
                    new_field = bigquery.SchemaField(
                        name=field.name,
                        field_type=field.field_type,
                        mode=field.mode,
                        description=new_desc,
                        fields=field.fields
                    )
                    new_fields.append(new_field)
                table.schema = new_fields
                client.update_table(table, ["description", "labels", "schema"])
            else:
                client.update_table(table, ["description", "labels"])

            updated_count += 1
            print(f"  ✅ Updated `{table_name}` (Tier: {labels.get('data_tier', 'N/A')}, Domain: {labels.get('domain', 'N/A')})")
        except Exception as e:
            # Notice for local execution when network/token is stubbed
            print(f"Notice updating table `{table_name}`: {e}", file=sys.stderr)

    print(f"\nCompleted metadata synchronization across {updated_count}/{total_tables} warehouse tables in BigQuery.")

    # ---------------------------------------------------------------
    # Schema drift report.
    #
    # `col_map.get(field.name, field.description)` silently ignores keys that
    # no longer exist, which is exactly how this file fell out of sync with
    # 01_create_schema.py. Tier A is the tier whose whole value proposition is
    # rich metadata, so an undocumented column here is a real defect.
    # ---------------------------------------------------------------
    print("\n" + "=" * 78)
    print("SCHEMA DRIFT REPORT")
    print("=" * 78)
    if stale_keys:
        print(f"\n⚠️  {len(stale_keys)} documented column(s) do NOT exist in BigQuery "
              f"(dead entries, silently ignored):")
        for key in sorted(stale_keys):
            print(f"     • {key}")
    else:
        print("\n✅ No stale column entries.")

    if undocumented:
        print(f"\n⚠️  {len(undocumented)} live column(s) have NO description at all "
              f"(Tier A quality gap):")
        for key in sorted(undocumented):
            print(f"     • {key}")
    else:
        print("✅ Every live column carries a description.")
    print("=" * 78)

if __name__ == "__main__":
    apply_descriptions()
