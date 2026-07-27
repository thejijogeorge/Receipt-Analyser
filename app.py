import os
import glob
import subprocess
from datetime import datetime, date
from flask import Flask, render_template, request, jsonify
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from parsers import parse_receipt
from extractors import SUPPORTED_EXTENSIONS
from models import get_session, Receipt, ReceiptItem, GiftCard, GiftCardDeduction

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

                r_date = parsed.get("receipt_date")
                gc_date = datetime.combine(r_date, datetime.min.time()) if r_date else datetime.utcnow()
                redeemed = gc.get("amount_redeemed")

                card = None
                card_balance = None

                if gc.get("balance") is not None:
                    # store reports remaining balance directly (Coles/Woolworths/JB Hi-Fi)
                    card_balance = gc["balance"]
                    if existing:
                        existing.balance = card_balance
                        existing.amount_redeemed = redeemed
                        existing.last_receipt_filename = filename
                        existing.updated_at = gc_date
                        card = existing
                    else:
                        card = GiftCard(
                            last_four=gc["last_four"],
                            balance=card_balance,
                            amount_redeemed=redeemed,
                            store_key=parsed["store_key"],
                            last_receipt_filename=filename,
                            updated_at=gc_date,
                        )
                        session.add(card)
                else:
                    if redeemed is None:
                        continue

                    if existing and existing.balance is not None:
                        # known leftover balance -- just deduct this transaction's redemption
                        card_balance = round(existing.balance - redeemed, 2)
                        existing.balance = card_balance
                        existing.amount_redeemed = redeemed
                        existing.last_receipt_filename = filename
                        existing.updated_at = gc_date
                        card = existing
                    elif existing and existing.balance is None:
                        # already seen but user hasn't confirmed the starting amount yet --
                        # keep accumulating until they do
                        existing.amount_redeemed = round((existing.amount_redeemed or 0) + redeemed, 2)
                        existing.last_receipt_filename = filename
                        existing.updated_at = gc_date
                        card = existing
                        giftcards_to_confirm.append({
                            "id": existing.id,
                            "last_four": gc["last_four"],
                            "store_key": parsed["store_key"],
                            "pending_redeemed": existing.amount_redeemed,
                        })
                    else:
                        card = GiftCard(
                            last_four=gc["last_four"],
                            balance=None,
                            amount_redeemed=redeemed,
                            store_key=parsed["store_key"],
                            last_receipt_filename=filename,
                            updated_at=gc_date,
                        )
                        session.add(card)
                        session.flush()  # assign an id before we reference it below
                        giftcards_to_confirm.append({
                            "id": card.id,
                            "last_four": gc["last_four"],
                            "store_key": parsed["store_key"],
                            "pending_redeemed": redeemed,
                        })

                if card and redeemed is not None:
                    session.flush()  # ensure card has id
                    existing_deduction = session.query(GiftCardDeduction).filter_by(
                        gift_card_id=card.id, receipt_id=receipt.id
                    ).first()
                    if not existing_deduction:
                        session.add(GiftCardDeduction(
                            gift_card_id=card.id,
                            receipt_id=receipt.id,
                            amount_redeemed=redeemed,
                            balance=card_balance
                        ))

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
    track_mode = request.args.get("track", "unit_price")
    session = get_session()
    display_name = func.coalesce(ReceiptItem.real_name, ReceiptItem.item_name)

    if not selected_items:
        item_rows = (
            session.query(display_name)
            .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
            .filter(Receipt.store_key == store_key)
            .distinct()
            .all()
        )
        selected_items = [r[0] for r in item_rows if r[0]]

    track_col = ReceiptItem.unit_price if track_mode == "unit_price" else ReceiptItem.line_total

    per_item = {}
    all_dates = set()

    for item in selected_items:
        rows = (
            session.query(Receipt.receipt_date, track_col.label("price"))
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
            by_date[r.receipt_date] = r.price
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
        
    status_filter = request.args.get("status", "all").strip()
    if status_filter == "has_balance":
        q = q.filter(GiftCard.balance > 0)
    elif status_filter == "no_balance":
        q = q.filter((GiftCard.balance <= 0) | (GiftCard.balance.is_(None)))

    sort_by = request.args.get("sort_by", "last_four").strip()
    sort_dir = request.args.get("sort_dir", "asc").strip()
    
    sort_columns = {
        "last_four": GiftCard.last_four,
        "balance": GiftCard.balance,
        "amount_redeemed": GiftCard.amount_redeemed,
        "last_receipt_filename": GiftCard.last_receipt_filename,
        "updated_at": GiftCard.updated_at
    }
    
    col = sort_columns.get(sort_by, GiftCard.last_four)
    if sort_dir == "desc":
        q = q.order_by(col.desc())
    else:
        q = q.order_by(col.asc())

    cards = q.all()
    session.close()
    return render_template(
        "giftcards.html",
        cards=cards,
        filter_val=filter_val,
        status_filter=status_filter,
        sort_by=sort_by,
        sort_dir=sort_dir,
        store_key=store_key,
        store_name=store_name
    )


@app.route("/giftcard/<int:card_id>/deductions")
def giftcard_deductions(card_id):
    session = get_session()
    card = session.get(GiftCard, card_id)
    if not card:
        session.close()
        return "Gift card not found", 404

    # Fetch store name
    receipt = session.query(Receipt).filter_by(store_key=card.store_key).first()
    store_name = receipt.store_name if receipt else card.store_key

    # Fetch deductions sorted by receipt date ascending (chronological)
    deductions = (
        session.query(GiftCardDeduction)
        .filter(GiftCardDeduction.gift_card_id == card_id)
        .join(Receipt, GiftCardDeduction.receipt_id == Receipt.id)
        .order_by(Receipt.receipt_date.asc())
        .all()
    )

    # Compute running balances
    computed_deductions = []
    
    if card.balance is not None:
        # We know the current balance, so we can calculate the starting balance
        total_redeemed = sum(d.amount_redeemed for d in deductions if d.amount_redeemed)
        running_bal = round(card.balance + total_redeemed, 2)
    else:
        running_bal = None

    for d in deductions:
        # If the store reports the remaining balance directly, use that,
        # otherwise use our computed running balance.
        if d.balance is not None:
            display_bal = d.balance
            # update running_bal to stay in sync
            running_bal = d.balance
        elif running_bal is not None:
            running_bal = round(running_bal - d.amount_redeemed, 2)
            display_bal = running_bal
        else:
            display_bal = None

        computed_deductions.append({
            "date": d.receipt.receipt_date,
            "filename": d.receipt.filename,
            "amount_redeemed": d.amount_redeemed,
            "balance_after": display_bal
        })

    # Sort the list newest first for display
    computed_deductions.reverse()

    session.close()
    return render_template(
        "giftcard_deductions.html",
        card=card,
        store_name=store_name,
        deductions=computed_deductions
    )


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



# ==============================================================================
# REST API V1 ENDPOINTS (FOR MOBILE ANDROID APP & EXTERNAL INTEGRATIONS)
# ==============================================================================

@app.route("/api/v1/health", methods=["GET"])
def api_health():
    """Health check endpoint for Android app to verify server reachability."""
    return jsonify({
        "status": "ok",
        "service": "Receipt Analyser API",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat()
    })


@app.route("/api/v1/stores", methods=["GET"])
def api_stores():
    """Return list of all recognized stores with key and display name."""
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


@app.route("/api/v1/process", methods=["POST"])
def api_process():
    """Process receipts in target folder and return JSON response."""
    data = request.get_json(silent=True) or {}
    folder = data.get("folder") or request.form.get("folder") or os.environ.get("RECEIPTS_FOLDER", "/receipts")
    results, items_to_name, stores_to_name, giftcards_to_confirm = process_folder(folder)
    return jsonify({
        "status": "success",
        "results": results,
        "items_to_name": items_to_name,
        "stores_to_name": stores_to_name,
        "giftcards_to_confirm": giftcards_to_confirm
    })


@app.route("/api/v1/upload", methods=["POST"])
def api_upload():
    """Upload and process single/multiple receipt files directly from phone camera/picker."""
    files = request.files.getlist("file") or request.files.getlist("files")
    if not files or files[0].filename == "":
        return jsonify({"status": "error", "message": "No file provided in request"}), 400

    save_folder = os.environ.get("RECEIPTS_FOLDER", "/receipts")
    if not os.path.exists(save_folder):
        os.makedirs(save_folder, exist_ok=True)

    saved_filenames = []
    for file in files:
        if file and file.filename:
            filename = os.path.basename(file.filename)
            filepath = os.path.join(save_folder, filename)
            file.save(filepath)
            saved_filenames.append(filename)

    results, items_to_name, stores_to_name, giftcards_to_confirm = process_folder(save_folder)
    
    # Filter results to include uploaded files
    uploaded_results = [r for r in results if r.get("filename") in saved_filenames] if saved_filenames else results

    return jsonify({
        "status": "success",
        "saved_files": saved_filenames,
        "results": uploaded_results,
        "items_to_name": items_to_name,
        "stores_to_name": stores_to_name,
        "giftcards_to_confirm": giftcards_to_confirm
    })


@app.route("/api/v1/sync-drive", methods=["POST"])
def api_sync_drive():
    """Trigger Google Drive rclone sync and process new files, returning JSON status."""
    remote = os.environ.get("RCLONE_REMOTE")
    local_folder = os.environ.get("RECEIPTS_FOLDER", "/receipts")

    if not remote:
        return jsonify({"status": "error", "message": "RCLONE_REMOTE not configured"}), 400

    try:
        proc = subprocess.run(
            ["rclone", "sync", remote, local_folder],
            capture_output=True, text=True, timeout=300,
        )
        if proc.returncode != 0:
            return jsonify({"status": "error", "message": f"rclone sync failed: {proc.stderr.strip()[:300]}"}), 500
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "rclone is not installed in this container"}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "message": "rclone sync timed out"}), 504

    results, items_to_name, stores_to_name, giftcards_to_confirm = process_folder(local_folder)
    return jsonify({
        "status": "success",
        "results": results,
        "items_to_name": items_to_name,
        "stores_to_name": stores_to_name,
        "giftcards_to_confirm": giftcards_to_confirm
    })


@app.route("/api/v1/save-names", methods=["POST"])
def api_save_names():
    """Save clean item names. Accepts JSON body e.g. {"items": [{"id": 1, "real_name": "Milk"}]}."""
    data = request.get_json(silent=True) or {}
    items_data = data.get("items", [])
    
    # Fallback to form data if sending form parameters
    if not items_data:
        item_ids = request.form.getlist("item_id")
        items_data = [{"id": i, "real_name": request.form.get(f"real_name_{i}", "")} for i in item_ids]

    session = get_session()
    updated_count = 0

    for entry in items_data:
        item_id = entry.get("id")
        real_name = str(entry.get("real_name", "")).strip()
        if not item_id:
            continue
        item = session.get(ReceiptItem, int(item_id))
        if not item:
            continue
        final_name = real_name if real_name else item.item_name
        session.query(ReceiptItem).filter(
            ReceiptItem.item_name == item.item_name
        ).update({"real_name": final_name}, synchronize_session=False)
        updated_count += 1

    session.commit()
    session.close()
    return jsonify({"status": "success", "updated_count": updated_count})


@app.route("/api/v1/save-store-names", methods=["POST"])
def api_save_store_names():
    """Save custom store display names. Accepts JSON body e.g. {"stores": [{"store_key": "kmart", "store_name": "Kmart Australia"}]}."""
    data = request.get_json(silent=True) or {}
    stores_data = data.get("stores", [])

    if not stores_data:
        store_keys = request.form.getlist("store_key")
        stores_data = [{
            "store_key": sk,
            "store_name": request.form.get(f"store_name_{sk}", ""),
            "detected_name": request.form.get(f"detected_name_{sk}", "")
        } for sk in store_keys]

    session = get_session()
    updated_count = 0

    for entry in stores_data:
        store_key = entry.get("store_key")
        if not store_key:
            continue
        custom_name = str(entry.get("store_name", "")).strip()
        detected_name = str(entry.get("detected_name", "")).strip()
        final_name = custom_name if custom_name else (detected_name or store_key)

        session.query(Receipt).filter(
            Receipt.store_key == store_key
        ).update({"store_name": final_name}, synchronize_session=False)
        updated_count += 1

    session.commit()
    session.close()
    return jsonify({"status": "success", "updated_count": updated_count})


@app.route("/api/v1/confirm-giftcard-initial", methods=["POST"])
def api_confirm_giftcard_initial():
    """Set starting balance for unconfirmed gift cards. Accepts JSON e.g. {"cards": [{"id": 1, "initial_amount": 50.0}]}."""
    data = request.get_json(silent=True) or {}
    cards_data = data.get("cards", [])

    if not cards_data:
        # Check single object or form fallback
        if "id" in data or "gift_card_id" in data:
            cards_data = [data]
        else:
            card_ids = request.form.getlist("gift_card_id")
            cards_data = [{"id": cid, "initial_amount": request.form.get(f"initial_amount_{cid}")} for cid in card_ids]

    session = get_session()
    updated_count = 0

    for entry in cards_data:
        cid = entry.get("id") or entry.get("gift_card_id")
        raw_amount = entry.get("initial_amount")
        if cid is None or raw_amount is None:
            continue
        try:
            initial_amount = float(raw_amount)
        except (ValueError, TypeError):
            continue

        card = session.get(GiftCard, int(cid))
        if card:
            card.balance = round(initial_amount - (card.amount_redeemed or 0), 2)
            updated_count += 1

    session.commit()
    session.close()
    return jsonify({"status": "success", "updated_count": updated_count})


@app.route("/api/v1/giftcards/<store_key>", methods=["GET"])
def api_giftcards(store_key):
    """Return JSON list of gift cards and balances for store."""
    session = get_session()
    receipt = session.query(Receipt).filter_by(store_key=store_key).first()
    store_name = receipt.store_name if receipt else store_key

    q = session.query(GiftCard).filter(GiftCard.store_key == store_key)

    filter_val = request.args.get("last_four", "").strip()
    if filter_val:
        q = q.filter(GiftCard.last_four.like(f"%{filter_val}%"))

    status_filter = request.args.get("status", "all").strip()
    if status_filter == "has_balance":
        q = q.filter(GiftCard.balance > 0)
    elif status_filter == "no_balance":
        q = q.filter((GiftCard.balance <= 0) | (GiftCard.balance.is_(None)))

    sort_by = request.args.get("sort_by", "last_four").strip()
    sort_dir = request.args.get("sort_dir", "asc").strip()

    sort_columns = {
        "last_four": GiftCard.last_four,
        "balance": GiftCard.balance,
        "amount_redeemed": GiftCard.amount_redeemed,
        "last_receipt_filename": GiftCard.last_receipt_filename,
        "updated_at": GiftCard.updated_at
    }

    col = sort_columns.get(sort_by, GiftCard.last_four)
    if sort_dir == "desc":
        q = q.order_by(col.desc())
    else:
        q = q.order_by(col.asc())

    cards = q.all()
    result = [{
        "id": c.id,
        "last_four": c.last_four,
        "balance": c.balance,
        "amount_redeemed": c.amount_redeemed,
        "last_receipt_filename": c.last_receipt_filename,
        "store_key": c.store_key,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None
    } for c in cards]

    session.close()
    return jsonify({
        "store_key": store_key,
        "store_name": store_name,
        "cards": result
    })


@app.route("/api/v1/giftcard/<int:card_id>/deductions", methods=["GET"])
def api_giftcard_deductions(card_id):
    """Return JSON deduction history timeline for a gift card."""
    session = get_session()
    card = session.get(GiftCard, card_id)
    if not card:
        session.close()
        return jsonify({"status": "error", "message": "Gift card not found"}), 404

    receipt = session.query(Receipt).filter_by(store_key=card.store_key).first()
    store_name = receipt.store_name if receipt else card.store_key

    deductions = (
        session.query(GiftCardDeduction)
        .filter(GiftCardDeduction.gift_card_id == card_id)
        .join(Receipt, GiftCardDeduction.receipt_id == Receipt.id)
        .order_by(Receipt.receipt_date.asc())
        .all()
    )

    computed_deductions = []
    if card.balance is not None:
        total_redeemed = sum(d.amount_redeemed for d in deductions if d.amount_redeemed)
        running_bal = round(card.balance + total_redeemed, 2)
    else:
        running_bal = None

    for d in deductions:
        if d.balance is not None:
            display_bal = d.balance
            running_bal = d.balance
        elif running_bal is not None:
            running_bal = round(running_bal - d.amount_redeemed, 2)
            display_bal = running_bal
        else:
            display_bal = None

        computed_deductions.append({
            "date": d.receipt.receipt_date.isoformat() if d.receipt.receipt_date else None,
            "filename": d.receipt.filename,
            "amount_redeemed": d.amount_redeemed,
            "balance_after": display_bal
        })

    computed_deductions.reverse()
    session.close()

    return jsonify({
        "card": {
            "id": card.id,
            "last_four": card.last_four,
            "balance": card.balance,
            "amount_redeemed": card.amount_redeemed,
            "store_key": card.store_key,
            "store_name": store_name
        },
        "deductions": computed_deductions
    })


@app.route("/api/v1/receipts", methods=["GET"])
def api_receipts():
    """Return JSON list of recent receipts."""
    limit = request.args.get("limit", 50, type=int)
    session = get_session()
    receipts = (
        session.query(Receipt)
        .order_by(Receipt.processed_at.desc())
        .limit(limit)
        .all()
    )
    result = []
    for r in receipts:
        total_cost = sum(i.line_total or 0 for i in r.items)
        result.append({
            "id": r.id,
            "filename": r.filename,
            "receipt_date": r.receipt_date.isoformat() if r.receipt_date else None,
            "store_key": r.store_key,
            "store_name": r.store_name,
            "store_location": r.store,
            "item_count": len(r.items),
            "total_cost": round(total_cost, 2),
            "processed_at": r.processed_at.isoformat() if r.processed_at else None
        })
    session.close()
    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)

