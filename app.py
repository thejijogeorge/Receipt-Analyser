import os
import glob
import subprocess
from datetime import datetime, date
from flask import Flask, render_template, request, jsonify
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from parsers import parse_receipt
from extractors import SUPPORTED_EXTENSIONS
from models import get_session, Receipt, ReceiptItem, GiftCard

app = Flask(__name__)


@app.route("/")
def index():
    session = get_session()
    stores = (
        session.query(Receipt.store_key, Receipt.store_name)
        .filter(Receipt.store_name.isnot(None))
        .distinct()
        .order_by(Receipt.store_name)
        .all()
    )
    session.close()
    return render_template("index.html", results=None, items_to_name=None, stores_to_name=None, giftcards_to_confirm=None, stores=stores)


def process_folder(folder):
    results = []
    items_to_name = []
    stores_to_name = []
    giftcards_to_confirm = []

    if not folder or not os.path.isdir(folder):
        results.append({"filename": folder, "status": "error", "detail": "Folder not found", "date": ""})
        return results, items_to_name, stores_to_name, giftcards_to_confirm

    all_files = sorted(glob.glob(os.path.join(folder, "*")))
    receipt_paths = [f for f in all_files if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS]
    if not receipt_paths:
        results.append({"filename": folder, "status": "error", "detail": "No receipt files (PDF/JPG/PNG) found in folder", "date": ""})
        return results, items_to_name, stores_to_name, giftcards_to_confirm

    session = get_session()

    # Parse every file first, then apply them to the DB in chronological
    # order (by the receipt's own date), not filename order. This matters
    # because gift card balances (and other date-dependent state) must be
    # applied in true time order -- e.g. "14_feb_2026.pdf" sorts before
    # "7_Feb_2026.pdf" alphabetically despite being the later receipt,
    # which would otherwise leave a stale/wrong balance stored after a
    # batch run.
    parsed_files = []
    for receipt_path in receipt_paths:
        filename = os.path.basename(receipt_path)
        try:
            parsed = parse_receipt(receipt_path)
            parsed_files.append({"path": receipt_path, "filename": filename, "parsed": parsed, "parse_error": None})
        except Exception as e:
            parsed_files.append({"path": receipt_path, "filename": filename, "parsed": None, "parse_error": str(e)})

    def sort_key(entry):
        parsed = entry["parsed"]
        if parsed and parsed.get("receipt_date"):
            return (0, parsed["receipt_date"])
        return (1, date.max)  # undated or failed-to-parse -- process last

    parsed_files.sort(key=sort_key)

    for entry in parsed_files:
        filename = entry["filename"]
        try:
            if entry["parse_error"]:
                raise Exception(entry["parse_error"])
            parsed = entry["parsed"]

            receipt = Receipt(
                filename=filename,
                receipt_date=parsed["receipt_date"],
                store=parsed["store_location"],
                store_key=parsed["store_key"],
                store_name=parsed["store_name"],
            )
            for item in parsed["items"]:
                receipt.items.append(ReceiptItem(**item))

            session.add(receipt)
            session.commit()

            for gc in parsed.get("gift_cards", []):
                existing = session.query(GiftCard).filter_by(
                    last_four=gc["last_four"], store_key=parsed["store_key"]
                ).first()

                if gc.get("balance") is not None:
                    # store reports remaining balance directly (Coles/Woolworths/JB Hi-Fi)
                    if existing:
                        existing.balance = gc["balance"]
                        existing.last_receipt_filename = filename
                        existing.updated_at = datetime.utcnow()
                    else:
                        session.add(GiftCard(
                            last_four=gc["last_four"],
                            balance=gc["balance"],
                            store_key=parsed["store_key"],
                            last_receipt_filename=filename,
                            updated_at=datetime.utcnow(),
                        ))
                    continue

                redeemed = gc.get("amount_redeemed")
                if redeemed is None:
                    continue

                if existing and existing.balance is not None:
                    # known leftover balance -- just deduct this transaction's redemption
                    existing.balance = round(existing.balance - redeemed, 2)
                    existing.amount_redeemed = redeemed
                    existing.last_receipt_filename = filename
                    existing.updated_at = datetime.utcnow()
                elif existing and existing.balance is None:
                    # already seen but user hasn't confirmed the starting amount yet --
                    # keep accumulating until they do
                    existing.amount_redeemed = round((existing.amount_redeemed or 0) + redeemed, 2)
                    existing.last_receipt_filename = filename
                    existing.updated_at = datetime.utcnow()
                    giftcards_to_confirm.append({
                        "id": existing.id,
                        "last_four": gc["last_four"],
                        "store_key": parsed["store_key"],
                        "pending_redeemed": existing.amount_redeemed,
                    })
                else:
                    new_card = GiftCard(
                        last_four=gc["last_four"],
                        balance=None,
                        amount_redeemed=redeemed,
                        store_key=parsed["store_key"],
                        last_receipt_filename=filename,
                        updated_at=datetime.utcnow(),
                    )
                    session.add(new_card)
                    session.flush()  # assign an id before we reference it below
                    giftcards_to_confirm.append({
                        "id": new_card.id,
                        "last_four": gc["last_four"],
                        "store_key": parsed["store_key"],
                        "pending_redeemed": redeemed,
                    })

            session.commit()

            for item in receipt.items:
                items_to_name.append({"id": item.id, "item_name": item.item_name})

            if parsed["store_name"] is None:
                stores_to_name.append({
                    "store_key": parsed["store_key"],
                    "detected_name": parsed["store_location"] or parsed["store_key"],
                })

            if parsed["items"]:
                detail = f"{len(parsed['items'])} items saved"
            elif parsed["store_name"] is None:
                detail = "Unrecognized store format -- saved for naming, no items parsed"
            else:
                detail = "0 items parsed -- check receipt format"

            results.append({
                "filename": filename,
                "status": "ok",
                "detail": detail,
                "date": parsed["receipt_date"].isoformat() if parsed["receipt_date"] else "",
            })

        except IntegrityError:
            session.rollback()
            results.append({"filename": filename, "status": "skipped", "detail": "Already processed", "date": ""})
        except Exception as e:
            session.rollback()
            results.append({"filename": filename, "status": "error", "detail": str(e), "date": ""})

    session.close()

    # de-dupe stores_to_name by store_key (multiple receipts from the same
    # unrecognized store in one batch should only show one naming row)
    seen = set()
    deduped_stores = []
    for s in stores_to_name:
        if s["store_key"] not in seen:
            seen.add(s["store_key"])
            deduped_stores.append(s)

    # de-dupe giftcards_to_confirm by card id, keeping the last (most
    # up-to-date accumulated) entry if the same unconfirmed card shows up
    # across multiple receipts in one batch
    deduped_cards = {}
    for gc in giftcards_to_confirm:
        deduped_cards[gc["id"]] = gc

    return results, items_to_name, deduped_stores, list(deduped_cards.values())


@app.route("/process", methods=["POST"])
def process():
    folder = request.form.get("folder", "").strip()
    results, items_to_name, stores_to_name, giftcards_to_confirm = process_folder(folder)
    return render_template("_results.html", results=results, items_to_name=items_to_name,
                            stores_to_name=stores_to_name, giftcards_to_confirm=giftcards_to_confirm)


@app.route("/sync-drive", methods=["POST"])
def sync_drive():
    remote = os.environ.get("RCLONE_REMOTE")
    local_folder = os.environ.get("RECEIPTS_FOLDER", "/receipts")

    if not remote:
        results = [{"filename": "", "status": "error", "detail": "RCLONE_REMOTE not configured", "date": ""}]
        return render_template("_results.html", results=results, items_to_name=[], stores_to_name=[], giftcards_to_confirm=[])

    try:
        proc = subprocess.run(
            ["rclone", "sync", remote, local_folder],
            capture_output=True, text=True, timeout=300,
        )
        if proc.returncode != 0:
            results = [{"filename": remote, "status": "error", "detail": f"rclone sync failed: {proc.stderr.strip()[:300]}", "date": ""}]
            return render_template("_results.html", results=results, items_to_name=[], stores_to_name=[], giftcards_to_confirm=[])
    except FileNotFoundError:
        results = [{"filename": "", "status": "error", "detail": "rclone is not installed in this container", "date": ""}]
        return render_template("_results.html", results=results, items_to_name=[], stores_to_name=[], giftcards_to_confirm=[])
    except subprocess.TimeoutExpired:
        results = [{"filename": remote, "status": "error", "detail": "rclone sync timed out", "date": ""}]
        return render_template("_results.html", results=results, items_to_name=[], stores_to_name=[], giftcards_to_confirm=[])

    results, items_to_name, stores_to_name, giftcards_to_confirm = process_folder(local_folder)
    return render_template("_results.html", results=results, items_to_name=items_to_name,
                            stores_to_name=stores_to_name, giftcards_to_confirm=giftcards_to_confirm)


@app.route("/save-names", methods=["POST"])
def save_names():
    session = get_session()
    item_ids = request.form.getlist("item_id")

    for item_id in item_ids:
        real_name = request.form.get(f"real_name_{item_id}", "").strip()
        item = session.get(ReceiptItem, int(item_id))
        if not item:
            continue
        final_name = real_name if real_name else item.item_name
        # apply to every row that shares this receipt's original item_name,
        # not just the one row being edited
        session.query(ReceiptItem).filter(
            ReceiptItem.item_name == item.item_name
        ).update({"real_name": final_name}, synchronize_session=False)

    session.commit()
    session.close()
    return render_template("_names_saved.html")


@app.route("/save-store-names", methods=["POST"])
def save_store_names():
    session = get_session()
    store_keys = request.form.getlist("store_key")

    for store_key in store_keys:
        custom_name = request.form.get(f"store_name_{store_key}", "").strip()
        detected_name = request.form.get(f"detected_name_{store_key}", "").strip()
        final_name = custom_name if custom_name else (detected_name or store_key)

        # apply to every receipt sharing this store_key, past and future
        session.query(Receipt).filter(
            Receipt.store_key == store_key
        ).update({"store_name": final_name}, synchronize_session=False)

    session.commit()
    session.close()
    return render_template("_names_saved.html")


@app.route("/confirm-giftcard-initial", methods=["POST"])
def confirm_giftcard_initial():
    session = get_session()
    card_ids = request.form.getlist("gift_card_id")

    for cid in card_ids:
        raw_amount = request.form.get(f"initial_amount_{cid}", "").strip()
        if not raw_amount:
            continue  # leave unconfirmed -- will keep accumulating until answered
        try:
            initial_amount = float(raw_amount)
        except ValueError:
            continue

        card = session.get(GiftCard, int(cid))
        if card:
            card.balance = round(initial_amount - (card.amount_redeemed or 0), 2)

    session.commit()
    session.close()
    return render_template("_names_saved.html")


@app.route("/analytics/<store_key>")
def analytics(store_key):
    session = get_session()
    receipt = session.query(Receipt).filter_by(store_key=store_key).first()
    store_name = receipt.store_name if receipt else store_key
    session.close()
    return render_template("analytics.html", store_key=store_key, store_name=store_name)


@app.route("/analytics/<store_key>/items")
def analytics_items(store_key):
    session = get_session()
    display_name = func.coalesce(ReceiptItem.real_name, ReceiptItem.item_name)
    rows = (
        session.query(display_name)
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .filter(Receipt.store_key == store_key)
        .distinct()
        .order_by(display_name)
        .all()
    )
    session.close()
    return jsonify([r[0] for r in rows if r[0]])


@app.route("/analytics/<store_key>/data")
def analytics_data(store_key):
    selected_items = request.args.getlist("item")
    session = get_session()
    display_name = func.coalesce(ReceiptItem.real_name, ReceiptItem.item_name)

    per_item = {}
    all_dates = set()

    for item in selected_items:
        rows = (
            session.query(Receipt.receipt_date, ReceiptItem.unit_price)
            .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
            .filter(display_name == item)
            .filter(Receipt.store_key == store_key)
            .filter(Receipt.receipt_date.isnot(None))
            .order_by(Receipt.receipt_date)
            .all()
        )
        if not rows:
            per_item[item] = {"by_date": {}, "purchase_count": 0, "avg_days_between": None}
            continue

        by_date = {}
        for r in rows:
            by_date[r.receipt_date] = r.unit_price
            all_dates.add(r.receipt_date)

        dates_sorted = sorted(by_date.keys())
        days_between = [(dates_sorted[i] - dates_sorted[i - 1]).days for i in range(1, len(dates_sorted))]
        avg_days = round(sum(days_between) / len(days_between), 1) if days_between else None

        per_item[item] = {
            "by_date": by_date,
            "purchase_count": len(rows),
            "avg_days_between": avg_days,
        }

    session.close()

    labels = sorted(all_dates)
    label_strs = [d.isoformat() for d in labels]

    series = []
    for item in selected_items:
        info = per_item[item]
        data = [info["by_date"].get(d) for d in labels]
        series.append({
            "item": item,
            "data": data,
            "purchase_count": info["purchase_count"],
            "avg_days_between": info["avg_days_between"],
        })

    return jsonify({"labels": label_strs, "series": series})


@app.route("/giftcards/<store_key>")
def giftcards(store_key):
    session = get_session()
    receipt = session.query(Receipt).filter_by(store_key=store_key).first()
    store_name = receipt.store_name if receipt else store_key

    q = session.query(GiftCard).filter(GiftCard.store_key == store_key)
    filter_val = request.args.get("last_four", "").strip()
    if filter_val:
        q = q.filter(GiftCard.last_four.like(f"%{filter_val}%"))
    cards = q.order_by(GiftCard.last_four).all()
    session.close()
    return render_template("giftcards.html", cards=cards, filter_val=filter_val, store_key=store_key, store_name=store_name)


@app.route("/expenses")
def expenses():
    return render_template("expenses.html")


@app.route("/expenses/stores")
def expenses_stores():
    session = get_session()
    stores = (
        session.query(Receipt.store_key, Receipt.store_name)
        .filter(Receipt.store_name.isnot(None))
        .distinct()
        .order_by(Receipt.store_name)
        .all()
    )
    session.close()
    return jsonify([{"store_key": k, "store_name": n} for k, n in stores])


@app.route("/expenses/data")
def expenses_data():
    selected_stores = request.args.getlist("store")
    session = get_session()

    q = (
        session.query(Receipt.receipt_date, ReceiptItem.line_total)
        .join(ReceiptItem, ReceiptItem.receipt_id == Receipt.id)
        .filter(Receipt.receipt_date.isnot(None))
    )
    if selected_stores:
        q = q.filter(Receipt.store_key.in_(selected_stores))

    rows = q.all()
    session.close()

    # aggregate by (year, month) in Python rather than via DB-specific date
    # truncation functions, so this works identically whether the DB is
    # SQL Server or Postgres
    monthly = {}
    for receipt_date, line_total in rows:
        key = (receipt_date.year, receipt_date.month)
        monthly[key] = monthly.get(key, 0) + (line_total or 0)

    sorted_keys = sorted(monthly.keys())
    labels = [f"{y}-{m:02d}" for y, m in sorted_keys]
    totals = [round(monthly[k], 2) for k in sorted_keys]

    total_spend = round(sum(totals), 2)
    avg_monthly = round(total_spend / len(totals), 2) if totals else 0

    return jsonify({
        "labels": labels,
        "totals": totals,
        "total_spend": total_spend,
        "avg_monthly": avg_monthly,
        "month_count": len(totals),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
