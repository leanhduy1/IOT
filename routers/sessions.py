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


@router.post("/sessions")
def start_session(payload: SessionStart, con: sqlite3.Connection = Depends(get_db)):
    sid = secrets.token_urlsafe(8)
    con.execute(
        "INSERT INTO sessions(id, device_id, state, created_at) VALUES(?, ?, 'ACTIVE', ?)",
        (sid, payload.device_id, now_iso()),
    )
    return {"session_id": sid, "state": "ACTIVE", "created_at": now_iso()}


@router.post("/sessions/{session_id}/frames")
def ingest_frame(
        session_id: str,
        image: UploadFile = File(...),
        frame_id: str = Form(...),
        device_id: str = Form(...),
        ts: Optional[str] = Form(None),
        con: sqlite3.Connection = Depends(get_db)
):
    row = con.execute("SELECT state FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        raise HTTPException(404, "session not found")
    if row["state"] != "ACTIVE":
        raise HTTPException(409, f"session state is {row['state']}")

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


@router.post("/sessions/{session_id}/confirm")
def confirm_session(session_id: str, con: sqlite3.Connection = Depends(get_db)):
    row = con.execute("SELECT state FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        raise HTTPException(404, "session not found")
    if row["state"] != "ACTIVE":
        raise HTTPException(409, f"session state is {row['state']}")

    total = con.execute(
        "SELECT COALESCE(SUM(amount),0) FROM session_items WHERE session_id = ?",
        (session_id,),
    ).fetchone()[0]

    inv_id = f"INV-{secrets.token_hex(3).upper()}"
    now = now_iso()

    con.execute(
        "INSERT INTO invoices(id, session_id, issued_at, total_amount) VALUES(?, ?, ?, ?)",
        (inv_id, session_id, now, total),
    )
    con.execute(
        "UPDATE sessions SET state='INVOICED', closed_at=?, total_amount=? WHERE id=?",
        (now, total, session_id),
    )

    c = cart_for(con, session_id)
    return {
        "invoice_id": inv_id,
        "session_id": session_id,
        "issued_at": now,
        "items": c["items"],
        "total": c["total"],
        "state": "INVOICED",
    }


@router.post("/sessions/{session_id}/cancel")
def cancel_session(session_id: str, con: sqlite3.Connection = Depends(get_db)):
    row = con.execute("SELECT state FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        raise HTTPException(404, "session not found")
    if row["state"] != "ACTIVE":
        raise HTTPException(409, f"session state is {row['state']}")
    con.execute("UPDATE sessions SET state='CANCELLED', closed_at=? WHERE id=?", (now_iso(), session_id))
    return {"state": "CANCELLED"}