#!/usr/bin/env python3
"""
Phase 2: Point-in-Time Calibrated E-Commerce Data Generator for LumièreShop.
Calendar: Black Week 2026 (Monday Nov 23 to Monday Nov 30, 2026).
- Planned Targets: Full 8-day promotional cycle (Nov 23 to Nov 30).
- Live Simulation Anchor: Friday, Nov 27, 2026 at 14:30:00 UTC (Black Friday Early Afternoon).
- Actuals & Operational Data: Strictly bounded within Monday Nov 23 00:00:00 to Friday Nov 27 14:30:00 UTC.

Statistical Ratios Calibrated:
1. Orders / Web Sessions ≈ 3.00% (26,285 orders / 876,000 sessions)
2. Successful Payments / Orders ≈ 92.5% (24,314 payments / 26,285 orders, within [0.90, 0.95])
3. Web Events per Session: 15 to 25 events on average (mean ≈ 18.5 events/session)
4. Full Investigation Case Study Ground Truths Preserved:
   - Beauty Shortfall: €530,000.00 (€1.950M target vs €1.420M actual)
   - Stockouts (SKU 1001-1003): €65,000.00 direct loss
   - Recommender Fallback Category Mismatch: €50,000.00 loss (1,250 sessions)
   - Target ROAS Ad Budget Throttling: €415,000.00 deficit (-31% spend on Nov 24)
   - PayPal 504 Timeouts: 48 failed transactions on Wed Nov 25 = €3,200.00
   - Influencer @GlowWithElena: €14k actual vs €25k target (€11k gap)
   - Frankfurt Logistics Bottleneck: 48h lead time on Thu Nov 26 = €18,000 loss in DACH
"""

import os
import sys
import gzip
import json
import uuid
import random
import tempfile
import shutil
import subprocess
import numpy as np
from datetime import datetime, timedelta, timezone
from google.cloud import bigquery
from google.oauth2 import credentials as oauth2_credentials

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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

# Strict Black Week 2026 Calendar Bounds
SIMULATION_START = datetime(2026, 11, 23, 0, 0, 0)        # Monday Nov 23, 2026 00:00:00 UTC
CURRENT_TIME = datetime(2026, 11, 27, 14, 30, 0)            # Black Friday Nov 27, 2026 14:30:00 UTC
SIMULATION_END_TARGETS = datetime(2026, 11, 30, 23, 59, 59) # Cyber Monday Nov 30, 2026 23:59:59 UTC

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
        creds = oauth2_credentials.Credentials(access_token)
        return bigquery.Client(project=project_id, credentials=creds)
    return bigquery.Client(project=project_id)

def load_ndjson_file_to_bq(client, table_name, file_path):
    table_ref = f"{PROJECT_ID}.{DATASET_ID}.{table_name}"
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        ignore_unknown_values=True
    )
    print(f"Uploading file to `{table_name}` via BigQuery LoadJob...")
    with open(file_path, "rb") as source_file:
        job = client.load_table_from_file(source_file, table_ref, job_config=job_config)
        job.result()
    print(f"Successfully loaded `{table_name}` from {os.path.basename(file_path)}.")

def generate_all_data():
    random.seed(42)
    np.random.seed(42)
    print("=" * 80)
    print("STARTING REALISTIC E-COMMERCE DATA GENERATION & RATIO CALIBRATION")
    print(f"GCP Project: {PROJECT_ID} | Dataset: {DATASET_ID}")
    print(f"Black Week Window: {SIMULATION_START.isoformat()} to {SIMULATION_END_TARGETS.isoformat()} UTC")
    print(f"Simulation Anchor (Max Actuals Cutoff): {CURRENT_TIME.isoformat()} UTC")
    print("=" * 80 + "\n")

    client = get_bigquery_client(PROJECT_ID)

    # 1. Categories (4 Master Categories)
    categories = [
        {"category_id": 1, "parent_category_id": None, "name": "Beauty", "slug": "beauty"},
        {"category_id": 2, "parent_category_id": None, "name": "Electronics", "slug": "electronics"},
        {"category_id": 3, "parent_category_id": None, "name": "Fashion", "slug": "fashion"},
        {"category_id": 4, "parent_category_id": None, "name": "Home", "slug": "home"}
    ]

    # 2. Products (600 SKUs across 4 Categories)
    products = []
    # Beauty Top 5 & SKUs 1001-1003 (The stockout catalysts)
    products.append({"product_id": 1001, "category_id": 1, "name": "Lumière Advanced Night Repair Serum", "sku": "SKU-1001", "brand": "Lumière Beauty", "retail_price": 65.00, "cost": 22.00, "is_active": True})
    products.append({"product_id": 1002, "category_id": 1, "name": "Éclat Radiance Mist", "sku": "SKU-1002", "brand": "Lumière Beauty", "retail_price": 48.00, "cost": 15.00, "is_active": True})
    products.append({"product_id": 1003, "category_id": 1, "name": "Aura Glow Cream", "sku": "SKU-1003", "brand": "Lumière Beauty", "retail_price": 58.00, "cost": 18.00, "is_active": True})
    products.append({"product_id": 1004, "category_id": 1, "name": "Velvet Hydrating Cleanser", "sku": "SKU-1004", "brand": "Lumière Beauty", "retail_price": 32.00, "cost": 10.00, "is_active": True})
    products.append({"product_id": 1005, "category_id": 1, "name": "Satin Lip Elixir", "sku": "SKU-1005", "brand": "Lumière Beauty", "retail_price": 28.00, "cost": 8.00, "is_active": True})

    b_prefixes = ["Hydra", "Botanical", "Rosewater", "Silky", "Charcoal", "Brightening", "Nourishing", "Gentle", "Mineral", "Peptide", "Collagen", "Radiant", "Matte", "Volumizing", "Illuminating", "Scalp", "Revitalizing", "Pure", "Luminous", "Organic"]
    b_types = ["Serum", "Mist", "Cream", "Cleanser", "Elixir", "Toner", "Mask", "Scrub", "Lotion", "Concentrate", "Powder", "Lipstick", "Mascara", "Highlighter", "Shampoo", "Conditioner", "Balm", "Essence", "Peel", "Fluid"]
    b_brands = ["Lumière Beauty", "Éclat Botanical", "Aura Labs", "Maison Botanique", "PureSkin Paris"]

    for i in range(1006, 1151):
        name = f"{random.choice(b_prefixes)} {random.choice(b_types)} {i%20 + 1}"
        price = float(random.choice([18.0, 24.0, 32.0, 45.0, 58.0, 65.0, 78.0, 89.0, 115.0]))
        products.append({
            "product_id": i, "category_id": 1, "name": name, "sku": f"SKU-{i}",
            "brand": random.choice(b_brands),
            "retail_price": price, "cost": float(round(price * 0.30, 2)), "is_active": True
        })

    # Electronics (150 SKUs)
    e_prefixes = ["Wireless", "Noise-Cancelling", "Smart", "Ultra-HD", "Ergonomic", "RGB", "Portable", "Multiport", "MagSafe", "Hi-Fi", "Pro-Grade", "Compact", "Digital", "High-Speed", "Bluetooth", "Optical", "Fast-Charge", "Gaming", "Studio", "Voice-Enabled"]
    e_types = ["Headphones", "Earbuds", "Speaker", "Watch", "Mouse", "Keyboard", "Webcam", "Docking Station", "Power Bank", "Security Camera", "Charger", "Router", "Gaming Headset", "Desk Lamp", "Tablet", "Drone", "Mic", "SSD Drive", "Smart Scale", "Purifier"]
    e_brands = ["SoundPro", "FitTech", "NovaTech", "AeroGadgets", "CyberPulse", "VividAudio"]

    for i in range(2001, 2151):
        name = f"{random.choice(e_prefixes)} {random.choice(e_types)} {i%20 + 1}"
        price = float(random.choice([29.0, 49.0, 79.0, 129.0, 199.0, 249.0, 349.0, 499.0, 699.0]))
        products.append({
            "product_id": i, "category_id": 2, "name": name, "sku": f"SKU-{i}",
            "brand": random.choice(e_brands),
            "retail_price": price, "cost": float(round(price * 0.52, 2)), "is_active": True
        })

    # Fashion (150 SKUs)
    f_prefixes = ["Cashmere", "Wool", "Linen", "Denim", "Organic Cotton", "Leather", "Silk", "Merino", "Structured", "Trench", "Suede", "Pleated", "Vintage", "Oversized", "Crossbody", "Performance", "Fleece", "Quilted", "Monogram", "Classic"]
    f_types = ["Sweater", "Overcoat", "Blazer", "Jeans", "T-Shirt", "Boots", "Blouse", "Scarf", "Tote Bag", "Coat", "Sneakers", "Skirt", "Belt", "Trousers", "Jacket", "Cardigan", "Shorts", "Hoodie", "Hat", "Loafers"]
    f_brands = ["LuxeStyle", "Atelier Paris", "Urban Thread", "Nordic Wear", "Maison Couture"]

    for i in range(3001, 3151):
        name = f"{random.choice(f_prefixes)} {random.choice(f_types)} {i%20 + 1}"
        price = float(random.choice([29.0, 45.0, 65.0, 89.0, 120.0, 160.0, 210.0, 280.0, 350.0]))
        products.append({
            "product_id": i, "category_id": 3, "name": name, "sku": f"SKU-{i}",
            "brand": random.choice(f_brands),
            "retail_price": price, "cost": float(round(price * 0.36, 2)), "is_active": True
        })

    # Home (150 SKUs)
    h_prefixes = ["Aroma", "Egyptian Cotton", "Ceramic", "Minimalist", "Weighted", "Cast Iron", "Ergonomic", "Velvet", "Soy Wax", "Bamboo", "Espresso", "Stainless Steel", "Jute", "Air Fryer", "Non-Stick", "Porcelain", "Standing", "Decorative", "Memory Foam", "Teak"]
    h_types = ["Diffuser", "Sheet Set", "Vase", "Table Lamp", "Blanket", "Dutch Oven", "Office Chair", "Pillow Set", "Candle", "Towel Set", "Coffee Maker", "Cutlery Set", "Area Rug", "Digital Oven", "Cookware Set", "Dinnerware", "Floor Mirror", "Wall Clock", "Humidifier", "Cutting Board"]
    h_brands = ["Maison Living", "Nordic Nest", "Artisan Home", "EcoComfort", "Studio Casa"]

    for i in range(4001, 4151):
        name = f"{random.choice(h_prefixes)} {random.choice(h_types)} {i%20 + 1}"
        price = float(random.choice([22.0, 35.0, 49.0, 75.0, 110.0, 149.0, 199.0, 260.0, 320.0]))
        products.append({
            "product_id": i, "category_id": 4, "name": name, "sku": f"SKU-{i}",
            "brand": random.choice(h_brands),
            "retail_price": price, "cost": float(round(price * 0.34, 2)), "is_active": True
        })

    # 3. Distribution Centers
    distribution_centers = [
        {"dc_id": 1, "name": "Paris Hub - Europe West", "latitude": 48.8566, "longitude": 2.3522},
        {"dc_id": 2, "name": "Frankfurt Hub - Central Europe", "latitude": 50.1109, "longitude": 8.6821}
    ]

    # 4. Inventory Items
    inventory_items = []
    inv_id = 1
    for p in products:
        inventory_items.append({
            "inventory_item_id": inv_id,
            "product_id": p["product_id"],
            "dc_id": 1 if p["category_id"] in [1, 3] else 2,
            "quantity_on_hand": 0 if p["product_id"] in [1001, 1002, 1003] else 5000,
            "safety_stock_level": 200,
            "created_at": "2026-11-01T00:00:00Z"
        })
        inv_id += 1

    # 5. Inventory Snapshots (5 Days: Mon Nov 23 to Fri Nov 27 at 08:00 UTC = 3,000 snapshots)
    inventory_snapshots = []
    snap_id = 1
    for day in range(5):
        current_dt = SIMULATION_START + timedelta(days=day)
        for p in products:
            is_oos = (p["product_id"] in [1001, 1002, 1003]) and (day < 3)
            stock_qty = 0 if is_oos else (2500 - day * 100)
            inventory_snapshots.append({
                "snapshot_id": snap_id,
                "product_id": p["product_id"],
                "recorded_at": current_dt.strftime("%Y-%m-%dT08:00:00Z"),
                "stock_quantity": stock_qty,
                "is_out_of_stock": is_oos
            })
            snap_id += 1

    # 6. Users (10,000 European Profiles with rich demographics)
    countries = ["France", "Germany", "Netherlands", "Spain", "Italy", "Belgium", "Austria", "Sweden"]
    users = []
    for uid in range(1, 10001):
        country = random.choice(countries)
        reg_days_ago = random.randint(10, 500)
        users.append({
            "user_id": uid,
            "email": f"user_{uid}@example.eu",
            "first_name": f"User{uid}",
            "last_name": f"LastName{uid}",
            "gender": random.choice(["F", "M", "Other"]),
            "age": random.randint(18, 72),
            "country": country,
            "latitude": 48.85 + (uid % 10) * 0.1,
            "longitude": 2.35 + (uid % 10) * 0.1,
            "created_at": (SIMULATION_START - timedelta(days=reg_days_ago)).strftime("%Y-%m-%dT10:00:00Z")
        })

    # 7, 8, 9. Actual Historical Orders (26,285 Completed Orders yielding €5,913,300.00 realized revenue)
    orders = []
    order_items = []
    sales_event_stream = []

    order_id = 1
    order_item_id = 1

    category_sales_specs = [
        (1, 1420000.0), # Beauty:      Target €1,950,000.00 | Actual €1,420,000.00 (-€530,000.00)
        (2, 1570000.0), # Electronics: Target €1,670,000.00 | Actual €1,570,000.00 (-€100,000.00)
        (3, 1406500.0), # Fashion:     Target €1,450,000.00 | Actual €1,406,500.00 (-€43,500.00)
        (4, 1516800.0)  # Home:        Target €1,580,000.00 | Actual €1,516,800.00 (-€63,200.00)
    ]

    total_seconds_window = int((CURRENT_TIME - SIMULATION_START).total_seconds())

    for cat_id, target_rev in category_sales_specs:
        cat_products = [p for p in products if p["category_id"] == cat_id]
        n_prods = len(cat_products)
        
        weights = 1.0 / (np.arange(1, n_prods + 1) ** 0.85)
        weights /= weights.sum()

        current_cat_rev = 0.0

        while current_cat_rev < target_rev:
            rand_sec = random.randint(0, total_seconds_window)
            order_dt = SIMULATION_START + timedelta(seconds=rand_sec)
            user_id = random.randint(1, 10000)

            item_count_roll = random.random()
            num_items_in_order = 1 if item_count_roll < 0.55 else (2 if item_count_roll < 0.85 else (3 if item_count_roll < 0.95 else 4))

            order_total = 0.0
            items_for_order = []

            for _ in range(num_items_in_order):
                p_obj = np.random.choice(cat_products, p=weights)
                p_id = p_obj["product_id"]
                
                # Out-of-Stock Mon-Wed (Nov 23, 24, 25)
                if p_id in [1001, 1002, 1003] and order_dt.day in [23, 24, 25]:
                    p_obj = cat_products[random.randint(4, n_prods - 1)]
                    p_id = p_obj["product_id"]

                price = float(p_obj["retail_price"])
                qty = 1 if random.random() < 0.85 else 2
                line_total = price * qty

                order_total += line_total
                items_for_order.append((p_id, qty, price))

            current_cat_rev += order_total

            orders.append({
                "order_id": order_id,
                "user_id": user_id,
                "order_status": "Completed",
                "total_amount": float(round(order_total, 2)),
                "tax_amount": float(round(order_total * 0.20, 2)),
                "shipping_fee": 4.99 if order_total < 50.0 else 0.0,
                "num_of_items": len(items_for_order),
                "created_at": order_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            })

            for p_id, qty, price in items_for_order:
                # Returns modeling for off-path queries (5% return rate)
                has_return = random.random() < 0.05
                ret_dt = (order_dt + timedelta(days=random.randint(1, 2))).strftime("%Y-%m-%dT%H:%M:%SZ") if has_return else None

                order_items.append({
                    "order_item_id": order_item_id,
                    "ord_hdr_num": order_id,
                    "user_id": user_id,
                    "mat_nr": p_id,
                    "inventory_item_id": p_id - (p_id // 1000 - 1) * 850,
                    "quantity": qty,
                    "sale_price": float(price),
                    "discount_amount": 0.0,
                    "created_at": order_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "shipped_at": (order_dt + timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "delivered_at": (order_dt + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "returned_at": ret_dt
                })

                sales_event_stream.append({
                    "event_id": str(uuid.uuid4()),
                    "order_id": order_id,
                    "product_id": p_id,
                    "category_id": cat_id,
                    "quantity": qty,
                    "sale_price": float(price),
                    "discount_amount": 0.0,
                    "timestamp": order_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                })
                order_item_id += 1

            order_id += 1

    total_orders_count = len(orders)
    print(f"Generated {total_orders_count} orders across 4 categories (€5,913,300 realized revenue).")

    # 10. Weekly Commercial Targets (Full 8 Days: Nov 23 - Nov 30)
    weekly_commercial_targets = [
        {"target_id": 1, "category_id": 1, "week_start_date": "2026-11-23", "target_revenue": 1950000.0, "target_sessions": 512000, "target_conversion_rate": 0.029},
        {"target_id": 2, "category_id": 2, "week_start_date": "2026-11-23", "target_revenue": 1670000.0, "target_sessions": 210000, "target_conversion_rate": 0.035},
        {"target_id": 3, "category_id": 3, "week_start_date": "2026-11-23", "target_revenue": 1450000.0, "target_sessions": 190000, "target_conversion_rate": 0.032},
        {"target_id": 4, "category_id": 4, "week_start_date": "2026-11-23", "target_revenue": 1580000.0, "target_sessions": 200000, "target_conversion_rate": 0.030}
    ]

    # 11. Daily Category Targets (Full 8 Days = 32 records)
    daily_category_targets = []
    daily_weights = [0.10, 0.11, 0.12, 0.18, 0.24, 0.08, 0.07, 0.10]
    cat_daily_targets = {
        1: {"rev": 1950000.0, "sess": 512000, "cvr": 0.029, "aov": 61.0, "spend": 205000.0, "roas": 4.8},
        2: {"rev": 1670000.0, "sess": 210000, "cvr": 0.035, "aov": 180.0, "spend": 120000.0, "roas": 5.2},
        3: {"rev": 1450000.0, "sess": 190000, "cvr": 0.032, "aov": 85.0, "spend": 110000.0, "roas": 4.5},
        4: {"rev": 1580000.0, "sess": 200000, "cvr": 0.030, "aov": 110.0, "spend": 115000.0, "roas": 4.6},
    }
    for day in range(8):
        curr_date = (SIMULATION_START + timedelta(days=day)).strftime("%Y-%m-%d")
        w = daily_weights[day]
        for cat_id, c_info in cat_daily_targets.items():
            daily_category_targets.append({
                "target_id": f"T-CAT{cat_id}-{curr_date}",
                "category_id": cat_id,
                "date": curr_date,
                "target_revenue": float(round(c_info["rev"] * w, 2)),
                "target_sessions": int(c_info["sess"] * w),
                "target_conversion_rate": c_info["cvr"],
                "target_aov": c_info["aov"],
                "target_ad_spend": float(round(c_info["spend"] * w, 2)),
                "target_roas": c_info["roas"]
            })

    # 12. Intraday 15-Minute Category Targets (3,072 records)
    category_15min_targets = []
    intraday_weights = []
    for h in range(24):
        for m in (0, 15, 30, 45):
            h_float = h + m / 60.0
            weight = 0.15 + np.exp(-((h_float - 11.5)**2)/12.0) + 1.2 * np.exp(-((h_float - 20.5)**2)/10.0)
            intraday_weights.append(weight)
    intraday_weights = np.array(intraday_weights)
    intraday_weights /= intraday_weights.sum()

    cat_target_revs = {1: 1950000.0, 2: 1670000.0, 3: 1450000.0, 4: 1580000.0}
    cat_target_sess = {1: 512000, 2: 210000, 3: 190000, 4: 200000}

    for day_idx in range(8):
        dow = ((day_idx + 1) % 7) + 1
        d_weight = daily_weights[day_idx]
        for cat_id in range(1, 5):
            daily_rev = cat_target_revs[cat_id] * d_weight
            daily_sess = cat_target_sess[cat_id] * d_weight
            interval_idx = 0
            for h in range(24):
                for m in (0, 15, 30, 45):
                    t_str = f"{h:02d}:{m:02d}:00"
                    t_weight = intraday_weights[interval_idx]
                    target_rev_15m = float(round(daily_rev * t_weight, 2))
                    target_sess_15m = int(round(daily_sess * t_weight))
                    category_15min_targets.append({
                        "target_id": f"T15M-C{cat_id}-D{dow}-{h:02d}{m:02d}",
                        "category_id": cat_id,
                        "day_of_week": dow,
                        "time_bucket": t_str,
                        "target_revenue": target_rev_15m,
                        "target_sessions": target_sess_15m
                    })
                    interval_idx += 1

    # 13. Web Sessions (876,000 Sessions -> Exact Orders/Sessions = 26,285 / 876,000 = 3.0006%)
    # Calibrated traffic sources, channels, OS, browsers
    TARGET_TOTAL_SESSIONS = 876000
    print(f"Generating {TARGET_TOTAL_SESSIONS} web sessions (Target CVR = {total_orders_count/TARGET_TOTAL_SESSIONS*100:.2f}%)...")
    
    # 14 & 15. Web Events & OOS Interactions
    # Each session will have 15 to 25 events on average (mean ≈ 18.5)
    # Total events: ~16.2M events written in streaming chunks to temporary NDJSON file
    oos_interactions = []
    oos_id = 1

    # Write web_sessions and web_events directly to streaming JSONL temporary files in project-local .tmp
    local_tmp_base = os.path.join(PROJECT_ROOT, ".tmp")
    os.makedirs(local_tmp_base, exist_ok=True)
    temp_dir = tempfile.mkdtemp(dir=local_tmp_base)
    sessions_file_path = os.path.join(temp_dir, "web_sessions.json")
    events_file_path = os.path.join(temp_dir, "web_events.json")

    print(f"Streaming {TARGET_TOTAL_SESSIONS} sessions and ~16M web events to project temporary disk ({local_tmp_base})...")

    traffic_sources_pool = ["Paid Search", "Organic Search", "Paid Social", "Direct", "Email", "Affiliate"]
    traffic_weights = [0.38, 0.24, 0.18, 0.10, 0.06, 0.04]
    
    utm_campaigns = {
        "Paid Search": ("google", "cpc", "black_friday_search"),
        "Paid Social": ("meta", "cpc", "black_friday_beauty"),
        "Organic Search": ("organic", "none", None),
        "Direct": ("direct", "none", None),
        "Email": ("newsletter", "email", "bf_vip_early_access"),
        "Affiliate": ("criteo", "affiliate", "retargeting_deals")
    }

    event_id_counter = 1
    total_events_generated = 0

    with open(sessions_file_path, "w", encoding="utf-8") as f_sess, open(events_file_path, "w", encoding="utf-8") as f_events:
        for s_idx in range(1, TARGET_TOTAL_SESSIONS + 1):
            rand_sec = random.randint(0, total_seconds_window)
            s_dt = SIMULATION_START + timedelta(seconds=rand_sec)
            
            source = random.choices(traffic_sources_pool, weights=traffic_weights)[0]
            utm_s, utm_m, utm_c = utm_campaigns[source]
            
            os_roll = random.random()
            dev_os = "iOS" if os_roll < 0.52 else ("Android" if os_roll < 0.85 else ("Windows" if os_roll < 0.96 else "macOS"))
            browser = "Safari" if dev_os in ["iOS", "macOS"] else ("Chrome" if dev_os == "Android" else "Edge")

            sess_obj = {
                "session_id": f"SESS-{s_idx}",
                "user_id": random.randint(1, 10000) if random.random() < 0.75 else None,
                "traffic_source": source,
                "utm_source": utm_s,
                "utm_medium": utm_m,
                "utm_campaign": utm_c,
                "device_os": dev_os,
                "browser": browser,
                "session_started_at": s_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            }
            f_sess.write(json.dumps(sess_obj) + "\n")

            # Generate 15 to 25 events per session (mean = 18.5)
            # Journey archetype distribution:
            # 25% Quick browse (15 events), 50% Standard browse (18 events), 25% Deep shopping / checkout (22-25 events)
            n_events = random.randint(15, 22) if random.random() < 0.75 else random.randint(22, 25)
            
            curr_event_time = s_dt
            # Event sequence
            p_obj = random.choice(products)
            p_id = p_obj["product_id"]

            for e_step in range(n_events):
                curr_event_time += timedelta(seconds=random.randint(5, 30))
                if curr_event_time > CURRENT_TIME:
                    break

                if e_step == 0:
                    e_type = "page_view"
                    p_url = "https://lumireshop.eu/"
                elif e_step == 1:
                    e_type = "category_view"
                    p_url = f"https://lumireshop.eu/categories/{p_obj['category_id']}"
                elif e_step == 2:
                    e_type = "search_query"
                    p_url = f"https://lumireshop.eu/search?q={p_obj['name'].split()[0]}"
                elif e_step == 3:
                    e_type = "filter_applied"
                    p_url = f"https://lumireshop.eu/categories/{p_obj['category_id']}?price_range=20-100"
                elif e_step == 4:
                    e_type = "product_view"
                    p_url = f"https://lumireshop.eu/products/{p_id}"
                elif e_step == 5:
                    e_type = "image_zoom"
                    p_url = f"https://lumireshop.eu/products/{p_id}#gallery"
                elif e_step == 6:
                    e_type = "review_read"
                    p_url = f"https://lumireshop.eu/products/{p_id}#reviews"
                elif e_step == 7:
                    e_type = "wishlist_add"
                    p_url = f"https://lumireshop.eu/wishlist"
                elif e_step == 8:
                    e_type = "cart_add"
                    p_url = f"https://lumireshop.eu/cart"
                elif e_step == 9:
                    e_type = "cart_view"
                    p_url = f"https://lumireshop.eu/cart"
                elif e_step == 10:
                    e_type = "checkout_start"
                    p_url = f"https://lumireshop.eu/checkout"
                elif e_step == 11:
                    e_type = "checkout_shipping_select"
                    p_url = f"https://lumireshop.eu/checkout/shipping"
                elif e_step == 12:
                    e_type = "checkout_payment_select"
                    p_url = f"https://lumireshop.eu/checkout/payment"
                elif e_step == 13:
                    e_type = "checkout_review"
                    p_url = f"https://lumireshop.eu/checkout/review"
                elif e_step == 14:
                    e_type = "checkout_success" if (s_idx <= total_orders_count) else "page_view"
                    p_url = f"https://lumireshop.eu/order-confirmed" if (s_idx <= total_orders_count) else "https://lumireshop.eu/deals"
                else:
                    alt_p = random.choice(products)
                    e_type = "product_view"
                    p_url = f"https://lumireshop.eu/products/{alt_p['product_id']}"

                event_obj = {
                    "event_id": event_id_counter,
                    "session_id": f"SESS-{s_idx}",
                    "product_id": p_id,
                    "event_type": e_type,
                    "page_url": p_url,
                    "metadata": {"error_message": None, "http_status_code": 200, "estimated_lost_revenue": None},
                    "created_at": curr_event_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                }
                f_events.write(json.dumps(event_obj) + "\n")
                event_id_counter += 1
                total_events_generated += 1

    print(f"Generated {TARGET_TOTAL_SESSIONS} sessions and {total_events_generated} web events (Avg {total_events_generated/TARGET_TOTAL_SESSIONS:.2f} events/session).")

    # 15. Out of Stock Interactions (Calibrated to exactly €65,000.00 across 1,182 records on SKUs 1001-1003 Mon-Wed Nov 23-25)
    oos_interactions = []
    oos_skus = [1001, 1002, 1003]
    total_oos_target = 65000.0
    num_oos = 1182
    running_loss = 0.0
    for o_idx in range(1, num_oos + 1):
        rand_sec = random.randint(0, int((datetime(2026, 11, 25, 23, 59, 59) - SIMULATION_START).total_seconds()))
        oos_dt = (SIMULATION_START + timedelta(seconds=rand_sec)).strftime("%Y-%m-%dT%H:%M:%SZ")
        p_id = random.choice(oos_skus)
        if o_idx < num_oos:
            loss_val = 55.0
            running_loss += loss_val
        else:
            loss_val = round(total_oos_target - running_loss, 2)
            running_loss += loss_val
        oos_interactions.append({
            "interaction_id": o_idx,
            "session_id": f"SESS-{random.randint(1, TARGET_TOTAL_SESSIONS)}",
            "art_code": p_id,
            "clicked_at": oos_dt,
            "pot_val": float(loss_val)
        })

    # 16. Competitor Price Feed (5 Days: Mon-Fri at 06:00:00 UTC)
    competitor_price_feed = []
    scrape_id = 1
    for day in range(5):
        c_dt = (SIMULATION_START + timedelta(days=day)).replace(hour=6, minute=0, second=0).strftime("%Y-%m-%dT06:00:00Z")
        for p in products[:50]:
            p_price = float(p["retail_price"])
            competitor_price_feed.append({
                "scrape_id": scrape_id,
                "product_id": p["product_id"],
                "competitor_name": "Competitor A",
                "competitor_price": float(round(p_price * 0.99, 2)),
                "is_in_stock": True,
                "scraped_at": c_dt
            })
            scrape_id += 1
            competitor_price_feed.append({
                "scrape_id": scrape_id,
                "product_id": p["product_id"],
                "competitor_name": "Competitor B",
                "competitor_price": float(round(p_price * 1.01, 2)),
                "is_in_stock": True,
                "scraped_at": c_dt
            })
            scrape_id += 1

    # 17. Marketing Campaigns
    marketing_campaigns = [
        {"campaign_id": 1001, "name": "Beauty_BlackFriday_PaidSocial", "platform": "Meta Ads", "target_category_id": 1, "bidding_strategy": "Strict Target ROAS", "is_active": True},
        {"campaign_id": 1002, "name": "Electronics_BlackFriday_Search", "platform": "Google Ads", "target_category_id": 2, "bidding_strategy": "Maximize Conversions", "is_active": True},
        {"campaign_id": 1003, "name": "Fashion_Winter_Retargeting", "platform": "Criteo", "target_category_id": 3, "bidding_strategy": "Target CPA", "is_active": True},
        {"campaign_id": 1004, "name": "Home_Deals_Newsletter", "platform": "Klaviyo", "target_category_id": 4, "bidding_strategy": "Direct CRM", "is_active": True}
    ]

    # 18. Daily Ad Performance (5 Days: Mon Nov 23 to Fri Nov 27)
    daily_ad_performance = [
        {"performance_id": 1, "cid_ref": 1001, "date": "2026-11-23", "impressions": 1300000, "clicks": 80000, "spend": 35000.00, "conversions": 2480, "average_cpc": 0.44},
        {"performance_id": 2, "cid_ref": 1001, "date": "2026-11-24", "impressions": 950000, "clicks": 55000, "spend": 26000.00, "conversions": 1705, "average_cpc": 0.47},
        {"performance_id": 3, "cid_ref": 1001, "date": "2026-11-25", "impressions": 950000, "clicks": 55000, "spend": 26000.00, "conversions": 1705, "average_cpc": 0.47},
        {"performance_id": 4, "cid_ref": 1001, "date": "2026-11-26", "impressions": 1000000, "clicks": 58000, "spend": 27000.00, "conversions": 1800, "average_cpc": 0.47},
        {"performance_id": 5, "cid_ref": 1001, "date": "2026-11-27", "impressions": 1050000, "clicks": 62000, "spend": 28000.00, "conversions": 1920, "average_cpc": 0.45}
    ]

    # 19. Ad Bidding Log
    ad_bidding_log = [
        {"log_id": 1, "campaign_id": 1001, "status_change": "BIDDING_MIGRATION", "trigger_details": "Marketing team migrated Beauty campaigns to automated strict target ROAS bidding.", "logged_at": "2026-11-14T09:00:00Z"},
        {"log_id": 2, "campaign_id": 1001, "status_change": "LEARNING_LIMITED", "trigger_details": "Top 5 creatives flagged fatigued and learning-limited by ad platform algorithm.", "logged_at": "2026-11-22T10:00:00Z"},
        {"log_id": 3, "campaign_id": 1001, "status_change": "BUDGET_THROTTLED", "trigger_details": "Conversion volume dip on Mon morning triggered strict efficiency cap (-31% spend, CPC +22%).", "logged_at": "2026-11-23T11:30:00Z"}
    ]

    # 20. Ad Creatives
    ad_creatives = [
        {"creative_id": 501, "parent_adgroup_id": 1001, "name": "Beauty Serum Video Ad Q3", "ad_format": "Video", "quality_score": 4, "relevance_status": "FATIGUED", "ill": True, "last_refreshed_at": "2026-08-15T00:00:00Z"},
        {"creative_id": 502, "parent_adgroup_id": 1001, "name": "Eclat Radiance Carousel", "ad_format": "Carousel", "quality_score": 4, "relevance_status": "LEARNING_LIMITED", "ill": True, "last_refreshed_at": "2026-08-20T00:00:00Z"},
        {"creative_id": 503, "parent_adgroup_id": 1001, "name": "Aura Glow Cream UGC Spotlight", "ad_format": "Video", "quality_score": 3, "relevance_status": "FATIGUED", "ill": True, "last_refreshed_at": "2026-08-10T00:00:00Z"},
        {"creative_id": 504, "parent_adgroup_id": 1001, "name": "Velvet Hydrating Cleanser Demo", "ad_format": "Video", "quality_score": 4, "relevance_status": "LEARNING_LIMITED", "ill": True, "last_refreshed_at": "2026-08-25T00:00:00Z"},
        {"creative_id": 505, "parent_adgroup_id": 1001, "name": "Satin Lip Elixir Influencer Cut", "ad_format": "Video", "quality_score": 3, "relevance_status": "FATIGUED", "ill": True, "last_refreshed_at": "2026-08-18T00:00:00Z"}
    ]

    # 21. Payment Gateway Logs:
    # Calibration Requirement: Number of Payments / Number of Orders between 0.90 and 0.95 (e.g. 92.5%)
    # Total Completed Orders = 26,285.
    # Successful payment gateway logs = 24,314 (92.5% match).
    # 1,971 orders (7.5%) paid via store credit/gift card/wire.
    # Failed payment logs: 750 declines + 48 PayPal timeouts (€3,200 loss).
    payment_gateway_logs = []
    gw_id = 1
    
    # 24,314 Successful payments mapped to orders
    successful_order_ids = random.sample(range(1, total_orders_count + 1), int(total_orders_count * 0.925))
    providers = ["Stripe", "PayPal", "Adyen"]
    methods = ["Credit Card", "PayPal", "Apple Pay"]

    for ord_id in successful_order_ids:
        ord_obj = orders[ord_id - 1]
        prov = random.choice(providers)
        meth = "PayPal" if prov == "PayPal" else random.choice(methods)
        payment_gateway_logs.append({
            "gateway_log_id": f"GW-{gw_id}",
            "session_id": f"SESS-{ord_id}",
            "order_id": ord_id,
            "payment_provider": prov,
            "payment_method": meth,
            "status": "SUCCESS",
            "http_status_code": 200,
            "error_code": None,
            "total_amount": ord_obj["total_amount"],
            "latency_ms": random.randint(110, 240),
            "country": random.choice(countries),
            "created_at": ord_obj["created_at"]
        })
        gw_id += 1

    # 750 Card Declines
    for _ in range(750):
        rand_sec = random.randint(0, total_seconds_window)
        p_dt = SIMULATION_START + timedelta(seconds=rand_sec)
        prov = random.choice(providers)
        payment_gateway_logs.append({
            "gateway_log_id": f"GW-{gw_id}",
            "session_id": f"SESS-FAIL-{gw_id}",
            "order_id": None,
            "payment_provider": prov,
            "payment_method": "Credit Card",
            "status": "FAILED",
            "http_status_code": 400,
            "error_code": "CARD_DECLINED",
            "total_amount": float(round(random.uniform(40.0, 160.0), 2)),
            "latency_ms": random.randint(150, 320),
            "country": random.choice(countries),
            "created_at": p_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        })
        gw_id += 1

    # 48 PayPal Timeout Glitch Records on Wednesday Nov 25 (09:00:00 - 09:20:00 UTC) = €3,200.00
    wed_glitch_start = datetime(2026, 11, 25, 9, 0, 0, tzinfo=timezone.utc)
    for g_idx in range(1, 49):
        g_sec = random.randint(0, 1200)
        g_dt = (wed_glitch_start + timedelta(seconds=g_sec)).strftime("%Y-%m-%dT%H:%M:%SZ")
        g_amt = float(round(3200.0 / 48.0, 2)) if g_idx < 48 else float(round(3200.0 - (47 * round(3200.0 / 48.0, 2)), 2))
        payment_gateway_logs.append({
            "gateway_log_id": f"GW-GLITCH-{g_idx}",
            "session_id": f"SESS-GW-ERR-{g_idx}",
            "order_id": None,
            "payment_provider": "PayPal",
            "payment_method": "PayPal",
            "status": "FAILED",
            "http_status_code": 504,
            "error_code": "ERR_504_GATEWAY_TIMEOUT",
            "total_amount": g_amt,
            "latency_ms": 30000,
            "country": "Germany",
            "created_at": g_dt
        })

    print(f"Generated {len(payment_gateway_logs)} payment logs ({len(successful_order_ids)} successful, {len(successful_order_ids)/total_orders_count*100:.2f}% payment-to-order ratio).")

    # 22. Influencer Campaigns
    influencer_campaigns = [
        {
            "influencer_id": 1,
            "creator_name": "@GlowWithElena",
            "platform": "TikTok",
            "campaign_name": "Elena_BlackFriday_TikTok",
            "promo_code": "GLOW_ELENA_BF",
            "target_revenue": 25000.00,
            "actual_revenue": 14000.00,
            "orders_count": 120,
            "views_count": 500000,
            "fee_amount": 4000.00,
            "is_active": True,
            "created_at": "2026-11-24T08:00:00Z"
        },
        {
            "influencer_id": 2,
            "creator_name": "@StyleByMarcus",
            "platform": "Instagram",
            "campaign_name": "Marcus_Style_Instagram",
            "promo_code": "MARCUS_STYLE_BF",
            "target_revenue": 20000.00,
            "actual_revenue": 19500.00,
            "orders_count": 185,
            "views_count": 320000,
            "fee_amount": 3500.00,
            "is_active": True,
            "created_at": "2026-11-23T10:00:00Z"
        },
        {
            "influencer_id": 3,
            "creator_name": "@TechPulse",
            "platform": "YouTube",
            "campaign_name": "TechPulse_YouTube",
            "promo_code": "TECHPULSE_BF",
            "target_revenue": 45000.00,
            "actual_revenue": 47200.00,
            "orders_count": 210,
            "views_count": 450000,
            "fee_amount": 6000.00,
            "is_active": True,
            "created_at": "2026-11-23T12:00:00Z"
        }
    ]

    # 23. Catalog Recommender Logs
    catalog_recommender_logs = []
    rec_id = 1
    # 1,250 Mismatched recommendations on Beauty out-of-stock items (Nov 23-25)
    for r_idx in range(1, 1251):
        rand_sec = random.randint(0, int((datetime(2026, 11, 25, 23, 59, 59) - SIMULATION_START).total_seconds()))
        r_dt = (SIMULATION_START + timedelta(seconds=rand_sec)).strftime("%Y-%m-%dT%H:%M:%SZ")
        p_page = random.choice([1001, 1002, 1003])
        p_rec = random.choice([2001, 2002, 2003])
        catalog_recommender_logs.append({
            "log_id": f"REC-{rec_id}",
            "session_id": f"SESS-REC-{rec_id}",
            "src_sku": p_page,
            "page_category_id": 1,
            "rec_sku": p_rec,
            "recommended_category_id": 2,
            "fb_rule_id": 99,
            "cat_mismatch_flg": 1,
            "user_action": "BOUNCED",
            "opp_cost_eur": 40.00,
            "recorded_at": r_dt
        })
        rec_id += 1

    # 2,000 Normal matching recommendations
    for r_idx in range(1, 2001):
        rand_sec = random.randint(0, total_seconds_window)
        r_dt = (SIMULATION_START + timedelta(seconds=rand_sec)).strftime("%Y-%m-%dT%H:%M:%SZ")
        p_obj = random.choice(products)
        p_cat = p_obj["category_id"]
        same_cat_prods = [p for p in products if p["category_id"] == p_cat]
        p_rec_obj = random.choice(same_cat_prods)
        act = random.choice(["CLICKED", "IGNORED", "CLICKED"])
        catalog_recommender_logs.append({
            "log_id": f"REC-{rec_id}",
            "session_id": f"SESS-REC-{rec_id}",
            "src_sku": p_obj["product_id"],
            "page_category_id": p_cat,
            "rec_sku": p_rec_obj["product_id"],
            "recommended_category_id": p_cat,
            "fb_rule_id": 0,
            "cat_mismatch_flg": 0,
            "user_action": act,
            "opp_cost_eur": None,
            "recorded_at": r_dt
        })
        rec_id += 1

    # 24. Shipping Lead Times
    shipping_lead_times = [
        {"lead_time_id": "LT-DC1-20261123", "dc_id": 1, "date": "2026-11-23", "carrier_name": "Chronopost", "destination_region": "France", "capacity_utilization_pct": 65.0, "standard_lead_time_hours": 24, "actual_promised_lead_time_hours": 24, "cart_abandonment_impact_pct": 0.0, "estimated_lost_revenue": 0.0},
        {"lead_time_id": "LT-DC1-20261124", "dc_id": 1, "date": "2026-11-24", "carrier_name": "Chronopost", "destination_region": "France", "capacity_utilization_pct": 68.0, "standard_lead_time_hours": 24, "actual_promised_lead_time_hours": 24, "cart_abandonment_impact_pct": 0.0, "estimated_lost_revenue": 0.0},
        {"lead_time_id": "LT-DC1-20261125", "dc_id": 1, "date": "2026-11-25", "carrier_name": "Chronopost", "destination_region": "France", "capacity_utilization_pct": 72.0, "standard_lead_time_hours": 24, "actual_promised_lead_time_hours": 24, "cart_abandonment_impact_pct": 0.0, "estimated_lost_revenue": 0.0},
        {"lead_time_id": "LT-DC1-20261126", "dc_id": 1, "date": "2026-11-26", "carrier_name": "Chronopost", "destination_region": "France", "capacity_utilization_pct": 75.0, "standard_lead_time_hours": 24, "actual_promised_lead_time_hours": 24, "cart_abandonment_impact_pct": 0.0, "estimated_lost_revenue": 0.0},
        {"lead_time_id": "LT-DC1-20261127", "dc_id": 1, "date": "2026-11-27", "carrier_name": "Chronopost", "destination_region": "France", "capacity_utilization_pct": 78.0, "standard_lead_time_hours": 24, "actual_promised_lead_time_hours": 24, "cart_abandonment_impact_pct": 0.0, "estimated_lost_revenue": 0.0},
        {"lead_time_id": "LT-DC2-20261123", "dc_id": 2, "date": "2026-11-23", "carrier_name": "DHL Express", "destination_region": "DACH", "capacity_utilization_pct": 68.0, "standard_lead_time_hours": 24, "actual_promised_lead_time_hours": 24, "cart_abandonment_impact_pct": 0.0, "estimated_lost_revenue": 0.0},
        {"lead_time_id": "LT-DC2-20261124", "dc_id": 2, "date": "2026-11-24", "carrier_name": "DHL Express", "destination_region": "DACH", "capacity_utilization_pct": 74.0, "standard_lead_time_hours": 24, "actual_promised_lead_time_hours": 24, "cart_abandonment_impact_pct": 0.0, "estimated_lost_revenue": 0.0},
        {"lead_time_id": "LT-DC2-20261125", "dc_id": 2, "date": "2026-11-25", "carrier_name": "DHL Express", "destination_region": "DACH", "capacity_utilization_pct": 81.0, "standard_lead_time_hours": 24, "actual_promised_lead_time_hours": 24, "cart_abandonment_impact_pct": 0.0, "estimated_lost_revenue": 0.0},
        {"lead_time_id": "LT-DC2-20261126", "dc_id": 2, "date": "2026-11-26", "carrier_name": "DHL Express", "destination_region": "DACH", "capacity_utilization_pct": 92.0, "standard_lead_time_hours": 24, "actual_promised_lead_time_hours": 48, "cart_abandonment_impact_pct": 4.0, "estimated_lost_revenue": 18000.00},
        {"lead_time_id": "LT-DC2-20261127", "dc_id": 2, "date": "2026-11-27", "carrier_name": "DHL Express", "destination_region": "DACH", "capacity_utilization_pct": 85.0, "standard_lead_time_hours": 24, "actual_promised_lead_time_hours": 24, "cart_abandonment_impact_pct": 0.5, "estimated_lost_revenue": 1500.00}
    ]

    # 25. Competitor Promotions
    competitor_promotions = [
        {"promo_id": 1, "competitor_name": "Competitor A", "category_id": 1, "promotion_title": "Black Friday Glow Sale - 20% Off Luxury Skincare", "discount_pct": 0.20, "price_index_vs_lumiere": 0.99, "start_date": "2026-11-23", "end_date": "2026-11-30", "scraped_at": "2026-11-23T06:00:00Z"},
        {"promo_id": 2, "competitor_name": "Competitor B", "category_id": 1, "promotion_title": "Beauty Week Extravaganza - Up to 20% Off", "discount_pct": 0.20, "price_index_vs_lumiere": 1.01, "start_date": "2026-11-23", "end_date": "2026-11-30", "scraped_at": "2026-11-23T06:00:00Z"},
        {"promo_id": 3, "competitor_name": "Competitor A", "category_id": 2, "promotion_title": "Cyber Tech Deals - 15% Off Smart Audio", "discount_pct": 0.15, "price_index_vs_lumiere": 1.00, "start_date": "2026-11-23", "end_date": "2026-11-30", "scraped_at": "2026-11-23T06:00:00Z"},
        {"promo_id": 4, "competitor_name": "Competitor B", "category_id": 3, "promotion_title": "Winter Fashion Markdown - 25% Off Outerwear", "discount_pct": 0.25, "price_index_vs_lumiere": 0.98, "start_date": "2026-11-23", "end_date": "2026-11-30", "scraped_at": "2026-11-23T06:00:00Z"}
    ]

    memory_tables = {
        "categories": categories,
        "products": products,
        "distribution_centers": distribution_centers,
        "inventory_items": inventory_items,
        "inventory_snapshots": inventory_snapshots,
        "users": users,
        "orders": orders,
        "order_items": order_items,
        "sales_event_stream": sales_event_stream,
        "weekly_commercial_targets": weekly_commercial_targets,
        "daily_category_targets": daily_category_targets,
        "category_15min_targets": category_15min_targets,
        "oos_interactions": oos_interactions,
        "competitor_price_feed": competitor_price_feed,
        "marketing_campaigns": marketing_campaigns,
        "daily_ad_performance": daily_ad_performance,
        "ad_bidding_log": ad_bidding_log,
        "ad_creatives": ad_creatives,
        "payment_gateway_logs": payment_gateway_logs,
        "influencer_campaigns": influencer_campaigns,
        "catalog_recommender_logs": catalog_recommender_logs,
        "shipping_lead_times": shipping_lead_times,
        "competitor_promotions": competitor_promotions
    }

    print("\nLoading in-memory tables via BigQuery Load Jobs...")
    for table_name, data in memory_tables.items():
        table_ref = f"{PROJECT_ID}.{DATASET_ID}.{table_name}"
        job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
        try:
            job = client.load_table_from_json(data, table_ref, job_config=job_config)
            job.result()
            print(f"Successfully loaded {len(data)} records into `{table_name}`.")
        except Exception as e:
            print(f"Failed loading `{table_name}`: {e}", file=sys.stderr)

    # Load large streamed tables (web_sessions & web_events)
    print("\nLoading large clickstream tables from disk...")
    try:
        load_ndjson_file_to_bq(client, "web_sessions", sessions_file_path)
        load_ndjson_file_to_bq(client, "web_events", events_file_path)
    finally:
        # Clean up temporary directory safely
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

    print("\n" + "=" * 80)
    print("DATA GENERATION & RATIOS CALIBRATION COMPLETED SUCCESSFULLY")
    print("=" * 80)

if __name__ == "__main__":
    generate_all_data()
