"""Regression tests for the CMO benchmark scorer.

WHY THIS FILE EXISTS
--------------------
An automated scorer on this project has reported a FALSE RESULT eight times.
Every occurrence had the same mechanism - it searched a whole transcript for a
substring instead of judging what the agent CONCLUDED - and every fix was
local, so the general defect survived into the next scorer.

Three of those false results were believed long enough to be acted on. That is
worse than having no measurement, because a broken instrument looks like
evidence.

The fixtures below are VERBATIM agent answers from benchmark run 1
(2026-09-12 08:32 UTC, raw data `scratch/cmo_benchmark_20260912-083203.json`).
They are not invented strings. Each one encodes a specific defect and the
verdict a human reached by reading the answer, recorded in the run-1 analysis.

Run: python3 scripts/test/test_cmo_scorer.py
"""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "export", "scripts"))

import yaml  # noqa: E402

import run_cmo_questions as R  # noqa: E402

QUESTIONS_YAML = os.path.join(REPO, "config", "cmo_questions.yaml")

FAILURES = []


def check(label, actual, expected):
    ok = actual == expected
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: {actual!r}")
    if not ok:
        FAILURES.append(f"{label}: expected {expected!r}, got {actual!r}")


def load_questions():
    cfg = yaml.safe_load(open(QUESTIONS_YAML))
    out = {}
    for key in ("demo_script", "benchmark"):
        for q in cfg[key]:
            out[q["id"]] = q
    return out


# =========================================================================== #
# Retired questions, preserved here so their scorer coverage survives
# =========================================================================== #
#
# B-S3 was retired from config/cmo_questions.yaml on 2026-09-13. It only
# separated the agent tiers when the agent held the glossary term "Known
# Unpopulated Columns", and the unified discovery prompt does not retrieve
# that term. The prompt cannot be reworded to chase it: adding "discounts"
# to the prompt was measured to drop the orders and web_sessions tables and
# collapse the main story from 11/11 answerable to 1/11.
#
# The DEFECT D5 regression it guards is still live and still valuable. D5 was
# the scorer being unable to tell an honest statement about the DATA ("the
# `discount_amount` column contains EUR 0") from a false statement about the
# BUSINESS ("there were no discounts applied to orders"). That is a general
# scorer property, not a property of this one question, so the definition is
# kept verbatim below rather than deleted with the question.
RETIRED_QUESTIONS_YAML = r"""
  - id: B-S3
    tier: semantic_trap
    title: Unpopulated field
    prompt: >-
      How much did we give away in discounts during Black Week?
    tests: >-
      `order_items.discount_amount` is uniformly 0.00 - the field is not
      populated in this warehouse. The honest answer is that it cannot be
      answered from this field, not that discounting was zero.
    ground_truth:
      summary: >-
        Cannot be answered from `discount_amount`: all 207,062 rows are 0.00,
        which reflects a field that is not populated rather than an absence of
        discounting.
      figures: {}
      context:
        rows: 207062
        non_zero: 0
    scoring:
      # The primary discriminator is the MECHANISM axis, not the trap list.
      # That is deliberate: "did the agent flag the field as unpopulated" is a
      # property of the answer, whereas the forbidden list is a guess at one
      # agent's wording - and guessing at wording is precisely the habit that
      # has produced six false scorer results on this project. Agent A's honest
      # framing passes the list below; Agent C's does not.
      mechanism_any:
        - [not populated, unpopulated, no data, not recorded, not tracked,
           not captured, cannot be answered, "can't be answered", unable to,
           all zero, all zeros, always 0, always zero, empty, no non-zero,
           "contains 0", "contains eur 0", "contains €0", "0.00 for",
           "zero for every", "zero for all", "0 for all", placeholder,
           reserved, not used, unused, appears to be, suggests the field,
           data quality, likely not]
      # Scoped to the conclusion (the default), NOT `full`. A correct answer
      # very often contains a disclaimer of the form "this does not mean no
      # discounts were given", and scanning the whole transcript for these
      # strings would flag that disclaimer as the trap it is warning against.
      trap_forbidden:
        - "we gave no discounts"
        - "we offered no discounts"
        - "we did not offer any discounts"
        - "we did not apply any discounts"
        - "we did not give away any"
        - "no discounts were given"
        - "no discounts were offered"
        - "no discounts were applied"
        - "no discounts applied"
        - "no discounting took place"
        - "no discounting occurred"
        - "zero discounts were"
        - "total discounts given was"
        - "we discounted nothing"
      trap_note: >-
        Claiming "we gave no discounts" treats missing data as a measurement.
        The correct behaviour is to flag the field as unpopulated. Read the
        mechanism axis first on this question: it is the axis that separates the
        honest answer from the trapped one. Residual risk, accepted knowingly: a
        conclusion that quotes the false claim only in order to reject it would
        be flagged. Every answer is hand-read, so this is visible rather than
        silent.
    tolerance_pct: 0
"""


def load_retired_questions():
    """Retired questions are kept out of the live set deliberately.

    They are returned as a separate dict so that the configuration-hygiene
    test, which sweeps every live question, does not start policing
    definitions that are no longer shipped.
    """
    cfg = yaml.safe_load("retired:\n" + RETIRED_QUESTIONS_YAML)
    return {q["id"]: q for q in cfg["retired"]}


# =========================================================================== #
# Verbatim run-1 answers
# =========================================================================== #

# B-D2, Agent B. Concludes with EUR 917,949.50 - the whole-days-only basis.
# DEFECT D2: the old trap forbade EUR 1,702,537, which no agent ever produced,
# and missed this entirely.
D2_AGENT_B = (
    "Based on the daily category targets for the current week (November 23, "
    "2026 to November 27, 2026), all four categories are currently behind "
    "their revenue plan:\n\n### Key Findings\n"
    "- **Beauty** is the furthest behind plan, with a revenue shortfall of "
    "**\u20ac917,949.50** (-39.0%).\n"
    "- **Electronics**, **Home**, and **Fashion** are also behind plan by "
    "21.6%, 20.7%, and 19.3% respectively.\n"
    "- Across all categories, the total revenue gap for this week stands at "
    "over **\u20ac2 million**."
)

# B-D2, Agent C. Its "54.3%" belongs to ELECTRONICS, not Beauty.
# DEFECT D3: the trap string "54.3%" fired here and was reported as the Beauty
# naive figure. The percentage trap has since been removed - a naked percentage
# cannot be attributed to a category when every category is named in the same
# paragraph. This answer must now fail on FIGURES instead.
D2_AGENT_C = (
    "All categories are currently performing significantly behind their "
    "cumulative planned revenue targets as of 27 November 2026, with the "
    "**Beauty** category showing the largest absolute variance of "
    "**-\u20ac2,237,949.50** (-60.9%).\n\n### Category Performance Gap\n"
    "The data indicates a substantial shortfall across the board, with actual "
    "revenues for all major categories (Beauty, Electronics, Fashion, and "
    "Home) being less than half of their planned targets. The **Beauty** "
    "category is the furthest behind in both absolute terms and percentage, "
    "followed by **Electronics** with a deficit of **\u20ac1,876,230.49** (-54.3%)."
)

# B-D3, Agent A. The clearest failure in run 1, and the grader passed it.
# DEFECT D4.
D3_AGENT_A = (
    "Beauty's underperformance is primarily a **conversion/efficiency "
    "problem**, not a traffic problem. While Beauty generated the **highest "
    "traffic** volume (82,361 interactions), it had the **lowest revenue per "
    "interaction** ($34.39), causing it to lag behind Electronics in total "
    "revenue despite having nearly 3x the interaction volume.\n\n"
    "### Efficiency vs. Volume\nBeauty leads in customer engagement volume "
    "but struggles with monetization efficiency. Compared to Electronics, "
    "Beauty requires significantly more traffic to generate less total "
    "revenue, suggesting a need to analyze price points or conversion funnel "
    "drop-offs within this category."
)

# B-D3, Agent B. CORRECT. Must not be penalised. Note "versus a target of":
# the first draft of the plan-comparison requirement omitted "target of" and
# failed this answer.
D3_AGENT_B = (
    "I assumed the analysis focuses on Black Friday week-to-date (2026-11-23 "
    "through 2026-11-27 14:30 UTC) comparing actual web sessions and "
    "conversion rates against daily commercial targets.\n\n"
    "Beauty's underperformance is primarily a **traffic problem**, not a "
    "conversion problem. \n\n"
    "* **Traffic:** Actual sessions for Beauty reached **636,119** versus a "
    "target of **1,000,095** (a **-36.4% deficit**).\n"
    "* **Conversion Rate:** Beauty's conversion rate held strong at **3.89%**, "
    "slightly outperforming the target of **3.85%** (+0.03 percentage "
    "points).\n\n### Key Takeaway\nWhile conversion efficiency remained "
    "healthy at 3.89%, the shortfall in top-of-funnel traffic (over 363k "
    "missing sessions) caused Beauty to lag behind target revenue by -39.0%."
)

# B-S3, Agent A. HONEST - a statement about the DATA.
S3_AGENT_A = (
    "During Black Week (Monday, November 23, 2026, through Friday, November "
    "27, 2026 at 14:30:00 UTC), the total explicit order discount amount "
    "recorded was **\u20ac0.00** across all 107,412 ordered items.\n\n"
    "I assumed 'Black Week' refers to Monday, November 23, 2026, through the "
    "current snapshot timestamp on Black Friday, November 27, 2026 at "
    "14:30:00 UTC, and evaluated discounts using the `discount_amount` metric "
    "in the order items table.\n\n### Key Discount Takeaways\n"
    "- **Recorded Discounts**: The `discount_amount` column in `order_items` "
    "contains \u20ac0 across all 65,011 orders placed during Black Week.\n"
    "- **Order Volume**: A total of 107,412 line items were processed during "
    "this timeframe with no direct line-item discounts recorded."
)

# B-S3, Agent C. THE TRAP - a false statement about the BUSINESS.
# DEFECT D5: A and C scored identically in run 1.
S3_AGENT_C = (
    "During Black Week (2026-11-23 to 2026-11-27), there were no discounts "
    "applied to orders."
)

# B-R1, Agent A. Rejects the red herring by asserting something FALSE.
# DEFECT D7, found by replaying run 1 after fixing D1-D6.
R1_AGENT_A = (
    "There were **no payment failures** recorded during Black Week (Nov 20\u201327, "
    "2026); all orders were successfully completed. The revenue shortfall was "
    "instead driven by actual revenue failing to meet daily targets, with a "
    "significant **56.3% gap** specifically on Black Friday (Nov 27).\n\n"
    "### Revenue Shortfall Drivers\n* **Payment Reliability:** Data confirms a "
    "0% failure rate for all transactions during the period, ruling out "
    "technical payment gateway issues as a cause.\n"
    "* **Target Variance:** While revenue grew significantly during Black "
    "Week, it consistently fell behind aggressive targets, culminating in a "
    "$1.45M shortfall on Friday alone."
)

# B-X1, Agent C. Internally impossible: a EUR 917,949.50 shortfall with
# EUR 2,003,060.60 attributed to one cause inside it. In run 1 this scored a
# clean trap pass, because B-X1 had no trap axis at all.
#
# It is ALSO the fixture for the false-exemption defect: the conclusion quotes
# "49,960" (a COUNT of OOS interactions), which the figure matcher accepts as
# the EUR 49,804 recommender loss - 0.31% away. Under global forgiveness that
# single false match disarmed BOTH traps.
X1_AGENT_C = (
    "I evaluated the Beauty shortfall for Black Friday week-to-date "
    "(2026-11-23 through 2026-11-27 14:30:00 UTC) comparing actual revenue "
    "against daily targets.\n\nThe Beauty category has a total shortfall of "
    "**\u20ac917,949.50** against its target of \u20ac2,353,760.92 (achieving "
    "\u20ac1,435,811.42 actual revenue), primarily driven by severe out-of-stock "
    "events and shipping lead time cart abandonment:\n\n"
    "1. **Out-of-Stock (OOS) Lost Demand**: Accounts for **\u20ac2,003,060.60** in "
    "missed potential revenue across 49,960 lost demand interactions.\n"
    "2. **Shipping Lead Time Cart Abandonment**: Accounts for **\u20ac25,790.55** "
    "in lost revenue due to extended delivery promises and DC capacity "
    "constraints.\n3. **Ad Throttling**: The main Beauty campaign "
    "(`Beauty_BlackFriday_PaidSocial`, ID 1001) suffered 5 automated "
    "`TARGET_ROAS_BREACH_THROTTLED` bidding reductions due to "
    "delivery/conversion friction."
)

# A SYNTHETIC fixture, and the only one. It is the answer no agent has yet
# given: the correct one, arrived at by showing the trap value as working. No
# real example exists, and this is the single most important behaviour to get
# right, because the old scorer marked exactly this answer as trapped.
#
# It is deliberately longer than CONCLUSION_TAIL_CHARS so that the marker split
# is genuinely exercised. A shorter answer is treated as all-conclusion, which
# is correct behaviour but tests nothing here.
S1_CORRECT_SHOWING_WORKING = (
    "I assumed 'Black Week' means 2026-11-23 00:00 UTC through the current "
    "snapshot at 2026-11-27 14:30 UTC, and scoped the analysis to the Beauty "
    "category, where the shortfall is concentrated.\n\n"
    "### How I approached it\nThere are two candidate readings of \"revenue "
    "lost to items being out of stock\", and they differ by more than an order "
    "of magnitude, so it is worth being explicit about which one I used.\n\n"
    "The first is gross attempted demand: every basket value recorded against "
    "an out-of-stock interaction, summed. I computed "
    "SUM(oos_interactions.pot_val), which comes to \u20ac2,003,060.60 across 49,960 "
    "interactions, all of them in Beauty and concentrated on hero SKUs 1001, "
    "1002 and 1003 between Monday 23 and Wednesday 25 November.\n\n"
    "That figure is gross demand, not lost revenue, and reporting it as a loss "
    "would be badly misleading: it is larger than the entire storewide "
    "shortfall for the week, which is not arithmetically possible for a single "
    "cause. Only a fraction of shoppers who encounter an out-of-stock item "
    "would have converted at all, and the rest either substituted, bought "
    "later, or were never going to buy.\n\n"
    "The second reading nets that demand down by the rate at which comparable "
    "traffic actually converts. The relevant rate here is the paid conversion "
    "rate, 3.115%, because the affected sessions are overwhelmingly paid.\n\n"
    "In summary, applying the paid conversion rate of 3.115% to that demand "
    "gives an attributed loss of **\u20ac62,386**, which is about 12% of the Beauty "
    "shortfall. I would not report the gross \u20ac2.0M figure to the board as a "
    "loss."
)


# =========================================================================== #
# Tests
# =========================================================================== #

def test_conclusion_isolation():
    print("\nConclusion isolation")

    # A short answer has no separable conclusion: the whole thing IS what the
    # agent concluded.
    body, concl = R.split_conclusion(S3_AGENT_C)
    check("short answer -> whole text is the conclusion", body, "")
    check("short answer -> conclusion is non-empty", bool(concl), True)

    # A long answer with a marker splits at the marker.
    body, concl = R.split_conclusion(S1_CORRECT_SHOWING_WORKING)
    check("marker splits off the conclusion", concl.lower().startswith("in summary"), True)
    check("the working stays in the body", "2,003,060.60" in body, True)
    check("the working is NOT in the conclusion", "2,003,060.60" in concl, False)

    # An early marker must not swallow the whole answer.
    text = "In short, let me check three things. " + ("x " * 900) + "\n\nDone."
    body, concl = R.split_conclusion(text)
    check("early marker is ignored", len(concl) < len(text) / 2, True)


def test_number_extraction():
    print("\nNumber extraction")
    # extract_numbers yields (value, is_percent, is_count).
    nums = R.extract_numbers("We lost \u20ac520,871 which is -26.6% of plan.")
    check("euro amount parsed", (520871.0, False, False) in nums, True)
    check("percentage tagged separately", (26.6, True, False) in nums, True)
    nums = R.extract_numbers("roughly 2.0 million")
    check("million suffix expanded", (2000000.0, False, False) in nums, True)

    # UNIT AWARENESS. A tally of things must not be usable as an amount of
    # money. This is the tenth false scorer result: Agent B answered "49,960
    # customer interactions", the number landed inside the EUR 62,386 window,
    # and the phantom match then forgave the trap it should have triggered.
    nums = R.extract_numbers("blocked 49,960 customer interactions")
    check("a tally is tagged as a count", (49960.0, False, True) in nums, True)
    check("a tally is not offered as money",
          (49960.0, False, False) in nums, False)
    # An explicit currency marker outranks the trailing noun.
    nums = R.extract_numbers("\u20ac49,960 of orders")
    check("currency marker beats the noun",
          (49960.0, False, False) in nums, True)



def test_figure_matching_is_exclusive():
    print("\nFigure matching")
    q = {"ground_truth": {"figures": {"actual": 10.12, "target": 9.51}},
         "tolerance_pct": 10}
    # Quoting ONLY the target must not satisfy both figures. At a 10% tolerance
    # 9.51 sits inside 10.12's window as well as matching itself.
    s = R.score_response(q, "ROAS came in at 9.51x.")
    check("one number cannot satisfy two figures", s["figure_matched"], 1)


def test_D2_naive_pacing_trap(Q):
    print("\nDEFECT D2 - the naive value agents actually produce")
    s = R.score_response(Q["B-D2"], D2_AGENT_B)
    check("EUR 917,949.50 is trapped", s["trap_ok"], False)
    check("trapped on the whole-days basis",
          any("fullday" in h for h in s["trap_hits"]), True)


def test_D3_percentage_is_not_identifying(Q):
    print("\nDEFECT D3 - a naked percentage cannot identify a category")
    s = R.score_response(Q["B-D2"], D2_AGENT_C)
    # C IS wrong, but not by a value on the trap list. It must be caught by the
    # figure axis, not mislabelled as the Beauty naive-percentage trap.
    check("no Electronics figure mislabelled as a Beauty trap",
          [h for h in s["trap_hits"] if "beauty" in h.lower()], [])
    check("wrongness is carried by the figure axis", s["figure_matched"], 0)


def test_D4_conversion_conclusion_is_trapped(Q):
    print("\nDEFECT D4 - naming conversion as the cause")
    s_a = R.score_response(Q["B-D3"], D3_AGENT_A)
    check("'primarily a conversion problem' is trapped", s_a["trap_ok"], False)
    check("no comparison to plan -> mechanism fails", s_a["mechanism_ok"], False)

    # The opposite, CORRECT conclusion must be untouched. This is the half of
    # the test that matters: a trap list tuned until it catches the wrong
    # answer is worthless if it also catches the right one.
    s_b = R.score_response(Q["B-D3"], D3_AGENT_B)
    check("the correct answer is NOT trapped", s_b["trap_ok"], True)
    check("'versus a target of' satisfies the plan comparison",
          s_b["mechanism_ok"], True)


def test_D5_honesty_is_distinguishable(Q):
    print("\nDEFECT D5 - honest wording vs the false claim")
    s_a = R.score_response(Q["B-S3"], S3_AGENT_A)
    s_c = R.score_response(Q["B-S3"], S3_AGENT_C)
    check("honest answer flags the field", s_a["mechanism_ok"], True)
    check("honest answer is not trapped", s_a["trap_ok"], True)
    check("false business claim is trapped", s_c["trap_ok"], False)
    check("the two are now distinguishable",
          (s_a["mechanism_ok"], s_a["trap_ok"]) != (s_c["mechanism_ok"], s_c["trap_ok"]),
          True)


def test_D7_false_reason_for_rejecting_a_red_herring(Q):
    print("\nDEFECT D7 - rejecting a red herring by asserting something false")
    s = R.score_response(Q["B-R1"], R1_AGENT_A)
    check("'no payment failures' is trapped", s["trap_ok"], False)


def test_trap_forgiveness_is_pairwise(Q):
    print("\nPairwise trap forgiveness")
    s = R.score_response(Q["B-X1"], X1_AGENT_C)
    # "49,960" is a COUNT and matches the EUR 49,804 recommender figure to
    # within 0.31%. Under global forgiveness that disarmed both traps.
    check("a coincidental match no longer excuses the traps", s["trap_ok"], False)
    check("both naive values are reported", len(s["trap_hits"]), 2)


def test_trap_forgiveness_still_applies_when_earned(Q):
    print("\nTrap forgiveness when the correct figure IS stated")
    s = R.score_response(Q["B-S1"], S1_CORRECT_SHOWING_WORKING)
    check("showing the gross figure as working is not a trap", s["trap_ok"], True)
    check("the correct figure is credited", s["figure_matched"], 1)


def test_every_trap_value_has_a_pairing(Q):
    print("\nConfiguration hygiene")
    for qid, q in Q.items():
        sc = q.get("scoring") or {}
        figs = (q.get("ground_truth") or {}).get("figures") or {}
        tvals = sc.get("trap_values") or {}
        pairs = sc.get("trap_forgiven_by") or {}
        numeric_figs = [k for k, v in figs.items()
                        if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if tvals and len(numeric_figs) > 1:
            missing = [k for k in tvals if k not in pairs]
            check(f"{qid}: every trap value is paired", missing, [])
        for trap_key, fig_key in pairs.items():
            check(f"{qid}: `{trap_key}` is paired to a real figure",
                  fig_key in figs, True)
            check(f"{qid}: `{trap_key}` is a declared trap value",
                  trap_key in tvals, True)


def main():
    Q = load_questions()
    RETIRED = load_retired_questions()
    print(f"Loaded {len(Q)} live questions from config/cmo_questions.yaml")
    print(f"Loaded {len(RETIRED)} retired question(s) from this file: "
          f"{', '.join(sorted(RETIRED))}")

    test_conclusion_isolation()
    test_number_extraction()
    test_figure_matching_is_exclusive()
    test_D2_naive_pacing_trap(Q)
    test_D3_percentage_is_not_identifying(Q)
    test_D4_conversion_conclusion_is_trapped(Q)
    # B-S3 no longer ships, but the honest-vs-false discrimination it guards
    # is a general scorer property, so it is still exercised.
    test_D5_honesty_is_distinguishable(RETIRED)
    test_D7_false_reason_for_rejecting_a_red_herring(Q)
    test_trap_forgiveness_is_pairwise(Q)
    test_trap_forgiveness_still_applies_when_earned(Q)
    test_every_trap_value_has_a_pairing(Q)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("All scorer regression tests passed.")


if __name__ == "__main__":
    main()
