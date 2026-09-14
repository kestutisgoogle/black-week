"""Unit tests for the shared `orders.order_status` derivation.

Neither generator has a dry-run mode that exposes the derived statuses, and a
full `02_generate_data.py --skip-load` run takes about twelve minutes. These
tests exercise the rule directly so a logic error is caught in under a second
rather than after a destructive rebuild.

Run: python3 scripts/test/test_order_status.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from order_status import (PLACED_ORDER_STATUSES, derive_order_status,
                          status_distribution)

FAILURES = []


def check(label, actual, expected):
    ok = actual == expected
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: {actual!r}")
    if not ok:
        FAILURES.append(f"{label}: expected {expected!r}, got {actual!r}")


def main():
    print("Deriving order_status from line-level return flags")

    # Single-line orders: the only two outcomes are all-or-nothing. There is no
    # such thing as a partially returned one-line order, and asserting that
    # guards against an off-by-one in the len() comparison.
    check("1 line, not returned", derive_order_status([False]), "Completed")
    check("1 line, returned", derive_order_status([True]), "Returned")

    # Multi-line orders.
    check("3 lines, none returned",
          derive_order_status([False, False, False]), "Completed")
    check("3 lines, all returned",
          derive_order_status([True, True, True]), "Returned")
    check("3 lines, first returned",
          derive_order_status([True, False, False]), "Partially Returned")
    check("3 lines, last returned",
          derive_order_status([False, False, True]), "Partially Returned")
    check("3 lines, two returned",
          derive_order_status([True, True, False]), "Partially Returned")

    # The Black Week generator passes a GENERATOR, not a list. A naive
    # implementation that iterates twice (once to count, once for len) would
    # silently see an exhausted iterator and mislabel every order.
    check("accepts a generator",
          derive_order_status(x < 0.05 for x in [0.01, 0.9, 0.9]),
          "Partially Returned")

    # The comparison must be strictly less-than, matching ITEM_RETURN_RATE
    # usage in the generator, so a roll of exactly 0.05 is NOT a return.
    check("roll exactly at the threshold is not a return",
          derive_order_status(x < 0.05 for x in [0.05]), "Completed")

    # An order with no lines is a bug, not a Completed order.
    try:
        derive_order_status([])
        check("empty order raises", "no exception", "ValueError")
    except ValueError:
        check("empty order raises", "ValueError", "ValueError")

    print("\nCounting the distribution")

    orders = ([{"order_status": "Completed"}] * 5
              + [{"order_status": "Returned"}] * 2
              + [{"order_status": "Partially Returned"}] * 3)
    check("distribution counts",
          status_distribution(orders),
          {"Completed": 5, "Partially Returned": 3, "Returned": 2})

    # A status that never occurred must still appear, as a zero. A silently
    # absent key is precisely how the degenerate single-value column went
    # unnoticed in the first place.
    check("absent status reported as zero",
          status_distribution([{"order_status": "Completed"}]),
          {"Completed": 1, "Partially Returned": 0, "Returned": 0})

    check("three statuses defined", len(PLACED_ORDER_STATUSES), 3)

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S)")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
