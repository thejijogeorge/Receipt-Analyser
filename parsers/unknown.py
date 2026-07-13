import re

SLUG_RE = re.compile(r'[^a-z0-9]+')


def build_unknown_store_key(text):
    """Derive a stable identifier for an unrecognized store from the first
    non-blank line of its receipt text, so repeat receipts from the same
    (unrecognized) store group together under one key even before the user
    has given it a real name.
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    first_line = lines[0] if lines else "unknown"
    slug = SLUG_RE.sub("_", first_line.lower()).strip("_")[:60]
    return f"unknown_{slug}" if slug else "unknown_receipt"


def parse(text):
    """We can't reliably extract items from a format we don't recognize --
    guessing risks silently parsing garbage into the DB. So we still save
    the receipt (so the user can name the store and know it was seen), but
    with an empty item list rather than a guessed one.
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    first_line = lines[0] if lines else "Unknown store"

    return {
        "store_key": build_unknown_store_key(text),
        "store_name": None,  # left blank -- shows up in the "confirm store" step
        "store_location": first_line,
        "receipt_date": None,
        "items": [],
        "gift_cards": [],
    }
