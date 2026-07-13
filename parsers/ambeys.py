import re
from datetime import datetime

DATE_RE = re.compile(r'Date:\s*(\d{2}/\d{2}/\d{4})')
PRICE_LINE_RE = re.compile(r'(\d+)\s*[Xx].*?\$?(\d+\.\d{2}).*?=.*?\$?(\d+\.\d{2})')
NAME_CLEAN_RE = re.compile(r'^[^A-Za-z0-9]+')


def matches(text):
    return "ambeys" in text.lower()


def parse(text):
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    receipt_date = None
    for line in lines:
        m = DATE_RE.search(line)
        if m:
            receipt_date = datetime.strptime(m.group(1), "%d/%m/%Y").date()
            break

    store_location = None
    for line in lines:
        if "ambeys" in line.lower():
            store_location = line
            break

    items = _extract_items(lines)

    return {
        "store_key": "ambeys",
        "store_name": "Ambeys",
        "store_location": store_location,
        "receipt_date": receipt_date,
        "items": items,
        "gift_cards": [],
    }


def _extract_items(lines):
    """OCR of a photographed receipt is noisy, especially in item names --
    but the "qty X unit_price = line_total" line is reliably recognizable
    even with OCR errors elsewhere, so we anchor on that pattern rather
    than trying to detect section boundaries (which get garbled
    unpredictably). The item name is taken from whichever line immediately
    precedes the matched price line, with leading OCR noise (stray
    asterisks, symbols the taxable-item marker got misread as) stripped.
    """
    items = []
    for i, line in enumerate(lines):
        pm = PRICE_LINE_RE.search(line)
        if not pm or i == 0:
            continue

        raw_name = lines[i - 1]
        name = NAME_CLEAN_RE.sub("", raw_name).strip()
        if not name:
            continue

        items.append({
            "item_name": name,
            "quantity": int(pm.group(1)),
            "unit_price": float(pm.group(2)),
            "line_total": float(pm.group(3)),
            "discount": None,
        })

    return items
