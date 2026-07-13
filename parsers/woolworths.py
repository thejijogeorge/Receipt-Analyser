import re
from datetime import datetime

from .utils import split_on_dashes

STORE_LOCATION_RE = re.compile(r'^(\d+)\s+(.+?)\s+PH:')
DATE_RE = re.compile(r'TRANS\s+\d+\s+\d{2}:\d{2}\s+(\d{2}/\d{2}/\d{4})')
ITEM_RE = re.compile(r'^([\^#]*)(.+?)\s+(-?\d+\.\d{2})$')
SUBTOTAL_RE = re.compile(r'^\d+\s+SUBTOTAL')
BASKET_DISCOUNT_KEYWORDS = ("everyday extra",)

CARD_RE = re.compile(r'CARD:\.+(\d+)')
BALANCE_RE = re.compile(r'BALANCE\s+\$?([\d.]+)')


def matches(text):
    return "WOOLWORTHS" in text.upper()


def parse(text):
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    store_location = None
    receipt_date = None
    for line in lines:
        if not store_location:
            m = STORE_LOCATION_RE.match(line)
            if m:
                store_location = f"{m.group(1)} {m.group(2)}".strip()
        if not receipt_date:
            m = DATE_RE.search(line)
            if m:
                receipt_date = datetime.strptime(m.group(1), "%d/%m/%Y").date()

    items = _extract_items(lines)
    gift_cards = _extract_gift_cards(lines)

    return {
        "store_key": "woolworths",
        "store_name": "Woolworths",
        "store_location": store_location,
        "receipt_date": receipt_date,
        "items": items,
        "gift_cards": gift_cards,
    }


def _extract_items(lines):
    items = []
    in_items = False

    for line in lines:
        if line.startswith("Description"):
            in_items = True
            continue
        if SUBTOTAL_RE.match(line):
            in_items = False
            continue
        if not in_items:
            continue

        im = ITEM_RE.match(line)
        if not im:
            continue

        name = im.group(2).strip()
        price = float(im.group(3))

        # basket-level discounts (e.g. "Everyday Extra Perk -6.00",
        # "Everyday Extra 10% Discount -9.83") aren't tied to one item --
        # they're subtracted from the whole basket, so don't record them
        # as purchasable items
        if any(kw in name.lower() for kw in BASKET_DISCOUNT_KEYWORDS):
            continue

        items.append({
            "item_name": name,
            "quantity": 1,
            "unit_price": price,
            "line_total": price,
            "discount": None,
        })

    return items


def _extract_gift_cards(lines):
    """Woolworths gift card redemptions appear as dash-delimited blocks, e.g.:
        WOOLWORTHS 1941
        SCHOFIELDS NSW
        MERCH ID:611000602001941
        QC GIFT CARD SAVINGS
        19/03/26 17:45 006517
        TERM ID: W1941063
        CARD:.............4855 B
        REDEMPTION $78.47
        TOTAL $78.47
        BALANCE $0.00
        APPROVED 00
    """
    blocks = split_on_dashes(lines, min_length=15)
    cards = []

    for block in blocks:
        if not any("GIFT CARD" in l.upper() for l in block):
            continue
        if not any("APPROVED" in l for l in block):
            continue  # skip declined redemptions

        card_line = next((l for l in block if l.startswith("CARD:")), None)
        if not card_line:
            continue
        cm = CARD_RE.search(card_line)
        if not cm:
            continue
        card_id = cm.group(1)

        balance_line = next((l for l in block if l.startswith("BALANCE")), None)
        if not balance_line:
            continue
        bm = BALANCE_RE.search(balance_line)
        if not bm:
            continue

        cards.append({"last_four": card_id, "balance": float(bm.group(1))})

    return cards
