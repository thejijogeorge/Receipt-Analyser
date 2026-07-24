import re
from datetime import datetime

DATE_RE = re.compile(r'(?:Date|Transaction)\s*:?\s*(\d{2}[/\.-]\d{2}[/\.-]\d{4})', re.IGNORECASE)
STORE_MATCH_RE = re.compile(
    r'a[abn]beys?|big\s*apple|tallawong|55\s*674\s*313\s*252',
    re.IGNORECASE
)
KG_PRICE_LINE_RE = re.compile(
    r'([\d.]+)\s*kg\s*[Xx]\s*\$?([\d.]+)\s*/\s*kg\s*=\s*\$?([\d.]+)',
    re.IGNORECASE
)
QTY_PRICE_LINE_RE = re.compile(
    r'(\d+)\s*[Xx]\s*\$?([\d.]+)\s*=\s*\$?([\d.]+)',
    re.IGNORECASE
)
NAME_CLEAN_RE = re.compile(r'^[^A-Za-z0-9]+')


def matches(text):
    return bool(STORE_MATCH_RE.search(text))


def parse(text):
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    receipt_date = None
    for line in lines:
        m = DATE_RE.search(line)
        if m:
            raw_date = m.group(1).replace(".", "/").replace("-", "/")
            receipt_date = datetime.strptime(raw_date, "%d/%m/%Y").date()
            break

    store_location = None
    for line in lines:
        if STORE_MATCH_RE.search(line):
            store_location = line
            break
    if not store_location and lines:
        store_location = lines[0]

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
    but item price lines are reliably recognizable even with OCR errors.
    Ambey receipts use two line formats for pricing:
      1) Fixed quantity items:  <qty> X $<unit_price> = $<line_total>
         e.g. "1 X $15.99 = $15.99"
      2) Weight-based items:     <weight>kg X $<price_per_kg>/kg = $<line_total>
         e.g. "1.510kg X $3.49/kg = $5.27"
    The item name is taken from whichever line immediately precedes the price
    line, with leading OCR noise stripped.
    """
    items = []
    for i, line in enumerate(lines):
        if i == 0:
            continue

        km = KG_PRICE_LINE_RE.search(line)
        qm = QTY_PRICE_LINE_RE.search(line) if not km else None

        if not km and not qm:
            continue

        raw_name = lines[i - 1]
        name = NAME_CLEAN_RE.sub("", raw_name).strip()
        if not name:
            continue

        if km:
            unit_price = float(km.group(2))
            line_total = float(km.group(3))
            items.append({
                "item_name": name,
                "quantity": 1,
                "unit_price": unit_price,
                "line_total": line_total,
                "discount": None,
            })
        elif qm:
            quantity = int(qm.group(1))
            unit_price = float(qm.group(2))
            line_total = float(qm.group(3))
            items.append({
                "item_name": name,
                "quantity": quantity,
                "unit_price": unit_price,
                "line_total": line_total,
                "discount": None,
            })

    return items

