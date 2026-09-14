"""Shared clickstream profile for both generators.

`02_generate_data.py` produces the Black Week clickstream and
`14_generate_historical_data.py` produces the six weeks before it. They write
to the SAME `web_sessions` and `web_events` tables, so any difference in shape
between them appears in the data as a step change on 23 November.

That matters more than it sounds. This codebase has already been bitten by
exactly that failure: historical payment logs were once 100% successful, which
made Black Week's ordinary ~7% failure rate look like a gateway outage - a
false root cause louder than any of the three real ones, and one every agent
tier could "discover".

Everything here is therefore defined ONCE and imported by both. A funnel step
or device mix added to one generator and not the other is not possible.

Nothing in this module draws random numbers. The callers pass in their own
rolls, so each generator keeps full control of its own seeded stream.
"""

# The ordered journey a session walks through. Sessions longer than this repeat
# product_view; sessions shorter than it simply stop partway.
EVENT_FUNNEL = [
    ("page_view", "https://lumiereshop.eu/"),
    ("category_view", "https://lumiereshop.eu/categories/{cat}"),
    ("search_query", "https://lumiereshop.eu/search"),
    ("filter_applied", "https://lumiereshop.eu/categories/{cat}?filter=price"),
    ("product_view", "https://lumiereshop.eu/products/{pid}"),
    ("image_zoom", "https://lumiereshop.eu/products/{pid}#gallery"),
    ("review_read", "https://lumiereshop.eu/products/{pid}#reviews"),
    ("wishlist_add", "https://lumiereshop.eu/wishlist"),
    ("cart_add", "https://lumiereshop.eu/cart"),
    ("cart_view", "https://lumiereshop.eu/cart"),
    ("checkout_start", "https://lumiereshop.eu/checkout"),
    ("checkout_shipping_select", "https://lumiereshop.eu/checkout/shipping"),
    ("checkout_payment_select", "https://lumiereshop.eu/checkout/payment"),
    ("checkout_review", "https://lumiereshop.eu/checkout/review"),
]

# Events that happen WITHIN a page rather than navigating to a new one.
#
# web_events records every interaction, so the event count and the page-view
# count are deliberately different numbers. Subtracting these is what makes
# web_sessions.page_views_count a genuine engagement measure rather than a
# second copy of the event total.
NON_PAGEVIEW_EVENTS = frozenset({
    "filter_applied", "image_zoom", "review_read", "wishlist_add", "cart_add",
})

assert NON_PAGEVIEW_EVENTS.issubset({e for e, _ in EVENT_FUNNEL}), \
    "NON_PAGEVIEW_EVENTS names an event type the funnel never emits"

# Clickstream depth. TECHNICAL_SPECIFICATION.md section 3.2 requires a mean of
# 15-25 events per session. Converting sessions run deeper because they
# traverse the whole checkout.
EVENTS_PER_SESSION_RANGE = (7, 33)          # mean ~19.5
EVENTS_PER_CONVERTING_SESSION = (20, 42)    # mean ~30.5

# Gap between consecutive events, in seconds.
EVENT_GAP_SECONDS = (8, 95)

# Device mix, expressed as cumulative thresholds on a uniform [0, 1) roll.
# The caller supplies the roll so that each generator keeps control of its own
# random stream.
_DEVICE_OS_THRESHOLDS = ((0.52, "iOS"), (0.85, "Android"), (0.96, "Windows"))
_DEFAULT_OS = "macOS"

_BROWSER_BY_OS = {
    "iOS": "Safari",
    "macOS": "Safari",
    "Android": "Chrome",
    "Windows": "Edge",
}


def device_os_for(roll):
    """Map a uniform [0, 1) roll to an operating system."""
    for threshold, name in _DEVICE_OS_THRESHOLDS:
        if roll < threshold:
            return name
    return _DEFAULT_OS


def browser_for(device_os):
    """The browser that ships as default on the given operating system."""
    return _BROWSER_BY_OS[device_os]


def event_at_step(step, n_events, converted, cat_id, product_id):
    """Return (event_type, page_url) for one step of a session.

    A converting session always ends on checkout_success; that is what makes
    `converted_to_order` verifiable from the event stream itself rather than
    being an unsupported flag on the session row.
    """
    if converted and step == n_events - 1:
        return "checkout_success", "https://lumiereshop.eu/order-confirmed"
    if step < len(EVENT_FUNNEL):
        event_type, url = EVENT_FUNNEL[step]
    else:
        event_type, url = "product_view", "https://lumiereshop.eu/products/{pid}"
    return event_type, url.format(cat=cat_id, pid=product_id)


def is_page_view(event_type):
    """True when the event navigated to a new page."""
    return event_type not in NON_PAGEVIEW_EVENTS
