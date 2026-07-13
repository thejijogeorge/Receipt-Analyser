import re
from datetime import datetime

from .utils import split_on_dashes

STORE_LOCATION_RE = re.compile(r'^JB HIFI\s*-\s*(.+)$', re.IGNORECASE)
DATE_RE = re.compile(r'(\d{2}/\d{2}/\d{2})\s+\d{2}:\d{2}')
SKU_PRICE_RE = re.compile(r'^(\d+)\s+(-?\d+\.\d{2})$')
QTY_RE = re.compile(r'^qty\s+(\d+)\s+@\s+\$([\d.]+)\s+each$', re.IGNORECASE)
LESS_RE = re.compile(r'^LESS\s+[\d.]+%\s+-\$\s*([\d.]+)$', re.IGNORECASE)
NON_ITEM_PREFIXES = ("VOUCHER", "V#")

MASKED_CARD_RE = re.compile(r'\d+\.\.\.(\d+)')
REF_NO_RE = re.compile(r'Ref No:\s*([\d\-]+)')
BALANCE_RE = re.compile(r'Avail Balance:\s*\$([\d.]+)')


def matches(text):
    upper = text.upper()
    return "JB HI-FI" in upper or "JB HIFI" in upper


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
                receipt_date = datetime.strptime(m.group(1), "%d/%m/%y").date()

    items = _extract_items(lines)
    gift_cards = _extract_gift_cards(lines)

    return {
        "store_key": "jbhifi",
        "store_name": "JB Hi-Fi",
        "store_location": store_location,
        "receipt_date": receipt_date,
        "items": items,
        "gift_cards": gift_cards,
    }


def _extract_items(lines):
    items = []
    in_items = False

    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("Items"):
            in_items = True
            i += 1
            continue
        if line.startswith("SUBTOTAL"):
            in_items = False
            i += 1
            continue
        if not in_items:
            i += 1
            continue

        if any(line.startswith(p) for p in NON_ITEM_PREFIXES):
            i += 1
            continue

        qm = QTY_RE.match(line)
        if qm and items:
            items[-1]["quantity"] = int(qm.group(1))
            items[-1]["unit_price"] = float(qm.group(2))
            i += 1
            continue

        lm = LESS_RE.match(line)
        if lm and items:
            # the SKU/price line above is already post-discount, so just
            # record the discount for reference -- don't subtract again
            items[-1]["discount"] = float(lm.group(1))
            i += 1
            continue

        sku_m = SKU_PRICE_RE.match(line)
        if sku_m and items:
            # this line is the SKU + price for the most recently named item
            price = float(sku_m.group(2))
            items[-1]["unit_price"] = price
            items[-1]["line_total"] = price
            i += 1
            continue

        # otherwise, this is a new item name line
        name = line.lstrip("*").strip()
        if name:
            items.append({
                "item_name": name,
                "quantity": 1,
                "unit_price": None,
                "line_total": None,
                "discount": None,
            })
        i += 1

    # drop any item that never got a price (shouldn't normally happen)
    return [it for it in items if it["line_total"] is not None]


def _extract_gift_cards(lines):
    """JB Hi-Fi gift card redemptions appear as dash-delimited blocks, e.g.:
        Terminal: JBHIFI61079002
        Ref No: 204685231-1
        502904...9023
        REDEMPTION:
        Value: $46.00
        Avail Balance: $0.00
        APPROVED 00 423663

    The masked card number is sometimes cut off across a page break (no
    trailing digits e.g. "502904..."); when that happens we fall back to
    the block's Ref No as the identifier instead, since it's still unique
    per transaction even if less precise than an actual card suffix.
    """
    blocks = split_on_dashes(lines)
    cards = []

    for block in blocks:
        if not any("REDEMPTION:" in l for l in block):
            continue
        if not any("APPROVED" in l for l in block):
            continue  # skip declined/failed redemptions

        card_id = None
        for l in block:
            mm = MASKED_CARD_RE.search(l)
            if mm:
                card_id = mm.group(1)
                break

        if not card_id:
            ref_m = next((REF_NO_RE.search(l) for l in block if REF_NO_RE.search(l)), None)
            if ref_m:
                card_id = ref_m.group(1)

        if not card_id:
            continue

        balance_line = next((l for l in block if l.startswith("Avail Balance")), None)
        if not balance_line:
            continue
        bm = BALANCE_RE.search(balance_line)
        if not bm:
            continue

        cards.append({"last_four": card_id, "balance": float(bm.group(1))})

    return cards
