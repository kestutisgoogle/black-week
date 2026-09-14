"""Shared definition of `orders.order_status`.

Two separate generators write to the `orders` table - `02_generate_data.py` for
the Black Week window and `14_generate_historical_data.py` for the six weeks
before it. They previously each hardcoded the single value "Completed", which
left the column degenerate: every agent that read it concluded, reasonably but
wrongly, that nothing ever went wrong with an order.

The status is now DERIVED from the per-line return outcomes that both
generators already draw. Deriving rather than drawing matters for two reasons:

  1. It consumes no random numbers. Both generators thread a single seeded
     stream through the entire simulation, so drawing even one extra value
     mid-stream would shift every subsequent draw and silently change every
     published figure in the project.

  2. It makes `orders` and `order_items` agree BY CONSTRUCTION. An order can
     never be labelled 'Returned' unless its lines actually carry return
     dates, because both facts come from the same rolls.

Keeping the rule here, in one place, is what stops the two generators drifting
apart - which is exactly how the region vocabulary in
`shipping_lead_times.destination_region` ended up with two spellings.
"""

# Every status a real, placed order can hold.
#
# All three represent a genuine, paid-for purchase: a return happens days AFTER
# the order converts, so none of these should ever be excluded when counting
# orders, sessions-to-orders conversion, or revenue.
#
# A failed payment attempt never becomes an order at all - it appears only in
# payment_gateway_logs with a NULL order_id. Adding 'Payment Failed' rows was
# considered and deliberately deferred; see BACKLOG.md item B27.
PLACED_ORDER_STATUSES = ("Completed", "Partially Returned", "Returned")


def derive_order_status(returned_flags):
    """Return the order-level status implied by its line-level return flags.

    Args:
      returned_flags: an iterable of truthy/falsey values, one per order line,
        where truthy means that line was sent back.

    Returns:
      'Completed'          - no line was returned
      'Partially Returned' - some but not all lines were returned
      'Returned'           - every line was returned

    Raises:
      ValueError: if the order has no lines. An order with no lines is not a
        valid order, and silently returning 'Completed' would hide the bug.
    """
    flags = [bool(f) for f in returned_flags]
    if not flags:
        raise ValueError("an order must have at least one line item")

    n_returned = sum(flags)
    if n_returned == 0:
        return "Completed"
    if n_returned == len(flags):
        return "Returned"
    return "Partially Returned"


def status_distribution(orders):
    """Count how many orders hold each status. Used for the generator summary.

    Returns a dict keyed by status, including a zero entry for any status that
    never occurred - a missing status is the signal that the derivation has
    been broken or bypassed, so it must be visible rather than absent.
    """
    counts = {s: 0 for s in PLACED_ORDER_STATUSES}
    for o in orders:
        counts[o["order_status"]] = counts.get(o["order_status"], 0) + 1
    return counts
