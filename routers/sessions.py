# routers/sessions.py
import io
import json
import secrets
import sqlite3
from typing import Optional
from PIL import Image

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from pydantic import BaseModel

from core.config import DB_PATH, THRESHOLD
from core.time import now_iso
from db import connect, cart_for, product_by_label, upsert_item, save_frame, save_image
from ml import infer_pil

router = APIRouter()


def get_db():
    db = connect(DB_PATH)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class SessionStart(BaseModel):
    device_id: str


# 1. BẮT ĐẦU
@router.post("/sessions")
def start_session(payload: SessionStart, con: sqlite3.Connection = Depends(get_db)):
    sid = secrets.token_urlsafe(8)
    con.execute(
        "INSERT INTO sessions(id, device_id, state, created_at) VALUES(?, ?, 'ACTIVE', ?)",
        (sid, payload.device_id, now_iso()),
    )
    return {"session_id": sid, "state": "ACTIVE", "created_at": now_iso()}


# 2. QUÉT ẢNH (Chỉ cho phép khi ACTIVE)
@router.post("/sessions/{session_id}/frames")
def ingest_frame(
        session_id: str,
        image: UploadFile = File(...),
        frame_id: str = Form(...),
        device_id: str = Form(...),
        ts: Optional[str] = Form(None),
        con: sqlite3.Connection = Depends(get_db)
):
    # Check state: Chỉ ACTIVE mới được thêm hàng
    row = con.execute("SELECT state FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        raise HTTPException(404, "session not found")

    # Nếu đang chờ thanh toán hoặc đã thanh toán thì không nhận ảnh nữa
    if row["state"] != "ACTIVE":
        # Trả về nhẹ nhàng để Client biết mà dừng gửi, hoặc báo lỗi 409 tùy bạn
        return {"frame_id": frame_id, "error": f"Session is {row['state']}, cannot add items"}

    existed = con.execute("SELECT result_json FROM frames WHERE frame_id = ?", (frame_id,)).fetchone()
    if existed:
        try:
            prev = json.loads(existed["result_json"])
        except Exception:
            prev = {"frame_id": frame_id, "added": False, "proposal": {"label": "unknown"}}
        curr_total = con.execute("SELECT total_amount FROM sessions WHERE id=?", (session_id,)).fetchone()[0]
        prev["current_total"] = curr_total
        return prev

    raw = image.file.read()
    path = save_image(device_id, frame_id, raw)
    img = Image.open(io.BytesIO(raw))
    out = infer_pil(img)

    added = False
    proposal = {}

    if out["label"] != "unknown":
        prod = product_by_label(con, out["label"])
        upsert_item(con, session_id, prod["id"], prod["price"])
        added = True
        proposal = {
            "product_id": prod["id"],
            "name": prod["name"],
            "price": prod["price"],
            "qty": 1,
            "prob": out["confidence"],
        }
    else:
        proposal = {
            "label": "unknown",
            "prob": out["confidence"],
            "topk": [
                {"label": out["top1"]["label"], "prob": float(out["top1"]["prob"])},
                {"label": out["top2"]["label"], "prob": float(out["top2"]["prob"])}
            ],
        }

    result_obj = {
        "frame_id": frame_id,
        "added": added,
        "proposal": proposal,
        "threshold": THRESHOLD,
        "ts": ts or now_iso(),
    }
    save_frame(con, session_id, frame_id, path, result_obj)

    new_total = con.execute("SELECT total_amount FROM sessions WHERE id=?", (session_id,)).fetchone()[0]
    resp = result_obj.copy()
    resp["current_total"] = new_total
    return resp


@router.get("/sessions/{session_id}/cart")
def get_cart(session_id: str, con: sqlite3.Connection = Depends(get_db)):
    row = con.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        raise HTTPException(404, "session not found")
    return cart_for(con, session_id)


# 3. CHỐT ĐƠN (Confirm) -> Chuyển sang PENDING_PAYMENT
@router.post("/sessions/{session_id}/confirm")
def confirm_session(session_id: str, con: sqlite3.Connection = Depends(get_db)):
    row = con.execute("SELECT state FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        raise HTTPException(404, "session not found")

    # Chỉ cho phép confirm khi đang ACTIVE
    if row["state"] != "ACTIVE":
        raise HTTPException(409, f"Session cannot confirm in state {row['state']}")

    # Tính chốt tổng tiền lần cuối
    total = con.execute(
        "SELECT COALESCE(SUM(amount),0) FROM session_items WHERE session_id = ?",
        (session_id,),
    ).fetchone()[0]

    # Cập nhật trạng thái sang CHỜ THANH TOÁN
    con.execute(
        "UPDATE sessions SET state='PENDING_PAYMENT', total_amount=? WHERE id=?",
        (total, session_id),
    )

    c = cart_for(con, session_id)
    return {
        "session_id": session_id,
        "state": "PENDING_PAYMENT",
        "message": "Bill confirmed. Waiting for payment.",
        "total": c["total"],
        "items": c["items"]
    }


# 4. THANH TOÁN (Pay - Giả lập) -> Chuyển sang PAID & Tạo Invoice
@router.post("/sessions/{session_id}/pay")
def pay_session(session_id: str, con: sqlite3.Connection = Depends(get_db)):
    row = con.execute("SELECT state, total_amount FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        raise HTTPException(404, "session not found")

    # Chỉ được thanh toán khi đang PENDING_PAYMENT
    if row["state"] != "PENDING_PAYMENT":
        raise HTTPException(409, f"Session is {row['state']}, expected PENDING_PAYMENT to pay")

    inv_id = f"INV-{secrets.token_hex(3).upper()}"
    now = now_iso()
    total = row["total_amount"]

    # Tạo hóa đơn lưu trữ (Bằng chứng đã trả tiền)
    con.execute(
        "INSERT INTO invoices(id, session_id, issued_at, total_amount) VALUES(?, ?, ?, ?)",
        (inv_id, session_id, now, total),
    )

    # Đổi trạng thái sang PAID (Kết thúc thành công)
    con.execute(
        "UPDATE sessions SET state='PAID', closed_at=? WHERE id=?",
        (now, session_id),
    )

    return {
        "session_id": session_id,
        "state": "PAID",
        "invoice_id": inv_id,
        "paid_at": now,
        "amount_paid": total
    }


# 5. HỦY (Cancel) -> Cho phép hủy khi ACTIVE hoặc PENDING_PAYMENT
@router.post("/sessions/{session_id}/cancel")
def cancel_session(session_id: str, con: sqlite3.Connection = Depends(get_db)):
    row = con.execute("SELECT state FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        raise HTTPException(404, "session not found")

    # Logic mới: Chưa trả tiền (PAID) thì vẫn được hủy
    if row["state"] in ["PAID", "CANCELLED"]:
        raise HTTPException(409, f"Cannot cancel. Session is already {row['state']}")

    con.execute("UPDATE sessions SET state='CANCELLED', closed_at=? WHERE id=?", (now_iso(), session_id))
    return {"state": "CANCELLED", "message": "Session cancelled successfully"}