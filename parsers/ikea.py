import re
from datetime import datetime, date

STORE_LOCATION_RE = re.compile(r'Thanks for visiting IKEA\s+(.+?)(?:!|$)', re.IGNORECASE)
DATE_HEADER_RE = re.compile(r'Date\s+Time\s+Store\s+POS', re.IGNORECASE)
ARTICLE_RE = re.compile(r'^Article\s+(\d+)$', re.IGNORECASE)
ITEM_RE = re.compile(r'^(.+?)\s+(-?\d+\.\d{2})\s+(\w)$')
QTY_RE = re.compile(r'^(\d+)\s*(?:x|@|PCS\s*@)\s*([\d.]+)', re.IGNORECASE)
GIFT_CARD_RE = re.compile(r'^Gift\s+card\s+([\d.]+)\s*AUD', re.IGNORECASE)


def matches(text):
    return "ikea" in text.lower()


def parse(text):
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    store_location = None
    receipt_date = None

    for line in lines:
        if not store_location:
            m = STORE_LOCATION_RE.search(line)
            if m:
                store_location = m.group(1).strip()
                break

    for idx, line in enumerate(lines):
        if DATE_HEADER_RE.search(line):
            if idx + 1 < len(lines):
                next_line = lines[idx + 1]
                m = re.search(r'(\d{2})\.(\d{2})\.(\d{2,4})', next_line)
                if m:
                    day, month, year = m.groups()
                    year_val = int(year)
                    if year_val < 100:
                        year_val += 2000
                    receipt_date = date(year_val, int(month), int(day))
                    break

    if not receipt_date:
        # Fallback date search: find DD/MM/YY or DD.MM.YY format with time next to it
        date_matches = re.finditer(r'\b(\d{2})([./])(\d{2})\2(\d{2,4})\s+(\d{2}:\d{2}(?::\d{2})?)\b', text)
        for m in date_matches:
            day, separator, month, year, time_str = m.groups()
            year_val = int(year)
            if year_val < 100:
                year_val += 2000
            if 2000 <= year_val <= 2050:
                receipt_date = date(year_val, int(month), int(day))
                break

    items = _extract_items(lines)
    gift_cards = _extract_gift_cards(lines)

    return {
        "store_key": "ikea",
        "store_name": "IKEA",
        "store_location": store_location,
        "receipt_date": receipt_date,
        "items": items,
        "gift_cards": gift_cards,
    }


def _extract_items(lines):
    items = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = ARTICLE_RE.match(line)
        if m:
            article = m.group(1)
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                im = ITEM_RE.match(next_line)
                if im:
                    raw_name = im.group(1).strip()
                    price = float(im.group(2))
                    
                    qty = 1
                    unit_price = price
                    
                    # Check for quantity line following the item line
                    if i + 2 < len(lines):
                        future_line = lines[i + 2]
                        if not ARTICLE_RE.match(future_line) and not ITEM_RE.match(future_line):
                            qm = QTY_RE.match(future_line)
                            if qm:
                                qty = int(qm.group(1))
                                unit_price = float(qm.group(2))
                                i += 1
                                
                    items.append({
                        "item_name": f"{raw_name} ({article})",
                        "quantity": qty,
                        "unit_price": unit_price,
                        "line_total": price,
                        "discount": None,
                    })
                    i += 1
        i += 1
    return items


def _extract_gift_cards(lines):
    cards = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = GIFT_CARD_RE.match(line)
        if m:
            amount_redeemed = float(m.group(1))
            last_four = None
            balance = None
            
            for j in range(1, 5):
                if i + j >= len(lines):
                    break
                next_line = lines[i + j]
                
                card_m = re.search(r'[xX*]+(\d{4})', next_line)
                if card_m:
                    last_four = card_m.group(1)
                    continue
                
                bal_m = re.search(r'New\s+Balance:\s*([\d.]+)\s*AUD', next_line, re.IGNORECASE)
                if bal_m:
                    balance = float(bal_m.group(1))
                    continue
                    
            if last_four is not None:
                cards.append({
                    "last_four": last_four,
                    "balance": balance,
                    "amount_redeemed": amount_redeemed
                })
        i += 1
    return cards
