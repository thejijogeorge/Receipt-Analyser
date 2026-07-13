import re
from datetime import datetime

STORE_LOCATION_RE = re.compile(r'^Kmart\s+(.+)$', re.IGNORECASE)
DATE_RE = re.compile(r'Purchased on\s*(\d{2}/\d{2}/\d{4})')
ITEM_RE = re.compile(r'^(.+?)\s+\$(\d+\.\d{2})$')
GIFT_CARD_RE = re.compile(r'KMART GIFT CARD\s*\(\*+(\w+)\)\s+\$(\d+\.\d{2})')


def matches(text):
    return "kmart" in text.lower()


def parse(text):
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    store_location = None
    receipt_date = None
    for line in lines:
        if not store_location:
            m = STORE_LOCATION_RE.match(line)
            if m:
                store_location = m.group(1).strip()
        if not receipt_date:
            m = DATE_RE.search(line)
            if m:
                receipt_date = datetime.strptime(m.group(1), "%d/%m/%Y").date()

    items = _extract_items(lines)
    gift_cards = _extract_gift_cards(lines)

    return {
        "store_key": "kmart",
        "store_name": "Kmart",
        "store_location": store_location,
        "receipt_date": receipt_date,
        "items": items,
        "gift_cards": gift_cards,
    }


def _extract_items(lines):
    """Item lines sit between the "SALE: ..." line and the "Subtotal" line,
    e.g. "3PK GLASS CLOTH $4.00". Kmart's displayed "Subtotal" is actually
    the pre-GST amount (Total minus GST), not a sum of item lines -- the
    item prices themselves are already GST-inclusive and sum to Total.
    """
    items = []
    in_items = False

    for line in lines:
        if line.startswith("SALE:"):
            in_items = True
            continue
        if line.startswith("Subtotal"):
            in_items = False
            continue
        if not in_items:
            continue

        im = ITEM_RE.match(line)
        if not im:
            continue

        items.append({
            "item_name": im.group(1).strip(),
            "quantity": 1,
            "unit_price": float(im.group(2)),
            "line_total": float(im.group(2)),
            "discount": None,
        })

    return items


def _extract_gift_cards(lines):
    """Kmart receipts only show the amount redeemed from each card in this
    transaction, e.g. "KMART GIFT CARD (*****626) $16.00" -- there's no
    remaining-balance figure printed anywhere on the receipt. So we record
    this under amount_redeemed, not balance, to avoid implying we know the
    card's remaining balance when we don't.
    """
    cards = []
    for line in lines:
        m = GIFT_CARD_RE.search(line)
        if m:
            cards.append({
                "last_four": m.group(1),
                "balance": None,
                "amount_redeemed": float(m.group(2)),
            })
    return cards
