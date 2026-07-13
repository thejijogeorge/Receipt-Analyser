import re
from datetime import datetime

QTY_RE = re.compile(r'^(\d+)\s*@\s*\$([\d.]+)\s*EACH$', re.IGNORECASE)
ITEM_RE = re.compile(r'^(%\s*)?(.+?)\s+-?\$?(\d+\.\d{2})$')
NEG_RE = re.compile(r'-\$?(\d+\.\d{2})$')
DATE_RE = re.compile(r'Date:\s*(\d{2}/\d{2}/\d{4})')
STORE_RE = re.compile(r'Store:\s*(.+)')

GIFT_CARD_HEADER_RE = re.compile(r'(\d+)\s+(\d+)\s+COLES GIFT CARD$')
STATUS_RE = re.compile(r'\((\d+)\)(APPROVED|DECLINED)')
BALANCE_RE = re.compile(r'BALANCE\s+AUD\$\s*([\d.]+)')


def matches(text):
    return "Coles Supermarkets" in text or "coles.com.au" in text.lower()


def parse(text):
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    receipt_date = None
    store_location = None
    items = []
    in_items = False

    for line in lines:
        if not receipt_date:
            m = DATE_RE.search(line)
            if m:
                receipt_date = datetime.strptime(m.group(1), "%d/%m/%Y").date()
        if not store_location:
            m = STORE_RE.search(line)
            if m:
                store_location = m.group(1).strip()

        if line.startswith("Description"):
            in_items = True
            continue
        if line.startswith("Total for"):
            in_items = False
            continue
        if not in_items:
            continue

        # quantity line e.g. "2 @ $4.60 EACH" -> updates previous item
        qm = QTY_RE.match(line)
        if qm and items:
            items[-1]["quantity"] = int(qm.group(1))
            items[-1]["unit_price"] = float(qm.group(2))
            continue

        # multi-buy / promo discount line, e.g. "DOLMIO PASTA SAUCE 2 FOR $6 -$3.20"
        # applies to the previous item, not a new item
        neg_m = NEG_RE.search(line)
        if neg_m and items:
            discount = float(neg_m.group(1))
            items[-1]["line_total"] = round(items[-1]["line_total"] - discount, 2)
            items[-1]["discount"] = discount
            continue

        im = ITEM_RE.match(line)
        if im:
            name = im.group(2).strip()
            price = float(im.group(3))
            items.append({
                "item_name": name,
                "quantity": 1,
                "unit_price": price,
                "line_total": price,
                "discount": None,
            })

    gift_cards = _extract_gift_cards(lines)

    return {
        "store_key": "coles",
        "store_name": "Coles",
        "store_location": store_location,
        "receipt_date": receipt_date,
        "items": items,
        "gift_cards": gift_cards,
    }


def _extract_gift_cards(lines):
    """Coles gift card transactions appear as blocks starting with "Coles NSW AU",
    e.g.:
        Coles NSW AU
        04/07/26 17:10 29835162   NL72B7
        627340 182 COLES GIFT CARD
        EXPIRY 05/30
        PURCHASE       AUD$ 2.63
        BALANCE       AUD$ 0.00
        RRN 001120882200    (00)APPROVED
        AUTH 078964

    Declined attempts show "BALANCE UNAVAILABLE" and a DECLINED status; those
    are skipped since there's no usable balance.
    """
    blocks = []
    current = []
    for line in lines:
        if line == "Coles NSW AU":
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append(current)

    cards = []
    for block in blocks:
        header_line = next((l for l in block if l.endswith("COLES GIFT CARD")), None)
        if not header_line:
            continue

        hm = GIFT_CARD_HEADER_RE.search(header_line)
        if not hm:
            continue
        card_id = hm.group(2)

        status_match = None
        for l in block:
            sm = STATUS_RE.search(l)
            if sm:
                status_match = sm
                break
        if not status_match or status_match.group(2) != "APPROVED":
            continue

        balance_line = next((l for l in block if l.startswith("BALANCE")), None)
        if not balance_line:
            continue
        bm = BALANCE_RE.search(balance_line)
        if not bm:
            continue

        cards.append({"last_four": card_id, "balance": float(bm.group(1))})

    return cards
