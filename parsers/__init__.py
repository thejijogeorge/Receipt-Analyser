from extractors import extract_text

from . import coles, jbhifi, woolworths, kmart, ambeys, ikea, unknown

STORE_MODULES = [coles, jbhifi, woolworths, kmart, ambeys, ikea]


def detect_store_module(text):
    for module in STORE_MODULES:
        if module.matches(text):
            return module
    return None


def parse_receipt(file_path):
    """Extract text from a receipt file (PDF or photographed/scanned image)
    and parse it with the matching store module. Returns a dict with:
        store_key, store_name, store_location, receipt_date, items, gift_cards
    Unrecognized formats fall back to `unknown`, which saves the receipt
    (so it shows up for the user to name) but with no items, rather than
    guessing at a format we don't know.
    """
    text = extract_text(file_path)

    module = detect_store_module(text)
    if module:
        return module.parse(text)
    return unknown.parse(text)
