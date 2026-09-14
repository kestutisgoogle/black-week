import yaml
import json
import os

with open("config/business_glossary.yaml.bak", "r") as f:
    base = yaml.safe_load(f)["glossary"]

categories = base["categories"]
terms = base["terms"]

# Add 3 new categories if missing
existing_cat_ids = {c["id"] for c in categories}

new_categories = [
    {
        "id": "lifecycle_marketing",
        "display_name": "Lifecycle Marketing, Email & Campaigns",
        "description": "Email deliverability, template conversions, bounce tracking, affiliate publisher commissions, and coupon promotions."
    },
    {
        "id": "staging_ingestion",
        "display_name": "Raw Ingestion & Third-Party Partner Feeds",
        "description": "Staging pipelines and raw API feeds from Shopify, Meta, Google Ads, Stripe, Adyen, Zendesk, SAP ERP, and GA4."
    },
    {
        "id": "data_governance",
        "display_name": "Data Governance, Quality & Interaction Auditing",
        "description": "Agent interaction logs, query execution telemetry, data profiling scans, and table access auditing."
    }
]

for nc in new_categories:
    if nc["id"] not in existing_cat_ids:
        categories.append(nc)
        existing_cat_ids.add(nc["id"])

# 33 New Detailed Terms covering Domains H-Q
new_terms = [
    # --- Returns & RMA (Domain I) ---
    {
        "id": "rma_authorization_rate",
        "display_name": "RMA Authorization Rate",
        "category_id": "returns_rma",
        "definition": "Percentage of completed orders that result in a return merchandise authorization (RMA) request.",
        "formula": "COUNT(DISTINCT product_returns.return_id) / COUNT(DISTINCT orders.order_id)",
        "synonyms": ["return rate", "return merchandise authorization", "RMA percentage", "order return ratio"],
        "bindings": [{"table": "product_returns", "column": "return_id"}, {"table": "return_reasons_lookup", "column": "reason_code"}]
    },
    {
        "id": "defective_return_rate",
        "display_name": "Defective Inspection Rate",
        "category_id": "returns_rma",
        "definition": "Ratio of returned items classified as defective or damaged upon warehouse triage inspection.",
        "formula": "COUNTIF(return_inspections.condition_grade = 'DEFECTIVE') / COUNT(return_inspections.inspection_id)",
        "synonyms": ["damaged return rate", "inspection defect ratio", "faulty goods percentage"],
        "bindings": [{"table": "return_inspections", "column": "condition_grade"}, {"table": "return_shipping_labels", "column": "tracking_number"}]
    },
    {
        "id": "refund_processing_latency",
        "display_name": "Refund Payout Processing Latency",
        "category_id": "returns_rma",
        "definition": "Average duration in hours from customer return receipt to financial refund disbursement.",
        "formula": "AVG(TIMESTAMP_DIFF(customer_refunds.created_at, product_returns.created_at, HOUR))",
        "synonyms": ["refund turnaround time", "refund payout speed", "customer refund delay"],
        "bindings": [{"table": "customer_refunds", "column": "amount_eur"}]
    },

    # --- Customer Support & CRM (Domain J) ---
    {
        "id": "first_contact_resolution_rate",
        "display_name": "First Contact Resolution (FCR) Rate",
        "category_id": "customer_service",
        "definition": "Percentage of incoming support tickets resolved in a single interaction without follow-up escalation.",
        "formula": "COUNTIF(support_tickets.reopened_count = 0 AND support_tickets.status = 'RESOLVED') / COUNT(support_tickets.ticket_id)",
        "synonyms": ["FCR", "one-touch resolution", "single contact fix rate"],
        "bindings": [{"table": "support_tickets", "column": "status"}, {"table": "ticket_categories", "column": "category_name"}]
    },
    {
        "id": "ticket_backlog_volume",
        "display_name": "Customer Support Ticket Backlog",
        "category_id": "customer_service",
        "definition": "Total count of unresolved or pending customer service tickets across support queues.",
        "formula": "COUNTIF(support_tickets.status IN ('OPEN', 'PENDING', 'IN_PROGRESS'))",
        "synonyms": ["support backlog", "open ticket queue", "unresolved ticket count", "helpdesk queue depth"],
        "bindings": [{"table": "support_tickets", "column": "priority"}, {"table": "ticket_messages", "column": "sender_type"}]
    },
    {
        "id": "csat_net_score",
        "display_name": "CSAT (Customer Satisfaction Score)",
        "category_id": "customer_service",
        "definition": "Average customer satisfaction rating recorded on post-ticket resolution surveys on a 1-5 scale.",
        "formula": "AVG(csat_surveys.csat_score)",
        "synonyms": ["customer satisfaction", "CSAT rating", "support quality score", "customer happiness index"],
        "bindings": [{"table": "csat_surveys", "column": "csat_score"}, {"table": "support_agents", "column": "tier_level"}]
    },
    {
        "id": "customer_escalation_rate",
        "display_name": "Customer Escalation Incident Rate",
        "category_id": "customer_service",
        "definition": "Percentage of customer support inquiries escalated to senior management or tier-3 support teams.",
        "formula": "COUNT(customer_escalations.escalation_id) / COUNT(support_tickets.ticket_id)",
        "synonyms": ["tier 3 escalation", "manager escalation rate", "critical complaint volume"],
        "bindings": [{"table": "customer_escalations", "column": "escalation_reason"}, {"table": "agent_worklog_shifts", "column": "shift_type"}, {"table": "call_center_recordings_metadata", "column": "call_duration_seconds"}]
    },

    # --- Supply Chain, WMS & Procurement (Domain K) ---
    {
        "id": "purchase_order_fill_rate",
        "display_name": "Purchase Order (PO) Fill Rate",
        "category_id": "supply_chain",
        "definition": "Percentage of ordered units successfully received against supplier purchase order line commitments.",
        "formula": "SUM(purchase_order_line_items.received_quantity) / SUM(purchase_order_line_items.ordered_quantity)",
        "synonyms": ["PO fulfillment rate", "supplier fill rate", "procurement receipt ratio"],
        "bindings": [{"table": "purchase_orders", "column": "po_status"}, {"table": "purchase_order_line_items", "column": "ordered_quantity"}]
    },
    {
        "id": "supplier_on_time_delivery_rate",
        "display_name": "Supplier On-Time Inbound Delivery (OTD) Rate",
        "category_id": "supply_chain",
        "definition": "Percentage of supplier purchase orders delivered to fulfillment hubs on or before the agreed contractual SLA date.",
        "formula": "COUNTIF(purchase_orders.actual_delivery_date <= purchase_orders.expected_delivery_date) / COUNT(purchase_orders.po_id)",
        "synonyms": ["supplier OTD", "inbound delivery timeliness", "supplier SLA compliance"],
        "bindings": [{"table": "suppliers_master", "column": "country_code"}, {"table": "supplier_lead_time_history", "column": "actual_lead_time_days"}, {"table": "supplier_quality_scorecards", "column": "overall_score"}]
    },
    {
        "id": "warehouse_aisle_cube_utilization",
        "display_name": "Warehouse Aisle & Rack Cube Utilization",
        "category_id": "supply_chain",
        "definition": "Percentage of total volumetric storage capacity currently occupied across warehouse aisles and storage racks.",
        "formula": "SUM(warehouse_aisles_and_racks.occupied_cube_meters) / SUM(warehouse_aisles_and_racks.total_cube_meters)",
        "synonyms": ["storage rack density", "cube utilization", "warehouse space utilization", "aisle occupancy"],
        "bindings": [{"table": "warehouse_aisles_and_racks", "column": "utilization_pct"}, {"table": "warehouse_zones", "column": "zone_type"}, {"table": "warehouse_labor_shifts", "column": "hours_worked"}]
    },
    {
        "id": "inbound_dock_turnaround_time",
        "display_name": "Inbound Dock Appointment Turnaround Time",
        "category_id": "supply_chain",
        "definition": "Average elapsed time from carrier truck arrival at the inbound dock to container unload and putaway completion.",
        "formula": "AVG(TIMESTAMP_DIFF(inbound_dock_appointments.unload_end_time, inbound_dock_appointments.arrival_time, MINUTE))",
        "synonyms": ["dock dwell time", "cross dock turnaround", "freight unloading latency"],
        "bindings": [{"table": "inbound_dock_appointments", "column": "status"}, {"table": "cross_dock_transfer_orders", "column": "transfer_status"}, {"table": "forklift_telemetry_logs", "column": "battery_level_pct"}, {"table": "freight_carrier_contracts", "column": "base_rate_eur"}, {"table": "warehouse_refurbishments", "column": "refurbishment_cost_eur"}]
    },

    # --- Finance, Tax & General Ledger (Domain L) ---
    {
        "id": "accounts_payable_aging_days",
        "display_name": "Accounts Payable (AP) Days Outstanding (DPO)",
        "category_id": "finance",
        "definition": "Average number of days taken to settle vendor and supplier invoices from invoice receipt date.",
        "formula": "(SUM(accounts_payable_invoices.invoice_amount_eur) / SUM(purchase_order_line_items.unit_cost_eur * purchase_order_line_items.received_quantity)) * 365",
        "synonyms": ["DPO", "days payable outstanding", "AP invoice aging", "vendor payment latency"],
        "bindings": [{"table": "accounts_payable_invoices", "column": "invoice_amount_eur"}, {"table": "accounts_payable_disbursements", "column": "disbursement_amount_eur"}]
    },
    {
        "id": "gl_journal_entry_balance",
        "display_name": "General Ledger (GL) Debit-Credit Balance",
        "category_id": "finance",
        "definition": "Double-entry bookkeeping validation ensuring total debits equal total credits across all posted journal lines.",
        "formula": "SUM(gl_journal_lines.debit_amount_eur) - SUM(gl_journal_lines.credit_amount_eur)",
        "synonyms": ["trial balance check", "debit credit equality", "GL reconciliation", "journal line balance"],
        "bindings": [{"table": "general_ledger_journal_entries", "column": "journal_id"}, {"table": "gl_journal_lines", "column": "debit_amount_eur"}, {"table": "chart_of_accounts", "column": "account_number"}]
    },
    {
        "id": "bank_reconciliation_variance",
        "display_name": "Bank Statement Reconciliation Discrepancy",
        "category_id": "finance",
        "definition": "Unreconciled financial variance between bank statement settlement cash flows and internal general ledger cash accounts.",
        "formula": "SUM(bank_account_reconciliation.statement_balance_eur) - SUM(bank_account_reconciliation.ledger_balance_eur)",
        "synonyms": ["bank variance", "cash book reconciliation", "unsettled bank items"],
        "bindings": [{"table": "bank_account_reconciliation", "column": "discrepancy_amount_eur"}, {"table": "accounts_receivable_invoices", "column": "invoice_amount_eur"}, {"table": "currency_exchange_rates_daily", "column": "exchange_rate_to_eur"}, {"table": "customs_and_duties_declarations", "column": "duty_amount_eur"}]
    },

    # --- Customer Loyalty, Rewards & Retention (Domain M) ---
    {
        "id": "points_burn_earn_ratio",
        "display_name": "Loyalty Points Burn-to-Earn Ratio",
        "category_id": "loyalty_retention",
        "definition": "Proportion of issued loyalty reward points redeemed by customers relative to newly earned points.",
        "formula": "SUM(CASE WHEN points_delta < 0 THEN ABS(points_delta) ELSE 0 END) / SUM(CASE WHEN points_delta > 0 THEN points_delta ELSE 0 END)",
        "synonyms": ["burn to earn", "points redemption velocity", "loyalty point utilization rate"],
        "bindings": [{"table": "loyalty_points_ledger", "column": "points_delta"}, {"table": "loyalty_members", "column": "current_points_balance"}, {"table": "loyalty_reward_redemptions", "column": "reward_id"}, {"table": "loyalty_tier_definitions", "column": "tier_name"}]
    },
    {
        "id": "gift_card_breakage_rate",
        "display_name": "Gift Card Unredeemed Breakage Value",
        "category_id": "loyalty_retention",
        "definition": "Total monetary value of issued gift cards and store credit balances that remain unredeemed past expiration thresholds.",
        "formula": "SUM(gift_card_master.initial_balance_eur - gift_card_master.current_balance_eur)",
        "synonyms": ["unredeemed gift cards", "breakage revenue", "store credit float"],
        "bindings": [{"table": "gift_card_master", "column": "current_balance_eur"}, {"table": "gift_card_transactions", "column": "transaction_amount_eur"}, {"table": "store_credit_issuances", "column": "credit_amount_eur"}]
    },

    # --- Lifecycle Marketing & Email Campaigns (Domain N) ---
    {
        "id": "email_deliverability_rate",
        "display_name": "Email Campaign Deliverability Rate",
        "category_id": "lifecycle_marketing",
        "definition": "Percentage of dispatched promotional and lifecycle emails successfully accepted by recipient mail servers without hard or soft bounces.",
        "formula": "COUNTIF(email_send_queue_logs.status = 'DELIVERED') / COUNT(email_send_queue_logs.queue_id)",
        "synonyms": ["email delivery rate", "inbox placement rate", "deliverability percentage"],
        "bindings": [{"table": "email_send_queue_logs", "column": "status"}, {"table": "email_campaign_templates", "column": "subject_line"}, {"table": "email_bounces_and_complaints", "column": "bounce_type"}]
    },
    {
        "id": "affiliate_commission_yield",
        "display_name": "Affiliate Publisher Commission Yield",
        "category_id": "lifecycle_marketing",
        "definition": "Total partner commission payout generated per unit of net revenue driven by external affiliate publisher networks.",
        "formula": "SUM(affiliate_commission_payouts.commission_amount_eur) / SUM(affiliate_commission_payouts.attributed_revenue_eur)",
        "synonyms": ["affiliate payout rate", "partner publisher commission", "affiliate ROI"],
        "bindings": [{"table": "affiliate_commission_payouts", "column": "commission_amount_eur"}, {"table": "affiliate_publishers_directory", "column": "publisher_name"}, {"table": "discount_coupons_master", "column": "discount_percentage"}, {"table": "coupon_redemption_audit", "column": "discount_applied_eur"}]
    },

    # --- Product Information Management (PIM) (Domain O) ---
    {
        "id": "catalog_attribute_completeness_rate",
        "display_name": "PIM Product Attribute Completeness Rate",
        "category_id": "product_pim",
        "definition": "Percentage of active catalog SKUs possessing 100% of required merchandising attributes, translations, and media assets.",
        "formula": "COUNT(DISTINCT product_attribute_values.product_id) / COUNT(DISTINCT products.product_id)",
        "synonyms": ["PIM completeness", "catalog data quality", "attribute fullness", "SKU enrichment score"],
        "bindings": [{"table": "product_attribute_definitions", "column": "attribute_name"}, {"table": "product_attribute_values", "column": "attribute_value_text"}, {"table": "product_multilingual_translations", "column": "locale_code"}, {"table": "product_size_charts", "column": "fit_type"}, {"table": "product_media_gallery", "column": "media_type"}, {"table": "product_brand_guidelines", "column": "brand_name"}]
    },

    # --- Retail Physical Stores & Omni-Channel POS (Domain P) ---
    {
        "id": "bopis_fulfillment_sla_rate",
        "display_name": "Click & Collect (BOPIS) Ready-for-Pickup SLA Rate",
        "category_id": "omnichannel_pos",
        "definition": "Percentage of online click-and-collect orders picked, packed, and marked ready in physical store branches within the 2-hour customer promise SLA.",
        "formula": "COUNTIF(click_and_collect_orders.fulfillment_duration_minutes <= 120) / COUNT(click_and_collect_orders.order_id)",
        "synonyms": ["BOPIS SLA", "click and collect readiness", "curbside pickup fulfillment time", "store pickup SLA"],
        "bindings": [{"table": "click_and_collect_orders", "column": "pickup_status"}, {"table": "physical_store_locations", "column": "city"}, {"table": "pos_store_transactions", "column": "total_amount_eur"}, {"table": "pos_transaction_items", "column": "quantity"}, {"table": "pos_terminal_registers", "column": "register_number"}, {"table": "store_inventory_levels", "column": "quantity_in_store"}, {"table": "store_cash_drawer_counts", "column": "variance_eur"}, {"table": "store_employee_rosters", "column": "shift_role"}]
    },

    # --- Staging & Third-Party Ingestion Feeds (Domain H) ---
    {
        "id": "staging_pipeline_sync_latency",
        "display_name": "Third-Party Staging Pipeline Ingestion Latency",
        "category_id": "staging_ingestion",
        "definition": "Average time delay in minutes between upstream source API transaction timestamps and raw BigQuery staging table ingestion.",
        "formula": "AVG(TIMESTAMP_DIFF(stg_shopify_orders_raw._ingestion_timestamp, stg_shopify_orders_raw.created_at, MINUTE))",
        "synonyms": ["staging latency", "API ingestion delay", "ELT sync freshness", "raw feed latency"],
        "bindings": [
            {"table": "stg_shopify_orders_raw", "column": "raw_payload"},
            {"table": "stg_shopify_customers_raw", "column": "raw_payload"},
            {"table": "stg_shopify_products_raw", "column": "raw_payload"},
            {"table": "stg_meta_ad_insights_raw", "column": "raw_payload"},
            {"table": "stg_google_ads_campaigns_raw", "column": "raw_payload"},
            {"table": "stg_google_ads_search_terms_raw", "column": "raw_payload"},
            {"table": "stg_klaviyo_email_events_raw", "column": "raw_payload"},
            {"table": "stg_klaviyo_campaigns_raw", "column": "raw_payload"},
            {"table": "stg_stripe_payment_intents_raw", "column": "raw_payload"},
            {"table": "stg_stripe_disputes_raw", "column": "raw_payload"},
            {"table": "stg_adyen_settlements_raw", "column": "raw_payload"},
            {"table": "stg_zendesk_tickets_raw", "column": "raw_payload"},
            {"table": "stg_zendesk_satisfaction_raw", "column": "raw_payload"},
            {"table": "stg_sap_erp_inventory_feed_raw", "column": "raw_payload"},
            {"table": "stg_sap_erp_purchase_orders_raw", "column": "raw_payload"},
            {"table": "stg_criteo_retargeting_raw", "column": "raw_payload"},
            {"table": "stg_ga4_clickstream_raw", "column": "raw_payload"},
            {"table": "stg_ga4_traffic_sources_raw", "column": "raw_payload"},
            {"table": "stg_wms_shipments_raw", "column": "raw_payload"},
            {"table": "stg_trustpilot_reviews_raw", "column": "raw_payload"}
        ]
    },

    # --- Data Governance & Telemetry (Domain Q / Governance) ---
    {
        "id": "agent_query_slot_utilization",
        "display_name": "Conversational Agent Query Slot-Millisecond Efficiency",
        "category_id": "data_governance",
        "definition": "BigQuery slot-milliseconds and compute resources consumed by automated conversational analytics agents per SQL execution.",
        "formula": "AVG(agent_interaction_logs.slot_milliseconds)",
        "synonyms": ["slot consumption", "agent query compute", "BigQuery slot efficiency"],
        "bindings": [
            {"table": "agent_interaction_logs", "column": "slot_milliseconds"},
            {"table": "dev_customer_churn_feature_store", "column": "feature_timestamp"},
            {"table": "dev_product_embedding_vectors", "column": "embedding_version"}
        ]
    }
]

for nt in new_terms:
    terms.append(nt)

output_data = {
    "glossary": {
        "name": "ecommerce-glossary",
        "display_name": "LumièreShop Executive Retail Glossary (140 Tables)",
        "description": "Enterprise semantic glossary defining retail business metrics, e-commerce KPIs, operational failure modes, and BigQuery column bindings across all 17 domains for LumièreShop.",
        "categories": categories,
        "terms": terms
    }
}

# Write YAML
with open("config/business_glossary.yaml", "w") as f:
    yaml.dump(output_data, f, sort_keys=False, allow_unicode=True)

# NOTE: config/business_glossary.yaml is now the single source of truth.
# The JSON copy this script used to emit has been retired - it duplicated
# the same content in a second format with nothing keeping the two in step.

print(f"✅ Generated expanded business glossary: {len(categories)} categories, {len(terms)} terms.")
