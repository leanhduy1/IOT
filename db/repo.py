import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from core.config import STORAGE_DIR
from core.time import now_iso

def cart_for(con: sqlite3.Connection, session_id: str):
    rows = con.execute(
        """
        SELECT si.id AS item_id, si.product_id, p.name, si.qty, si.unit_price, si.amount
        FROM session_items si
        JOIN products p ON p.id = si.product_id
        WHERE si.session_id = ?
        ORDER BY si.id ASC
        """,
        (session_id,),
    ).fetchall()
    items = [dict(r) for r in rows]
    total = sum(r["amount"] for r in rows)
    return {"items": items, "total": total}

def upsert_item(con: sqlite3.Connection, session_id: str, product_id: int, unit_price: int):
    """
    Thêm 1 sản phẩm vào giỏ: nếu đã có thì tăng qty.
    Dựa vào UNIQUE(session_id, product_id) + UPSERT của SQLite.
    """
    con.execute(
        """
        INSERT INTO session_items(session_id, product_id, qty, unit_price, amount, created_at)
        VALUES(?, ?, 1, ?, ?, ?)
        ON CONFLICT(session_id, product_id)
        DO UPDATE SET
          qty    = qty + 1,
          amount = (qty + 1) * unit_price
        """,
        (session_id, product_id, unit_price, unit_price, now_iso()),
    )
    con.execute(
        "UPDATE sessions SET total_amount = total_amount + ? WHERE id = ?",
        (unit_price, session_id),
    )

def save_frame(con: sqlite3.Connection, session_id: str, frame_id: str, image_path: str, result_obj: dict):
    con.execute(
        """
        INSERT INTO frames(session_id, frame_id, image_path, result_json, created_at)
        VALUES(?, ?, ?, ?, ?)
        """,
        (session_id, frame_id, image_path, json.dumps(result_obj, ensure_ascii=False), now_iso()),
    )

def save_image(device_id: str, frame_id: str, raw: bytes) -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    dest = Path(STORAGE_DIR) / day / device_id / f"{frame_id}.jpg"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return str(dest)
