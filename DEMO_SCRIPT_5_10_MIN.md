# LumièreShop — 5 to 10 Minute Executive Demo Script & Playbook

**Live Environment**: `https://lumiere-shop-app-kjlt6xcbra-ez.a.run.app`  
**GCP Project**: `malaga-conv-analytics` (`europe-west4`)  
**Target Duration**: **5–10 Minutes** (Modular: **5-Min Core Track** + **Optional 3-Min "Compare Chats" 3-Tier Metadata Showdown**)

---

## 🎯 Demo Thesis (What the Audience Should Remember)

1. **Discovery Without Hardcoding**: An executive types **one business question**, and **Google Cloud Knowledge Catalog** (`dataplex.googleapis.com`) dynamically ranks and selects the **40 relevant analytical tables** (out of 140 warehouse tables) and **17 certified Business Glossary terms** (out of 99), staying safely under the 50-table context cliff.
2. **Semantics Prevent Million-Euro Hallucinations**: Raw SQL over cryptic enterprise columns (`pot_val`, `cat_mismatch_flg`, `fb_rule_id`, `opp_cost_eur`) traps standard AI agents into reporting **€2,003,060.60** as "lost stockout revenue" (32x higher than reality!). Grounding the **Gemini Data Analytics Agent** (`geminidataanalytics.googleapis.com`) in Knowledge Catalog's **Business Glossary & EntryLinks** produces the exact certified financial attribution (**€520,871** Beauty shortfall = **€408,681** Ad Throttling + **€62,386** Stockouts + **€49,804** Recommender Mismatch).

---

## 🗺️ High-Level Timing & Navigation Map

| Beat | Time | Screen / UI View | Goal |
| :--- | :--- | :--- | :--- |
| **0. Setup & Entry** | `0:00 – 0:45` | **Screen 0** (`#userNameModal`) $\rightarrow$ **Screen 1** (`#alertView`) | Set operator identity and frame the **Friday 14:30 UTC Black Week Incident**. |
| **1. Live Catalog Discovery** | `0:45 – 2:00` | **Screen 1** (`#alertView`) $\rightarrow$ **Prompt Studio** (`#promptStudioModal`) $\rightarrow$ **Screen 2** (`#workspaceView`) | Show Knowledge Catalog discovering **40 tables + 17 glossary terms** and provisioning `gda-blackweek-primary`. |
| **2. Isolate the Symptom & Funnel** | `2:00 – 4:00` | **Screen 2: CMO Workspace** (`#workspaceView`) | Run **Prompt 1** (Category Gap) & **Prompt 2** (Traffic vs. CVR) to prove Beauty traffic collapsed **-23.5%** while CVR held at **3.89%**. |
| **3. The Semantic Trap & Root Causes** | `4:00 – 7:00` | **Screen 2: CMO Workspace** (`#workspaceView`) | Run **Prompt 3** (Stockouts: €62.4K vs €2.0M trap), **Prompt 4** (Recommender Rule 99: €49.8K), and **Prompt 5/6** (ROAS Throttling: €408.7K & Full Attribution). |
| **4. The Proof: 3-Agent Showdown** *(8–10 min track)* | `7:00 – 10:00` | **Screen 3: Compare Chats** (`#compareChatsView`) | Broadcast one prompt simultaneously to **Agent A** (Full Catalog), **Agent B** (Descriptions Only), and **Agent C** (Raw Schema) to watch B & C fall into the €2.0M trap live. |

---

## 🎬 Step-by-Step Demo Script (Prompts, Clicks & Talk Track)

### Beat 0: Incident Framing & Operator Sign-In (`0:00 – 0:45`)

#### 🧭 Navigation
1. Open **[https://lumiere-shop-app-kjlt6xcbra-ez.a.run.app](https://lumiere-shop-app-kjlt6xcbra-ez.a.run.app)** in your browser.
2. **Screen 0 (Operator Identity Modal)**:
   - Type your name (e.g., `CMO_Executive` or your first name) into the input box (`#userNameInput`).
   - Click **"Continue to Workspace"** (`#userNameSubmitBtn`).
3. You land on **Screen 1: Google Chat Executive Alert View** (`#alertView`).
   - Point out the live **Revenue Pacing Alert Card** at the top: it is **Black Friday, Nov 27, 2026 at 14:30 UTC** (62.35% through Black Week).
   - Storewide revenue is **€731,430 (-11.0%) behind the pro-rated plan**, and **Beauty** alone is down **-€520,870.86 (-26.62%)** — accounting for **71% of the entire company's shortfall**.

#### 🗣️ Talk Track
> *"It's 2:30 PM on Black Friday at LumièreShop. Our executive pacing monitor just fired a critical alert: we are €731K behind our pro-rated Black Week plan, and our flagship **Beauty** category accounts for over €520K of that deficit. Dashboards tell us **what** is down, but not **why** — is the payment gateway failing? Are competitors undercutting us? Did we run out of stock, or did our ad bidding algorithm choke?"*

---

### Beat 1: Live Knowledge Catalog Discovery & Agent Provisioning (`0:45 – 2:00`)

#### 🧭 Navigation
1. On **Screen 1** (`#alertView`), locate the **"Active Discovery Prompt"** box showing the unified CMO question:
   ```text
   I need to know how each product category is pacing against its Black Week revenue plan to date, and how much revenue the Beauty shortfall lost to each cause: traffic and conversion rate, advertising budget throttling, items being out of stock, mismatched product recommendations, payment gateway failures, and competitor pricing.
   ```
2. *(Optional 20s detour)* Click **"Open Prompt Optimization Studio"** (`#comparePromptsBtn`) to briefly show how Gemini evaluates candidate prompts against Knowledge Catalog coverage before closing the modal.
3. Click the primary CTA button: **"Prepare Data & Launch Investigation"** (`#prepareDataBtn`).
4. Watch the live **Knowledge Catalog Semantic Discovery** progress modal:
   - Queries `dataplex.googleapis.com` across **140 BigQuery tables** and **99 Business Glossary terms**.
   - Automatically filters out non-analytic `stg_*`, `qa_*`, and `legacy_*` tables.
   - Grounds `gda-blackweek-primary` on **40 analytical tables** (including all **13/13 load-bearing tables**, keeping 10 slots of headroom below the 50-table metadata cliff) and injects **17 Business Glossary definitions**.
5. The UI automatically transitions to **Screen 2: CMO Conversational Investigation Workspace** (`#workspaceView`). Point out the badge in the top bar confirming **`40 Tables Mapped`** and **`17 Glossary Terms`**.

#### 🗣️ Talk Track
> *"Notice we didn't hardcode a single table name. Ourwarehouse has 140 tables across 17 domains — ERP staging feeds, QA backups, POS registers. When I click **Prepare Data**, Google Cloud Knowledge Catalog runs semantic search on our single business question, filters out staging noise, discovers the exact **40 analytical tables** and **17 certified Business Glossary formulas**, and dynamically provisions our Gemini Data Agent in real time."*

---

### Beat 2: Isolate the Outlier & Decompose the Funnel (`2:00 – 4:00`)

#### 🧭 Navigation
In **Screen 2: CMO Conversational Workspace** (`#workspaceView`), all **6 Demo Scenario Prompts** (`1️⃣` through `6️⃣`) are pre-loaded as **one-click buttons** in two places:
1. The **6-Card Guided Investigation Grid** (`#promptsGrid`) at the top of the workspace (expanded by default).
2. The persistent **`Demo Flow:` Quick-Select Bar** (`#demoQuickPromptsBar`) directly above the bottom chat input (`#promptInput`), which stays visible as you scroll through the conversation.

Click the numbered buttons (`1️⃣`, `2️⃣`, `3️⃣`, `4️⃣`, `5️⃣`) in sequence — or paste the prompts below — with the mode toggle set to **⚡ Fast** (or **🧠 Thinking** to display live SQL + reasoning traces).

#### 💬 Prompt 1 — Category Pacing & Pro-Rated Plan Variance (`D-Q1` • Click `1️⃣ Category Gap (-26.6%)`)
```text
Which product categories missed their revenue targets during Black Week, and what is the gap for each?
```
- **What to Highlight in the Response & Chart**:
  - The agent automatically pro-rates the 8-day Black Week plan to the **Friday 14:30 UTC cutoff (62.35% elapsed)** — guided by the `Target To Date (Pro-Rated Plan)` and `Pacing Variance` glossary terms.
  - **Beauty** is the clear outlier at **-€520,871 (-26.62%)**, whereas **Electronics (-5.74%)**, **Home (-4.59%)**, and **Fashion (-2.87%)** are within normal trading variance.

#### 💬 Prompt 2 — Funnel Decomposition: Traffic vs. Conversion Rate (`D-Q2` • Click `2️⃣ Sessions vs. CVR`)
```text
For the Beauty category during Black Week, did sessions come in below plan, or did the conversion rate come in below plan? Compare both against the plan for the same period.
```
- **What to Highlight in the Response**:
  - **Traffic collapsed, NOT conversion rate!**
  - Beauty web sessions came in **-23.5% below plan** (`636,119` actual vs. `831,381` planned sessions).
  - Meanwhile, Beauty's conversion rate finished at **3.89%** against a session-weighted target of **3.84% (+1.1% above plan)**.
  - *Why this matters*: Without anchoring to the pro-rated plan via the glossary, an ungrounded agent compares Black Week traffic to the pre-Black-Week baseline week, sees a "5.5x traffic surge," and falsely blames conversion rate!

---

### Beat 3: Uncover the 3 Root Causes & The €2.0M Semantic Trap (`4:00 – 7:00`)

#### 💬 Prompt 3 — Hero SKU Stockouts & The €2.0M Gross Demand Trap (`D-Q3` • Click `3️⃣ Stockouts (€62.4K vs €2M Trap)`)
```text
Did we have out-of-stock events on bestselling Beauty products, and what was the estimated lost sales impact?
```
- **What to Highlight (The Hero Moment of the Demo)**:
  - Click **"View SQL & Reasoning"** on the agent's response card.
  - Show that 3 hero Beauty SKUs (**1001 Lumière Advanced Night Repair Serum**, **1002 Aura Glow Cream**, **1003 Éclat Radiance Mist**) were out of stock from **Monday Nov 23 to Wednesday Nov 25**, generating **49,960 out-of-stock clicks** in `oos_interactions`.
  - Point out the column `oos_interactions.pot_val`: its raw `SUM(pot_val)` is **€2,003,060.60** (gross attempted basket value at retail list price — nearly 4x the entire Beauty deficit!).
  - Because **Agent A** has the **`Stockout Estimated Lost Revenue`** glossary term from Knowledge Catalog, it multiplies gross unfulfilled demand by the **Paid Conversion Rate (3.115% / 4.05% category CVR)** to report the true net lost revenue: **€62,386 (12.0% of the Beauty shortfall)**.

#### 💬 Prompt 4 — Recommender Engine Fallback Bug (`D-Q4` • Click `4️⃣ Recommender Bug (Rule 99)`)
```text
When customers viewed out-of-stock Beauty items, did our product recommendations suggest relevant alternatives, or was there an algorithm issue?
```
- **What to Highlight**:
  - The column names in `catalog_recommender_logs` are deliberately cryptic ERP abbreviations: `fb_rule_id`, `cat_mismatch_flg`, and `opp_cost_eur` (which is a reserved column filled with `0.00`!).
  - Using Knowledge Catalog's **`Catalog Recommender Category Mismatch`** and **`Recommender Mismatch Lost Revenue`** glossary definitions, the agent ignores the dead `opp_cost_eur` column, filters for `fb_rule_id = 99 AND cat_mismatch_flg = 1` (**64,003 mismatched Electronics impressions** shown on Beauty pages, **22,065 bounced**), and calculates `bounced_impressions × CVR × AOV` = **€49,804 (9.6% of the Beauty shortfall)**.

#### 💬 Prompt 5 — Automated Target ROAS Bidding Throttle & Full Attribution (`D-Q5` & `D-Q6` • Click `5️⃣ Full €521K Attribution Waterfall`)
```text
Break down the Beauty revenue shortfall during Black Week. How much does each root cause account for, including paid marketing ad throttling?
```
- **What to Highlight**:
  - Connects the entire causal chain:
    1. Early-week stockouts on Hero SKUs (`1001–1003`) + mismatched Electronics cross-sell recommendations caused a temporary dip in early-week conversion efficiency (`23–25 Nov`).
    2. That dip caused the automated bidding engine (`ad_bidding_log`) to breach its **4.5x Target ROAS threshold** (`TARGET_ROAS_BREACH_THROTTLED`), slashing `budget_multiplier` down to **0.62 (-38% daily ad spend)** and starving the site of paid traffic!
  - **Certified Executive Reconciliation**:
    - **Automated Ad Budget Throttling**: **€408,681** (`78.5%` of deficit — residual traffic collapse)
    - **Hero SKU Stockouts**: **€62,386** (`12.0%` of deficit)
    - **Recommender Category Mismatch**: **€49,804** (`9.6%` of deficit)
    - **Total Beauty Deficit Explained**: **€520,871 (`100.0%`)**

---

### Beat 4 (Optional 3-Min Finale): "Compare Chats" — 3-Tier Metadata Isolation Showdown (`7:00 – 10:00`)

If you have 8–10 minutes, this is the ultimate visual proof of why **Google Cloud Knowledge Catalog** matters.

#### 🧭 Navigation
1. In the left sidebar or top navigation bar, click **"Compare chats"** (`#compareChatsBtn` — 3 fast clicks or via the staging modal) to open **Screen 3: 3-Agent Parallel Conversational Cockpit** (`#multiAgentWorkspaceView`).
2. Point out the 3 columns grounded on the **exact same tables** and **identical row counts**, differing **only** in metadata richness:
   - **Column 1 — Agent A (`ecommerce_dw`)**: **Full Knowledge Catalog Grounding** (Table/Column Descriptions + **17 Business Glossary Terms** + EntryLinks + Custom Aspects).
   - **Column 2 — Agent B (`ecommerce_dw_2nd`)**: **Descriptions Only** (Basic column labels, **0 Glossary Terms**, **0 EntryLinks**).
   - **Column 3 — Agent C (`ecommerce_dw_3rd`)**: **Raw Schema Only** (**0 Descriptions**, **0 Glossary Terms**, bare column names like `pot_val`, `cat_mismatch_flg`, `ord_hdr_num`).
3. **One-Click Suggested Prompts in Every Chatbox**:
   - **Master Broadcast Bar (`#demoPromptsBroadcast`)**: Click **`🎯 6️⃣ Dual-Trap Showdown (Stockout €62.4K vs €2M + Recommender Rule 99)`** right above `#multiPromptInput` to broadcast the exact dual-trap question to all 3 agents simultaneously!
   - **Individual Agent Columns (`#demoPromptsAgentA`, `#demoPromptsAgentB`, `#demoPromptsAgentC`)**: Each of the 3 agent chatboxes also has its own clickable Demo Scenario pills (`🎯 6️⃣ Dual-Trap`, `3️⃣ Stockouts`, `4️⃣ Recommender`, `5️⃣ Full Waterfall`, `1️⃣ Category Gap`, `2️⃣ Sessions vs CVR`) both inside the agent's welcome card and right above `#inputAgentA/B/C`.

#### 💬 Broadcast Prompt (The Side-by-Side Trap Test • Click `🎯 6️⃣ Dual-Trap Showdown`)
```text
Did we have out-of-stock events on bestselling Beauty products, and what was the estimated lost sales impact? Also how much revenue did we lose from mismatched product recommendations?
```

#### 🏆 What Happens Live on Screen (The Side-by-Side Contrast)
| Dimension | 🟢 Agent A (Full Knowledge Catalog) | 🟡 Agent B (Descriptions Only) | 🔴 Agent C (Raw Schema Only) |
| :--- | :--- | :--- | :--- |
| **Stockout Loss (`oos_interactions`)** | Reports **~€62,386** (applies Paid CVR to `SUM(pot_val)` per Glossary formula). | Sums `pot_val` directly and claims **€2,003,060.60** in lost sales (**32x overstatement!**). | Sums `pot_val` (**€2,003,060.60**) or fails to join `art_code` to `products.product_id`. |
| **Recommender Loss (`catalog_recommender_logs`)** | Reports **~€49,804** (`22,065` bounced `fb_rule_id=99` impressions × CVR × AOV). | Sums `opp_cost_eur` and reports **€0.00** (misses the €49.8K loss completely). | Reports **€0.00** or misinterprets `fb_rule_id = 99`. |
| **Executive Trust** | **100% Reconciled** to the €520,871 P&L shortfall. | **Unusable for CFO/CMO** (claims €2.0M loss on a €520K shortfall). | **Unusable** (guesses column semantics from raw schema). |

---

## 🛠️ Presenter Quick-Reference Cheat Sheet

- **Live App URL**: `https://lumiere-shop-app-kjlt6xcbra-ez.a.run.app`
- **Resetting / Re-grounding Before a Demo**:
  - Clicking **"Prepare Data & Launch Investigation"** (`#prepareDataBtn`) on Screen 1 automatically re-runs live Knowledge Catalog discovery and resets the agent grounding to the 40 canonical tables + 17 glossary terms.
- **Language Switching**:
  - Use the **Language Selector (`🌐 EN / PL / DE / FR / ES ...`)** in the top header to demonstrate 25-language UI localization and multilingual conversational SQL generation on the fly.
