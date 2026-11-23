"""Facts about the business that the model needs to draft sensible replies.

Kept in code so the prompt and the mock model read the same source.
"""

COMPANY = {
    "name": "Northbeam Outdoor Gear",
    "support_address": "support@northbeam.example.com",
    "signature": "Northbeam Outdoor Gear Support",
    "products": [
        "Ridgeline 2P Tent",
        "Summit 40 Sleeping Bag",
        "TrailPack 55L",
        "Cascade Stove",
        "Alder Trekking Poles",
        "Pika Headlamp",
        "Granite Water Filter",
        "Fjord Rain Shell",
        "Basecamp Cook Set",
        "Ember Fuel Canister",
    ],
    "policies": [
        "Returns are accepted within 30 days of delivery for unused items.",
        "Refunds and replacements are decided by a staff member, never promised in a first reply.",
        "Order numbers look like NB-12345. Invoice numbers look like INV-2026-0123.",
    ],
}
